import os
import re
import sqlite3
import logging
from datetime import datetime

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

# =========================================================
# VEXORA STORE
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or "0")
CHANNEL_ID = os.getenv("CHANNEL_ID", "@Vexora1Store").strip()
SUPPORT = os.getenv("SUPPORT_USERNAME", "@Vexorini").strip()
CARD_NUMBER = os.getenv("CARD_NUMBER", "").strip()
CARD_NAME = os.getenv("CARD_NAME", "").strip()
DB_NAME = os.getenv("DB_NAME", "vexora.db")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("VEXORA")

# =========================================================
# PRICES — TOMAN
# =========================================================

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


# =========================================================
# DATABASE
# =========================================================

def connect_db():
    con = sqlite3.connect(DB_NAME, timeout=20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


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
        """)

        # Update old database schema safely.
        cols = {
            row["name"]
            for row in con.execute("PRAGMA table_info(orders)")
        }
        for name, definition in [
            ("receipt_type", "TEXT DEFAULT ''"),
            ("updated_at", "TEXT DEFAULT ''"),
            ("delivered_at", "TEXT DEFAULT ''"),
            ("commission_done", "INTEGER DEFAULT 0"),
            ("channel_posted", "INTEGER DEFAULT 0"),
        ]:
            if name not in cols:
                con.execute(
                    f"ALTER TABLE orders ADD COLUMN {name} {definition}"
                )

        con.commit()


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def toman(amount):
    return f"{int(amount):,} تومان"


def admin(user_id):
    return ADMIN_ID != 0 and user_id == ADMIN_ID


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


# =========================================================
# CHANNEL MEMBERSHIP
# The bot must be an administrator in the channel.
# =========================================================

async def is_channel_member(bot, user_id):
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ("member", "administrator", "creator")
    except TelegramError:
        # If membership cannot be checked, don't falsely award referrals.
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
        "برای استفاده از ربات، ابتدا عضو کانال VEXORA شو.",
        reply_markup=keyboard,
    )
    return False


# =========================================================
# ORDERS
# =========================================================

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

    card = CARD_NUMBER or "شماره کارت هنوز توسط مدیریت تنظیم نشده است."
    owner = CARD_NAME or "نام صاحب کارت تنظیم نشده است."

    await message.reply_text(
        f"سفارش شما ثبت شد.\n\n"
        f"شماره سفارش: VX{order_id:06d}\n"
        f"محصول: {order['product']}\n"
        f"مبلغ: {toman(order['price'])}\n\n"
        f"شماره کارت:\n{card}\n"
        f"به نام: {owner}\n\n"
        "پس از پرداخت، تصویر رسید را همین‌جا ارسال کن.\n"
        "سفارش پس از بررسی مدیریت تأیید می‌شود.",
        reply_markup=MAIN_MENU,
    )


async def send_admin_order_receipt(context, order_id):
    order = get_order(order_id)
    if not order or not ADMIN_ID:
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "تأیید پرداخت",
                callback_data=f"approve:{order_id}",
            ),
            InlineKeyboardButton(
                "رد پرداخت",
                callback_data=f"reject:{order_id}",
            ),
        ]
    ])

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
        log.exception("Failed to send receipt to admin")


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
                "✍️ تعداد دلخواه استارز",
                callback_data="custom_stars",
            )
        ])

    await update.effective_message.reply_text(
        "محصول موردنظرت را انتخاب کن:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# =========================================================
# START / MENU
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        "به فروشگاه VEXORA خوش اومدی.\n\n"
        "استارز، گیفت و پرمیوم تلگرام رو از منوی زیر انتخاب کن.\n"
        "برای خرید، ابتدا محصول رو انتخاب کن و سپس اطلاعات سفارش رو وارد کن.",
        reply_markup=MAIN_MENU,
    )


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    register_user(user)

    text = update.effective_message.text or ""

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
            f"برای خرید کانفیگ و دریافت جزئیات با پشتیبانی ارتباط بگیر:\n{SUPPORT}"
        )

    elif text == "👛 کیف پول من":
        await update.effective_message.reply_text(
            f"موجودی کیف پولت: {toman(user_balance(user.id))}\n\n"
            "برای افزایش موجودی، گزینه «شارژ کیف پول» را بزن."
        )

    elif text == "💳 شارژ کیف پول":
        context.user_data["state"] = "topup_amount"
        await update.effective_message.reply_text(
            "مبلغ شارژ کیف پول را به تومان وارد کن.\n"
            "مثال: 200000"
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
            f"تعداد دعوت‌شده‌ها: {count}\n"
            "با خرید و تحویل سفارش دعوت‌شده، ۵۰٪ مبلغ سفارش به کیف پولت اضافه می‌شود.\n"
            "دعوت‌شده باید عضو کانال باشد."
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
        points = user_points(user.id)
        await update.effective_message.reply_text(
            f"امتیاز وکسورای تو: {points}\n\n"
            "۳ امتیاز: درخواست جایزه استارز\n"
            "۱۸ امتیاز: درخواست گیفت تدی\n"
            "هر امتیاز قابل خرید است: ۱٬۰۰۰ تومان\n\n"
            "درخواست جایزه پس از بررسی مدیریت انجام می‌شود."
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
                "هنوز سفارشی ثبت نکردی."
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
            "۲. یوزرنیم یا اطلاعات لازم سفارش را وارد کن.\n"
            "۳. مبلغ را به کارت اعلام‌شده پرداخت کن.\n"
            "۴. تصویر رسید را ارسال کن.\n"
            "۵. پس از تأیید پرداخت، سفارش در انتظار تحویل می‌ماند.\n"
            "۶. پس از تحویل واقعی، وضعیت سفارش تکمیل می‌شود.\n\n"
            "تأیید پرداخت به معنی تحویل محصول نیست."
        )

    elif text == "❓ سؤالات متداول":
        await update.effective_message.reply_text(
            "سؤالات متداول\n\n"
            "• سفارش من کجاست؟ از بخش پیگیری سفارش استفاده کن.\n"
            "• رسیدم بررسی نشده؟ کمی صبر کن یا به پشتیبانی پیام بده.\n"
            "• پرداخت تأیید شده ولی محصول نرسیده؟ وضعیت سفارش در انتظار تحویل است.\n"
            "• برای کانفیگ چه کنم؟ به پشتیبانی پیام بده."
        )

    elif text == "👨‍💻 پشتیبانی":
        await update.effective_message.reply_text(
            f"پشتیبانی VEXORA:\n{SUPPORT}"
        )

    elif text == "🎯 مأموریت‌ها":
        await update.effective_message.reply_text(
            "برای دریافت امتیاز، دوستانت را با لینک اختصاصی دعوت کن.\n"
            "امتیاز دعوت پس از عضویت دعوت‌شده در کانال بررسی می‌شود."
        )

    elif text == "🎮 سرگرمی و بازی":
        await update.effective_message.reply_text(
            "بخش سرگرمی در حال آماده‌سازی است."
        )


# =========================================================
# CALLBACKS
# =========================================================

async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                "هنوز عضویتت تأیید نشده. ابتدا عضو کانال شو و دوباره امتحان کن."
            )
        return

    if data == "custom_stars":
        context.user_data["state"] = "custom_stars"
        await query.message.reply_text(
            "تعداد استارز موردنظرت را وارد کن.\n"
            "حداقل ۵۰ عدد؛ قیمت هر استارز ۳٬۶۰۰ تومان است."
        )
        return

    if data.startswith("buy:"):
        if not await is_channel_member(context.bot, user.id) and not admin(user.id):
            await query.message.reply_text(
                "برای خرید ابتدا عضو کانال شو:\nhttps://t.me/Vexora1Store"
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
            prompt + "\n\nبرای لغو سفارش، /cancel را بفرست."
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
                UPDATE orders
                SET status='paid', updated_at=?
                WHERE id=? AND status='receipt_sent'
                """,
                (now(), order_id),
            )
            con.commit()

        await context.bot.send_message(
            order["user_id"],
            f"پرداخت سفارش VX{order_id:06d} تأیید شد.\n"
            "سفارش در انتظار تحویل است. پس از تحویل واقعی، وضعیت تکمیل می‌شود."
        )
        await query.message.reply_text(
            f"پرداخت سفارش VX{order_id:06d} تأیید شد.\n"
            f"برای ثبت تحویل واقعی، دستور زیر را بفرست:\n"
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
                UPDATE orders
                SET status='rejected', updated_at=?
                WHERE id=? AND status='receipt_sent'
                """,
                (now(), order_id),
            )
            con.commit()

        await context.bot.send_message(
            order["user_id"],
            f"رسید سفارش VX{order_id:06d} رد شد.\n"
            "برای بررسی بیشتر با پشتیبانی تماس بگیر."
        )
        await query.message.reply_text(
            f"رسید سفارش VX{order_id:06d} رد شد."
        )
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
                    user_id,amount,description,created_at
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
            f"شارژ کیف پولت به مبلغ {toman(topup['amount'])} تأیید شد."
        )
        await query.message.reply_text("شارژ کیف پول تأیید شد.")
        return


# =========================================================
# TEXT INPUTS
# =========================================================

async def text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message

    if not user or not message or not message.text:
        return

    register_user(user)
    state = context.user_data.get("state")
    text = message.text.strip()

    if state == "order_target":
        product = context.user_data.get("pending_product")
        price = context.user_data.get("pending_price")

        if not product or not price:
            context.user_data.pop("state", None)
            await message.reply_text(
                "اطلاعات سفارش منقضی شده. دوباره محصول را انتخاب کن.",
                reply_markup=MAIN_MENU,
            )
            return

        if len(text) < 3 or len(text) > 200:
            await message.reply_text(
                "اطلاعات واردشده معتبر نیست؛ دوباره وارد کن."
            )
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
            await message.reply_text("فقط تعداد را به عدد وارد کن.")
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

        card = CARD_NUMBER or "شماره کارت هنوز تنظیم نشده است."
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


# =========================================================
# RECEIPTS
# =========================================================

async def receipt_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            await message.reply_text("درخواست شارژ منقضی شده؛ دوباره شروع کن.")
            return

        if message.photo:
            receipt_id = message.photo[-1].file_id
            receipt_type = "photo"
        elif message.document:
            receipt_id = message.document.file_id
            receipt_type = "document"
        else:
            await message.reply_text("لطفاً تصویر رسید یا فایل آن را بفرست.")
            return

        with connect_db() as con:
            cur = con.execute(
                """
                INSERT INTO topups(
                    user_id,amount,receipt_id,receipt_type,status,created_at
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
            f"رسید شارژ با شماره {topup_id} ارسال شد و منتظر بررسی مدیریت است."
        )

        if ADMIN_ID:
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "تأیید شارژ",
                    callback_data=f"topup_approve:{topup_id}",
                )
            ]])
            caption = (
                f"درخواست شارژ کیف پول #{topup_id}\n"
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

    # Order receipt
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
            SET status='receipt_sent',
                receipt_id=?,
                receipt_type=?,
                updated_at=?
            WHERE id=? AND status='waiting_payment'
            """,
            (receipt_id, receipt_type, now(), order["id"]),
        )
        con.commit()

    context.user_data.pop("state", None)

    await message.reply_text(
        f"رسید سفارش VX{order['id']:06d} دریافت شد.\n"
        "پس از بررسی مدیریت، نتیجه به تو اطلاع داده می‌شود.",
        reply_markup=MAIN_MENU,
    )

    await send_admin_order_receipt(context, order["id"])


# =========================================================
# ADMIN COMMANDS
# =========================================================

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    await update.effective_message.reply_text(
        "پنل مدیریت VEXORA\n\n"
        f"کاربران: {users}\n"
        f"کل سفارش‌ها: {orders}\n"
        f"رسیدهای منتظر بررسی: {pending}\n"
        f"مجموع مبلغ سفارش‌های تحویل‌شده: {toman(revenue)}\n\n"
        "دستورات:\n"
        "/orders — سفارش‌های اخیر\n"
        "/approve ID — تأیید پرداخت\n"
        "/reject ID — رد پرداخت\n"
        "/delivered ID — ثبت تحویل واقعی\n"
        "/setprice نام محصول|مبلغ — تغییر قیمت\n"
        "/broadcast متن — ارسال پیام همگانی"
    )


async def admin_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin(update.effective_user.id):
        return

    with connect_db() as con:
        orders = con.execute(
            "SELECT * FROM orders ORDER BY id DESC LIMIT 20"
        ).fetchall()

    if not orders:
        await update.effective_message.reply_text("هنوز سفارشی ثبت نشده.")
        return

    lines = []
    for o in orders:
        lines.append(
            f"VX{o['id']:06d} | {o['product']}\n"
            f"کاربر: {o['user_id']} | {toman(o['price'])}\n"
            f"وضعیت: {STATUS.get(o['status'], o['status'])}\n"
        )

    await update.effective_message.reply_text("\n".join(lines))


async def admin_approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                "سفارش پیدا نشد یا رسید آن قبلاً بررسی شده است."
            )
            return

        con.execute(
            """
            UPDATE orders SET status='paid',updated_at=?
            WHERE id=? AND status='receipt_sent'
            """,
            (now(), order_id),
        )
        con.commit()

    await context.bot.send_message(
        order["user_id"],
        f"پرداخت سفارش VX{order_id:06d} تأیید شد؛ سفارش در انتظار تحویل است."
    )
    await update.effective_message.reply_text(
        f"پرداخت تأیید شد. بعد از تحویل واقعی از /delivered {order_id} استفاده کن."
    )


async def admin_reject_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            UPDATE orders SET status='rejected',updated_at=?
            WHERE id=? AND status='receipt_sent'
            """,
            (now(), order_id),
        )
        con.commit()

    await context.bot.send_message(
        order["user_id"],
        f"رسید سفارش VX{order_id:06d} رد شد. برای پیگیری با {SUPPORT} تماس بگیر."
    )
    await update.effective_message.reply_text("رسید رد شد.")


