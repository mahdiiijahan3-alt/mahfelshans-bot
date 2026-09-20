import os
import sqlite3
import logging
import random
import html
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import quote

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

# =========================================================
# CONFIG
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

BOT_USERNAME = os.getenv(
    "BOT_USERNAME",
    "MahfelShansBot"
).strip().lstrip("@")

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
    ""
).strip().lstrip("@")

DATABASE = os.getenv(
    "DATABASE",
    "mahfelshans.db"
).strip()

# هم ADMIN_ID و هم ADMIN_IDS را قبول می‌کنیم
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "").strip()

if not ADMIN_IDS_RAW:
    ADMIN_IDS_RAW = os.getenv("ADMIN_ID", "").strip()

ADMIN_IDS = set()

for item in ADMIN_IDS_RAW.split(","):
    item = item.strip()
    if item:
        try:
            ADMIN_IDS.add(int(item))
        except ValueError:
            pass

ACTIVATION_TARGET = int(
    os.getenv("ACTIVATION_TARGET", "100000")
)

PORT = int(
    os.getenv("PORT", "10000")
)

REQUIRE_TELEGRAM_MEMBERSHIP = (
    os.getenv("REQUIRE_TELEGRAM_MEMBERSHIP", "true").lower()
    == "true"
)

AUTO_POSTS_ENABLED = (
    os.getenv("AUTO_POSTS_ENABLED", "true").lower()
    == "true"
)

AUTO_POST_INTERVAL = int(
    os.getenv("AUTO_POST_INTERVAL", "7200")
)

FREE_REGISTRATION_ENABLED = True
PAID_REGISTRATION_ENABLED = False

YOUTUBE_API_KEY = os.getenv(
    "YOUTUBE_API_KEY",
    ""
).strip()

YOUTUBE_CHANNEL_ID = os.getenv(
    "YOUTUBE_CHANNEL_ID",
    ""
).strip()


# =========================================================
# BASIC HELPERS
# =========================================================

def now_iso():
    return datetime.now(timezone.utc).isoformat()


