import os
import sqlite3
import logging
import asyncio
import json
import random
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
    MessageHandler,
    ContextTypes,
    filters,
)

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

NETWORK_UPDATE_HOURS = int(
    os.environ.get("NETWORK_UPDATE_HOURS", "6")
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================================================
# ENV
# =========================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "")
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")

ADMIN_IDS = set()

for item in os.environ.get("ADMIN_IDS", "").split(","):
    item = item.strip()
    if item.isdigit():
        ADMIN_IDS.add(int(item))

YOUTUBE_HANDLE = os.environ.get(
    "YOUTUBE_HANDLE",
    DEFAULT_YOUTUBE_HANDLE,
)

TELEGRAM_CHANNEL = os.environ.get(
    "TELEGRAM_CHANNEL",
    DEFAULT_TELEGRAM_CHANNEL,
)

PORT = int(os.environ.get("PORT", "10000"))


# =========================================================
# DATABASE
# =========================================================

def db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():

    conn = db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            first_name TEXT,
            username TEXT,
            phone TEXT,
            joined_at TEXT,
            accepted_rules INTEGER DEFAULT 0,
            rules_version TEXT DEFAULT '1.0',
            chances INTEGER DEFAULT 1,
            referred_by INTEGER DEFAULT NULL,
            is_active INTEGER DEFAULT 1
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inviter_id INTEGER,
            invited_id INTEGER UNIQUE,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            description TEXT,
            prize TEXT,
            prize_count INTEGER DEFAULT 1,
            sponsor_id INTEGER DEFAULT NULL,
            sponsor_name TEXT DEFAULT '',
            sponsor_budget INTEGER DEFAULT 0,
            draw_date TEXT,
            status TEXT DEFAULT 'active',
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS participations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER,
            user_id INTEGER,
            chance_number INTEGER DEFAULT 1,
            created_at TEXT,
            UNIQUE(campaign_id, user_id, chance_number)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS rule_acceptances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            rules_version TEXT,
            accepted_at TEXT
        )
    """)

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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            message TEXT,
            answer TEXT,
            status TEXT DEFAULT 'open',
            created_at TEXT,
            answered_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            authority TEXT,
            ref_id TEXT,
            status TEXT,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sponsors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            description TEXT,
            website TEXT,
            budget INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active',
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS operation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT,
            created_at TEXT
        )
    """)

    defaults = {
        "activation_followers": "100000",
        "plan_max_followers": "1000000",
        "daily_prize_amount": "10000000",
        "payment_enabled": "0",
        "rules_version": "1.0",
        "instagram_followers": "0",
        "youtube_followers": "0",
        "telegram_followers": "0",
        "networks_activated": "0",
        "network_last_update": "",
        "total_sponsor_budget": "0",
    }

    for key, value in defaults.items():
        cur.execute(
            """
            INSERT OR IGNORE INTO settings(key,value)
            VALUES(?,?)
            """,
            (key, value),
        )

    conn.commit()
    conn.close()


# =========================================================
# SETTINGS
# =========================================================

def setting_get(conn, key, default=None):
    row = conn.execute(
        "SELECT value FROM settings WHERE key=?",
        (key,),
    ).fetchone()

    if row is None:
        return default

    return row["value"]


def setting_set(conn, key, value):
    conn.execute(
        """
        INSERT INTO settings(key,value)
        VALUES(?,?)
        ON CONFLICT(key)
        DO UPDATE SET value=excluded.value
        """,
        (key, str(value)),
    )


# =========================================================
# LOG
# =========================================================

def log_action(user_id, action):

    conn = db()

    conn.execute(
        """
        INSERT INTO operation_logs(
            user_id,
            action,
            created_at
        )
        VALUES(?,?,?)
        """,
        (
            user_id,
            action,
            datetime.utcnow().isoformat(),
        ),
    )

    conn.commit()
    conn.close()


# =========================================================
# ADMIN
# =========================================================

async def admin_required(update):

    user = update.effective_user

    if not user or user.id not in ADMIN_IDS:

        if update.callback_query:
            await update.callback_query.answer(
                "دسترسی ندارید.",
                show_alert=True,
            )
        elif update.message:
            await update.message.reply_text(
                "❌ شما دسترسی مدیریت ندارید."
            )

        return False

    return True


# =========================================================
# USER
# =========================================================

def get_user(user_id):

    conn = db()

    row = conn.execute(
        "SELECT * FROM users WHERE id=?",
        (user_id,),
    ).fetchone()

    conn.close()

    return row


def create_user(tg_user, referred_by=None):

    conn = db()

    existing = conn.execute(
        "SELECT id FROM users WHERE id=?",
        (tg_user.id,),
    ).fetchone()

    if existing:
        conn.close()
        return False

    now = datetime.utcnow().isoformat()

    conn.execute(
        """
        INSERT INTO users(
            id,
            first_name,
            username,
            joined_at,
            referred_by
        )
        VALUES(?,?,?,?,?)
        """,
        (
            tg_user.id,
            tg_user.first_name or "",
            tg_user.username or "",
            now,
            referred_by,
        ),
    )

    conn.commit()
    conn.close()

    return True


# =========================================================
# RULES
# =========================================================

def current_rules_version():

    conn = db()

    value = setting_get(
        conn,
        "rules_version",
        "1.0",
    )

    conn.close()

    return value


def rules_text():

    version = current_rules_version()

    return f"""
📋 قوانین محفل خوش‌شانس‌ها

نسخه قوانین: {version}

1️⃣ ثبت‌نام در محفل رایگان است.

2️⃣ شرکت در کمپین‌ها و قرعه‌کشی‌های محفل
بر اساس قوانین اعلام‌شده هر کمپین انجام می‌شود.

3️⃣ جوایز کمپین‌ها توسط محفل و/یا اسپانسر
کمپین تأمین می‌شوند.

4️⃣ هیچ مبلغی بابت خرید شانس قرعه‌کشی
از کاربر دریافت نمی‌شود.

5️⃣ اطلاعات صحیح هنگام ثبت‌نام بر عهده کاربر است.

6️⃣ نتیجه قرعه‌کشی پس از انجام فرآیند رسمی
در بخش برندگان اعلام می‌شود.

7️⃣ امکان بررسی و ثبت سوابق کمپین‌ها و برندگان
در سیستم وجود دارد.

8️⃣ با ادامه فعالیت در محفل، کاربر تأیید می‌کند
که قوانین هر کمپین را مطالعه کرده است.
"""


