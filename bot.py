import os
import sqlite3
import logging
import asyncio
import random
import json
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.parse import urlencode

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

# =========================================================
# CONFIG
# =========================================================

BOT_USERNAME = "MahfelShansBot"

DB_FILE = "mahfelshans.db"

INSTAGRAM_URL = "https://instagram.com/MAHFELSHANS"
YOUTUBE_URL = "https://youtube.com/@mahfelshans"
TELEGRAM_URL = "https://t.me/MahfelShans"

DEFAULT_YOUTUBE_HANDLE = "@mahfelshans"
DEFAULT_TELEGRAM_CHANNEL = "@MahfelShans"

CHANNEL_POST_INTERVAL_HOURS = int(
    os.environ.get("CHANNEL_POST_INTERVAL_HOURS", "2")
)

NETWORK_UPDATE_HOURS = int(
    os.environ.get("NETWORK_UPDATE_HOURS", "6")
)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()

RENDER_EXTERNAL_URL = os.environ.get(
    "RENDER_EXTERNAL_URL", ""
).strip()

YOUTUBE_API_KEY = os.environ.get(
    "YOUTUBE_API_KEY", ""
).strip()

YOUTUBE_HANDLE = os.environ.get(
    "YOUTUBE_HANDLE",
    DEFAULT_YOUTUBE_HANDLE
).strip()

TELEGRAM_CHANNEL = os.environ.get(
    "TELEGRAM_CHANNEL",
    DEFAULT_TELEGRAM_CHANNEL
).strip()

PORT = int(os.environ.get("PORT", "10000"))

ADMIN_IDS = set()

for item in os.environ.get("ADMIN_IDS", "").split(","):
    item = item.strip()

    if item:
        try:
            ADMIN_IDS.add(int(item))
        except ValueError:
            pass


RULES_VERSION = "1.0"

INSTAGRAM_VERIFICATION_ENABLED = False
YOUTUBE_VERIFICATION_ENABLED = False
TELEGRAM_MEMBERSHIP_REQUIRED = True


# =========================================================
# DATABASE
# =========================================================

def db_connect():
    conn = sqlite3.connect(
        DB_FILE,
        check_same_thread=False
    )

    conn.row_factory = sqlite3.Row

    return conn


def init_db():

    conn = db_connect()

    cur = conn.cursor()

    # USERS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            first_name TEXT,
            username TEXT,
            phone TEXT,
            joined_at TEXT,
            accepted_rules INTEGER DEFAULT 0,
            rules_version TEXT DEFAULT '',
            chances INTEGER DEFAULT 0,
            referred_by INTEGER,
            is_active INTEGER DEFAULT 1
        )
    """)

    # REFERRALS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inviter_id INTEGER,
            invited_id INTEGER UNIQUE,
            created_at TEXT
        )
    """)

    # CAMPAIGNS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            description TEXT,
            prize TEXT,
            prize_count INTEGER DEFAULT 1,
            sponsor_id INTEGER,
            sponsor_name TEXT,
            sponsor_budget REAL DEFAULT 0,
            draw_date TEXT,
            status TEXT DEFAULT 'active',
            created_at TEXT
        )
    """)

    # PARTICIPATIONS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS participations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER,
            user_id INTEGER,
            chance_number INTEGER,
            created_at TEXT,
            UNIQUE(campaign_id, user_id, chance_number)
        )
    """)

    # RULE ACCEPTANCE
    cur.execute("""
        CREATE TABLE IF NOT EXISTS rule_acceptances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            rules_version TEXT,
            accepted_at TEXT
        )
    """)

    # WINNERS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS winners (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER,
            user_id INTEGER,
            prize TEXT,
            selected_at TEXT,
            announced INTEGER DEFAULT 0
        )
    """)

    # SUPPORT
    cur.execute("""
        CREATE TABLE IF NOT EXISTS support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            message TEXT,
            status TEXT DEFAULT 'open',
            created_at TEXT,
            replied_at TEXT,
            reply TEXT
        )
    """)

    # PAYMENTS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            status TEXT,
            reference TEXT,
            created_at TEXT
        )
    """)

    # SPONSORS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sponsors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            phone TEXT,
            budget REAL DEFAULT 0,
            description TEXT,
            created_at TEXT
        )
    """)

    # SETTINGS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # LOGS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS operation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER,
            action TEXT,
            details TEXT,
            created_at TEXT
        )
    """)

    defaults = {

        "activation_followers": "100000",

        "plan_max_followers": "1000000",

        "daily_prize_amount": "10000000",

        "payment_enabled": "0",

        "rules_version": RULES_VERSION,

        "instagram_followers": "0",

        "youtube_followers": "0",

        "telegram_followers": "0",

        "networks_activated": "0",

        "network_last_update": "",

        "total_sponsor_budget": "0",

        "instagram_verification_enabled": "0",

        "youtube_verification_enabled": "0",

        "telegram_membership_required": "1",
    }

    for key, value in defaults.items():

        cur.execute(
            """
            INSERT OR IGNORE INTO settings(key, value)
            VALUES(?, ?)
            """,
            (key, value)
        )

    conn.commit()

    conn.close()


# =========================================================
# SETTINGS
# =========================================================

def get_setting(key, default=None):

    conn = db_connect()

    row = conn.execute(
        "SELECT value FROM settings WHERE key=?",
        (key,)
    ).fetchone()

    conn.close()

    if row:
        return row["value"]

    return default


def set_setting(key, value):

    conn = db_connect()

    conn.execute(
        """
        INSERT INTO settings(key, value)
        VALUES(?, ?)
        ON CONFLICT(key)
        DO UPDATE SET value=excluded.value
        """,
        (key, str(value))
    )

    conn.commit()

    conn.close()


# =========================================================
# LOGGING OPERATIONS
# =========================================================

def log_operation(
    admin_id,
    action,
    details=""
):

    conn = db_connect()

    conn.execute(
        """
        INSERT INTO operation_logs(
            admin_id,
            action,
            details,
            created_at
        )
        VALUES(?,?,?,?)
        """,
        (
            admin_id,
            action,
            details,
            datetime.utcnow().isoformat()
        )
    )

    conn.commit()

    conn.close()


# =========================================================
# USERS
# =========================================================

def get_user(user_id):

    conn = db_connect()

    row = conn.execute(
        "SELECT * FROM users WHERE id=?",
        (user_id,)
    ).fetchone()

    conn.close()

    return row


