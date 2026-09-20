import os
import sqlite3
import logging
import random
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
    ContextTypes,
    MessageHandler,
    filters,
)

# ============================================================
# MAHFEL SHANSHAH
# محفل خوش‌شانس‌ها
# Version: 2.0
# Single-file Telegram Bot
# ============================================================

# ============================================================
# ENVIRONMENT
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

PORT = int(os.getenv("PORT", "10000"))

RENDER_EXTERNAL_URL = os.getenv(
    "RENDER_EXTERNAL_URL",
    ""
).strip()

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
# FEATURES
# ------------------------------------------------------------

ACTIVATION_TARGET = int(
    os.getenv("ACTIVATION_TARGET", "100000")
)

AUTO_POST_ENABLED = (
    os.getenv(
        "AUTO_POST_ENABLED",
        "true"
    ).lower()
    in ("1", "true", "yes", "on")
)

AUTO_POST_HOURS = int(
    os.getenv("AUTO_POST_HOURS", "2")
)

TELEGRAM_MEMBERSHIP_REQUIRED = (
    os.getenv(
        "TELEGRAM_MEMBERSHIP_REQUIRED",
        "true"
    ).lower()
    in ("1", "true", "yes", "on")
)

# این دو فعلاً خاموش هستند
PAID_REGISTRATION_ENABLED = (
    os.getenv(
        "PAID_REGISTRATION_ENABLED",
        "false"
    ).lower()
    in ("1", "true", "yes", "on")
)

INSTAGRAM_VERIFICATION_ENABLED = (
    os.getenv(
        "INSTAGRAM_VERIFICATION_ENABLED",
        "false"
    ).lower()
    in ("1", "true", "yes", "on")
)

YOUTUBE_VERIFICATION_ENABLED = (
    os.getenv(
        "YOUTUBE_VERIFICATION_ENABLED",
        "false"
    ).lower()
    in ("1", "true", "yes", "on")
)

# ------------------------------------------------------------
# YOUTUBE API - OPTIONAL / CURRENTLY NOT REQUIRED
# ------------------------------------------------------------

YOUTUBE_API_KEY = os.getenv(
    "YOUTUBE_API_KEY",
    ""
).strip()

YOUTUBE_CHANNEL_ID = os.getenv(
    "YOUTUBE_CHANNEL_ID",
    ""
).strip()

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

logger = logging.getLogger("MAHFELSHANS")


# ============================================================
# DATABASE
# ============================================================

def db():
    connection = sqlite3.connect(
        DATABASE,
        check_same_thread=False
    )
    connection.row_factory = sqlite3.Row
    return connection


def now():
    return datetime.now(timezone.utc).isoformat()


def init_db():
    connection = db()
    cursor = connection.cursor()

    # --------------------------------------------------------
    # USERS
    # --------------------------------------------------------

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
            rules_accepted INTEGER DEFAULT 0,
            blocked INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            last_seen TEXT NOT NULL
        )
    """)

    # --------------------------------------------------------
    # REFERRALS
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inviter_id INTEGER NOT NULL,
            invited_id INTEGER UNIQUE NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    # --------------------------------------------------------
    # CAMPAIGNS
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            prize TEXT NOT NULL,
            active INTEGER DEFAULT 1,
            draw_completed INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)

    # --------------------------------------------------------
    # PARTICIPATIONS
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # WINNERS
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS winners (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL,
            telegram_id INTEGER NOT NULL,
            prize TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    # --------------------------------------------------------
    # RULE ACCEPTANCE
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rule_acceptances (
            telegram_id INTEGER PRIMARY KEY,
            version TEXT NOT NULL,
            accepted_at TEXT NOT NULL
        )
    """)

    # --------------------------------------------------------
    # SUPPORT
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            status TEXT DEFAULT 'open',
            created_at TEXT NOT NULL
        )
    """)

    # --------------------------------------------------------
    # SETTINGS
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # --------------------------------------------------------
    # DEFAULT SETTINGS
    # --------------------------------------------------------

    defaults = {
        "instagram_followers": "0",
        "youtube_followers": "0",
        "telegram_followers": "0",

        "activation_target": str(
            ACTIVATION_TARGET
        ),

        "networks_activated": "0",

        "rules_version": "1.0",

        "telegram_membership_required": (
            "1"
            if TELEGRAM_MEMBERSHIP_REQUIRED
            else "0"
        ),

        "paid_registration_enabled": (
            "1"
            if PAID_REGISTRATION_ENABLED
            else "0"
        ),

        "instagram_verification_enabled": (
            "1"
            if INSTAGRAM_VERIFICATION_ENABLED
            else "0"
        ),

        "youtube_verification_enabled": (
            "1"
            if YOUTUBE_VERIFICATION_ENABLED
            else "0"
        ),

        "last_auto_post": "",

        "last_youtube_check": "",

        "campaigns_enabled": "1",
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
            (key, value)
        )

    connection.commit()
    connection.close()


def get_setting(key, default=None):
    connection = db()

    row = connection.execute(
        """
        SELECT value
        FROM settings
        WHERE key=?
        """,
        (key,)
    ).fetchone()

    connection.close()

    if row is None:
        return default

    return row["value"]


def set_setting(key, value):
    connection = db()

    connection.execute(
        """
        INSERT INTO settings(key, value)
        VALUES (?, ?)
        ON CONFLICT(key)
        DO UPDATE SET value=excluded.value
        """,
        (key, str(value))
    )

    connection.commit()
    connection.close()


def setting_bool(key, default=False):
    value = get_setting(
        key,
        "1" if default else "0"
    )

    return str(value).lower() in (
        "1",
        "true",
        "yes",
        "on"
    )


# ============================================================
# USER HELPERS
# ============================================================

def get_user(telegram_id):
    connection = db()

    row = connection.execute(
        """
        SELECT *
        FROM users
        WHERE telegram_id=?
        """,
        (telegram_id,)
    ).fetchone()

    connection.close()

    return row


def create_or_update_user(tg_user):
    connection = db()

    current = now()

    row = connection.execute(
        """
        SELECT telegram_id
        FROM users
        WHERE telegram_id=?
        """,
        (tg_user.id,)
    ).fetchone()

    if row:
        connection.execute(
            """
            UPDATE users
            SET username=?,
                first_name=?,
                last_name=?,
                last_seen=?
            WHERE telegram_id=?
            """,
            (
                tg_user.username,
                tg_user.first_name,
                tg_user.last_name,
                current,
                tg_user.id,
            )
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
                created_at,
                last_seen
            )
            VALUES (?, ?, ?, ?, 1, ?, ?)
            """,
            (
                tg_user.id,
                tg_user.username,
                tg_user.first_name,
                tg_user.last_name,
                current,
                current,
            )
        )

    connection.commit()
    connection.close()


def rules_accepted(telegram_id):
    user = get_user(telegram_id)

    return bool(
        user and user["rules_accepted"] == 1
    )


def save_rules_acceptance(telegram_id):
    version = get_setting(
        "rules_version",
        "1.0"
    )

    connection = db()

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
            version,
            now()
        )
    )

    connection.execute(
        """
        UPDATE users
        SET rules_accepted=1
        WHERE telegram_id=?
        """,
        (telegram_id,)
    )

    connection.commit()
    connection.close()


# ============================================================
# GENERAL HELPERS
# ============================================================

def is_admin(user_id):
    return user_id in ADMIN_IDS


