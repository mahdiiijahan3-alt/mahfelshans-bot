import os
import sqlite3
import logging
import random
import asyncio
from datetime import datetime, timezone

import requests

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from telegram.constants import ParseMode

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# ============================================================
# MAHFEL SHANS HA
# محفل خوش‌شانس‌ها
# MAIN.PY - CLEAN VERSION
# ============================================================


# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

BOT_USERNAME = os.getenv(
    "BOT_USERNAME",
    "MahfelShansBot"
).replace("@", "").strip()

TELEGRAM_CHANNEL = os.getenv(
    "TELEGRAM_CHANNEL",
    "@MahfelShans"
).strip()

INSTAGRAM_URL = os.getenv(
    "INSTAGRAM_URL",
    "https://instagram.com/MAHFELSHANS"
).strip()

YOUTUBE_URL = os.getenv(
    "YOUTUBE_URL",
    "https://youtube.com/@mahfelshans"
).strip()

SUPPORT_USERNAME = os.getenv(
    "SUPPORT_USERNAME",
    "@MahdiJahanshahi"
).strip()

DATABASE = os.getenv(
    "DATABASE",
    "mahfelshans.db"
).strip()

YOUTUBE_API_KEY = os.getenv(
    "YOUTUBE_API_KEY",
    ""
).strip()

YOUTUBE_CHANNEL_ID = os.getenv(
    "YOUTUBE_CHANNEL_ID",
    ""
).strip()

RENDER_EXTERNAL_URL = os.getenv(
    "RENDER_EXTERNAL_URL",
    ""
).strip()

PORT = int(
    os.getenv("PORT", "10000")
)

WEBHOOK_PATH = os.getenv(
    "WEBHOOK_PATH",
    "mahfelshans"
).strip("/")


# ------------------------------------------------------------
# ADMIN IDS
# ------------------------------------------------------------

ADMIN_IDS = set()

for value in os.getenv("ADMIN_IDS", "").split(","):
    value = value.strip()

    if value:
        try:
            ADMIN_IDS.add(int(value))
        except ValueError:
            pass


# ------------------------------------------------------------
# SYSTEM SETTINGS
# ------------------------------------------------------------

ACTIVATION_TARGET = int(
    os.getenv(
        "ACTIVATION_TARGET",
        "100000"
    )
)

AUTO_POST_ENABLED = (
    os.getenv(
        "AUTO_POST_ENABLED",
        "1"
    ).lower()
    in ("1", "true", "yes", "on")
)

AUTO_POST_HOURS = int(
    os.getenv(
        "AUTO_POST_HOURS",
        "2"
    )
)

RULES_VERSION = "2.0"

# رایگان فعال
FREE_REGISTRATION_ENABLED = True

# پرداختی فعلاً خاموش
PAID_REGISTRATION_ENABLED = False

# عضویت تلگرام برای شرایط مسابقه
TELEGRAM_MEMBERSHIP_REQUIRED = True


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format=(
        "%(asctime)s | "
        "%(levelname)s | "
        "%(name)s | "
        "%(message)s"
    ),
    level=logging.INFO,
)

logger = logging.getLogger(
    "MAHFELSHANS"
)


# ============================================================
# DATABASE
# ============================================================

def db():
    connection = sqlite3.connect(
        DATABASE,
        check_same_thread=False,
        timeout=30,
    )

    connection.row_factory = sqlite3.Row

    return connection


def now():
    return datetime.now(
        timezone.utc
    ).isoformat()


def init_db():
    connection = db()
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            referred_by INTEGER DEFAULT NULL,
            referral_count INTEGER DEFAULT 0,
            chances INTEGER DEFAULT 1,
            registered INTEGER DEFAULT 0,
            registration_type TEXT DEFAULT NULL,
            rules_accepted INTEGER DEFAULT 0,
            blocked INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            registered_at TEXT DEFAULT NULL,
            last_seen TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inviter_id INTEGER NOT NULL,
            invited_id INTEGER UNIQUE NOT NULL,
            chance_awarded INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            prize TEXT NOT NULL,
            active INTEGER DEFAULT 1,
            draw_completed INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS participations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL,
            telegram_id INTEGER NOT NULL,
            chance_count INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            UNIQUE(campaign_id, telegram_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS winners (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL,
            telegram_id INTEGER NOT NULL,
            prize TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rule_acceptances (
            telegram_id INTEGER PRIMARY KEY,
            version TEXT NOT NULL,
            accepted_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            admin_reply TEXT DEFAULT NULL,
            status TEXT DEFAULT 'open',
            created_at TEXT NOT NULL,
            replied_at TEXT DEFAULT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    defaults = {
        "instagram_followers": "0",
        "youtube_followers": "0",
        "telegram_followers": "0",
        "activation_target": str(ACTIVATION_TARGET),
        "networks_activated": "0",
        "rules_version": RULES_VERSION,
        "last_auto_post": "",
        "last_youtube_check": "",
    }

    for key, value in defaults.items():
        cursor.execute(
            """
            INSERT OR IGNORE INTO settings(
                key,
                value
            )
            VALUES (?, ?)
            """,
            (
                key,
                value,
            ),
        )

    connection.commit()

    connection.close()


def get_setting(
    key,
    default=None
):
    connection = db()

    row = connection.execute(
        """
        SELECT value
        FROM settings
        WHERE key=?
        """,
        (key,),
    ).fetchone()

    connection.close()

    if row is None:
        return default

    return row["value"]


def set_setting(
    key,
    value
):
    connection = db()

    connection.execute(
        """
        INSERT INTO settings(
            key,
            value
        )
        VALUES (?, ?)
        ON CONFLICT(key)
        DO UPDATE SET
            value=excluded.value
        """,
        (
            key,
            str(value),
        ),
    )

    connection.commit()
    connection.close()


# ============================================================
# USER FUNCTIONS
# ============================================================

def get_user(
    telegram_id
):
    connection = db()

    row = connection.execute(
        """
        SELECT *
        FROM users
        WHERE telegram_id=?
        """,
        (telegram_id,),
    ).fetchone()

    connection.close()

    return row


def create_or_update_user(
    telegram_user
):
    connection = db()

    existing = connection.execute(
        """
        SELECT telegram_id
        FROM users
        WHERE telegram_id=?
        """,
        (telegram_user.id,),
    ).fetchone()

    if existing:
        connection.execute(
            """
            UPDATE users
            SET
                username=?,
                first_name=?,
                last_name=?,
                last_seen=?
            WHERE telegram_id=?
            """,
            (
                telegram_user.username,
                telegram_user.first_name,
                telegram_user.last_name,
                now(),
                telegram_user.id,
            ),
        )
    else:
        connection.execute(
            """
            INSERT INTO users(
                telegram_id,
                username,
                first_name,
                last_name,
                chances,
                registered,
                rules_accepted,
                created_at,
                last_seen
            )
            VALUES (?, ?, ?, ?, 1, 0, 0, ?, ?)
            """,
            (
                telegram_user.id,
                telegram_user.username,
                telegram_user.first_name,
                telegram_user.last_name,
                now(),
                now(),
            ),
        )

    connection.commit()
    connection.close()


def accept_rules(
    telegram_id
):
    connection = db()

    connection.execute(
        """
        UPDATE users
        SET rules_accepted=1
        WHERE telegram_id=?
        """,
        (telegram_id,),
    )

    connection.execute(
        """
        INSERT INTO rule_acceptances(
            telegram_id,
            version,
            accepted_at
        )
        VALUES (?, ?, ?)
        ON CONFLICT(telegram_id)
        DO UPDATE SET
            version=excluded.version,
            accepted_at=excluded.accepted_at
        """,
        (
            telegram_id,
            get_setting(
                "rules_version",
                RULES_VERSION
            ),
            now(),
        ),
    )

    connection.commit()
    connection.close()


def register_user(
    telegram_id,
    registration_type="free"
):
    connection = db()

    row = connection.execute(
        """
        SELECT *
        FROM users
        WHERE telegram_id=?
        """,
        (telegram_id,),
    ).fetchone()

    if not row:
        connection.close()
        return False, "user_not_found"

    if not row["rules_accepted"]:
        connection.close()
        return False, "rules_not_accepted"

    if row["registered"]:
        connection.close()
        return False, "already_registered"

    connection.execute(
        """
        UPDATE users
        SET
            registered=1,
            registration_type=?,
            registered_at=?
        WHERE telegram_id=?
        """,
        (
            registration_type,
            now(),
            telegram_id,
        ),
    )

    connection.commit()

    # --------------------------------------------------------
    # REFERRAL REWARD
    # فقط بعد از ثبت‌نام موفق دعوت‌شده
    # --------------------------------------------------------

    inviter_id = row["referred_by"]

    if inviter_id:
        referral = connection.execute(
            """
            SELECT *
            FROM referrals
            WHERE invited_id=?
            """,
            (telegram_id,),
        ).fetchone()

        if referral and not referral["chance_awarded"]:
            connection.execute(
                """
                UPDATE users
                SET
                    referral_count=
                        referral_count + 1,
                    chances=
                        chances + 1
                WHERE telegram_id=?
                """,
                (inviter_id,),
            )

            connection.execute(
                """
                UPDATE referrals
                SET chance_awarded=1
                WHERE invited_id=?
                """,
                (telegram_id,),
            )

    connection.commit()
    connection.close()

    return True, "registered"


# ============================================================
# REFERRAL
# ============================================================

def save_referral(
    inviter_id,
    invited_id
):
    if inviter_id == invited_id:
        return False

    connection = db()

    invited = connection.execute(
        """
        SELECT referred_by
        FROM users
        WHERE telegram_id=?
        """,
        (invited_id,),
    ).fetchone()

    inviter = connection.execute(
        """
        SELECT telegram_id
        FROM users
        WHERE telegram_id=?
        """,
        (inviter_id,),
    ).fetchone()

    if not invited or not inviter:
        connection.close()
        return False

    if invited["referred_by"]:
        connection.close()
        return False

    connection.execute(
        """
        UPDATE users
        SET referred_by=?
        WHERE telegram_id=?
        """,
        (
            inviter_id,
            invited_id,
        ),
    )

    connection.execute(
        """
        INSERT OR IGNORE INTO referrals(
            inviter_id,
            invited_id,
            chance_awarded,
            created_at
        )
        VALUES (?, ?, 0, ?)
        """,
        (
            inviter_id,
            invited_id,
            now(),
        ),
    )

    connection.commit()
    connection.close()

    return True


# ============================================================
# FORMATTING
# ============================================================

def fmt_number(
    value
):
    try:
        return f"{int(value):,}"
    except Exception:
        return str(value)


def is_admin(
    user_id
):
    return user_id in ADMIN_IDS


# ============================================================
# RULES
# ============================================================

def rules_text():
    return (
        "📜 <b>قوانین محفل خوش‌شانس‌ها</b>\n\n"

        "1️⃣ <b>ثبت‌نام رایگان</b>\n"
        "ثبت‌نام رایگان در مرحله فعلی فعال است و برای ورود "
        "به لیست کاربران محفل هزینه‌ای ندارد.\n\n"

        "2️⃣ <b>ثبت‌نام پولی</b>\n"
        "گزینه ثبت‌نام پولی فعلاً غیرفعال است. "
        "در صورت فعال شدن در آینده، قوانین و شرایط مربوط "
        "قبل از استفاده اعلام خواهد شد.\n\n"

        "3️⃣ <b>پذیرش قوانین</b>\n"
        "برای ثبت‌نام، مطالعه و پذیرش قوانین الزامی است.\n\n"

        "4️⃣ <b>دعوت دوستان</b>\n"
        "هر کاربر می‌تواند لینک اختصاصی خود را برای دیگران ارسال کند. "
        "در صورتی که فرد دعوت‌شده از طریق لینک شما وارد شود و "
        "ثبت‌نام خود را با موفقیت کامل کند، طبق سیستم محفل "
        "یک شانس اضافه برای دعوت‌کننده ثبت می‌شود.\n\n"

        "5️⃣ <b>شبکه‌های اجتماعی</b>\n"
        "برای اطلاع از مسابقات و شرایط جایزه، دنبال کردن "
        "اینستاگرام، یوتیوب و عضویت در کانال رسمی تلگرام "
        "توصیه و در صورت اعلام در قوانین همان مسابقه، الزامی است.\n\n"

        "6️⃣ <b>۱۰۰ هزار نفر</b>\n"
        "رسیدن شبکه‌های محفل به حد نصاب اعلام‌شده، "
        "مرحله فعال‌سازی قرعه‌کشی را مشخص می‌کند.\n\n"

        "7️⃣ <b>ثبت‌نام مسابقات</b>\n"
        "ثبت‌نام در فهرست مسابقات از مرحله رسیدن به ۱۰۰K "
        "جداست. ممکن است مسابقه برای ثبت‌نام باز باشد، "
        "اما اجرای قرعه‌کشی تا زمان فعال شدن شرایط آن انجام نشود.\n\n"

        "8️⃣ <b>بررسی شرایط</b>\n"
        "شرایط لازم می‌تواند در هر مسابقه متفاوت باشد و "
        "هنگام قرعه‌کشی نیز بررسی شود.\n\n"

        "9️⃣ <b>نتیجه</b>\n"
        "نتیجه مسابقات و اطلاعیه‌های رسمی فقط از مسیرهای رسمی "
        "محفل اعلام می‌شود.\n\n"

        "🔟 <b>تغییر قوانین</b>\n"
        "هرگونه تغییر مهم در قوانین قبل از اعمال برای کاربران "
        "اعلام خواهد شد.\n\n"

        "⚠️ اجرای هر مسابقه باید مطابق قوانین و مقررات محل "
        "فعالیت و الزامات قانونی مربوطه باشد."
    )


# ============================================================
# KEYBOARDS
# ============================================================

def start_keyboard():
    buttons = [
        [
            InlineKeyboardButton(
                "📜 مطالعه و پذیرش قوانین",
                callback_data="rules"
            )
        ],
        [
            InlineKeyboardButton(
                "🆘 راهنمای ثبت‌نام",
                callback_data="guide"
            )
        ],
    ]

    return InlineKeyboardMarkup(buttons)


def registration_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🆓 ثبت‌نام رایگان",
                callback_data="register_free"
            )
        ],
        [
            InlineKeyboardButton(
                "💳 ثبت‌نام پولی 🔒",
                callback_data="paid_disabled"
            )
        ],
        [
            InlineKeyboardButton(
                "📜 قوانین",
                callback_data="rules"
            )
        ],
    ])