def create_user(
    tg_user,
    referred_by=None
):

    conn = db_connect()

    existing = conn.execute(
        "SELECT * FROM users WHERE id=?",
        (tg_user.id,)
    ).fetchone()

    if existing:

        conn.execute(
            """
            UPDATE users
            SET first_name=?,
                username=?
            WHERE id=?
            """,
            (
                tg_user.first_name or "",
                tg_user.username or "",
                tg_user.id
            )
        )

        conn.commit()
        conn.close()

        return False

    conn.execute(
        """
        INSERT INTO users(
            id,
            first_name,
            username,
            joined_at,
            chances,
            referred_by,
            is_active
        )
        VALUES(?,?,?,?,?,?,?)
        """,
        (
            tg_user.id,
            tg_user.first_name or "",
            tg_user.username or "",
            datetime.utcnow().isoformat(),
            1,
            referred_by,
            1
        )
    )

    # Referral
    if referred_by and referred_by != tg_user.id:

        inviter = conn.execute(
            "SELECT id FROM users WHERE id=?",
            (referred_by,)
        ).fetchone()

        if inviter:

            try:

                conn.execute(
                    """
                    INSERT INTO referrals(
                        inviter_id,
                        invited_id,
                        created_at
                    )
                    VALUES(?,?,?)
                    """,
                    (
                        referred_by,
                        tg_user.id,
                        datetime.utcnow().isoformat()
                    )
                )

                # inviter gets one extra chance
                conn.execute(
                    """
                    UPDATE users
                    SET chances=chances+1
                    WHERE id=?
                    """,
                    (referred_by,)
                )

            except sqlite3.IntegrityError:

                pass

    conn.commit()

    conn.close()

    return True


# =========================================================
# IMPORTANT:
# This function is intentionally NOT named accept_rules.
# This fixes the previous callback bug.
# =========================================================

def save_rules_acceptance(user_id):

    conn = db_connect()

    conn.execute(
        """
        UPDATE users
        SET accepted_rules=1,
            rules_version=?
        WHERE id=?
        """,
        (
            RULES_VERSION,
            user_id
        )
    )

    conn.execute(
        """
        INSERT INTO rule_acceptances(
            user_id,
            rules_version,
            accepted_at
        )
        VALUES(?,?,?)
        """,
        (
            user_id,
            RULES_VERSION,
            datetime.utcnow().isoformat()
        )
    )

    conn.commit()

    conn.close()


# =========================================================
# NETWORK
# =========================================================

def get_network_counts():

    return {

        "instagram": int(
            get_setting(
                "instagram_followers",
                "0"
            ) or 0
        ),

        "youtube": int(
            get_setting(
                "youtube_followers",
                "0"
            ) or 0
        ),

        "telegram": int(
            get_setting(
                "telegram_followers",
                "0"
            ) or 0
        ),
    }


def activation_target():

    return int(
        get_setting(
            "activation_followers",
            "100000"
        )
    )


def all_networks_reached():

    counts = get_network_counts()

    target = activation_target()

    return (
        counts["instagram"] >= target
        and
        counts["youtube"] >= target
        and
        counts["telegram"] >= target
    )


def lottery_is_active():

    return all_networks_reached()


def network_status_text():

    counts = get_network_counts()

    target = activation_target()

    active = all_networks_reached()

    status = (
        "🟢 قرعه‌کشی فعال شده است"
        if active
        else
        "🔴 هنوز فعال نشده است"
    )

    return (
        "📊 وضعیت شبکه محفل خوش‌شانس‌ها\n\n"

        f"📸 اینستاگرام: "
        f"{counts['instagram']:,}\n"

        f"▶️ یوتیوب: "
        f"{counts['youtube']:,}\n"

        f"📢 تلگرام: "
        f"{counts['telegram']:,}\n\n"

        f"🎯 هدف فعال شدن قرعه‌کشی: "
        f"{target:,}\n\n"

        f"وضعیت: {status}"
    )


# =========================================================
# YOUTUBE
# =========================================================

def get_youtube_subscribers():

    if not YOUTUBE_API_KEY:

        return None

    try:

        params = urlencode(
            {
                "part": "statistics",
                "forHandle": YOUTUBE_HANDLE,
                "key": YOUTUBE_API_KEY
            }
        )

        url = (
            "https://www.googleapis.com/"
            "youtube/v3/channels?"
            + params
        )

        request = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        with urlopen(
            request,
            timeout=20
        ) as response:

            data = response.read().decode(
                "utf-8"
            )

        payload = json.loads(data)

        items = payload.get(
            "items",
            []
        )

        if not items:

            return None

        count = (
            items[0]
            .get("statistics", {})
            .get("subscriberCount")
        )

        if count is None:

            return None

        return int(count)

    except Exception as e:

        logger.warning(
            "YouTube subscriber error: %s",
            e
        )

        return None


# =========================================================
# TELEGRAM MEMBERSHIP
# =========================================================

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

    except Exception as e:

        logger.warning(
            "Telegram membership check error: %s",
            e
        )

        return False


# =========================================================
# KEYBOARDS
# =========================================================

def eligibility_keyboard():

    return InlineKeyboardMarkup(
        [

            [
                InlineKeyboardButton(
                    "📢 عضویت در تلگرام",
                    url=TELEGRAM_URL
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
                    "🔄 بررسی عضویت",
                    callback_data="verify_membership"
                )
            ],

            [
                InlineKeyboardButton(
                    "🔙 بازگشت",
                    callback_data="back_main"
                )
            ]
        ]
    )


def main_menu():

    return InlineKeyboardMarkup(
        [

            [
                InlineKeyboardButton(
                    "🎁 مسابقات",
                    callback_data="campaigns"
                ),

                InlineKeyboardButton(
                    "👤 پروفایل",
                    callback_data="profile"
                )
            ],

            [
                InlineKeyboardButton(
                    "🎟 شانس‌های من",
                    callback_data="chances"
                ),

                InlineKeyboardButton(
                    "👥 دعوت دوستان",
                    callback_data="invite"
                )
            ],

            [
                InlineKeyboardButton(
                    "🏆 برندگان",
                    callback_data="winners"
                ),

                InlineKeyboardButton(
                    "📜 آرشیو",
                    callback_data="archive"
                )
            ],

            [
                InlineKeyboardButton(
                    "📊 وضعیت شبکه",
                    callback_data="network"
                ),

                InlineKeyboardButton(
                    "📋 قوانین",
                    callback_data="rules"
                )
            ],

            [
                InlineKeyboardButton(
                    "🎧 پشتیبانی",
                    callback_data="support"
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
                    url=TELEGRAM_URL
                )
            ]
        ]
    )


# =========================================================
# RULES
# =========================================================

