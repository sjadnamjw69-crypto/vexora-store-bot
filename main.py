import os
import re
import sqlite3
import random
import time
import logging

from datetime import datetime, date

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ==================================================
# CONFIG
# ==================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or "0")
CHANNEL_ID = os.getenv("CHANNEL_ID", "@Vexora1Store").strip()
SUPPORT = os.getenv("SUPPORT_USERNAME", "@Vexorini").strip()
CARD_NUMBER = os.getenv("CARD_NUMBER", "").strip()
CARD_NAME = os.getenv("CARD_NAME", "").strip()
DB_NAME = os.getenv("DB_NAME", "vexora.db")

POINT_PRICE = 1000
GROUP_POINT_COOLDOWN = 30
DAILY_POINT_REWARD = 10

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("VEXORA")


# ==================================================
# PRODUCTS
# ==================================================

PRODUCTS = {
    "استارز 50 عدد": (180000, "stars"),
    "استارز 100 عدد": (360000, "stars"),
    "استارز 250 عدد": (900000, "stars"),
    "استارز 500 عدد": (1800000, "stars"),
    "استارز 1000 عدد": (3600000, "stars"),
    "استارز 2500 عدد": (9000000, "stars"),

    "گیفت تدی": (60000, "gift"),
    "گیفت قلب": (60000, "gift"),
    "گیفت رز": (100000, "gift"),
    "گیفت جعبه هدیه": (100000, "gift"),
    "گیفت کیک": (200000, "gift"),
    "گیفت دسته گل": (200000, "gift"),
    "گیفت موشک": (200000, "gift"),
    "گیفت شامپاین": (200000, "gift"),
    "گیفت جام": (400000, "gift"),
    "گیفت الماس": (400000, "gift"),
    "گیفت حلقه": (400000, "gift"),

    "پرمیوم 3 ماهه": (3090000, "premium"),
    "پرمیوم 6 ماهه": (4090000, "premium"),
    "پرمیوم 12 ماهه": (7090000, "premium"),
}

STATUS = {
    "waiting_payment": "در انتظار پرداخت",
    "receipt_sent": "رسید ارسال شده؛ در انتظار بررسی",
    "paid": "پرداخت تأیید شده؛ در انتظار تحویل",
    "delivered": "تحویل شده",
    "rejected": "پرداخت رد شده",
    "cancelled": "لغو شده",
}

MAIN_MENU = ReplyKeyboardMarkup(
    [
        ["⭐ خرید استارز", "🎁 خرید گیفت"],
        ["💎 خرید پرمیوم", "⚙️ خرید کانفیگ"],
        ["💳 شارژ کیف پول", "👛 کیف پول من"],
        ["🔗 دعوت از دوستان", "💰 درآمد من"],
        ["🏆 امتیاز وکسورا", "🛒 سفارش‌های من"],
        ["🔎 پیگیری سفارش", "📖 راهنمای خرید"],
        ["❓ سؤالات متداول", "👨‍💻 پشتیبانی"],
    ],
    resize_keyboard=True,
)


# ==================================================
# DATABASE
# ==================================================