def fmt_number(number):
    try:
        return f"{int(number):,}"
    except Exception:
        return str(number)


def bot_link():
    return f"https://t.me/{BOT_USERNAME}"


def telegram_channel_url():
    return (
        "https://t.me/"
        f"{TELEGRAM_CHANNEL.lstrip('@')}"
    )


# ============================================================
# RULES
# ============================================================

def rules_text():
    return (
        "📜 <b>قوانین و شرایط محفل خوش‌شانس‌ها</b>\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "🎁 <b>۱. ثبت‌نام</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "ثبت‌نام فعلی کاملاً رایگان است.\n"
        "گزینه ثبت‌نام پولی فعلاً غیرفعال است.\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "📋 <b>۲. پذیرش قوانین</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "هر کاربر قبل از ورود به بخش‌های اصلی باید "
        "قوانین را مطالعه و تأیید کند.\n"
        "پذیرش قوانین در سیستم ثبت می‌شود.\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "👥 <b>۳. دعوت دوستان</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "هر کاربر یک لینک اختصاصی دعوت دارد.\n"
        "اگر شخص جدید از لینک شما وارد ربات شود و "
        "ثبت‌نام خود را کامل کند، یک دعوت موفق برای شما "
        "ثبت می‌شود و یک شانس اضافه دریافت می‌کنید.\n"
        "هر دعوت فقط یک بار برای یک کاربر محاسبه می‌شود.\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "📱 <b>۴. شبکه‌های رسمی</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "برای اطلاع از مسابقات و شرایط جدید، "
        "عضویت و دنبال‌کردن شبکه‌های رسمی محفل توصیه و "
        "در صورت فعال شدن شرط مربوطه الزامی خواهد بود.\n\n"

        "📸 اینستاگرام:\n"
        f"{INSTAGRAM_URL}\n\n"

        "▶️ یوتیوب:\n"
        f"{YOUTUBE_URL}\n\n"

        "📢 کانال تلگرام:\n"
        f"{telegram_channel_url()}\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "🚀 <b>۵. مرحله فعال‌سازی</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"هدف فعلی رسیدن هر سه شبکه به "
        f"<b>{fmt_number(ACTIVATION_TARGET)}</b> نفر است.\n\n"

        "Instagram → 100K\n"
        "YouTube → 100K\n"
        "Telegram → 100K\n\n"

        "تعداد هر شبکه در حال حاضر از پنل مدیریت ثبت می‌شود "
        "و بررسی خودکار فالوور اینستاگرام و یوتیوب فعلاً "
        "غیرفعال است.\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "🎁 <b>۶. مسابقات و قرعه‌کشی</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "مسابقات زمانی که توسط مدیریت فعال شوند در بخش "
        "«جوایز و مسابقات» نمایش داده می‌شوند.\n"
        "شرایط هر مسابقه ممکن است جداگانه اعلام شود.\n"
        "شرایط لازم برای دریافت جایزه باید هنگام قرعه‌کشی "
        "و تحویل جایزه رعایت شود.\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "💳 <b>۷. پرداخت</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "ثبت‌نام پولی در نسخه فعلی غیرفعال است.\n"
        "اگر در آینده این بخش فعال شود، شرایط پرداخت، "
        "هزینه، قوانین مربوطه و شرایط شرکت قبل از استفاده "
        "به‌صورت شفاف اعلام خواهد شد.\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "🏆 <b>۸. نتیجه قرعه‌کشی</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "نتیجه مسابقات پس از انجام قرعه‌کشی از طریق "
        "کانال رسمی اعلام می‌شود.\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "🆘 <b>۹. پشتیبانی</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "برای مشکلات و سوالات می‌توانید از بخش پشتیبانی "
        "ربات استفاده کنید.\n\n"

        "⚠️ قوانین نهایی هر مسابقه و الزامات قانونی "
        "مربوط به محل برگزاری باید قبل از اجرای آن مسابقه "
        "مشخص و رعایت شود."
    )


# ============================================================
# MENUS
# ============================================================

def registration_menu():
    buttons = [
        [
            InlineKeyboardButton(
                "🎁 ثبت‌نام رایگان",
                callback_data="register_free"
            )
        ]
    ]

    if setting_bool(
        "paid_registration_enabled",
        False
    ):
        buttons.append([
            InlineKeyboardButton(
                "💳 ثبت‌نام پولی",
                callback_data="register_paid"
            )
        ])
    else:
        buttons.append([
            InlineKeyboardButton(
                "💳 ثبت‌نام پولی 🔒",
                callback_data="paid_disabled"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "📜 مطالعه قوانین",
            callback_data="rules"
        )
    ])

    return InlineKeyboardMarkup(buttons)


def main_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🎁 جوایز و مسابقات",
                callback_data="campaigns"
            )
        ],
        [
            InlineKeyboardButton(
                "🎟 شانس‌های من",
                callback_data="my_chances"
            ),
            InlineKeyboardButton(
                "👥 دعوت دوستان",
                callback_data="referral"
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
                "📢 کانال تلگرام",
                url=telegram_channel_url()
            )
        ],
        [
            InlineKeyboardButton(
                "🚀 وضعیت 100K",
                callback_data="network"
            ),
            InlineKeyboardButton(
                "✅ بررسی شرایط",
                callback_data="eligibility"
            )
        ],
        [
            InlineKeyboardButton(
                "📜 قوانین",
                callback_data="rules"
            ),
            InlineKeyboardButton(
                "🆘 پشتیبانی",
                callback_data="support"
            )
        ]
    ])


def admin_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📊 وضعیت سیستم",
                callback_data="admin_status"
            )
        ],
        [
            InlineKeyboardButton(
                "👥 کاربران",
                callback_data="admin_users"
            ),
            InlineKeyboardButton(
                "🎁 مسابقات",
                callback_data="admin_campaigns"
            )
        ],
        [
            InlineKeyboardButton(
                "📈 شبکه‌ها",
                callback_data="admin_networks"
            )
        ],
        [
            InlineKeyboardButton(
                "⚙️ قابلیت‌ها",
                callback_data="admin_features"
            )
        ],
        [
            InlineKeyboardButton(
                "📢 ارسال تبلیغ",
                callback_data="admin_post"
            )
        ],
        [
            InlineKeyboardButton(
                "🎲 آخرین قرعه‌ها",
                callback_data="admin_last_draw"
            )
        ],
        [
            InlineKeyboardButton(
                "🏠 منوی اصلی",
                callback_data="home"
            )
        ]
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
        )
    }


def check_activation():
    networks = get_networks()

    target = int(
        get_setting(
            "activation_target",
            str(ACTIVATION_TARGET)
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
            str(ACTIVATION_TARGET)
        )
    )

    def progress(name, value):
        percent = 0

        if target > 0:
            percent = min(
                100,
                int(
                    value * 100 / target
                )
            )

        blocks = min(
            10,
            int(percent / 10)
        )

        bar = (
            "🟩" * blocks
            + "⬜" * (10 - blocks)
        )

        return (
            f"{name}\n"
            f"{bar} {percent}%\n"
            f"<b>{fmt_number(value)}</b> / "
            f"{fmt_number(target)}\n"
        )

    active = check_activation()

    if active:
        state = (
            "🎉 <b>مرحله فعال‌سازی کامل شده است!</b>\n\n"
            "هر سه شبکه به حد نصاب رسیده‌اند.\n"
            "مسابقات فعال اکنون می‌توانند اجرا شوند."
        )
    else:
        state = (
            "🔒 <b>قرعه‌کشی هنوز در مرحله فعال‌سازی است.</b>\n\n"
            "برای باز شدن مرحله اصلی، هر سه شبکه باید "
            "به حد نصاب برسند."
        )

    return (
        "🚀 <b>مسیر 100K محفل خوش‌شانس‌ها</b>\n\n"
        + progress(
            "📸 Instagram",
            networks["instagram"]
        )
        + "\n"
        + progress(
            "▶️ YouTube",
            networks["youtube"]
        )
        + "\n"
        + progress(
            "📢 Telegram",
            networks["telegram"]
        )
        + "\n"
        + state
    )