def rules_keyboard():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ قبول قوانین",
                callback_data="accept_rules",
            )
        ]
    ])


# =========================================================
# MAIN MENU
# =========================================================

def main_menu():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "🎁 کمپین‌ها",
                callback_data="campaigns",
            ),
            InlineKeyboardButton(
                "👤 پروفایل",
                callback_data="profile",
            ),
        ],

        [
            InlineKeyboardButton(
                "🍀 شانس‌های من",
                callback_data="chances",
            ),
            InlineKeyboardButton(
                "👥 دعوت دوستان",
                callback_data="invite",
            ),
        ],

        [
            InlineKeyboardButton(
                "📜 تاریخچه",
                callback_data="history",
            ),
            InlineKeyboardButton(
                "🏆 برندگان",
                callback_data="winners",
            ),
        ],

        [
            InlineKeyboardButton(
                "🗄 آرشیو",
                callback_data="archive",
            ),
            InlineKeyboardButton(
                "📋 قوانین",
                callback_data="rules",
            ),
        ],

        [
            InlineKeyboardButton(
                "🎧 پشتیبانی",
                callback_data="support",
            ),
        ],

        [
            InlineKeyboardButton(
                "📸 Instagram",
                url=INSTAGRAM_URL,
            ),
            InlineKeyboardButton(
                "▶️ YouTube",
                url=YOUTUBE_URL,
            ),
        ],

        [
            InlineKeyboardButton(
                "📢 Telegram",
                url=TELEGRAM_URL,
            ),
        ],
    ])


# =========================================================
# NETWORK
# =========================================================

def all_networks_reached(conn):

    target = int(
        setting_get(
            conn,
            "activation_followers",
            "100000",
        )
    )

    instagram = int(
        setting_get(
            conn,
            "instagram_followers",
            "0",
        )
    )

    youtube = int(
        setting_get(
            conn,
            "youtube_followers",
            "0",
        )
    )

    telegram = int(
        setting_get(
            conn,
            "telegram_followers",
            "0",
        )
    )

    return (
        instagram >= target
        and youtube >= target
        and telegram >= target
    )


def network_status_text():

    conn = db()

    target = int(
        setting_get(
            conn,
            "activation_followers",
            "100000",
        )
    )

    ig = int(
        setting_get(
            conn,
            "instagram_followers",
            "0",
        )
    )

    yt = int(
        setting_get(
            conn,
            "youtube_followers",
            "0",
        )
    )

    tg = int(
        setting_get(
            conn,
            "telegram_followers",
            "0",
        )
    )

    active = all_networks_reached(conn)

    conn.close()

    return f"""
📊 وضعیت شبکه

Instagram:
{ig:,} / {target:,}

YouTube:
{yt:,} / {target:,}

Telegram:
{tg:,} / {target:,}

وضعیت:
{"🟢 فعال" if active else "🔴 هنوز به حدنصاب نرسیده"}
"""


def lottery_is_active():

    conn = db()

    active = all_networks_reached(conn)

    conn.close()

    return active


# =========================================================
# YOUTUBE API
# =========================================================

def fetch_youtube_subscribers():

    if not YOUTUBE_API_KEY:
        return None

    handle = YOUTUBE_HANDLE

    if handle.startswith("@"):
        handle = handle[1:]

    try:

        params = urlencode({
            "part": "statistics",
            "forHandle": handle,
            "key": YOUTUBE_API_KEY,
        })

        url = (
            "https://www.googleapis.com/youtube/v3/channels?"
            + params
        )

        request = Request(
            url,
            headers={
                "User-Agent": "MahfelShansBot/1.0"
            },
        )

        with urlopen(request, timeout=20) as response:

            data = json.loads(
                response.read().decode("utf-8")
            )

        items = data.get("items", [])

        if not items:
            return None

        count = items[0]["statistics"].get(
            "subscriberCount"
        )

        if count is None:
            return None

        return int(count)

    except Exception as e:

        logger.warning(
            "YouTube API error: %s",
            e,
        )

        return None


async def fetch_telegram_members(bot):

    try:

        return await bot.get_chat_member_count(
            TELEGRAM_CHANNEL
        )

    except Exception as e:

        logger.warning(
            "Telegram count error: %s",
            e,
        )

        return None


# =========================================================
# NETWORK UPDATE
# =========================================================

async def update_network_counts(bot):

    conn = db()

    yt = fetch_youtube_subscribers()

    if yt is not None:
        setting_set(
            conn,
            "youtube_followers",
            yt,
        )

    tg = await fetch_telegram_members(bot)

    if tg is not None:
        setting_set(
            conn,
            "telegram_followers",
            tg,
        )

    setting_set(
        conn,
        "network_last_update",
        datetime.utcnow().isoformat(),
    )

    if all_networks_reached(conn):
        setting_set(
            conn,
            "networks_activated",
            "1",
        )
    else:
        setting_set(
            conn,
            "networks_activated",
            "0",
        )

    conn.commit()
    conn.close()


async def network_loop(app):

    while True:

        try:

            await update_network_counts(
                app.bot
            )

        except Exception as e:

            logger.exception(
                "Network loop error: %s",
                e,
            )

        await asyncio.sleep(
            NETWORK_UPDATE_HOURS * 3600
        )


# =========================================================
# START
# =========================================================

async def start(update, context):

    user = update.effective_user

    referred_by = None

    if context.args:

        value = context.args[0]

        if value.startswith("ref_"):

            raw = value.replace(
                "ref_",
                "",
                1,
            )

            if raw.isdigit():

                ref_id = int(raw)

                if ref_id != user.id:
                    referred_by = ref_id

    is_new = create_user(
        user,
        referred_by,
    )

    if is_new and referred_by:

        conn = db()

        inviter = conn.execute(
            "SELECT id FROM users WHERE id=?",
            (referred_by,),
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
                        user.id,
                        datetime.utcnow().isoformat(),
                    ),
                )

                conn.execute(
                    """
                    UPDATE users
                    SET chances=chances+1
                    WHERE id=?
                    """,
                    (referred_by,),
                )

            except sqlite3.IntegrityError:
                pass

        conn.commit()
        conn.close()

    current = get_user(user.id)

    if not current:
        return

    if not current["accepted_rules"]:

        await update_or_send(
            update,
            """
🎉 به محفل خوش‌شانس‌ها خوش آمدید!

ثبت‌نام در محفل رایگان است.

برای ادامه، ابتدا قوانین را مطالعه و تأیید کنید:
            """,
            rules_keyboard(),
        )

        return

    await update_or_send(
        update,
        """
🍀 خوش آمدی به محفل خوش‌شانس‌ها

🎁 کمپین‌های رایگان
🏆 جوایز
👥 دعوت دوستان
📊 پیگیری شانس‌ها

از منوی زیر انتخاب کن:
        """,
        main_menu(),
    )


