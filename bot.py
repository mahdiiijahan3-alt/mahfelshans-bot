import os
import sqlite3
import logging
import random
import asyncio
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote

import requests

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("MAHFELSHANS")


# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

BOT_USERNAME = os.getenv(
    "BOT_USERNAME",
    "MahfelShansBot",
).strip().lstrip("@")

TELEGRAM_CHANNEL = os.getenv(
    "TELEGRAM_CHANNEL",
    "@MahfelShans",
).strip()

INSTAGRAM_URL = os.getenv(
    "INSTAGRAM_URL",
    "https://instagram.com/MAHFELSHANS",
).strip()

YOUTUBE_URL = os.getenv(
    "YOUTUBE_URL",
    "https://youtube.com/@mahfelshans",
).strip()

SUPPORT_USERNAME = os.getenv(
    "SUPPORT_USERNAME",
    "",
).strip().lstrip("@")

DATABASE = os.getenv(
    "DATABASE",
    "mahfelshans.db",
).strip()

ADMIN_IDS_RAW = os.getenv(
    "ADMIN_IDS",
    "",
).strip()

ACTIVATION_TARGET = int(
    os.getenv("ACTIVATION_TARGET", "100000")
)

# ثبت‌نام رایگان روشن است
FREE_REGISTRATION_ENABLED = True

# ثبت‌نام پولی فعلاً خاموش است
PAID_REGISTRATION_ENABLED = False

# بررسی عضویت تلگرام توسط خود ربات
TELEGRAM_MEMBERSHIP_REQUIRED = (
    os.getenv("TELEGRAM_MEMBERSHIP_REQUIRED", "true").lower()
    in ("1", "true", "yes", "on")
)

# ارسال خودکار تبلیغ به کانال
AUTO_POST_ENABLED = (
    os.getenv("AUTO_POST_ENABLED", "true").lower()
    in ("1", "true", "yes", "on")
)

AUTO_POST_HOURS = float(
    os.getenv("AUTO_POST_HOURS", "2")
)

PORT = int(
    os.getenv("PORT", "10000")
)

YOUTUBE_API_KEY = os.getenv(
    "YOUTUBE_API_KEY",
    "",
).strip()

YOUTUBE_CHANNEL_ID = os.getenv(
    "YOUTUBE_CHANNEL_ID",
    "",
).strip()


def parse_admin_ids():
    result = []

    for item in ADMIN_IDS_RAW.split(","):
        item = item.strip()

        if not item:
            continue

        try:
            result.append(int(item))
        except ValueError:
            logger.warning("Invalid ADMIN_IDS value: %s", item)

    return result


ADMIN_IDS = parse_admin_ids()


# ============================================================
# DATABASE
# ============================================================

DB_LOCK = threading.Lock()