# ============================================================
# PROMOTIONAL MESSAGE
# ============================================================

def promotional_text():
    networks = get_networks()

    target = int(
        get_setting(
            "activation_target",
            str(ACTIVATION_TARGET)
        )
    )

    return (
        "🔥🔥 <b>محفل خوش‌شانس‌ها</b> 🔥🔥\n\n"

        "🎁 یک محفل بزرگ در حال ساخته‌شدن است!\n"
        "🚀 هدف ما رسیدن به <b>100K</b> در هر سه شبکه است.\n\n"

        "📸 Instagram:\n"
        f"<b>{fmt_number(networks['instagram'])}</b>"
        f" / {fmt_number(target)}\n\n"

        "▶️ YouTube:\n"
        f"<b>{fmt_number(networks['youtube'])}</b>"
        f" / {fmt_number(target)}\n\n"

        "📢 Telegram:\n"
        f"<b>{fmt_number(networks['telegram'])}</b>"
        f" / {fmt_number(target)}\n\n"

        "👥 <b>دوستت را معرفی کن!</b>\n"
        "هر ثبت‌نام موفق از لینک دعوت تو، "
        "طبق قوانین، یک شانس اضافه برایت ایجاد می‌کند. 🎟🔥\n\n"

        "📱 اینستاگرام را دنبال کن\n"
        "▶️ یوتیوب را دنبال کن\n"
        "📢 عضو کانال تلگرام شو\n\n"

        "⚠️ برای شرکت در مسابقات و دریافت جایزه، "
        "رعایت شرایط اعلام‌شده هر مسابقه الزامی است.\n\n"

        "👇 همین الان وارد محفل شو:\n"
        f"{bot_link()}\n\n"

        "🚀 <b>این تازه شروع ماجراست...</b>"
    )


# ============================================================
# TELEGRAM MEMBERSHIP
# ============================================================

async def check_telegram_membership(
    bot,
    user_id
):
    if not setting_bool(
        "telegram_membership_required",
        True
    ):
        return True

    try:
        member = await bot.get_chat_member(
            TELEGRAM_CHANNEL,
            user_id
        )

        if member.status in (
            "creator",
            "administrator",
            "member"
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
            "Telegram membership check failed: %s",
            exc
        )
        return False


# ============================================================
# ELIGIBILITY
# ============================================================

async def eligibility_status(
    bot,
    user_id
):
    telegram_ok = await check_telegram_membership(
        bot,
        user_id
    )

    return {
        "telegram": telegram_ok,
        "instagram": (
            not setting_bool(
                "instagram_verification_enabled",
                False
            )
        ),
        "youtube": (
            not setting_bool(
                "youtube_verification_enabled",
                False
            )
        )
    }


def eligibility_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📢 عضویت کانال",
                url=telegram_channel_url()
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
                "🔄 بررسی دوباره",
                callback_data="verify_membership"
            )
        ],
        [
            InlineKeyboardButton(
                "🏠 منوی اصلی",
                callback_data="home"
            )
        ]
    ])


# ============================================================
# YOUTUBE
# ============================================================

def fetch_youtube_followers():
    if (
        not YOUTUBE_API_KEY
        or
        not YOUTUBE_CHANNEL_ID
    ):
        return None

    try:
        response = requests.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={
                "part": "statistics",
                "id": YOUTUBE_CHANNEL_ID,
                "key": YOUTUBE_API_KEY,
            },
            timeout=20
        )

        if response.status_code != 200:
            return None

        data = response.json()

        items = data.get("items", [])

        if not items:
            return None

        count = items[0].get(
            "statistics",
            {}
        ).get(
            "subscriberCount"
        )

        if count is None:
            return None

        return int(count)

    except Exception as exc:
        logger.warning(
            "YouTube API error: %s",
            exc
        )
        return None


# ============================================================
# /START
# ============================================================

async def start(update, context):
    user = update.effective_user

    create_or_update_user(user)

    # --------------------------------------------------------
    # REFERRAL
    # --------------------------------------------------------

    referral_code = None

    if context.args:
        referral_code = context.args[0].strip()

    if referral_code:
        try:
            inviter_id = int(
                referral_code
            )

            if inviter_id != user.id:
                inviter = get_user(
                    inviter_id
                )

                if inviter:
                    connection = db()

                    existing = connection.execute(
                        """
                        SELECT id
                        FROM referrals
                        WHERE invited_id=?
                        """,
                        (user.id,)
                    ).fetchone()

                    if not existing:
                        connection.execute(
                            """
                            INSERT INTO referrals(
                                inviter_id,
                                invited_id,
                                created_at
                            )
                            VALUES (?, ?, ?)
                            """,
                            (
                                inviter_id,
                                user.id,
                                now()
                            )
                        )

                        connection.execute(
                            """
                            UPDATE users
                            SET referral_count =
                                referral_count + 1,
                                chances =
                                chances + 1
                            WHERE telegram_id=?
                            """,
                            (inviter_id,)
                        )

                        connection.commit()

                    connection.close()

        except Exception as exc:
            logger.warning(
                "Referral processing failed: %s",
                exc
            )

    # --------------------------------------------------------
    # RULES NOT ACCEPTED
    # --------------------------------------------------------

    if not rules_accepted(user.id):
        await update.message.reply_text(
            "🎉 <b>به محفل خوش‌شانس‌ها خوش آمدید!</b>\n\n"

            "🎁 ثبت‌نام فعلی رایگان است.\n"
            "👥 با معرفی دوستان می‌توانی شانس اضافه بگیری.\n"
            "📸 اینستاگرام\n"
            "▶️ یوتیوب\n"
            "📢 تلگرام\n\n"

            "⚠️ قبل از ورود باید قوانین را مطالعه و "
            "تأیید کنی.\n\n"

            "👇 ابتدا قوانین را بخوان:",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "📜 مطالعه قوانین",
                        callback_data="rules"
                    )
                ]
            ])
        )
        return

    await update.message.reply_text(
        "🔥 <b>خوش برگشتی به محفل خوش‌شانس‌ها!</b>\n\n"
        "از منوی زیر انتخاب کن:",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu()
    )


# ============================================================
# MY ID
# ============================================================

async def myid(update, context):
    await update.message.reply_text(
        "🆔 <b>Telegram ID شما:</b>\n\n"
        f"<code>{update.effective_user.id}</code>",
        parse_mode=ParseMode.HTML
    )


# ============================================================
# ADMIN
# ============================================================