# =========================================================
# UPDATE MESSAGE
# =========================================================

async def update_or_send(
    update,
    text,
    keyboard=None,
):

    if update.callback_query:

        try:

            await update.callback_query.edit_message_text(
                text,
                reply_markup=keyboard,
            )

        except Exception:

            await update.callback_query.message.reply_text(
                text,
                reply_markup=keyboard,
            )

    else:

        await update.message.reply_text(
            text,
            reply_markup=keyboard,
        )


# =========================================================
# ACCEPT RULES
# =========================================================

async def accept_rules(update, context):

    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    version = current_rules_version()

    conn = db()

    conn.execute(
        """
        UPDATE users
        SET accepted_rules=1,
            rules_version=?
        WHERE id=?
        """,
        (
            version,
            user_id,
        ),
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
            version,
            datetime.utcnow().isoformat(),
        ),
    )

    conn.commit()
    conn.close()

    log_action(
        user_id,
        "accepted_rules",
    )

    await query.edit_message_text(
        """
✅ قوانین با موفقیت تأیید شد.

ثبت‌نام شما رایگان است و می‌توانید
در کمپین‌های فعال شرکت کنید.
        """,
        reply_markup=main_menu(),
    )


# =========================================================
# PROFILE
# =========================================================

async def show_profile(update, context):

    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    conn = db()

    user = conn.execute(
        "SELECT * FROM users WHERE id=?",
        (user_id,),
    ).fetchone()

    referrals = conn.execute(
        """
        SELECT COUNT(*) AS c
        FROM referrals
        WHERE inviter_id=?
        """,
        (user_id,),
    ).fetchone()["c"]

    participated = conn.execute(
        """
        SELECT COUNT(DISTINCT campaign_id) AS c
        FROM participations
        WHERE user_id=?
        """,
        (user_id,),
    ).fetchone()["c"]

    conn.close()

    if not user:
        return

    text = f"""
👤 پروفایل شما

🆔 شناسه: {user_id}

👤 نام: {user["first_name"] or "-"}

📅 ثبت‌نام:
{user["joined_at"][:10]}

🍀 شانس‌ها:
{user["chances"]:,}

👥 دعوت موفق:
{referrals:,}

🎁 کمپین‌های شرکت‌کرده:
{participated:,}
"""

    await query.edit_message_text(
        text,
        reply_markup=main_menu(),
    )


# =========================================================
# CHANCES
# =========================================================

async def show_chances(update, context):

    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    conn = db()

    user = conn.execute(
        "SELECT chances FROM users WHERE id=?",
        (user_id,),
    ).fetchone()

    conn.close()

    chances = user["chances"] if user else 0

    await query.edit_message_text(
        f"""
🍀 شانس‌های شما

تعداد شانس‌های فعلی:
🎟 {chances:,}

هر دعوت موفق یک شانس رایگان
برای شما ایجاد می‌کند.
        """,
        reply_markup=main_menu(),
    )


# =========================================================
# INVITE
# =========================================================

async def show_invite(update, context):

    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    link = (
        f"https://t.me/"
        f"{BOT_USERNAME}"
        f"?start=ref_{user_id}"
    )

    conn = db()

    count = conn.execute(
        """
        SELECT COUNT(*)
        FROM referrals
        WHERE inviter_id=?
        """,
        (user_id,),
    ).fetchone()[0]

    conn.close()

    await query.edit_message_text(
        f"""
👥 دعوت دوستان

لینک اختصاصی شما:

{link}

👤 دعوت موفق:
{count:,}

🍀 هر دعوت موفق = ۱ شانس رایگان

این لینک را برای دوستانت ارسال کن.
        """,
        reply_markup=main_menu(),
    )


# =========================================================
# CAMPAIGNS
# =========================================================

async def show_campaigns(update, context):

    query = update.callback_query
    await query.answer()

    if not lottery_is_active():

        await query.edit_message_text(
            f"""
🎁 کمپین‌های محفل

فعلاً سیستم قرعه‌کشی هنوز به
حدنصاب شبکه‌ها نرسیده است.

{network_status_text()}
            """,
            reply_markup=main_menu(),
        )

        return

    conn = db()

    campaigns = conn.execute(
        """
        SELECT *
        FROM campaigns
        WHERE status='active'
        ORDER BY id DESC
        """
    ).fetchall()

    conn.close()

    if not campaigns:

        await query.edit_message_text(
            """
🎁 در حال حاضر کمپین فعالی وجود ندارد.

به‌زودی کمپین‌های جدید اعلام می‌شوند.
            """,
            reply_markup=main_menu(),
        )

        return

    buttons = []

    for campaign in campaigns:

        buttons.append([
            InlineKeyboardButton(
                f"🎁 {campaign['title']}",
                callback_data=f"campaign_{campaign['id']}",
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "🔙 بازگشت",
            callback_data="home",
        )
    ])

    await query.edit_message_text(
        """
🎁 کمپین‌های فعال

یکی از کمپین‌ها را انتخاب کن:
        """,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# =========================================================
# CAMPAIGN DETAIL
# =========================================================

async def campaign_detail(update, context):

    query = update.callback_query
    await query.answer()

    campaign_id = int(
        query.data.split("_")[1]
    )

    user_id = query.from_user.id

    conn = db()

    campaign = conn.execute(
        """
        SELECT *
        FROM campaigns
        WHERE id=?
        """,
        (campaign_id,),
    ).fetchone()

    if not campaign:

        conn.close()

        await query.edit_message_text(
            "❌ کمپین پیدا نشد.",
            reply_markup=main_menu(),
        )

        return

    participant_count = conn.execute(
        """
        SELECT COUNT(DISTINCT user_id)
        FROM participations
        WHERE campaign_id=?
        """,
        (campaign_id,),
    ).fetchone()[0]

    already = conn.execute(
        """
        SELECT COUNT(*)
        FROM participations
        WHERE campaign_id=?
        AND user_id=?
        """,
        (
            campaign_id,
            user_id,
        ),
    ).fetchone()[0]

    conn.close()

    sponsor_text = ""

    if campaign["sponsor_name"]:

        sponsor_text = (
            f"\n🤝 اسپانسر: "
            f"{campaign['sponsor_name']}"
        )

    status = (
        "✅ شما در این کمپین شرکت کرده‌اید."
        if already
        else "👇 برای شرکت رایگان کلیک کنید."
    )

    keyboard = []

    if not already:

        keyboard.append([
            InlineKeyboardButton(
                "🎟 شرکت رایگان در کمپین",
                callback_data=(
                    f"join_{campaign_id}"
                ),
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "🔙 بازگشت",
            callback_data="campaigns",
        )
    ])

    text = f"""
🎁 {campaign["title"]}

{campaign["description"]}

🏆 جایزه:
{campaign["prize"]}

🎁 تعداد جوایز:
{campaign["prize_count"]}

👥 شرکت‌کنندگان:
{participant_count:,}

📅 تاریخ قرعه‌کشی:
{campaign["draw_date"] or "اعلام خواهد شد"}
{sponsor_text}

{status}
"""

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
    )