def db():
    conn = sqlite3.connect(
        DATABASE,
        timeout=30,
        check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    return conn


def is_admin(user_id):
    return user_id in ADMIN_IDS


# =========================================================
# DATABASE
# =========================================================

def init_database():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            username TEXT,
            first_name TEXT,
            chances INTEGER DEFAULT 1,
            registered INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER NOT NULL,
            referred_id INTEGER NOT NULL,
            rewarded INTEGER DEFAULT 0,
            created_at TEXT,
            UNIQUE(referrer_id, referred_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            prize TEXT,
            active INTEGER DEFAULT 1,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS participations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            chances INTEGER DEFAULT 1,
            created_at TEXT,
            UNIQUE(campaign_id, user_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS winners (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS rule_acceptances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            rules_version TEXT NOT NULL,
            accepted_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            status TEXT DEFAULT 'open',
            admin_reply TEXT,
            created_at TEXT,
            replied_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    defaults = {
        "rules_version": "1.0",
        "instagram_followers": "0",
        "youtube_subscribers": "0",
        "telegram_members": "0",
        "network_activated": "0",
    }

    for key, value in defaults.items():
        cur.execute(
            """
            INSERT OR IGNORE INTO settings(key, value)
            VALUES (?, ?)
            """,
            (key, value)
        )

    cur.execute(
        "SELECT COUNT(*) AS c FROM campaigns"
    )

    if cur.fetchone()["c"] == 0:
        cur.execute(
            """
            INSERT INTO campaigns
            (title, description, prize, active, created_at)
            VALUES (?, ?, ?, 1, ?)
            """,
            (
                "مسابقه اصلی محفل خوش‌شانس‌ها",
                "ثبت‌نام رایگان مسابقه",
                "جایزه بزرگ محفل خوش‌شانس‌ها",
                now_iso(),
            )
        )

    conn.commit()
    conn.close()


# =========================================================
# SETTINGS
# =========================================================

def get_setting(key, default=None):
    conn = db()
    cur = conn.cursor()

    cur.execute(
        "SELECT value FROM settings WHERE key = ?",
        (key,)
    )

    row = cur.fetchone()
    conn.close()

    if row is None:
        return default

    return row["value"]


def set_setting(key, value):
    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO settings(key, value)
        VALUES (?, ?)
        ON CONFLICT(key)
        DO UPDATE SET value = excluded.value
        """,
        (key, str(value))
    )

    conn.commit()
    conn.close()


def rules_version():
    return get_setting(
        "rules_version",
        "1.0"
    )


# =========================================================
# RULES
# =========================================================

def rules_text():
    return f"""
<b>📜 قوانین رسمی محفل خوش‌شانس‌ها</b>

1️⃣ ثبت‌نام در حال حاضر کاملاً رایگان است.

2️⃣ ثبت‌نام پولی فعلاً غیرفعال است و هیچ مبلغی از کاربران دریافت نمی‌شود.

3️⃣ <b>ثبت‌نام مسابقه و فعال‌سازی شبکه دو موضوع کاملاً جدا هستند.</b>

4️⃣ شما می‌توانید در مسابقه ثبت‌نام کنید حتی اگر شبکه هنوز به هدف نهایی نرسیده باشد.

5️⃣ هر کاربر پس از ثبت‌نام، شانس پایه دریافت می‌کند.

6️⃣ معرفی موفق کاربران جدید می‌تواند برای معرف شانس اضافه ایجاد کند.

7️⃣ معرفی زمانی موفق محسوب می‌شود که کاربر جدید واقعاً وارد ربات شده و ثبت‌نام مسابقه را کامل کند.

8️⃣ برای دریافت جایزه، رعایت شرایط اعلام‌شده مسابقه و عضویت در کانال تلگرام الزامی است.

9️⃣ دنبال کردن اینستاگرام و یوتیوب جزو شرایط اعلام‌شده محفل است.

🔟 قرعه‌کشی فقط پس از فعال شدن شبکه انجام می‌شود.

1️⃣1️⃣ فعال شدن شبکه زمانی است که اعداد اعلام‌شده توسط مدیریت به هدف تعیین‌شده برسند.

1️⃣2️⃣ هیچ کاربری صرفاً با ثبت‌نام یا معرفی، برنده قطعی نیست.

1️⃣3️⃣ ثبت‌نام تکراری، اطلاعات جعلی، تقلب یا سوءاستفاده از سیستم معرفی می‌تواند باعث حذف کاربر شود.

1️⃣4️⃣ محفل خوش‌شانس‌ها می‌تواند برای جلوگیری از تقلب، قوانین فنی و اجرایی را با اطلاع‌رسانی رسمی به‌روزرسانی کند.

<b>نسخه قوانین: {html.escape(rules_version())}</b>
"""


# =========================================================
# USER FUNCTIONS
# =========================================================

def ensure_user(tg_user):
    conn = db()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM users WHERE telegram_id = ?",
        (tg_user.id,)
    )

    row = cur.fetchone()

    if row is None:
        cur.execute(
            """
            INSERT INTO users
            (telegram_id, username, first_name, chances,
             registered, created_at, updated_at)
            VALUES (?, ?, ?, 1, 0, ?, ?)
            """,
            (
                tg_user.id,
                tg_user.username or "",
                tg_user.first_name or "",
                now_iso(),
                now_iso(),
            )
        )
    else:
        cur.execute(
            """
            UPDATE users
            SET username = ?,
                first_name = ?,
                updated_at = ?
            WHERE telegram_id = ?
            """,
            (
                tg_user.username or "",
                tg_user.first_name or "",
                now_iso(),
                tg_user.id,
            )
        )

    conn.commit()
    conn.close()


def get_user(telegram_id):
    conn = db()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM users WHERE telegram_id = ?",
        (telegram_id,)
    )

    row = cur.fetchone()
    conn.close()

    return row


def register_user(telegram_id):
    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE users
        SET registered = 1,
            updated_at = ?
        WHERE telegram_id = ?
        """,
        (now_iso(), telegram_id)
    )

    conn.commit()
    conn.close()


def add_chance(telegram_id, amount=1):
    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE users
        SET chances = chances + ?,
            updated_at = ?
        WHERE telegram_id = ?
        """,
        (amount, now_iso(), telegram_id)
    )

    conn.commit()
    conn.close()


# =========================================================
# REFERRAL
# =========================================================

def save_referral(referrer_id, referred_id):
    if referrer_id == referred_id:
        return

    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT OR IGNORE INTO referrals
        (referrer_id, referred_id, rewarded, created_at)
        VALUES (?, ?, 0, ?)
        """,
        (
            referrer_id,
            referred_id,
            now_iso()
        )
    )

    conn.commit()
    conn.close()


def reward_referral_if_needed(referred_id):
    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM referrals
        WHERE referred_id = ?
        AND rewarded = 0
        LIMIT 1
        """,
        (referred_id,)
    )

    referral = cur.fetchone()

    if referral is None:
        conn.close()
        return None

    referrer_id = referral["referrer_id"]

    cur.execute(
        """
        UPDATE users
        SET chances = chances + 1,
            updated_at = ?
        WHERE telegram_id = ?
        """,
        (now_iso(), referrer_id)
    )

    cur.execute(
        """
        UPDATE referrals
        SET rewarded = 1
        WHERE id = ?
        """,
        (referral["id"],)
    )

    conn.commit()
    conn.close()

    return referrer_id


# =========================================================
# CAMPAIGNS
# =========================================================

def get_active_campaigns():
    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM campaigns
        WHERE active = 1
        ORDER BY id DESC
        """
    )

    rows = cur.fetchall()
    conn.close()

    return rows


def get_campaign(campaign_id):
    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM campaigns
        WHERE id = ?
        """,
        (campaign_id,)
    )

    row = cur.fetchone()
    conn.close()

    return row


def is_participating(campaign_id, user_id):
    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id
        FROM participations
        WHERE campaign_id = ?
        AND user_id = ?
        """,
        (campaign_id, user_id)
    )

    row = cur.fetchone()
    conn.close()

    return row is not None