async def admin_command(update, context):
    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text(
            "❌ دسترسی ادمین ندارید.\n\n"
            f"🆔 ID شما:\n"
            f"<code>{user_id}</code>\n\n"
            "این ID را در Environment Variable "
            "<code>ADMIN_IDS</code> قرار دهید.",
            parse_mode=ParseMode.HTML
        )
        return

    await update.message.reply_text(
        "🛠 <b>پنل مدیریت محفل خوش‌شانس‌ها</b>\n\n"
        "مدیریت کاربران، مسابقات، شبکه‌ها، "
        "قابلیت‌ها و تبلیغات از این بخش انجام می‌شود.",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_menu()
    )


async def adminhelp(update, context):
    if not is_admin(
        update.effective_user.id
    ):
        await update.message.reply_text(
            "❌ دسترسی ادمین ندارید."
        )
        return

    await update.message.reply_text(
        "🛠 <b>راهنمای مدیریت</b>\n\n"

        "/admin — پنل مدیریت\n"
        "/myid — شناسه عددی\n"
        "/status — وضعیت سیستم\n"
        "/users — آمار کاربران\n\n"

        "/igfollowers 100000\n"
        "ثبت تعداد اینستاگرام\n\n"

        "/ytfollowers 100000\n"
        "ثبت تعداد یوتیوب\n\n"

        "/tgfollowers 100000\n"
        "ثبت تعداد تلگرام\n\n"

        "/createcampaign عنوان | توضیحات | جایزه\n"
        "ساخت مسابقه\n\n"

        "/campaigns — لیست مسابقات\n"
        "/draw ID — انجام قرعه‌کشی\n"
        "/postnow — ارسال تبلیغ\n\n"

        "⚙️ قابلیت‌های خاموش نیز از پنل مدیریت "
        "قابل فعال‌سازی هستند.",
        parse_mode=ParseMode.HTML
    )


# ============================================================
# STATUS
# ============================================================

async def status(update, context):
    if not is_admin(
        update.effective_user.id
    ):
        await update.message.reply_text(
            "❌ دسترسی ادمین ندارید."
        )
        return

    connection = db()

    users = connection.execute(
        "SELECT COUNT(*) c FROM users"
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

    campaigns = connection.execute(
        "SELECT COUNT(*) c FROM campaigns"
    ).fetchone()["c"]

    winners = connection.execute(
        "SELECT COUNT(*) c FROM winners"
    ).fetchone()["c"]

    connection.close()

    networks = get_networks()

    await update.message.reply_text(
        "📊 <b>وضعیت کامل سیستم</b>\n\n"

        f"👥 کاربران: <b>{fmt_number(users)}</b>\n"
        f"📜 پذیرش قوانین: <b>{fmt_number(accepted)}</b>\n"
        f"👥 دعوت‌های موفق: <b>{fmt_number(referrals)}</b>\n"
        f"🎁 مسابقات: <b>{fmt_number(campaigns)}</b>\n"
        f"🏆 برندگان: <b>{fmt_number(winners)}</b>\n\n"

        f"📸 Instagram: "
        f"<b>{fmt_number(networks['instagram'])}</b>\n"

        f"▶️ YouTube: "
        f"<b>{fmt_number(networks['youtube'])}</b>\n"

        f"📢 Telegram: "
        f"<b>{fmt_number(networks['telegram'])}</b>\n\n"

        f"🚀 فعال‌سازی: "
        f"<b>{'فعال' if check_activation() else 'در انتظار'}</b>\n\n"

        f"💳 پرداخت: "
        f"<b>{'فعال' if setting_bool('paid_registration_enabled') else 'خاموش'}</b>\n"

        f"📸 احراز IG: "
        f"<b>{'فعال' if setting_bool('instagram_verification_enabled') else 'خاموش'}</b>\n"

        f"▶️ احراز YT: "
        f"<b>{'فعال' if setting_bool('youtube_verification_enabled') else 'خاموش'}</b>",
        parse_mode=ParseMode.HTML
    )


# ============================================================
# USERS
# ============================================================

async def users_command(update, context):
    if not is_admin(
        update.effective_user.id
    ):
        await update.message.reply_text(
            "❌ دسترسی ادمین ندارید."
        )
        return

    connection = db()

    total = connection.execute(
        "SELECT COUNT(*) c FROM users"
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
        f"کل کاربران: <b>{fmt_number(total)}</b>\n"
        f"قوانین پذیرفته‌شده: <b>{fmt_number(accepted)}</b>\n"
        f"دعوت موفق: <b>{fmt_number(referrals)}</b>",
        parse_mode=ParseMode.HTML
    )


# ============================================================
# MANUAL NETWORK COUNTERS
# ============================================================

async def set_network_count(
    update,
    context,
    setting_key,
    title
):
    if not is_admin(
        update.effective_user.id
    ):
        await update.message.reply_text(
            "❌ دسترسی ادمین ندارید."
        )
        return

    if not context.args:
        await update.message.reply_text(
            f"مثال:\n/{title.lower()} 100000"
        )
        return

    try:
        value = int(
            context.args[0].replace(",", "")
        )

        if value < 0:
            raise ValueError

    except ValueError:
        await update.message.reply_text(
            "❌ یک عدد صحیح معتبر وارد کنید."
        )
        return

    set_setting(
        setting_key,
        value
    )

    active = check_activation()

    await update.message.reply_text(
        f"✅ <b>{title}</b> بروزرسانی شد.\n\n"
        f"تعداد: <b>{fmt_number(value)}</b>\n\n"
        f"🚀 وضعیت فعال‌سازی: "
        f"<b>{'فعال' if active else 'در انتظار'}</b>",
        parse_mode=ParseMode.HTML
    )


async def igfollowers(update, context):
    await set_network_count(
        update,
        context,
        "instagram_followers",
        "Instagram"
    )


async def ytfollowers(update, context):
    await set_network_count(
        update,
        context,
        "youtube_followers",
        "YouTube"
    )


async def tgfollowers(update, context):
    await set_network_count(
        update,
        context,
        "telegram_followers",
        "Telegram"
    )


# ============================================================
# CAMPAIGNS
# ============================================================

async def createcampaign(update, context):
    if not is_admin(
        update.effective_user.id
    ):
        await update.message.reply_text(
            "❌ دسترسی ادمین ندارید."
        )
        return

    raw = " ".join(context.args)

    parts = [
        item.strip()
        for item in raw.split("|")
    ]

    if len(parts) < 3:
        await update.message.reply_text(
            "فرمت صحیح:\n\n"
            "/createcampaign عنوان | توضیحات | جایزه\n\n"
            "مثال:\n"
            "/createcampaign "
            "جایزه ویژه | مسابقه بزرگ محفل | پژو 405"
        )
        return

    title = parts[0]
    description = parts[1]
    prize = parts[2]

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
            title,
            description,
            prize,
            now()
        )
    )

    campaign_id = cursor.lastrowid

    connection.commit()
    connection.close()

    await update.message.reply_text(
        "✅ <b>مسابقه ساخته شد</b>\n\n"
        f"🆔 ID: <code>{campaign_id}</code>\n"
        f"🎁 {title}\n"
        f"🏆 جایزه: {prize}",
        parse_mode=ParseMode.HTML
    )