def db_connect():
    conn = sqlite3.connect(
        DATABASE,
        timeout=30,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    return conn


def db_execute(query, params=(), fetchone=False, fetchall=False, commit=True):
    with DB_LOCK:
        conn = db_connect()

        try:
            cur = conn.cursor()
            cur.execute(query, params)

            if commit:
                conn.commit()

            if fetchone:
                return cur.fetchone()

            if fetchall:
                return cur.fetchall()

            return cur.lastrowid

        finally:
            conn.close()


def init_database():
    with DB_LOCK:
        conn = db_connect()

        try:
            cur = conn.cursor()

            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    registered INTEGER DEFAULT 0,
                    registration_type TEXT DEFAULT 'free',
                    rules_accepted INTEGER DEFAULT 0,
                    instagram_follow INTEGER DEFAULT 0,
                    youtube_follow INTEGER DEFAULT 0,
                    telegram_member INTEGER DEFAULT 0,
                    chances INTEGER DEFAULT 0,
                    referred_by INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS referrals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    referrer_id INTEGER NOT NULL,
                    referred_id INTEGER UNIQUE NOT NULL,
                    successful INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS campaigns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT,
                    prize TEXT,
                    status TEXT DEFAULT 'open',
                    draw_allowed INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS participations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    campaign_id INTEGER NOT NULL,
                    chances INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL,
                    UNIQUE(user_id, campaign_id)
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS winners (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    telegram_id INTEGER NOT NULL,
                    chances_at_draw INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS rule_acceptances (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER NOT NULL,
                    rules_version TEXT NOT NULL,
                    accepted_at TEXT NOT NULL,
                    UNIQUE(telegram_id, rules_version)
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS support_tickets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_telegram_id INTEGER NOT NULL,
                    admin_telegram_id INTEGER,
                    message TEXT NOT NULL,
                    status TEXT DEFAULT 'open',
                    created_at TEXT NOT NULL,
                    answered_at TEXT
                )
            """)

            cur.execute("""
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
                "network_activated": "0",
                "rules_version": "1.0",
                "free_registration_enabled": "1",
                "paid_registration_enabled": "0",
                "membership_required": "1",
                "last_auto_post": "",
            }

            for key, value in defaults.items():
                cur.execute(
                    """
                    INSERT OR IGNORE INTO settings(key, value)
                    VALUES (?, ?)
                    """,
                    (key, value),
                )

            # مسابقه اصلی را فقط اگر وجود ندارد بساز
            existing = cur.execute(
                "SELECT id FROM campaigns ORDER BY id LIMIT 1"
            ).fetchone()

            if existing is None:
                cur.execute(
                    """
                    INSERT INTO campaigns(
                        title,
                        description,
                        prize,
                        status,
                        draw_allowed,
                        created_at
                    )
                    VALUES (?, ?, ?, 'open', 0, ?)
                    """,
                    (
                        "اولین مسابقه محفل خوش‌شانس‌ها",
                        "ثبت‌نام از همین حالا آزاد است. قرعه‌کشی پس از فعال شدن شبکه انجام می‌شود.",
                        "جایزه طبق اطلاع‌رسانی رسمی محفل",
                        now_iso(),
                    ),
                )

            conn.commit()

        finally:
            conn.close()


# ============================================================
# HELPERS
# ============================================================

def now_iso():
    return datetime.now(timezone.utc).isoformat()


def get_setting(key, default=""):
    row = db_execute(
        "SELECT value FROM settings WHERE key = ?",
        (key,),
        fetchone=True,
        commit=False,
    )

    if row is None:
        return default

    return row["value"]


def set_setting(key, value):
    db_execute(
        """
        INSERT INTO settings(key, value)
        VALUES (?, ?)
        ON CONFLICT(key)
        DO UPDATE SET value = excluded.value
        """,
        (key, str(value)),
    )


def get_user(telegram_id):
    return db_execute(
        """
        SELECT *
        FROM users
        WHERE telegram_id = ?
        """,
        (telegram_id,),
        fetchone=True,
        commit=False,
    )


def ensure_user(tg_user):
    existing = get_user(tg_user.id)

    if existing:
        db_execute(
            """
            UPDATE users
            SET username = ?,
                first_name = ?,
                last_name = ?,
                updated_at = ?
            WHERE telegram_id = ?
            """,
            (
                tg_user.username or "",
                tg_user.first_name or "",
                tg_user.last_name or "",
                now_iso(),
                tg_user.id,
            ),
        )

        return get_user(tg_user.id)

    db_execute(
        """
        INSERT INTO users(
            telegram_id,
            username,
            first_name,
            last_name,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            tg_user.id,
            tg_user.username or "",
            tg_user.first_name or "",
            tg_user.last_name or "",
            now_iso(),
            now_iso(),
        ),
    )

    return get_user(tg_user.id)


def is_admin(user_id):
    return user_id in ADMIN_IDS


def network_activated():
    return get_setting("network_activated", "0") == "1"


def get_counts():
    return {
        "instagram": int(get_setting("instagram_followers", "0") or 0),
        "youtube": int(get_setting("youtube_followers", "0") or 0),
        "telegram": int(get_setting("telegram_followers", "0") or 0),
    }


def calculate_activation():
    counts = get_counts()

    return (
        counts["instagram"] >= ACTIVATION_TARGET
        and counts["youtube"] >= ACTIVATION_TARGET
        and counts["telegram"] >= ACTIVATION_TARGET
    )


def update_activation_status():
    active = calculate_activation()

    set_setting(
        "network_activated",
        "1" if active else "0",
    )

    return active


def rules_version():
    return get_setting("rules_version", "1.0")


# ============================================================
# RULES
# ============================================================

RULES_TEXT = f"""
<b>📜 قوانین رسمی محفل خوش‌شانس‌ها</b>

1️⃣ ثبت‌نام رایگان در حال حاضر فعال است.

2️⃣ ثبت‌نام پولی فعلاً غیرفعال است و تا زمان اعلام رسمی هیچ مبلغی از کاربران دریافت نمی‌شود.

3️⃣ ثبت‌نام مسابقه با «فعال‌سازی شبکه» دو موضوع جدا هستند.
یعنی شما می‌توانید از همین حالا ثبت‌نام کنید، حتی اگر شبکه هنوز به {ACTIVATION_TARGET:,} نرسیده باشد.

4️⃣ هر کاربر پس از ثبت‌نام، طبق قوانین مسابقه شانس پایه دریافت می‌کند.

5️⃣ معرفی موفق افراد جدید می‌تواند برای معرف شانس اضافه ایجاد کند.
معرفی زمانی موفق محسوب می‌شود که فرد جدید واقعاً از لینک معرفی وارد ربات و ثبت‌نام کند.

6️⃣ برای دریافت جایزه، رعایت شرایط اعلام‌شده مسابقه و عضویت در کانال تلگرام الزامی است.

7️⃣ دنبال کردن اینستاگرام و یوتیوب جزو شرایط اعلام‌شده محفل است.
بررسی خودکار این دو شبکه فعلاً فعال نیست و روش بررسی نهایی در زمان اعلام مسابقه مشخص می‌شود.

8️⃣ شمارش فعلی اینستاگرام و یوتیوب توسط مدیریت ثبت می‌شود.
شمارش اعضای تلگرام توسط خود ربات قابل بررسی است.

9️⃣ قرعه‌کشی فقط پس از فعال شدن شبکه انجام می‌شود.
فعال شدن شبکه زمانی است که هر سه عدد اینستاگرام، یوتیوب و تلگرام به حداقل {ACTIVATION_TARGET:,} برسند.

🔟 در صورت باز شدن ثبت‌نام پولی در آینده، قوانین و شرایط آن قبل از پرداخت به کاربر نمایش داده می‌شود و پذیرش قوانین ثبت‌شده کاربر محفوظ خواهد بود.

1️⃣1️⃣ هیچ‌کس صرفاً با ثبت‌نام یا معرفی، برنده قطعی نیست.

1️⃣2️⃣ نتیجه قرعه‌کشی و شرایط دریافت جایزه طبق قوانین همان مسابقه اعلام خواهد شد.

1️⃣3️⃣ هرگونه تقلب، ثبت‌نام تکراری، سوءاستفاده از سیستم معرفی یا اطلاعات جعلی می‌تواند باعث حذف کاربر از مسابقه شود.

1️⃣4️⃣ محفل خوش‌شانس‌ها حق دارد برای جلوگیری از تقلب، شرایط فنی و اجرایی مسابقات را با اطلاع‌رسانی رسمی به‌روزرسانی کند.

<b>نسخه قوانین: {rules_version()}</b>
"""


def has_accepted_rules(user_id):
    row = db_execute(
        """
        SELECT id
        FROM rule_acceptances
        WHERE telegram_id = ?
          AND rules_version = ?
        """,
        (user_id, rules_version()),
        fetchone=True,
        commit=False,
    )

    return row is not None


def save_rules_acceptance(user_id):
    db_execute(
        """
        INSERT OR IGNORE INTO rule_acceptances(
            telegram_id,
            rules_version,
            accepted_at
        )
        VALUES (?, ?, ?)
        """,
        (
            user_id,
            rules_version(),
            now_iso(),
        ),
    )

    db_execute(
        """
        UPDATE users
        SET rules_accepted = 1,
            updated_at = ?
        WHERE telegram_id = ?
        """,
        (now_iso(), user_id),
    )


# ============================================================
# TELEGRAM MEMBERSHIP
# ============================================================

async def check_telegram_membership(bot, user_id):
    if not TELEGRAM_MEMBERSHIP_REQUIRED:
        return True

    try:
        member = await bot.get_chat_member(
            chat_id=TELEGRAM_CHANNEL,
            user_id=user_id,
        )

        if member.status in (
            "creator",
            "administrator",
            "member",
        ):
            return True

        if member.status == "restricted":
            return bool(
                getattr(member, "is_member", False)
            )

        return False

    except TelegramError as exc:
        logger.warning(
            "Telegram membership check failed: %s",
            exc,
        )
        return False

    except Exception as exc:
        logger.exception(
            "Unexpected membership error: %s",
            exc,
        )
        return False


async def refresh_user_membership(bot, user_id):
    member = await check_telegram_membership(
        bot,
        user_id,
    )

    db_execute(
        """
        UPDATE users
        SET telegram_member = ?,
            updated_at = ?
        WHERE telegram_id = ?
        """,
        (
            1 if member else 0,
            now_iso(),
            user_id,
        ),
    )

    return member


# ============================================================
# KEYBOARDS
# ============================================================

def main_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🎟 ثبت‌نام مسابقه",
                callback_data="register",
            ),
            InlineKeyboardButton(
                "🏆 مسابقات",
                callback_data="campaigns",
            ),
        ],
        [
            InlineKeyboardButton(
                "🎯 شانس‌های من",
                callback_data="my_chances",
            ),
            InlineKeyboardButton(
                "👥 دعوت دوستان",
                callback_data="referral",
            ),
        ],
        [
            InlineKeyboardButton(
                "📊 وضعیت فعال‌سازی",
                callback_data="activation",
            ),
            InlineKeyboardButton(
                "✅ شرایط من",
                callback_data="eligibility",
            ),
        ],
        [
            InlineKeyboardButton(
                "📸 اینستاگرام",
                url=INSTAGRAM_URL,
            ),
            InlineKeyboardButton(
                "▶️ یوتیوب",
                url=YOUTUBE_URL,
            ),
        ],
        [
            InlineKeyboardButton(
                "📢 کانال تلگرام",
                url=f"https://t.me/{TELEGRAM_CHANNEL.lstrip('@')}",
            ),
        ],
        [
            InlineKeyboardButton(
                "📜 قوانین",
                callback_data="rules",
            ),
            InlineKeyboardButton(
                "🎧 پشتیبانی",
                callback_data="support",
            ),
        ],
    ])


def back_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🏠 منوی اصلی",
                callback_data="home",
            )
        ]
    ])


def registration_menu():
    paid_text = (
        "💳 ثبت‌نام پولی 🔒"
        if not PAID_REGISTRATION_ENABLED
        else "💳 ثبت‌نام پولی"
    )

    paid_callback = (
        "paid_disabled"
        if not PAID_REGISTRATION_ENABLED
        else "register_paid"
    )

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🆓 ثبت‌نام رایگان",
                callback_data="register_free",
            )
        ],
        [
            InlineKeyboardButton(
                paid_text,
                callback_data=paid_callback,
            )
        ],
        [
            InlineKeyboardButton(
                "📜 مشاهده قوانین",
                callback_data="rules",
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 بازگشت",
                callback_data="home",
            )
        ],
    ])


def campaign_keyboard(campaigns):
    buttons = []

    for campaign in campaigns:
        buttons.append([
            InlineKeyboardButton(
                f"🎟 {campaign['title']}",
                callback_data=f"join:{campaign['id']}",
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "🔙 بازگشت",
            callback_data="home",
        )
    ])

    return InlineKeyboardMarkup(buttons)


def support_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✉️ ارسال پیام به پشتیبانی",
                callback_data="support_new",
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 بازگشت",
                callback_data="home",
            )
        ],
    ])


# ============================================================
# TEXT
# ============================================================

def home_text(user):
    registered = bool(user and user["registered"])
    chances = int(user["chances"] if user else 0)

    status = "✅ ثبت‌نام شده" if registered else "⭕ هنوز ثبت‌نام نکرده"

    return f"""
<b>🎉 محفل خوش‌شانس‌ها</b>

جایی برای مسابقه، شانس و جایزه.

<b>وضعیت شما:</b>
{status}

🎯 شانس فعلی: <b>{chances}</b>

ثبت‌نام مسابقه از همین حالا امکان‌پذیر است.
فعال شدن قرعه‌کشی موضوع جداگانه‌ای است و پس از رسیدن شبکه به هدف اعلام‌شده انجام می‌شود.

از منوی زیر انتخاب کن:
"""


def activation_text():
    counts = get_counts()

    ig = counts["instagram"]
    yt = counts["youtube"]
    tg = counts["telegram"]

    ig_ok = ig >= ACTIVATION_TARGET
    yt_ok = yt >= ACTIVATION_TARGET
    tg_ok = tg >= ACTIVATION_TARGET

    status = (
        "🟢 شبکه فعال شده است."
        if network_activated()
        else "🟡 شبکه هنوز فعال نشده است."
    )

    return f"""
<b>📊 وضعیت فعال‌سازی محفل</b>

{status}

هدف فعال‌سازی: <b>{ACTIVATION_TARGET:,}</b>

📸 اینستاگرام:
<b>{ig:,}</b> {'✅' if ig_ok else '⏳'}

▶️ یوتیوب:
<b>{yt:,}</b> {'✅' if yt_ok else '⏳'}

📢 تلگرام:
<b>{tg:,}</b> {'✅' if tg_ok else '⏳'}

<b>نکته مهم:</b>
ثبت‌نام مسابقه منتظر فعال شدن شبکه نمی‌ماند.
شما می‌توانید همین حالا ثبت‌نام کنید و شانس خود را جمع کنید.

قرعه‌کشی فقط پس از فعال شدن شبکه انجام می‌شود.
"""


# ============================================================
# REFERRAL
# ============================================================

def referral_link(user_id):
    return (
        f"https://t.me/{BOT_USERNAME}"
        f"?start=ref_{user_id}"
    )


def process_referral(new_user_id, referrer_id):
    if not referrer_id:
        return False

    if new_user_id == referrer_id:
        return False

    referrer = get_user(referrer_id)

    if referrer is None:
        return False

    already = db_execute(
        """
        SELECT id
        FROM referrals
        WHERE referred_id = ?
        """,
        (new_user_id,),
        fetchone=True,
        commit=False,
    )

    if already:
        return False

    db_execute(
        """
        INSERT INTO referrals(
            referrer_id,
            referred_id,
            successful,
            created_at
        )
        VALUES (?, ?, 1, ?)
        """,
        (
            referrer_id,
            new_user_id,
            now_iso(),
        ),
    )

    db_execute(
        """
        UPDATE users
        SET chances = chances + 1,
            updated_at = ?
        WHERE telegram_id = ?
        """,
        (
            now_iso(),
            referrer_id,
        ),
    )

    return True


# ============================================================
# REGISTRATION
# ============================================================

async def register_free_user(update, context):
    query = update.callback_query
    user = query.from_user

    await query.answer()

    ensure_user(user)

    if not FREE_REGISTRATION_ENABLED:
        await query.edit_message_text(
            "🛑 ثبت‌نام رایگان فعلاً غیرفعال است.",
            reply_markup=back_menu(),
        )
        return

    if not has_accepted_rules(user.id):
        await query.edit_message_text(
            RULES_TEXT
            + "\n\n<b>برای ثبت‌نام ابتدا باید قوانین را بپذیری.</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "✅ قوانین را می‌پذیرم",
                        callback_data="accept_rules_register",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔙 بازگشت",
                        callback_data="register",
                    )
                ],
            ]),
        )
        return

    db_execute(
        """
        UPDATE users
        SET registered = 1,
            registration_type = 'free',
            chances = CASE
                WHEN chances < 1 THEN 1
                ELSE chances
            END,
            updated_at = ?
        WHERE telegram_id = ?
        """,
        (
            now_iso(),
            user.id,
        ),
    )

    await query.edit_message_text(
        """
<b>🎉 ثبت‌نام شما با موفقیت انجام شد.</b>

🆓 نوع ثبت‌نام: رایگان

🎯 شما حداقل ۱ شانس پایه دارید.

از اینجا به بعد می‌توانی با معرفی دوستان، شانس‌های بیشتری بگیری.

⚠️ ثبت‌نام شما مستقل از فعال شدن شبکه است؛
برای قرعه‌کشی، شرایط فعال‌سازی شبکه باید بعداً تکمیل شود.
""",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(),
    )


# ============================================================
# CAMPAIGNS
# ============================================================

def get_open_campaigns():
    return db_execute(
        """
        SELECT *
        FROM campaigns
        WHERE status = 'open'
        ORDER BY id DESC
        """,
        fetchall=True,
        commit=False,
    )


async def show_campaigns(update, context):
    query = update.callback_query
    await query.answer()

    campaigns = get_open_campaigns()

    if not campaigns:
        await query.edit_message_text(
            """
🏆 <b>مسابقات</b>

در حال حاضر مسابقه فعالی وجود ندارد.
""",
            parse_mode=ParseMode.HTML,
            reply_markup=back_menu(),
        )
        return

    text = "<b>🏆 مسابقات فعال</b>\n\n"

    for campaign in campaigns:
        text += (
            f"🎟 <b>{campaign['title']}</b>\n"
            f"{campaign['description'] or ''}\n"
            f"🎁 جایزه: {campaign['prize'] or 'طبق اطلاع‌رسانی رسمی'}\n\n"
        )

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=campaign_keyboard(campaigns),
    )


async def join_campaign(update, context):
    query = update.callback_query
    await query.answer()

    try:
        campaign_id = int(query.data.split(":", 1)[1])
    except Exception:
        await query.edit_message_text(
            "❌ شناسه مسابقه نامعتبر است.",
            reply_markup=back_menu(),
        )
        return

    user = query.from_user
    ensure_user(user)

    if not has_accepted_rules(user.id):
        await query.edit_message_text(
            RULES_TEXT
            + "\n\n<b>قبل از ثبت‌نام مسابقه باید قوانین را بپذیری.</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "✅ پذیرش قوانین",
                        callback_data=f"accept_rules_join:{campaign_id}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔙 بازگشت",
                        callback_data="campaigns",
                    )
                ],
            ]),
        )
        return

    campaign = db_execute(
        """
        SELECT *
        FROM campaigns
        WHERE id = ?
          AND status = 'open'
        """,
        (campaign_id,),
        fetchone=True,
        commit=False,
    )

    if campaign is None:
        await query.edit_message_text(
            "❌ این مسابقه دیگر فعال نیست.",
            reply_markup=back_menu(),
        )
        return

    existing = db_execute(
        """
        SELECT id
        FROM participations
        WHERE user_id = ?
          AND campaign_id = ?
        """,
        (
            user.id,
            campaign_id,
        ),
        fetchone=True,
        commit=False,
    )

    if existing:
        await query.edit_message_text(
            f"""
✅ شما قبلاً در مسابقه <b>{campaign['title']}</b> ثبت‌نام کرده‌اید.

🎯 شانس‌های حساب شما از بخش «شانس‌های من» قابل مشاهده است.
""",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu(),
        )
        return

    db_execute(
        """
        INSERT INTO participations(
            user_id,
            campaign_id,
            chances,
            created_at
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            user.id,
            campaign_id,
            1,
            now_iso(),
        ),
    )

    db_execute(
        """
        UPDATE users
        SET registered = 1,
            registration_type = 'free',
            chances = CASE
                WHEN chances < 1 THEN 1
                ELSE chances
            END,
            updated_at = ?
        WHERE telegram_id = ?
        """,
        (
            now_iso(),
            user.id,
        ),
    )

    await query.edit_message_text(
        f"""
🎉 <b>ثبت‌نام مسابقه با موفقیت انجام شد.</b>

🏆 مسابقه:
<b>{campaign['title']}</b>

🎯 شانس پایه: <b>۱</b>

برای افزایش شانس، دوستانت را با لینک اختصاصی خودت دعوت کن.
""",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(),
    )


# ============================================================
# RULES CALLBACKS
# ============================================================

async def show_rules(update, context):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        RULES_TEXT,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ قبول قوانین",
                    callback_data="accept_rules",
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 بازگشت",
                    callback_data="home",
                )
            ],
        ]),
    )


