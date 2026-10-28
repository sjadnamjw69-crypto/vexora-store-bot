import os
import sqlite3
import logging
from datetime import datetime

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
CHANNEL_ID = os.getenv("CHANNEL_ID", "@Vexora1Store")
SUPPORT = "@Vexorini"
CARD_NUMBER = os.getenv("CARD_NUMBER", "")
CARD_NAME = os.getenv("CARD_NAME", "")
DB_FILE = "vexora.db"

STAR_PRICE = 3000

PRODUCTS = {
    "تدی 🧸": 55000,
    "قلب ❤️": 55000,
    "رز 🌹": 95000,
    "کادو 🎁": 95000,
    "کیک 🎂": 195000,
    "دسته گل 💐": 195000,
    "راکت 🚀": 195000,
    "شامپاین 🥂": 195000,
    "جام 🏆": 390000,
    "الماس 💎": 390000,
    "حلقه 💍": 390000,
    "پرمیوم ۳ ماهه 💎": 2990000,
    "پرمیوم ۶ ماهه 💎": 3990000,
    "پرمیوم ۱۲ ماهه 💎": 6990000,
}

STAR_PACKAGES = [50, 100, 250, 500, 1000, 2500]

MENU = ReplyKeyboardMarkup(
    [
        ["🛍 خرید"],
        ["👥 زیرمجموعه‌گیری", "🎁 مأموریت‌ها"],
        ["💰 کیف پول", "👤 حساب کاربری"],
        ["📋 پیگیری سفارش"],
        ["🛡 راهنمای خرید", "☎️ پشتیبانی"],
    ],
    resize_keyboard=True,
)


# =========================
# DATABASE
# =========================

def connect_db():
    return sqlite3.connect(DB_FILE)


def init_db():
    with connect_db() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                points INTEGER NOT NULL DEFAULT 0,
                referred_by INTEGER
            )
        """)

        con.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                product TEXT NOT NULL,
                price INTEGER NOT NULL,
                target TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'در انتظار پرداخت',
                created TEXT NOT NULL
            )
        """)


def money(amount):
    return f"{amount:,} تومان"


# =========================
# START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    referral_id = None
    if context.args and context.args[0].startswith("ref_"):
        try:
            referral_id = int(context.args[0][4:])
        except ValueError:
            pass

    if referral_id == user.id:
        referral_id = None

    with connect_db() as con:
        con.execute(
            "INSERT OR IGNORE INTO users(user_id, referred_by) VALUES(?, ?)",
            (user.id, referral_id),
        )

    context.user_data.clear()

    await update.message.reply_text(
        f"سلام {user.first_name}! 🖤\n\n"
        "به فروشگاه VEXORA خوش اومدی.\n"
        "از منوی زیر انتخاب کن:",
        reply_markup=MENU,
    )


# =========================
# PRODUCTS
# =========================