def connect_db():
    con = sqlite3.connect(DB_NAME, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def toman(amount):
    return f"{int(amount):,} تومان"


def admin(user_id):
    return ADMIN_ID != 0 and user_id == ADMIN_ID


def init_db():
    with connect_db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            balance INTEGER DEFAULT 0,
            points INTEGER DEFAULT 0,
            invited_by INTEGER DEFAULT 0,
            created_at TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT DEFAULT '',
            product TEXT NOT NULL,
            price INTEGER NOT NULL,
            target TEXT DEFAULT '',
            status TEXT DEFAULT 'waiting_payment',
            receipt_id TEXT DEFAULT '',
            receipt_type TEXT DEFAULT '',
            created_at TEXT DEFAULT '',
            updated_at TEXT DEFAULT '',
            delivered_at TEXT DEFAULT '',
            commission_done INTEGER DEFAULT 0,
            channel_posted INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS referrals(
            invited_id INTEGER PRIMARY KEY,
            inviter_id INTEGER NOT NULL,
            points_awarded INTEGER DEFAULT 0,
            commission_paid INTEGER DEFAULT 0,
            created_at TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS wallet_transactions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            description TEXT DEFAULT '',
            created_at TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS topups(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            receipt_id TEXT DEFAULT '',
            receipt_type TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS withdrawals(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            destination TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS point_transactions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            description TEXT DEFAULT '',
            created_at TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS point_activity(
            user_id INTEGER PRIMARY KEY,
            last_reward REAL DEFAULT 0,
            last_message TEXT DEFAULT '',
            daily_claim TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS point_requests(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            reward TEXT NOT NULL,
            cost INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT '',
            reviewed_at TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS point_transfers(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            created_at TEXT DEFAULT ''
        );
        """)

        # Migrations for older databases
        order_cols = {
            r["name"] for r in con.execute("PRAGMA table_info(orders)")
        }

        for name, definition in [
            ("receipt_type", "TEXT DEFAULT ''"),
            ("updated_at", "TEXT DEFAULT ''"),
            ("delivered_at", "TEXT DEFAULT ''"),
            ("commission_done", "INTEGER DEFAULT 0"),
            ("channel_posted", "INTEGER DEFAULT 0"),
        ]:
            if name not in order_cols:
                con.execute(
                    f"ALTER TABLE orders ADD COLUMN {name} {definition}"
                )

        user_cols = {
            r["name"] for r in con.execute("PRAGMA table_info(users)")
        }

        for name, definition in [
            ("username", "TEXT DEFAULT ''"),
            ("balance", "INTEGER DEFAULT 0"),
            ("points", "INTEGER DEFAULT 0"),
            ("invited_by", "INTEGER DEFAULT 0"),
            ("created_at", "TEXT DEFAULT ''"),
        ]:
            if name not in user_cols:
                con.execute(
                    f"ALTER TABLE users ADD COLUMN {name} {definition}"
                )

        activity_cols = {
            r["name"]
            for r in con.execute("PRAGMA table_info(point_activity)")
        }

        for name, definition in [
            ("last_reward", "REAL DEFAULT 0"),
            ("last_message", "TEXT DEFAULT ''"),
            ("daily_claim", "TEXT DEFAULT ''"),
        ]:
            if name not in activity_cols:
                con.execute(
                    f"ALTER TABLE point_activity ADD COLUMN {name} {definition}"
                )

        con.commit()


# ==================================================
# USER REGISTRATION
# ==================================================

def register_user(user, referrer=0):
    if not user:
        return

    with connect_db() as con:
        exists = con.execute(
            "SELECT user_id FROM users WHERE user_id=?",
            (user.id,),
        ).fetchone()

        if not exists:
            valid_referrer = 0

            if referrer and referrer != user.id:
                ref = con.execute(
                    "SELECT user_id FROM users WHERE user_id=?",
                    (referrer,),
                ).fetchone()

                if ref:
                    valid_referrer = referrer

            con.execute(
                """
                INSERT INTO users(
                    user_id, username, invited_by, created_at
                ) VALUES(?,?,?,?)
                """,
                (
                    user.id,
                    user.username or "",
                    valid_referrer,
                    now(),
                ),
            )

            if valid_referrer:
                con.execute(
                    """
                    INSERT OR IGNORE INTO referrals(
                        invited_id, inviter_id, created_at
                    ) VALUES(?,?,?)
                    """,
                    (user.id, valid_referrer, now()),
                )
        else:
            con.execute(
                "UPDATE users SET username=? WHERE user_id=?",
                (user.username or "", user.id),
            )

        con.execute(
            "INSERT OR IGNORE INTO point_activity(user_id) VALUES(?)",
            (user.id,),
        )
        con.commit()


def user_balance(user_id):
    with connect_db() as con:
        row = con.execute(
            "SELECT balance FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()
        return row["balance"] if row else 0


def user_points(user_id):
    with connect_db() as con:
        row = con.execute(
            "SELECT points FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()
        return row["points"] if row else 0


def add_points(user_id, amount, description):
    if amount == 0:
        return

    with connect_db() as con:
        user = con.execute(
            "SELECT user_id FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()

        if not user:
            return

        con.execute(
            "UPDATE users SET points=points+? WHERE user_id=?",
            (amount, user_id),
        )
        con.execute(
            """
            INSERT INTO point_transactions(
                user_id, amount, description, created_at
            ) VALUES(?,?,?,?)
            """,
            (user_id, amount, description, now()),
        )
        con.commit()


# ==================================================
# VEXO POINT: GROUP EARNING
# ==================================================

def award_group_points(user_id, message_text):
    current_time = time.time()
    normalized = (message_text or "").strip().lower()

    # Very short messages do not earn points.
    if len(normalized) < 2:
        return 0

    with connect_db() as con:
        con.execute(
            "INSERT OR IGNORE INTO point_activity(user_id) VALUES(?)",
            (user_id,),
        )

        row = con.execute(
            """
            SELECT last_reward, last_message
            FROM point_activity WHERE user_id=?
            """,
            (user_id,),
        ).fetchone()

        # Repeated identical messages do not earn points.
        if row["last_message"] == normalized:
            return 0

        if current_time - float(row["last_reward"] or 0) < GROUP_POINT_COOLDOWN:
            return 0

        points = random.choice([5, 6])

        con.execute(
            "UPDATE users SET points=points+? WHERE user_id=?",
            (points, user_id),
        )

        con.execute(
            """
            INSERT INTO point_transactions(
                user_id, amount, description, created_at
            ) VALUES(?,?,?,?)
            """,
            (user_id, points, "فعالیت در گپ", now()),
        )

        con.execute(
            """
            UPDATE point_activity
            SET last_reward=?, last_message=?
            WHERE user_id=?
            """,
            (current_time, normalized, user_id),
        )

        con.commit()

    return points


# ==================================================
# VEXO POINT: DAILY REWARD
# ==================================================

def claim_daily_points(user_id):
    today = date.today().isoformat()

    with connect_db() as con:
        con.execute(
            "INSERT OR IGNORE INTO point_activity(user_id) VALUES(?)",
            (user_id,),
        )

        row = con.execute(
            "SELECT daily_claim FROM point_activity WHERE user_id=?",
            (user_id,),
        ).fetchone()

        if row and row["daily_claim"] == today:
            return False

        amount = DAILY_POINT_REWARD

        con.execute(
            "UPDATE users SET points=points+? WHERE user_id=?",
            (amount, user_id),
        )

        con.execute(
            """
            INSERT INTO point_transactions(
                user_id, amount, description, created_at
            ) VALUES(?,?,?,?)
            """,
            (user_id, amount, "پاداش روزانه", now()),
        )

        con.execute(
            """
            UPDATE point_activity SET daily_claim=?
            WHERE user_id=?
            """,
            (today, user_id),
        )

        con.commit()

    return amount


# ==================================================
# VEXO POINT: LEADERBOARD AND HISTORY
# ==================================================

def point_leaderboard(user_id):
    with connect_db() as con:
        rows = con.execute(
            """
            SELECT user_id, username, points
            FROM users
            ORDER BY points DESC, user_id ASC
            LIMIT 10
            """
        ).fetchall()

        current = con.execute(
            "SELECT points FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()

        position = 0

        if current:
            position = con.execute(
                """
                SELECT COUNT(*)+1 AS rank
                FROM users
                WHERE points>?
                """,
                (current["points"],),
            ).fetchone()["rank"]

    lines = ["🏆 رتبه‌بندی VEXO POINT", ""]

    for index, row in enumerate(rows, 1):
        name = (
            "@" + row["username"]
            if row["username"]
            else f"کاربر {row['user_id']}"
        )
        lines.append(
            f"{index}. {name} — {row['points']} پوینت"
        )

    lines.append("")
    lines.append(f"رتبه تو: {position if position else 'ثبت نشده'}")
    lines.append(f"موجودی تو: {user_points(user_id)} پوینت")

    return "\n".join(lines)


def point_history(user_id):
    with connect_db() as con:
        rows = con.execute(
            """
            SELECT amount, description, created_at
            FROM point_transactions
            WHERE user_id=?
            ORDER BY id DESC
            LIMIT 10
            """,
            (user_id,),
        ).fetchall()

    if not rows:
        return "هنوز تراکنشی برای پوینت‌های تو ثبت نشده."

    lines = ["📜 تاریخچه VEXO POINT", ""]

    for row in rows:
        sign = "+" if row["amount"] > 0 else ""
        lines.append(
            f"{sign}{row['amount']} | {row['description']}\n"
            f"{row['created_at']}"
        )

    return "\n\n".join(lines)


# ==================================================
# VEXO POINT: TRANSFERS
# ==================================================

def transfer_points(sender_id, receiver_id, amount):
    if sender_id == receiver_id:
        return False, "نمی‌توانی به خودت پوینت انتقال بدهی."

    if amount <= 0:
        return False, "مقدار انتقال باید بیشتر از صفر باشد."

    with connect_db() as con:
        sender = con.execute(
            "SELECT points FROM users WHERE user_id=?",
            (sender_id,),
        ).fetchone()

        receiver = con.execute(
            "SELECT user_id FROM users WHERE user_id=?",
            (receiver_id,),
        ).fetchone()

        if not sender or not receiver:
            return False, "فرستنده یا گیرنده در ربات ثبت نشده است."

        if sender["points"] < amount:
            return False, "موجودی پوینت تو کافی نیست."

        con.execute(
            "UPDATE users SET points=points-? WHERE user_id=?",
            (amount, sender_id),
        )

        con.execute(
            "UPDATE users SET points=points+? WHERE user_id=?",
            (amount, receiver_id),
        )

        con.execute(
            """
            INSERT INTO point_transactions(
                user_id, amount, description, created_at
            ) VALUES(?,?,?,?)
            """,
            (sender_id, -amount, f"انتقال به {receiver_id}", now()),
        )

        con.execute(
            """
            INSERT INTO point_transactions(
                user_id, amount, description, created_at
            ) VALUES(?,?,?,?)
            """,
            (receiver_id, amount, f"دریافت از {sender_id}", now()),
        )

        con.execute(
            """
            INSERT INTO point_transfers(
                sender_id, receiver_id, amount, created_at
            ) VALUES(?,?,?,?)
            """,
            (sender_id, receiver_id, amount, now()),
        )

        con.commit()

    return True, "انتقال با موفقیت انجام شد."


# ==================================================
# VEXO POINT: REWARD REQUESTS
# ==================================================

REWARDS = {
    "stars": {
        "name": "درخواست جایزه استارز",
        "cost": 3,
    },
    "teddy": {
        "name": "درخواست گیفت تدی",
        "cost": 18,
    },
}


def create_point_request(user_id, reward_key):
    reward = REWARDS.get(reward_key)

    if not reward:
        return False, "این جایزه وجود ندارد."

    with connect_db() as con:
        user = con.execute(
            "SELECT points FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()

        if not user:
            return False, "حساب کاربری پیدا نشد."

        pending = con.execute(
            """
            SELECT id FROM point_requests
            WHERE user_id=? AND status='pending'
            """,
            (user_id,),
        ).fetchone()

        if pending:
            return False, "یک درخواست جایزه در انتظار بررسی داری."

        if user["points"] < reward["cost"]:
            return False, (
                f"برای این جایزه به {reward['cost']} پوینت نیاز داری.\n"
                f"موجودی فعلی: {user['points']}"
            )

        cur = con.execute(
            """
            INSERT INTO point_requests(
                user_id, reward, cost, status, created_at
            ) VALUES(?,?,?,?,?)
            """,
            (
                user_id,
                reward_key,
                reward["cost"],
                "pending",
                now(),
            ),
        )

        request_id = cur.lastrowid
        con.commit()

    return True, f"درخواست جایزه #{request_id} برای مدیریت ارسال شد."


async def notify_admin_point_request(context, request_id):
    if not ADMIN_ID:
        return

    with connect_db() as con:
        row = con.execute(
            "SELECT * FROM point_requests WHERE id=?",
            (request_id,),
        ).fetchone()

    if not row:
        return

    reward_name = REWARDS.get(
        row["reward"], {"name": row["reward"]}
    )["name"]

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "تأیید و کسر پوینت",
            callback_data=f"point_approve:{request_id}",
        ),
        InlineKeyboardButton(
            "رد درخواست",
            callback_data=f"point_reject:{request_id}",
        ),
    ]])

    try:
        await context.bot.send_message(
            ADMIN_ID,
            f"درخواست جایزه VEXO POINT\n\n"
            f"شماره درخواست: {request_id}\n"
            f"کاربر: {row['user_id']}\n"
            f"جایزه: {reward_name}\n"
            f"هزینه: {row['cost']} پوینت",
            reply_markup=keyboard,
        )
    except TelegramError:
        log.exception("Could not notify admin about point request")


async def review_point_request(query, context, request_id, approve):
    if not admin(query.from_user.id):
        await query.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    with connect_db() as con:
        row = con.execute(
            "SELECT * FROM point_requests WHERE id=?",
            (request_id,),
        ).fetchone()

        if not row or row["status"] != "pending":
            await query.message.reply_text(
                "این درخواست قبلاً بررسی شده یا وجود ندارد."
            )
            return

        if approve:
            user = con.execute(
                "SELECT points FROM users WHERE user_id=?",
                (row["user_id"],),
            ).fetchone()

            if not user or user["points"] < row["cost"]:
                con.execute(
                    """
                    UPDATE point_requests
                    SET status='rejected', reviewed_at=?
                    WHERE id=?
                    """,
                    (now(), request_id),
                )
                con.commit()

                await context.bot.send_message(
                    row["user_id"],
                    "درخواست جایزه رد شد؛ موجودی پوینت کافی نیست.",
                )
                await query.message.reply_text(
                    "درخواست رد شد؛ موجودی کافی نبود."
                )
                return

            con.execute(
                "UPDATE users SET points=points-? WHERE user_id=?",
                (row["cost"], row["user_id"]),
            )

            con.execute(
                """
                INSERT INTO point_transactions(
                    user_id, amount, description, created_at
                ) VALUES(?,?,?,?)
                """,
                (
                    row["user_id"],
                    -row["cost"],
                    f"مصرف پوینت برای جایزه #{request_id}",
                    now(),
                ),
            )

            con.execute(
                """
                UPDATE point_requests
                SET status='approved', reviewed_at=?
                WHERE id=?
                """,
                (now(), request_id),
            )
            con.commit()

        else:
            con.execute(
                """
                UPDATE point_requests
                SET status='rejected', reviewed_at=?
                WHERE id=?
                """,
                (now(), request_id),
            )
            con.commit()

    if approve:
        await context.bot.send_message(
            row["user_id"],
            "درخواست جایزه‌ات تأیید شد.\n"
            "برای هماهنگی تحویل جایزه با پشتیبانی تماس بگیر.\n"
            f"{SUPPORT}",
        )
        await query.message.reply_text(
            f"درخواست #{request_id} تأیید شد و پوینت کسر شد."
        )
    else:
        await context.bot.send_message(
            row["user_id"],
            "درخواست جایزه‌ات توسط مدیریت رد شد. "
            "پوینت‌هایت کسر نشده‌اند.",
        )
        await query.message.reply_text(
            f"درخواست #{request_id} رد شد."
        )


# ==================================================
# CHANNEL MEMBERSHIP
# ==================================================

async def is_channel_member(bot, user_id):
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ("member", "administrator", "creator")
    except TelegramError:
        return False


async def require_membership(update, context):
    user = update.effective_user

    if not user:
        return False

    if admin(user.id):
        return True

    if await is_channel_member(context.bot, user.id):
        return True

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "عضویت در کانال",
                url="https://t.me/Vexora1Store",
            )
        ],
        [
            InlineKeyboardButton(
                "بررسی عضویت",
                callback_data="check_membership",
            )
        ],
    ])

    await update.effective_message.reply_text(
        "برای استفاده از فروشگاه، ابتدا عضو کانال VEXORA شو.",
        reply_markup=keyboard,
    )
    return False


# ==================================================
# ORDERS
# ==================================================

def create_order(user, product, price, target):
    with connect_db() as con:
        cur = con.execute(
            """
            INSERT INTO orders(
                user_id, username, product, price, target,
                status, created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                user.id,
                user.username or "",
                product,
                price,
                target,
                "waiting_payment",
                now(),
                now(),
            ),
        )
        con.commit()
        return cur.lastrowid


def get_order(order_id):
    with connect_db() as con:
        return con.execute(
            "SELECT * FROM orders WHERE id=?",
            (order_id,),
        ).fetchone()


async def order_payment_instructions(message, order_id):
    order = get_order(order_id)

    if not order:
        await message.reply_text("سفارش پیدا نشد.")
        return

    card = CARD_NUMBER or "شماره کارت هنوز تنظیم نشده است."
    owner = CARD_NAME or "نام صاحب کارت تنظیم نشده است."

    await message.reply_text(
        f"سفارش ثبت شد.\n\n"
        f"شماره سفارش: VX{order_id:06d}\n"
        f"محصول: {order['product']}\n"
        f"مبلغ: {toman(order['price'])}\n\n"
        f"شماره کارت:\n{card}\n"
        f"به نام: {owner}\n\n"
        f"پس از پرداخت، تصویر رسید را همین‌جا ارسال کن.",
        reply_markup=MAIN_MENU,
    )


async def send_admin_order_receipt(context, order_id):
    order = get_order(order_id)

    if not order or not ADMIN_ID:
        return

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "تأیید پرداخت",
            callback_data=f"approve:{order_id}",
        ),
        InlineKeyboardButton(
            "رد پرداخت",
            callback_data=f"reject:{order_id}",
        ),
    ]])

    caption = (
        f"رسید سفارش VX{order_id:06d}\n"
        f"کاربر: {order['user_id']}\n"
        f"محصول: {order['product']}\n"
        f"مبلغ: {toman(order['price'])}\n"
        f"وضعیت: {STATUS.get(order['status'], order['status'])}"
    )

    try:
        if order["receipt_type"] == "photo":
            await context.bot.send_photo(
                ADMIN_ID,
                order["receipt_id"],
                caption=caption,
                reply_markup=keyboard,
            )
        else:
            await context.bot.send_document(
                ADMIN_ID,
                order["receipt_id"],
                caption=caption,
                reply_markup=keyboard,
            )
    except TelegramError:
        log.exception("Failed to send order receipt to admin")


async def buy_product(update, context, category):
    products = [
        (name, price)
        for name, (price, cat) in PRODUCTS.items()
        if cat == category
    ]

    if not products:
        await update.effective_message.reply_text(
            "فعلاً محصولی در این بخش موجود نیست."
        )
        return

    keyboard = [
        [
            InlineKeyboardButton(
                f"{name} — {toman(price)}",
                callback_data=f"buy:{name}",
            )
        ]
        for name, price in products
    ]

    if category == "stars":
        keyboard.append([
            InlineKeyboardButton(
                "تعداد دلخواه استارز",
                callback_data="custom_stars",
            )
        ])

    await update.effective_message.reply_text(
        "محصول موردنظرت را انتخاب کن:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ==================================================
# START / MENU
# ==================================================

async def start(update, context):
    user = update.effective_user
    referrer = 0

    if context.args:
        arg = context.args[0]

        if arg.startswith("ref_"):
            try:
                referrer = int(arg[4:])
            except ValueError:
                pass

    register_user(user, referrer)

    await update.effective_message.reply_text(
        "به فروشگاه VEXORA خوش آمدی.\n\n"
        "استارز، گیفت و پرمیوم تلگرام را از منوی زیر انتخاب کن.\n"
        "برای سیستم امتیاز هم از بخش امتیاز وکسورا استفاده کن.",
        reply_markup=MAIN_MENU,
    )


async def menu(update, context):
    user = update.effective_user

    if not user:
        return

    register_user(user)
    text = (update.effective_message.text or "").strip()

    if text == "⭐ خرید استارز":
        if await require_membership(update, context):
            await buy_product(update, context, "stars")

    elif text == "🎁 خرید گیفت":
        if await require_membership(update, context):
            await buy_product(update, context, "gift")

    elif text == "💎 خرید پرمیوم":
        if await require_membership(update, context):
            await buy_product(update, context, "premium")

    elif text == "⚙️ خرید کانفیگ":
        await update.effective_message.reply_text(
            f"برای خرید کانفیگ با پشتیبانی ارتباط بگیر:\n{SUPPORT}"
        )

    elif text == "👛 کیف پول من":
        await update.effective_message.reply_text(
            f"موجودی کیف پول: {toman(user_balance(user.id))}\n\n"
            "برای افزایش موجودی، «شارژ کیف پول» را بزن."
        )

    elif text == "💳 شارژ کیف پول":
        context.user_data["state"] = "topup_amount"
        await update.effective_message.reply_text(
            "مبلغ شارژ را به تومان وارد کن.\nمثال: 200000"
        )

    elif text == "🔗 دعوت از دوستان":
        me = await context.bot.get_me()
        link = f"https://t.me/{me.username}?start=ref_{user.id}"

        with connect_db() as con:
            count = con.execute(
                "SELECT COUNT(*) AS n FROM referrals WHERE inviter_id=?",
                (user.id,),
            ).fetchone()["n"]

        await update.effective_message.reply_text(
            f"لینک دعوت اختصاصی تو:\n{link}\n\n"
            f"دعوت‌شده‌ها: {count}\n"
            "پورسانت مالی پس از تحویل اولین سفارش معتبر دعوت‌شده محاسبه می‌شود."
        )

    elif text == "💰 درآمد من":
        with connect_db() as con:
            row = con.execute(
                """
                SELECT COALESCE(SUM(amount),0) AS total
                FROM wallet_transactions
                WHERE user_id=? AND description LIKE '%پورسانت%'
                """,
                (user.id,),
            ).fetchone()

        await update.effective_message.reply_text(
            f"مجموع پورسانت ثبت‌شده: {toman(row['total'])}\n"
            f"موجودی فعلی: {toman(user_balance(user.id))}"
        )

    elif text == "🏆 امتیاز وکسورا":
        await update.effective_message.reply_text(
            f"🪙 VEXO POINT\n\n"
            f"موجودی: {user_points(user.id)} پوینت\n\n"
            "۵ یا ۶ پوینت: فعالیت معتبر در گپ با فاصله ۳۰ ثانیه\n"
            f"{DAILY_POINT_REWARD} پوینت: پاداش روزانه\n"
            "۳ پوینت: درخواست جایزه استارز\n"
            "۱۸ پوینت: درخواست گیفت تدی\n"
            f"قیمت خرید هر پوینت: {toman(POINT_PRICE)}\n\n"
            "دستورها:\n"
            "پوینت من\n"
            "لیدربورد\n"
            "پوینت روزانه\n"
            "فروشگاه پوینت\n"
            "تاریخچه پوینت"
        )

    elif text == "🛒 سفارش‌های من":
        with connect_db() as con:
            orders = con.execute(
                """
                SELECT * FROM orders
                WHERE user_id=?
                ORDER BY id DESC LIMIT 10
                """,
                (user.id,),
            ).fetchall()

        if not orders:
            await update.effective_message.reply_text(
                "هنوز سفارشی ثبت نکرده‌ای."
            )
            return

        lines = ["آخرین سفارش‌های تو:\n"]

        for order in orders:
            lines.append(
                f"VX{order['id']:06d} | {order['product']}\n"
                f"مبلغ: {toman(order['price'])}\n"
                f"وضعیت: {STATUS.get(order['status'], order['status'])}\n"
            )

        await update.effective_message.reply_text("\n".join(lines))

    elif text == "🔎 پیگیری سفارش":
        context.user_data["state"] = "track_order"
        await update.effective_message.reply_text(
            "شماره سفارش را وارد کن؛ مثال: VX000001"
        )

    elif text == "📖 راهنمای خرید":
        await update.effective_message.reply_text(
            "راهنمای خرید VEXORA\n\n"
            "۱. محصول را انتخاب کن.\n"
            "۲. اطلاعات تحویل را وارد کن.\n"
            "۳. مبلغ را پرداخت کن.\n"
            "۴. رسید را ارسال کن.\n"
            "۵. منتظر تأیید مدیریت بمان.\n"
            "۶. پس از تحویل واقعی، سفارش تکمیل می‌شود."
        )

    elif text == "❓ سؤالات متداول":
        await update.effective_message.reply_text(
            "سؤالات متداول\n\n"
            "• پیگیری سفارش: بخش پیگیری سفارش\n"
            "• رسید بررسی نشده: با پشتیبانی تماس بگیر.\n"
            "• پرداخت تأیید شده ولی محصول نرسیده: در انتظار تحویل است.\n"
            "• کانفیگ: با پشتیبانی تماس بگیر."
        )

    elif text == "👨‍💻 پشتیبانی":
        await update.effective_message.reply_text(
            f"پشتیبانی VEXORA:\n{SUPPORT}"
        )


# ==================================================
# VEXO POINT: PRIVATE COMMANDS
# ==================================================

async def handle_point_text(update, context, text):
    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return False

    normalized = re.sub(r"\s+", " ", text.strip().lower())

    if normalized in (
        "پوینت",
        "پوینت من",
        "موجودی",
        "موجودی من",
        "موجودی پوینت",
        "پوینتم چقدره؟",
        "چند پوینت دارم؟",
    ):
        await message.reply_text(
            f"🪙 کیف پول VEXO POINT\n\n"
            f"موجودی تو: {user_points(user.id)} پوینت"
        )
        return True

    if normalized in (
        "رتبه من",
        "رتبه",
        "لیدربورد",
        "برترین ها",
        "برترین‌های پوینت",
    ):
        await message.reply_text(point_leaderboard(user.id))
        return True

    if normalized in ("پوینت روزانه", "پاداش روزانه"):
        result = claim_daily_points(user.id)

        if result is False:
            await message.reply_text(
                "پاداش امروزت را قبلاً دریافت کرده‌ای."
            )
        else:
            await message.reply_text(
                f"🎁 {result} پوینت دریافت کردی.\n"
                f"موجودی جدید: {user_points(user.id)}"
            )

        return True

    if normalized in ("فروشگاه پوینت", "فروشگاه امتیاز"):
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "درخواست جایزه استارز — ۳ پوینت",
                    callback_data="point_reward:stars",
                )
            ],
            [
                InlineKeyboardButton(
                    "درخواست گیفت تدی — ۱۸ پوینت",
                    callback_data="point_reward:teddy",
                )
            ],
        ])

        await message.reply_text(
            "🛍 فروشگاه VEXO POINT\n\n"
            "۳ پوینت: درخواست جایزه استارز\n"
            "۱۸ پوینت: درخواست گیفت تدی\n\n"
            "درخواست‌ها باید توسط مدیریت بررسی شوند.",
            reply_markup=keyboard,
        )
        return True

    if normalized in ("ماموریت ها", "ماموریت‌ها", "ماموریت"):
        await message.reply_text(
            "🎯 مأموریت‌های VEXO POINT\n\n"
            "۱. فعالیت معتبر در گپ: ۵ یا ۶ پوینت\n"
            "۲. دریافت پاداش روزانه: ۱۰ پوینت\n"
            "۳. دعوت دوستان: لینک اختصاصی خودت را از منوی ربات بگیر.\n\n"
            "امتیاز دعوت در این نسخه خودکار نیست."
        )
        return True

    if normalized in ("راهنمای پوینت", "راهنمای امتیاز"):
        await message.reply_text(
            "راهنمای VEXO POINT\n\n"
            "• پوینت من: مشاهده موجودی\n"
            "• لیدربورد: رتبه‌بندی\n"
            "• پوینت روزانه: دریافت پاداش روزانه\n"
            "• فروشگاه پوینت: درخواست جایزه\n"
            "• تاریخچه پوینت: آخرین تراکنش‌ها\n\n"
            "برای انتقال پوینت، به پیام گیرنده ریپلای کن و بنویس:\n"
            "انتقال پوینت 10"
        )
        return True

    if normalized in ("تاریخچه پوینت", "تراکنش‌های پوینت"):
        await message.reply_text(point_history(user.id))
        return True

    # Transfer points by replying to the recipient's message.
    match = re.fullmatch(
        r"(?:انتقال پوینت|انتقال)\s+(\d+)(?:\s+پوینت)?",
        normalized,
    )

    if match:
        if not message.reply_to_message:
            await message.reply_text(
                "برای انتقال پوینت، به پیام گیرنده ریپلای کن.\n"
                "مثال: انتقال پوینت 10"
            )
            return True

        receiver = message.reply_to_message.from_user

        if not receiver or receiver.is_bot:
            await message.reply_text("گیرنده معتبر نیست.")
            return True

        register_user(receiver)

        success, result = transfer_points(
            user.id,
            receiver.id,
            int(match.group(1)),
        )

        await message.reply_text(
            f"{'✅' if success else '❌'} {result}"
        )

        if success:
            try:
                await context.bot.send_message(
                    receiver.id,
                    f"🪙 {int(match.group(1))} پوینت از طرف "
                    f"{user.first_name} دریافت کردی.",
                )
            except TelegramError:
                pass

        return True

    if normalized in (
        "درخواست جایزه استارز",
        "جایزه استارز",
    ):
        success, result = create_point_request(user.id, "stars")
        await message.reply_text(
            f"{'✅' if success else '❌'} {result}"
        )

        if success:
            with connect_db() as con:
                row = con.execute(
                    """
                    SELECT MAX(id) AS id FROM point_requests
                    WHERE user_id=?
                    """,
                    (user.id,),
                ).fetchone()

            if row and row["id"]:
                await notify_admin_point_request(
                    context,
                    row["id"],
                )

        return True

    if normalized in (
        "درخواست گیفت تدی",
        "جایزه تدی",
    ):
        success, result = create_point_request(user.id, "teddy")
        await message.reply_text(
            f"{'✅' if success else '❌'} {result}"
        )

        if success:
            with connect_db() as con:
                row = con.execute(
                    """
                    SELECT MAX(id) AS id FROM point_requests
                    WHERE user_id=?
                    """,
                    (user.id,),
                ).fetchone()

            if row and row["id"]:
                await notify_admin_point_request(
                    context,
                    row["id"],
                )

        return True

    return False