def join_campaign(campaign_id, telegram_id):
    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id
        FROM participations
        WHERE campaign_id = ?
        AND user_id = ?
        """,
        (campaign_id, telegram_id)
    )

    existing = cur.fetchone()

    if existing:
        conn.close()
        return False

    cur.execute(
        """
        SELECT chances
        FROM users
        WHERE telegram_id = ?
        """,
        (telegram_id,)
    )

    user = cur.fetchone()
    chances = user["chances"] if user else 1

    cur.execute(
        """
        INSERT INTO participations
        (campaign_id, user_id, chances, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            campaign_id,
            telegram_id,
            chances,
            now_iso()
        )
    )

    conn.commit()
    conn.close()

    return True


# =========================================================
# NETWORK
# =========================================================

def get_network_stats():
    return {
        "instagram": int(
            get_setting("instagram_followers", "0")
        ),
        "youtube": int(
            get_setting("youtube_subscribers", "0")
        ),
        "telegram": int(
            get_setting("telegram_members", "0")
        ),
    }


def network_is_active():
    stats = get_network_stats()

    return (
        stats["instagram"] >= ACTIVATION_TARGET
        and
        stats["youtube"] >= ACTIVATION_TARGET
        and
        stats["telegram"] >= ACTIVATION_TARGET
    )


def update_network_status():
    active = network_is_active()

    set_setting(
        "network_activated",
        "1" if active else "0"
    )

    return active


# =========================================================
# TELEGRAM MEMBERSHIP
# =========================================================

async def is_member(bot, user_id):
    if not REQUIRE_TELEGRAM_MEMBERSHIP:
        return True

    try:
        member = await bot.get_chat_member(
            chat_id=TELEGRAM_CHANNEL,
            user_id=user_id
        )

        return member.status in (
            "member",
            "administrator",
            "creator",
        )

    except Exception as exc:
        logger.warning(
            "Membership check failed: %s",
            exc
        )
        return False


# =========================================================
# KEYBOARDS
# =========================================================

def main_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🎁 ثبت‌نام مسابقه",
                callback_data="campaigns"
            )
        ],
        [
            InlineKeyboardButton(
                "🎯 فعال‌سازی شبکه",
                callback_data="activation"
            )
        ],
        [
            InlineKeyboardButton(
                "👤 پروفایل من",
                callback_data="profile"
            ),
            InlineKeyboardButton(
                "🎟️ معرفی دوستان",
                callback_data="referral"
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
        ],
    ])


def activation_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📸 اینستاگرام",
                url=INSTAGRAM_URL
            )
        ],
        [
            InlineKeyboardButton(
                "▶️ یوتیوب",
                url=YOUTUBE_URL
            )
        ],
        [
            InlineKeyboardButton(
                "📢 کانال تلگرام",
                url=f"https://t.me/{TELEGRAM_CHANNEL.lstrip('@')}"
            )
        ],
        [
            InlineKeyboardButton(
                "🔄 بررسی وضعیت",
                callback_data="activation"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 بازگشت",
                callback_data="home"
            )
        ],
    ])


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    ensure_user(user)

    # دریافت لینک معرفی
    if context.args:
        arg = context.args[0]

        if arg.startswith("ref_"):
            try:
                referrer_id = int(
                    arg.replace("ref_", "", 1)
                )

                if referrer_id != user.id:
                    save_referral(
                        referrer_id,
                        user.id
                    )

            except ValueError:
                pass

    text = f"""
<b>🎉 به محفل خوش‌شانس‌ها خوش آمدید</b>

اینجا محل مسابقات و قرعه‌کشی‌های بزرگ آینده است.

🎁 ثبت‌نام مسابقه فعلاً <b>رایگان</b> است.

📌 ثبت‌نام مسابقه از فعال‌سازی شبکه جداست.

هر زمان آماده بودید، از منوی زیر شروع کنید.
"""

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard()
    )