async def campaigns_command(update, context):
    connection = db()

    rows = connection.execute(
        """
        SELECT *
        FROM campaigns
        ORDER BY id DESC
        LIMIT 30
        """
    ).fetchall()

    connection.close()

    if not rows:
        await update.message.reply_text(
            "🎁 هنوز مسابقه‌ای ساخته نشده."
        )
        return

    text = "🎁 <b>مسابقات محفل</b>\n\n"

    for row in rows:
        if (
            row["active"]
            and not row["draw_completed"]
        ):
            state = "🟢 فعال"
        else:
            state = "🔴 پایان‌یافته"

        text += (
            f"#{row['id']} — "
            f"<b>{row['title']}</b>\n"
            f"🏆 {row['prize']}\n"
            f"{state}\n\n"
        )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML
    )


# ============================================================
# DRAW
# ============================================================

async def draw(update, context):
    if not is_admin(
        update.effective_user.id
    ):
        await update.message.reply_text(
            "❌ دسترسی ادمین ندارید."
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
            "❌ شناسه مسابقه نامعتبر است."
        )
        return

    # --------------------------------------------------------
    # ACTIVATION CHECK
    # --------------------------------------------------------

    if not check_activation():
        await update.message.reply_text(
            "🔒 هنوز مرحله فعال‌سازی کامل نشده است.\n\n"
            "هر سه شبکه باید به حد نصاب برسند."
        )
        return

    connection = db()

    campaign = connection.execute(
        """
        SELECT *
        FROM campaigns
        WHERE id=?
        """,
        (campaign_id,)
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
            "❌ این مسابقه قبلاً قرعه‌کشی شده است."
        )
        return

    rows = connection.execute(
        """
        SELECT
            p.telegram_id,
            p.chance_count
        FROM participations p
        JOIN users u
          ON u.telegram_id=p.telegram_id
        WHERE p.campaign_id=?
          AND u.blocked=0
        """,
        (campaign_id,)
    ).fetchall()

    connection.close()

    eligible = []

    for row in rows:
        telegram_ok = await check_telegram_membership(
            context.bot,
            row["telegram_id"]
        )

        if telegram_ok:
            count = max(
                1,
                int(row["chance_count"])
            )

            eligible.extend(
                [row["telegram_id"]] * count
            )

    if not eligible:
        await update.message.reply_text(
            "❌ شرکت‌کننده واجد شرایط وجود ندارد."
        )
        return

    winner_id = random.choice(
        eligible
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
            now()
        )
    )

    connection.execute(
        """
        UPDATE campaigns
        SET active=0,
            draw_completed=1
        WHERE id=?
        """,
        (campaign_id,)
    )

    connection.commit()
    connection.close()

    await update.message.reply_text(
        "🎉 <b>قرعه‌کشی انجام شد!</b>\n\n"
        f"🎁 مسابقه: <b>{campaign['title']}</b>\n"
        f"🏆 جایزه: <b>{campaign['prize']}</b>\n"
        f"🆔 برنده: <code>{winner_id}</code>",
        parse_mode=ParseMode.HTML
    )

    try:
        await context.bot.send_message(
            chat_id=TELEGRAM_CHANNEL,
            text=(
                "🎉 <b>نتیجه قرعه‌کشی محفل</b>\n\n"
                f"🎁 <b>{campaign['title']}</b>\n"
                f"🏆 جایزه: <b>{campaign['prize']}</b>\n\n"
                f"🆔 شناسه برنده:\n"
                f"<code>{winner_id}</code>\n\n"
                "🔥 برای مسابقات بعدی همراه محفل باشید."
            ),
            parse_mode=ParseMode.HTML
        )

    except Exception as exc:
        logger.warning(
            "Winner announcement failed: %s",
            exc
        )


# ============================================================
# AUTO POST
# ============================================================

async def postnow(update, context):
    if not is_admin(
        update.effective_user.id
    ):
        await update.message.reply_text(
            "❌ دسترسی ادمین ندارید."
        )
        return

    try:
        message = await context.bot.send_message(
            chat_id=TELEGRAM_CHANNEL,
            text=promotional_text(),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=False
        )

        set_setting(
            "last_auto_post",
            now()
        )

        await update.message.reply_text(
            "✅ تبلیغ ارسال شد.\n"
            f"Message ID: {message.message_id}"
        )

    except Exception as exc:
        logger.warning(
            "Manual post failed: %s",
            exc
        )

        await update.message.reply_text(
            "❌ ارسال تبلیغ ناموفق بود.\n\n"
            "بررسی کن ربات در کانال ادمین باشد."
        )


async def automatic_channel_post(context):
    if not AUTO_POST_ENABLED:
        return

    try:
        await context.bot.send_message(
            chat_id=TELEGRAM_CHANNEL,
            text=promotional_text(),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=False
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
            "Automatic promotional post failed: %s",
            exc
        )


# ============================================================
# CALLBACK - RULES
# ============================================================

async def rules_callback(update, context):
    query = update.callback_query

    await query.answer()

    await query.edit_message_text(
        rules_text(),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ پذیرش قوانین",
                    callback_data="accept_rules"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 بازگشت",
                    callback_data="home"
                )
            ]
        ])
    )


async def accept_rules(update, context):
    query = update.callback_query

    await query.answer()

    create_or_update_user(
        query.from_user
    )

    save_rules_acceptance(
        query.from_user.id
    )

    await query.edit_message_text(
        "✅ <b>قوانین با موفقیت پذیرفته شد.</b>\n\n"
        "🎉 حالا ثبت‌نامت کامل شده و وارد محفل شدی.\n\n"
        "از منوی زیر استفاده کن:",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu()
    )


# ============================================================
# REGISTRATION
# ============================================================

async def register_free(update, context):
    query = update.callback_query

    await query.answer()

    create_or_update_user(
        query.from_user
    )

    if not rules_accepted(
        query.from_user.id
    ):
        await query.edit_message_text(
            "⚠️ ابتدا باید قوانین را مطالعه و "
            "تأیید کنی.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "📜 مطالعه قوانین",
                        callback_data="rules"
                    )
                ]
            ])
        )
        return

    await query.edit_message_text(
        "🎉 <b>ثبت‌نام رایگان شما انجام شد!</b>\n\n"
        "👤 شما در لیست کاربران محفل ثبت شدید.\n"
        "🎟 شانس اولیه: <b>1</b>\n\n"
        "👥 حالا دوستانت را دعوت کن؛ "
        "هر دعوت موفق طبق قوانین یک شانس اضافه "
        "برای تو ایجاد می‌کند.",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu()
    )


async def paid_disabled(update, context):
    query = update.callback_query

    await query.answer(
        "ثبت‌نام پولی فعلاً فعال نیست.",
        show_alert=True
    )


async def register_paid(update, context):
    query = update.callback_query

    await query.answer(
        "بخش پرداخت فعلاً فعال نیست.",
        show_alert=True
    )


# ============================================================
# HOME
# ============================================================

async def home_callback(update, context):
    query = update.callback_query

    await query.answer()

    if not rules_accepted(
        query.from_user.id
    ):
        await query.edit_message_text(
            "🎉 <b>به محفل خوش‌شانس‌ها خوش آمدید!</b>\n\n"
            "برای ورود ابتدا قوانین را مطالعه و تأیید کن.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "📜 مطالعه قوانین",
                        callback_data="rules"
                    )
                ]
            ])
        )
        return

    await query.edit_message_text(
        "🏠 <b>منوی اصلی محفل خوش‌شانس‌ها</b>\n\n"
        "انتخاب کن:",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu()
    )


# ============================================================
# ELIGIBILITY CALLBACK
# ============================================================