def main_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🎁 مسابقات",
                callback_data="campaigns"
            ),
            InlineKeyboardButton(
                "🎟 شانس‌های من",
                callback_data="my_chances"
            ),
        ],
        [
            InlineKeyboardButton(
                "👥 دعوت دوستان",
                callback_data="referral"
            ),
            InlineKeyboardButton(
                "📋 ثبت‌نام من",
                callback_data="my_registration"
            ),
        ],
        [
            InlineKeyboardButton(
                "📸 اینستاگرام",
                url=INSTAGRAM_URL
            ),
            InlineKeyboardButton(
                "▶️ یوتیوب",
                url=YOUTUBE_URL
            ),
        ],
        [
            InlineKeyboardButton(
                "📢 کانال تلگرام",
                url=(
                    "https://t.me/"
                    f"{TELEGRAM_CHANNEL.lstrip('@')}"
                )
            )
        ],
        [
            InlineKeyboardButton(
                "🔎 بررسی شرایط",
                callback_data="eligibility"
            )
        ],
        [
            InlineKeyboardButton(
                "📈 وضعیت 100K",
                callback_data="network"
            ),
            InlineKeyboardButton(
                "📜 قوانین",
                callback_data="rules"
            ),
        ],
        [
            InlineKeyboardButton(
                "🆘 پشتیبانی",
                callback_data="support"
            )
        ],
    ])


def admin_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📊 وضعیت",
                callback_data="admin_status"
            ),
            InlineKeyboardButton(
                "👥 کاربران",
                callback_data="admin_users"
            ),
        ],
        [
            InlineKeyboardButton(
                "🎁 مسابقات",
                callback_data="admin_campaigns"
            ),
            InlineKeyboardButton(
                "🎲 قرعه‌کشی",
                callback_data="admin_draw"
            ),
        ],
        [
            InlineKeyboardButton(
                "📢 تبلیغ",
                callback_data="admin_post"
            ),
            InlineKeyboardButton(
                "📩 پشتیبانی",
                callback_data="admin_support"
            ),
        ],
        [
            InlineKeyboardButton(
                "📈 شبکه‌ها",
                callback_data="admin_networks"
            ),
            InlineKeyboardButton(
                "▶️ یوتیوب",
                callback_data="admin_youtube"
            ),
        ],
        [
            InlineKeyboardButton(
                "🏠 منوی اصلی",
                callback_data="home"
            )
        ],
    ])


# ============================================================
# NETWORKS
# ============================================================

def get_networks():
    return {
        "instagram": int(
            get_setting(
                "instagram_followers",
                "0"
            )
        ),
        "youtube": int(
            get_setting(
                "youtube_followers",
                "0"
            )
        ),
        "telegram": int(
            get_setting(
                "telegram_followers",
                "0"
            )
        ),
    }


async def update_telegram_count(
    bot
):
    try:
        count = await bot.get_chat_member_count(
            TELEGRAM_CHANNEL
        )

        set_setting(
            "telegram_followers",
            count
        )

        return count

    except Exception as exc:
        logger.warning(
            "Telegram member count failed: %s",
            exc
        )

        return None


def check_activation():
    networks = get_networks()

    target = int(
        get_setting(
            "activation_target",
            ACTIVATION_TARGET
        )
    )

    active = (
        networks["instagram"] >= target
        and
        networks["youtube"] >= target
        and
        networks["telegram"] >= target
    )

    set_setting(
        "networks_activated",
        "1" if active else "0"
    )

    return active