# =========================================================
# CAMPAIGNS MENU
# =========================================================

async def show_campaigns(query):
    campaigns = get_active_campaigns()

    if not campaigns:
        await query.edit_message_text(
            "در حال حاضر مسابقه فعالی وجود ندارد.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 بازگشت",
                        callback_data="home"
                    )
                ]
            ])
        )
        return

    buttons = []

    for campaign in campaigns:
        buttons.append([
            InlineKeyboardButton(
                f"🎁 {campaign['title']}",
                callback_data=f"campaign:{campaign['id']}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "🔙 بازگشت",
            callback_data="home"
        )
    ])

    await query.edit_message_text(
        "<b>🎁 مسابقات فعال</b>\n\n"
        "مسابقه موردنظر را انتخاب کنید:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def show_campaign(query, campaign_id):
    campaign = get_campaign(campaign_id)

    if not campaign:
        await query.answer(
            "مسابقه پیدا نشد.",
            show_alert=True
        )
        return

    text = f"""
<b>🎁 {html.escape(campaign['title'])}</b>

{html.escape(campaign['description'] or '')}

🏆 جایزه:
<b>{html.escape(campaign['prize'] or '')}</b>

💰 هزینه ثبت‌نام:
<b>رایگان</b>
"""

    buttons = [
        [
            InlineKeyboardButton(
                "📜 قوانین",
                callback_data=f"rules_join:{campaign_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 بازگشت",
                callback_data="campaigns"
            )
        ],
    ]

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# =========================================================
# RULES / REGISTRATION
# =========================================================

async def show_rules(query, campaign_id=None):
    buttons = []

    if campaign_id:
        buttons.append([
            InlineKeyboardButton(
                "✅ پذیرش قوانین و ثبت‌نام",
                callback_data=f"accept:{campaign_id}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "🔙 بازگشت",
            callback_data=(
                f"campaign:{campaign_id}"
                if campaign_id
                else "home"
            )
        )
    ])

    await query.edit_message_text(
        rules_text(),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def accept_rules_join(query, user_id, campaign_id):
    campaign = get_campaign(campaign_id)

    if not campaign:
        await query.answer(
            "مسابقه پیدا نشد.",
            show_alert=True
        )
        return

    if not FREE_REGISTRATION_ENABLED:
        await query.answer(
            "ثبت‌نام فعلاً غیرفعال است.",
            show_alert=True
        )
        return

    # بررسی عضویت تلگرام
    if REQUIRE_TELEGRAM_MEMBERSHIP:
        member = await is_member(
            query.get_bot(),
            user_id
        )

        if not member:
            await query.edit_message_text(
                "برای ثبت‌نام ابتدا باید عضو کانال تلگرام محفل شوید.\n\n"
                "پس از عضویت، دوباره روی بررسی عضویت بزنید.",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "📢 عضویت در کانال",
                            url=f"https://t.me/{TELEGRAM_CHANNEL.lstrip('@')}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "🔄 بررسی عضویت",
                            callback_data=f"accept:{campaign_id}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "🔙 بازگشت",
                            callback_data=f"campaign:{campaign_id}"
                        )
                    ]
                ])
            )
            return

    # ثبت پذیرش قوانین
    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO rule_acceptances
        (user_id, rules_version, accepted_at)
        VALUES (?, ?, ?)
        """,
        (
            user_id,
            rules_version(),
            now_iso()
        )
    )

    conn.commit()
    conn.close()

    # ثبت کاربر
    register_user(user_id)

    # ثبت شرکت در مسابقه
    joined = join_campaign(
        campaign_id,
        user_id
    )

    # فقط بعد از ثبت‌نام واقعی معرف پاداش می‌گیرد
    rewarded_referrer = reward_referral_if_needed(
        user_id
    )

    message = (
        "🎉 <b>ثبت‌نام شما با موفقیت انجام شد!</b>\n\n"
        f"🎁 مسابقه: <b>{html.escape(campaign['title'])}</b>\n"
        "🎟️ شانس پایه شما ثبت شد.\n\n"
    )

    if not joined:
        message += (
            "ℹ️ شما قبلاً در این مسابقه ثبت‌نام کرده بودید.\n"
        )

    if rewarded_referrer:
        message += (
            "🎟️ معرفی موفق شما ثبت شد و یک شانس به معرف شما اضافه شد.\n"
        )

    message += (
        "\n📌 فعال‌سازی شبکه جدا از ثبت‌نام مسابقه است."
    )

    await query.edit_message_text(
        message,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🎯 فعال‌سازی شبکه",
                    callback_data="activation"
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


# =========================================================
# PROFILE
# =========================================================

async def show_profile(query, user_id):
    user = get_user(user_id)

    if not user:
        await query.answer(
            "اطلاعات شما پیدا نشد.",
            show_alert=True
        )
        return

    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT COUNT(*) AS c
        FROM participations
        WHERE user_id = ?
        """,
        (user_id,)
    )

    participation_count = cur.fetchone()["c"]

    cur.execute(
        """
        SELECT COUNT(*) AS c
        FROM referrals
        WHERE referrer_id = ?
        AND rewarded = 1
        """,
        (user_id,)
    )

    referral_count = cur.fetchone()["c"]

    conn.close()

    status = (
        "✅ ثبت‌نام شده"
        if user["registered"]
        else "❌ هنوز ثبت‌نام نکرده"
    )

    text = f"""
<b>👤 پروفایل شما</b>

🆔 شناسه: <code>{user_id}</code>

📌 وضعیت: {status}

🎟️ شانس‌ها: <b>{user['chances']}</b>

🎁 تعداد مسابقات: <b>{participation_count}</b>

👥 معرفی موفق: <b>{referral_count}</b>
"""

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🎟️ لینک معرفی من",
                    callback_data="referral"
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