async def eligibility_callback(update, context):
    query = update.callback_query

    await query.answer()

    result = await eligibility_status(
        context.bot,
        query.from_user.id
    )

    telegram_text = (
        "✅ تأیید شده"
        if result["telegram"]
        else "❌ تأیید نشده"
    )

    instagram_text = (
        "🔒 احراز فعال"
        if setting_bool(
            "instagram_verification_enabled"
        )
        else "ℹ️ فعلاً احراز خودکار خاموش است"
    )

    youtube_text = (
        "🔒 احراز فعال"
        if setting_bool(
            "youtube_verification_enabled"
        )
        else "ℹ️ فعلاً احراز خودکار خاموش است"
    )

    await query.edit_message_text(
        "🔎 <b>بررسی شرایط شما</b>\n\n"
        f"📢 عضویت تلگرام: {telegram_text}\n"
        f"📸 اینستاگرام: {instagram_text}\n"
        f"▶️ یوتیوب: {youtube_text}\n\n"
        "⚠️ شرایط نهایی هر مسابقه هنگام اجرای همان "
        "مسابقه اعلام می‌شود.",
        parse_mode=ParseMode.HTML,
        reply_markup=eligibility_keyboard()
    )


async def verify_membership(update, context):
    query = update.callback_query

    result = await eligibility_status(
        context.bot,
        query.from_user.id
    )

    await query.answer(
        (
            "عضویت تلگرام تأیید شد ✅"
            if result["telegram"]
            else
            "عضویت تلگرام هنوز تأیید نشده ❌"
        ),
        show_alert=True
    )

    await eligibility_callback(
        update,
        context
    )


# ============================================================
# REFERRAL
# ============================================================

async def referral_callback(update, context):
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

    referral_link = (
        f"{bot_link()}"
        f"?start={query.from_user.id}"
    )

    await query.edit_message_text(
        "👥 <b>سیستم دعوت محفل</b>\n\n"

        f"🎟 شانس‌های شما: "
        f"<b>{user['chances']}</b>\n"

        f"👥 دعوت‌های موفق: "
        f"<b>{user['referral_count']}</b>\n\n"

        "🔥 لینک اختصاصی تو:\n\n"

        f"<code>{referral_link}</code>\n\n"

        "📣 این لینک را برای دوستانت بفرست.\n\n"

        "✅ وقتی فرد جدید از لینک تو وارد ربات شود "
        "و ثبت‌نامش کامل شود، یک دعوت موفق ثبت می‌شود "
        "و یک شانس اضافه می‌گیری.\n\n"

        "⚠️ هر شخص فقط یک بار می‌تواند به‌عنوان "
        "دعوت موفق ثبت شود.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🏠 منوی اصلی",
                    callback_data="home"
                )
            ]
        ])
    )


# ============================================================
# CHANCES
# ============================================================

async def chances_callback(update, context):
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
        "🎟 <b>شانس‌های شما</b>\n\n"
        f"🎟 شانس فعلی: <b>{user['chances']}</b>\n"
        f"👥 دعوت موفق: <b>{user['referral_count']}</b>\n\n"
        "🎁 شانس‌های اضافه از طریق دعوت موفق "
        "به حساب شما ثبت می‌شوند.\n\n"
        "در زمان شرکت در مسابقه، تعداد شانس‌های "
        "ثبت‌شده برای همان مسابقه ذخیره می‌شود.",
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
            ]
        ])
    )


# ============================================================
# CAMPAIGNS CALLBACK
# ============================================================

async def campaigns_callback(update, context):
    query = update.callback_query

    await query.answer()

    if not check_activation():
        await query.edit_message_text(
            "🔒 <b>مسابقات اصلی هنوز باز نشده‌اند.</b>\n\n"
            "🚀 برای رسیدن به مرحله فعال‌سازی، "
            "هر سه شبکه باید به 100K برسند.\n\n"
            "از همین حالا با دعوت دوستان به رشد محفل کمک کن.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🚀 وضعیت 100K",
                        callback_data="network"
                    )
                ],
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
                ]
            ])
        )
        return

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
            "🎁 <b>فعلاً مسابقه فعالی وجود ندارد.</b>\n\n"
            "به‌زودی مسابقات از همین بخش اعلام می‌شوند.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🏠 منوی اصلی",
                        callback_data="home"
                    )
                ]
            ])
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
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ============================================================
# CAMPAIGN DETAILS
# ============================================================

async def campaign_details(update, context):
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
        (campaign_id,)
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
        "برای شرکت روی دکمه زیر بزن.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🎟 شرکت در مسابقه",
                    callback_data=f"join:{campaign_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 مسابقات",
                    callback_data="campaigns"
                )
            ]
        ])
    )


# ============================================================
# JOIN CAMPAIGN
# ============================================================

async def join_campaign(update, context):
    query = update.callback_query

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

    if not rules_accepted(
        query.from_user.id
    ):
        await query.answer(
            "ابتدا قوانین را تأیید کنید.",
            show_alert=True
        )
        return

    if not check_activation():
        await query.answer(
            "مرحله فعال‌سازی هنوز کامل نشده است.",
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
            "ابتدا عضو کانال شو و سپس «بررسی دوباره» را بزن.",
            parse_mode=ParseMode.HTML,
            reply_markup=eligibility_keyboard()
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
        (campaign_id,)
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
            query.from_user.id
        )
    ).fetchone()

    if existing:
        connection.close()

        await query.answer(
            "قبلاً در این مسابقه ثبت‌نام کرده‌ای.",
            show_alert=True
        )
        return

    user = connection.execute(
        """
        SELECT chances
        FROM users
        WHERE telegram_id=?
        """,
        (query.from_user.id,)
    ).fetchone()

    chances = (
        int(user["chances"])
        if user
        else 1
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
            chances,
            now()
        )
    )

    connection.commit()
    connection.close()

    await query.answer(
        "ثبت‌نام در مسابقه انجام شد 🎉",
        show_alert=True
    )

    await query.edit_message_text(
        "🎉 <b>ورود شما به مسابقه ثبت شد!</b>\n\n"
        f"🎁 {campaign['title']}\n"
        f"🏆 جایزه: {campaign['prize']}\n"
        f"🎟 شانس ثبت‌شده: <b>{chances}</b>\n\n"
        "شرایط لازم هنگام قرعه‌کشی نیز بررسی می‌شود.",
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
            ]
        ])
    )


# ============================================================
# SUPPORT
# ============================================================

async def support_callback(update, context):
    query = update.callback_query

    await query.answer()

    await query.edit_message_text(
        "🆘 <b>پشتیبانی محفل</b>\n\n"
        "اگر مشکل یا سوالی داری، همینجا پیام متنی "
        "بفرست تا برای تیم پشتیبانی ثبت شود.\n\n"
        f"👤 پشتیبانی مستقیم: {SUPPORT_USERNAME}",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "💬 پشتیبانی مستقیم",
                    url=(
                        "https://t.me/"
                        f"{SUPPORT_USERNAME.lstrip('@')}"
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "🏠 منوی اصلی",
                    callback_data="home"
                )
            ]
        ])
    )


# ============================================================
# NETWORK CALLBACK
# ============================================================

async def network_callback(update, context):
    query = update.callback_query

    await query.answer()

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
                    "👥 دعوت دوستان",
                    callback_data="referral"
                )
            ],
            [
                InlineKeyboardButton(
                    "🏠 منوی اصلی",
                    callback_data="home"
                )
            ]
        ])
    )


# ============================================================
# ADMIN STATUS CALLBACK
# ============================================================