RULES_TEXT = """
📋 قوانین محفل خوش‌شانس‌ها

1️⃣ ثبت‌نام و دریافت شانس در این مرحله رایگان است.

2️⃣ با دعوت دوستان می‌توانید شانس بیشتری دریافت کنید.

3️⃣ برای دریافت جایزه، رعایت شرایط اعلام‌شده هر مسابقه الزامی است.

4️⃣ عضویت در کانال تلگرام برای دریافت جایزه الزامی است.

5️⃣ دنبال کردن اینستاگرام و یوتیوب نیز جزو شرایط دریافت جایزه است.

6️⃣ بررسی خودکار اینستاگرام و یوتیوب در مرحله بعد به سیستم اضافه خواهد شد.

7️⃣ قرعه‌کشی پس از رسیدن شبکه‌های تعیین‌شده به حد فعال‌سازی انجام می‌شود.

8️⃣ هدف فعلی فعال شدن قرعه‌کشی:
100,000 عضو / دنبال‌کننده برای هر شبکه تعیین‌شده.

9️⃣ در حال حاضر ثبت‌نام و دریافت شانس رایگان است.

🔟 در صورت رعایت نکردن شرایط دریافت جایزه، امکان عدم تأیید یا لغو جایزه وجود دارد.

⚠️ قوانین هر کمپین ممکن است شرایط تکمیلی داشته باشد که قبل از شرکت اعلام می‌شود.
"""


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    referred_by = None

    if context.args:

        arg = context.args[0].strip()

        if arg.startswith("ref_"):

            try:

                referred_by = int(
                    arg.replace(
                        "ref_",
                        "",
                        1
                    )
                )

            except ValueError:

                referred_by = None

    create_user(
        user,
        referred_by=referred_by
    )

    db_user = get_user(
        user.id
    )

    if not db_user:

        return

    if not db_user["accepted_rules"]:

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "📋 مطالعه قوانین",
                        callback_data="rules_before_accept"
                    )
                ],

                [
                    InlineKeyboardButton(
                        "✅ مطالعه و پذیرش قوانین",
                        callback_data="accept_rules"
                    )
                ]
            ]
        )

        await update.message.reply_text(

            "🎉 به محفل خوش‌شانس‌ها خوش آمدید!\n\n"

            "🎁 ثبت‌نام کاملاً رایگان است.\n\n"

            "قبل از شروع، قوانین را مطالعه و تأیید کنید.",

            reply_markup=keyboard
        )

        return

    await update.message.reply_text(

        "🎉 خوش آمدی به محفل خوش‌شانس‌ها!\n\n"

        "🎁 ثبت‌نام رایگان است.\n"

        "👥 با دعوت دوستان شانس بیشتری می‌گیری.\n\n"

        "🏆 قرعه‌کشی پس از رسیدن شبکه به هدف "
        "۱۰۰ هزار فعال می‌شود.",

        reply_markup=main_menu()
    )


# =========================================================
# ACCEPT RULES
# =========================================================

async def accept_rules(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    # FIXED:
    # No recursive call.
    save_rules_acceptance(
        query.from_user.id
    )

    await query.edit_message_text(

        "✅ قوانین با موفقیت پذیرفته شد.\n\n"

        "🎉 به محفل خوش‌شانس‌ها خوش آمدی!\n\n"

        "🎁 ثبت‌نام رایگان است.\n"

        "👥 دوستانت را دعوت کن و شانس بیشتری بگیر.\n\n"

        "🏆 قرعه‌کشی پس از رسیدن شبکه به هدف فعال می‌شود.",

        reply_markup=main_menu()
    )


# =========================================================
# RULES BEFORE ACCEPT
# =========================================================

async def show_rules_before_accept(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    keyboard = InlineKeyboardMarkup(
        [

            [
                InlineKeyboardButton(
                    "✅ پذیرش قوانین",
                    callback_data="accept_rules"
                )
            ],

            [
                InlineKeyboardButton(
                    "🔙 بازگشت",
                    callback_data="back_start"
                )
            ]
        ]
    )

    await query.edit_message_text(
        RULES_TEXT,
        reply_markup=keyboard
    )


# =========================================================
# VERIFY TELEGRAM
# =========================================================

async def verify_membership(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    is_member = await check_telegram_membership(
        context.bot,
        user_id
    )

    if not is_member:

        await query.edit_message_text(

            "❌ هنوز عضویت تلگرام شما تأیید نشده است.\n\n"

            "ابتدا وارد کانال محفل خوش‌شانس‌ها شوید، "
            "سپس روی «🔄 بررسی عضویت» بزنید.",

            reply_markup=eligibility_keyboard()
        )

        return

    await query.edit_message_text(

        "✅ عضویت تلگرام شما تأیید شد.\n\n"

        "برای دریافت جایزه باید شرایط اعلام‌شده را رعایت کنید:\n\n"

        "📢 عضویت تلگرام\n"
        "📸 دنبال کردن اینستاگرام\n"
        "▶️ دنبال کردن یوتیوب\n\n"

        "⚠️ بررسی خودکار اینستاگرام و یوتیوب "
        "در نسخه فعلی هنوز فعال نشده است.",

        reply_markup=InlineKeyboardMarkup(
            [

                [
                    InlineKeyboardButton(
                        "📢 کانال تلگرام",
                        url=TELEGRAM_URL
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
                        "🔙 بازگشت",
                        callback_data="back_main"
                    )
                ]
            ]
        )
    )


# =========================================================
# PROFILE
# =========================================================

async def show_profile(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    user = get_user(
        query.from_user.id
    )

    if not user:

        return

    username = (
        f"@{user['username']}"
        if user["username"]
        else "ندارد"
    )

    referrals = 0

    conn = db_connect()

    row = conn.execute(
        """
        SELECT COUNT(*) AS total
        FROM referrals
        WHERE inviter_id=?
        """,
        (query.from_user.id,)
    ).fetchone()

    if row:

        referrals = row["total"]

    conn.close()

    await query.edit_message_text(

        "👤 پروفایل شما\n\n"

        f"🆔 شناسه: {user['id']}\n"

        f"👤 نام کاربری: {username}\n\n"

        f"🎟 تعداد شانس‌ها: {user['chances']}\n"

        f"👥 دعوت موفق: {referrals}\n\n"

        "🎁 ثبت‌نام شما رایگان است.",

        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🔙 بازگشت",
                        callback_data="back_main"
                    )
                ]
            ]
        )
    )


# =========================================================
# CHANCES
# =========================================================