# ==================================================
# CALLBACKS
# ==================================================

async def callbacks(update, context):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    register_user(user)

    data = query.data or ""

    if data == "check_membership":
        if await is_channel_member(context.bot, user.id):
            await query.edit_message_text(
                "عضویتت تأیید شد. حالا از منوی ربات استفاده کن."
            )
        else:
            await query.edit_message_text(
                "هنوز عضو کانال نشده‌ای. ابتدا عضو شو و دوباره امتحان کن."
            )
        return

    if data.startswith("point_reward:"):
        reward_key = data.split(":", 1)[1]
        success, result = create_point_request(user.id, reward_key)

        try:
            await query.message.reply_text(
                f"{'✅' if success else '❌'} {result}"
            )
        except TelegramError:
            pass

        if success:
            with connect_db() as con:
                row = con.execute(
                    """
                    SELECT MAX(id) AS id FROM point_requests
                    WHERE user_id=?
                    """,
                    (user.id,),
                ).fetchone()

            if row and row["id"]:
                await notify_admin_point_request(
                    context,
                    row["id"],
                )
        return

    if data.startswith("point_approve:"):
        try:
            request_id = int(data.split(":")[1])
        except ValueError:
            return

        await review_point_request(
            query,
            context,
            request_id,
            True,
        )
        return

    if data.startswith("point_reject:"):
        try:
            request_id = int(data.split(":")[1])
        except ValueError:
            return

        await review_point_request(
            query,
            context,
            request_id,
            False,
        )
        return

    if data == "custom_stars":
        context.user_data["state"] = "custom_stars"
        await query.message.reply_text(
            "تعداد استارز را وارد کن.\n"
            "حداقل ۵۰ و حداکثر ۲۵۰۰ عدد.\n"
            "قیمت هر استارز در این نسخه ۳٬۶۰۰ تومان است."
        )
        return

    if data.startswith("buy:"):
        if (
            not await is_channel_member(context.bot, user.id)
            and not admin(user.id)
        ):
            await query.message.reply_text(
                "برای خرید ابتدا عضو کانال شو:\n"
                "https://t.me/Vexora1Store"
            )
            return

        product = data[4:]
        item = PRODUCTS.get(product)

        if not item:
            await query.message.reply_text("این محصول پیدا نشد.")
            return

        context.user_data["pending_product"] = product
        context.user_data["pending_price"] = item[0]
        context.user_data["state"] = "order_target"

        if product.startswith("استارز"):
            prompt = "یوزرنیم تلگرام یا اطلاعات لازم برای تحویل استارز را وارد کن."
        elif product.startswith("گیفت"):
            prompt = "یوزرنیم گیرنده گیفت را وارد کن."
        else:
            prompt = "یوزرنیم تلگرام و اطلاعات لازم برای پرمیوم را وارد کن."

        await query.message.reply_text(
            prompt + "\nبرای لغو سفارش /cancel را بفرست."
        )
        return

    if data.startswith("approve:"):
        if not admin(user.id):
            await query.answer("اجازه دسترسی نداری.", show_alert=True)
            return

        order_id = int(data.split(":")[1])

        with connect_db() as con:
            order = con.execute(
                "SELECT * FROM orders WHERE id=?",
                (order_id,),
            ).fetchone()

            if not order or order["status"] != "receipt_sent":
                await query.message.reply_text(
                    "این سفارش وجود ندارد یا قبلاً بررسی شده است."
                )
                return

            con.execute(
                """
                UPDATE orders SET status='paid', updated_at=?
                WHERE id=? AND status='receipt_sent'
                """,
                (now(), order_id),
            )
            con.commit()

        await context.bot.send_message(
            order["user_id"],
            f"پرداخت سفارش VX{order_id:06d} تأیید شد.\n"
            "سفارش در انتظار تحویل است.",
        )

        await query.message.reply_text(
            f"پرداخت تأیید شد. پس از تحویل واقعی:\n"
            f"/delivered {order_id}"
        )
        return

    if data.startswith("reject:"):
        if not admin(user.id):
            await query.answer("اجازه دسترسی نداری.", show_alert=True)
            return

        order_id = int(data.split(":")[1])

        with connect_db() as con:
            order = con.execute(
                "SELECT * FROM orders WHERE id=?",
                (order_id,),
            ).fetchone()

            if not order or order["status"] != "receipt_sent":
                await query.message.reply_text(
                    "این سفارش وجود ندارد یا قبلاً بررسی شده است."
                )
                return

            con.execute(
                """
                UPDATE orders SET status='rejected', updated_at=?
                WHERE id=? AND status='receipt_sent'
                """,
                (now(), order_id),
            )
            con.commit()

        await context.bot.send_message(
            order["user_id"],
            f"رسید سفارش VX{order_id:06d} رد شد.\n"
            f"پشتیبانی: {SUPPORT}",
        )
        await query.message.reply_text("رسید رد شد.")
        return

    if data.startswith("topup_approve:"):
        if not admin(user.id):
            return

        topup_id = int(data.split(":")[1])

        with connect_db() as con:
            topup = con.execute(
                "SELECT * FROM topups WHERE id=?",
                (topup_id,),
            ).fetchone()

            if not topup or topup["status"] != "pending":
                await query.message.reply_text(
                    "این درخواست قبلاً بررسی شده است."
                )
                return

            con.execute(
                "UPDATE topups SET status='approved' WHERE id=?",
                (topup_id,),
            )
            con.execute(
                "UPDATE users SET balance=balance+? WHERE user_id=?",
                (topup["amount"], topup["user_id"]),
            )
            con.execute(
                """
                INSERT INTO wallet_transactions(
                    user_id, amount, description, created_at
                ) VALUES(?,?,?,?)
                """,
                (
                    topup["user_id"],
                    topup["amount"],
                    f"شارژ کیف پول #{topup_id}",
                    now(),
                ),
            )
            con.commit()

        await context.bot.send_message(
            topup["user_id"],
            f"شارژ کیف پول به مبلغ {toman(topup['amount'])} تأیید شد.",
        )
        await query.message.reply_text("شارژ تأیید شد.")
        return