def activation_text():
    networks = get_networks()

    target = int(
        get_setting(
            "activation_target",
            ACTIVATION_TARGET
        )
    )

    active = check_activation()

    def progress(
        name,
        value
    ):
        percent = (
            int(
                min(
                    100,
                    value / target * 100
                )
            )
            if target
            else 0
        )

        return (
            f"{name}: "
            f"<b>{fmt_number(value)}</b> / "
            f"{fmt_number(target)} "
            f"({percent}%)"
        )

    if active:
        return (
            "🚀 <b>مرحله فعال‌سازی تکمیل شد!</b>\n\n"
            "🎉 حد نصاب هر سه شبکه تکمیل شده است.\n"
            "🎲 اجرای قرعه‌کشی‌های واجد شرایط می‌تواند فعال شود."
        )

    return (
        "📈 <b>مسیر فعال‌سازی محفل</b>\n\n"
        f"📸 {progress('Instagram', networks['instagram'])}\n"
        f"▶️ {progress('YouTube', networks['youtube'])}\n"
        f"📢 {progress('Telegram', networks['telegram'])}\n\n"
        "🎯 حد نصاب فعلی هر شبکه: "
        f"<b>{fmt_number(target)}</b>\n\n"
        "⚠️ ثبت‌نام کاربران و ثبت‌نام در مسابقات "
        "از این مرحله جداست؛ این عدد برای فعال شدن "
        "مرحله قرعه‌کشی استفاده می‌شود."
    )


# ============================================================
# YOUTUBE
# ============================================================

def fetch_youtube_followers():
    if not YOUTUBE_API_KEY:
        return None

    if not YOUTUBE_CHANNEL_ID:
        return None

    try:
        response = requests.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={
                "part": "statistics",
                "id": YOUTUBE_CHANNEL_ID,
                "key": YOUTUBE_API_KEY,
            },
            timeout=20,
        )

        if response.status_code != 200:
            logger.warning(
                "YouTube HTTP %s",
                response.status_code
            )
            return None

        data = response.json()

        items = data.get(
            "items",
            []
        )

        if not items:
            return None

        value = (
            items[0]
            .get("statistics", {})
            .get("subscriberCount")
        )

        if value is None:
            return None

        return int(value)

    except Exception as exc:
        logger.warning(
            "YouTube API error: %s",
            exc
        )

        return None


# ============================================================
# TELEGRAM MEMBERSHIP
# ============================================================

async def check_telegram_membership(
    bot,
    user_id
):
    if not TELEGRAM_MEMBERSHIP_REQUIRED:
        return True

    try:
        member = await bot.get_chat_member(
            TELEGRAM_CHANNEL,
            user_id
        )

        if member.status in (
            "creator",
            "administrator",
            "member",
        ):
            return True

        if member.status == "restricted":
            return bool(
                getattr(
                    member,
                    "is_member",
                    False
                )
            )

        return False

    except Exception as exc:
        logger.warning(
            "Membership check failed: %s",
            exc
        )

        return False


# ============================================================
# PROMOTIONAL MESSAGE
# ============================================================

def promotional_text():
    return (
        "🔥🔥 <b>محفل خوش‌شانس‌ها در حال بزرگ شدن است!</b> 🔥🔥\n\n"

        "🎁 مسابقات و جوایز ویژه در راه است.\n"
        "🚀 هدف بزرگ ما: <b>100,000 نفر</b>\n\n"

        "🎟 <b>همین حالا رایگان ثبت‌نام کن.</b>\n"
        "👥 دوستانت را هم وارد محفل کن؛ "
        "هر دعوت موفق طبق قوانین می‌تواند برایت "
        "یک شانس اضافه بسازد.\n\n"

        "📸 اینستاگرام:\n"
        f"{INSTAGRAM_URL}\n\n"

        "▶️ یوتیوب:\n"
        f"{YOUTUBE_URL}\n\n"

        "📢 کانال تلگرام:\n"
        f"https://t.me/{TELEGRAM_CHANNEL.lstrip('@')}\n\n"

        "⚠️ برای دریافت جایزه، رعایت شرایط اعلام‌شده "
        "در قوانین همان مسابقه الزامی است.\n\n"

        "🚨 <b>این پیام را برای دوستانت بفرست.</b>\n"
        "هر عضو جدید یعنی یک قدم نزدیک‌تر به شروع مرحله "
        "قرعه‌کشی. 🚀🔥"
    )


# ============================================================
# START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user

    create_or_update_user(user)

    # --------------------------------------------------------
    # REFERRAL CODE
    # --------------------------------------------------------

    if context.args:
        try:
            inviter_id = int(
                context.args[0]
            )

            save_referral(
                inviter_id,
                user.id
            )

        except Exception:
            pass

    existing = get_user(
        user.id
    )

    if existing and existing["registered"]:
        await update.message.reply_text(
            "🔥 <b>خوش برگشتی!</b>\n\n"
            "ثبت‌نامت قبلاً انجام شده است.\n"
            "از منوی زیر همه امکانات محفل در دسترس توست.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu(),
        )

        return

    await update.message.reply_text(
        "🎉 <b>به محفل خوش‌شانس‌ها خوش آمدید!</b>\n\n"

        "🎁 ثبت‌نام فعلی <b>کاملاً رایگان</b> است.\n"
        "👥 با دعوت موفق دوستان می‌توانی شانس اضافه بگیری.\n"
        "🎁 مسابقات از بخش مسابقات قابل مشاهده و ثبت‌نام هستند.\n\n"

        "⚠️ برای ورود به محفل ابتدا قوانین را "
        "مطالعه و تأیید کن.",
        parse_mode=ParseMode.HTML,
        reply_markup=start_keyboard(),
    )


# ============================================================
# MY ID
# ============================================================