async def show_chances(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    user = get_user(
        query.from_user.id
    )

    if not user:

        return

    await query.edit_message_text(

        "🎟 شانس‌های شما\n\n"

        f"تعداد شانس فعلی: {user['chances']}\n\n"

        "💡 با دعوت دوستان می‌توانی شانس بیشتری بگیری.\n\n"

        "هر دعوت موفق = ۱ شانس اضافه برای دعوت‌کننده.",

        reply_markup=InlineKeyboardMarkup(
            [

                [
                    InlineKeyboardButton(
                        "👥 دعوت دوستان",
                        callback_data="invite"
                    )
                ],

                [
                    InlineKeyboardButton(
                        "🔙 بازگشت",
                        callback_data="back_main"
                    )
                ]
            ]
        )
    )


# =========================================================
# INVITE
# =========================================================

async def show_invite(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    invite_link = (
        f"https://t.me/{BOT_USERNAME}"
        f"?start=ref_{user_id}"
    )

    user = get_user(
        user_id
    )

    chances = (
        user["chances"]
        if user
        else 0
    )

    text = (

        "👥 دعوت دوستان\n\n"

        "دوستانت را به محفل خوش‌شانس‌ها دعوت کن.\n\n"

        "🎟 هر دعوت موفق = ۱ شانس اضافه\n\n"

        f"🎟 شانس فعلی شما: {chances}\n\n"

        "🔗 لینک دعوت اختصاصی شما:\n\n"

        f"{invite_link}\n\n"

        "📲 این لینک را برای دوستانت ارسال کن."
    )

    await query.edit_message_text(

        text,

        reply_markup=InlineKeyboardMarkup(
            [

                [
                    InlineKeyboardButton(
                        "📤 اشتراک لینک دعوت",
                        url=(
                            "https://t.me/share/url?"
                            + urlencode(
                                {
                                    "url": invite_link,
                                    "text":
                                    "🎉 به محفل خوش‌شانس‌ها بپیوند!"
                                }
                            )
                        )
                    )
                ],

                [
                    InlineKeyboardButton(
                        "🔙 بازگشت",
                        callback_data="back_main"
                    )
                ]
            ]
        )
    )


# =========================================================
# NETWORK STATUS
# =========================================================

async def show_network(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    await query.edit_message_text(

        network_status_text(),

        reply_markup=InlineKeyboardMarkup(
            [

                [
                    InlineKeyboardButton(
                        "🔄 بروزرسانی",
                        callback_data="network"
                    )
                ],

                [
                    InlineKeyboardButton(
                        "🔙 بازگشت",
                        callback_data="back_main"
                    )
                ]
            ]
        )
    )


# =========================================================
# CAMPAIGNS
# =========================================================

def get_active_campaigns():

    conn = db_connect()

    rows = conn.execute(
        """
        SELECT *
        FROM campaigns
        WHERE status='active'
        ORDER BY id DESC
        """
    ).fetchall()

    conn.close()

    return rows


async def show_campaigns(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    campaigns = get_active_campaigns()

    if not campaigns:

        await query.edit_message_text(

            "🎁 مسابقات\n\n"

            "فعلاً مسابقه فعالی وجود ندارد.\n\n"

            "🔔 از کانال محفل خوش‌شانس‌ها خارج نشو "
            "تا شروع مسابقات را از دست ندهی.",

            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "📢 کانال تلگرام",
                            url=TELEGRAM_URL
                        )
                    ],

                    [
                        InlineKeyboardButton(
                            "🔙 بازگشت",
                            callback_data="back_main"
                        )
                    ]
                ]
            )
        )

        return

    keyboard = []

    for campaign in campaigns:

        keyboard.append(
            [
                InlineKeyboardButton(
                    f"🎁 {campaign['title']}",
                    callback_data=f"campaign_{campaign['id']}"
                )
            ]
        )

    keyboard.append(
        [
            InlineKeyboardButton(
                "🔙 بازگشت",
                callback_data="back_main"
            )
        ]
    )

    await query.edit_message_text(
        "🎁 مسابقات فعال\n\n"
        "مسابقه موردنظر را انتخاب کن:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================================================
# JOIN CAMPAIGN
# =========================================================

async def campaign_details(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    campaign_id
):

    query = update.callback_query

    campaign_id = int(campaign_id)

    conn = db_connect()

    campaign = conn.execute(
        """
        SELECT *
        FROM campaigns
        WHERE id=?
        """,
        (campaign_id,)
    ).fetchone()

    conn.close()

    if not campaign:

        await query.edit_message_text(
            "❌ مسابقه پیدا نشد.",
            reply_markup=main_menu()
        )

        return

    text = (

        f"🎁 {campaign['title']}\n\n"

        f"🏆 جایزه: {campaign['prize']}\n"

        f"🎯 تعداد برنده: {campaign['prize_count']}\n\n"

        f"{campaign['description'] or ''}\n\n"

        "📌 شرایط شرکت:\n"

        "📢 عضویت تلگرام الزامی است.\n"
        "📸 دنبال کردن اینستاگرام الزامی است.\n"
        "▶️ دنبال کردن یوتیوب الزامی است.\n\n"

        "⚠️ قرعه‌کشی فقط بعد از فعال شدن شبکه انجام می‌شود."
    )

    keyboard = InlineKeyboardMarkup(
        [

            [
                InlineKeyboardButton(
                    "📢 عضویت تلگرام",
                    url=TELEGRAM_URL
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
                    "🎟 شرکت در مسابقه",
                    callback_data=f"join_{campaign_id}"
                )
            ],

            [
                InlineKeyboardButton(
                    "🔙 مسابقات",
                    callback_data="campaigns"
                )
            ]
        ]
    )

    await query.edit_message_text(
        text,
        reply_markup=keyboard
    )


async def join_campaign(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    campaign_id
):

    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    campaign_id = int(campaign_id)

    user = get_user(user_id)

    if not user:

        await query.answer(
            "ابتدا /start را بزنید.",
            show_alert=True
        )

        return

    if not user["accepted_rules"]:

        await query.answer(
            "ابتدا قوانین را بپذیرید.",
            show_alert=True
        )

        return

    # Telegram membership check
    is_member = await check_telegram_membership(
        context.bot,
        user_id
    )

    if not is_member:

        await query.edit_message_text(

            "❌ برای شرکت در مسابقه ابتدا باید "
            "عضو کانال تلگرام محفل خوش‌شانس‌ها باشید.\n\n"

            "بعد از عضویت روی «🔄 بررسی عضویت» بزنید.",

            reply_markup=eligibility_keyboard()
        )

        return

    # Lottery must be active
    if not lottery_is_active():

        await query.edit_message_text(

            "⏳ هنوز قرعه‌کشی فعال نشده است.\n\n"

            "قرعه‌کشی زمانی فعال می‌شود که شبکه‌های "
            "تعیین‌شده به هدف ۱۰۰,۰۰۰ برسند.\n\n"

            + network_status_text(),

            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "👥 دعوت دوستان",
                            callback_data="invite"
                        )
                    ],

                    [
                        InlineKeyboardButton(
                            "🔙 بازگشت",
                            callback_data="back_main"
                        )
                    ]
                ]
            )
        )

        return

    conn = db_connect()

    campaign = conn.execute(
        """
        SELECT *
        FROM campaigns
        WHERE id=?
        AND status='active'
        """,
        (campaign_id,)
    ).fetchone()

    if not campaign:

        conn.close()

        await query.answer(
            "این مسابقه دیگر فعال نیست.",
            show_alert=True
        )

        return

    # Check existing participation
    existing = conn.execute(
        """
        SELECT COUNT(*) AS total
        FROM participations
        WHERE campaign_id=?
        AND user_id=?
        """,
        (
            campaign_id,
            user_id
        )
    ).fetchone()

    if existing and existing["total"] > 0:

        conn.close()

        await query.answer(
            "شما قبلاً در این مسابقه شرکت کرده‌اید.",
            show_alert=True
        )

        return

    user_chances = int(
        user["chances"] or 0
    )

    if user_chances <= 0:

        conn.close()

        await query.answer(
            "شانس کافی ندارید.",
            show_alert=True
        )

        return

    now = datetime.utcnow().isoformat()

    # Give all current chances to this campaign
    for number in range(
        1,
        user_chances + 1
    ):

        conn.execute(
            """
            INSERT OR IGNORE INTO participations(
                campaign_id,
                user_id,
                chance_number,
                created_at
            )
            VALUES(?,?,?,?)
            """,
            (
                campaign_id,
                user_id,
                number,
                now
            )
        )

    conn.commit()

    total = conn.execute(
        """
        SELECT COUNT(*)
        FROM participations
        WHERE campaign_id=?
        AND user_id=?
        """,
        (
            campaign_id,
            user_id
        )
    ).fetchone()[0]

    conn.close()

    await query.edit_message_text(

        "✅ ثبت‌نام شما در مسابقه انجام شد.\n\n"

        f"🎁 مسابقه: {campaign['title']}\n"

        f"🎟 تعداد شانس ثبت‌شده: {total}\n\n"

        "🍀 موفق باشی!\n\n"

        "⚠️ برای دریافت جایزه باید شرایط شبکه‌های "
        "اجتماعی را در زمان اعلام برنده نیز داشته باشید.",

        reply_markup=main_menu()
    )