# =========================================================
# REFERRAL MENU
# =========================================================

async def show_referral(query, user_id):
    link = (
        f"https://t.me/{BOT_USERNAME}"
        f"?start=ref_{user_id}"
    )

    user = get_user(user_id)

    chances = user["chances"] if user else 1

    text = f"""
<b>🎟️ سیستم معرفی محفل خوش‌شانس‌ها</b>

لینک اختصاصی شما:

<code>{html.escape(link)}</code>

🎟️ شانس فعلی شما:
<b>{chances}</b>

هر فردی که از لینک شما وارد شود و <b>ثبت‌نام مسابقه را کامل کند</b>، یک شانس برای شما ایجاد می‌کند.
"""

    share_url = (
        "https://t.me/share/url"
        f"?url={quote(link)}"
        f"&text={quote('به محفل خوش‌شانس‌ها بپیوندید 🎉')}"
    )

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "📤 اشتراک‌گذاری لینک",
                    url=share_url
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


# =========================================================
# ACTIVATION
# =========================================================

async def show_activation(query):
    stats = get_network_stats()
    active = update_network_status()

    status = (
        "🟢 شبکه فعال شده است"
        if active
        else "🟡 شبکه هنوز فعال نشده است"
    )

    text = f"""
<b>🎯 فعال‌سازی شبکه</b>

{status}

هدف هر بخش:
<b>{ACTIVATION_TARGET:,}</b>

📸 اینستاگرام:
<b>{stats['instagram']:,}</b>

▶️ یوتیوب:
<b>{stats['youtube']:,}</b>

📢 تلگرام:
<b>{stats['telegram']:,}</b>

📌 نکته مهم:
فعال‌سازی شبکه <b>جدا از ثبت‌نام مسابقه</b> است.
"""

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=activation_keyboard()
    )


# =========================================================
# SUPPORT
# =========================================================

async def show_support(query, user_id):
    text = """
<b>🆘 پشتیبانی محفل خوش‌شانس‌ها</b>

پیام خود را در یک پیام ارسال کنید.

مثلاً:
مشکل ثبت‌نام دارم
یا
سؤال من درباره مسابقه است.

بعد از ارسال، درخواست شما برای مدیریت ثبت می‌شود.
"""

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✉️ ارسال پیام پشتیبانی",
                    callback_data="support_new"
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


async def support_new(query, context):
    context.user_data["waiting_support"] = True

    await query.edit_message_text(
        "✉️ لطفاً پیام پشتیبانی خود را همینجا ارسال کنید.\n\n"
        "برای لغو، /cancel را بزنید."
    )


