import os
import re
import sqlite3
import logging
import random
from datetime import datetime, timedelta

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ChatPermissions,
)
from telegram.constants import ChatType
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
log = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or "0")
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
    "کادو
    # =========================
# ORDER CREATION
# =========================

async def create_order(update, context, target):
    user = update.effective_user
    product = context.user_data.get("target_product")
    price = context.user_data.get("target_price")

    if not product or price is None:
        await update.effective_message.reply_text(
            "اول از فروشگاه محصولت رو انتخاب کن.",
            reply_markup=MENU,
        )
        return

    target = target.strip()
    if target.lower() == "ندارم":
        target = "نیاز ندارد"

    created = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with connect_db() as con:
        cur = con.execute(
            """
            INSERT INTO orders
            (user_id, username, product, price, target, status, created)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user.id,
                user.username or "",
                product,
                int(price),
                target,
                "در انتظار پرداخت",
                created,
            ),
        )
        order_id = cur.lastrowid

    context.user_data.pop("target_product", None)
    context.user_data.pop("target_price", None)

    await update.effective_message.reply_text(
        f"سفارش شما ثبت شد.\n\n"
        f"شماره سفارش: VX{order_id}\n"
        f"محصول: {product}\n"
        f"مبلغ: {money(price)}\n"
        f"وضعیت: در انتظار پرداخت\n\n"
        f"برای پرداخت با پشتیبانی هماهنگ کن: {SUPPORT}",
        reply_markup=MENU,
    )

    if CHANNEL_ID:
        try:
            await context.bot.send_message(
                chat_id=CHANNEL_ID,
                text=(
                    "🛍 سفارش جدید VEXORA\n\n"
                    f"شماره سفارش: VX{order_id}\n"
                    f"محصول: {product}\n"
                    f"مبلغ: {money(price)}\n"
                    "وضعیت: در انتظار پرداخت"
                ),
            )
        except Exception:
            log.exception("Could not announce new order")

    if ADMIN_ID:
        try:
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "تأیید پرداخت",
                        callback_data=f"payment:yes:{order_id}",
                    ),
                    InlineKeyboardButton(
                        "رد پرداخت",
                        callback_data=f"payment:no:{order_id}",
                    ),
                ]
            ])

            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    f"سفارش جدید VX{order_id}\n"
                    f"محصول: {product}\n"
                    f"مبلغ: {money(price)}\n"
                    f"شناسه مشتری: {user.id}\n"
                    f"مقصد: {target}"
                ),
                reply_markup=keyboard,
            )
        except Exception:
            log.exception("Could not notify admin")


# =========================
# PAYMENT STATUS
# =========================

async def payment_handler(update, context):
    query = update.callback_query

    if not ADMIN_ID or query.from_user.id != ADMIN_ID:
        await query.answer("این دکمه مخصوص مدیر است.", show_alert=True)
        return

    await query.answer()

    parts = query.data.split(":")
    if len(parts) != 3 or not parts[2].isdigit():
        return

    action = parts[1]
    order_id = int(parts[2])

    if action not in ("yes", "no"):
        return

    status = (
        "پرداخت تأیید شد"
        if action == "yes"
        else "پرداخت رد شد"
    )

    with connect_db() as con:
        row = con.execute(
            "SELECT user_id, product, price, status FROM orders WHERE id=?",
            (order_id,),
        ).fetchone()

        if not row:
            await query.message.reply_text("سفارش پیدا نشد.")
            return

        user_id, product, price, old_status = row

        if old_status == "تحویل داده شد":
            await query.message.reply_text(
                "این سفارش قبلاً تحویل داده شده است."
            )
            return

        con.execute(
            "UPDATE orders SET status=? WHERE id=?",
            (status, order_id),
        )

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                f"وضعیت سفارش VX{order_id} تغییر کرد.\n"
                f"محصول: {product}\n"
                f"مبلغ: {money(price)}\n"
                f"وضعیت: {status}\n\n"
                f"پشتیبانی: {SUPPORT}"
            ),
        )
    except Exception:
        log.exception("Could not notify customer")

    try:
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=(
                f"📋 به‌روزرسانی سفارش VX{order_id}\n\n"
                f"محصول: {product}\n"
                f"وضعیت: {status}"
            ),
        )
    except Exception:
        log.exception("Could not announce payment status")

    await query.message.reply_text(
        f"وضعیت سفارش VX{order_id}: {status}"
    )


# =========================
# DELIVERED ORDER
# =========================

async def delivered(update, context):
    if not ADMIN_ID or update.effective_user.id != ADMIN_ID:
        await update.effective_message.reply_text(
            "این دستور مخصوص مدیر است."
        )
        return

    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text(
            "روش استفاده:\n/delivered شماره_سفارش\n"
            "مثال: /delivered 12"
        )
        return

    order_id = int(context.args[0])

    with connect_db() as con:
        row = con.execute(
            """
            SELECT user_id, product, price, status, created
            FROM orders WHERE id=?
            """,
            (order_id,),
        ).fetchone()

    if not row:
        await update.effective_message.reply_text(
            "سفارش پیدا نشد."
        )
        return

    user_id, product, price, status, created = row

    if status == "تحویل داده شد":
        await update.effective_message.reply_text(
            f"سفارش VX{order_id} قبلاً تحویل شده."
        )
        return

    delivered_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=(
                "✅ سفارش با موفقیت تحویل داده شد\n\n"
                f"شماره سفارش: VX{order_id}\n"
                f"محصول: {product}\n"
                f"مبلغ: {money(price)}\n"
                f"زمان ثبت: {created}\n"
                f"زمان تحویل: {delivered_at}\n"
                "وضعیت: تحویل داده شد\n\n"
                "VEXORA | فروشگاه تلگرام"
            ),
        )
    except Exception:
        await update.effective_message.reply_text(
            "ارسال اطلاعیه کانال ناموفق بود؛ "
            "وضعیت سفارش تغییر نکرد. دسترسی ربات به کانال را بررسی کن."
        )
        return

    with connect_db() as con:
        con.execute(
            """
            UPDATE orders
            SET status=?, delivered_at=?
            WHERE id=?
            """,
            ("تحویل داده شد", delivered_at, order_id),
        )

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"سفارش VX{order_id} تحویل داده شد. ممنون از خریدت.",
        )
    except Exception:
        pass

    await update.effective_message.reply_text(
        f"سفارش VX{order_id} تحویل‌شده ثبت شد."
    )


# =========================
# RECEIPT PHOTO
# =========================

async def receipt_handler(update, context):
    user = update.effective_user

    if not user or not update.message or not update.message.photo:
        return

    if not ADMIN_ID:
        await update.message.reply_text(
            "ثبت رسید فعلاً فعال نیست؛ پشتیبانی را بررسی کن."
        )
        return

    caption = (
        f"رسید پرداخت از مشتری\n"
        f"شناسه مشتری: {user.id}\n"
        f"نام کاربری: @{user.username or 'ندارد'}"
    )

    try:
        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=update.message.photo[-1].file_id,
            caption=caption,
        )
        await update.message.reply_text(
            "رسید برای مدیر ارسال شد. منتظر بررسی پرداخت باش."
        )
    except Exception:
        log.exception("Receipt forwarding failed")
        await update.message.reply_text(
            "ارسال رسید ناموفق بود؛ با پشتیبانی تماس بگیر."
        )


# =========================
# ORDERS / WALLET / ACCOUNT
# =========================

async def my_orders(update, context):
    user_id = update.effective_user.id

    with connect_db() as con:
        rows = con.execute(
            """
            SELECT id, product, price, status, created
            FROM orders
            WHERE user_id=?
            ORDER BY id DESC LIMIT 10
            """,
            (user_id,),
        ).fetchall()

    if not rows:
        await update.message.reply_text(
            "هنوز سفارشی ثبت نکردی."
        )
        return

    lines = ["📋 آخرین سفارش‌های تو:\n"]

    for order_id, product, price, status, created in rows:
        lines.append(
            f"شماره: VX{order_id}\n"
            f"محصول: {product}\n"
            f"مبلغ: {money(price)}\n"
            f"وضعیت: {status}\n"
            f"زمان: {created}\n"
        )

    await update.message.reply_text("\n".join(lines))


async def wallet(update, context):
    user_id = update.effective_user.id
    ensure_user(user_id)

    with connect_db() as con:
        row = con.execute(
            "SELECT balance, points FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()

    balance, points = row or (0, 0)

    await update.message.reply_text(
        f"💰 کیف پول مجازی\n"
        f"موجودی: {money(balance)}\n"
        f"امتیاز دعوت: {points}"
    )


async def account(update, context):
    user = update.effective_user
    ensure_user(user.id)

    with connect_db() as con:
        row = con.execute(
            "SELECT points, balance, mood FROM users WHERE user_id=?",
            (user.id,),
        ).fetchone()

    points, balance, mood = row or (0, 0, 50)

    await update.message.reply_text(
        f"👤 حساب کاربری\n\n"
        f"نام: {user.first_name}\n"
        f"شناسه: {user.id}\n"
        f"امتیاز: {points}\n"
        f"پول مجازی: {money(balance)}\n"
        f"حال: {mood}/100"
    )


async def referral(update, context):
    user_id = update.effective_user.id
    bot = await context.bot.get_me()

    await update.message.reply_text(
        "👥 سیستم دعوت VEXORA\n\n"
        f"لینک اختصاصی تو:\n"
        f"https://t.me/{bot.username}?start=ref_{user_id}\n\n"
        "هر عضو جدیدی که با لینک تو وارد شود، "
        "یک امتیاز دعوت ثبت می‌شود.\n"
        "۳ امتیاز: یک استارز هدیه\n"
        "۱۸ امتیاز: یک گیفت تدی هدیه\n\n"
        "توجه: تحویل هدایا فعلاً با هماهنگی پشتیبانی است."
    )


async def missions(update, context):
    await update.message.reply_text(
        "🎁 مأموریت‌های VEXORA\n\n"
        "۱ امتیاز: دعوت یک عضو جدید\n"
        "۳ امتیاز: یک استارز هدیه\n"
        "۱۸ امتیاز: یک گیفت تدی هدیه\n\n"
        "برای بررسی امتیازها از کیف پول استفاده کن."
    )


async def help_buy(update, context):
    await update.message.reply_text(
        "راهنمای خرید:\n"
        "۱. محصول را انتخاب کن.\n"
        "۲. آیدی مقصد را بفرست.\n"
        "۳. برای پرداخت با پشتیبانی هماهنگ کن.\n"
        "۴. رسید را در همین ربات ارسال کن.\n"
        "۵. بعد از بررسی، وضعیت سفارش اعلام می‌شود.\n\n"
        "رمز عبور و کد ورود تلگرام را برای هیچ‌کس نفرست."
    )


async def support(update, context):
    await update.message.reply_text(
        f"☎️ پشتیبانی VEXORA\n{SUPPORT}"
    )


# =========================
# GROUP ECONOMY
# =========================

async def balance_command(update, context):
    user = update.effective_user
    ensure_user(user.id)

    with connect_db() as con:
        row = con.execute(
            "SELECT balance, mood FROM users WHERE user_id=?",
            (user.id,),
        ).fetchone()

    balance, mood = row or (0, 50)

    await update.effective_message.reply_text(
        f"💰 پول مجازی: {money(balance)}\n"
        f"حال: {mood}/100"
    )


async def work(update, context):
    user = update.effective_user
    ensure_user(user.id)

    now = datetime.now()

    with connect_db() as con:
        row = con.execute(
            "SELECT last_work FROM users WHERE user_id=?",
            (user.id,),
        ).fetchone()

        last_work = row[0] if row else None

        if last_work:
            try:
                last = datetime.fromisoformat(last_work)
                remaining = 300 - int((now - last).total_seconds())

                if remaining > 0:
                    await update.effective_message.reply_text(
                        f"هنوز خسته‌ای! {remaining} ثانیه دیگه دوباره کار کن."
                    )
                    return
            except ValueError:
                pass

        event = context.chat_data.get("income_event", False)
        multiplier = 200 if event else 1
        earned = random.randint(1000, 5000) * multiplier

        con.execute(
            """
            UPDATE users
            SET balance=balance+?, last_work=?
            WHERE user_id=?
            """,
            (earned, now.isoformat(), user.id),
        )

    await update.effective_message.reply_text(
        f"💼 کار کردی و {money(earned)} به دست آوردی!"
        + ("\n🔥 ایونت درآمد فعال بود!" if multiplier > 1 else "")
    )


async def pay_virtual(update, context):
    message = update.effective_message
    sender = update.effective_user

    if not message.reply_to_message:
        await message.reply_text(
            "برای انتقال پول، روی پیام فرد موردنظر ریپلای کن و بنویس:\n"
            "/pay 1000"
        )
        return

    target = message.reply_to_message.from_user

    if target.is_bot or target.id == sender.id:
        await message.reply_text("انتقال به خودت یا ربات مجاز نیست.")
        return

    if not context.args or not context.args[0].isdigit():
        await message.reply_text("مبلغ را وارد کن؛ مثال: /pay 1000")
        return

    amount = int(context.args[0])

    if amount <= 0:
        await message.reply_text("مبلغ باید بیشتر از صفر باشد.")
        return

    ensure_user(sender.id)
    ensure_user(target.id)

    with connect_db() as con:
        row = con.execute(
            "SELECT balance FROM users WHERE user_id=?",
            (sender.id,),
        ).fetchone()

        if not row or row[0] < amount:
            await message.reply_text("موجودی مجازی کافی نیست.")
            return

        con.execute(
            "UPDATE users SET balance=balance-? WHERE user_id=?",
            (amount, sender.id),
        )
        con.execute(
            "UPDATE users SET balance=balance+? WHERE user_id=?",
            (amount, target.id),
        )

    await message.reply_text(
        f"انتقال انجام شد: {money(amount)}\n"
        f"گیرنده: {target.first_name}"
    )


async def mood(update, context):
    user_id = update.effective_user.id
    ensure_user(user_id)

    with connect_db() as con:
        row = con.execute(
            "SELECT mood FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()

    value = row[0] if row else 50

    await update.effective_message.reply_text(
        f"حال فعلی تو: {value}/100"
    )


# =========================
# LOVE ACTIONS
# =========================

async def group_text_handler(update, context):
    message = update.effective_message
    user = update.effective_user

    if not message or not user or user.is_bot:
        return

    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return

    text_value = (message.text or "").strip().lower()

    # Simple anti-link rule: delete links from non-admins.
    if re.search(r"(https?://|t\.me/|www\.)", text_value):
        try:
            member = await context.bot.get_chat_member(
                message.chat_id,
                user.id,
            )
            if member.status not in ("administrator", "creator"):
                await message.delete()
                await context.bot.send_message(
                    chat_id=message.chat_id,
                    text="⚠️ ارسال لینک برای اعضا مجاز نیست.",
                )
                return
        except Exception:
            log.exception("Anti-link check failed")

    if text_value.startswith(("بوس", "😘", "بغل", "🤗")):
        replied = message.reply_to_message

        if not replied or not replied.from_user:
            await message.reply_text(
                "برای بوس یا بغل، روی پیام یک نفر ریپلای کن."
            )
            return

        target = replied.from_user

        if target.is_bot or target.id == user.id:
            await message.reply_text("این کار فقط برای عضو دیگری ممکنه.")
            return

        ensure_user(user.id)
        ensure_user(target.id)

        love_event = context.chat_data.get("love_event", False)
        multiplier = 156 if love_event else 1
        reward = random.randint(100, 500) * multiplier

        with connect_db() as con:
            con.execute(
                """
                UPDATE users
                SET balance=balance+?,
                    mood=MIN(100, mood+10)
                WHERE user_id=?
                """,
                (reward, user.id),
            )
            con.execute(
                """
                UPDATE users
                SET balance=balance+?,
                    mood=MIN(100, mood+10)
                WHERE user_id=?
                """,
                (reward, target.id),
            )

        action = "بوسه 😘" if text_value.startswith(("بوس", "😘")) else "بغل 🤗"

        await message.reply_text(
            f"{user.first_name} برای {target.first_name} {action} فرستاد!\n"
            f"هر دو {money(reward)} پول مجازی گرفتند."
            + ("\n💖 ایونت عشق فعاله؛ جایزه ۱۵۶ برابری!" if love_event else "")
        )


# =========================
# EVENTS
# =========================

async def is_group_admin(update, context):
    if update.effective_chat.type not in (
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    ):
        await update.effective_message.reply_text(
            "این دستور فقط داخل گروه کار می‌کنه."
        )
        return False

    member = await context.bot.get_chat_member(
        update.effective_chat.id,
        update.effective_user.id,
    )

    if member.status not in ("administrator", "creator"):
        await update.effective_message.reply_text(
            "فقط مدیران گروه می‌تونن ایونت رو شروع کنن."
        )
        return False

    return True


async def end_event(context):
    data = context.job.data
    chat_id = data["chat_id"]
    event_type = data["event_type"]

    context.application.chat_data[chat_id][event_type] = False

    title = "عشق" if event_type == "love_event" else "درآمد"

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"⏰ ایونت {title} به پایان رسید!",
    )


async def start_event(update, context, event_type, duration, multiplier):
    if not await is_group_admin(update, context):
        return

    chat_id = update.effective_chat.id
    chat_data = context.application.chat_data[chat_id]

    if chat_data.get(event_type):
        await update.effective_message.reply_text(
            "این ایونت همین الان فعاله."
        )
        return

    chat_data[event_type] = True

    context.job_queue.run_once(
        end_event,
        when=duration,
        data={
            "chat_id": chat_id,
            "event_type": event_type,
        },
        name=f"{event_type}_{chat_id}",
    )

    title = "عشق" if event_type == "love_event" else "درآمد"

    await update.effective_message.reply_text(
        f"🔥 ایونت {title} شروع شد!\n"
        f"مدت: {duration // 60} دقیقه\n"
        f"جایزه: {multiplier} برابر"
    )


async def love_event(update, context):
    a