# ==================================================
# TEXT INPUTS
# ==================================================

async def text_input(update, context):
    user = update.effective_user
    message = update.effective_message

    if not user or not message or not message.text:
        return

    register_user(user)
    text = message.text.strip()
    state = context.user_data.get("state")

    # Process point commands before normal menu fallback.
    if not state:
        handled = await handle_point_text(update, context, text)

        if handled:
            return

    if state == "order_target":
        product = context.user_data.get("pending_product")
        price = context.user_data.get("pending_price")

        if product is None or price is None:
            context.user_data.pop("state", None)
            await message.reply_text(
                "اطلاعات سفارش منقضی شده؛ دوباره محصول را انتخاب کن.",
                reply_markup=MAIN_MENU,
            )
            return

        if len(text) < 3 or len(text) > 200:
            await message.reply_text("اطلاعات واردشده معتبر نیست.")
            return

        order_id = create_order(user, product, price, text)

        context.user_data.pop("pending_product", None)
        context.user_data.pop("pending_price", None)
        context.user_data.pop("state", None)

        await order_payment_instructions(message, order_id)
        return

    if state == "custom_stars":
        try:
            quantity = int(text)
        except ValueError:
            await message.reply_text("تعداد را فقط به عدد وارد کن.")
            return

        if quantity < 50 or quantity > 2500:
            await message.reply_text(
                "تعداد باید بین ۵۰ تا ۲۵۰۰ استارز باشد."
            )
            return

        price = quantity * 3600
        product = f"استارز سفارشی {quantity} عدد"

        context.user_data["pending_product"] = product
        context.user_data["pending_price"] = price
        context.user_data["state"] = "order_target"

        await message.reply_text(
            f"تعداد: {quantity}\n"
            f"مبلغ: {toman(price)}\n\n"
            "یوزرنیم تلگرام یا اطلاعات لازم برای تحویل را وارد کن."
        )
        return

    if state == "topup_amount":
        try:
            amount = int(text.replace(",", ""))
        except ValueError:
            await message.reply_text("مبلغ را فقط به عدد وارد کن.")
            return

        if amount < 10000 or amount > 100000000:
            await message.reply_text(
                "مبلغ شارژ باید بین ۱۰٬۰۰۰ تا ۱۰۰٬۰۰۰٬۰۰۰ تومان باشد."
            )
            return

        context.user_data["topup_amount"] = amount
        context.user_data["state"] = "topup_receipt"

        card = CARD_NUMBER or "شماره کارت تنظیم نشده است."
        owner = CARD_NAME or "نام صاحب کارت تنظیم نشده است."

        await message.reply_text(
            f"مبلغ شارژ: {toman(amount)}\n"
            f"شماره کارت: {card}\n"
            f"به نام: {owner}\n\n"
            "پس از پرداخت، تصویر رسید را ارسال کن."
        )
        return

    if state == "track_order":
        match = re.search(r"(\d+)", text)

        if not match:
            await message.reply_text("شماره سفارش معتبر نیست.")
            return

        order_id = int(match.group(1))

        with connect_db() as con:
            order = con.execute(
                "SELECT * FROM orders WHERE id=? AND user_id=?",
                (order_id, user.id),
            ).fetchone()

        context.user_data.pop("state", None)

        if not order:
            await message.reply_text(
                "سفارشی با این شماره برای حساب تو پیدا نشد."
            )
            return

        await message.reply_text(
            f"شماره سفارش: VX{order['id']:06d}\n"
            f"محصول: {order['product']}\n"
            f"مبلغ: {toman(order['price'])}\n"
            f"وضعیت: {STATUS.get(order['status'], order['status'])}\n"
            f"تاریخ ثبت: {order['created_at']}"
        )
        return

    await menu(update, context)