async def handle_support_message(update, context):
    user = update.effective_user

    if not context.user_data.get("waiting_support"):
        return False

    text = update.message.text.strip()

    if not text:
        return True

    if text == "/cancel":
        context.user_data["waiting_support"] = False

        await update.message.reply_text(
            "لغو شد.",
            reply_markup=main_keyboard()
        )

        return True

    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO support_tickets
        (user_id, message, status, created_at)
        VALUES (?, ?, 'open', ?)
        """,
        (
            user.id,
            text,
            now_iso()
        )
    )

    ticket_id = cur.lastrowid

    conn.commit()
    conn.close()

    context.user_data["waiting_support"] = False

    await update.message.reply_text(
        f"✅ پیام شما ثبت شد.\n\n"
        f"🎫 شماره درخواست: <b>#{ticket_id}</b>\n\n"
        "مدیریت پس از بررسی پاسخ خواهد داد.",
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard()
    )

    # ارسال به ادمین‌ها
    safe_text = html.escape(text)

    admin_text = (
        f"🆘 <b>تیکت جدید #{ticket_id}</b>\n\n"
        f"👤 کاربر: <code>{user.id}</code>\n"
        f"نام: {html.escape(user.first_name or '')}\n"
        f"Username: @{html.escape(user.username or '-')}\n\n"
        f"💬 پیام:\n{safe_text}"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "💬 پاسخ",
                callback_data=f"admin_reply:{ticket_id}"
            ),
            InlineKeyboardButton(
                "✅ بستن",
                callback_data=f"admin_close:{ticket_id}"
            )
        ]
    ])

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=admin_text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard
            )
        except Exception as exc:
            logger.warning(
                "Cannot notify admin %s: %s",
                admin_id,
                exc
            )

    return True


# =========================================================
# ADMIN SUPPORT
# =========================================================

async def admin_reply_start(query, context, ticket_id):
    if not is_admin(query.from_user.id):
        await query.answer(
            "دسترسی ندارید.",
            show_alert=True
        )
        return

    context.user_data["admin_reply_ticket"] = ticket_id

    await query.edit_message_text(
        f"💬 پاسخ به تیکت #{ticket_id}\n\n"
        "متن پاسخ را ارسال کنید."
    )


async def admin_close_ticket(query, ticket_id):
    if not is_admin(query.from_user.id):
        await query.answer(
            "دسترسی ندارید.",
            show_alert=True
        )
        return

    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE support_tickets
        SET status = 'closed'
        WHERE id = ?
        """,
        (ticket_id,)
    )

    conn.commit()

    cur.execute(
        """
        SELECT user_id
        FROM support_tickets
        WHERE id = ?
        """,
        (ticket_id,)
    )

    ticket = cur.fetchone()
    conn.close()

    if ticket:
        try:
            await query.get_bot().send_message(
                chat_id=ticket["user_id"],
                text=(
                    f"✅ درخواست پشتیبانی #{ticket_id} "
                    "بسته شد."
                )
            )
        except Exception:
            pass

    await query.edit_message_text(
        f"✅ تیکت #{ticket_id} بسته شد."
    )


async def process_admin_reply(update, context):
    ticket_id = context.user_data.get(
        "admin_reply_ticket"
    )

    if not ticket_id:
        return False

    if not is_admin(update.effective_user.id):
        return True

    text = update.message.text.strip()

    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT user_id
        FROM support_tickets
        WHERE id = ?
        """,
        (ticket_id,)
    )

    ticket = cur.fetchone()

    if not ticket:
        conn.close()
        context.user_data.pop(
            "admin_reply_ticket",
            None
        )
        await update.message.reply_text(
            "تیکت پیدا نشد."
        )
        return True

    cur.execute(
        """
        UPDATE support_tickets
        SET status = 'answered',
            admin_reply = ?,
            replied_at = ?
        WHERE id = ?
        """,
        (
            text,
            now_iso(),
            ticket_id
        )
    )

    conn.commit()
    conn.close()

    context.user_data.pop(
        "admin_reply_ticket",
        None
    )

    try:
        await context.bot.send_message(
            chat_id=ticket["user_id"],
            text=(
                f"💬 <b>پاسخ پشتیبانی</b>\n\n"
                f"🎫 تیکت #{ticket_id}\n\n"
                f"{html.escape(text)}"
            ),
            parse_mode=ParseMode.HTML
        )
    except Exception as exc:
        logger.warning(
            "Cannot send support reply: %s",
            exc
        )

    await update.message.reply_text(
        f"✅ پاسخ تیکت #{ticket_id} ارسال شد."
    )

    return True


# =========================================================
# ADMIN COMMANDS
# =========================================================

async def admin_command(update, context):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(
            "⛔ دسترسی ندارید."
        )
        return

    text = """
<b>👑 پنل مدیریت</b>

/status
وضعیت شبکه

/setig عدد
تعداد اینستاگرام

/setyt عدد
تعداد یوتیوب

/settg عدد
تعداد تلگرام

/users
تعداد کاربران

/tickets
تیکت‌های باز

/draw
قرعه‌کشی

/announce متن
ارسال پیام به کاربران
"""

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML
    )


async def admin_status(update, context):
    if not is_admin(update.effective_user.id):
        return

    stats = get_network_stats()
    active = update_network_status()

    text = f"""
<b>📊 وضعیت شبکه</b>

Instagram: {stats['instagram']:,}
YouTube: {stats['youtube']:,}
Telegram: {stats['telegram']:,}

هدف: {ACTIVATION_TARGET:,}