async def admin_status_callback(update, context):
    query = update.callback_query

    if not is_admin(
        query.from_user.id
    ):
        await query.answer(
            "دسترسی ندارید.",
            show_alert=True
        )
        return

    await query.answer()

    connection = db()

    users = connection.execute(
        "SELECT COUNT(*) c FROM users"
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

    campaigns = connection.execute(
        "SELECT COUNT(*) c FROM campaigns"
    ).fetchone()["c"]

    winners = connection.execute(
        "SELECT COUNT(*) c FROM winners"
    ).fetchone()["c"]

    connection.close()

    networks = get_networks()

    await query.edit_message_text(
        "📊 <b>وضعیت سیستم</b>\n\n"

        f"👥 کاربران: <b>{fmt_number(users)}</b>\n"
        f"📜 پذیرش قوانین: <b>{fmt_number(accepted)}</b>\n"
        f"👥 دعوت‌ها: <b>{fmt_number(referrals)}</b>\n"
        f"🎁 مسابقات: <b>{fmt_number(campaigns)}</b>\n"
        f"🏆 برندگان: <b>{fmt_number(winners)}</b>\n\n"

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
        ])
    )


# ============================================================
# ADMIN USERS CALLBACK
# ============================================================

async def admin_users_callback(update, context):
    query = update.callback_query

    if not is_admin(
        query.from_user.id
    ):
        await query.answer(
            "دسترسی ندارید.",
            show_alert=True
        )
        return

    await query.answer()

    connection = db()

    total = connection.execute(
        "SELECT COUNT(*) c FROM users"
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

    await query.edit_message_text(
        "👥 <b>کاربران</b>\n\n"
        f"کل: <b>{fmt_number(total)}</b>\n"
        f"پذیرش قوانین: <b>{fmt_number(accepted)}</b>\n"
        f"دعوت موفق: <b>{fmt_number(referrals)}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 پنل مدیریت",
                    callback_data="admin"
                )
            ]
        ])
    )


# ============================================================
# ADMIN NETWORKS
# ============================================================

async def admin_networks_callback(update, context):
    query = update.callback_query

    if not is_admin(
        query.from_user.id
    ):
        await query.answer(
            "دسترسی ندارید.",
            show_alert=True
        )
        return

    await query.answer()

    networks = get_networks()

    await query.edit_message_text(
        "📈 <b>مدیریت شمارش شبکه‌ها</b>\n\n"

        f"📸 Instagram: "
        f"<b>{fmt_number(networks['instagram'])}</b>\n"

        f"▶️ YouTube: "
        f"<b>{fmt_number(networks['youtube'])}</b>\n"

        f"📢 Telegram: "
        f"<b>{fmt_number(networks['telegram'])}</b>\n\n"

        "این سه عدد فعلاً به‌صورت دستی توسط ادمین "
        "ثبت می‌شوند.\n\n"

        "دستورات:\n"
        "<code>/igfollowers 100000</code>\n"
        "<code>/ytfollowers 100000</code>\n"
        "<code>/tgfollowers 100000</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 پنل مدیریت",
                    callback_data="admin"
                )
            ]
        ])
    )


# ============================================================
# ADMIN FEATURES
# ============================================================

async def admin_features_callback(update, context):
    query = update.callback_query

    if not is_admin(
        query.from_user.id
    ):
        await query.answer(
            "دسترسی ندارید.",
            show_alert=True
        )
        return

    await query.answer()

    paid = setting_bool(
        "paid_registration_enabled"
    )

    instagram = setting_bool(
        "instagram_verification_enabled"
    )

    youtube = setting_bool(
        "youtube_verification_enabled"
    )

    telegram = setting_bool(
        "telegram_membership_required"
    )

    text = (
        "⚙️ <b>قابلیت‌های سیستم</b>\n\n"

        f"💳 ثبت‌نام پولی: "
        f"<b>{'🟢 روشن' if paid else '🔴 خاموش'}</b>\n"

        f"📸 احراز اینستاگرام: "
        f"<b>{'🟢 روشن' if instagram else '🔴 خاموش'}</b>\n"

        f"▶️ احراز یوتیوب: "
        f"<b>{'🟢 روشن' if youtube else '🔴 خاموش'}</b>\n"

        f"📢 الزام عضویت تلگرام: "
        f"<b>{'🟢 روشن' if telegram else '🔴 خاموش'}</b>\n\n"

        "فعلاً پرداخت و احراز Instagram/YouTube "
        "خاموش هستند."
    )

    buttons = [
        [
            InlineKeyboardButton(
                (
                    "💳 خاموش → روشن"
                    if not paid
                    else
                    "💳 روشن → خاموش"
                ),
                callback_data="toggle_paid"
            )
        ],
        [
            InlineKeyboardButton(
                (
                    "📸 احراز IG خاموش → روشن"
                    if not instagram
                    else
                    "📸 احراز IG روشن → خاموش"
                ),
                callback_data="toggle_instagram"
            )
        ],
        [
            InlineKeyboardButton(
                (
                    "▶️ احراز YT خاموش → روشن"
                    if not youtube
                    else
                    "▶️ احراز YT روشن → خاموش"
                ),
                callback_data="toggle_youtube"
            )
        ],
        [
            InlineKeyboardButton(
                (
                    "📢 تلگرام خاموش → روشن"
                    if not telegram
                    else
                    "📢 تلگرام روشن → خاموش"
                ),
                callback_data="toggle_telegram"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 پنل مدیریت",
                callback_data="admin"
            )
        ]
    ]

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def toggle_feature(
    update,
    context,
    key,
    title
):
    query = update.callback_query

    if not is_admin(
        query.from_user.id
    ):
        await query.answer(
            "دسترسی ندارید.",
            show_alert=True
        )
        return

    current = setting_bool(key)

    set_setting(
        key,
        "0" if current else "1"
    )

    await query.answer(
        f"{title} {'خاموش' if current else 'روشن'} شد.",
        show_alert=True
    )

    await admin_features_callback(
        update,
        context
    )


# ============================================================
# ADMIN POST
# ============================================================

async def admin_post_callback(update, context):
    query = update.callback_query

    if not is_admin(
        query.from_user.id
    ):
        await query.answer(
            "دسترسی ندارید.",
            show_alert=True
        )
        return

    await query.answer()

    try:
        await context.bot.send_message(
            chat_id=TELEGRAM_CHANNEL,
            text=promotional_text(),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=False
        )

        text = "✅ پیام تبلیغاتی ارسال شد."

    except Exception as exc:
        logger.warning(
            "Admin post error: %s",
            exc
        )

        text = (
            "❌ ارسال ناموفق بود.\n\n"
            "ربات باید در کانال ادمین باشد."
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
        ])
    )


# ============================================================
# ADMIN CAMPAIGNS
# ============================================================

async def admin_campaigns_callback(update, context):
    query = update.callback_query

    if not is_admin(
        query.from_user.id
    ):
        await query.answer(
            "دسترسی ندارید.",
            show_alert=True
        )
        return

    await query.answer()

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
        text = "🎁 هنوز مسابقه‌ای ساخته نشده."

    else:
        text = "🎁 <b>مسابقات</b>\n\n"

        for row in rows:
            state = (
                "🟢 فعال"
                if row["active"]
                and not row["draw_completed"]
                else "🔴 پایان‌یافته"
            )

            text += (
                f"#{row['id']} "
                f"<b>{row['title']}</b>\n"
                f"🏆 {row['prize']}\n"
                f"{state}\n\n"
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
        ])
    )


