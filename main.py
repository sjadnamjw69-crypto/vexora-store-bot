import os
import sqlite3
import random
import time
import logging
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ==================================================
# VEXORA CONFIG
# ==================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
CHANNEL_ID = os.getenv("CHANNEL_ID", "@Vexora1Store")
SUPPORT = "@Vexorini"

CARD_NUMBER = os.getenv("CARD_NUMBER", "")
CARD_NAME = os.getenv("CARD_NAME", "")

DB_NAME = "vexora.db"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("VEXORA")

# ==================================================
# PRODUCTS
# Prices are in toman
# ==================================================

DEFAULT_PRODUCTS = {
    "استارز 50 عدد": 100000,
    "استارز 100 عدد": 200000,
    "استارز 250 عدد": 500000,
    "استارز 500 عدد": 1000000,
    "استارز 1000 عدد": 2000000,

    "گیفت تدی": 55000,
    "گیفت قلب": 55000,
    "گیفت رز": 95000,

    "پریمیوم 3 ماهه": 2990000,
    "پریمیوم 6 ماهه": 3990000,
    "پریمیوم 12 ماهه": 6990000,
}

# ==================================================
# DATABASE
# ==================================================

def db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            name TEXT PRIMARY KEY,
            price INTEGER NOT NULL,
            active INTEGER DEFAULT 1
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            coins INTEGER DEFAULT 0,
            points INTEGER DEFAULT 0,
            invited_by INTEGER DEFAULT 0,
            last_work INTEGER DEFAULT 0,
            last_daily INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT DEFAULT '',
            product TEXT NOT NULL,
            price INTEGER NOT NULL,
            target TEXT DEFAULT '',
            status TEXT DEFAULT 'waiting',
            receipt_id TEXT DEFAULT '',
            created_at TEXT DEFAULT ''
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            inviter_id INTEGER NOT NULL,
            invited_id INTEGER NOT NULL UNIQUE,
            created_at TEXT DEFAULT ''
        )
    """)

    for name, price in DEFAULT_PRODUCTS.items():
        cur.execute(
            "INSERT OR IGNORE INTO products (name, price) VALUES (?, ?)",
            (name, price),
        )

    conn.commit()
    conn.close()


def ensure_user(user):
    if not user:
        return

    conn = db()
    conn.execute("""
        INSERT INTO users (user_id, username)
        VALUES (?, ?)
        ON CONFLICT(user_id)
        DO UPDATE SET username = excluded.username
    """, (user.id, user.username or ""))

    conn.commit()
    conn.close()


def get_products():
    conn = db()
    rows = conn.execute("""
        SELECT name, price FROM products
        WHERE active = 1
        ORDER BY name
    """).fetchall()
    conn.close()
    return rows


def get_product(name):
    conn = db()
    row = conn.execute(
        "SELECT name, price FROM products WHERE name = ? AND active = 1",
        (name,),
    ).fetchone()
    conn.close()
    return row


def is_admin(user_id):
    return user_id == ADMIN_ID and ADMIN_ID != 0


def main_menu():
    return ReplyKeyboardMarkup(
        [
            ["🛍 فروشگاه", "📦 سفارش‌های من"],
            ["💰 کیف پول", "🎁 دعوت دوستان"],
            ["📜 راهنمای پرداخت", "🎧 پشتیبانی"],
        ],
        resize_keyboard=True,
    )


def money(value):
    return f"{int(value):,} تومان"


# ==================================================
# START / REFERRAL
# ==================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    ensure_user(user)

    # Referral link: /start USER_ID
    if context.args:
        try:
            inviter_id = int(context.args[0])

            if inviter_id != user.id:
                conn = db()
                already = conn.execute(
                    "SELECT invited_id FROM referrals WHERE invited_id = ?",
                    (user.id,),
                ).fetchone()

                inviter_exists = conn.execute(
                    "SELECT user_id FROM users WHERE user_id = ?",
                    (inviter_id,),
                ).fetchone()

                if not already and inviter_exists:
                    conn.execute("""
                        INSERT INTO referrals
                        (inviter_id, invited_id, created_at)
                        VALUES (?, ?, ?)
                    """, (
                        inviter_id,
                        user.id,
                        datetime.now().isoformat(timespec="seconds"),
                    ))

                    conn.execute("""
                        UPDATE users
                        SET points = points + 1
                        WHERE user_id = ?
                    """, (inviter_id,))

                    conn.commit()

                    try:
                        await context.bot.send_message(
                            inviter_id,
                            "🎉 یک نفر با لینک دعوتت وارد وکسورا شد!\n"
                            "یک امتیاز به حسابت اضافه شد."
                        )
                    except Exception:
                        pass

                conn.close()

        except (ValueError, TypeError):
            pass

    text = (
        "به فروشگاه VEXORA خوش آمدی.\n\n"
        "فروش استارز، گیفت و تلگرام پریمیوم\n"
        "ثبت سفارش از طریق ربات انجام می‌شود.\n\n"
        f"پشتیبانی: {SUPPORT}\n\n"
        "برای شروع، از منوی زیر استفاده کن."
    )

    await update.effective_message.reply_text(
        text,
        reply_markup=main_menu(),
    )


# ==================================================
# STORE
# ==================================================

async def show_store(update: Update, context: ContextTypes.DEFAULT_TYPE):
    products = get_products()

    if not products:
        await update.effective_message.reply_text(
            "در حال حاضر محصولی موجود نیست."
        )
        return

    keyboard = []

    for product in products:
        keyboard.append([
            InlineKeyboardButton(
                f"{product['name']} | {money(product['price'])}",
                callback_data=f"product:{product['name']}",
            )
        ])

    await update.effective_message.reply_text(
        "🛍 فروشگاه VEXORA\n\n"
        "محصول موردنظرت را انتخاب کن:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def product_selected(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    name = query.data.split(":", 1)[1]
    product = get_product(name)

    if not product:
        await query.edit_message_text("این محصول در دسترس نیست.")
        return

    context.user_data["selected_product"] = name

    keyboard = [[
        InlineKeyboardButton(
            "🛒 ثبت سفارش",
            callback_data="create_order",
        )
    ]]

    await query.edit_message_text(
        f"محصول: {name}\n"
        f"قیمت: {money(product['price'])}\n\n"
        "برای ادامه روی ثبت سفارش بزن.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def create_order(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    ensure_user(user)

    name = context.user_data.get("selected_product")
    product = get_product(name) if name else None

    if not product:
        await query.edit_message_text(
            "محصول پیدا نشد. لطفاً دوباره از فروشگاه انتخاب کن."
        )
        return

    context.user_data["waiting_target"] = True

    await query.edit_message_text(
        f"محصول انتخابی: {name}\n"
        f"مبلغ: {money(product['price'])}\n\n"
        "حالا یوزرنیم مقصد را ارسال کن.\n"
        "مثال: @username\n\n"
        "رمز عبور و کد ورود تلگرام را ارسال نکن."
    )


async def handle_target(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not context.user_data.get("waiting_target"):
        return

    target = update.effective_message.text.strip()

    if not target or len(target) > 100:
        await update.effective_message.reply_text(
            "یوزرنیم معتبر را ارسال کن."
        )
        return

    name = context.user_data.get("selected_product")
    product = get_product(name) if name else None

    if not product:
        context.user_data.pop("waiting_target", None)
        await update.effective_message.reply_text(
            "محصول پیدا نشد. دوباره از فروشگاه انتخاب کن."
        )
        return

    user = update.effective_user

    conn = db()
    cur = conn.execute("""
        INSERT INTO orders
        (user_id, username, product, price, target, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        user.id,
        user.username or "",
        name,
        product["price"],
        target,
        "waiting_payment",
        datetime.now().isoformat(timespec="seconds"),
    ))

    order_id = cur.lastrowid
    conn.commit()
    conn.close()

    context.user_data.pop("waiting_target", None)
    context.user_data.pop("selected_product", None)

    payment_text = (
        f"سفارش شما ثبت شد.\n\n"
        f"شماره سفارش: #{order_id}\n"
        f"محصول: {name}\n"
        f"مبلغ: {money(product['price'])}\n"
        f"مقصد: {target}\n\n"
        "پس از پرداخت، تصویر رسید را همین‌جا ارسال کن."
    )

    if CARD_NUMBER:
        payment_text += (
            f"\n\nشماره کارت:\n{CARD_NUMBER}"
        )

    if CARD_NAME:
        payment_text += f"\nبه نام: {CARD_NAME}"

    await update.effective_message.reply_text(payment_text)

    if ADMIN_ID:
        try:
            await context.bot.send_message(
                ADMIN_ID,
                f"🛒 سفارش جدید #{order_id}\n\n"
                f"کاربر: {user.full_name}\n"
                f"آیدی: {user.id}\n"
                f"یوزرنیم: @{user.username or 'ندارد'}\n"
                f"محصول: {name}\n"
                f"مبلغ: {money(product['price'])}\n"
                f"مقصد: {target}\n"
                "وضعیت: در انتظار پرداخت",
            )
        except Exception as e:
            logger.warning("Admin notification failed: %s", e)