# ==================================================
# RECEIPTS
# ==================================================

async def receipt_handler(update, context):
    user = update.effective_user
    message = update.effective_message

    if not user or not message:
        return

    register_user(user)
    state = context.user_data.get("state")

    if state == "topup_receipt":
        amount = context.user_data.get("topup_amount")

        if not amount:
            context.user_data.pop("state", None)
            await message.reply_text(
                "درخواست شارژ منقضی شده؛ دوباره شروع کن."
            )
            return

        if message.photo:
            receipt_id = message.photo[-1].file_id
            receipt_type = "photo"
        elif message.document:
            receipt_id = message.document.file_id
            receipt_type = "document"
        else:
            await message.reply_text(
                "لطفاً تصویر رسید یا فایل آن را بفرست."
            )
            return

        with connect_db() as con:
            cur = con.execute(
                """
                INSERT INTO topups(
                    user_id, amount, receipt_id, receipt_type,
                    status, created_at
                ) VALUES(?,?,?,?,?,?)
                """,
                (
                    user.id,
                    amount,
                    receipt_id,
                    receipt_type,
                    "pending",
                    now(),
                ),
            )
            topup_id = cur.lastrowid
            con.commit()

        context.user_data.pop("topup_amount", None)
        context.user_data.pop("state", None)

        await message.reply_text(
            f"رسید شارژ #{topup_id} ارسال شد و منتظر بررسی مدیریت است."
        )

        if ADMIN_ID:
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "تأیید شارژ",
                    callback_data=f"topup_approve:{topup_id}",
                )
            ]])

            caption = (
                f"درخواست شارژ #{topup_id}\n"
                f"کاربر: {user.id}\n"
                f"مبلغ: {toman(amount)}"
            )

            try:
                if receipt_type == "photo":
                    await context.bot.send_photo(
                        ADMIN_ID,
                        receipt_id,
                        caption=caption,
                        reply_markup=keyboard,
                    )
                else:
                    await context.bot.send_document(
                        ADMIN_ID,
                        receipt_id,
                        caption=caption,
                        reply_markup=keyboard,
                    )
            except TelegramError:
                log.exception("Could not forward top-up receipt")

        return

    if not message.photo and not message.document:
        return

    with connect_db() as con:
        order = con.execute(
            """
            SELECT * FROM orders
            WHERE user_id=? AND status='waiting_payment'
            ORDER BY id DESC LIMIT 1
            """,
            (user.id,),
        ).fetchone()

        if not order:
            await message.reply_text(
                "سفارش در انتظار پرداخت پیدا نشد. "
                "از بخش سفارش‌های من وضعیت را بررسی کن."
            )
            return

        if message.photo:
            receipt_id = message.photo[-1].file_id
            receipt_type = "photo"
        else:
            receipt_id = message.document.file_id
            receipt_type = "document"

        con.execute(
            """
            UPDATE orders
            SET status='receipt_sent', receipt_id=?,
                receipt_type=?, updated_at=?
            WHERE id=? AND status='waiting_payment'
            """,
            (receipt_id, receipt_type, now(), order["id"]),
        )
        con.commit()

    context.user_data.pop("state", None)

    await message.reply_text(
        f"رسید سفارش VX{order['id']:06d} دریافت شد.\n"
        "پس از بررسی مدیریت، نتیجه اعلام می‌شود.",
        reply_markup=MAIN_MENU,
    )

    await send_admin_order_receipt(context, order["id"])


