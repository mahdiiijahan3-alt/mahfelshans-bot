import os
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

BOT_USERNAME = "MahfelShansBot"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    keyboard = [
        [InlineKeyboardButton("🎁 کمپین‌ها و جوایز", callback_data="campaigns")],
        [InlineKeyboardButton("👤 پروفایل من", callback_data="profile")],
        [InlineKeyboardButton("🎟 شانس‌های من", callback_data="chances")],
        [InlineKeyboardButton("👥 دعوت از دوستان", callback_data="invite")],
        [
            InlineKeyboardButton(
                "📸 اینستاگرام",
                url="https://instagram.com/MAHFELSHANS"
            )
        ],
        [
            InlineKeyboardButton(
                "▶️ یوتیوب",
                url="https://youtube.com/@mahfelshans"
            )
        ],
        [InlineKeyboardButton("💬 پشتیبانی", callback_data="support")],
    ]

    text = f"""
🎉 سلام {user.first_name} عزیز!

به «محفل خوش‌شانس‌ها» خوش اومدی ❤️

اینجا می‌تونی در کمپین‌ها و برنامه‌های ویژه محفل شرکت کنی، شانس‌هات رو ببینی و دوستانت رو دعوت کنی.

👇 از منوی زیر شروع کن:
"""

    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ راهنمای محفل\n\n"
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
        await query.message.reply_text(
            "🎁 کمپین‌ها و جوایز\n\n"
            "به‌زودی کمپین‌های محفل از همین قسمت نمایش داده می‌شوند."
        )

    elif query.data == "profile":
        user = query.from_user
        await query.message.reply_text(
            f"👤 پروفایل شما\n\n"
            f"نام: {user.first_name}\n"
            f"شناسه: {user.id}"
        )

    elif query.data == "chances":
        await query.message.reply_text(
            "🎟 شانس‌های من\n\n"
            "فعلاً شانس ثبت‌شده‌ای ندارید."
        )

    elif query.data == "invite":
        user_id = query.from_user.id
        invite_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"

        await query.message.reply_text(
            "👥 دعوت از دوستان\n\n"
            "این لینک اختصاصی شماست:\n\n"
            f"{invite_link}\n\n"
            "هر دوستی که از لینک شما وارد شود، در سیستم به عنوان معرفی شما ثبت خواهد شد."
        )

    elif query.data == "support":
        await query.message.reply_text(
            "💬 پشتیبانی\n\n"
            "برای ارتباط با پشتیبانی، پیام خود را همینجا ارسال کنید."
        )


async def main():
    token = os.environ.get("BOT_TOKEN")

    if not token:
        raise RuntimeError("BOT_TOKEN تنظیم نشده است.")

    port = int(os.environ.get("PORT", "10000"))
    render_url = os.environ.get("RENDER_EXTERNAL_URL")

    if not render_url:
        raise RuntimeError("RENDER_EXTERNAL_URL تنظیم نشده است.")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(button_handler))

    await app.initialize()
    await app.start()

    await app.bot.set_webhook(
        url=f"{render_url}/telegram",
    )

    await app.updater.start_webhook(
        listen="0.0.0.0",
        port=port,
        url_path="telegram",
        webhook_url=f"{render_url}/telegram",
    )

    logging.info("MahfelShans bot is running on Render.")

    import asyncio
    await asyncio.Event().wait()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