async def accept_rules(update, context):
    query = update.callback_query
    await query.answer()

    save_rules_acceptance(query.from_user.id)

    await query.edit_message_text(
        """
✅ <b>قوانین با موفقیت پذیرفته شد.</b>

حالا می‌توانی برای مسابقه ثبت‌نام کنی.
""",
        parse_mode=ParseMode.HTML,
        reply_markup=registration_menu(),
    )


async def accept_rules_register(update, context):
    query = update.callback_query
    await query.answer()

    save_rules_acceptance(query.from_user.id)

    await register_free_user(update, context)


async def accept_rules_join(update, context):
    query = update.callback_query
    await query.answer()

    try:
        campaign_id = int(
            query.data.split(":", 1)[1]
        )
    except Exception:
        await query.edit_message_text(
            "❌ خطا در مسابقه.",
            reply_markup=back_menu(),
        )
        return

    save_rules_acceptance(query.from_user.id)

    # ثبت‌نام را مستقیم انجام بده
    class FakeQuery:
        pass

    # همان منطق join را با تغییر callback اجرا نمی‌کنیم؛
    # برای جلوگیری از پیچیدگی، کاربر را به لیست مسابقات برمی‌گردانیم.
    campaigns = get_open_campaigns()

    await query.edit_message_text(
        """
✅ قوانین پذیرفته شد.

حالا مسابقه موردنظر را انتخاب کن:
""",
        reply_markup=campaign_keyboard(campaigns),
    )