وضعیت:
{'🟢 فعال' if active else '🔴 غیرفعال'}
"""

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML
    )


async def set_network_value(update, context, key):
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text(
            "عدد را وارد کنید."
        )
        return

    try:
        value = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "عدد نامعتبر است."
        )
        return

    set_setting(key, value)
    active = update_network_status()

    await update.message.reply_text(
        f"✅ ثبت شد: {value:,}\n"
        f"شبکه: {'فعال' if active else 'غیرفعال'}"
    )


async def set_ig(update, context):
    await set_network_value(
        update,
        context,
        "instagram_followers"
    )


async def set_yt(update, context):
    await set_network_value(
        update,
        context,
        "youtube_subscribers"
    )


async def set_tg(update, context):
    await set_network_value(
        update,
        context,
        "telegram_members"
    )


async def admin_users(update, context):
    if not is_admin(update.effective_user.id):
        return

    conn = db()
    cur = conn.cursor()

    cur.execute(
        "SELECT COUNT(*) AS c FROM users"
    )
    total = cur.fetchone()["c"]

    cur.execute(
        """
        SELECT COUNT(*) AS c
        FROM users
        WHERE registered = 1
        """
    )
    registered = cur.fetchone()["c"]

    conn.close()

    await update.message.reply_text(
        f"👥 کل کاربران: {total:,}\n"
        f"🎟️ ثبت‌نام‌شده‌ها: {registered:,}"
    )


async def admin_tickets(update, context):
    if not is_admin(update.effective_user.id):
        return

    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM support_tickets
        WHERE status != 'closed'
        ORDER BY id DESC
        LIMIT 20
        """
    )

    tickets = cur.fetchall()
    conn.close()

    if not tickets:
        await update.message.reply_text(
            "✅ تیکت بازی وجود ندارد."
        )
        return

    for ticket in tickets:
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "💬 پاسخ",
                    callback_data=f"admin_reply:{ticket['id']}"
                ),
                InlineKeyboardButton(
                    "✅ بستن",
                    callback_data=f"admin_close:{ticket['id']}"
                )
            ]
        ])

        await update.message.reply_text(
            f"🎫 <b>#{ticket['id']}</b>\n\n"
            f"👤 {ticket['user_id']}\n"
            f"📌 {ticket['status']}\n\n"
            f"{html.escape(ticket['message'])}",
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )


# =========================================================
# DRAW
# =========================================================

async def admin_draw(update, context):
    if not is_admin(update.effective_user.id):
        return

    if not network_is_active():
        await update.message.reply_text(
            "⛔ قرعه‌کشی مجاز نیست.\n"
            "شبکه هنوز فعال نشده است."
        )
        return

    campaigns = get_active_campaigns()

    if not campaigns:
        await update.message.reply_text(
            "مسابقه فعالی وجود ندارد."
        )
        return

    campaign = campaigns[0]

    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT user_id, chances
        FROM participations
        WHERE campaign_id = ?
        """,
        (campaign["id"],)
    )

    rows = cur.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text(
            "شرکت‌کننده‌ای وجود ندارد."
        )
        return

    pool = []

    for row in rows:
        weight = max(
            1,
            int(row["chances"])
        )

        pool.extend(
            [row["user_id"]] * weight
        )

    winner_id = random.choice(pool)

    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO winners
        (campaign_id, user_id, created_at)
        VALUES (?, ?, ?)
        """,
        (
            campaign["id"],
            winner_id,
            now_iso()
        )
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"🎉 <b>قرعه‌کشی انجام شد</b>\n\n"
        f"🏆 برنده:\n"
        f"<code>{winner_id}</code>",
        parse_mode=ParseMode.HTML
    )


# =========================================================
# BROADCAST
# =========================================================

async def admin_announce(update, context):
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text(
            "متن پیام را بعد از /announce بنویسید."
        )
        return

    message = " ".join(context.args)

    conn = db()
    cur = conn.cursor()

    cur.execute(
        "SELECT telegram_id FROM users"
    )

    users = cur.fetchall()
    conn.close()

    sent = 0

    for row in users:
        try:
            await context.bot.send_message(
                chat_id=row["telegram_id"],
                text=message
            )
            sent += 1
        except Exception:
            pass

    await update.message.reply_text(
        f"📢 ارسال انجام شد.\n"
        f"تعداد موفق: {sent:,}"
    )


# =========================================================
# CALLBACK HANDLER
# =========================================================

