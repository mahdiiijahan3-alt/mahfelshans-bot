import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)

BOT_USERNAME = "MahfelShansBot"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    keyboard = [
        [
            InlineKeyboardButton("🎁 کمپین‌ها و جوایز", callback_data="campaigns"),
        ],
        [
            InlineKeyboardButton("👤 پروفایل من", callback_data="profile"),
            InlineKeyboardButton("🎟 شانس‌های من", callback_data="chances"),
        ],
        [
            InlineKeyboardButton("👥 دعوت از دوستان", callback_data="invite"),
        ],
        [
            InlineKeyboardButton("📸 اینستاگرام", url="https://instagram.com/MAHFELSHANS"),
            InlineKeyboardButton("▶️ یوتیوب", url="https://youtube.com/@mahfelshans"),
        ],
        [
            InlineKeyboardButton("💬 پشتیبانی", callback_data="support"),
        ],
    ]

    text = (
        f"سلام {user.first_name} 👋\n\n"
        "به «محفل خوش‌شانس‌ها» خوش اومدی! 🎉\n\n"
        "از منوی زیر می‌تونی کمپین‌ها، شانس‌ها، "
        "دعوت دوستان و پشتیبانی رو ببینی."
    )

    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "راهنمای محفل خوش‌شانس‌ها:\n\n"
        "🎁 کمپین‌ها و جوایز\n"
        "👤 پروفایل\n"
        "🎟 شانس‌های من\n"
        "👥 دعوت از دوستان\n"
        "💬 پشتیبانی"
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "campaigns":
        await query.edit_message_text(
            "🎁 کمپین‌ها و جوایز\n\n"
            "در حال آماده‌سازی کمپین‌های محفل خوش‌شانس‌ها هستیم."
        )

    elif query.data == "profile":
        user = query.from_user
        await query.edit_message_text(
            f"👤 پروفایل شما\n\n"
            f"نام: {user.first_name}\n"
            f"شناسه تلگرام: {user.id}"
        )

    elif query.data == "chances":
        await query.edit_message_text(
            "🎟 شانس‌های شما\n\n"
            "فعلاً شانس ثبت‌شده‌ای ندارید."
        )

    elif query.data == "invite":
        user_id = query.from_user.id
        invite_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"

        await query.edit_message_text(
            "👥 دعوت از دوستان\n\n"
            "لینک اختصاصی معرفی شما:\n\n"
            f"{invite_link}\n\n"
            "هر کسی از طریق این لینک وارد شود، "
            "در سیستم به‌عنوان معرفی‌شده شما ثبت خواهد شد."
        )

    elif query.data == "support":
        await query.edit_message_text(
            "💬 پشتیبانی\n\n"
            "سؤال یا مشکلت رو همینجا برای ما ارسال کن."
        )


def main():
    token = os.environ.get("BOT_TOKEN")

    if not token:
        raise RuntimeError("BOT_TOKEN is not set")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(
        __import__("telegram.ext", fromlist=["CallbackQueryHandler"])
        .CallbackQueryHandler(button_handler)
    )

    print("MahfelShans bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