# ==================================================
# ADMIN PANEL
# ==================================================

async def admin_panel(update, context):
    if not admin(update.effective_user.id):
        await update.effective_message.reply_text("اجازه دسترسی نداری.")
        return

    with connect_db() as con:
        users = con.execute(
            "SELECT COUNT(*) AS n FROM users"
        ).fetchone()["n"]

        orders = con.execute(
            "SELECT COUNT(*) AS n FROM orders"
        ).fetchone()["n"]

        pending = con.execute(
            "SELECT COUNT(*) AS n FROM orders WHERE status='receipt_sent'"
        ).fetchone()["n"]

        revenue = con.execute(
            """
            SELECT COALESCE(SUM(price),0) AS n
            FROM orders WHERE status='delivered'
            """
        ).fetchone()["n"]

        pending_points = con.execute(
            """
            SELECT COUNT(*) AS n FROM point_requests
            WHERE status='pending'
            """
        ).fetchone()["n"]

    await update.effective_message.reply_text(
        "پنل مدیریت VEXORA\n\n"
        f"کاربران: {users}\n"
        f"کل سفارش‌ها: {orders}\n"
        f"رسیدهای منتظر بررسی: {pending}\n"
        f"درخواست‌های جایزه منتظر بررسی: {pending_points}\n"
        f"مجموع سفارش‌های تحویل‌شده: {toman(revenue)}\n\n"
        "دستورات مدیریت:\n"
        "/orders\n"
        "/approve ID\n"
        "/reject ID\n"
        "/delivered ID\n"
        "/setprice نام محصول|مبلغ\n"
        "/broadcast متن\n"
        "/addpoints USER_ID AMOUNT\n"
        "/removepoints USER_ID AMOUNT\n"
        "/setpoints USER_ID AMOUNT\n"
        "/pointrequests"
    )