# ============================================================
# MY CHANCES
# ============================================================

async def show_my_chances(update, context):
    query = update.callback_query
    await query.answer()

    user = get_user(query.from_user.id)

    if not user:
        user = ensure_user(query.from_user)

    referrals = db_execute(
        """
        SELECT COUNT(*) AS total
        FROM referrals
        WHERE referrer_id = ?
          AND successful = 1
        """,
        (query.from_user.id,),
        fetchone=True,
        commit=False,
    )

    participations = db_execute(
        """
        SELECT COUNT(*) AS total
        FROM participations
        WHERE user_id = ?
        """,
        (query.from_user.id,),
        fetchone=True,
        commit=False,
    )

    await query.edit_message_text(
        f"""
<b>🎯 شانس‌های من</b>

شانس کل حساب:
<b>{user['chances']}</b>

👥 معرفی موفق:
<b>{referrals['total']}</b>

🏆 تعداد مسابقات ثبت‌نام‌شده:
<b>{participations['total']}</b>

هر معرفی موفق یک شانس اضافه ایجاد می‌کند.
""",
        parse_mode=ParseMode.HTML,
        reply_markup=back_menu(),
    )


# ============================================================
# REFERRAL
# ============================================================

async def show_referral(update, context):
    query = update.callback_query
    await query.answer()

    link = referral_link(query.from_user.id)

    referrals = db_execute(
        """
        SELECT COUNT(*) AS total
        FROM referrals
        WHERE referrer_id = ?
          AND successful = 1
        """,
        (query.from_user.id,),
        fetchone=True,
        commit=False,
    )

    await query.edit_message_text(
        f"""
<b>👥 دعوت دوستان</b>

با لینک اختصاصی خودت دوستانت را دعوت کن.

هر فردی که از لینک تو وارد شود و ثبت‌نام موفق انجام دهد:

🎯 <b>۱ شانس اضافه برای تو</b>

تعداد دعوت‌های موفق:
<b>{referrals['total']}</b>

<b>لینک اختصاصی شما:</b>
<code>{link}</code>

لینک را برای دوستانت بفرست.
""",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "📤 اشتراک لینک",
                    url=(
                        "https://t.me/share/url?"
                        f"url={quote(link)}"
                        "&text="
                        f"{quote('برای شرکت در محفل خوش‌شانس‌ها وارد شو و ثبت‌نام کن 🎉')}"
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 بازگشت",
                    callback_data="home",
                )
            ],
        ]),
    )


# ============================================================
# ELIGIBILITY
# ============================================================

async def show_eligibility(update, context):
    query = update.callback_query
    await query.answer()

    user = ensure_user(query.from_user)

    tg_member = await refresh_user_membership(
        context.bot,
        query.from_user.id,
    )

    rules = has_accepted_rules(query.from_user.id)

    await query.edit_message_text(
        f"""
<b>✅ شرایط فعلی شما</b>

📜 قوانین:
{'✅ پذیرفته شده' if rules else '❌ هنوز پذیرفته نشده'}

📢 عضویت تلگرام:
{'✅ تأیید شد' if tg_member else '❌ تأیید نشد'}

📸 اینستاگرام:
{'✅ اعلام شده' if user['instagram_follow'] else '⏳ هنوز ثبت نشده'}

▶️ یوتیوب:
{'✅ اعلام شده' if user['youtube_follow'] else '⏳ هنوز ثبت نشده'}

🏆 وضعیت شبکه:
{'🟢 فعال' if network_activated() else '🟡 هنوز فعال نشده'}

⚠️ تأیید خودکار اینستاگرام و یوتیوب فعلاً فعال نیست.
""",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "📸 باز کردن اینستاگرام",
                    url=INSTAGRAM_URL,
                ),
                InlineKeyboardButton(
                    "▶️ باز کردن یوتیوب",
                    url=YOUTUBE_URL,
                ),
            ],
            [
                InlineKeyboardButton(
                    "📢 عضویت کانال",
                    url=f"https://t.me/{TELEGRAM_CHANNEL.lstrip('@')}",
                )
            ],
            [
                InlineKeyboardButton(
                    "🔄 بررسی عضویت تلگرام",
                    callback_data="check_tg",
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 بازگشت",
                    callback_data="home",
                )
            ],
        ]),
    )


async def check_tg(update, context):
    query = update.callback_query
    await query.answer()

    member = await refresh_user_membership(
        context.bot,
        query.from_user.id,
    )

    if member:
        text = """
✅ عضویت شما در کانال تلگرام تأیید شد.
"""
    else:
        text = """
❌ هنوز عضویت شما در کانال تلگرام تأیید نشده است.

ابتدا عضو کانال شوید و دوباره بررسی کنید.
"""

    await query.edit_message_text(
        text,
        reply_markup=back_menu(),
    )


# ============================================================
# SUPPORT
# ============================================================