async def show_products(update, context):
    keyboard = [
        [InlineKeyboardButton(
            "⭐ خرید استارز تلگرام",
            callback_data="stars",
        )]
    ]

    for name, price in PRODUCTS.items():
        keyboard.append([
            InlineKeyboardButton(
                f"{name} | {money(price)}",
                callback_data=f"buy:{name}",
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "🌐 کانفیگ V2Ray",
            callback_data="v2ray",
        )
    ])

    await update.message.reply_text(
        "🛍 فروشگاه VEXORA\n\nمحصول موردنظرت رو انتخاب کن:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def button_handler(update, context):
    query = update.callback_query
    await query.answer()

    if query.data == "stars":
        keyboard = [
            [InlineKeyboardButton(
                f"{n} استارز | {money(n * STAR_PRICE)}",
                callback_data=f"starpack:{n}",
            )]
            for n in STAR_PACKAGES
        ]

        keyboard.append([
            InlineKeyboardButton(
                "✍️ واردکردن تعداد دلخواه",
                callback_data="customstars",
            )
        ])

        await query.message.reply_text(
            "⭐ خرید تلگرام استارز\n"
            f"نرخ هر استارز: {money(STAR_PRICE)}\n\n"
            "یک بسته انتخاب کن یا تعداد دلخواهت رو وارد کن:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if query.data == "customstars":
        context.user_data["waiting_custom_stars"] = True
        await query.message.reply_text(
            "⭐ تعداد استارز موردنظرت رو وارد کن.\n"
            "مثال: 75\nحداقل: 1\nحداکثر: 10000"
        )
        return

    if query.data.startswith("starpack:"):
        try:
            count = int(query.data.split(":")[1])
        except ValueError:
            await query.message.reply_text("تعداد نامعتبره.")
            return

        await choose_product(
            query.message,
            context,
            f"{count} استارز ⭐",
            count * STAR_PRICE,
        )
        return

    if query.data == "v2ray":
        await query.message.reply_text(
            "🌐 برای اطلاع از قیمت و موجودی کانفیگ V2Ray "
            f"به پشتیبانی پیام بده:\n{SUPPORT}"
        )
        return

    if query.data.startswith("buy:"):
        product = query.data[4:]

        if product not in PRODUCTS:
            await query.message.reply_text("محصول پیدا نشد.")
            return

        await choose_product(
            query.message,
            context,
            product,
            PRODUCTS[product],
        )


async def choose_product(message, context, product, price):
    context.user_data["target_product"] = product
    context.user_data["target_price"] = price
    context.user_data.pop("waiting_custom_stars", None)

    await message.reply_text(
        f"محصول: {product}\n"
        f"قیمت: {money(price)}\n\n"
        "آیدی تلگرام مقصد رو بفرست؛ مثلاً @username\n"
        "اگر آیدی لازم نداره بنویس: ندارم\n\n"
        "⚠️ رمز عبور یا کد ورود تلگرامت رو نفرست."
    )


# =========================
# CREATE ORDER
# =========================

async def create_order(update, context, target):
    user = update.effective_user
    product = context.user_data.get("target_product")
    price = context.user_data.get("target_price")

    if not product or price is None:
        return

    with connect_db() as con:
        cur = con.execute(
            """
            INSERT INTO orders
            (user_id, username, product, price, target, created)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user.id,
                user.username or "",
                product,
                price,
                target,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        order_id = cur.lastrowid

    context.user_data.pop("target_product", None)
    context.user_data.pop("target_price", None)
    context.user_data["target_order"] = order_id

    if CARD_NUMBER and CARD_NAME:
        payment_info = (
            f"💳 شماره کارت: {CARD_NUMBER}\n"
            f"👤 به نام: {CARD_NAME}"
        )
    else:
        payment_info = (
            "روش پرداخت هنوز توسط مدیر تنظیم نشده.\n"
            "قبل از پرداخت با پشتیبانی هماهنگ کن."
        )

    await update.message.reply_text(
        f"✅ سفارش ثبت شد!\n\n"
        f"شماره سفارش: VX{order_id}\n"
        f"محصول: {product}\n"
        f"مبلغ: {money(price)}\n"
        f"مقصد: {target}\n\n"
        f"{payment_info}\n\n"
        "پس از هماهنگی پرداخت، تصویر رسید رو همین‌جا ارسال کن.",
        reply_markup=MENU,
    )

    if ADMIN_ID:
        await context.bot.send_message(
            ADMIN_ID,
            f"🛒 سفارش جدید VX{order_id}\n"
            f"کاربر: {user.id}\n"
            f"محصول: {product}\n"
            f"مبلغ: {money(price)}\n"
            f"مقصد: {target}",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "✅ تأیید پرداخت",
                        callback_data=f"approve:{order_id}",
                    ),
                    InlineKeyboardButton(
                        "❌ رد پرداخت",
                        callback_data=f"reject:{order_id}",
                    ),
                ]
            ]),
        )


# =========================
# TEXT HANDLER
# =========================

async def text_handler(update, context):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    user = update.effective_user
    chat = update.effective_chat

    if chat.type in ("group", "supergroup"):
        msg = text.lower()

        if any(w in msg for w in ["قیمت", "چنده", "چند تومن"]):
            await update.message.reply_text(
                "🛍 برای دیدن قیمت‌های VEXORA وارد ربات شو:\n"
                "@VexoraStoreBot"
            )
        elif any(w in msg for w in ["سلام", "درود"]):
            await update.message.reply_text(
                "سلام! 👋 به VEXORA خوش اومدی.\n"
                "برای خرید: @VexoraStoreBot"
            )
        elif any(w in msg for w in ["خرید", "سفارش"]):
            await update.message.reply_text(
                "🛍 برای ثبت سفارش وارد شو:\n@VexoraStoreBot"
            )
        return

    if text == "🛍 خرید":
        await show_products(update, context)
        return

    if text == "👤 حساب کاربری":
        with connect_db() as con:
            row = con.execute(
                "SELECT points FROM users WHERE user_id=?",
                (user.id,),
            ).fetchone()

            count = con.execute(
                "SELECT COUNT(*) FROM orders WHERE user_id=?",
                (user.id,),
            ).fetchone()[0]

        await update.message.reply_text(
            f"👤 حساب کاربری\n"
            f"شناسه: {user.id}\n"
            f"امتیاز: {row[0] if row else 0}\n"
            f"تعداد سفارش‌ها: {count}",
            reply_markup=MENU,
        )
        return

    if text == "💰 کیف پول":
        await update.message.reply_text(
            "💰 موجودی فعلی: ۰ تومان\n"
            "برای راهنمایی با پشتیبانی تماس بگیر.",
            reply_markup=MENU,
        )
        return

    if text == "👥 زیرمجموعه‌گیری":
        await update.message.reply_text(
            "👥 لینک دعوت اختصاصی:\n"
            f"https://t.me/{context.bot.username}?start=ref_{user.id}\n\n"
            "توجه: امتیازدهی خودکار زیرمجموعه‌ها هنوز فعال نیست.",
            reply_markup=MENU,
        )
        return

    if text == "🎁 مأموریت‌ها":
        await update.message.reply_text(
            "🎁 پاداش‌ها:\n"
            "۳ امتیاز = ۱ استارز رایگان\n"
            "۱۸ امتیاز = ۱ گیفت تدی رایگان\n\n"
            "تحویل جوایز فعلاً با هماهنگی مدیر انجام می‌شه.",
            reply_markup=MENU,
        )
        return

    if text == "📋 پیگیری سفارش":
        with connect_db() as con:
            rows = con.execute(
                """
                SELECT id, product, price, status
                FROM orders
                WHERE user_id=?
                ORDER BY id DESC LIMIT 10
                """,
                (user.id,),
            ).fetchall()

        if not rows:
            await update.message.reply_text("هنوز سفارشی ثبت نکردی.")
            return

        result = "📋 سفارش‌های شما:\n\n"

        for oid, product, price, status in rows:
            result += (
                f"شماره: VX{oid}\n"
                f"محصول: {product}\n"
                f"مبلغ: {money(price)}\n"
                f"وضعیت: {status}\n\n"
            )

        await update.message.reply_text(result, reply_markup=MENU)
        return

    if text == "🛡 راهنمای خرید":
        await update.message.reply_text(
            "🛡 راهنمای خرید:\n"
            "۱. محصول رو انتخاب کن.\n"
            "۲. آیدی مقصد رو وارد کن.\n"
            "۳. سفارش رو بررسی کن.\n"
            "۴. قبل از پرداخت با پشتیبانی هماهنگ کن.\n"
            "۵. رسید رو ارسال کن.\n\n"
            f"پشتیبانی: {SUPPORT}",
            reply_markup=MENU,
        )
        return

    if text == "☎️ پشتیبانی":
        await update.message.reply_text(
            f"پشتیبانی VEXORA:\n{SUPPORT}",
            reply_markup=MENU,
        )
        return

    if context.user_data.get("waiting_custom_stars"):
        try:
            count = int(text)
        except ValueError:
            await update.message.reply_text(
                "لطفاً فقط عدد وارد کن؛ مثلاً 75."
            )
            return

        if not 1 <= count <= 10000:
            await update.message.reply_text(
                "تعداد باید بین ۱ تا ۱۰۰۰۰ استارز باشه."
            )
            return

        context.user_data["waiting_custom_stars"] = False

        await choose_product(
            update.message,
            context,
            f"{count} استارز ⭐",
            count * STAR_PRICE,
        )
        return

    if context.user_data.get("target_product"):
        await create_order(update, context, text)
        return

    await update.message.reply_text(
        "از منوی زیر انتخاب کن یا با پشتیبانی تماس بگیر.",
        reply_markup=MENU,
    )


# =========================
# PAYMENT RECEIPT
# =========================

async def receipt_handler(update, context):
    if not update.message or not update.message.photo:
        return

    order_id = context.user_data.get("target_order")

    if not order_id:
        await update.message.reply_text(
            "اول سفارش ثبت کن، بعد رسید رو بفرست."
        )
        return

    user = update.effective_user

    if ADMIN_ID:
        await context.bot.send_photo(
            ADMIN_ID,
            update.message.photo[-1].file_id,
            caption=(
                f"🧾 رسید سفارش VX{order_id}\n"
                f"شناسه کاربر: {user.id}"
            ),
        )

    await update.message.reply_text(
        "🧾 رسید برای بررسی به مدیر ارسال شد."
    )


# =========================
# ADMIN APPROVE / REJECT
# =========================

async def admin_order_handler(update, context):
    query = update.callback_query
    await query.answer()

    if not ADMIN_ID or query.from_user.id != ADMIN_ID:
        await query.message.reply_text("اجازه دسترسی نداری.")
        return

    action, order_text = query.data.split(":")
    order_id = int(order_text)

    with connect_db() as con:
        row = con.execute(
            "SELECT user_id FROM orders WHERE id=?",
            (order_id,),
        ).fetchone()

        if not row:
            await query.message.reply_text("سفارش پیدا نشد.")
            return

        user_id = row[0]

        status = (
            "پرداخت تأیید شد؛ در انتظار تحویل"
            if action == "approve"
            else "پرداخت رد شد"
        )

        con.execute(
            "UPDATE orders SET status=? WHERE id=?",
            (status, order_id),
        )

    message = (
        f"پرداخت سفارش VX{order_id} تأیید شد."
        if action == "approve"
        else f"پرداخت سفارش VX{order_id} تأیید نشد؛ با پشتیبانی تماس بگیر."
    )

    await context.bot.send_message(user_id, message)
    await query.message.reply_text("وضعیت سفارش به‌روزرسانی شد.")


# =========================
# DELIVERED ORDER + ROSE ANNOUNCEMENT
# =========================

async def delivered(update, context):
    if not ADMIN_ID or update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("این دستور مخصوص مدیر است.")
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "روش استفاده:\n"
            "/delivered شماره_سفارش\n"
            "مثال: /delivered 12"
        )
        return

    order_id = int(context.args[0])

    with connect_db() as con:
        row = con.execute(
            """
            SELECT user_id, product, price, status, created
            FROM orders
            WHERE id=?
            """,
            (order_id,),
        ).fetchone()

        if not row:
            await update.message.reply_text("سفارش پیدا نشد.")
            return

        user_id, product, price, status, created = row

        if status == "تحویل داده شد":
            await update.message.reply_text(
                f"سفارش VX{order_id} قبلاً تحویل‌شده ثبت شده."
            )
            return

        con.execute(
            "UPDATE orders SET status=? WHERE id=?",
            ("تحویل داده شد", order_id),
        )

    buyer = str(user_id)
    if len(buyer) > 5:
        buyer = f"{buyer[:3]}···{buyer[-2:]}"

    delivered_time = datetime.now().strftime("%Y/%m/%d · %H:%M:%S")

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                f"🌹 سفارش VX{order_id} با موفقیت تحویل داده شد!\n\n"
                f"محصول: {product}\n"
                f"کد پیگیری: VX{order_id}\n\n"
                "ممنون از خریدت از VEXORA STORE. 🌹"
            ),
        )
    except Exception:
        logging.exception("ارسال پیام خصوصی تحویل به مشتری ناموفق بود")

    announcement = (
        "🌹🌹🌹🌹🌹🌹🌹🌹🌹\n\n"
        f"👑 سفارش VX{order_id} تحویل شد!\n\n"
        f"🌹 محصول: {product}\n"
        f"✔️ خریدار: {buyer}\n"
        f"💰 مبلغ: {money(price)}\n"
        f"🪪 کد پیگیری: VX{order_id}\n"
        f"💜 ثبت سفارش: {created}\n"
        f"🌹 زمان تحویل: {delivered_time}\n"
        "⚡️ وضعیت: با موفقیت تحویل شد\n\n"
        "🌹🌹🌹🌹🌹🌹🌹🌹🌹\n\n"
        "💜 یک سفارش دیگه به مقصد رسید.\n\n"
        "🛍 خرید از VEXORA STORE"
    )

    try:
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=announcement,
        )
    except Exception:
        logging.exception("ارسال اعلان کانال ناموفق بود")
        await update.message.reply_text(
            "سفارش در دیتابیس تحویل‌شده ثبت شد، اما پیام کانال ارسال نشد. "
            "بررسی کن ربات در کانال مدیر و مجاز به ارسال پیام باشد."
        )
        return

    await update.message.reply_text(
        f"✅ سفارش VX{order_id} تحویل‌شده ثبت شد و در کانال اعلام شد."
    )


# =========================
# RUN BOT
# =========================

def main():
    if not TOKEN:
        raise RuntimeError(
            "متغیر BOT_TOKEN در تنظیمات هاست وارد نشده است."
        )

    init_db()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("delivered", delivered))

    app.add_handler(
        CallbackQueryHandler(
            admin_order_handler,
            pattern=r"^(approve|reject):",
        )
    )

    app.add_handler(CallbackQueryHandler(button_handler))

    app.add_handler(
        MessageHandler(
            filters.PHOTO & filters.ChatType.PRIVATE,
            receipt_handler,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler,
        )
    )

    print("VEXORA STORE is running.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