async def myid(
    update,
    context
):
    await update.message.reply_text(
        "🆔 <b>Telegram ID شما:</b>\n\n"
        f"<code>{update.effective_user.id}</code>",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# ADMIN COMMAND
# ============================================================

async def admin_command(
    update,
    context
):
    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text(
            "❌ شما دسترسی ادمین ندارید.\n\n"
            f"🆔 ID شما:\n"
            f"<code>{user_id}</code>\n\n"
            "این ID را در Environment Variable زیر قرار بده:\n"
            "<code>ADMIN_IDS</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    await update.message.reply_text(
        "🛠 <b>پنل مدیریت محفل خوش‌شانس‌ها</b>\n\n"
        "از منوی زیر مدیریت کن:",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_menu(),
    )


# ============================================================
# ADMIN HELP
# ============================================================

async def adminhelp(
    update,
    context
):
    if not is_admin(
        update.effective_user.id
    ):
        await update.message.reply_text(
            "❌ دسترسی ندارید."
        )
        return

    await update.message.reply_text(
        "🛠 <b>راهنمای ادمین</b>\n\n"

        "/admin\n"
        "پنل مدیریت\n\n"

        "/myid\n"
        "شناسه تلگرام\n\n"

        "/status\n"
        "وضعیت سیستم\n\n"

        "/users\n"
        "آمار کاربران\n\n"

        "/igfollowers 100000\n"
        "ثبت دستی Instagram\n\n"

        "/ytfollowers\n"
        "دریافت YouTube از API\n\n"

        "/tgfollowers\n"
        "دریافت تعداد Telegram\n\n"

        "/createcampaign عنوان | توضیحات | جایزه\n"
        "ساخت مسابقه\n\n"

        "/campaigns\n"
        "لیست مسابقات\n\n"

        "/draw 1\n"
        "قرعه‌کشی مسابقه شماره ۱\n\n"

        "/postnow\n"
        "ارسال تبلیغ فوری\n\n"

        "/tickets\n"
        "تیکت‌های پشتیبانی\n\n"

        "/replyticket ID متن\n"
        "پاسخ به تیکت",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# STATUS
# ============================================================

async def status(
    update,
    context
):
    if not is_admin(
        update.effective_user.id
    ):
        await update.message.reply_text(
            "❌ دسترسی ندارید."
        )
        return

    connection = db()

    users = connection.execute(
        "SELECT COUNT(*) c FROM users"
    ).fetchone()["c"]

    registered = connection.execute(
        """
        SELECT COUNT(*) c
        FROM users
        WHERE registered=1
        """
    ).fetchone()["c"]

    referrals = connection.execute(
        "SELECT COUNT(*) c FROM referrals"
    ).fetchone()["c"]

    campaigns = connection.execute(
        "SELECT COUNT(*) c FROM campaigns"
    ).fetchone()["c"]

    winners = connection.execute(
        "SELECT COUNT(*) c FROM winners"
    ).fetchone()["c"]

    tickets = connection.execute(
        """
        SELECT COUNT(*) c
        FROM support_tickets
        WHERE status='open'
        """
    ).fetchone()["c"]

    connection.close()

    await update_telegram_count(
        context.bot
    )

    networks = get_networks()

    await update.message.reply_text(
        "📊 <b>وضعیت کامل سیستم</b>\n\n"

        f"👥 کل کاربران: <b>{fmt_number(users)}</b>\n"
        f"✅ ثبت‌نام‌شده: <b>{fmt_number(registered)}</b>\n"
        f"🤝 دعوت موفق: <b>{fmt_number(referrals)}</b>\n"
        f"🎁 مسابقات: <b>{fmt_number(campaigns)}</b>\n"
        f"🏆 برندگان: <b>{fmt_number(winners)}</b>\n"
        f"🆘 تیکت باز: <b>{fmt_number(tickets)}</b>\n\n"

        f"📸 Instagram: "
        f"<b>{fmt_number(networks['instagram'])}</b>\n"

        f"▶️ YouTube: "
        f"<b>{fmt_number(networks['youtube'])}</b>\n"

        f"📢 Telegram: "
        f"<b>{fmt_number(networks['telegram'])}</b>\n\n"

        f"🚀 فعال‌سازی 100K: "
        f"<b>{'فعال' if check_activation() else 'در انتظار'}</b>",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# USERS
# ============================================================

async def users_command(
    update,
    context
):
    if not is_admin(
        update.effective_user.id
    ):
        await update.message.reply_text(
            "❌ دسترسی ندارید."
        )
        return

    connection = db()

    total = connection.execute(
        "SELECT COUNT(*) c FROM users"
    ).fetchone()["c"]

    registered = connection.execute(
        """
        SELECT COUNT(*) c
        FROM users
        WHERE registered=1
        """
    ).fetchone()["c"]

    accepted = connection.execute(
        """
        SELECT COUNT(*) c
        FROM users
        WHERE rules_accepted=1
        """
    ).fetchone()["c"]

    referrals = connection.execute(
        "SELECT COUNT(*) c FROM referrals"
    ).fetchone()["c"]

    connection.close()

    await update.message.reply_text(
        "👥 <b>آمار کاربران</b>\n\n"
        f"کل ورودی‌ها: <b>{fmt_number(total)}</b>\n"
        f"قوانین پذیرفته: <b>{fmt_number(accepted)}</b>\n"
        f"ثبت‌نام کامل: <b>{fmt_number(registered)}</b>\n"
        f"دعوت موفق: <b>{fmt_number(referrals)}</b>",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# MANUAL INSTAGRAM
# ============================================================

async def igfollowers(
    update,
    context
):
    if not is_admin(
        update.effective_user.id
    ):
        await update.message.reply_text(
            "❌ دسترسی ندارید."
        )
        return

    if not context.args:
        await update.message.reply_text(
            "مثال:\n"
            "/igfollowers 100000"
        )
        return

    try:
        value = int(
            context.args[0]
            .replace(",", "")
            .replace("٬", "")
        )
    except ValueError:
        await update.message.reply_text(
            "❌ عدد صحیح وارد کنید."
        )
        return

    if value < 0:
        await update.message.reply_text(
            "❌ عدد نمی‌تواند منفی باشد."
        )
        return

    set_setting(
        "instagram_followers",
        value
    )

    active = check_activation()

    await update.message.reply_text(
        "📸 <b>Instagram بروزرسانی شد.</b>\n\n"
        f"تعداد: <b>{fmt_number(value)}</b>\n"
        f"هدف: <b>{fmt_number(ACTIVATION_TARGET)}</b>\n\n"
        f"🚀 وضعیت: "
        f"<b>{'فعال' if active else 'در انتظار'}</b>",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# TELEGRAM COUNT
# ============================================================

async def tgfollowers(
    update,
    context
):
    if not is_admin(
        update.effective_user.id
    ):
        await update.message.reply_text(
            "❌ دسترسی ندارید."
        )
        return

    count = await update_telegram_count(
        context.bot
    )

    if count is None:
        await update.message.reply_text(
            "❌ تعداد اعضای کانال دریافت نشد.\n\n"
            "مطمئن شوید نام کانال صحیح است و ربات "
            "دسترسی لازم را دارد."
        )
        return

    active = check_activation()

    await update.message.reply_text(
        "📢 <b>Telegram بروزرسانی شد.</b>\n\n"
        f"اعضا: <b>{fmt_number(count)}</b>\n"
        f"هدف: <b>{fmt_number(ACTIVATION_TARGET)}</b>\n\n"
        f"🚀 وضعیت: "
        f"<b>{'فعال' if active else 'در انتظار'}</b>",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# YOUTUBE COUNT
# ============================================================

async def ytfollowers(
    update,
    context
):
    if not is_admin(
        update.effective_user.id
    ):
        await update.message.reply_text(
            "❌ دسترسی ندارید."
        )
        return

    count = fetch_youtube_followers()

    if count is None:
        await update.message.reply_text(
            "❌ دریافت YouTube انجام نشد.\n\n"
            "این موارد را بررسی کن:\n"
            "YOUTUBE_API_KEY\n"
            "YOUTUBE_CHANNEL_ID\n"
            "فعال بودن YouTube Data API"
        )
        return

    set_setting(
        "youtube_followers",
        count
    )

    set_setting(
        "last_youtube_check",
        now()
    )

    active = check_activation()

    await update.message.reply_text(
        "▶️ <b>YouTube بروزرسانی شد.</b>\n\n"
        f"مشترکان: <b>{fmt_number(count)}</b>\n"
        f"هدف: <b>{fmt_number(ACTIVATION_TARGET)}</b>\n\n"
        f"🚀 وضعیت: "
        f"<b>{'فعال' if active else 'در انتظار'}</b>",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# CREATE CAMPAIGN
# ============================================================

async def createcampaign(
    update,
    context
):
    if not is_admin(
        update.effective_user.id
    ):
        await update.message.reply_text(
            "❌ دسترسی ندارید."
        )
        return

    raw = " ".join(
        context.args
    ).strip()

    parts = [
        item.strip()
        for item in raw.split("|")
    ]

    if len(parts) < 3:
        await update.message.reply_text(
            "فرمت صحیح:\n\n"
            "/createcampaign عنوان | توضیحات | جایزه\n\n"
            "مثال:\n"
            "/createcampaign مسابقه اول | "
            "اولین مسابقه محفل | پژو"
        )
        return

    connection = db()

    cursor = connection.execute(
        """
        INSERT INTO campaigns(
            title,
            description,
            prize,
            active,
            draw_completed,
            created_at
        )
        VALUES (?, ?, ?, 1, 0, ?)
        """,
        (
            parts[0],
            parts[1],
            parts[2],
            now(),
        ),
    )

    campaign_id = cursor.lastrowid

    connection.commit()
    connection.close()

    await update.message.reply_text(
        "✅ <b>مسابقه ساخته شد.</b>\n\n"
        f"🆔 ID: <code>{campaign_id}</code>\n"
        f"🎁 {parts[0]}\n"
        f"🏆 جایزه: {parts[2]}\n\n"
        "ℹ️ ثبت‌نام کاربران در مسابقه از فعال‌سازی "
        "100K جداست.",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# CAMPAIGNS COMMAND
# ============================================================

async def campaigns_command(
    update,
    context
):
    connection = db()

    rows = connection.execute(
        """
        SELECT *
        FROM campaigns
        WHERE active=1
          AND draw_completed=0
        ORDER BY id DESC
        """
    ).fetchall()

    connection.close()

    if not rows:
        await update.message.reply_text(
            "🎁 در حال حاضر مسابقه فعالی وجود ندارد."
        )
        return

    text = "🎁 <b>مسابقات فعال</b>\n\n"

    for row in rows:
        text += (
            f"#{row['id']} — "
            f"<b>{row['title']}</b>\n"
            f"🏆 {row['prize']}\n\n"
        )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# DRAW
# ============================================================

async def draw(
    update,
    context
):
    if not is_admin(
        update.effective_user.id
    ):
        await update.message.reply_text(
            "❌ دسترسی ندارید."
        )
        return

    if not context.args:
        await update.message.reply_text(
            "مثال:\n/draw 1"
        )
        return

    try:
        campaign_id = int(
            context.args[0]
        )
    except ValueError:
        await update.message.reply_text(
            "❌ ID مسابقه صحیح نیست."
        )
        return

    # --------------------------------------------------------
    # قرعه‌کشی تا زمان فعال شدن مرحله 100K قفل است
    # --------------------------------------------------------

    await update_telegram_count(
        context.bot
    )

    if not check_activation():
        await update.message.reply_text(
            "🔒 <b>قرعه‌کشی هنوز فعال نشده است.</b>\n\n"
            "ثبت‌نام کاربران و ثبت‌نام مسابقات "
            "می‌تواند انجام شود، اما اجرای قرعه‌کشی "
            "تا تکمیل حد نصاب فعال‌سازی 100K قفل است.",
            parse_mode=ParseMode.HTML,
        )
        return

    connection = db()

    campaign = connection.execute(
        """
        SELECT *
        FROM campaigns
        WHERE id=?
        """,
        (campaign_id,),
    ).fetchone()

    if not campaign:
        connection.close()

        await update.message.reply_text(
            "❌ مسابقه پیدا نشد."
        )
        return

    if campaign["draw_completed"]:
        connection.close()

        await update.message.reply_text(
            "❌ این مسابقه قبلاً قرعه‌کشی شده."
        )
        return

    participants = connection.execute(
        """
        SELECT
            p.telegram_id,
            p.chance_count
        FROM participations p
        JOIN users u
          ON u.telegram_id=p.telegram_id
        WHERE p.campaign_id=?
          AND u.registered=1
          AND u.blocked=0
        """,
        (campaign_id,),
    ).fetchall()

    connection.close()

    pool = []

    for participant in participants:
        try:
            member_ok = await check_telegram_membership(
                context.bot,
                participant["telegram_id"]
            )
        except Exception:
            member_ok = False

        if not member_ok:
            continue

        count = max(
            1,
            int(
                participant["chance_count"]
            )
        )

        pool.extend(
            [participant["telegram_id"]] * count
        )

    if not pool:
        await update.message.reply_text(
            "❌ شرکت‌کننده واجد شرایط پیدا نشد."
        )
        return

    winner_id = random.choice(
        pool
    )

    connection = db()

    connection.execute(
        """
        INSERT INTO winners(
            campaign_id,
            telegram_id,
            prize,
            created_at
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            campaign_id,
            winner_id,
            campaign["prize"],
            now(),
        ),
    )

    connection.execute(
        """
        UPDATE campaigns
        SET
            active=0,
            draw_completed=1
        WHERE id=?
        """,
        (campaign_id,),
    )

    connection.commit()
    connection.close()

    await update.message.reply_text(
        "🎉 <b>قرعه‌کشی انجام شد.</b>\n\n"
        f"🎁 مسابقه: <b>{campaign['title']}</b>\n"
        f"🏆 جایزه: <b>{campaign['prize']}</b>\n"
        f"🆔 شناسه برنده: "
        f"<code>{winner_id}</code>",
        parse_mode=ParseMode.HTML,
    )

    try:
        await context.bot.send_message(
            chat_id=TELEGRAM_CHANNEL,
            text=(
                "🎉 <b>نتیجه رسمی قرعه‌کشی محفل</b>\n\n"
                f"🎁 {campaign['title']}\n"
                f"🏆 جایزه: {campaign['prize']}\n\n"
                f"🆔 شناسه برنده:\n"
                f"<code>{winner_id}</code>\n\n"
                "🔥 برای مسابقات بعدی همراه محفل باشید."
            ),
            parse_mode=ParseMode.HTML,
        )
    except Exception as exc:
        logger.warning(
            "Winner announcement failed: %s",
            exc
        )


# ============================================================
# POST NOW
# ============================================================

async def postnow(
    update,
    context
):
    if not is_admin(
        update.effective_user.id
    ):
        await update.message.reply_text(
            "❌ دسترسی ندارید."
        )
        return

    try:
        await context.bot.send_message(
            chat_id=TELEGRAM_CHANNEL,
            text=promotional_text(),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=False,
        )

        set_setting(
            "last_auto_post",
            now()
        )

        await update.message.reply_text(
            "✅ تبلیغ با موفقیت ارسال شد."
        )

    except Exception as exc:
        logger.warning(
            "postnow error: %s",
            exc
        )

        await update.message.reply_text(
            "❌ ارسال نشد.\n\n"
            "بررسی کن ربات در کانال ادمین باشد "
            "و اجازه ارسال پیام داشته باشد."
        )


# ============================================================
# SUPPORT
# ============================================================

async def support_callback(
    update,
    context
):
    query = update.callback_query

    await query.answer()

    context.user_data["support_mode"] = True

    await query.edit_message_text(
        "🆘 <b>پشتیبانی محفل</b>\n\n"

        "پیامت را همینجا به صورت یک پیام متنی بفرست.\n\n"

        "📌 پیام تو به عنوان تیکت ثبت می‌شود و "
        "برای مدیریت ارسال خواهد شد.\n\n"

        "برای لغو، روی «لغو» بزن.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "❌ لغو",
                    callback_data="support_cancel"
                )
            ],
            [
                InlineKeyboardButton(
                    "🏠 منوی اصلی",
                    callback_data="home"
                )
            ],
        ]),
    )


async def support_cancel(
    update,
    context
):
    query = update.callback_query

    await query.answer()

    context.user_data.pop(
        "support_mode",
        None
    )

    await query.edit_message_text(
        "🆘 ارسال پیام پشتیبانی لغو شد.",
        reply_markup=main_menu(),
    )


async def tickets_command(
    update,
    context
):
    if not is_admin(
        update.effective_user.id
    ):
        await update.message.reply_text(
            "❌ دسترسی ندارید."
        )
        return

    connection = db()

    rows = connection.execute(
        """
        SELECT *
        FROM support_tickets
        WHERE status='open'
        ORDER BY id DESC
        LIMIT 20
        """
    ).fetchall()

    connection.close()

    if not rows:
        await update.message.reply_text(
            "📩 تیکت بازی وجود ندارد."
        )
        return

    for row in rows:
        await update.message.reply_text(
            "🆘 <b>تیکت #{}</b>\n\n"
            "🆔 User ID: <code>{}</code>\n"
            "🕐 {}\n\n"
            "{}\n\n"
            "برای پاسخ:\n"
            "<code>/replyticket {} متن پاسخ</code>".format(
                row["id"],
                row["telegram_id"],
                row["created_at"],
                row["message"],
                row["id"],
            ),
            parse_mode=ParseMode.HTML,
        )


async def replyticket(
    update,
    context
):
    if not is_admin(
        update.effective_user.id
    ):
        await update.message.reply_text(
            "❌ دسترسی ندارید."
        )
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "فرمت:\n"
            "/replyticket ID متن پاسخ\n\n"
            "مثال:\n"
            "/replyticket 15 سلام، مشکل شما بررسی شد."
        )
        return

    try:
        ticket_id = int(
            context.args[0]
        )
    except ValueError:
        await update.message.reply_text(
            "❌ ID تیکت صحیح نیست."
        )
        return

    reply_text = " ".join(
        context.args[1:]
    ).strip()

    connection = db()

    ticket = connection.execute(
        """
        SELECT *
        FROM support_tickets
        WHERE id=?
        """,
        (ticket_id,),
    ).fetchone()

    if not ticket:
        connection.close()

        await update.message.reply_text(
            "❌ تیکت پیدا نشد."
        )
        return

    connection.execute(
        """
        UPDATE support_tickets
        SET
            admin_reply=?,
            status='closed',
            replied_at=?
        WHERE id=?
        """,
        (
            reply_text,
            now(),
            ticket_id,
        ),
    )

    connection.commit()
    connection.close()

    try:
        await context.bot.send_message(
            chat_id=ticket["telegram_id"],
            text=(
                "🆘 <b>پاسخ پشتیبانی محفل</b>\n\n"
                f"{reply_text}\n\n"
                f"🎫 شماره تیکت: #{ticket_id}"
            ),
            parse_mode=ParseMode.HTML,
        )

        await update.message.reply_text(
            f"✅ پاسخ تیکت #{ticket_id} ارسال شد."
        )

    except Exception as exc:
        logger.warning(
            "Support reply failed: %s",
            exc
        )

        await update.message.reply_text(
            "⚠️ پاسخ ذخیره شد اما ارسال به کاربر انجام نشد."
        )


# ============================================================
# REGISTRATION / RULES CALLBACKS
# ============================================================

async def rules_callback(
    update,
    context
):
    query = update.callback_query

    await query.answer()

    create_or_update_user(
        query.from_user
    )

    await query.edit_message_text(
        rules_text(),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ قوانین را می‌پذیرم",
                    callback_data="accept_rules"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 بازگشت",
                    callback_data="home"
                )
            ],
        ]),
    )


async def accept_rules_callback(
    update,
    context
):
    query = update.callback_query

    await query.answer()

    create_or_update_user(
        query.from_user
    )

    accept_rules(
        query.from_user.id
    )

    await query.edit_message_text(
        "✅ <b>قوانین با موفقیت پذیرفته شد.</b>\n\n"
        "حالا نوع ثبت‌نامت را انتخاب کن.\n\n"
        "🆓 ثبت‌نام رایگان فعال است.\n"
        "💳 ثبت‌نام پولی فعلاً خاموش است.",
        parse_mode=ParseMode.HTML,
        reply_markup=registration_keyboard(),
    )


async def register_free_callback(
    update,
    context
):
    query = update.callback_query

    await query.answer()

    create_or_update_user(
        query.from_user
    )

    success, reason = register_user(
        query.from_user.id,
        "free"
    )

    if not success:
        if reason == "already_registered":
            await query.edit_message_text(
                "✅ <b>قبلاً ثبت‌نام کرده‌ای.</b>\n\n"
                "از منوی اصلی ادامه بده.",
                parse_mode=ParseMode.HTML,
                reply_markup=main_menu(),
            )
            return

        await query.answer(
            "ابتدا قوانین را بپذیر.",
            show_alert=True
        )

        return

    user = get_user(
        query.from_user.id
    )

    await query.edit_message_text(
        "🎉 <b>ثبت‌نام با موفقیت انجام شد!</b>\n\n"

        "✅ نام شما وارد لیست محفل شد.\n"
        f"🎟 شانس اولیه: <b>{user['chances']}</b>\n\n"

        "👥 حالا لینک دعوت اختصاصی خودت را بفرست "
        "تا دوستانت هم وارد محفل شوند.\n\n"

        "📌 هر دعوت موفق، پس از ثبت‌نام کامل فرد دعوت‌شده، "
        "طبق قوانین یک شانس اضافه برای تو ایجاد می‌کند.\n\n"

        "🔥 مسابقات را هم از همین حالا می‌توانی ببینی.",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(),
    )


async def paid_disabled_callback(
    update,
    context
):
    query = update.callback_query

    await query.answer(
        "💳 ثبت‌نام پولی فعلاً فعال نیست.",
        show_alert=True
    )


async def guide_callback(
    update,
    context
):
    query = update.callback_query

    await query.answer()

    await query.edit_message_text(
        "📘 <b>راهنمای محفل</b>\n\n"

        "1️⃣ قوانین را بخوان و قبول کن.\n"
        "2️⃣ ثبت‌نام رایگان را انجام بده.\n"
        "3️⃣ وارد لیست کاربران محفل می‌شوی.\n"
        "4️⃣ لینک دعوت اختصاصی‌ات را برای دوستان بفرست.\n"
        "5️⃣ با هر دعوت موفق، شانس اضافه دریافت کن.\n"
        "6️⃣ اینستاگرام، یوتیوب و تلگرام محفل را دنبال کن.\n"
        "7️⃣ مسابقات فعال را ببین و در مسابقه موردنظر ثبت‌نام کن.\n"
        "8️⃣ حد نصاب شبکه‌ها مسیر فعال شدن قرعه‌کشی را مشخص می‌کند.\n"
        "9️⃣ هنگام قرعه‌کشی شرایط لازم دوباره بررسی می‌شود.\n\n"

        "💡 ثبت‌نام کاربر با فعال‌سازی 100K دو مرحله جدا هستند.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🆓 ثبت‌نام",
                    callback_data="rules"
                )
            ],
            [
                InlineKeyboardButton(
                    "🏠 منوی اصلی",
                    callback_data="home"
                )
            ],
        ]),
    )


# ============================================================
# USER INFO
# ============================================================

async def my_registration_callback(
    update,
    context
):
    query = update.callback_query

    await query.answer()

    user = get_user(
        query.from_user.id
    )

    if not user:
        create_or_update_user(
            query.from_user
        )
        user = get_user(
            query.from_user.id
        )

    if user["registered"]:
        registration_type = (
            "رایگان"
            if user["registration_type"] == "free"
            else user["registration_type"]
        )

        text = (
            "📋 <b>وضعیت ثبت‌نام</b>\n\n"
            "✅ ثبت‌نام: انجام شده\n"
            f"نوع: <b>{registration_type}</b>\n"
            f"🎟 شانس: <b>{user['chances']}</b>\n"
            f"👥 دعوت موفق: <b>{user['referral_count']}</b>"
        )

    else:
        text = (
            "📋 <b>وضعیت ثبت‌نام</b>\n\n"
            "❌ هنوز ثبت‌نام کامل نشده است.\n\n"
            "برای ثبت‌نام رایگان از گزینه زیر استفاده کن."
        )

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🆓 ثبت‌نام / ادامه",
                    callback_data="rules"
                )
            ],
            [
                InlineKeyboardButton(
                    "🏠 منوی اصلی",
                    callback_data="home"
                )
            ],
        ]),
    )


# ============================================================
# REFERRAL
# ============================================================

async def referral_callback(
    update,
    context
):
    query = update.callback_query

    await query.answer()

    user = get_user(
        query.from_user.id
    )

    if not user:
        create_or_update_user(
            query.from_user
        )
        user = get_user(
            query.from_user.id
        )

    link = (
        f"https://t.me/"
        f"{BOT_USERNAME}"
        f"?start={query.from_user.id}"
    )

    await query.edit_message_text(
        "👥 <b>دعوت دوستان</b>\n\n"

        f"🎟 شانس فعلی: <b>{user['chances']}</b>\n"
        f"🤝 دعوت موفق: <b>{user['referral_count']}</b>\n\n"

        "🔗 لینک اختصاصی تو:\n"
        f"<code>{link}</code>\n\n"

        "📌 نکته مهم:\n"
        "فقط وقتی دعوت موفق محسوب می‌شود که فرد از "
        "لینک تو وارد شود و ثبت‌نام خودش را کامل کند.\n\n"

        "🔥 لینک را برای دوستانت بفرست!",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🏠 منوی اصلی",
                    callback_data="home"
                )
            ]
        ]),
    )


# ============================================================
# CHANCES
# ============================================================

async def chances_callback(
    update,
    context
):
    query = update.callback_query

    await query.answer()

    user = get_user(
        query.from_user.id
    )

    if not user:
        create_or_update_user(
            query.from_user
        )
        user = get_user(
            query.from_user.id
        )

    await query.edit_message_text(
        "🎟 <b>شانس‌های من</b>\n\n"
        f"🎟 شانس فعلی: <b>{user['chances']}</b>\n"
        f"👥 دعوت موفق: <b>{user['referral_count']}</b>\n\n"
        "هر شانس طبق قوانین مسابقه می‌تواند "
        "در محاسبه شانس‌های همان مسابقه استفاده شود.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "👥 دعوت دوستان",
                    callback_data="referral"
                )
            ],
            [
                InlineKeyboardButton(
                    "🏠 منوی اصلی",
                    callback_data="home"
                )
            ],
        ]),
    )


# ============================================================
# ELIGIBILITY
# ============================================================

async def eligibility_callback(
    update,
    context
):
    query = update.callback_query

    await query.answer()

    telegram_ok = await check_telegram_membership(
        context.bot,
        query.from_user.id
    )

    await query.edit_message_text(
        "🔎 <b>بررسی شرایط فعلی</b>\n\n"

        f"📢 عضویت تلگرام: "
        f"<b>{'✅ تأیید شده' if telegram_ok else '❌ تأیید نشده'}</b>\n\n"

        "📸 Instagram: "
        "در حال حاضر احراز خودکار فعال نیست.\n"

        "▶️ YouTube: "
        "در حال حاضر احراز خودکار فعال نیست.\n\n"

        "⚠️ در صورت فعال شدن احراز شبکه‌های اجتماعی، "
        "شرایط آن در قوانین و مسابقه مربوطه اعلام خواهد شد.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "📢 عضویت تلگرام",
                    url=(
                        "https://t.me/"
                        f"{TELEGRAM_CHANNEL.lstrip('@')}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "🔄 بررسی دوباره",
                    callback_data="eligibility"
                )
            ],
            [
                InlineKeyboardButton(
                    "🏠 منوی اصلی",
                    callback_data="home"
                )
            ],
        ]),
    )


# ============================================================
# CAMPAIGNS CALLBACK
# ============================================================

async def campaigns_callback(
    update,
    context
):
    query = update.callback_query

    await query.answer()

    connection = db()

    rows = connection.execute(
        """
        SELECT *
        FROM campaigns
        WHERE active=1
          AND draw_completed=0
        ORDER BY id DESC
        """
    ).fetchall()

    connection.close()

    if not rows:
        await query.edit_message_text(
            "🎁 <b>مسابقه فعال فعلاً وجود ندارد.</b>\n\n"
            "🔥 محفل در حال آماده‌سازی مسابقات است.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "📈 وضعیت 100K",
                        callback_data="network"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🏠 منوی اصلی",
                        callback_data="home"
                    )
                ],
            ]),
        )
        return

    buttons = []

    for row in rows:
        buttons.append([
            InlineKeyboardButton(
                f"🎁 {row['title']}",
                callback_data=f"campaign:{row['id']}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "🏠 منوی اصلی",
            callback_data="home"
        )
    ])

    await query.edit_message_text(
        "🎁 <b>مسابقات فعال</b>\n\n"
        "مسابقه موردنظر را انتخاب کن:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def campaign_details(
    update,
    context
):
    query = update.callback_query

    await query.answer()

    try:
        campaign_id = int(
            query.data.split(":")[1]
        )
    except Exception:
        return

    connection = db()

    row = connection.execute(
        """
        SELECT *
        FROM campaigns
        WHERE id=?
        """,
        (campaign_id,),
    ).fetchone()

    connection.close()

    if not row:
        await query.edit_message_text(
            "❌ مسابقه پیدا نشد."
        )
        return

    await query.edit_message_text(
        f"🎁 <b>{row['title']}</b>\n\n"
        f"{row['description']}\n\n"
        f"🏆 جایزه: <b>{row['prize']}</b>\n\n"

        "📌 ثبت‌نام مسابقه از فعال‌سازی 100K جداست.\n"
        "🎲 اجرای قرعه‌کشی پس از تکمیل شرایط فعال‌سازی "
        "و سایر شرایط مسابقه انجام می‌شود.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🎟 ثبت‌نام در مسابقه",
                    callback_data=f"join:{campaign_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 مسابقات",
                    callback_data="campaigns"
                )
            ],
        ]),
    )


# ============================================================
# JOIN CAMPAIGN
# ============================================================

async def join_campaign(
    update,
    context
):
    query = update.callback_query

    await query.answer()

    user = get_user(
        query.from_user.id
    )

    if not user or not user["registered"]:
        await query.answer(
            "ابتدا ثبت‌نام رایگان را کامل کن.",
            show_alert=True
        )

        await query.edit_message_text(
            "❌ <b>هنوز ثبت‌نام نکرده‌ای.</b>\n\n"
            "ثبت‌نام مسابقه فقط برای کاربران ثبت‌نام‌شده "
            "انجام می‌شود.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🆓 ثبت‌نام رایگان",
                        callback_data="rules"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🏠 منوی اصلی",
                        callback_data="home"
                    )
                ],
            ]),
        )

        return

    try:
        campaign_id = int(
            query.data.split(":")[1]
        )
    except Exception:
        await query.answer(
            "شناسه مسابقه نامعتبر است.",
            show_alert=True
        )
        return

    telegram_ok = await check_telegram_membership(
        context.bot,
        query.from_user.id
    )

    if not telegram_ok:
        await query.answer(
            "ابتدا عضو کانال تلگرام شوید.",
            show_alert=True
        )

        await query.edit_message_text(
            "❌ <b>عضویت تلگرام تأیید نشد.</b>\n\n"
            "ابتدا عضو کانال شو و دوباره امتحان کن.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "📢 عضویت در کانال",
                        url=(
                            "https://t.me/"
                            f"{TELEGRAM_CHANNEL.lstrip('@')}"
                        )
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔄 تلاش دوباره",
                        callback_data=f"join:{campaign_id}"
                    )
                ]
            ]),
        )

        return

    connection = db()

    campaign = connection.execute(
        """
        SELECT *
        FROM campaigns
        WHERE id=?
          AND active=1
          AND draw_completed=0
        """,
        (campaign_id,),
    ).fetchone()

    if not campaign:
        connection.close()

        await query.answer(
            "این مسابقه فعال نیست.",
            show_alert=True
        )
        return

    existing = connection.execute(
        """
        SELECT id
        FROM participations
        WHERE campaign_id=?
          AND telegram_id=?
        """,
        (
            campaign_id,
            query.from_user.id,
        ),
    ).fetchone()

    if existing:
        connection.close()

        await query.answer(
            "قبلاً در این مسابقه ثبت‌نام کرده‌ای.",
            show_alert=True
        )
        return

    chance_count = max(
        1,
        int(user["chances"])
    )

    connection.execute(
        """
        INSERT INTO participations(
            campaign_id,
            telegram_id,
            chance_count,
            created_at
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            campaign_id,
            query.from_user.id,
            chance_count,
            now(),
        ),
    )

    connection.commit()
    connection.close()

    await query.answer(
        "ثبت‌نام مسابقه انجام شد 🎉",
        show_alert=True
    )

    await query.edit_message_text(
        "🎉 <b>ثبت‌نام مسابقه موفق بود!</b>\n\n"
        f"🎁 {campaign['title']}\n"
        f"🏆 جایزه: {campaign['prize']}\n"
        f"🎟 شانس ثبت‌شده: <b>{chance_count}</b>\n\n"
        "⚠️ شرایط لازم هنگام قرعه‌کشی دوباره بررسی می‌شود.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "👥 دعوت دوستان",
                    callback_data="referral"
                )
            ],
            [
                InlineKeyboardButton(
                    "🏠 منوی اصلی",
                    callback_data="home"
                )
            ],
        ]),
    )


# ============================================================
# NETWORK CALLBACK
# ============================================================

async def network_callback(
    update,
    context
):
    query = update.callback_query

    await query.answer()

    await update_telegram_count(
        context.bot
    )

    await query.edit_message_text(
        activation_text(),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔄 بروزرسانی",
                    callback_data="network"
                )
            ],
            [
                InlineKeyboardButton(
                    "🏠 منوی اصلی",
                    callback_data="home"
                )
            ],
        ]),
    )