async def show_support(update, context):
    query = update.callback_query
    await query.answer()

    support_text = """
<b>🎧 پشتیبانی محفل خوش‌شانس‌ها</b>

اگر سؤال، مشکل ثبت‌نام، مشکل شانس، مشکل مسابقه یا موضوع دیگری داری، از گزینه زیر پیام خودت را برای پشتیبانی ارسال کن.

پشتیبانی واقعی است و پیام شما مستقیماً برای مدیریت ارسال می‌شود.
"""

    if SUPPORT_USERNAME:
        support_text += (
            f"\n\n🆔 پشتیبانی مستقیم: @{SUPPORT_USERNAME}"
        )

    await query.edit_message_text(
        support_text,
        parse_mode=ParseMode.HTML,
        reply_markup=support_menu(),
    )


async def start_support_ticket(update, context):
    query = update.callback_query
    await query.answer()

    context.user_data["support_waiting"] = True

    await query.edit_message_text(
        """
✉️ <b>پیام خود را بنویس</b>

هر مشکلی داری همینجا بنویس.
پیام مستقیماً برای پشتیبانی ارسال می‌شود.

برای لغو، /cancel را بزن.
""",
        parse_mode=ParseMode.HTML,
    )


async def cancel_command(update, context):
    context.user_data.pop("support_waiting", None)
    context.user_data.pop("admin_reply_to", None)

    await update.message.reply_text(
        "لغو شد.",
        reply_markup=main_menu(),
    )


async def send_support_ticket(update, context):
    if not update.message:
        return

    if not context.user_data.get("support_waiting"):
        return

    if is_admin(update.effective_user.id):
        return

    user = update.effective_user
    ensure_user(user)

    message_text = update.message.text or ""

    if not message_text.strip():
        await update.message.reply_text(
            "لطفاً پیام پشتیبانی را به صورت متن ارسال کن."
        )
        return

    ticket_id = db_execute(
        """
        INSERT INTO support_tickets(
            user_telegram_id,
            message,
            status,
            created_at
        )
        VALUES (?, ?, 'open', ?)
        """,
        (
            user.id,
            message_text,
            now_iso(),
        ),
    )

    context.user_data["support_waiting"] = False

    sent = 0

    for admin_id in ADMIN_IDS:
        try:
            admin_text = (
                "🎧 <b>پیام جدید پشتیبانی</b>\n\n"
                f"🎫 تیکت: <code>#{ticket_id}</code>\n"
                f"👤 نام: {user.first_name or '-'}\n"
                f"🆔 Telegram ID: <code>{user.id}</code>\n"
                f"👤 Username: @{user.username if user.username else '-'}\n\n"
                f"💬 پیام:\n{message_text}"
            )

            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "↩️ پاسخ به کاربر",
                        callback_data=f"reply_ticket:{ticket_id}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "✅ بستن تیکت",
                        callback_data=f"close_ticket:{ticket_id}",
                    )
                ],
            ])

            await context.bot.send_message(
                chat_id=admin_id,
                text=admin_text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )

            sent += 1

        except Exception as exc:
            logger.exception(
                "Could not send support ticket to admin: %s",
                exc,
            )

    if sent:
        await update.message.reply_text(
            f"""
✅ پیام شما ثبت شد.

🎫 شماره تیکت:
<code>#{ticket_id}</code>

پیام برای مدیریت ارسال شد.
""",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu(),
        )
    else:
        await update.message.reply_text(
            """
⚠️ پیام ثبت شد، اما در حال حاضر پشتیبانی آنلاین در دسترس نیست.
مدیریت پس از اتصال بررسی خواهد کرد.
""",
            reply_markup=main_menu(),
        )


async def admin_reply_button(update, context):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        return

    try:
        ticket_id = int(
            query.data.split(":", 1)[1]
        )
    except Exception:
        await query.edit_message_text(
            "❌ شماره تیکت نامعتبر است."
        )
        return

    ticket = db_execute(
        """
        SELECT *
        FROM support_tickets
        WHERE id = ?
        """,
        (ticket_id,),
        fetchone=True,
        commit=False,
    )

    if not ticket:
        await query.edit_message_text(
            "❌ تیکت پیدا نشد."
        )
        return

    context.user_data["admin_reply_to"] = ticket_id

    await query.message.reply_text(
        f"""
↩️ <b>پاسخ به تیکت #{ticket_id}</b>

پیام خودت را ارسال کن.
پیام مستقیماً برای کاربر ارسال می‌شود.

برای لغو:
 /cancel
""",
        parse_mode=ParseMode.HTML,
    )


async def send_admin_reply(update, context):
    if not is_admin(update.effective_user.id):
        return

    ticket_id = context.user_data.get("admin_reply_to")

    if not ticket_id:
        return

    if not update.message:
        return

    text = update.message.text or ""

    if not text.strip():
        return

    ticket = db_execute(
        """
        SELECT *
        FROM support_tickets
        WHERE id = ?
        """,
        (ticket_id,),
        fetchone=True,
        commit=False,
    )

    if not ticket:
        context.user_data.pop("admin_reply_to", None)

        await update.message.reply_text(
            "❌ تیکت پیدا نشد."
        )
        return

    try:
        await context.bot.send_message(
            chat_id=ticket["user_telegram_id"],
            text=(
                "🎧 <b>پاسخ پشتیبانی محفل</b>\n\n"
                f"{text}"
            ),
            parse_mode=ParseMode.HTML,
        )

        db_execute(
            """
            UPDATE support_tickets
            SET status = 'answered',
                admin_telegram_id = ?,
                answered_at = ?
            WHERE id = ?
            """,
            (
                update.effective_user.id,
                now_iso(),
                ticket_id,
            ),
        )

        context.user_data.pop("admin_reply_to", None)

        await update.message.reply_text(
            f"✅ پاسخ تیکت #{ticket_id} برای کاربر ارسال شد."
        )

    except Exception as exc:
        logger.exception(
            "Admin reply failed: %s",
            exc,
        )

        await update.message.reply_text(
            "❌ ارسال پاسخ انجام نشد. احتمالاً کاربر ربات را مسدود کرده است."
        )


async def close_ticket(update, context):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        return

    try:
        ticket_id = int(
            query.data.split(":", 1)[1]
        )
    except Exception:
        return

    db_execute(
        """
        UPDATE support_tickets
        SET status = 'closed',
            admin_telegram_id = ?
        WHERE id = ?
        """,
        (
            query.from_user.id,
            ticket_id,
        ),
    )

    await query.edit_message_reply_markup(
        reply_markup=None,
    )

    await query.message.reply_text(
        f"✅ تیکت #{ticket_id} بسته شد."
    )


# ============================================================
# ADMIN
# ============================================================

async def admin_command(update, context):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(
            "⛔ دسترسی مجاز نیست."
        )
        return

    await update.message.reply_text(
        """
<b>🛠 پنل مدیریت محفل</b>

دستورات مهم:

/status
/users
/igfollowers 100000
/ytfollowers 100000
/tgfollowers 100000
/createcampaign عنوان | توضیحات | جایزه
/campaigns
/draw ID
/postnow
/tickets
/broadcast متن
/activate
/deactivate
/myid

برای پاسخ به پشتیبانی، روی دکمه «پاسخ به کاربر» بزن.
""",
        parse_mode=ParseMode.HTML,
    )


async def myid_command(update, context):
    await update.message.reply_text(
        f"Telegram ID شما:\n<code>{update.effective_user.id}</code>",
        parse_mode=ParseMode.HTML,
    )