# =========================================================
# WINNERS
# =========================================================

async def show_winners(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    conn = db_connect()

    rows = conn.execute(
        """
        SELECT
            winners.*,
            users.first_name,
            users.username,
            campaigns.title
        FROM winners
        LEFT JOIN users
            ON winners.user_id=users.id
        LEFT JOIN campaigns
            ON winners.campaign_id=campaigns.id
        WHERE winners.announced=1
        ORDER BY winners.id DESC
        LIMIT 20
        """
    ).fetchall()

    conn.close()

    if not rows:

        text = (
            "🏆 برندگان\n\n"
            "هنوز برنده‌ای اعلام نشده است."
        )

    else:

        lines = [
            "🏆 آخرین برندگان\n"
        ]

        for row in rows:

            name = (
                row["first_name"]
                or "کاربر"
            )

            lines.append(
                f"🎉 {name} — "
                f"{row['prize']}\n"
                f"🎁 {row['title']}\n"
            )

        text = "\n".join(lines)

    await query.edit_message_text(

        text,

        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🔙 بازگشت",
                        callback_data="back_main"
                    )
                ]
            ]
        )
    )


# =========================================================
# ARCHIVE
# =========================================================

async def show_archive(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    conn = db_connect()

    rows = conn.execute(
        """
        SELECT
            id,
            title,
            prize,
            status,
            created_at
        FROM campaigns
        ORDER BY id DESC
        LIMIT 30
        """
    ).fetchall()

    conn.close()

    if not rows:

        text = (
            "📜 آرشیو\n\n"
            "هنوز مسابقه‌ای ثبت نشده است."
        )

    else:

        lines = [
            "📜 آرشیو مسابقات\n"
        ]

        for row in rows:

            if row["status"] == "active":

                status = "🟢 فعال"

            elif row["status"] == "completed":

                status = "🏁 پایان‌یافته"

            else:

                status = "⚪ " + str(
                    row["status"]
                )

            lines.append(
                f"🎁 {row['title']}\n"
                f"🏆 {row['prize']}\n"
                f"{status}\n"
            )

        text = "\n".join(lines)

    await query.edit_message_text(

        text,

        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🔙 بازگشت",
                        callback_data="back_main"
                    )
                ]
            ]
        )
    )


# =========================================================
# SUPPORT
# =========================================================

async def show_support(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    context.user_data[
        "waiting_support"
    ] = True

    await query.edit_message_text(

        "🎧 پشتیبانی محفل خوش‌شانس‌ها\n\n"

        "پیام خود را همینجا ارسال کنید.\n\n"

        "📌 پیام شما برای تیم پشتیبانی ثبت می‌شود.\n\n"

        "برای لغو، /cancel را بزنید.",

        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🔙 بازگشت",
                        callback_data="back_main"
                    )
                ]
            ]
        )
    )


async def receive_support_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.user_data.get(
        "waiting_support"
    ):

        return False

    text = update.message.text

    user_id = update.effective_user.id

    conn = db_connect()

    cursor = conn.execute(
        """
        INSERT INTO support_tickets(
            user_id,
            message,
            status,
            created_at
        )
        VALUES(?,?,?,?)
        """,
        (
            user_id,
            text,
            "open",
            datetime.utcnow().isoformat()
        )
    )

    ticket_id = cursor.lastrowid

    conn.commit()

    conn.close()

    context.user_data[
        "waiting_support"
    ] = False

    await update.message.reply_text(

        "✅ پیام شما ثبت شد.\n\n"

        f"🎫 شماره درخواست: #{ticket_id}\n\n"

        "پشتیبانی در اولین فرصت پاسخ خواهد داد.",

        reply_markup=main_menu()
    )

    # Send notification to admins
    for admin_id in ADMIN_IDS:

        try:

            await context.bot.send_message(

                chat_id=admin_id,

                text=(
                    "🎧 درخواست جدید پشتیبانی\n\n"

                    f"🎫 شماره: #{ticket_id}\n"

                    f"👤 کاربر: {user_id}\n\n"

                    f"💬 پیام:\n{text}"
                )
            )

        except Exception as e:

            logger.warning(
                "Admin support notification failed: %s",
                e
            )

    return True