# ============================================================
# HOME
# ============================================================

async def home_callback(
    update,
    context
):
    query = update.callback_query

    await query.answer()

    context.user_data.pop(
        "support_mode",
        None
    )

    await query.edit_message_text(
        "🏠 <b>محفل خوش‌شانس‌ها</b>\n\n"
        "از منوی زیر انتخاب کن:",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(),
    )


# ============================================================
# ADMIN CALLBACKS
# ============================================================

async def admin_callback(
    update,
    context
):
    query = update.callback_query

    await query.answer()

    if not is_admin(
        query.from_user.id
    ):
        await query.answer(
            "دسترسی ندارید.",
            show_alert=True
        )
        return

    await query.edit_message_text(
        "🛠 <b>پنل مدیریت</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_menu(),
    )


async def admin_status_callback(
    update,
    context
):
    query = update.callback_query

    await query.answer()

    if not is_admin(
        query.from_user.id
    ):
        return

    await update_telegram_count(
        context.bot
    )

    connection = db()

    users = connection.execute(
        "SELECT COUNT(*) c FROM users"
    ).fetchone()["c"]

    registered = connection.execute(
        """
        SELECT COUNT(*) c
        FROM users
        WHERE registered=1
        """
    ).fetchone()["c"]

    tickets = connection.execute(
        """
        SELECT COUNT(*) c
        FROM support_tickets
        WHERE status='open'
        """
    ).fetchone()["c"]

    connection.close()

    networks = get_networks()

    await query.edit_message_text(
        "📊 <b>وضعیت سیستم</b>\n\n"
        f"👥 کاربران: <b>{fmt_number(users)}</b>\n"
        f"✅ ثبت‌نام‌شده: <b>{fmt_number(registered)}</b>\n"
        f"🆘 تیکت باز: <b>{fmt_number(tickets)}</b>\n\n"

        f"📸 IG: <b>{fmt_number(networks['instagram'])}</b>\n"
        f"▶️ YT: <b>{fmt_number(networks['youtube'])}</b>\n"
        f"📢 TG: <b>{fmt_number(networks['telegram'])}</b>\n\n"

        f"🚀 فعال‌سازی: "
        f"<b>{'فعال' if check_activation() else 'در انتظار'}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 پنل مدیریت",
                    callback_data="admin"
                )
            ]
        ]),
    )