async def status_command(update, context):
    if not is_admin(update.effective_user.id):
        return

    counts = get_counts()
    users = db_execute(
        "SELECT COUNT(*) AS total FROM users",
        fetchone=True,
        commit=False,
    )

    registered = db_execute(
        """
        SELECT COUNT(*) AS total
        FROM users
        WHERE registered = 1
        """,
        fetchone=True,
        commit=False,
    )

    tickets = db_execute(
        """
        SELECT COUNT(*) AS total
        FROM support_tickets
        WHERE status = 'open'
        """,
        fetchone=True,
        commit=False,
    )

    await update.message.reply_text(
        f"""
<b>📊 وضعیت سیستم</b>

👤 کل کاربران:
<b>{users['total']:,}</b>

🎟 ثبت‌نام‌شده:
<b>{registered['total']:,}</b>

🎧 تیکت باز:
<b>{tickets['total']:,}</b>

📸 Instagram:
<b>{counts['instagram']:,}</b>

▶️ YouTube:
<b>{counts['youtube']:,}</b>

📢 Telegram:
<b>{counts['telegram']:,}</b>

🎯 هدف:
<b>{ACTIVATION_TARGET:,}</b>

🌐 فعال‌سازی:
{'🟢 فعال' if network_activated() else '🟡 غیرفعال'}

🆓 ثبت‌نام رایگان:
🟢 فعال

💳 ثبت‌نام پولی:
🔴 خاموش
""",
        parse_mode=ParseMode.HTML,
    )


async def users_command(update, context):
    if not is_admin(update.effective_user.id):
        return

    row = db_execute(
        "SELECT COUNT(*) AS total FROM users",
        fetchone=True,
        commit=False,
    )

    registered = db_execute(
        """
        SELECT COUNT(*) AS total
        FROM users
        WHERE registered = 1
        """,
        fetchone=True,
        commit=False,
    )

    await update.message.reply_text(
        f"""
👥 کاربران

کل کاربران: {row['total']:,}
ثبت‌نام‌شده: {registered['total']:,}
""",
    )


async def set_followers(update, context, key, label):
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text(
            f"مثال:\n/{label.lower()} 100000"
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
            "❌ عدد معتبر وارد کن."
        )
        return

    set_setting(key, value)

    active = update_activation_status()

    await update.message.reply_text(
        f"""
✅ شمارش {label} روی {value:,} ثبت شد.

وضعیت فعال‌سازی:
{'🟢 فعال' if active else '🟡 هنوز فعال نشده'}
"""
    )


async def igfollowers_command(update, context):
    await set_followers(
        update,
        context,
        "instagram_followers",
        "Instagram",
    )


async def ytfollowers_command(update, context):
    if not is_admin(update.effective_user.id):
        return

    # اگر عدد دستی داده شد، دستی ثبت کن
    if context.args:
        await set_followers(
            update,
            context,
            "youtube_followers",
            "YouTube",
        )
        return

    if not YOUTUBE_API_KEY or not YOUTUBE_CHANNEL_ID:
        await update.message.reply_text(
            """
⚠️ برای شمارش خودکار یوتیوب، این دو Environment Variable را در Render قرار بده:

YOUTUBE_API_KEY
YOUTUBE_CHANNEL_ID

یا عدد را دستی بده:

/ytfollowers 100000
"""
        )
        return

    try:
        value = await asyncio.to_thread(
            fetch_youtube_subscribers
        )

        set_setting(
            "youtube_followers",
            value,
        )

        active = update_activation_status()

        await update.message.reply_text(
            f"""
✅ تعداد مشترکین یوتیوب از API خوانده شد:

<b>{value:,}</b>

وضعیت فعال‌سازی:
{'🟢 فعال' if active else '🟡 هنوز فعال نشده'}
""",
            parse_mode=ParseMode.HTML,
        )

    except Exception as exc:
        logger.exception(
            "YouTube update failed: %s",
            exc,
        )

        await update.message.reply_text(
            f"❌ دریافت تعداد یوتیوب انجام نشد:\n{exc}"
        )


async def tgfollowers_command(update, context):
    if not is_admin(update.effective_user.id):
        return

    if context.args:
        await set_followers(
            update,
            context,
            "telegram_followers",
            "Telegram",
        )
        return

    try:
        chat = await context.bot.get_chat(
            TELEGRAM_CHANNEL
        )

        count = await context.bot.get_chat_member_count(
            chat.id
        )

        set_setting(
            "telegram_followers",
            count,
        )

        active = update_activation_status()

        await update.message.reply_text(
            f"""
📢 تعداد اعضای تلگرام:

<b>{count:,}</b>

وضعیت فعال‌سازی:
{'🟢 فعال' if active else '🟡 هنوز فعال نشده'}
""",
            parse_mode=ParseMode.HTML,
        )

    except Exception as exc:
        logger.exception(
            "Telegram count failed: %s",
            exc,
        )

        await update.message.reply_text(
            f"""
❌ شمارش تلگرام انجام نشد.

مطمئن شو ربات در کانال دسترسی لازم را دارد.

خطا:
{exc}
"""
        )


async def activate_command(update, context):
    if not is_admin(update.effective_user.id):
        return

    set_setting(
        "network_activated",
        "1",
    )

    await update.message.reply_text(
        """
🟢 فعال‌سازی شبکه به صورت دستی روشن شد.

توجه:
این گزینه فقط برای مدیریت و تست است.
"""
    )


async def deactivate_command(update, context):
    if not is_admin(update.effective_user.id):
        return

    set_setting(
        "network_activated",
        "0",
    )

    await update.message.reply_text(
        "🟡 فعال‌سازی شبکه خاموش شد."
    )


# ============================================================
# CAMPAIGN ADMIN
# ============================================================

async def create_campaign_command(update, context):
    if not is_admin(update.effective_user.id):
        return

    raw = update.message.text[
        len("/createcampaign"):
    ].strip()

    parts = [
        x.strip()
        for x in raw.split("|")
    ]

    if len(parts) < 3:
        await update.message.reply_text(
            """
فرمت صحیح:

/createcampaign عنوان | توضیحات | جایزه
"""
        )
        return

    title, description, prize = parts[:3]

    campaign_id = db_execute(
        """
        INSERT INTO campaigns(
            title,
            description,
            prize,
            status,
            draw_allowed,
            created_at
        )
        VALUES (?, ?, ?, 'open', ?, ?)
        """,
        (
            title,
            description,
            prize,
            1 if network_activated() else 0,
            now_iso(),
        ),
    )

    await update.message.reply_text(
        f"""
✅ مسابقه ساخته شد.

شناسه:
<b>{campaign_id}</b>

عنوان:
<b>{title}</b>

وضعیت قرعه:
{'🟢 مجاز' if network_activated() else '🟡 تا فعال شدن شبکه بسته'}
""",
        parse_mode=ParseMode.HTML,
    )


async def campaigns_command(update, context):
    if not is_admin(update.effective_user.id):
        return

    campaigns = db_execute(
        """
        SELECT *
        FROM campaigns
        ORDER BY id DESC
        """,
        fetchall=True,
        commit=False,
    )

    if not campaigns:
        await update.message.reply_text(
            "هیچ مسابقه‌ای وجود ندارد."
        )
        return

    lines = ["<b>🏆 لیست مسابقات</b>\n"]

    for c in campaigns:
        participants = db_execute(
            """
            SELECT COUNT(*) AS total
            FROM participations
            WHERE campaign_id = ?
            """,
            (c["id"],),
            fetchone=True,
            commit=False,
        )

        lines.append(
            f"ID: <b>{c['id']}</b>\n"
            f"عنوان: {c['title']}\n"
            f"وضعیت: {c['status']}\n"
            f"شرکت‌کنندگان: {participants['total']}\n"
            f"قرعه: {'مجاز' if c['draw_allowed'] else 'بسته'}\n"
        )

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# DRAW
# ============================================================