# =========================================================
# JOIN CAMPAIGN
# =========================================================

async def join_campaign(update, context):

    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    campaign_id = int(
        query.data.split("_")[1]
    )

    conn = db()

    user = conn.execute(
        """
        SELECT *
        FROM users
        WHERE id=?
        """,
        (user_id,),
    ).fetchone()

    campaign = conn.execute(
        """
        SELECT *
        FROM campaigns
        WHERE id=?
        AND status='active'
        """,
        (campaign_id,),
    ).fetchone()

    if not user or not campaign:

        conn.close()

        await query.answer(
            "کمپین در دسترس نیست.",
            show_alert=True,
        )

        return

    if not user["accepted_rules"]:

        conn.close()

        await query.answer(
            "ابتدا قوانین را تأیید کنید.",
            show_alert=True,
        )

        return

    exists = conn.execute(
        """
        SELECT COUNT(*)
        FROM participations
        WHERE campaign_id=?
        AND user_id=?
        """,
        (
            campaign_id,
            user_id,
        ),
    ).fetchone()[0]

    if exists:

        conn.close()

        await query.answer(
            "شما قبلاً در این کمپین شرکت کرده‌اید.",
            show_alert=True,
        )

        return

    chances = max(
        int(user["chances"]),
        1,
    )

    # ثبت تمام شانس‌های رایگان کاربر
    for chance in range(1, chances + 1):

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
                chance,
                datetime.utcnow().isoformat(),
            ),
        )

    conn.commit()
    conn.close()

    log_action(
        user_id,
        f"joined_campaign={campaign_id}",
    )

    await query.edit_message_text(
        f"""
✅ ثبت شد!

شما با {chances:,} شانس رایگان
در کمپین «{campaign["title"]}» شرکت کردید.

🏆 جایزه:
{campaign["prize"]}

📅 قرعه‌کشی:
{campaign["draw_date"] or "اعلام خواهد شد"}
        """,
        reply_markup=main_menu(),
    )


# =========================================================
# HISTORY
# =========================================================

async def show_history(update, context):

    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    conn = db()

    rows = conn.execute(
        """
        SELECT
            c.title,
            p.created_at
        FROM participations p
        JOIN campaigns c
        ON c.id=p.campaign_id
        WHERE p.user_id=?
        GROUP BY c.id
        ORDER BY p.created_at DESC
        LIMIT 20
        """,
        (user_id,),
    ).fetchall()

    conn.close()

    if not rows:

        text = """
📜 تاریخچه

هنوز در هیچ کمپینی شرکت نکرده‌اید.
"""

    else:

        text = "📜 تاریخچه شرکت شما\n\n"

        for row in rows:

            text += (
                f"🎁 {row['title']}\n"
                f"📅 {row['created_at'][:10]}\n\n"
            )

    await query.edit_message_text(
        text,
        reply_markup=main_menu(),
    )


# =========================================================
# WINNERS
# =========================================================

async def show_winners(update, context):

    query = update.callback_query
    await query.answer()

    conn = db()

    rows = conn.execute(
        """
        SELECT
            w.*,
            c.title,
            u.first_name,
            u.username
        FROM winners w
        JOIN campaigns c
        ON c.id=w.campaign_id
        JOIN users u
        ON u.id=w.user_id
        ORDER BY w.selected_at DESC
        LIMIT 30
        """
    ).fetchall()

    conn.close()

    if not rows:

        text = """
🏆 برندگان

هنوز برنده‌ای ثبت نشده است.
"""

    else:

        text = "🏆 آخرین برندگان\n\n"

        for row in rows:

            name = row["first_name"] or "کاربر"

            text += (
                f"🎁 {row['title']}\n"
                f"👤 {name}\n"
                f"🏆 {row['prize']}\n"
                f"📅 {row['selected_at'][:10]}\n\n"
            )

    await query.edit_message_text(
        text,
        reply_markup=main_menu(),
    )


# =========================================================
# ARCHIVE
# =========================================================

async def show_archive(update, context):

    query = update.callback_query
    await query.answer()

    conn = db()

    rows = conn.execute(
        """
        SELECT *
        FROM campaigns
        WHERE status='closed'
        ORDER BY id DESC
        LIMIT 20
        """
    ).fetchall()

    conn.close()

    if not rows:

        text = """
🗄 آرشیو

هنوز کمپین بسته‌شده‌ای وجود ندارد.
"""

    else:

        text = "🗄 آرشیو کمپین‌ها\n\n"

        for row in rows:

            text += (
                f"🎁 {row['title']}\n"
                f"🏆 {row['prize']}\n"
                f"📅 {row['draw_date'] or '-'}\n\n"
            )

    await query.edit_message_text(
        text,
        reply_markup=main_menu(),
    )


# =========================================================
# SUPPORT
# =========================================================

async def show_support(update, context):

    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        """
🎧 پشتیبانی

برای ارسال پیام به پشتیبانی،
پیام خود را همینجا ارسال کنید.

پیام شما برای تیم پشتیبانی ثبت خواهد شد.
        """,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 بازگشت",
                    callback_data="home",
                )
            ]
        ]),
    )

    context.user_data["waiting_support"] = True