async def admin_users_callback(
    update,
    context
):
    query = update.callback_query

    await query.answer()

    if not is_admin(
        query.from_user.id
    ):
        return

    connection = db()

    total = connection.execute(
        "SELECT COUNT(*) c FROM users"
    ).fetchone()["c"]

    registered = connection.execute(
        """
        SELECT COUNT(*) c
        FROM users
        WHERE registered=1
        """
    ).fetchone()["c"]

    referrals = connection.execute(
        "SELECT COUNT(*) c FROM referrals"
    ).fetchone()["c"]

    connection.close()

    await query.edit_message_text(
        "👥 <b>کاربران</b>\n\n"
        f"کل: <b>{fmt_number(total)}</b>\n"
        f"ثبت‌نام کامل: <b>{fmt_number(registered)}</b>\n"
        f"دعوت موفق: <b>{fmt_number(referrals)}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 پنل مدیریت",
                    callback_data="admin"
                )
            ]
        ]),
    )


async def admin_networks_callback(
    update,
    context
):
    query = update.callback_query

    await query.answer()

    if not is_admin(
        query.from_user.id
    ):
        return

    await update_telegram_count(
        context.bot
    )

    await query.edit_message_text(
        activation_text(),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 پنل مدیریت",
                    callback_data="admin"
                )
            ]
        ]),
    )