async def admin_orders(update, context):
    if not admin(update.effective_user.id):
        return

    with connect_db() as con:
        orders = con.execute(
            "SELECT * FROM orders ORDER BY id DESC LIMIT 20"
        ).fetchall()

    if not orders:
        await update.effective_message.reply_text(
            "هنوز سفارشی ثبت نشده است."
        )
        return

    lines = []

    for order in orders:
        lines.append(
            f"VX{order['id']:06d} | {order['product']}\n"
            f"کاربر: {order['user_id']} | {toman(order['price'])}\n"
            f"وضعیت: {STATUS.get(order['status'], order['status'])}\n"
        )

    await update.effective_message.reply_text("\n".join(lines))


async def admin_approve_command(update, context):
    if not admin(update.effective_user.id):
        return

    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text("مثال: /approve 12")
        return

    order_id = int(context.args[0])

    with connect_db() as con:
        order = con.execute(
            "SELECT * FROM orders WHERE id=?",
            (order_id,),
        ).fetchone()

        if not order or order["status"] != "receipt_sent":
            await update.effective_message.reply_text(
                "سفارش پیدا نشد یا رسید قبلاً بررسی شده است."
            )
            return

        con.execute(
            """
            UPDATE orders SET status='paid', updated_at=?
            WHERE id=? AND status='receipt_sent'
            """,
            (now(), order_id),
        )
        con.commit()

    await context.bot.send_message(
        order["user_id"],
        f"پرداخت سفارش VX{order_id:06d} تأیید شد؛ "
        "سفارش در انتظار تحویل است.",
    )

    await update.effective_message.reply_text(
        f"پرداخت تأیید شد. پس از تحویل واقعی:\n"
        f"/delivered {order_id}"
    )


async def admin_reject_command(update, context):
    if not admin(update.effective_user.id):
        return

    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text("مثال: /reject 12")
        return

    order_id = int(context.args[0])

    with connect_db() as con:
        order = con.execute(
            "SELECT * FROM orders WHERE id=?",
            (order_id,),
        ).fetchone()

        if not order or order["status"] != "receipt_sent":
            await update.effective_message.reply_text(
                "سفارش پیدا نشد یا رسید قبلاً بررسی شده است."
            )
            return

        con.execute(
            """
            UPDATE orders SET status='rejected', updated_at=?
            WHERE id=? AND status='receipt_sent'
            """,
            (now(), order_id),
        )
        con.commit()

    await context.bot.send_message(
        order["user_id"],
        f"رسید سفارش VX{order_id:06d} رد شد.\n"
        f"پشتیبانی: {SUPPORT}",
    )

    await update.effective_message.reply_text("رسید رد شد.")


async def mark_delivered(update, context):
    if not admin(update.effective_user.id):
        return

    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text("مثال: /delivered 12")
        return

    order_id = int(context.args[0])

    with connect_db() as con:
        order = con.execute(
            "SELECT * FROM orders WHERE id=?",
            (order_id,),
        ).fetchone()

        if not order:
            await update.effective_message.reply_text("سفارش پیدا نشد.")
            return

        if order["status"] == "delivered":
            await update.effective_message.reply_text(
                "این سفارش قبلاً تحویل‌شده ثبت شده است."
            )
            return

        if order["status"] != "paid":
            await update.effective_message.reply_text(
                "ابتدا باید پرداخت سفارش تأیید شده باشد."
            )
            return

        con.execute(
            """
            UPDATE orders
            SET status='delivered', updated_at=?, delivered_at=?
            WHERE id=? AND status='paid'
            """,
            (now(), now(), order_id),
        )

        referral = con.execute(
            "SELECT * FROM referrals WHERE invited_id=?",
            (order["user_id"],),
        ).fetchone()

        if referral and not referral["commission_paid"]:
            inviter_id = referral["inviter_id"]
            commission = int(order["price"] * 0.50)

            con.execute(
                "UPDATE users SET balance=balance+? WHERE user_id=?",
                (commission, inviter_id),
            )

            con.execute(
                """
                INSERT INTO wallet_transactions(
                    user_id, amount, description, created_at
                ) VALUES(?,?,?,?)
                """,
                (
                    inviter_id,
                    commission,
                    f"پورسانت سفارش VX{order_id:06d}",
                    now(),
                ),
            )

            con.execute(
                """
                UPDATE referrals SET commission_paid=1
                WHERE invited_id=?
                """,
                (order["user_id"],),
            )

        con.commit()

    await context.bot.send_message(
        order["user_id"],
        f"سفارش VX{order_id:06d} تحویل‌شده ثبت شد. ممنون از خریدت.",
    )

    if not order["channel_posted"]:
        try:
            await context.bot.send_message(
                CHANNEL_ID,
                "VEXORA | سفارش تکمیل شد\n\n"
                f"شماره سفارش: VX{order_id:06d}\n"
                f"محصول: {order['product']}\n"
                "وضعیت: تحویل‌شده",
            )

            with connect_db() as con:
                con.execute(
                    "UPDATE orders SET channel_posted=1 WHERE id=?",
                    (order_id,),
                )
                con.commit()

        except TelegramError:
            log.exception("Could not publish completion to channel")

    await update.effective_message.reply_text(
        f"سفارش VX{order_id:06d} تحویل‌شده ثبت شد."
    )


async def set_price(update, context):
    if not admin(update.effective_user.id):
        return

    raw = update.effective_message.text.partition(" ")[2]

    if "|" not in raw:
        await update.effective_message.reply_text(
            "فرمت:\n/setprice نام محصول|مبلغ\n"
            "مثال:\n/setprice گیفت تدی|70000"
        )
        return

    name, price_text = raw.rsplit("|", 1)

    try:
        price = int(price_text.strip())
    except ValueError:
        await update.effective_message.reply_text("مبلغ معتبر نیست.")
        return

    name = name.strip()

    if name not in PRODUCTS or price < 0:
        await update.effective_message.reply_text(
            "محصول پیدا نشد یا قیمت نامعتبر است."
        )
        return

    PRODUCTS[name] = (price, PRODUCTS[name][1])

    await update.effective_message.reply_text(
        f"قیمت {name} به {toman(price)} تغییر کرد.\n"
        "توجه: تغییر قیمت در این نسخه پس از راه‌اندازی مجدد ذخیره نمی‌شود."
    )


async def broadcast(update, context):
    if not admin(update.effective_user.id):
        return

    text = update.effective_message.text.partition(" ")[2].strip()

    if not text:
        await update.effective_message.reply_text(
            "مثال: /broadcast سلام"
        )
        return

    with connect_db() as con:
        users = con.execute("SELECT user_id FROM users").fetchall()

    sent = 0
    failed = 0

    for row in users:
        try:
            await context.bot.send_message(row["user_id"], text)
            sent += 1
        except TelegramError:
            failed += 1

    await update.effective_message.reply_text(
        f"ارسال تمام شد.\nموفق: {sent}\nناموفق: {failed}"
    )


# ==================================================
# ADMIN: POINT CONTROLS
# ==================================================