# ==================================================
# RECEIPTS
# ==================================================

async def receive_receipt(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user
    ensure_user(user)

    conn = db()
    order = conn.execute("""
        SELECT * FROM orders
        WHERE user_id = ?
        AND status = 'waiting_payment'
        ORDER BY id DESC LIMIT 1
    """, (user.id,)).fetchone()
    conn.close()

    if not order:
        return

    message = update.effective_message

    if message.photo:
        receipt_id = message.photo[-1].file_id
    elif message.document:
        receipt_id = message.document.file_id
    else:
        await message.reply_text(
            "لطفاً تصویر رسید پرداخت را به‌صورت عکس یا فایل ارسال کن."
        )
        return

    conn = db()
    conn.execute(
        "UPDATE orders SET receipt_id = ?, status = 'receipt_sent' WHERE id = ?",
        (receipt_id, order["id"]),
    )
    conn.commit()
    conn.close()

    await message.reply_text(
        f"رسید سفارش #{order['id']} دریافت شد.\n"
        "پس از بررسی پرداخت، نتیجه اعلام می‌شود."
    )

    if ADMIN_ID:
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ تأیید پرداخت",
                    callback_data=f"approve:{order['id']}",
                ),
                InlineKeyboardButton(
                    "❌ رد پرداخت",
                    callback_data=f"reject:{order['id']}",
                ),
            ]
        ])

        caption = (
            f"رسید سفارش #{order['id']}\n"
            f"کاربر: {user.id}\n"
            f"محصول: {order['product']}\n"
            f"مبلغ: {money(order['price'])}\n\n"
            "قبل از تأیید، پرداخت واقعی را بررسی کن."
        )

        try:
            if message.photo:
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
        except Exception as e:
            logger.warning("Receipt forwarding failed: %s", e)