# ============================================================
# ADMIN LAST DRAW
# ============================================================

async def admin_last_draw_callback(update, context):
    query = update.callback_query

    if not is_admin(
        query.from_user.id
    ):
        await query.answer(
            "دسترسی ندارید.",
            show_alert=True
        )
        return

    await query.answer()

    connection = db()

    rows = connection.execute(
        """
        SELECT
            w.*,
            c.title
        FROM winners w
        LEFT JOIN campaigns c
            ON c.id=w.campaign_id
        ORDER BY w.id DESC
        LIMIT 10
        """
    ).fetchall()

    connection.close()

    if not rows:
        text = "🎲 هنوز قرعه‌کشی انجام نشده."

    else:
        text = "🎲 <b>آخرین قرعه‌کشی‌ها</b>\n\n"

        for row in rows:
            text += (
                f"🎁 {row['title']}\n"
                f"🏆 {row['prize']}\n"
                f"🆔 <code>{row['telegram_id']}</code>\n\n"
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
        ])
    )


# ============================================================
# ADMIN MAIN CALLBACK
# ============================================================

async def admin_callback(update, context):
    query = update.callback_query

    if not is_admin(
        query.from_user.id
    ):
        await query.answer(
            "دسترسی ندارید.",
            show_alert=True
        )
        return

    await query.answer()

    await query.edit_message_text(
        "🛠 <b>پنل مدیریت محفل</b>\n\n"
        "یک بخش را انتخاب کن:",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_menu()
    )


# ============================================================
# TEXT / SUPPORT
# ============================================================

async def text_message(update, context):
    user = update.effective_user

    create_or_update_user(user)

    text = (
        update.message.text or ""
    ).strip()

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
            now()
        )
    )

    ticket_id = cursor.lastrowid

    connection.commit()
    connection.close()

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=(
                    "🆘 <b>تیکت جدید پشتیبانی</b>\n\n"
                    f"🎫 Ticket: <code>{ticket_id}</code>\n"
                    f"👤 {user.full_name}\n"
                    f"🆔 <code>{user.id}</code>\n\n"
                    f"{text}"
                ),
                parse_mode=ParseMode.HTML
            )

        except Exception as exc:
            logger.warning(
                "Support notification failed: %s",
                exc
            )

    await update.message.reply_text(
        "✅ پیام شما ثبت شد.\n\n"
        f"🎫 شماره پیگیری: <code>{ticket_id}</code>\n\n"
        "پیام برای پشتیبانی ارسال شد.",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu()
    )


# ============================================================
# ERROR
# ============================================================

async def error_handler(update, context):
    logger.exception(
        "Unhandled exception",
        exc_info=context.error
    )

    try:
        if (
            update
            and update.effective_message
        ):
            await update.effective_message.reply_text(
                "⚠️ یک خطای موقت رخ داد.\n"
                "لطفاً دوباره تلاش کنید."
            )

    except Exception:
        pass


# ============================================================
# BACKGROUND YOUTUBE
# ============================================================

async def youtube_background_update(context):
    try:
        count = fetch_youtube_followers()

        if count is None:
            return

        set_setting(
            "youtube_followers",
            count
        )

        set_setting(
            "last_youtube_check",
            now()
        )

        check_activation()

    except Exception as exc:
        logger.warning(
            "YouTube background update failed: %s",
            exc
        )


# ============================================================
# POST INIT
# ============================================================

async def post_init(application):
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

    # --------------------------------------------------------
    # AUTO PROMOTIONAL POST EVERY 2 HOURS
    # --------------------------------------------------------

    if AUTO_POST_ENABLED:

        application.job_queue.run_repeating(
            automatic_channel_post,
            interval=AUTO_POST_HOURS * 60 * 60,
            first=60,
            name="mahfel_auto_post"
        )

    # --------------------------------------------------------
    # OPTIONAL YOUTUBE API UPDATE
    # --------------------------------------------------------

    if (
        YOUTUBE_API_KEY
        and
        YOUTUBE_CHANNEL_ID
    ):

        application.job_queue.run_repeating(
            youtube_background_update,
            interval=60 * 60,
            first=120,
            name="youtube_update"
        )


# ============================================================
# APPLICATION
# ============================================================

def build_application():
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
            "ytfollowers",
            ytfollowers
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

    # --------------------------------------------------------
    # RULES / REGISTRATION
    # --------------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            rules_callback,
            pattern=r"^rules$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            accept_rules,
            pattern=r"^accept_rules$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            register_free,
            pattern=r"^register_free$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            register_paid,
            pattern=r"^register_paid$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            paid_disabled,
            pattern=r"^paid_disabled$"
        )
    )

    # --------------------------------------------------------
    # MAIN
    # --------------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            home_callback,
            pattern=r"^home$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            eligibility_callback,
            pattern=r"^eligibility$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            verify_membership,
            pattern=r"^verify_membership$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            referral_callback,
            pattern=r"^referral$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            chances_callback,
            pattern=r"^my_chances$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            campaigns_callback,
            pattern=r"^campaigns$"
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

    application.add_handler(
        CallbackQueryHandler(
            support_callback,
            pattern=r"^support$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            network_callback,
            pattern=r"^network$"
        )
    )

    # --------------------------------------------------------
    # ADMIN
    # --------------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            admin_callback,
            pattern=r"^admin$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            admin_status_callback,
            pattern=r"^admin_status$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            admin_users_callback,
            pattern=r"^admin_users$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            admin_campaigns_callback,
            pattern=r"^admin_campaigns$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            admin_post_callback,
            pattern=r"^admin_post$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            admin_networks_callback,
            pattern=r"^admin_networks$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            admin_features_callback,
            pattern=r"^admin_features$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            admin_last_draw_callback,
            pattern=r"^admin_last_draw$"
        )
    )

    # --------------------------------------------------------
    # FEATURE TOGGLES
    # --------------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            lambda update, context:
            toggle_feature(
                update,
                context,
                "paid_registration_enabled",
                "ثبت‌نام پولی"
            ),
            pattern=r"^toggle_paid$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            lambda update, context:
            toggle_feature(
                update,
                context,
                "instagram_verification_enabled",
                "احراز اینستاگرام"
            ),
            pattern=r"^toggle_instagram$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            lambda update, context:
            toggle_feature(
                update,
                context,
                "youtube_verification_enabled",
                "احراز یوتیوب"
            ),
            pattern=r"^toggle_youtube$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            lambda update, context:
            toggle_feature(
                update,
                context,
                "telegram_membership_required",
                "الزام عضویت تلگرام"
            ),
            pattern=r"^toggle_telegram$"
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

    application.add_error_handler(
        error_handler
    )

    return application


# ============================================================
# MAIN
# ============================================================

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN environment variable is missing."
        )

    init_db()

    application = build_application()

    if RENDER_EXTERNAL_URL:
        webhook_url = (
            f"{RENDER_EXTERNAL_URL.rstrip('/')}/"
            f"{WEBHOOK_PATH}"
        )

        logger.info(
            "Starting Render webhook: %s",
            webhook_url
        )

        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=WEBHOOK_PATH,
            webhook_url=webhook_url,
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES
        )

    else:
        logger.info(
            "Starting polling mode..."
        )

        application.run_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES
        )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