async def receive_support(update, context):

    if not update.message:
        return

    user = update.effective_user

    if not context.user_data.get(
        "waiting_support"
    ):
        return

    message = update.message.text

    conn = db()

    cur = conn.execute(
        """
        INSERT INTO support_tickets(
            user_id,
            message,
            created_at
        )
        VALUES(?,?,?)
        """,
        (
            user.id,
            message,
            datetime.utcnow().isoformat(),
        ),
    )

    ticket_id = cur.lastrowid

    conn.commit()
    conn.close()

    context.user_data["waiting_support"] = False

    for admin_id in ADMIN_IDS:

        try:

            await context.bot.send_message(
                admin_id,
                f"""
🎧 تیکت جدید

شماره: #{ticket_id}

کاربر:
{user.first_name or "-"}

ID:
{user.id}

پیام:
{message}

برای پاسخ:
 /reply {ticket_id} متن پاسخ
                """,
            )

        except Exception:
            pass

    await update.message.reply_text(
        """
✅ پیام شما ثبت شد.

تیم پشتیبانی پس از بررسی پاسخ خواهد داد.
        """,
        reply_markup=main_menu(),
    )


# =========================================================
# RULES CALLBACK
# =========================================================

async def show_rules(update, context):

    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        rules_text(),
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
            ]
        ]),
    )


# =========================================================
# HOME
# =========================================================

async def home(update, context):

    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        """
🍀 محفل خوش‌شانس‌ها

🎁 کمپین‌های رایگان
🏆 جوایز
👥 دعوت دوستان
🤝 همکاری با برندها

انتخاب کن:
        """,
        reply_markup=main_menu(),
    )


# =========================================================
# ADMIN PANEL
# =========================================================

async def admin_panel(update, context):

    if not await admin_required(update):
        return

    await update.message.reply_text(
        """
🛠 پنل مدیریت محفل

📊 آمار:
/stats

📈 وضعیت شبکه:
/network

📸 تعداد اینستاگرام:
/igfollowers 100000

▶️ تعداد یوتیوب:
/ytfollowers 100000

📢 تعداد تلگرام:
/tgfollowers 100000

🎯 حدنصاب:
/activation 100000

👥 سقف برنامه:
/maxfollowers 1000000

💰 بودجه اسپانسر:
/sponsorbudget 500000000

🎁 جایزه:
/dailyprize 10000000

📋 قوانین:
/rulesadmin 1.1

➕ ساخت کمپین:
/newcampaign

🤝 افزودن اسپانسر:
/newsponsor

🎲 قرعه‌کشی:
/draw CAMPAIGN_ID

🏆 اعلام برنده:
/announce CAMPAIGN_ID

📣 ارسال پیام:
/broadcast متن

📋 کاربران:
/users

🎫 تعداد شرکت‌کنندگان:
/participants CAMPAIGN_ID

🎧 تیکت‌ها:
/tickets

📜 لاگ:
/logs
        """
    )


# =========================================================
# ADMIN STATS
# =========================================================

async def stats(update, context):

    if not await admin_required(update):
        return

    conn = db()

    users = conn.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]

    referrals = conn.execute(
        "SELECT COUNT(*) FROM referrals"
    ).fetchone()[0]

    campaigns = conn.execute(
        "SELECT COUNT(*) FROM campaigns"
    ).fetchone()[0]

    active_campaigns = conn.execute(
        """
        SELECT COUNT(*)
        FROM campaigns
        WHERE status='active'
        """
    ).fetchone()[0]

    participants = conn.execute(
        "SELECT COUNT(*) FROM participations"
    ).fetchone()[0]

    sponsors = conn.execute(
        "SELECT COUNT(*) FROM sponsors"
    ).fetchone()[0]

    conn.close()

    await update.message.reply_text(
        f"""
📊 آمار محفل

👥 کاربران:
{users:,}

👥 دعوت‌های موفق:
{referrals:,}

🎁 کل کمپین‌ها:
{campaigns:,}

🟢 کمپین‌های فعال:
{active_campaigns:,}

🎟 رکوردهای شرکت:
{participants:,}

🤝 اسپانسرها:
{sponsors:,}
        """
    )


# =========================================================
# NETWORK ADMIN
# =========================================================

async def network(update, context):

    if not await admin_required(update):
        return

    await update.message.reply_text(
        network_status_text()
    )


async def set_instagram_followers(
    update,
    context,
):

    if not await admin_required(update):
        return

    if not context.args:

        await update.message.reply_text(
            "مثال:\n/igfollowers 100000"
        )

        return

    try:

        count = int(
            context.args[0].replace(",", "")
        )

        if count < 0:
            raise ValueError

    except Exception:

        await update.message.reply_text(
            "❌ عدد صحیح وارد کن."
        )

        return

    conn = db()

    setting_set(
        conn,
        "instagram_followers",
        count,
    )

    if not all_networks_reached(conn):

        setting_set(
            conn,
            "networks_activated",
            0,
        )

    conn.commit()
    conn.close()

    log_action(
        update.effective_user.id,
        f"instagram_followers={count}",
    )

    await update.message.reply_text(
        f"""
✅ Instagram روی {count:,} تنظیم شد.

{network_status_text()}
        """
    )


async def set_youtube_followers(
    update,
    context,
):

    if not await admin_required(update):
        return

    if not context.args:

        await update.message.reply_text(
            "مثال:\n/ytfollowers 100000"
        )

        return

    try:

        count = int(
            context.args[0].replace(",", "")
        )

        if count < 0:
            raise ValueError

    except Exception:

        await update.message.reply_text(
            "❌ عدد صحیح وارد کن."
        )

        return

    conn = db()

    setting_set(
        conn,
        "youtube_followers",
        count,
    )

    if not all_networks_reached(conn):

        setting_set(
            conn,
            "networks_activated",
            0,
        )

    conn.commit()
    conn.close()

    log_action(
        update.effective_user.id,
        f"youtube_followers={count}",
    )

    await update.message.reply_text(
        f"""
✅ YouTube روی {count:,} تنظیم شد.

{network_status_text()}
        """
    )