async def cancel_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    context.user_data[
        "waiting_support"
    ] = False

    await update.message.reply_text(
        "❌ عملیات لغو شد.",
        reply_markup=main_menu()
    )


# =========================================================
# BACK MAIN
# =========================================================

async def back_main(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    await query.edit_message_text(

        "🏠 منوی اصلی محفل خوش‌شانس‌ها",

        reply_markup=main_menu()
    )


async def back_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    await query.edit_message_text(

        "🎉 به محفل خوش‌شانس‌ها خوش آمدید!\n\n"

        "برای ادامه ابتدا قوانین را مطالعه و قبول کنید.",

        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "📋 مطالعه قوانین",
                        callback_data="rules_before_accept"
                    )
                ],

                [
                    InlineKeyboardButton(
                        "✅ پذیرش قوانین",
                        callback_data="accept_rules"
                    )
                ]
            ]
        )
    )


# =========================================================
# GENERIC CALLBACK ROUTER
# =========================================================

async def callback_router(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    data = query.data or ""

    if data == "accept_rules":

        await accept_rules(
            update,
            context
        )

        return

    if data == "rules_before_accept":

        await show_rules_before_accept(
            update,
            context
        )

        return

    if data == "verify_membership":

        await verify_membership(
            update,
            context
        )

        return

    if data == "back_main":

        await back_main(
            update,
            context
        )

        return

    if data == "back_start":

        await back_start(
            update,
            context
        )

        return

    if data == "profile":

        await show_profile(
            update,
            context
        )

        return

    if data == "chances":

        await show_chances(
            update,
            context
        )

        return

    if data == "invite":

        await show_invite(
            update,
            context
        )

        return

    if data == "network":

        await show_network(
            update,
            context
        )

        return

    if data == "campaigns":

        await show_campaigns(
            update,
            context
        )

        return

    if data == "winners":

        await show_winners(
            update,
            context
        )

        return

    if data == "archive":

        await show_archive(
            update,
            context
        )

        return

    if data == "support":

        await show_support(
            update,
            context
        )

        return

    if data == "rules":

        await query.answer()

        await query.edit_message_text(

            RULES_TEXT,

            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔙 بازگشت",
                            callback_data="back_main"
                        )
                    ]
                ]
            )
        )

        return

    if data.startswith("campaign_"):

        campaign_id = data.split(
            "_",
            1
        )[1]

        await query.answer()

        await campaign_details(
            update,
            context,
            campaign_id
        )

        return

    if data.startswith("join_"):

        campaign_id = data.split(
            "_",
            1
        )[1]

        await join_campaign(
            update,
            context,
            campaign_id
        )

        return

    await query.answer(
        "گزینه نامعتبر است.",
        show_alert=True
    )


# =========================================================
# ADMIN CHECK
# =========================================================

def is_admin(user_id):

    return user_id in ADMIN_IDS


# =========================================================
# ADMIN: INSTAGRAM FOLLOWERS
# =========================================================

async def admin_igfollowers(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(
        update.effective_user.id
    ):

        return

    if not context.args:

        await update.message.reply_text(
            "استفاده:\n/igfollowers 100000"
        )

        return

    try:

        count = int(
            context.args[0]
        )

    except ValueError:

        await update.message.reply_text(
            "❌ عدد صحیح وارد کنید."
        )

        return

    set_setting(
        "instagram_followers",
        count
    )

    log_operation(
        update.effective_user.id,
        "igfollowers",
        str(count)
    )

    await update.message.reply_text(

        f"✅ تعداد فالوور اینستاگرام ثبت شد:\n"
        f"{count:,}\n\n"
        + network_status_text()
    )


# =========================================================
# ADMIN: TELEGRAM FOLLOWERS MANUAL
# =========================================================

async def admin_tgfollower(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(
        update.effective_user.id
    ):

        return

    if not context.args:

        await update.message.reply_text(
            "استفاده:\n/tgfollowers 100000"
        )

        return

    try:

        count = int(
            context.args[0]
        )

    except ValueError:

        await update.message.reply_text(
            "❌ عدد صحیح وارد کنید."
        )

        return

    set_setting(
        "telegram_followers",
        count
    )

    await update.message.reply_text(
        network_status_text()
    )


# =========================================================
# ADMIN: CREATE CAMPAIGN
# =========================================================

async def admin_create_campaign(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(
        update.effective_user.id
    ):

        return

    if len(context.args) < 3:

        await update.message.reply_text(

            "استفاده:\n"

            "/createcampaign عنوان | توضیحات | جایزه\n\n"

            "مثال:\n"

            "/createcampaign "
            "جایزه بزرگ | "
            "اولین مسابقه محفل | "
            "100 میلیون تومان"
        )

        return

    raw = " ".join(
        context.args
    )

    parts = [
        x.strip()
        for x in raw.split("|")
    ]

    if len(parts) < 3:

        await update.message.reply_text(
            "❌ فرمت اشتباه است."
        )

        return

    title = parts[0]

    description = parts[1]

    prize = parts[2]

    conn = db_connect()

    cursor = conn.execute(
        """
        INSERT INTO campaigns(
            title,
            description,
            prize,
            prize_count,
            status,
            created_at
        )
        VALUES(?,?,?,?,?,?)
        """,
        (
            title,
            description,
            prize,
            1,
            "active",
            datetime.utcnow().isoformat()
        )
    )

    campaign_id = cursor.lastrowid

    conn.commit()

    conn.close()

    await update.message.reply_text(

        "✅ مسابقه ساخته شد.\n\n"

        f"🆔 شماره: {campaign_id}\n"
        f"🎁 عنوان: {title}\n"
        f"🏆 جایزه: {prize}"
    )


# =========================================================
# ADMIN: DRAW
# =========================================================

async def admin_draw(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(
        update.effective_user.id
    ):

        return

    if not context.args:

        await update.message.reply_text(
            "استفاده:\n/draw شماره_مسابقه"
        )

        return

    try:

        campaign_id = int(
            context.args[0]
        )

    except ValueError:

        await update.message.reply_text(
            "❌ شماره مسابقه اشتباه است."
        )

        return

    if not lottery_is_active():

        await update.message.reply_text(

            "❌ قرعه‌کشی هنوز فعال نشده است.\n\n"
            + network_status_text()
        )

        return

    conn = db_connect()

    campaign = conn.execute(
        """
        SELECT *
        FROM campaigns
        WHERE id=?
        """,
        (campaign_id,)
    ).fetchone()

    if not campaign:

        conn.close()

        await update.message.reply_text(
            "❌ مسابقه پیدا نشد."
        )

        return

    # Existing winner?
    existing_winner = conn.execute(
        """
        SELECT *
        FROM winners
        WHERE campaign_id=?
        AND announced>=0
        """,
        (campaign_id,)
    ).fetchone()

    if existing_winner:

        conn.close()

        await update.message.reply_text(
            "⚠️ برای این مسابقه قبلاً برنده انتخاب شده است."
        )

        return

    rows = conn.execute(
        """
        SELECT
            p.id,
            p.user_id,
            p.chance_number
        FROM participations p
        WHERE p.campaign_id=?
        """,
        (campaign_id,)
    ).fetchall()

    conn.close()

    if not rows:

        await update.message.reply_text(
            "❌ هیچ شرکت‌کننده‌ای وجود ندارد."
        )

        return

    # Random ticket
    selected = random.choice(
        rows
    )

    selected_user_id = selected["user_id"]

    # Verify Telegram membership
    member_ok = await check_telegram_membership(
        context.bot,
        selected_user_id
    )

    if not member_ok:

        conn = db_connect()

        conn.execute(
            """
            INSERT INTO winners(
                campaign_id,
                user_id,
                prize,
                selected_at,
                announced
            )
            VALUES(?,?,?,?,?)
            """,
            (
                campaign_id,
                selected_user_id,
                campaign["prize"],
                datetime.utcnow().isoformat(),
                -1
            )
        )

        conn.commit()

        conn.close()

        await update.message.reply_text(

            "⚠️ فرد انتخاب‌شده شرایط عضویت تلگرام را ندارد.\n\n"

            "این انتخاب باطل شد.\n"

            "دوباره دستور قرعه‌کشی را اجرا کنید."
        )

        return

    # Save winner
    conn = db_connect()

    conn.execute(
        """
        INSERT INTO winners(
            campaign_id,
            user_id,
            prize,
            selected_at,
            announced
        )
        VALUES(?,?,?,?,?)
        """,
        (
            campaign_id,
            selected_user_id,
            campaign["prize"],
            datetime.utcnow().isoformat(),
            1
        )
    )

    conn.commit()

    conn.close()

    # Get winner data
    winner_user = get_user(
        selected_user_id
    )

    winner_name = (
        winner_user["first_name"]
        if winner_user
        else "برنده"
    )

    await update.message.reply_text(

        "🎉 برنده انتخاب شد!\n\n"

        f"🎁 مسابقه: {campaign['title']}\n"

        f"🏆 جایزه: {campaign['prize']}\n"

        f"👤 برنده: {winner_name}\n"

        f"🆔 شناسه: {selected_user_id}\n\n"

        "✅ عضویت تلگرام برنده تأیید شد."
    )

    try:

        await context.bot.send_message(

            chat_id=selected_user_id,

            text=(

                "🎉🎉 تبریک!\n\n"

                "شما در قرعه‌کشی محفل خوش‌شانس‌ها "
                "به عنوان برنده انتخاب شدید! 🏆\n\n"

                f"🎁 مسابقه: {campaign['title']}\n"

                f"🏆 جایزه: {campaign['prize']}\n\n"

                "🎧 برای هماهنگی دریافت جایزه "
                "با پشتیبانی ارتباط بگیرید."
            ),

            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🎧 پشتیبانی",
                            callback_data="support"
                        )
                    ]
                ]
            )
        )

    except Exception as e:

        logger.warning(
            "Winner DM failed: %s",
            e
        )