async def mark_delivered(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            SET status='delivered',updated_at=?,delivered_at=?
            WHERE id=? AND status='paid'
            """,
            (now(), now(), order_id),
        )

        # One-time referral commission after delivery.
        referral = con.execute(
            """
            SELECT * FROM referrals
            WHERE invited_id=?
            """,
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
                    user_id,amount,description,created_at
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
        f"سفارش VX{order_id:06d} به‌عنوان تحویل‌شده ثبت شد. ممنون از خریدت."
    )

    if not order["channel_posted"]:
        try:
            await context.bot.send_message(
                CHANNEL_ID,
                "VEXORA | سفارش تکمیل شد\n\n"
                f"شماره سفارش: VX{order_id:06d}\n"
                f"محصول: {order['product']}\n"
                "وضعیت: تحویل‌شده"
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


async def set_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            "محصول پیش‌فرض پیدا نشد یا قیمت نامعتبر است."
        )
        return

    PRODUCTS[name] = (price, PRODUCTS[name][1])

    await update.effective_message.reply_text(
        f"قیمت {name} در حافظه ربات به {toman(price)} تغییر کرد.\n"
        "توجه: این تغییر پس از راه‌اندازی مجدد به حالت پیش‌فرض برمی‌گردد."
    )


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin(update.effective_user.id):
        return

    text = update.effective_message.text.partition(" ")[2].strip()
    if not text:
        await update.effective_message.reply_text("مثال: /broadcast سلام")
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


# =========================================================
# CANCEL / HELP
# =========================================================

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.effective_message.reply_text(
        "عملیات لغو شد.",
        reply_markup=MAIN_MENU,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "راهنمای ربات VEXORA\n\n"
        "/start — شروع\n"
        "/cancel — لغو عملیات\n"
        "/help — راهنما\n\n"
        f"پشتیبانی: {SUPPORT}",
        reply_markup=MAIN_MENU,
    )


# =========================================================
# GROUP FEATURES
# =========================================================

async def group_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user = update.effective_user

    if not message or not user or message.chat.type == "private":
        return

    # Only react to the administrator's messages.
    if admin(user.id):
        try:
            await message.set_reaction(
                reaction=[{"type": "emoji", "emoji": "🖤"}]
            )
        except (TelegramError, TypeError):
            # Reactions depend on Telegram API permissions and chat settings.
            pass

    text = (message.text or "").lower()

    # Simple opt-in commands for group events.
    if text in ("!عشق", "/عشق"):
        await message.reply_text(
            "ایونت عشق VEXORA فعال شد.\n"
            "برای سرگرمی و تعامل دوستانه؛ بدون شرط‌بندی واقعی."
        )

    elif text in ("!درآمد", "/درآمد"):
        await message.reply_text(
            "ایونت درآمد VEXORA\n"
            "برای اطلاع از محصولات و پیشنهادها به ربات مراجعه کن."
        )

    elif text in ("!قمار", "/قمار"):
        await message.reply_text(
            "بازی شانسی با پول واقعی در این ربات فعال نیست."
        )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(update, context):
    log.error("Unhandled exception: %s", context.error)


# =========================================================
# MAIN
# =========================================================

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

    app.add_handler(CallbackQueryHandler(callbacks))

    app.add_handler(
        MessageHandler(
            filters.PHOTO | filters.Document.ALL,
            receipt_handler,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
            text_input,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & ~filters.ChatType.PRIVATE,
            group_handler,
        )
    )

    app.add_error_handler(error_handler)

    log.info("VEXORA STORE is starting...")
    app.run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()