async def set_telegram_followers(
    update,
    context,
):

    if not await admin_required(update):
        return

    if not context.args:

        await update.message.reply_text(
            "مثال:\n/tgfollowers 100000"
        )

        return

    try:

        count = int(
            context.args[0].replace(",", "")
        )

        if count < 0:
            raise ValueError

    except Exception:

        await update.message.reply_text(
            "❌ عدد صحیح وارد کن."
        )

        return

    conn = db()

    setting_set(
        conn,
        "telegram_followers",
        count,
    )

    if not all_networks_reached(conn):

        setting_set(
            conn,
            "networks_activated",
            0,
        )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"""
✅ Telegram روی {count:,} تنظیم شد.

{network_status_text()}
        """
    )


async def activation(update, context):

    if not await admin_required(update):
        return

    if not context.args:

        await update.message.reply_text(
            "مثال:\n/activation 100000"
        )

        return

    try:
        count = int(context.args[0])
    except:
        await update.message.reply_text(
            "❌ عدد صحیح وارد کن."
        )
        return

    conn = db()

    setting_set(
        conn,
        "activation_followers",
        count,
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        network_status_text()
    )


async def maxfollowers(update, context):

    if not await admin_required(update):
        return

    if not context.args:
        await update.message.reply_text(
            "مثال:\n/maxfollowers 1000000"
        )
        return

    try:
        count = int(context.args[0])
    except:
        await update.message.reply_text(
            "❌ عدد صحیح."
        )
        return

    conn = db()

    setting_set(
        conn,
        "plan_max_followers",
        count,
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ سقف برنامه روی {count:,} تنظیم شد."
    )


# =========================================================
# SPONSOR ADMIN
# =========================================================

async def new_sponsor(update, context):

    if not await admin_required(update):
        return

    if len(context.args) < 2:

        await update.message.reply_text(
            """
مثال:

/newsponsor شرکت ایرانسل 500000000
            """
        )

        return

    name = context.args[0]

    try:
        budget = int(
            context.args[1].replace(",", "")
        )
    except:
        await update.message.reply_text(
            "❌ بودجه باید عدد باشد."
        )
        return

    conn = db()

    conn.execute(
        """
        INSERT INTO sponsors(
            name,
            budget,
            created_at
        )
        VALUES(?,?,?)
        """,
        (
            name,
            budget,
            datetime.utcnow().isoformat(),
        ),
    )

    total = int(
        setting_get(
            conn,
            "total_sponsor_budget",
            "0",
        )
    )

    setting_set(
        conn,
        "total_sponsor_budget",
        total + budget,
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"""
✅ اسپانسر ثبت شد.

🤝 {name}
💰 بودجه: {budget:,} تومان
        """
    )


async def sponsor_budget(update, context):

    if not await admin_required(update):
        return

    if not context.args:

        await update.message.reply_text(
            "مثال:\n/sponsorbudget 500000000"
        )

        return

    try:
        amount = int(
            context.args[0].replace(",", "")
        )
    except:
        await update.message.reply_text(
            "❌ عدد صحیح."
        )
        return

    conn = db()

    setting_set(
        conn,
        "total_sponsor_budget",
        amount,
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"🤝 بودجه اسپانسرها: {amount:,} تومان"
    )


# =========================================================
# CAMPAIGN CREATION
# =========================================================

async def new_campaign(update, context):

    if not await admin_required(update):
        return

    if len(context.args) < 4:

        await update.message.reply_text(
            """
ساخت کمپین:

/newcampaign عنوان | توضیح | جایزه | تاریخ

مثال:

/newcampaign
قرعه‌کشی شهریور |
۱۰ جایزه برای کاربران |
هر جایزه ۱۰ میلیون تومان |
1405/07/01
            """
        )

        return

    raw = " ".join(context.args)

    parts = [
        x.strip()
        for x in raw.split("|")
    ]

    if len(parts) < 4:

        await update.message.reply_text(
            "❌ اطلاعات را با | جدا کن."
        )

        return

    title = parts[0]
    description = parts[1]
    prize = parts[2]
    draw_date = parts[3]

    conn = db()

    conn.execute(
        """
        INSERT INTO campaigns(
            title,
            description,
            prize,
            prize_count,
            draw_date,
            status,
            created_at
        )
        VALUES(?,?,?,?,?,?,?)
        """,
        (
            title,
            description,
            prize,
            1,
            draw_date,
            "active",
            datetime.utcnow().isoformat(),
        ),
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"""
✅ کمپین ساخته شد.

🎁 {title}
🏆 {prize}
📅 {draw_date}
        """
    )


# =========================================================
# DAILY PRIZE
# =========================================================

async def daily_prize(update, context):

    if not await admin_required(update):
        return

    if not context.args:

        await update.message.reply_text(
            "مثال:\n/dailyprize 10000000"
        )

        return

    try:
        amount = int(
            context.args[0].replace(",", "")
        )
    except:
        await update.message.reply_text(
            "❌ عدد صحیح."
        )
        return

    conn = db()

    setting_set(
        conn,
        "daily_prize_amount",
        amount,
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"🎁 مبلغ پایه جایزه: {amount:,} تومان"
    )


# =========================================================
# RULE ADMIN
# =========================================================

async def rules_admin(update, context):

    if not await admin_required(update):
        return

    if not context.args:

        await update.message.reply_text(
            f"نسخه فعلی: {current_rules_version()}"
        )

        return

    version = context.args[0]

    conn = db()

    setting_set(
        conn,
        "rules_version",
        version,
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ نسخه قوانین شد: {version}"
    )


# =========================================================
# DRAW
# =========================================================

async def draw_campaign(update, context):

    if not await admin_required(update):
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
    except:

        await update.message.reply_text(
            "❌ شناسه کمپین اشتباه است."
        )

        return

    conn = db()

    campaign = conn.execute(
        """
        SELECT *
        FROM campaigns
        WHERE id=?
        """,
        (campaign_id,),
    ).fetchone()

    if not campaign:

        conn.close()

        await update.message.reply_text(
            "❌ کمپین پیدا نشد."
        )

        return

    rows = conn.execute(
        """
        SELECT
            p.user_id,
            p.chance_number
        FROM participations p
        WHERE p.campaign_id=?
        """,
        (campaign_id,),
    ).fetchall()

    if not rows:

        conn.close()

        await update.message.reply_text(
            "❌ هیچ شرکت‌کننده‌ای وجود ندارد."
        )

        return

    # وزن‌دهی بر اساس شانس‌های رایگان
    tickets = []

    for row in rows:

        tickets.append(
            row["user_id"]
        )

    winner_id = random.choice(
        tickets
    )

    conn.execute(
        """
        INSERT INTO winners(
            campaign_id,
            user_id,
            prize,
            selected_at
        )
        VALUES(?,?,?,?)
        """,
        (
            campaign_id,
            winner_id,
            campaign["prize"],
            datetime.utcnow().isoformat(),
        ),
    )

    conn.execute(
        """
        UPDATE campaigns
        SET status='closed'
        WHERE id=?
        """,
        (campaign_id,),
    )

    conn.commit()
    conn.close()

    log_action(
        update.effective_user.id,
        f"draw_campaign={campaign_id};winner={winner_id}",
    )

    await update.message.reply_text(
        f"""
🎲 قرعه‌کشی انجام شد.

🎁 کمپین:
{campaign["title"]}

🏆 جایزه:
{campaign["prize"]}

👤 شناسه برنده:
{winner_id}

برای اعلام عمومی:
 /announce {campaign_id}
        """
    )