# =========================================================
# ADMIN: SHOW STATUS
# =========================================================

async def admin_status(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(
        update.effective_user.id
    ):

        return

    conn = db_connect()

    users = conn.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]

    campaigns = conn.execute(
        """
        SELECT COUNT(*)
        FROM campaigns
        WHERE status='active'
        """
    ).fetchone()[0]

    participations = conn.execute(
        "SELECT COUNT(*) FROM participations"
    ).fetchone()[0]

    conn.close()

    await update.message.reply_text(

        "🛠 وضعیت مدیریتی محفل\n\n"

        f"👥 کاربران: {users:,}\n"

        f"🎁 مسابقات فعال: {campaigns:,}\n"

        f"🎟 مشارکت‌ها: {participations:,}\n\n"

        + network_status_text()
    )


# =========================================================
# ADMIN: POST NOW
# =========================================================

PROMO_MESSAGES = [

    (
        "🔥 محفل خوش‌شانس‌ها در حال ساخته شدن است!\n\n"

        "🎁 ثبت‌نام رایگان است.\n"

        "👥 دوستانت را دعوت کن و شانس بیشتری بگیر.\n\n"

        "📸 اینستاگرام:\n"
        "@MAHFELSHANS\n\n"

        "▶️ یوتیوب:\n"
        "@mahfelshans\n\n"

        "📢 کانال تلگرام:\n"
        "@MahfelShans\n\n"

        "🎯 هدف فعال شدن قرعه‌کشی: 100,000\n\n"

        "⚠️ برای دریافت جایزه، شرایط اعلام‌شده "
        "از جمله عضویت و دنبال کردن شبکه‌های اجتماعی "
        "باید رعایت شود."
    ),

    (
        "🚀 هر نفر یک قدم به شروع نزدیک‌تر!\n\n"

        "🎟 وارد ربات شو و ثبت‌نام کن.\n"

        "👥 دوستانت را دعوت کن.\n"

        "📸 اینستاگرام را دنبال کن.\n"

        "▶️ یوتیوب را دنبال کن.\n"

        "📢 عضو کانال تلگرام باش.\n\n"

        "🏆 وقتی شبکه به 100K برسد، "
        "مرحله قرعه‌کشی فعال می‌شود.\n\n"

        "🎁 ثبت‌نام رایگان است."
    ),

    (
        "🎁 جایزه‌ها از همین‌جا شروع می‌شوند!\n\n"

        "اما یک شرط مهم وجود دارد:\n\n"

        "🎯 اول باید جامعه محفل به هدف 100,000 برسد.\n\n"

        "پس اگر هنوز وارد ربات نشده‌ای:\n"

        "👇 همین الان وارد شو\n"

        f"https://t.me/{BOT_USERNAME}\n\n"

        "👥 دوستانت را هم دعوت کن.\n\n"

        "⚠️ برای دریافت جایزه، رعایت شرایط "
        "شبکه‌های اجتماعی الزامی است."
    ),

    (
        "📢 اگر می‌خواهی اولین مسابقات محفل را از دست ندهی...\n\n"

        "الان وقت ورود است! 🔥\n\n"

        "🎟 ثبت‌نام رایگان\n"
        "👥 دعوت دوستان\n"
        "📸 اینستاگرام\n"
        "▶️ یوتیوب\n"
        "📢 تلگرام\n\n"

        "🎯 هدف: 100,000\n\n"

        "🏆 بعد از رسیدن به هدف، "
        "قرعه‌کشی‌ها وارد مرحله اجرا می‌شوند.\n\n"

        f"👇 ورود به ربات:\n"
        f"https://t.me/{BOT_USERNAME}"
    ),

    (
        "💥 محفل خوش‌شانس‌ها فقط یک کانال نیست؛ "
        "یک جامعه در حال رشد است!\n\n"

        "اگر می‌خواهی در مسابقات آینده حضور داشته باشی:\n\n"

        "1️⃣ وارد ربات شو\n"
        "2️⃣ قوانین را بپذیر\n"
        "3️⃣ دوستانت را دعوت کن\n"
        "4️⃣ شبکه‌های اجتماعی را دنبال کن\n"
        "5️⃣ منتظر رسیدن جامعه به 100K باش\n\n"

        "🎁 ثبت‌نام رایگان است."
    ),
]