async def admin_add_points(update, context):
    if not admin(update.effective_user.id):
        return

    if len(context.args) != 2:
        await update.effective_message.reply_text(
            "فرمت:\n/addpoints USER_ID AMOUNT"
        )
        return

    try:
        user_id = int(context.args[0])
        amount = int(context.args[1])
    except ValueError:
        await update.effective_message.reply_text(
            "شناسه کاربر و مقدار باید عدد باشند."
        )
        return

    if amount <= 0:
        await update.effective_message.reply_text(
            "مقدار باید بیشتر از صفر باشد."
        )
        return

    with connect_db() as con:
        target = con.execute(
            "SELECT user_id FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()

    if not target:
        await update.effective_message.reply_text(
            "کاربر در دیتابیس ربات ثبت نشده است."
        )
        return

    add_points(user_id, amount, "افزایش توسط مدیریت")

    await update.effective_message.reply_text(
        f"{amount} پوینت به کاربر {user_id} اضافه شد."
    )

    try:
        await context.bot.send_message(
            user_id,
            f"مدیریت {amount} پوینت به حسابت اضافه کرد."
        )
    except TelegramError:
        pass


async def admin_remove_points(update, context):
    if not admin(update.effective_user.id):
        return

    if len(context.args) != 2:
        await update.effective_message.reply_text(
            "فرمت:\n/removepoints USER_ID AMOUNT"
        )
        return

    try:
        user_id = int(context.args[0])
        amount = int(context.args[1])
    except ValueError:
        await update.effective_message.reply_text(
            "شناسه کاربر و مقدار باید عدد باشند."
        )
        return

    if amount <= 0:
        await update.effective_message.reply_text(
            "مقدار باید بیشتر از صفر باشد."
        )
        return

    with connect_db() as con:
        target = con.execute(
            "SELECT points FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()

        if not target:
            await update.effective_message.reply_text(
                "کاربر پیدا نشد."
            )
            return

        actual = min(amount, target["points"])

        if actual <= 0:
            await update.effective_message.reply_text(
                "این کاربر پوینتی برای کسر ندارد."
            )
            return

        con.execute(
            "UPDATE users SET points=points-? WHERE user_id=?",
            (actual, user_id),
        )

        con.execute(
            """
            INSERT INTO point_transactions(
                user_id, amount, description, created_at
            ) VALUES(?,?,?,?)
            """,
            (user_id, -actual, "کسر توسط مدیریت", now()),
        )
        con.commit()

    await update.effective_message.reply_text(
        f"{actual} پوینت از کاربر {user_id} کسر شد."
    )


async def admin_set_points(update, context):
    if not admin(update.effective_user.id):
        return

    if len(context.args) != 2:
        await update.effective_message.reply_text(
            "فرمت:\n/setpoints USER_ID AMOUNT"
        )
        return

    try:
        user_id = int(context.args[0])
        amount = int(context.args[1])
    except ValueError:
        await update.effective_message.reply_text(
            "شناسه و مقدار باید عدد باشند."
        )
        return

    if amount < 0:
        await update.effective_message.reply_text(
            "مقدار نمی‌تواند منفی باشد."
        )
        return

    with connect_db() as con:
        target = con.execute(
            "SELECT points FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()

        if not target:
            await update.effective_message.reply_text(
                "کاربر پیدا نشد."
            )
            return

        difference = amount - target["points"]

        con.execute(
            "UPDATE users SET points=? WHERE user_id=?",
            (amount, user_id),
        )

        if difference:
            con.execute(
                """
                INSERT INTO point_transactions(
                    user_id, amount, description, created_at
                ) VALUES(?,?,?,?)
                """,
                (user_id, difference, "تنظیم توسط مدیریت", now()),
            )

        con.commit()

    await update.effective_message.reply_text(
        f"موجودی پوینت کاربر {user_id} روی {amount} تنظیم شد."
    )


async def admin_point_requests(update, context):
    if not admin(update.effective_user.id):
        return

    with connect_db() as con:
        rows = con.execute(
            """
            SELECT * FROM point_requests
            WHERE status='pending'
            ORDER BY id ASC LIMIT 20
            """
        ).fetchall()

    if not rows:
        await update.effective_message.reply_text(
            "درخواست جایزه منتظر بررسی وجود ندارد."
        )
        return

    lines = ["درخواست‌های منتظر بررسی VEXO POINT\n"]

    for row in rows:
        reward_name = REWARDS.get(
            row["reward"], {"name": row["reward"]}
        )["name"]

        lines.append(
            f"#{row['id']} | کاربر: {row['user_id']}\n"
            f"جایزه: {reward_name}\n"
            f"هزینه: {row['cost']} پوینت\n"
            f"تأیید: /pointapprove {row['id']}\n"
            f"رد: /pointreject {row['id']}\n"
        )

    await update.effective_message.reply_text("\n".join(lines))


async def admin_point_approve_command(update, context):
    if not admin(update.effective_user.id):
        return

    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text(
            "مثال: /pointapprove 12"
        )
        return

    request_id = int(context.args[0])

    class QueryWrapper:
        def __init__(self, user, message):
            self.from_user = user
            self.message = message

        async def answer(self, *args, **kwargs):
            return None

    wrapper = QueryWrapper(
        update.effective_user,
        update.effective_message,
    )

    await review_point_request(
        wrapper,
        context,
        request_id,
        True,
    )


async def admin_point_reject_command(update, context):
    if not admin(update.effective_user.id):
        return

    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text(
            "مثال: /pointreject 12"
        )
        return

    request_id = int(context.args[0])

    class QueryWrapper:
        def __init__(self, user, message):
            self.from_user = user
            self.message = message

        async def answer(self, *args, **kwargs):
            return None

    wrapper = QueryWrapper(
        update.effective_user,
        update.effective_message,
    )

    await review_point_request(
        wrapper,
        context,
        request_id,
        False,
    )


# ==================================================
# GROUP HANDLER
# ==================================================

async def group_handler(update, context):
    message = update.effective_message
    user = update.effective_user

    if (
        not message
        or not user
        or message.chat.type == "private"
        or user.is_bot
    ):
        return

    register_user(user)
    text = (message.text or "").strip()

    if not text:
        return

    # Point commands must work in groups too.
    handled = await handle_point_text(update, context, text)

    if handled:
        return

    lowered = text.lower()

    if lowered in ("!عشق", "/عشق"):
        await message.reply_text(
            "ایونت عشق VEXORA فعال شد.\n"
            "برای سرگرمی و تعامل دوستانه."
        )
        return

    if lowered in ("!درآمد", "/درآمد"):
        await message.reply_text(
            "برای اطلاع از محصولات و پیشنهادها به ربات VEXORA مراجعه کن."
        )
        return

    if lowered in ("!قمار", "/قمار"):
        await message.reply_text(
            "بازی شانسی با پول واقعی در این ربات فعال نیست."
        )
        return

    earned = award_group_points(user.id, text)

    if earned:
        await message.reply_text(
            f"🪙 +{earned} VEXO POINT\n"
            f"موجودی: {user_points(user.id)} پوینت"
        )


# ==================================================
# CANCEL / HELP
# ==================================================

async def cancel(update, context):
    context.user_data.clear()

    await update.effective_message.reply_text(
        "عملیات لغو شد.",
        reply_markup=MAIN_MENU,
    )


async def help_command(update, context):
    await update.effective_message.reply_text(
        "راهنمای ربات VEXORA\n\n"
        "/start — شروع\n"
        "/cancel — لغو عملیات\n"
        "/help — راهنما\n\n"
        "برای امتیازها بنویس: پوینت من\n"
        f"پشتیبانی: {SUPPORT}",
        reply_markup=MAIN_MENU,
    )


async def error_handler(update, context):
    log.error(
        "Unhandled exception",
        exc_info=context.error,
    )


# ==================================================
# MAIN
# ==================================================

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "متغیر محیطی BOT_TOKEN تنظیم نشده است."
        )

    if ADMIN_ID == 0:
        raise RuntimeError(
            "متغیر محیطی ADMIN_ID تنظیم نشده است."
        )

    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("cancel", cancel))

    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("orders", admin_orders))
    app.add_handler(CommandHandler("approve", admin_approve_command))
    app.add_handler(CommandHandler("reject", admin_reject_command))
    app.add_handler(CommandHandler("delivered", mark_delivered))
    app.add_handler(CommandHandler("setprice", set_price))
    app.add_handler(CommandHandler("broadcast", broadcast))

    app.add_handler(CommandHandler("addpoints", admin_add_points))
    app.add_handler(CommandHandler("removepoints", admin_remove_points))
    app.add_handler(CommandHandler("setpoints", admin_set_points))
    app.add_handler(CommandHandler("pointrequests", admin_point_requests))
    app.add_handler(
        CommandHandler("pointapprove", admin_point_approve_command)
    )
    app.add_handler(
        CommandHandler("pointreject", admin_point_reject_command)
    )

    app.add_handler(CallbackQueryHandler(callbacks))

    app.add_handler(
        MessageHandler(
            filters.PHOTO | filters.Document.ALL,
            receipt_handler,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND
            & filters.ChatType.PRIVATE,
            text_input,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND
            & filters.ChatType.GROUPS,
            group_handler,
        )
    )

    app.add_error_handler(error_handler)

    log.info("VEXORA STORE + VEXO POINT is starting...")
    app.run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()