# =========================================================
# ANNOUNCE WINNER
# =========================================================

async def announce_winner(update, context):

    if not await admin_required(update):
        return

    if not context.args:

        await update.message.reply_text(
            "مثال:\n/announce 1"
        )

        return

    try:
        campaign_id = int(
            context.args[0]
        )
    except:

        await update.message.reply_text(
            "❌ شناسه اشتباه."
        )

        return

    conn = db()

    row = conn.execute(
        """
        SELECT
            w.*,
            c.title,
            c.prize,
            u.first_name,
            u.username
        FROM winners w
        JOIN campaigns c
        ON c.id=w.campaign_id
        JOIN users u
        ON u.id=w.user_id
        WHERE w.campaign_id=?
        ORDER BY w.id DESC
        LIMIT 1
        """,
        (campaign_id,),
    ).fetchone()

    if not row:

        conn.close()

        await update.message.reply_text(
            "❌ برنده پیدا نشد."
        )

        return

    conn.execute(
        """
        UPDATE winners
        SET announced=1
        WHERE id=?
        """,
        (row["id"],),
    )

    conn.commit()
    conn.close()

    name = row["first_name"] or "کاربر"

    message = f"""
🏆 برنده محفل خوش‌شانس‌ها

🎁 کمپین:
{row["title"]}

🏆 جایزه:
{row["prize"]}

👤 برنده:
{name}

🎉 تبریک به برنده!

🤝 با حمایت اسپانسرهای محفل
"""

    await update.message.reply_text(
        message
    )

    try:

        await context.bot.send_message(
            TELEGRAM_CHANNEL,
            message,
        )

    except Exception as e:

        logger.warning(
            "Channel announce error: %s",
            e,
        )


# =========================================================
# USERS
# =========================================================

async def users_admin(update, context):

    if not await admin_required(update):
        return

    conn = db()

    rows = conn.execute(
        """
        SELECT *
        FROM users
        ORDER BY joined_at DESC
        LIMIT 20
        """
    ).fetchall()

    conn.close()

    if not rows:

        await update.message.reply_text(
            "کاربری وجود ندارد."
        )

        return

    text = "👥 آخرین کاربران\n\n"

    for row in rows:

        text += (
            f"ID: {row['id']}\n"
            f"نام: {row['first_name'] or '-'}\n"
            f"شانس: {row['chances']}\n"
            f"تاریخ: {row['joined_at'][:10]}\n\n"
        )

    await update.message.reply_text(
        text
    )


# =========================================================
# PARTICIPANTS
# =========================================================

async def participants_admin(update, context):

    if not await admin_required(update):
        return

    if not context.args:

        await update.message.reply_text(
            "مثال:\n/participants 1"
        )

        return

    try:
        campaign_id = int(
            context.args[0]
        )
    except:

        await update.message.reply_text(
            "❌ شناسه اشتباه."
        )

        return

    conn = db()

    total_tickets = conn.execute(
        """
        SELECT COUNT(*)
        FROM participations
        WHERE campaign_id=?
        """,
        (campaign_id,),
    ).fetchone()[0]

    users = conn.execute(
        """
        SELECT COUNT(DISTINCT user_id)
        FROM participations
        WHERE campaign_id=?
        """,
        (campaign_id,),
    ).fetchone()[0]

    conn.close()

    await update.message.reply_text(
        f"""
🎟 آمار کمپین

کمپین: {campaign_id}

👥 کاربران:
{users:,}

🎟 کل شانس‌ها:
{total_tickets:,}
        """
    )


# =========================================================
# SUPPORT ADMIN
# =========================================================

async def tickets_admin(update, context):

    if not await admin_required(update):
        return

    conn = db()

    rows = conn.execute(
        """
        SELECT *
        FROM support_tickets
        WHERE status='open'
        ORDER BY id DESC
        LIMIT 20
        """
    ).fetchall()

    conn.close()

    if not rows:

        await update.message.reply_text(
            "🎧 تیکت باز وجود ندارد."
        )

        return

    text = "🎧 تیکت‌های باز\n\n"

    for row in rows:

        text += (
            f"#{row['id']}\n"
            f"User: {row['user_id']}\n"
            f"{row['message']}\n\n"
        )

    await update.message.reply_text(
        text
    )


async def reply_ticket(update, context):

    if not await admin_required(update):
        return

    if len(context.args) < 2:

        await update.message.reply_text(
            "مثال:\n/reply 12 پاسخ شما"
        )

        return

    try:

        ticket_id = int(
            context.args[0]
        )

    except:

        await update.message.reply_text(
            "❌ شماره تیکت اشتباه."
        )

        return

    answer = " ".join(
        context.args[1:]
    )

    conn = db()

    ticket = conn.execute(
        """
        SELECT *
        FROM support_tickets
        WHERE id=?
        """,
        (ticket_id,),
    ).fetchone()

    if not ticket:

        conn.close()

        await update.message.reply_text(
            "❌ تیکت پیدا نشد."
        )

        return

    conn.execute(
        """
        UPDATE support_tickets
        SET answer=?,
            status='answered',
            answered_at=?
        WHERE id=?
        """,
        (
            answer,
            datetime.utcnow().isoformat(),
            ticket_id,
        ),
    )

    conn.commit()
    conn.close()

    try:

        await context.bot.send_message(
            ticket["user_id"],
            f"""
🎧 پاسخ پشتیبانی

تیکت #{ticket_id}

{answer}
            """,
        )

    except:
        pass

    await update.message.reply_text(
        "✅ پاسخ ارسال شد."
    )