async def send_channel_post(
    bot
):

    try:

        message = random.choice(
            PROMO_MESSAGES
        )

        await bot.send_message(

            chat_id=TELEGRAM_CHANNEL,

            text=message,

            disable_web_page_preview=True
        )

        logger.info(
            "Automatic channel post sent."
        )

        return True

    except Exception as e:

        logger.error(
            "Channel post failed: %s",
            e
        )

        return False


async def admin_postnow(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(
        update.effective_user.id
    ):

        return

    success = await send_channel_post(
        context.bot
    )

    if success:

        await update.message.reply_text(
            "✅ پیام در کانال ارسال شد."
        )

    else:

        await update.message.reply_text(

            "❌ ارسال نشد.\n\n"

            "مطمئن شو ربات در کانال "
            "@MahfelShans ادمین است."
        )


# =========================================================
# AUTOMATIC CHANNEL POSTS
# =========================================================

async def automatic_channel_posts(
    application
):

    # First delay
    await asyncio.sleep(30)

    while True:

        try:

            await send_channel_post(
                application.bot
            )

        except Exception as e:

            logger.error(
                "Automatic post error: %s",
                e
            )

        await asyncio.sleep(
            CHANNEL_POST_INTERVAL_HOURS * 3600
        )


# =========================================================
# NETWORK AUTO UPDATE
# =========================================================

async def update_network_counts(
    application
):

    while True:

        try:

            # YouTube
            youtube_count = (
                get_youtube_subscribers()
            )

            if youtube_count is not None:

                set_setting(
                    "youtube_followers",
                    youtube_count
                )

            # Telegram
            try:

                chat = await application.bot.get_chat(
                    TELEGRAM_CHANNEL
                )

                member_count = (
                    await application.bot.get_chat_member_count(
                        TELEGRAM_CHANNEL
                    )
                )

                if member_count is not None:

                    set_setting(
                        "telegram_followers",
                        member_count
                    )

            except Exception as e:

                logger.warning(
                    "Telegram count update error: %s",
                    e
                )

            set_setting(
                "network_last_update",
                datetime.utcnow().isoformat()
            )

            # Activation flag
            if all_networks_reached():

                set_setting(
                    "networks_activated",
                    "1"
                )

            else:

                set_setting(
                    "networks_activated",
                    "0"
                )

        except Exception as e:

            logger.error(
                "Network update error: %s",
                e
            )

        await asyncio.sleep(
            NETWORK_UPDATE_HOURS * 3600
        )


# =========================================================
# POST INIT
# =========================================================

async def post_init(
    application
):

    init_db()

    application.create_task(
        automatic_channel_posts(
            application
        )
    )

    application.create_task(
        update_network_counts(
            application
        )
    )

    logger.info(
        "Bot background tasks started."
    )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update,
    context
):

    logger.error(
        "Exception while handling update:",
        exc_info=context.error
    )


# =========================================================
# TEXT HANDLER
# =========================================================

async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    # Support message has priority
    if context.user_data.get(
        "waiting_support"
    ):

        handled = await receive_support_message(
            update,
            context
        )

        if handled:

            return

    await update.message.reply_text(

        "لطفاً یکی از گزینه‌های منو را انتخاب کنید.",

        reply_markup=main_menu()
    )


# =========================================================
# ADMIN HELP
# =========================================================

async def admin_help(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(
        update.effective_user.id
    ):

        return

    await update.message.reply_text(

        "🛠 دستورات مدیریت\n\n"

        "/status\n"
        "/igfollowers 100000\n"
        "/tgfollowers 100000\n"
        "/createcampaign عنوان | توضیحات | جایزه\n"
        "/draw شماره_مسابقه\n"
        "/postnow\n\n"

        "📌 برای استفاده از دستورات، "
        "شناسه شما باید داخل ADMIN_IDS باشد."
    )


# =========================================================
# BUILD APPLICATION
# =========================================================

def build_application():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN is not set."
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
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "cancel",
            cancel_command
        )
    )

    application.add_handler(
        CommandHandler(
            "igfollowers",
            admin_igfollowers
        )
    )

    application.add_handler(
        CommandHandler(
            "tgfollowers",
            admin_tgfollower
        )
    )

    application.add_handler(
        CommandHandler(
            "createcampaign",
            admin_create_campaign
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
            "status",
            admin_status
        )
    )

    application.add_handler(
        CommandHandler(
            "postnow",
            admin_postnow
        )
    )

    application.add_handler(
        CommandHandler(
            "adminhelp",
            admin_help
        )
    )

    # Callback buttons
    application.add_handler(
        CallbackQueryHandler(
            callback_router
        )
    )

    # Text
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler
        )
    )

    # Errors
    application.add_error_handler(
        error_handler
    )

    return application


# =========================================================
# MAIN
# =========================================================

def main():

    init_db()

    if not BOT_TOKEN:

        raise RuntimeError(
            "❌ BOT_TOKEN در Environment Variables تنظیم نشده است."
        )

    application = build_application()

    logger.info(
        "MahfelShansBot is starting..."
    )

    # Render Webhook
    if RENDER_EXTERNAL_URL:

        webhook_url = (
            RENDER_EXTERNAL_URL.rstrip("/")
            + "/"
            + BOT_TOKEN
        )

        logger.info(
            "Starting webhook: %s",
            RENDER_EXTERNAL_URL
        )

        application.run_webhook(

            listen="0.0.0.0",

            port=PORT,

            url_path=BOT_TOKEN,

            webhook_url=webhook_url,

            allowed_updates=Update.ALL_TYPES
        )

    else:

        logger.info(
            "Starting polling..."
        )

        application.run_polling(
            allowed_updates=Update.ALL_TYPES
        )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    main()