async def admin_youtube_callback(
    update,
    context
):
    query = update.callback_query

    await query.answer()

    if not is_admin(
        query.from_user.id
    ):
        return

    count = fetch_youtube_followers()

    if count is None:
        text = (
            "❌ YouTube دریافت نشد.\n\n"
            "API Key و Channel ID را بررسی کن."
        )
    else:
        set_setting(
            "youtube_followers",
            count
        )

        text = (
            "▶️ <b>YouTube بروزرسانی شد.</b>\n\n"
            f"مشترکان: <b>{fmt_number(count)}</b>\n"
            f"هدف: <b>{fmt_number(ACTIVATION_TARGET)}</b>"
        )

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 پنل مدیریت",
                    callback_data="admin"
                )
            ]
        ]),
    )


async def admin_post_callback(
    update,
    context
):
    query = update.callback_query

    await query.answer()

    if not is_admin(
        query.from_user.id
    ):
        return

    try:
        await context.bot.send_message(
            chat_id=TELEGRAM_CHANNEL,
            text=promotional_text(),
            parse_mode=ParseMode.HTML,
        )

        text = "✅ تبلیغ ارسال شد."

    except Exception:
        text = (
            "❌ ارسال نشد.\n\n"
            "ربات باید در کانال ادمین باشد."
        )

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 پنل مدیریت",
                    callback_data="admin"
                )
            ]
        ]),
    )


async def admin_campaigns_callback(
    update,
    context
):
    query = update.callback_query

    await query.answer()

    if not is_admin(
        query.from_user.id
    ):
        return

    connection = db()

    rows = connection.execute(
        """
        SELECT *
        FROM campaigns
        ORDER BY id DESC
        LIMIT 20
        """
    ).fetchall()

    connection.close()

    if not rows:
        text = "🎁 مسابقه‌ای وجود ندارد."

    else:
        text = "🎁 <b>مسابقات</b>\n\n"

        for row in rows:
            status_text = (
                "🟢 فعال"
                if row["active"]
                and not row["draw_completed"]
                else "🔴 پایان"
            )

            text += (
                f"#{row['id']} — "
                f"<b>{row['title']}</b>\n"
                f"🏆 {row['prize']}\n"
                f"{status_text}\n\n"
            )

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 پنل مدیریت",
                    callback_data="admin"
                )
            ]
        ]),
    )


async def admin_support_callback(
    update,
    context
):
    query = update.callback_query

    await query.answer()

    if not is_admin(
        query.from_user.id
    ):
        return

    connection = db()

    rows = connection.execute(
        """
        SELECT *
        FROM support_tickets
        WHERE status='open'
        ORDER BY id DESC
        LIMIT 10
        """
    ).fetchall()

    connection.close()

    if not rows:
        text = (
            "📩 <b>پشتیبانی</b>\n\n"
            "تیکت بازی وجود ندارد."
        )

    else:
        text = "📩 <b>تیکت‌های باز</b>\n\n"

        for row in rows:
            text += (
                f"🎫 #{row['id']}\n"
                f"👤 <code>{row['telegram_id']}</code>\n"
                f"{row['message'][:300]}\n\n"
                f"/replyticket {row['id']} متن پاسخ\n\n"
            )

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 پنل مدیریت",
                    callback_data="admin"
                )
            ]
        ]),
    )