# =========================================================
# BROADCAST
# =========================================================

async def broadcast(update, context):

    if not await admin_required(update):
        return

    if not context.args:

        await update.message.reply_text(
            "مثال:\n/broadcast متن پیام"
        )

        return

    message = " ".join(
        context.args
    )

    conn = db()

    rows = conn.execute(
        """
        SELECT id
        FROM users
        WHERE is_active=1
        """
    ).fetchall()

    conn.close()

    sent = 0

    for row in rows:

        try:

            await context.bot.send_message(
                row["id"],
                message,
            )

            sent += 1

            await asyncio.sleep(
                0.05
            )

        except:
            pass

    await update.message.reply_text(
        f"📣 ارسال انجام شد.\n\nموفق: {sent:,}"
    )


# =========================================================
# LOGS
# =========================================================

async def logs_admin(update, context):

    if not await admin_required(update):
        return

    conn = db()

    rows = conn.execute(
        """
        SELECT *
        FROM operation_logs
        ORDER BY id DESC
        LIMIT 30
        """
    ).fetchall()

    conn.close()

    if not rows:

        await update.message.reply_text(
            "لاگی وجود ندارد."
        )

        return

    text = "📜 آخرین عملیات\n\n"

    for row in rows:

        text += (
            f"{row['created_at']}\n"
            f"User: {row['user_id']}\n"
            f"{row['action']}\n\n"
        )

    await update.message.reply_text(
        text
    )


# =========================================================
# HELP
# =========================================================

async def help_command(update, context):

    await update.message.reply_text(
        """
🍀 محفل خوش‌شانس‌ها

ثبت‌نام و شرکت در کمپین‌ها رایگان است.

از /start شروع کنید.

در صورت نیاز از بخش 🎧 پشتیبانی استفاده کنید.
        """,
        reply_markup=main_menu(),
    )


# =========================================================
# CALLBACK ROUTER
# =========================================================

async def callback_router(update, context):

    query = update.callback_query

    data = query.data

    if data == "home":
        await home(update, context)

    elif data == "accept_rules":
        await accept_rules(update, context)

    elif data == "campaigns":
        await show_campaigns(update, context)

    elif data.startswith("campaign_"):
        await campaign_detail(update, context)

    elif data.startswith("join_"):
        await join_campaign(update, context)

    elif data == "profile":
        await show_profile(update, context)

    elif data == "chances":
        await show_chances(update, context)

    elif data == "invite":
        await show_invite(update, context)

    elif data == "history":
        await show_history(update, context)

    elif data == "winners":
        await show_winners(update, context)

    elif data == "archive":
        await show_archive(update, context)

    elif data == "rules":
        await show_rules(update, context)

    elif data == "support":
        await show_support(update, context)


# =========================================================
# ERROR
# =========================================================

async def error_handler(update, context):

    logger.error(
        "Unhandled error: %s",
        context.error,
    )


# =========================================================
# MAIN
# =========================================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN environment variable is missing."
        )

    init_db()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # -------------------------
    # USER
    # -------------------------

    application.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_command,
        )
    )

    # -------------------------
    # ADMIN
    # -------------------------

    application.add_handler(
        CommandHandler(
            "admin",
            admin_panel,
        )
    )

    application.add_handler(
        CommandHandler(
            "stats",
            stats,
        )
    )

    application.add_handler(
        CommandHandler(
            "network",
            network,
        )
    )

    application.add_handler(
        CommandHandler(
            "igfollowers",
            set_instagram_followers,
        )
    )

    application.add_handler(
        CommandHandler(
            "ytfollowers",
            set_youtube_followers,
        )
    )

    application.add_handler(
        CommandHandler(
            "tgfollowers",
            set_telegram_followers,
        )
    )

    application.add_handler(
        CommandHandler(
            "activation",
            activation,
        )
    )

    application.add_handler(
        CommandHandler(
            "maxfollowers",
            maxfollowers,
        )
    )

    application.add_handler(
        CommandHandler(
            "dailyprize",
            daily_prize,
        )
    )

    application.add_handler(
        CommandHandler(
            "newcampaign",
            new_campaign,
        )
    )

    application.add_handler(
        CommandHandler(
            "newsponsor",
            new_sponsor,
        )
    )

    application.add_handler(
        CommandHandler(
            "sponsorbudget",
            sponsor_budget,
        )
    )

    application.add_handler(
        CommandHandler(
            "draw",
            draw_campaign,
        )
    )

    application.add_handler(
        CommandHandler(
            "announce",
            announce_winner,
        )
    )

    application.add_handler(
        CommandHandler(
            "rulesadmin",
            rules_admin,
        )
    )

    application.add_handler(
        CommandHandler(
            "users",
            users_admin,
        )
    )

    application.add_handler(
        CommandHandler(
            "participants",
            participants_admin,
        )
    )

    application.add_handler(
        CommandHandler(
            "tickets",
            tickets_admin,
        )
    )

    application.add_handler(
        CommandHandler(
            "reply",
            reply_ticket,
        )
    )

    application.add_handler(
        CommandHandler(
            "broadcast",
            broadcast,
        )
    )

    application.add_handler(
        CommandHandler(
            "logs",
            logs_admin,
        )
    )

    # -------------------------
    # CALLBACKS
    # -------------------------

    application.add_handler(
        CallbackQueryHandler(
            callback_router
        )
    )

    # -------------------------
    # SUPPORT TEXT
    # -------------------------

    application.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            receive_support,
        )
    )

    application.add_error_handler(
        error_handler
    )

    # -------------------------
    # NETWORK TASK
    # -------------------------

    async def post_init(app):

        asyncio.create_task(
            network_loop(app)
        )

    application.post_init = post_init

    # -------------------------
    # RENDER WEBHOOK
    # -------------------------

    if RENDER_EXTERNAL_URL:

        webhook_url = (
            RENDER_EXTERNAL_URL.rstrip("/")
            + "/"
            + BOT_TOKEN
        )

        logger.info(
            "Starting webhook: %s",
            webhook_url,
        )

        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=webhook_url,
            drop_pending_updates=True,
        )

    else:

        logger.info(
            "Starting polling mode..."
        )

        application.run_polling(
            drop_pending_updates=True
        )


if __name__ == "__main__":
    main()
