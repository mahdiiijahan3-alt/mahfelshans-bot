import os
import sqlite3
import logging
import asyncio
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# =========================
# SETTINGS
# =========================

BOT_USERNAME = "MahfelShansBot"
DB_FILE = "mahfelshans.db"

INSTAGRAM_URL = "https://instagram.com/MAHFELSHANS"
YOUTUBE_URL = "https://youtube.com/@mahfelshans"
TELEGRAM_CHANNEL_URL = "https://t.me/MahfelShans"

# =========================================================
# مهم:
# اینجا آیدی عددی تلگرام خودت را قرار بده
# مثال:
# ADMIN_IDS = {5931155812}
#
# فعلاً عدد نمونه است و باید با آیدی خودت عوض شود.
# =========================================================

ADMIN_IDS = {
    5931155812
}


# =========================
# DATABASE
# =========================

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():

    conn = get_db()

    # کاربران
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            first_name TEXT,
            username TEXT,
            chances INTEGER DEFAULT 0,
            invited_by INTEGER,
            created_at TEXT
        )
    """)

    # معرفی‌ها
    conn.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER NOT NULL,
            referred_id INTEGER NOT NULL UNIQUE,
            created_at TEXT
        )
    """)

    # کمپین‌ها
    conn.execute("""
        CREATE TABLE IF NOT EXISTS campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            prize TEXT,
            active INTEGER DEFAULT 1,
            created_at TEXT
        )
    """)

    # آمار شبکه‌های اجتماعی
    conn.execute("""
        CREATE TABLE IF NOT EXISTS social_stats (
            id INTEGER PRIMARY KEY,
            youtube_subscribers INTEGER DEFAULT 0,
            instagram_followers INTEGER DEFAULT 0,
            updated_at TEXT
        )
    """)

    # ساخت رکورد اولیه آمار
    stats = conn.execute(
        "SELECT id FROM social_stats WHERE id = 1"
    ).fetchone()

    if not stats:
        conn.execute(
            """
            INSERT INTO social_stats
            (id, youtube_subscribers, instagram_followers, updated_at)
            VALUES (1, 0, 0, ?)
            """,
            (datetime.utcnow().isoformat(),)
        )

    # کمپین اولیه
    count = conn.execute(
        "SELECT COUNT(*) FROM campaigns"
    ).fetchone()[0]

    if count == 0:
        conn.execute(
            """
            INSERT INTO campaigns
            (title, description, prize, active, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "اولین کمپین محفل",
                "جزئیات کمپین به‌زودی اعلام می‌شود.",
                "جایزه ویژه محفل",
                1,
                datetime.utcnow().isoformat()
            )
        )

    conn.commit()
    conn.close()


# =========================
# ADMIN CHECK
# =========================

def is_admin(user_id):
    return user_id in ADMIN_IDS


# =========================
# SOCIAL STATS
# =========================

def get_social_stats():

    conn = get_db()

    row = conn.execute(
        """
        SELECT youtube_subscribers, instagram_followers
        FROM social_stats
        WHERE id = 1
        """
    ).fetchone()

    conn.close()

    if not row:
        return 0, 0

    return (
        row["youtube_subscribers"],
        row["instagram_followers"]
    )


def set_youtube_subscribers(number):

    conn = get_db()

    conn.execute(
        """
        UPDATE social_stats
        SET youtube_subscribers = ?,
            updated_at = ?
        WHERE id = 1
        """,
        (
            number,
            datetime.utcnow().isoformat()
        )
    )

    conn.commit()
    conn.close()


# =========================
# START
# =========================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    conn = get_db()

    existing = conn.execute(
        "SELECT id FROM users WHERE id = ?",
        (user.id,)
    ).fetchone()

    if not existing:

        referrer_id = None

        if context.args:

            arg = context.args[0]

            if arg.startswith("ref_"):

                possible_referrer = arg[4:]

                if possible_referrer.isdigit():

                    possible_referrer = int(
                        possible_referrer
                    )

                    if possible_referrer != user.id:

                        referrer_exists = conn.execute(
                            "SELECT id FROM users WHERE id = ?",
                            (possible_referrer,)
                        ).fetchone()

                        if referrer_exists:
                            referrer_id = possible_referrer

        conn.execute(
            """
            INSERT INTO users
            (id, first_name, username, chances, invited_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user.id,
                user.first_name or "",
                user.username or "",
                0,
                referrer_id,
                datetime.utcnow().isoformat()
            )
        )

        if referrer_id:

            try:

                conn.execute(
                    """
                    INSERT INTO referrals
                    (referrer_id, referred_id, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (
                        referrer_id,
                        user.id,
                        datetime.utcnow().isoformat()
                    )
                )

                conn.execute(
                    """
                    UPDATE users
                    SET chances = chances + 1
                    WHERE id = ?
                    """,
                    (referrer_id,)
                )

            except sqlite3.IntegrityError:
                pass

        conn.commit()

    else:

        conn.execute(
            """
            UPDATE users
            SET first_name = ?, username = ?
            WHERE id = ?
            """,
            (
                user.first_name or "",
                user.username or "",
                user.id
            )
        )

        conn.commit()

    conn.close()

    youtube_subscribers, instagram_followers = get_social_stats()

    keyboard = [

        [
            InlineKeyboardButton(
                "📢 عضویت در کانال محفل",
                url=TELEGRAM_CHANNEL_URL
            )
        ],

        [
            InlineKeyboardButton(
                "🎁 کمپین‌ها و جوایز",
                callback_data="campaigns"
            )
        ],

        [
            InlineKeyboardButton(
                "👤 پروفایل من",
                callback_data="profile"
            ),
            InlineKeyboardButton(
                "🎟 شانس‌های من",
                callback_data="chances"
            )
        ],

        [
            InlineKeyboardButton(
                "👥 دعوت از دوستان",
                callback_data="invite"
            )
        ],

        [
            InlineKeyboardButton(
                "📸 اینستاگرام",
                url=INSTAGRAM_URL
            ),
            InlineKeyboardButton(
                "▶️ یوتیوب",
                url=YOUTUBE_URL
            )
        ],

        [
            InlineKeyboardButton(
                "📊 آمار محفل",
                callback_data="stats"
            )
        ],

        [
            InlineKeyboardButton(
                "💬 پشتیبانی",
                callback_data="support"
            )
        ],
    ]

    text = f"""
🎉 سلام {user.first_name or 'دوست عزیز'}!

به «محفل خوش‌شانس‌ها» خوش اومدی ❤️

🎁 کمپین‌ها و جوایز
🎟 مدیریت شانس‌ها
👥 دعوت از دوستان
📢 کانال رسمی محفل

📊 آمار فعلی یوتیوب:
▶️ {youtube_subscribers:,} مشترک

👇 از منوی زیر شروع کن:
"""

    if update.message:

        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


# =========================
# HELP
# =========================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "ℹ️ راهنمای محفل\n\n"
        "📢 کانال رسمی\n"
        "🎁 کمپین‌ها و جوایز\n"
        "👤 پروفایل من\n"
        "🎟 شانس‌های من\n"
        "👥 دعوت از دوستان\n"
        "📊 آمار محفل\n"
        "💬 پشتیبانی\n\n"
        "برای شروع /start را بزنید."
    )


# =========================
# PROFILE
# =========================

async def show_profile(query):

    user = query.from_user

    conn = get_db()

    row = conn.execute(
        """
        SELECT * FROM users
        WHERE id = ?
        """,
        (user.id,)
    ).fetchone()

    referral_count = conn.execute(
        """
        SELECT COUNT(*) FROM referrals
        WHERE referrer_id = ?
        """,
        (user.id,)
    ).fetchone()[0]

    conn.close()

    if not row:

        await query.message.reply_text(
            "ابتدا /start را بزنید."
        )

        return

    username = (
        f"@{row['username']}"
        if row["username"]
        else "ندارد"
    )

    await query.message.reply_text(
        f"👤 پروفایل من\n\n"
        f"نام: {row['first_name']}\n"
        f"نام کاربری: {username}\n"
        f"شناسه کاربری: {row['id']}\n\n"
        f"👥 معرفی موفق: {referral_count} نفر\n"
        f"🎟 شانس‌های من: {row['chances']}"
    )


# =========================
# CHANCES
# =========================

async def show_chances(query):

    user_id = query.from_user.id

    conn = get_db()

    row = conn.execute(
        """
        SELECT chances FROM users
        WHERE id = ?
        """,
        (user_id,)
    ).fetchone()

    conn.close()

    chances = row["chances"] if row else 0

    await query.message.reply_text(
        f"🎟 شانس‌های من\n\n"
        f"تعداد شانس‌های شما: {chances}\n\n"
        f"👥 با معرفی دوستان می‌توانید شانس‌های بیشتری به دست بیاورید."
    )


# =========================
# INVITE
# =========================

async def show_invite(query):

    user_id = query.from_user.id

    invite_link = (
        f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
    )

    conn = get_db()

    count = conn.execute(
        """
        SELECT COUNT(*) FROM referrals
        WHERE referrer_id = ?
        """,
        (user_id,)
    ).fetchone()[0]

    conn.close()

    await query.message.reply_text(
        f"👥 دعوت از دوستان\n\n"
        f"تعداد معرفی موفق شما: {count}\n\n"
        f"🔗 لینک اختصاصی شما:\n"
        f"{invite_link}\n\n"
        f"لینک را برای دوستانت ارسال کن.\n\n"
        f"با ورود موفق دوست جدید، یک شانس برای شما ثبت می‌شود. 🎟"
    )


# =========================
# CAMPAIGNS
# =========================

async def show_campaigns(query):

    conn = get_db()

    campaigns = conn.execute(
        """
        SELECT * FROM campaigns
        WHERE active = 1
        ORDER BY id DESC
        """
    ).fetchall()

    conn.close()

    if not campaigns:

        await query.message.reply_text(
            "🎁 در حال حاضر کمپین فعالی وجود ندارد."
        )

        return

    text = "🎁 کمپین‌های فعال محفل\n\n"

    for campaign in campaigns:

        text += (
            f"🏆 {campaign['title']}\n"
            f"🎁 جایزه: {campaign['prize']}\n"
            f"📝 {campaign['description']}\n\n"
        )

    await query.message.reply_text(text)


# =========================
# SOCIAL STATS
# =========================

async def show_stats(query):

    youtube_subscribers, instagram_followers = get_social_stats()

    await query.message.reply_text(
        f"📊 آمار محفل\n\n"
        f"▶️ مشترکین یوتیوب: {youtube_subscribers:,}\n"
        f"📸 دنبال‌کنندگان اینستاگرام: {instagram_followers:,}\n\n"
        f"📢 کانال رسمی:\n"
        f"@MahfelShans"
    )


# =========================
# SUPPORT
# =========================

async def show_support(query):

    await query.message.reply_text(
        "💬 پشتیبانی محفل\n\n"
        "پیام خودت را همینجا ارسال کن.\n"
        "پیام شما برای بررسی پشتیبانی دریافت می‌شود."
    )


async def receive_support_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    text = update.message.text

    if text.startswith("/"):
        return

    await update.message.reply_text(
        "✅ پیام شما دریافت شد.\n\n"
        "پشتیبانی محفل در حال بررسی پیام شماست."
    )


# =========================
# ADMIN PANEL
# =========================

async def admin_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not is_admin(user.id):

        await update.message.reply_text(
            "⛔ شما دسترسی مدیریت ندارید."
        )

        return

    youtube_subscribers, instagram_followers = get_social_stats()

    keyboard = [

        [
            InlineKeyboardButton(
                "▶️ تنظیم آمار یوتیوب",
                callback_data="admin_youtube"
            )
        ],

        [
            InlineKeyboardButton(
                "📊 مشاهده آمار",
                callback_data="admin_stats"
            )
        ],

    ]

    await update.message.reply_text(
        f"⚙️ پنل مدیریت محفل\n\n"
        f"▶️ یوتیوب: {youtube_subscribers:,}\n"
        f"📸 اینستاگرام: {instagram_followers:,}\n\n"
        f"یکی از گزینه‌ها را انتخاب کن:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================
# ADMIN YOUTUBE
# =========================

async def admin_youtube(query):

    if not is_admin(query.from_user.id):

        await query.message.reply_text(
            "⛔ دسترسی غیرمجاز."
        )

        return

    await query.message.reply_text(
        "▶️ تنظیم آمار یوتیوب\n\n"
        "عدد جدید را به صورت عدد خالی ارسال کن.\n\n"
        "مثال:\n"
        "100000\n\n"
        "یعنی ۱۰۰ هزار مشترک."
    )


# =========================
# ADMIN STATS
# =========================

async def admin_stats(query):

    if not is_admin(query.from_user.id):

        await query.message.reply_text(
            "⛔ دسترسی غیرمجاز."
        )

        return

    youtube_subscribers, instagram_followers = get_social_stats()

    await query.message.reply_text(
        f"📊 آمار ثبت‌شده\n\n"
        f"▶️ یوتیوب: {youtube_subscribers:,}\n"
        f"📸 اینستاگرام: {instagram_followers:,}"
    )


# =========================
# SET YOUTUBE COMMAND
# =========================

async def set_youtube_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    if not is_admin(user.id):

        await update.message.reply_text(
            "⛔ شما دسترسی مدیریت ندارید."
        )

        return

    if not context.args:

        await update.message.reply_text(
            "❌ عدد را وارد نکردی.\n\n"
            "مثال:\n"
            "/setyoutube 100000"
        )

        return

    value = context.args[0].replace(",", "").replace("_", "")

    if not value.isdigit():

        await update.message.reply_text(
            "❌ فقط عدد وارد کن.\n\n"
            "مثال:\n"
            "/setyoutube 100000"
        )

        return

    number = int(value)

    if number < 0:

        await update.message.reply_text(
            "❌ عدد نمی‌تواند منفی باشد."
        )

        return

    set_youtube_subscribers(number)

    await update.message.reply_text(
        f"✅ آمار یوتیوب تغییر کرد.\n\n"
        f"▶️ تعداد مشترکین:\n"
        f"{number:,}"
    )


# =========================
# BUTTON HANDLER
# =========================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    if query.data == "campaigns":

        await show_campaigns(query)

    elif query.data == "profile":

        await show_profile(query)

    elif query.data == "chances":

        await show_chances(query)

    elif query.data == "invite":

        await show_invite(query)

    elif query.data == "stats":

        await show_stats(query)

    elif query.data == "support":

        await show_support(query)

    elif query.data == "admin_youtube":

        await admin_youtube(query)

    elif query.data == "admin_stats":

        await admin_stats(query)


# =========================
# MAIN
# =========================

async def main():

    token = os.environ.get("BOT_TOKEN")

    if not token:

        raise RuntimeError(
            "BOT_TOKEN تنظیم نشده است."
        )

    render_url = os.environ.get(
        "RENDER_EXTERNAL_URL"
    )

    if not render_url:

        raise RuntimeError(
            "RENDER_EXTERNAL_URL تنظیم نشده است."
        )

    port = int(
        os.environ.get(
            "PORT",
            "10000"
        )
    )

    init_db()

    app = (
        Application.builder()
        .token(token)
        .build()
    )

    # Commands

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "help",
            help_command
        )
    )

    app.add_handler(
        CommandHandler(
            "admin",
            admin_command
        )
    )

    app.add_handler(
        CommandHandler(
            "setyoutube",
            set_youtube_command
        )
    )

    # Buttons

    app.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    # Messages

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            receive_support_message
        )
    )

    await app.initialize()

    await app.start()

    await app.updater.start_webhook(
        listen="0.0.0.0",
        port=port,
        url_path="telegram",
        webhook_url=f"{render_url}/telegram",
    )

    logging.info(
        "MahfelShans bot is running."
    )

    await asyncio.Event().wait()


# =========================
# RUN
# =========================

if __name__ == "__main__":

    asyncio.run(main())