async def admin_draw_callback(
    update,
    context
):
    query = update.callback_query

    await query.answer()

    if not is_admin(
        query.from_user.id
    ):
        return

    await query.edit_message_text(
        "🎲 <b>قرعه‌کشی</b>\n\n"
        "برای اجرای قرعه‌کشی از دستور زیر استفاده کن:\n\n"
        "<code>/draw ID</code>\n\n"
        "⚠️ اجرای قرعه‌کشی تا تکمیل شرایط "
        "فعال‌سازی 100K قفل است.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 پنل مدیریت",
                    callback_data="admin"
                )
            ]
        ]),
    )


# ============================================================
# TEXT HANDLER
# ============================================================

async def text_message(
    update,
    context
):
    user = update.effective_user

    create_or_update_user(
        user
    )

    text = update.message.text.strip()

    # --------------------------------------------------------
    # SUPPORT MODE
    # --------------------------------------------------------

    if context.user_data.get(
        "support_mode"
    ):
        if not text:
            return

        connection = db()

        cursor = connection.execute(
            """
            INSERT INTO support_tickets(
                telegram_id,
                message,
                status,
                created_at
            )
            VALUES (?, ?, 'open', ?)
            """,
            (
                user.id,
                text,
                now(),
            ),
        )

        ticket_id = cursor.lastrowid

        connection.commit()
        connection.close()

        context.user_data.pop(
            "support_mode",
            None
        )

        # ----------------------------------------------------
        # SEND TICKET TO ALL ADMINS
        # ----------------------------------------------------

        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=(
                        "🆘 <b>تیکت جدید پشتیبانی</b>\n\n"
                        f"🎫 شماره: <b>#{ticket_id}</b>\n"
                        f"👤 {user.full_name}\n"
                        f"🆔 <code>{user.id}</code>\n\n"
                        f"{text}\n\n"
                        "برای پاسخ:\n"
                        f"<code>/replyticket "
                        f"{ticket_id} متن پاسخ</code>"
                    ),
                    parse_mode=ParseMode.HTML,
                )
            except Exception as exc:
                logger.warning(
                    "Sending support ticket to admin failed: %s",
                    exc
                )

        await update.message.reply_text(
            "✅ <b>پیام شما ثبت شد.</b>\n\n"
            f"🎫 شماره تیکت: <b>#{ticket_id}</b>\n\n"
            "پیام برای پشتیبانی ارسال شد و پاسخ از طریق "
            "همین ربات برایت ارسال می‌شود.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu(),
        )

        return

    # --------------------------------------------------------
    # NORMAL TEXT
    # --------------------------------------------------------

    await update.message.reply_text(
        "برای استفاده از ربات از منوی زیر انتخاب کن:",
        reply_markup=main_menu(),
    )


# ============================================================
# AUTOMATIC POSTS
# ============================================================

async def automatic_channel_post(
    application
):
    if not AUTO_POST_ENABLED:
        return

    try:
        await application.bot.send_message(
            chat_id=TELEGRAM_CHANNEL,
            text=promotional_text(),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=False,
        )

        set_setting(
            "last_auto_post",
            now()
        )

        logger.info(
            "Automatic promotional post sent."
        )

    except Exception as exc:
        logger.warning(
            "Automatic post failed: %s",
            exc
        )


async def background_loop(
    application
):
    """
    حلقه داخلی:
    - تبلیغ هر ۲ ساعت
    - بروزرسانی YouTube هر ۱ ساعت
    - بروزرسانی Telegram هر ۳۰ دقیقه
    """

    await asyncio.sleep(60)

    last_ad = 0
    last_youtube = 0
    last_telegram = 0

    while True:
        try:
            current = asyncio.get_running_loop().time()

            # ------------------------------------------------
            # AUTO AD
            # ------------------------------------------------

            if AUTO_POST_ENABLED:
                if (
                    current - last_ad
                    >= AUTO_POST_HOURS * 3600
                ):
                    await automatic_channel_post(
                        application
                    )

                    last_ad = current

            # ------------------------------------------------
            # YOUTUBE
            # ------------------------------------------------

            if (
                YOUTUBE_API_KEY
                and
                YOUTUBE_CHANNEL_ID
            ):
                if current - last_youtube >= 3600:
                    count = fetch_youtube_followers()

                    if count is not None:
                        set_setting(
                            "youtube_followers",
                            count
                        )

                        set_setting(
                            "last_youtube_check",
                            now()
                        )

                        check_activation()

                    last_youtube = current

            # ------------------------------------------------
            # TELEGRAM
            # ------------------------------------------------

            if current - last_telegram >= 1800:
                await update_telegram_count(
                    application.bot
                )

                check_activation()

                last_telegram = current

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            logger.exception(
                "Background loop error: %s",
                exc
            )

        await asyncio.sleep(30)


async def post_init(
    application
):
    logger.info(
        "MAHFELSHANS BOT STARTED"
    )

    logger.info(
        "Admins: %s",
        sorted(ADMIN_IDS)
    )

    logger.info(
        "Telegram channel: %s",
        TELEGRAM_CHANNEL
    )

    application.create_task(
        background_loop(
            application
        )
    )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update,
    context
):
    logger.exception(
        "Unhandled exception: %s",
        context.error
    )

    try:
        if (
            update
            and
            update.effective_message
        ):
            await update.effective_message.reply_text(
                "⚠️ یک خطای موقت رخ داد.\n"
                "لطفاً دوباره تلاش کنید."
            )
    except Exception:
        pass


# ============================================================
# BUILD APPLICATION
# ============================================================

def build_application():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN environment variable is missing."
        )

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # --------------------------------------------------------
    # COMMANDS
    # --------------------------------------------------------

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "myid",
            myid
        )
    )

    application.add_handler(
        CommandHandler(
            "admin",
            admin_command
        )
    )

    application.add_handler(
        CommandHandler(
            "adminhelp",
            adminhelp
        )
    )

    application.add_handler(
        CommandHandler(
            "status",
            status
        )
    )

    application.add_handler(
        CommandHandler(
            "users",
            users_command
        )
    )

    application.add_handler(
        CommandHandler(
            "igfollowers",
            igfollowers
        )
    )

    application.add_handler(
        CommandHandler(
            "tgfollowers",
            tgfollowers
        )
    )

    application.add_handler(
        CommandHandler(
            "ytfollowers",
            ytfollowers
        )
    )

    application.add_handler(
        CommandHandler(
            "createcampaign",
            createcampaign
        )
    )

    application.add_handler(
        CommandHandler(
            "campaigns",
            campaigns_command
        )
    )

    application.add_handler(
        CommandHandler(
            "draw",
            draw
        )
    )

    application.add_handler(
        CommandHandler(
            "postnow",
            postnow
        )
    )

    application.add_handler(
        CommandHandler(
            "tickets",
            tickets_command
        )
    )

    application.add_handler(
        CommandHandler(
            "replyticket",
            replyticket
        )
    )

    # --------------------------------------------------------
    # START / RULES / REGISTRATION
    # --------------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            rules_callback,
            pattern="^rules$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            accept_rules_callback,
            pattern="^accept_rules$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            register_free_callback,
            pattern="^register_free$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            paid_disabled_callback,
            pattern="^paid_disabled$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            guide_callback,
            pattern="^guide$"
        )
    )

    # --------------------------------------------------------
    # HOME
    # --------------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            home_callback,
            pattern="^home$"
        )
    )

    # --------------------------------------------------------
    # USER
    # --------------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            my_registration_callback,
            pattern="^my_registration$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            referral_callback,
            pattern="^referral$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            chances_callback,
            pattern="^my_chances$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            eligibility_callback,
            pattern="^eligibility$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            network_callback,
            pattern="^network$"
        )
    )

    # --------------------------------------------------------
    # CAMPAIGNS
    # --------------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            campaigns_callback,
            pattern="^campaigns$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            campaign_details,
            pattern=r"^campaign:\d+$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            join_campaign,
            pattern=r"^join:\d+$"
        )
    )

    # --------------------------------------------------------
    # SUPPORT
    # --------------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            support_callback,
            pattern="^support$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            support_cancel,
            pattern="^support_cancel$"
        )
    )

    # --------------------------------------------------------
    # ADMIN
    # --------------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            admin_callback,
            pattern="^admin$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            admin_status_callback,
            pattern="^admin_status$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            admin_users_callback,
            pattern="^admin_users$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            admin_campaigns_callback,
            pattern="^admin_campaigns$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            admin_post_callback,
            pattern="^admin_post$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            admin_networks_callback,
            pattern="^admin_networks$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            admin_youtube_callback,
            pattern="^admin_youtube$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            admin_support_callback,
            pattern="^admin_support$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            admin_draw_callback,
            pattern="^admin_draw$"
        )
    )

    # --------------------------------------------------------
    # TEXT
    # --------------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_message
        )
    )

    # --------------------------------------------------------
    # ERROR
    # --------------------------------------------------------

    application.add_error_handler(
        error_handler
    )

    return application


# ============================================================
# MAIN
# ============================================================

def main():
    init_db()

    application = build_application()

    if RENDER_EXTERNAL_URL:
        webhook_url = (
            f"{RENDER_EXTERNAL_URL.rstrip('/')}/"
            f"{WEBHOOK_PATH}"
        )

        logger.info(
            "Starting webhook: %s",
            webhook_url
        )

        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=WEBHOOK_PATH,
            webhook_url=webhook_url,
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
        )

    else:
        logger.info(
            "Starting polling mode."
        )

        application.run_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
        )


if __name__ == "__main__":
    main()