async def payment_decision(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    if not is_admin(query.from_user.id):
        await query.answer("اجازه دسترسی نداری.", show_alert=True)
        return

    await query.answer()

    action, order_id_text = query.data.split(":")
    order_id = int(order_id_text)

    conn = db()
    order = conn.execute(
        "SELECT * FROM orders WHERE id = ?",
        (order_id,),
    ).fetchone()

    if not order:
        conn.close()
        await query.edit_message_caption("سفارش پیدا نشد.")
        return

    if order["status"] not in ("receipt_sent", "waiting_payment"):
        conn.close()
        await query.answer("این سفارش قبلاً بررسی شده.", show_alert=True)
        return

    if action == "approve":
        conn.execute(
            "UPDATE orders SET status = 'paid' WHERE id = ?",
            (order_id,),
        )
        conn.commit()
        conn.close()

        await query.edit_message_caption(
            f"✅ پرداخت سفارش #{order_id} تأیید شد.\n"
            f"محصول: {order['product']}\n"
            "برای تکمیل سفارش، تحویل محصول را جداگانه انجام بده."
        )

        try:
            await context.bot.send_message(
                order["user_id"],
                f"پرداخت سفارش #{order_id} تأیید شد.\n"
                "سفارش در انتظار تحویل است."
            )
        except Exception:
            pass

    else:
        conn.execute(
            "UPDATE orders SET status = 'rejected' WHERE id = ?",
            (order_id,),
        )
        conn.commit()
        conn.close()

        await query.edit_message_caption(
            f"❌ پرداخت سفارش #{order_id} رد شد."
        )

        try:
            await context.bot.send_message(
                order["user_id"],
                f"پرداخت سفارش #{order_id} تأیید نشد.\n"
                f"برای بررسی با {SUPPORT} تماس بگیر."
            )
        except Exception:
            pass


# ==================================================
# ORDER HISTORY
# ==================================================

async def my_orders(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user_id = update.effective_user.id

    conn = db()
    rows = conn.execute("""
        SELECT id, product, price, status, created_at
        FROM orders WHERE user_id = ?
        ORDER BY id DESC LIMIT 10
    """, (user_id,)).fetchall()
    conn.close()

    if not rows:
        await update.effective_message.reply_text(
            "هنوز سفارشی ثبت نکرده‌ای."
        )
        return

    status_names = {
        "waiting_payment": "در انتظار پرداخت",
        "receipt_sent": "رسید ارسال شده",
        "paid": "پرداخت تأیید شده؛ در انتظار تحویل",
        "delivered": "تحویل شده",
        "rejected": "پرداخت رد شده",
    }

    lines = ["📦 سفارش‌های اخیر تو:\n"]

    for row in rows:
        lines.append(
            f"#{row['id']} — {row['product']}\n"
            f"مبلغ: {money(row['price'])}\n"
            f"وضعیت: {status_names.get(row['status'], row['status'])}\n"
        )

    await update.effective_message.reply_text("\n".join(lines))


async def delivered(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not is_admin(update.effective_user.id):
        return

    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text(
            "روش استفاده:\n/delivered شماره_سفارش\n"
            "مثال: /delivered 12"
        )
        return

    order_id = int(context.args[0])

    conn = db()
    order = conn.execute(
        "SELECT * FROM orders WHERE id = ?",
        (order_id,),
    ).fetchone()

    if not order:
        conn.close()
        await update.effective_message.reply_text(
            "سفارش پیدا نشد."
        )
        return

    if order["status"] != "paid":
        conn.close()
        await update.effective_message.reply_text(
            "ابتدا پرداخت سفارش باید تأیید شده باشد."
        )
        return

    conn.execute(
        "UPDATE orders SET status = 'delivered' WHERE id = ?",
        (order_id,),
    )
    conn.commit()
    conn.close()

    await update.effective_message.reply_text(
        f"سفارش #{order_id} تحویل‌شده ثبت شد."
    )

    try:
        await context.bot.send_message(
            order["user_id"],
            f"سفارش #{order_id} تحویل داده شد.\n"
            "از خریدت از VEXORA ممنونیم."
        )
    except Exception:
        pass

    try:
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=(
                "یک سفارش در VEXORA تکمیل شد.\n"
                f"محصول: {order['product']}\n"
                "از همراهی شما ممنونیم."
            ),
        )
    except Exception as e:
        logger.warning("Channel announcement failed: %s", e)


# ==================================================
# ADMIN PANEL / PRICE MANAGEMENT
# ==================================================

async def admin_panel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text(
            "اجازه دسترسی نداری."
        )
        return

    keyboard = [
        [InlineKeyboardButton(
            "💰 تغییر قیمت محصولات",
            callback_data="admin_prices",
        )],
        [InlineKeyboardButton(
            "📦 سفارش‌های در انتظار",
            callback_data="admin_orders",
        )],
        [InlineKeyboardButton(
            "📊 آمار فروشگاه",
            callback_data="admin_stats",
        )],
    ]

    await update.effective_message.reply_text(
        "پنل مدیریت VEXORA",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def admin_callbacks(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    if not is_admin(query.from_user.id):
        await query.answer("دسترسی غیرمجاز.", show_alert=True)
        return

    await query.answer()

    if query.data == "admin_prices":
        rows = get_products()
        keyboard = []

        for row in rows:
            keyboard.append([
                InlineKeyboardButton(
                    f"{row['name']} — {money(row['price'])}",
                    callback_data=f"price:{row['name']}",
                )
            ])

        await query.edit_message_text(
            "برای تغییر قیمت، محصول را انتخاب کن:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif query.data.startswith("price:"):
        name = query.data.split(":", 1)[1]
        context.user_data["editing_price"] = name

        await query.edit_message_text(
            f"قیمت جدید برای «{name}» را فقط به عدد تومان بفرست.\n"
            "مثال: 100000\n\n"
            "برای لغو دستور /cancel را بفرست."
        )

    elif query.data == "admin_orders":
        conn = db()
        rows = conn.execute("""
            SELECT id, user_id, product, price, status
            FROM orders
            WHERE status IN ('waiting_payment', 'receipt_sent', 'paid')
            ORDER BY id DESC LIMIT 15
        """).fetchall()
        conn.close()

        if not rows:
            await query.edit_message_text(
                "سفارش در انتظار بررسی وجود ندارد."
            )
            return

        lines = ["سفارش‌های باز:\n"]

        for row in rows:
            lines.append(
                f"#{row['id']} | {row['product']} | "
                f"{money(row['price'])} | {row['status']}"
            )

        await query.edit_message_text("\n".join(lines))

    elif query.data == "admin_stats":
        conn = db()

        users = conn.execute(
            "SELECT COUNT(*) AS n FROM users"
        ).fetchone()["n"]

        orders = conn.execute(
            "SELECT COUNT(*) AS n FROM orders"
        ).fetchone()["n"]

        paid = conn.execute("""
            SELECT COALESCE(SUM(price), 0) AS total
            FROM orders
            WHERE status IN ('paid', 'delivered')
        """).fetchone()["total"]

        conn.close()

        await query.edit_message_text(
            "📊 آمار VEXORA\n\n"
            f"کاربران ثبت‌شده: {users}\n"
            f"کل سفارش‌ها: {orders}\n"
            f"مجموع سفارش‌های پرداخت‌شده: {money(paid)}"
        )


async def admin_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    name = context.user_data.get("editing_price")

    if not name:
        return

    if not is_admin(update.effective_user.id):
        return

    text = update.effective_message.text.strip()

    if text == "/cancel":
        context.user_data.pop("editing_price", None)
        await update.effective_message.reply_text(
            "تغییر قیمت لغو شد."
        )
        return

    digits = text.replace(",", "").replace("٬", "")

    if not digits.isdigit() or int(digits) < 0:
        await update.effective_message.reply_text(
            "قیمت معتبر نیست. فقط عدد تومان بفرست."
        )
        return

    price = int(digits)

    conn = db()
    conn.execute(
        "UPDATE products SET price = ? WHERE name = ?",
        (price, name),
    )
    conn.commit()
    conn.close()

    context.user_data.pop("editing_price", None)

    await update.effective_message.reply_text(
        f"قیمت محصول «{name}» به {money(price)} تغییر کرد."
    )


async def add_product(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not is_admin(update.effective_user.id):
        return

    if len(context.args) < 2:
        await update.effective_message.reply_text(
            "روش استفاده:\n"
            "/addproduct نام_محصول قیمت\n"
            "مثال:\n/addproduct گیفت_جدید 100000"
        )
        return

    price_text = context.args[-1]

    if not price_text.isdigit():
        await update.effective_message.reply_text(
            "قیمت باید عدد باشد."
        )
        return

    name = " ".join(context.args[:-1]).replace("_", " ")
    price = int(price_text)

    conn = db()
    conn.execute("""
        INSERT INTO products (name, price, active)
        VALUES (?, ?, 1)
        ON CONFLICT(name)
        DO UPDATE SET price = excluded.price, active = 1
    """, (name, price))
    conn.commit()
    conn.close()

    await update.effective_message.reply_text(
        f"محصول «{name}» با قیمت {money(price)} ذخیره شد."
    )


# ==================================================
# GROUP ECONOMY
# ==================================================

async def balance(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user
    ensure_user(user)

    conn = db()
    row = conn.execute(
        "SELECT coins, points FROM users WHERE user_id = ?",
        (user.id,),
    ).fetchone()
    conn.close()

    await update.effective_message.reply_text(
        f"👤 {user.full_name}\n\n"
        f"🪙 سکه: {row['coins']}\n"
        f"🎁 امتیاز دعوت: {row['points']}"
    )


async def work(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user
    ensure_user(user)

    now = int(time.time())

    conn = db()
    row = conn.execute(
        "SELECT last_work FROM users WHERE user_id = ?",
        (user.id,),
    ).fetchone()

    wait = 3600 - (now - row["last_work"])

    if wait > 0:
        conn.close()
        minutes = max(1, wait // 60)
        await update.effective_message.reply_text(
            f"هنوز خسته‌ای! {minutes} دقیقه دیگر دوباره تلاش کن."
        )
        return

    reward = random.randint(50, 200)

    conn.execute("""
        UPDATE users
        SET coins = coins + ?, last_work = ?
        WHERE user_id = ?
    """, (reward, now, user.id))

    conn.commit()
    conn.close()

    await update.effective_message.reply_text(
        f"💼 کار کردی و {reward} سکه گرفتی!"
    )


async def daily(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user
    ensure_user(user)

    now = int(time.time())

    conn = db()
    row = conn.execute(
        "SELECT last_daily FROM users WHERE user_id = ?",
        (user.id,),
    ).fetchone()

    if now - row["last_daily"] < 86400:
        conn.close()
        await update.effective_message.reply_text(
            "پاداش روزانه را قبلاً دریافت کرده‌ای. فردا دوباره بیا."
        )
        return

    reward = 300

    conn.execute("""
        UPDATE users
        SET coins = coins + ?, last_daily = ?
        WHERE user_id = ?
    """, (reward, now, user.id))

    conn.commit()
    conn.close()

    await update.effective_message.reply_text(
        f"🎁 پاداش روزانه‌ات: {reward} سکه!"
    )


async def pay_coins(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user
    ensure_user(user)

    if len(context.args) != 2:
        await update.effective_message.reply_text(
            "روش استفاده:\n/pay شناسه_کاربر مقدار\n"
            "مثال: /pay 123456789 50"
        )
        return

    try:
        recipient = int(context.args[0])
        amount = int(context.args[1])
    except ValueError:
        await update.effective_message.reply_text(
            "شناسه و مقدار باید عدد باشند."
        )
        return

    if recipient == user.id or amount <= 0:
        await update.effective_message.reply_text(
            "اطلاعات انتقال معتبر نیست."
        )
        return

    conn = db()

    sender_row = conn.execute(
        "SELECT coins FROM users WHERE user_id = ?",
        (user.id,),
    ).fetchone()

    recipient_row = conn.execute(
        "SELECT user_id FROM users WHERE user_id = ?",
        (recipient,),
    ).fetchone()

    if not sender_row or sender_row["coins"] < amount:
        conn.close()
        await update.effective_message.reply_text(
            "سکه کافی نداری."
        )
        return

    if not recipient_row:
        conn.close()
        await update.effective_message.reply_text(
            "این کاربر هنوز ربات را شروع نکرده است."
        )
        return

    conn.execute(
        "UPDATE users SET coins = coins - ? WHERE user_id = ?",
        (amount, user.id),
    )
    conn.execute(
        "UPDATE users SET coins = coins + ? WHERE user_id = ?",
        (amount, recipient),
    )

    conn.commit()
    conn.close()

    await update.effective_message.reply_text(
        f"✅ {amount} سکه برای کاربر {recipient} ارسال شد."
    )


# ==================================================
# REFERRALS / MISSIONS
# ==================================================

async def referrals(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user
    ensure_user(user)

    bot_username = context.bot.username

    conn = db()
    row = conn.execute(
        "SELECT points FROM users WHERE user_id = ?",
        (user.id,),
    ).fetchone()

    invited = conn.execute(
        "SELECT COUNT(*) AS n FROM referrals WHERE inviter_id = ?",
        (user.id,),
    ).fetchone()["n"]

    conn.close()

    link = f"https://t.me/{bot_username}?start={user.id}"

    await update.effective_message.reply_text(
        "🎁 دعوت دوستان VEXORA\n\n"
        f"لینک اختصاصی تو:\n{link}\n\n"
        f"تعداد دعوت‌های ثبت‌شده: {invited}\n"
        f"امتیازهای تو: {row['points']}\n\n"
        "هر عضو جدیدی که با لینک تو وارد شود، "
        "یک امتیاز برایت ثبت می‌کند.\n"
        "برای دریافت پاداش با پشتیبانی هماهنگ کن."
    )


# ==================================================
# LOVE / GROUP EVENTS
# ==================================================

async def love(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if update.effective_chat.type == "private":
        await update.effective_message.reply_text(
            "این قابلیت را در گروه استفاده کن."
        )
        return

    members = update.effective_message.text.split()

    if len(members) >= 2:
        first = members[1]
        second = members[2] if len(members) >= 3 else "یک نفر خاص"

        percent = random.randint(1, 100)

        await update.effective_message.reply_text(
            f"❤️ میزان عشق بین {first} و {second}: {percent}%"
        )
    else:
        await update.effective_message.reply_text(
            "روش استفاده:\n/love @user1 @user2"
        )


async def hug(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if update.effective_chat.type == "private":
        await update.effective_message.reply_text(
            "این قابلیت را در گروه استفاده کن."
        )
        return

    target = "همه"

    if context.args:
        target = " ".join(context.args)

    await update.effective_message.reply_text(
        f"🫂 {update.effective_user.full_name} "
        f"برای {target} یک بغل فرستاد!"
    )


async def love_event(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if update.effective_chat.type == "private":
        await update.effective_message.reply_text(
            "این رویداد را در گروه اجرا کن."
        )
        return

    await update.effective_message.reply_text(
        "💞 رویداد عشق شروع شد!\n\n"
        "اعضا می‌توانند با دستور /love نام دو نفر را بررسی کنند."
    )


async def income_event(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if update.effective_chat.type == "private":
        await update.effective_message.reply_text(
            "این رویداد را در گروه اجرا کن."
        )
        return

    user = update.effective_user
    ensure_user(user)

    reward = random.randint(100, 500)

    conn = db()
    conn.execute(
        "UPDATE users SET coins = coins + ? WHERE user_id = ?",
        (reward, user.id),
    )
    conn.commit()
    conn.close()

    await update.effective_message.reply_text(
        f"💸 رویداد درآمد شروع شد!\n"
        f"{user.full_name} برنده {reward} سکه شد."
    )


# ==================================================
# ANTI-LINK
# ==================================================

async def anti_link(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    message = update.effective_message

    if not message or not message.text:
        return

    if message.chat.type == "private":
        return

    text = message.text.lower()

    contains_link = (
        "https://" in text
        or "http://" in text
        or "t.me/" in text
        or "telegram.me/" in text
    )

    if not contains_link:
        return

    try:
        member = await context.bot.get_chat_member(
            message.chat.id,
            update.effective_user.id,
        )

        if member.status in ("administrator", "creator"):
            return

        await message.delete()

        warning = await context.bot.send_message(
            message.chat.id,
            "⚠️ ارسال لینک در این گروه مجاز نیست.",
        )

        context.job_queue.run_once(
            delete_warning,
            8,
            data={
                "chat_id": warning.chat_id,
                "message_id": warning.message_id,
            },
        )

    except Exception as e:
        logger.warning("Anti-link error: %s", e)


async def delete_warning(
    context: ContextTypes.DEFAULT_TYPE
):
    data = context.job.data

    try:
        await context.bot.delete_message(
            chat_id=data["chat_id"],
            message_id=data["message_id"],
        )
    except Exception:
        pass


# ==================================================
# TEXT MENU
# ==================================================

async def text_router(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    message = update.effective_message
    if not message or not message.text:
        return

    text = message.text.strip()

    # Admin price input takes priority.
    if context.user_data.get("editing_price"):
        await admin_text(update, context)
        return

    if context.user_data.get("waiting_target"):
        await handle_target(update, context)
        return

    if text == "🛍 فروشگاه":
        await show_store(update, context)

    elif text == "📦 سفارش‌های من":
        await my_orders(update, context)

    elif text == "💰 کیف پول":
        await balance(update, context)

    elif text == "🎁 دعوت دوستان":
        await referrals(update, context)

    elif text == "📜 راهنمای پرداخت":
        await message.reply_text(
            "۱. محصول را از فروشگاه انتخاب کن.\n"
            "۲. یوزرنیم مقصد را بفرست.\n"
            "۳. مبلغ نمایش‌داده‌شده را پرداخت کن.\n"
            "۴. رسید را در همین ربات ارسال کن.\n"
            "۵. پس از بررسی مدیر، نتیجه اعلام می‌شود.\n\n"
            "هرگز رمز عبور یا کد ورود تلگرام را برای کسی نفرست."
        )

    elif text == "🎧 پشتیبانی":
        await message.reply_text(
            f"برای پیگیری سفارش با {SUPPORT} تماس بگیر."
        )


# ==================================================
# HELP / CANCEL
# ==================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await update.effective_message.reply_text(
        "دستورات ربات VEXORA:\n\n"
        "/start - شروع\n"
        "/admin - پنل مدیریت\n"
        "/products - نمایش محصولات\n"
        "/addproduct نام_محصول قیمت - افزودن محصول\n"
        "/delivered شماره - ثبت تحویل سفارش\n"
        "/balance - موجودی سکه\n"
        "/work - کار و دریافت سکه\n"
        "/daily - پاداش روزانه\n"
        "/pay شناسه مقدار - انتقال سکه\n"
        "/love @user1 @user2 - سنجش عشق\n"
        "/hug نام - ارسال بغل\n"
        "/loveevent - رویداد عشق\n"
        "/incomeevent - رویداد درآمد\n"
        "/cancel - لغو تغییر قیمت"
    )


async def products_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    rows = get_products()

    if not rows:
        await update.effective_message.reply_text(
            "محصولی وجود ندارد."
        )
        return

    lines = ["🛍 محصولات VEXORA\n"]

    for row in rows:
        lines.append(f"{row['name']} — {money(row['price'])}")

    await update.effective_message.reply_text("\n".join(lines))


async def cancel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    context.user_data.pop("editing_price", None)
    context.user_data.pop("waiting_target", None)
    context.user_data.pop("selected_product", None)

    await update.effective_message.reply_text(
        "عملیات جاری لغو شد.",
        reply_markup=main_menu(),
    )


# ==================================================
# ERROR HANDLER
# ==================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):
    logger.error(
        "Unhandled exception",
        exc_info=context.error,
    )


# ==================================================
# MAIN
# ==================================================

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN تنظیم نشده است. "
            "توکن را در Environment Variables هاست ثبت کن."
        )

    if ADMIN_ID == 0:
        logger.warning(
            "ADMIN_ID تنظیم نشده است؛ امکانات مدیر کار نخواهند کرد."
        )

    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("products", products_command))
    app.add_handler(CommandHandler("addproduct", add_product))
    app.add_handler(CommandHandler("delivered", delivered))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("work", work))
    app.add_handler(CommandHandler("daily", daily))
    app.add_handler(CommandHandler("pay", pay_coins))
    app.add_handler(CommandHandler("love", love))
    app.add_handler(CommandHandler("hug", hug))
    app.add_handler(CommandHandler("loveevent", love_event))
    app.add_handler(CommandHandler("incomeevent", income_event))
    app.add_handler(CommandHandler("cancel", cancel))

    # Callbacks
    app.add_handler(
        CallbackQueryHandler(
            product_selected,
            pattern=r"^product:",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            create_order,
            pattern=r"^create_order$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            payment_decision,
            pattern=r"^(approve|reject):",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            admin_callbacks,
            pattern=r"^(admin_prices|admin_orders|admin_stats|price:)",
        )
    )

    # Receipt messages
    app.add_handler(
        MessageHandler(
            filters.PHOTO | filters.Document.ALL,
            receive_receipt,
        )
    )

    # Group anti-link
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            anti_link,
        ),
        group=1,
    )

    # Text menus and pending input
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_router,
        ),
        group=2,
    )

    app.add_error_handler(error_handler)

    logger.info("VEXORA bot is starting...")
    app.run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()