async def draw_command(update, context):
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text(
            "مثال:\n/draw 1"
        )
        return

    try:
        campaign_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "❌ شناسه مسابقه نامعتبر است."
        )
        return

    if not network_activated():
        await update.message.reply_text(
            """
🛑 قرعه‌کشی هنوز مجاز نیست.

شبکه باید ابتدا فعال شود.
"""
        )
        return

    campaign = db_execute(
        """
        SELECT *
        FROM campaigns
        WHERE id = ?
        """,
        (campaign_id,),
        fetchone=True,
        commit=False,
    )

    if not campaign:
        await update.message.reply_text(
            "❌ مسابقه پیدا نشد."
        )
        return

    if campaign["status"] != "open":
        await update.message.reply_text(
            "❌ این مسابقه دیگر باز نیست."
        )
        return

    participants = db_execute(
        """
        SELECT
            p.user_id,
            p.chances,
            u.telegram_id,
            u.first_name,
            u.username
        FROM participations p
        JOIN users u
            ON u.telegram_id = p.user_id
        WHERE p.campaign_id = ?
          AND u.registered = 1
        """,
        (campaign_id,),
        fetchall=True,
        commit=False,
    )

    if not participants:
        await update.message.reply_text(
            "❌ هیچ شرکت‌کننده‌ای وجود ندارد."
        )
        return

    eligible = []

    for p in participants:
        member = await check_telegram_membership(
            context.bot,
            p["telegram_id"],
        )

        if member:
            chances = max(
                1,
                int(p["chances"]),
            )

            for _ in range(chances):
                eligible.append(p)

    if not eligible:
        await update.message.reply_text(
            "❌ هیچ شرکت‌کننده واجد شرایطی پیدا نشد."
        )
        return

    winner = random.choice(eligible)

    db_execute(
        """
        INSERT INTO winners(
            campaign_id,
            user_id,
            telegram_id,
            chances_at_draw,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            campaign_id,
            winner["user_id"],
            winner["telegram_id"],
            winner["chances"],
            now_iso(),
        ),
    )

    db_execute(
        """
        UPDATE campaigns
        SET status = 'drawn'
        WHERE id = ?
        """,
        (campaign_id,),
    )

    winner_name = (
        winner["first_name"]
        or winner["username"]
        or str(winner["telegram_id"])
    )

    await update.message.reply_text(
        f"""
🎉 <b>قرعه‌کشی انجام شد</b>

🏆 مسابقه:
<b>{campaign['title']}</b>

🎁 جایزه:
<b>{campaign['prize']}</b>

👤 برنده:
<b>{winner_name}</b>

🆔 Telegram ID:
<code>{winner['telegram_id']}</code>

🎯 شانس هنگام قرعه:
<b>{winner['chances']}</b>
""",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# AUTO POSTS
# ============================================================

PROMO_MESSAGES = [
    """
🎉 <b>محفل خوش‌شانس‌ها شروع شده!</b>

ثبت‌نام رایگان از همین حالا فعال است.

🎟 ثبت‌نام کن
👥 دوستانت را دعوت کن
🎯 شانس بیشتری بگیر
📸 اینستاگرام را دنبال کن
▶️ یوتیوب را دنبال کن
📢 عضو کانال تلگرام باش

⏳ قرعه‌کشی پس از فعال شدن شبکه انجام می‌شود.

🔥 هیچ هزینه‌ای برای ثبت‌نام رایگان دریافت نمی‌شود.
""",
    """
🎯 <b>یک شانس بیشتر می‌خواهی؟</b>

دوستانت را با لینک اختصاصی خودت به محفل خوش‌شانس‌ها دعوت کن.

هر معرفی موفق:
➕ ۱ شانس

ثبت‌نام رایگان فعال است و ثبت‌نام مسابقه مستقل از فعال شدن شبکه انجام می‌شود.

📸 Instagram
▶️ YouTube
📢 Telegram
""",
    """
🏆 <b>محفل خوش‌شانس‌ها</b>

هدف شبکه:
<b>100,000</b>

وقتی شبکه طبق قوانین به هدف برسد، شرایط قرعه‌کشی فعال می‌شود.

اما برای ثبت‌نام لازم نیست منتظر بمانی.

🎟 همین حالا ثبت‌نام کن
👥 دوستانت را دعوت کن
🎯 شانس جمع کن
""",
]


async def post_promo(bot):
    if not AUTO_POST_ENABLED:
        return False

    try:
        index = random.randint(
            0,
            len(PROMO_MESSAGES) - 1,
        )

        await bot.send_message(
            chat_id=TELEGRAM_CHANNEL,
            text=PROMO_MESSAGES[index],
            parse_mode=ParseMode.HTML,
        )

        set_setting(
            "last_auto_post",
            now_iso(),
        )

        return True

    except Exception as exc:
        logger.exception(
            "Auto post failed: %s",
            exc,
        )
        return False


async def postnow_command(update, context):
    if not is_admin(update.effective_user.id):
        return

    ok = await post_promo(
        context.bot
    )

    await update.message.reply_text(
        "✅ پیام ارسال شد."
        if ok
        else "❌ ارسال پیام انجام نشد."
    )


async def auto_post_job(context):
    await post_promo(context.bot)


# ============================================================
# YOUTUBE
# ============================================================

def fetch_youtube_subscribers():
    url = (
        "https://www.googleapis.com/youtube/v3/channels"
        "?part=statistics"
        f"&id={YOUTUBE_CHANNEL_ID}"
        f"&key={YOUTUBE_API_KEY}"
    )

    response = requests.get(
        url,
        timeout=20,
    )

    response.raise_for_status()

    data = response.json()

    items = data.get("items", [])

    if not items:
        raise RuntimeError(
            "YouTube channel not found."
        )

    statistics = items[0].get(
        "statistics",
        {},
    )

    return int(
        statistics.get(
            "subscriberCount",
            0,
        )
    )


async def youtube_background_update(context):
    if not YOUTUBE_API_KEY:
        return

    if not YOUTUBE_CHANNEL_ID:
        return

    try:
        value = await asyncio.to_thread(
            fetch_youtube_subscribers
        )

        set_setting(
            "youtube_followers",
            value,
        )

        active = update_activation_status()

        logger.info(
            "YouTube followers updated: %s | active=%s",
            value,
            active,
        )

    except Exception as exc:
        logger.warning(
            "YouTube background update failed: %s",
            exc,
        )


# ============================================================
# START
# ============================================================

async def start_command(update, context):
    user = update.effective_user

    ensure_user(user)

    # referral
    if context.args:
        arg = context.args[0]

        if arg.startswith("ref_"):
            try:
                referrer_id = int(
                    arg.split("_", 1)[1]
                )

                if process_referral(
                    user.id,
                    referrer_id,
                ):
                    try:
                        await context.bot.send_message(
                            chat_id=referrer_id,
                            text=(
                                "🎉 یک معرفی موفق داشتی!\n\n"
                                "🎯 +۱ شانس به حساب تو اضافه شد."
                            ),
                        )
                    except Exception:
                        pass

            except Exception:
                pass

    user = get_user(user.id)

    await update.message.reply_text(
        home_text(user),
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(),
    )


# ============================================================
# REGISTRATION MENU
# ============================================================

async def registration_page(update, context):
    query = update.callback_query
    await query.answer()

    user = ensure_user(query.from_user)

    await query.edit_message_text(
        f"""
<b>🎟 ثبت‌نام مسابقه</b>

🆓 ثبت‌نام رایگان:
🟢 فعال

💳 ثبت‌نام پولی:
🔴 فعلاً خاموش

ثبت‌نام مسابقه مستقل از فعال شدن شبکه است.

یعنی حتی اگر شبکه هنوز به {ACTIVATION_TARGET:,} نرسیده باشد، می‌توانی ثبت‌نام کنی، شانس بگیری و دوستانت را دعوت کنی.
""",
        parse_mode=ParseMode.HTML,
        reply_markup=registration_menu(),
    )


async def paid_disabled(update, context):
    query = update.callback_query
    await query.answer(
        "ثبت‌نام پولی فعلاً فعال نشده است.",
        show_alert=True,
    )


# ============================================================
# CALLBACK ROUTER
# ============================================================

async def callback_router(update, context):
    query = update.callback_query

    if query.data == "home":
        await query.answer()

        user = ensure_user(
            query.from_user
        )

        await query.edit_message_text(
            home_text(user),
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu(),
        )

    elif query.data == "register":
        await registration_page(
            update,
            context,
        )

    elif query.data == "register_free":
        await register_free_user(
            update,
            context,
        )

    elif query.data == "paid_disabled":
        await paid_disabled(
            update,
            context,
        )

    elif query.data == "campaigns":
        await show_campaigns(
            update,
            context,
        )

    elif query.data.startswith("join:"):
        await join_campaign(
            update,
            context,
        )

    elif query.data == "rules":
        await show_rules(
            update,
            context,
        )

    elif query.data == "accept_rules":
        await accept_rules(
            update,
            context,
        )

    elif query.data == "accept_rules_register":
        await accept_rules_register(
            update,
            context,
        )

    elif query.data.startswith("accept_rules_join:"):
        await accept_rules_join(
            update,
            context,
        )

    elif query.data == "my_chances":
        await show_my_chances(
            update,
            context,
        )

    elif query.data == "referral":
        await show_referral(
            update,
            context,
        )

    elif query.data == "activation":
        await query.answer()

        await query.edit_message_text(
            activation_text(),
            parse_mode=ParseMode.HTML,
            reply_markup=back_menu(),
        )

    elif query.data == "eligibility":
        await show_eligibility(
            update,
            context,
        )

    elif query.data == "check_tg":
        await check_tg(
            update,
            context,
        )

    elif query.data == "support":
        await show_support(
            update,
            context,
        )

    elif query.data == "support_new":
        await start_support_ticket(
            update,
            context,
        )

    elif query.data.startswith("reply_ticket:"):
        await admin_reply_button(
            update,
            context,
        )

    elif query.data.startswith("close_ticket:"):
        await close_ticket(
            update,
            context,
        )


# ============================================================
# TICKETS ADMIN
# ============================================================

async def tickets_command(update, context):
    if not is_admin(update.effective_user.id):
        return

    tickets = db_execute(
        """
        SELECT *
        FROM support_tickets
        WHERE status = 'open'
        ORDER BY id DESC
        LIMIT 20
        """,
        fetchall=True,
        commit=False,
    )

    if not tickets:
        await update.message.reply_text(
            "🎧 هیچ تیکت بازی وجود ندارد."
        )
        return

    for ticket in tickets:
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "↩️ پاسخ",
                    callback_data=f"reply_ticket:{ticket['id']}",
                ),
                InlineKeyboardButton(
                    "✅ بستن",
                    callback_data=f"close_ticket:{ticket['id']}",
                ),
            ]
        ])

        await update.message.reply_text(
            f"""
🎫 <b>تیکت #{ticket['id']}</b>

👤 User ID:
<code>{ticket['user_telegram_id']}</code>

💬 {ticket['message']}
""",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )


# ============================================================
# BROADCAST
# ============================================================

async def broadcast_command(update, context):
    if not is_admin(update.effective_user.id):
        return

    text = update.message.text[
        len("/broadcast"):
    ].strip()

    if not text:
        await update.message.reply_text(
            "مثال:\n/broadcast سلام به همه کاربران"
        )
        return

    users = db_execute(
        """
        SELECT telegram_id
        FROM users
        """,
        fetchall=True,
        commit=False,
    )

    success = 0
    failed = 0

    for user in users:
        try:
            await context.bot.send_message(
                chat_id=user["telegram_id"],
                text=text,
            )

            success += 1

            await asyncio.sleep(0.05)

        except Exception:
            failed += 1

    await update.message.reply_text(
        f"""
📢 ارسال همگانی تمام شد.

✅ موفق: {success}
❌ ناموفق: {failed}
"""
    )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(update, context):
    logger.exception(
        "Unhandled exception:",
        exc_info=context.error,
    )


# ============================================================
# HEALTH SERVER FOR RENDER
# ============================================================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path in ("/", "/health", "/healthz"):
            body = b"MAHFELSHANS BOT OK"

            self.send_response(200)
            self.send_header(
                "Content-Type",
                "text/plain; charset=utf-8",
            )
            self.send_header(
                "Content-Length",
                str(len(body)),
            )
            self.end_headers()
            self.wfile.write(body)

            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        return


def start_health_server():
    try:
        server = ThreadingHTTPServer(
            ("0.0.0.0", PORT),
            HealthHandler,
        )

        thread = threading.Thread(
            target=server.serve_forever,
            daemon=True,
        )

        thread.start()

        logger.info(
            "Health server started on port %s",
            PORT,
        )

    except Exception as exc:
        logger.exception(
            "Health server failed: %s",
            exc,
        )


# ============================================================
# POST INIT
# ============================================================

async def post_init(application):
    logger.info(
        "MAHFELSHANS BOT started."
    )

    try:
        await application.bot.set_my_commands([
            ("start", "شروع"),
            ("myid", "نمایش شناسه"),
            ("admin", "پنل مدیریت"),
            ("status", "وضعیت سیستم"),
        ])
    except Exception as exc:
        logger.warning(
            "Could not set bot commands: %s",
            exc,
        )

    if application.job_queue:

        if AUTO_POST_ENABLED:
            application.job_queue.run_repeating(
                auto_post_job,
                interval=AUTO_POST_HOURS * 3600,
                first=30,
                name="auto_promo",
            )

        if YOUTUBE_API_KEY and YOUTUBE_CHANNEL_ID:
            application.job_queue.run_repeating(
                youtube_background_update,
                interval=3600,
                first=60,
                name="youtube_update",
            )


# ============================================================
# BUILD APPLICATION
# ============================================================

def build_application():

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN is missing. Add BOT_TOKEN in Render Environment."
        )

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Commands
    application.add_handler(
        CommandHandler(
            "start",
            start_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "cancel",
            cancel_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "myid",
            myid_command,
        )
    )

    # Admin commands
    application.add_handler(
        CommandHandler(
            "admin",
            admin_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "status",
            status_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "users",
            users_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "igfollowers",
            igfollowers_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "ytfollowers",
            ytfollowers_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "tgfollowers",
            tgfollowers_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "activate",
            activate_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "deactivate",
            deactivate_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "createcampaign",
            create_campaign_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "campaigns",
            campaigns_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "draw",
            draw_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "postnow",
            postnow_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "tickets",
            tickets_command,
        )
    )

    application.add_handler(
        CommandHandler(
            "broadcast",
            broadcast_command,
        )
    )

    # Callback buttons
    application.add_handler(
        CallbackQueryHandler(
            callback_router,
        )
    )

    # Admin replies to support
    application.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND
            & filters.User(user_id=ADMIN_IDS),
            send_admin_reply,
        ),
        group=0,
    )

    # User support messages
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            send_support_ticket,
        ),
        group=1,
    )

    application.add_error_handler(
        error_handler
    )

    return application


# ============================================================
# MAIN
# ============================================================

def main():

    init_database()

    start_health_server()

    logger.info(
        "Starting MAHFELSHANS..."
    )

    logger.info(
        "Admins: %s",
        ADMIN_IDS,
    )

    logger.info(
        "Channel: %s",
        TELEGRAM_CHANNEL,
    )

    logger.info(
        "Activation target: %s",
        ACTIVATION_TARGET,
    )

    application = build_application()

    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )


if __name__ == "__main__":
    main()