async def callbacks(update, context):
    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    ensure_user(query.from_user)

    data = query.data

    if data == "home":
        await query.edit_message_text(
            "🏠 <b>محفل خوش‌شانس‌ها</b>\n\n"
            "گزینه موردنظر را انتخاب کنید:",
            parse_mode=ParseMode.HTML,
            reply_markup=main_keyboard()
        )
        return

    if data == "campaigns":
        await show_campaigns(query)
        return

    if data.startswith("campaign:"):
        campaign_id = int(
            data.split(":", 1)[1]
        )
        await show_campaign(
            query,
            campaign_id
        )
        return

    if data.startswith("rules_join:"):
        campaign_id = int(
            data.split(":", 1)[1]
        )
        await show_rules(
            query,
            campaign_id
        )
        return

    if data.startswith("accept:"):
        campaign_id = int(
            data.split(":", 1)[1]
        )

        await accept_rules_join(
            query,
            user_id,
            campaign_id
        )
        return

    if data == "rules":
        await show_rules(query)
        return

    if data == "activation":
        await show_activation(query)
        return

    if data == "profile":
        await show_profile(
            query,
            user_id
        )
        return

    if data == "referral":
        await show_referral(
            query,
            user_id
        )
        return

    if data == "support":
        await show_support(
            query,
            user_id
        )
        return

    if data == "support_new":
        await support_new(
            query,
            context
        )
        return

    if data.startswith("admin_reply:"):
        ticket_id = int(
            data.split(":", 1)[1]
        )

        await admin_reply_start(
            query,
            context,
            ticket_id
        )
        return

    if data.startswith("admin_close:"):
        ticket_id = int(
            data.split(":", 1)[1]
        )

        await admin_close_ticket(
            query,
            ticket_id
        )
        return


# =========================================================
# MESSAGE HANDLER
# =========================================================

async def text_handler(update, context):
    if not update.message:
        return

    if await process_admin_reply(
        update,
        context
    ):
        return

    if await handle_support_message(
        update,
        context
    ):
        return


# =========================================================
# HEALTH SERVER
# =========================================================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header(
            "Content-Type",
            "text/plain; charset=utf-8"
        )
        self.end_headers()
        self.wfile.write(
            b"MahfelShans Bot is running"
        )

    def log_message(self, format, *args):
        return


def run_health_server():
    server = HTTPServer(
        ("0.0.0.0", PORT),
        HealthHandler
    )

    logger.info(
        "Health server running on port %s",
        PORT
    )

    server.serve_forever()


# =========================================================
# AUTO POST
# =========================================================

async def auto_post(context):
    if not AUTO_POSTS_ENABLED:
        return

    if not TELEGRAM_CHANNEL:
        return

    messages = [
        "🎉 محفل خوش‌شانس‌ها در حال نزدیک شدن به هدف بزرگ خود است!",
        "🎁 مسابقات و جوایز بزرگ در راه هستند.",
        "👥 دوستان خود را به محفل خوش‌شانس‌ها دعوت کنید.",
        "📢 برای اطلاع از مسابقات آینده همراه ما باشید.",
    ]

    message = random.choice(messages)

    try:
        await context.bot.send_message(
            chat_id=TELEGRAM_CHANNEL,
            text=message
        )
    except Exception as exc:
        logger.warning(
            "Auto post failed: %s",
            exc
        )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(update, context):
    logger.error(
        "Telegram error: %s",
        context.error
    )


# =========================================================
# MAIN
# =========================================================

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN is not configured."
        )

    # خیلی مهم:
    # دیتابیس قبل از هر استفاده از settings ساخته می‌شود.
    init_database()

    update_network_status()

    # Health server برای Render
    health_thread = threading.Thread(
        target=run_health_server,
        daemon=True
    )

    health_thread.start()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Commands
    application.add_handler(
        CommandHandler(
            "start",
            start
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
            "status",
            admin_status
        )
    )

    application.add_handler(
        CommandHandler(
            "setig",
            set_ig
        )
    )

    application.add_handler(
        CommandHandler(
            "setyt",
            set_yt
        )
    )

    application.add_handler(
        CommandHandler(
            "settg",
            set_tg
        )
    )

    application.add_handler(
        CommandHandler(
            "users",
            admin_users
        )
    )

    application.add_handler(
        CommandHandler(
            "tickets",
            admin_tickets
        )
    )

    application.add_handler(
        CommandHandler(
            "draw",
            admin_draw
        )
    )

    application.add_handler(
        CommandHandler(
            "announce",
            admin_announce
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            callbacks
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler
        )
    )

    application.add_error_handler(
        error_handler
    )

    # Auto posts
    if AUTO_POSTS_ENABLED:
        application.job_queue.run_repeating(
            auto_post,
            interval=AUTO_POST_INTERVAL,
            first=60
        )

    logger.info(
        "MahfelShans bot starting..."
    )

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
