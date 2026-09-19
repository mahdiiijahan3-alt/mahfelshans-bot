import os
import sqlite3
import logging
import asyncio
import json
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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

BOT_USERNAME = "MahfelShansBot"

DB_FILE = "mahfelshans.db"

INSTAGRAM_URL = "https://instagram.com/MAHFELSHANS"
YOUTUBE_URL = "https://youtube.com/@mahfelshans"
TELEGRAM_CHANNEL_URL = "https://t.me/MahfelShans"

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
# DATABASE
# =========================================================

def db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def setting_get(conn, key, default=None):
    row = conn.execute(
        "SELECT value FROM settings WHERE key=?",
        (key,)
    ).fetchone()

    if row is None:
        return default

    return row["value"]


def setting_set(conn, key, value):
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


def setting_int(conn, key, default=0):
    value = setting_get(conn, key, default)

    try:
        return int(value)
    except Exception:
        return default


def column_exists(conn, table, column):
    rows = conn.execute(
        f"PRAGMA table_info({table})"
    ).fetchall()

    return any(row["name"] == column for row in rows)


def add_column_if_missing(conn, table, column, definition):
    if not column_exists(conn, table, column):
        conn.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )


def init_db():

    conn = db()

    # ---------------- USERS ----------------

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            first_name TEXT,
            username TEXT,
            chances INTEGER DEFAULT 0,
            invited_by INTEGER,
            created_at TEXT
        )
        """
    )

    add_column_if_missing(
        conn,
        "users",
        "support_mode",
        "INTEGER DEFAULT 0"
    )

    # ---------------- REFERRALS ----------------

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER NOT NULL,
            referred_id INTEGER NOT NULL UNIQUE,
            created_at TEXT
        )
        """
    )

    # ---------------- CAMPAIGNS ----------------

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            description TEXT,
            prize TEXT,
            active INTEGER DEFAULT 0,
            created_at TEXT
        )
        """
    )

    add_column_if_missing(
        conn,
        "campaigns",
        "rules",
        "TEXT DEFAULT ''"
    )

    add_column_if_missing(
        conn,
        "campaigns",
        "rules_version",
        "INTEGER DEFAULT 1"
    )

    add_column_if_missing(
        conn,
        "campaigns",
        "draw_at",
        "TEXT"
    )

    add_column_if_missing(
        conn,
        "campaigns",
        "archived",
        "INTEGER DEFAULT 0"
    )

    add_column_if_missing(
        conn,
        "campaigns",
        "prize_amount",
        "INTEGER DEFAULT 0"
    )

    # ---------------- PARTICIPATIONS ----------------

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS participations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER,
            user_id INTEGER,
            chances_used INTEGER DEFAULT 1,
            created_at TEXT,
            UNIQUE(campaign_id, user_id)
        )
        """
    )

    # ---------------- RULE ACCEPTANCES ----------------

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rule_acceptances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            campaign_id INTEGER,
            rules_version INTEGER,
            accepted INTEGER DEFAULT 0,
            accepted_at TEXT,
            UNIQUE(user_id, campaign_id)
        )
        """
    )

    # ---------------- WINNERS ----------------

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS winners (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER,
            user_id INTEGER,
            announced INTEGER DEFAULT 0,
            announced_at TEXT,
            created_at TEXT,
            UNIQUE(campaign_id)
        )
        """
    )

    # ---------------- SUPPORT ----------------

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            message TEXT,
            status TEXT DEFAULT 'open',
            admin_reply TEXT,
            created_at TEXT,
            replied_at TEXT
        )
        """
    )

    # ---------------- PAYMENTS ----------------

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            campaign_id INTEGER,
            amount INTEGER,
            gateway TEXT,
            transaction_code TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            paid_at TEXT
        )
        """
    )

    # ---------------- SETTINGS ----------------

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )

    # ---------------- LOGS ----------------

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS operation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER,
            action TEXT,
            created_at TEXT
        )
        """
    )

    defaults = {
        "followers": "0",
        "activation_followers": "100000",
        "plan_max_followers": "500000",
        "daily_prize_amount": "10000000",
        "payment_enabled": "0",
        "rules_version": "1",

        # NETWORK SETTINGS
        "instagram_followers": os.environ.get(
            "INSTAGRAM_FOLLOWERS",
            "0"
        ),
        "youtube_followers": "0",
        "telegram_followers": "0",
        "networks_activated": "0",
        "network_last_update": "",
    }

    default_rules = (
        "۱. شرکت در مسابقات طبق قوانین اعلام‌شده انجام می‌شود.\n"
        "۲. هر کاربر مسئول اطلاعات حساب خود است.\n"
        "۳. هر معرفی موفق یک شانس اضافه ایجاد می‌کند.\n"
        "۴. اعلام برندگان پس از قرعه‌کشی انجام خواهد شد.\n"
        "۵. قوانین هر کمپین ممکن است شرایط اختصاصی داشته باشد."
    )

    for key, value in defaults.items():

        exists = conn.execute(
            "SELECT 1 FROM settings WHERE key=?",
            (key,)
        ).fetchone()

        if not exists:
            conn.execute(
                "INSERT INTO settings(key,value) VALUES(?,?)",
                (key, str(value))
            )

    if not setting_get(conn, "rules_text"):
        setting_set(conn, "rules_text", default_rules)

    campaign_count = conn.execute(
        "SELECT COUNT(*) AS c FROM campaigns"
    ).fetchone()["c"]

    if campaign_count == 0:

        conn.execute(
            """
            INSERT INTO campaigns
            (
                title,
                description,
                prize,
                active,
                created_at,
                rules,
                rules_version,
                archived,
                prize_amount
            )
            VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                "اولین کمپین محفل خوش شانس ها",
                "کمپین به زودی فعال می‌شود.",
                "جایزه ویژه",
                0,
                datetime.utcnow().isoformat(),
                default_rules,
                1,
                0,
                0
            )
        )

    conn.commit()
    conn.close()


# =========================================================
# ADMIN
# =========================================================

def get_admin_ids():

    raw = os.environ.get("ADMIN_IDS", "")

    result = []

    for x in raw.split(","):

        x = x.strip()

        if not x:
            continue

        try:
            result.append(int(x))
        except Exception:
            pass

    return result


def is_admin(user_id):
    return user_id in get_admin_ids()


def log_action(admin_id, action):

    conn = db()

    conn.execute(
        """
        INSERT INTO operation_logs(admin_id, action, created_at)
        VALUES(?,?,?)
        """,
        (
            admin_id,
            action,
            datetime.utcnow().isoformat()
        )
    )

    conn.commit()
    conn.close()


async def admin_required(update):

    user = update.effective_user

    if not user or not is_admin(user.id):

        await update.message.reply_text(
            "⛔ این بخش فقط برای مدیریت ربات است."
        )

        return False

    return True


# =========================================================
# NETWORK API
# =========================================================

def fetch_youtube_subscribers_sync():

    api_key = os.environ.get("YOUTUBE_API_KEY")

    if not api_key:
        logger.warning(
            "YOUTUBE_API_KEY is not configured."
        )
        return None

    handle = os.environ.get(
        "YOUTUBE_HANDLE",
        DEFAULT_YOUTUBE_HANDLE
    )

    params = urlencode({
        "part": "statistics",
        "forHandle": handle,
        "key": api_key,
    })

    url = (
        "https://www.googleapis.com/youtube/v3/channels?"
        + params
    )

    try:

        request = Request(
            url,
            headers={
                "User-Agent": "MahfelShansBot/1.0"
            }
        )

        with urlopen(request, timeout=20) as response:

            data = json.loads(
                response.read().decode("utf-8")
            )

        items = data.get("items", [])

        if not items:

            logger.error(
                "YouTube channel not found: %s",
                handle
            )

            return None

        statistics = items[0].get(
            "statistics",
            {}
        )

        subscribers = statistics.get(
            "subscriberCount"
        )

        if subscribers is None:
            return None

        return int(subscribers)

    except Exception as e:

        logger.exception(
            "YouTube API error: %s",
            e
        )

        return None


async def fetch_youtube_subscribers():

    return await asyncio.to_thread(
        fetch_youtube_subscribers_sync
    )


async def fetch_telegram_members(bot):

    channel = os.environ.get(
        "TELEGRAM_CHANNEL",
        DEFAULT_TELEGRAM_CHANNEL
    )

    try:

        count = await bot.get_chat_member_count(
            channel
        )

        return int(count)

    except Exception as e:

        logger.exception(
            "Telegram member count error: %s",
            e
        )

        return None


def get_instagram_followers():

    conn = db()

    value = setting_int(
        conn,
        "instagram_followers",
        0
    )

    conn.close()

    return value


# =========================================================
# NETWORK STATUS
# =========================================================

def get_network_counts():

    conn = db()

    instagram = setting_int(
        conn,
        "instagram_followers",
        0
    )

    youtube = setting_int(
        conn,
        "youtube_followers",
        0
    )

    telegram = setting_int(
        conn,
        "telegram_followers",
        0
    )

    target = setting_int(
        conn,
        "activation_followers",
        100000
    )

    activated = setting_int(
        conn,
        "networks_activated",
        0
    )

    last_update = setting_get(
        conn,
        "network_last_update",
        ""
    )

    conn.close()

    return {
        "instagram": instagram,
        "youtube": youtube,
        "telegram": telegram,
        "target": target,
        "activated": activated,
        "last_update": last_update,
    }


def network_status_text():

    data = get_network_counts()

    target = data["target"]

    ig = data["instagram"]
    yt = data["youtube"]
    tg = data["telegram"]

    def line(name, count):

        if count <= 0:

            return (
                f"{name}: دریافت نشده ⏳\n"
                f"هدف: {target:,}"
            )

        if count >= target:

            return (
                f"{name}: {count:,} / "
                f"{target:,} ✅\n"
                f"هدف تکمیل شد"
            )

        remaining = target - count

        return (
            f"{name}: {count:,} / "
            f"{target:,}\n"
            f"باقی‌مانده: {remaining:,}"
        )

    text = (
        "📊 وضعیت رشد محفل خوش شانس ها\n\n"
        f"📸 Instagram\n"
        f"{line('Instagram', ig)}\n\n"
        f"▶️ YouTube\n"
        f"{line('YouTube', yt)}\n\n"
        f"📢 Telegram\n"
        f"{line('Telegram', tg)}\n\n"
    )

    if (
        ig >= target
        and yt >= target
        and tg >= target
    ):

        text += (
            "🎉 هر سه شبکه به ۱۰۰,۰۰۰ رسیده‌اند.\n"
            "🔥 کمپین‌ها فعال هستند."
        )

    else:

        text += (
            "🔒 قرعه‌کشی هنوز فعال نشده است.\n"
            "هر سه شبکه باید جداگانه به "
            f"{target:,} نفر برسند."
        )

    if data["last_update"]:

        text += (
            "\n\n🕐 آخرین بررسی: "
            + data["last_update"]
        )

    return text


def all_networks_reached(conn):

    target = setting_int(
        conn,
        "activation_followers",
        100000
    )

    instagram = setting_int(
        conn,
        "instagram_followers",
        0
    )

    youtube = setting_int(
        conn,
        "youtube_followers",
        0
    )

    telegram = setting_int(
        conn,
        "telegram_followers",
        0
    )

    return (
        instagram >= target
        and youtube >= target
        and telegram >= target
    )


async def activate_all_campaigns(bot):

    conn = db()

    already = setting_int(
        conn,
        "networks_activated",
        0
    )

    if not all_networks_reached(conn):

        conn.close()
        return False

    if already == 1:

        conn.close()
        return False

    conn.execute(
        """
        UPDATE campaigns
        SET active=1
        WHERE archived=0
        """
    )

    setting_set(
        conn,
        "networks_activated",
        1
    )

    conn.commit()
    conn.close()

    channel = os.environ.get(
        "TELEGRAM_CHANNEL",
        DEFAULT_TELEGRAM_CHANNEL
    )

    message = (
        "🎉🎉🎉 خبر بزرگ محفل خوش شانس ها 🎉🎉🎉\n\n"
        "📸 Instagram: 100,000 ✅\n"
        "▶️ YouTube: 100,000 ✅\n"
        "📢 Telegram: 100,000 ✅\n\n"
        "🔥 هر سه شبکه به حد نصاب رسیدند.\n"
        "🎁 کمپین‌ها و قرعه‌کشی‌های محفل خوش شانس ها فعال شدند.\n\n"
        "✨ از اینجا به بعد وارد مرحله مسابقات می‌شویم."
    )

    try:

        await bot.send_message(
            chat_id=channel,
            text=message,
            disable_web_page_preview=True
        )

    except Exception as e:

        logger.exception(
            "Could not send activation announcement: %s",
            e
        )

    return True


async def update_network_counts(bot, post_update=True):

    logger.info(
        "Updating social network counts..."
    )

    youtube_task = asyncio.create_task(
        fetch_youtube_subscribers()
    )

    telegram_task = asyncio.create_task(
        fetch_telegram_members(bot)
    )

    youtube = await youtube_task
    telegram = await telegram_task

    conn = db()

    instagram = setting_int(
        conn,
        "instagram_followers",
        0
    )

    if youtube is not None:

        setting_set(
            conn,
            "youtube_followers",
            youtube
        )

    if telegram is not None:

        setting_set(
            conn,
            "telegram_followers",
            telegram
        )

    now = datetime.utcnow().strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )

    setting_set(
        conn,
        "network_last_update",
        now
    )

    conn.commit()
    conn.close()

    logger.info(
        "Network counts: IG=%s YT=%s TG=%s",
        instagram,
        youtube,
        telegram
    )

    activated = await activate_all_campaigns(bot)

    if post_update:

        channel = os.environ.get(
            "TELEGRAM_CHANNEL",
            DEFAULT_TELEGRAM_CHANNEL
        )

        status = network_status_text()

        try:

            await bot.send_message(
                chat_id=channel,
                text=(
                    "📈 گزارش خودکار رشد محفل خوش شانس ها\n\n"
                    + status
                ),
                disable_web_page_preview=True
            )

        except Exception as e:

            logger.exception(
                "Could not post network update: %s",
                e
            )

    return activated


async def periodic_network_update(app):

    await asyncio.sleep(15)

    while True:

        try:

            await update_network_counts(
                app.bot,
                post_update=True
            )

        except Exception as e:

            logger.exception(
                "Periodic network update failed: %s",
                e
            )

        await asyncio.sleep(
            NETWORK_UPDATE_HOURS * 60 * 60
        )


# =========================================================
# START / REFERRAL
# =========================================================

def main_menu():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🎁 کمپین‌ها",
                callback_data="campaigns"
            ),
            InlineKeyboardButton(
                "👤 پروفایل",
                callback_data="profile"
            )
        ],
        [
            InlineKeyboardButton(
                "🍀 شانس‌های من",
                callback_data="chances"
            ),
            InlineKeyboardButton(
                "👥 دعوت دوستان",
                callback_data="invite"
            )
        ],
        [
            InlineKeyboardButton(
                "📜 تاریخچه",
                callback_data="history"
            ),
            InlineKeyboardButton(
                "🏆 برندگان",
                callback_data="winners"
            )
        ],
        [
            InlineKeyboardButton(
                "🗄 آرشیو",
                callback_data="archive"
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
                "📸 Instagram",
                url=INSTAGRAM_URL
            ),
            InlineKeyboardButton(
                "▶️ YouTube",
                url=YOUTUBE_URL
            )
        ],
        [
            InlineKeyboardButton(
                "📢 کانال تلگرام",
                url=TELEGRAM_CHANNEL_URL
            )
        ]
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    if not user:
        return

    conn = db()

    existing = conn.execute(
        "SELECT id FROM users WHERE id=?",
        (user.id,)
    ).fetchone()

    if not existing:

        invited_by = None

        if context.args:

            arg = context.args[0]

            if arg.startswith("ref_"):

                try:

                    referrer_id = int(
                        arg.replace("ref_", "", 1)
                    )

                    if referrer_id != user.id:

                        referrer = conn.execute(
                            "SELECT id FROM users WHERE id=?",
                            (referrer_id,)
                        ).fetchone()

                        if referrer:
                            invited_by = referrer_id

                except Exception:
                    pass

        conn.execute(
            """
            INSERT INTO users
            (
                id,
                first_name,
                username,
                chances,
                invited_by,
                created_at
            )
            VALUES(?,?,?,?,?,?)
            """,
            (
                user.id,
                user.first_name or "",
                user.username or "",
                0,
                invited_by,
                datetime.utcnow().isoformat()
            )
        )

        if invited_by:

            try:

                conn.execute(
                    """
                    INSERT INTO referrals
                    (
                        referrer_id,
                        referred_id,
                        created_at
                    )
                    VALUES(?,?,?)
                    """,
                    (
                        invited_by,
                        user.id,
                        datetime.utcnow().isoformat()
                    )
                )

                conn.execute(
                    """
                    UPDATE users
                    SET chances=chances+1
                    WHERE id=?
                    """,
                    (invited_by,)
                )

            except sqlite3.IntegrityError:
                pass

    else:

        conn.execute(
            """
            UPDATE users
            SET first_name=?,
                username=?
            WHERE id=?
            """,
            (
                user.first_name or "",
                user.username or "",
                user.id
            )
        )

    conn.commit()
    conn.close()

    status = network_status_text()

    text = (
        "🎉 به «محفل خوش شانس ها» خوش آمدی!\n\n"
        "اینجا قراره با رشد جامعه محفل، "
        "کمپین‌ها و جوایز مختلف برگزار بشه.\n\n"
        "🔥 شرط شروع قرعه‌کشی:\n"
        "هر سه شبکه باید جداگانه به ۱۰۰,۰۰۰ نفر برسند.\n\n"
        + status
        + "\n\n"
        "👇 از منوی زیر انتخاب کن:"
    )

    await update.message.reply_text(
        text,
        reply_markup=main_menu()
    )


# =========================================================
# PROFILE
# =========================================================

async def show_profile(update, context):

    user = update.effective_user

    conn = db()

    row = conn.execute(
        """
        SELECT *
        FROM users
        WHERE id=?
        """,
        (user.id,)
    ).fetchone()

    referrals = conn.execute(
        """
        SELECT COUNT(*) AS c
        FROM referrals
        WHERE referrer_id=?
        """,
        (user.id,)
    ).fetchone()["c"]

    conn.close()

    if not row:

        await update.callback_query.message.reply_text(
            "ابتدا /start را بزن."
        )

        return

    text = (
        "👤 پروفایل شما\n\n"
        f"نام: {row['first_name'] or '-'}\n"
        f"شناسه: {row['id']}\n"
        f"نام کاربری: @{row['username'] if row['username'] else '-'}\n\n"
        f"🍀 شانس‌ها: {row['chances']}\n"
        f"👥 معرفی موفق: {referrals}"
    )

    await update.callback_query.message.reply_text(
        text,
        reply_markup=main_menu()
    )


# =========================================================
# CHANCES
# =========================================================

async def show_chances(update, context):

    user = update.effective_user

    conn = db()

    row = conn.execute(
        "SELECT chances FROM users WHERE id=?",
        (user.id,)
    ).fetchone()

    conn.close()

    chances = row["chances"] if row else 0

    await update.callback_query.message.reply_text(
        f"🍀 شانس‌های شما: {chances}\n\n"
        "هر معرفی موفق یک شانس اضافه ایجاد می‌کند.",
        reply_markup=main_menu()
    )


# =========================================================
# INVITE
# =========================================================

async def show_invite(update, context):

    user = update.effective_user

    conn = db()

    row = conn.execute(
        "SELECT chances FROM users WHERE id=?",
        (user.id,)
    ).fetchone()

    referrals = conn.execute(
        """
        SELECT COUNT(*) AS c
        FROM referrals
        WHERE referrer_id=?
        """,
        (user.id,)
    ).fetchone()["c"]

    conn.close()

    chances = row["chances"] if row else 0

    link = (
        f"https://t.me/{BOT_USERNAME}"
        f"?start=ref_{user.id}"
    )

    text = (
        "👥 دعوت دوستان\n\n"
        "دوستت را با لینک اختصاصی خودت دعوت کن.\n"
        "هر معرفی موفق = ۱ شانس 🍀\n\n"
        f"🔗 لینک شما:\n{link}\n\n"
        f"👥 معرفی موفق: {referrals}\n"
        f"🍀 شانس فعلی: {chances}"
    )

    await update.callback_query.message.reply_text(
        text,
        reply_markup=main_menu()
    )


# =========================================================
# CAMPAIGNS
# =========================================================

def lottery_is_active():

    conn = db()

    active = all_networks_reached(conn)

    conn.close()

    return active


async def show_campaigns(update, context):

    query = update.callback_query

    conn = db()

    campaigns = conn.execute(
        """
        SELECT *
        FROM campaigns
        WHERE archived=0
        ORDER BY id DESC
        """
    ).fetchall()

    networks_reached = all_networks_reached(conn)

    conn.close()

    if not networks_reached:

        text = (
            "🔒 کمپین‌ها هنوز فعال نشده‌اند.\n\n"
            + network_status_text()
        )

        await query.message.reply_text(
            text,
            reply_markup=main_menu()
        )

        return

    if not campaigns:

        await query.message.reply_text(
            "فعلاً کمپینی وجود ندارد.",
            reply_markup=main_menu()
        )

        return

    buttons = []

    for campaign in campaigns:

        if campaign["active"]:

            buttons.append([
                InlineKeyboardButton(
                    f"🎁 {campaign['title']}",
                    callback_data=f"campaign_{campaign['id']}"
                )
            ])

    if not buttons:

        await query.message.reply_text(
            "در حال حاضر کمپین فعالی وجود ندارد.",
            reply_markup=main_menu()
        )

        return

    await query.message.reply_text(
        "🎁 کمپین‌های فعال:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def show_campaign_details(
    update,
    context,
    campaign_id
):

    query = update.callback_query

    conn = db()

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

        await query.message.reply_text(
            "کمپین پیدا نشد."
        )

        return

    if not lottery_is_active():

        await query.message.reply_text(
            "🔒 این کمپین هنوز فعال نشده است.\n\n"
            + network_status_text()
        )

        return

    text = (
        f"🎁 {campaign['title']}\n\n"
        f"📝 {campaign['description'] or '-'}\n\n"
        f"🏆 جایزه: {campaign['prize'] or '-'}\n\n"
    )

    if campaign["draw_at"]:

        text += (
            f"🕐 زمان قرعه‌کشی: "
            f"{campaign['draw_at']}\n\n"
        )

    text += "برای شرکت روی دکمه زیر بزن."

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📋 مشاهده قوانین",
                callback_data=f"rules_{campaign_id}"
            )
        ]
    ])

    await query.message.reply_text(
        text,
        reply_markup=keyboard
    )


async def show_campaign_rules(
    update,
    context,
    campaign_id
):

    query = update.callback_query

    conn = db()

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

        await query.message.reply_text(
            "کمپین پیدا نشد."
        )

        return

    rules = (
        campaign["rules"]
        or "قوانین عمومی محفل خوش شانس ها."
    )

    text = (
        f"📋 قوانین کمپین\n\n"
        f"{rules}\n\n"
        "در صورت قبول قوانین، روی دکمه زیر بزن."
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ قبول قوانین",
                callback_data=f"accept_{campaign_id}"
            )
        ]
    ])

    await query.message.reply_text(
        text,
        reply_markup=keyboard
    )


async def accept_rules(
    update,
    context,
    campaign_id
):

    user = update.effective_user

    conn = db()

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

        await update.callback_query.message.reply_text(
            "کمپین پیدا نشد."
        )

        return

    version = campaign["rules_version"] or 1

    conn.execute(
        """
        INSERT INTO rule_acceptances
        (
            user_id,
            campaign_id,
            rules_version,
            accepted,
            accepted_at
        )
        VALUES(?,?,?,?,?)
        ON CONFLICT(user_id,campaign_id)
        DO UPDATE SET
            rules_version=excluded.rules_version,
            accepted=excluded.accepted,
            accepted_at=excluded.accepted_at
        """,
        (
            user.id,
            campaign_id,
            version,
            1,
            datetime.utcnow().isoformat()
        )
    )

    conn.commit()
    conn.close()

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🎟 شرکت در کمپین",
                callback_data=f"join_{campaign_id}"
            )
        ]
    ])

    await update.callback_query.message.reply_text(
        "✅ قوانین با موفقیت پذیرفته شد.",
        reply_markup=keyboard
    )


async def join_campaign(
    update,
    context,
    campaign_id
):

    user = update.effective_user

    conn = db()

    if not all_networks_reached(conn):

        conn.close()

        await update.callback_query.message.reply_text(
            "🔒 کمپین هنوز فعال نشده است.\n\n"
            + network_status_text()
        )

        return

    campaign = conn.execute(
        """
        SELECT *
        FROM campaigns
        WHERE id=?
        """,
        (campaign_id,)
    ).fetchone()

    if not campaign or not campaign["active"]:

        conn.close()

        await update.callback_query.message.reply_text(
            "این کمپین فعال نیست."
        )

        return

    accepted = conn.execute(
        """
        SELECT *
        FROM rule_acceptances
        WHERE user_id=?
        AND campaign_id=?
        AND accepted=1
        """,
        (
            user.id,
            campaign_id
        )
    ).fetchone()

    if not accepted:

        conn.close()

        await update.callback_query.message.reply_text(
            "ابتدا قوانین کمپین را قبول کن."
        )

        return

    already = conn.execute(
        """
        SELECT *
        FROM participations
        WHERE campaign_id=?
        AND user_id=?
        """,
        (
            campaign_id,
            user.id
        )
    ).fetchone()

    if already:

        conn.close()

        await update.callback_query.message.reply_text(
            "✅ شما قبلاً در این کمپین ثبت شده‌ای."
        )

        return

    conn.execute(
        """
        INSERT INTO participations
        (
            campaign_id,
            user_id,
            chances_used,
            created_at
        )
        VALUES(?,?,?,?)
        """,
        (
            campaign_id,
            user.id,
            1,
            datetime.utcnow().isoformat()
        )
    )

    conn.commit()
    conn.close()

    await update.callback_query.message.reply_text(
        "🎉 ثبت‌نام شما با موفقیت انجام شد.\n\n"
        "🍀 شما در قرعه‌کشی این کمپین ثبت شدید.",
        reply_markup=main_menu()
    )


# =========================================================
# HISTORY
# =========================================================

async def show_history(update, context):

    user = update.effective_user

    conn = db()

    rows = conn.execute(
        """
        SELECT
            p.created_at,
            c.title,
            c.prize
        FROM participations p
        LEFT JOIN campaigns c
            ON c.id=p.campaign_id
        WHERE p.user_id=?
        ORDER BY p.id DESC
        LIMIT 20
        """,
        (user.id,)
    ).fetchall()

    conn.close()

    if not rows:

        text = "📜 هنوز در هیچ کمپینی شرکت نکرده‌ای."

    else:

        text = "📜 تاریخچه شرکت شما:\n\n"

        for row in rows:

            text += (
                f"🎁 {row['title'] or '-'}\n"
                f"🏆 {row['prize'] or '-'}\n"
                f"🕐 {row['created_at']}\n\n"
            )

    await update.callback_query.message.reply_text(
        text,
        reply_markup=main_menu()
    )


# =========================================================
# WINNERS
# =========================================================

async def show_winners(update, context):

    conn = db()

    rows = conn.execute(
        """
        SELECT
            w.created_at,
            w.announced,
            u.first_name,
            u.username,
            c.title,
            c.prize
        FROM winners w
        LEFT JOIN users u
            ON u.id=w.user_id
        LEFT JOIN campaigns c
            ON c.id=w.campaign_id
        WHERE w.announced=1
        ORDER BY w.id DESC
        LIMIT 30
        """
    ).fetchall()

    conn.close()

    if not rows:

        text = "🏆 هنوز برنده‌ای اعلام نشده است."

    else:

        text = "🏆 برندگان محفل خوش شانس ها\n\n"

        for row in rows:

            name = row["first_name"] or "کاربر"

            text += (
                f"🥇 {name}\n"
                f"🎁 {row['title'] or '-'}\n"
                f"🏆 {row['prize'] or '-'}\n\n"
            )

    await update.callback_query.message.reply_text(
        text,
        reply_markup=main_menu()
    )


# =========================================================
# ARCHIVE
# =========================================================

async def show_archive(update, context):

    conn = db()

    rows = conn.execute(
        """
        SELECT *
        FROM campaigns
        WHERE archived=1
        ORDER BY id DESC
        LIMIT 30
        """
    ).fetchall()

    conn.close()

    if not rows:

        text = "🗄 آرشیو فعلاً خالی است."

    else:

        text = "🗄 آرشیو کمپین‌ها\n\n"

        for row in rows:

            text += (
                f"🎁 {row['title']}\n"
                f"🏆 {row['prize'] or '-'}\n\n"
            )

    await update.callback_query.message.reply_text(
        text,
        reply_markup=main_menu()
    )


# =========================================================
# RULES
# =========================================================

async def show_rules(update, context):

    conn = db()

    rules = setting_get(
        conn,
        "rules_text",
        "قوانین هنوز تنظیم نشده است."
    )

    version = setting_int(
        conn,
        "rules_version",
        1
    )

    conn.close()

    await update.callback_query.message.reply_text(
        "📋 قوانین محفل خوش شانس ها\n\n"
        + rules
        + f"\n\nنسخه قوانین: {version}",
        reply_markup=main_menu()
    )


# =========================================================
# SUPPORT
# =========================================================

async def show_support(update, context):

    await update.callback_query.message.reply_text(
        "🎧 پشتیبانی\n\n"
        "پیام خودت را همینجا ارسال کن.\n"
        "پیام برای مدیریت ارسال می‌شود و پاسخ از طریق ربات برایت می‌آید.",
        reply_markup=main_menu()
    )


async def handle_support_message(update, context):

    if not update.message:
        return

    user = update.effective_user

    if not user:
        return

    if is_admin(user.id):
        return

    message = update.message.text

    if not message:
        return

    conn = db()

    conn.execute(
        """
        INSERT INTO support_tickets
        (
            user_id,
            message,
            status,
            created_at
        )
        VALUES(?,?,?,?)
        """,
        (
            user.id,
            message,
            "open",
            datetime.utcnow().isoformat()
        )
    )

    conn.commit()

    ticket = conn.execute(
        "SELECT last_insert_rowid() AS id"
    ).fetchone()["id"]

    conn.close()

    await update.message.reply_text(
        "✅ پیام شما برای پشتیبانی ارسال شد.\n"
        f"شماره تیکت: #{ticket}"
    )

    for admin_id in get_admin_ids():

        try:

            await context.bot.send_message(
                chat_id=admin_id,
                text=(
                    "🎧 تیکت جدید پشتیبانی\n\n"
                    f"Ticket: #{ticket}\n"
                    f"User ID: {user.id}\n"
                    f"Name: {user.first_name or '-'}\n\n"
                    f"پیام:\n{message}\n\n"
                    f"پاسخ:\n"
                    f"/reply {user.id} متن پاسخ"
                )
            )

        except Exception as e:

            logger.error(
                "Could not notify admin: %s",
                e
            )


# =========================================================
# ADMIN PANEL
# =========================================================

async def admin_panel(update, context):

    if not await admin_required(update):
        return

    text = (
        "🛠 پنل مدیریت محفل خوش شانس ها\n\n"

        "📊 آمار:\n"
        "/stats\n"
        "/networkstatus\n\n"

        "🌐 شبکه‌ها:\n"
        "/igfollowers 100000\n"
        "/followers 100000\n"
        "/activation 100000\n"
        "/maxfollowers 500000\n\n"

        "🎁 کمپین:\n"
        "/newcampaign عنوان | توضیح | جایزه\n"
        "/campaignsadmin\n"
        "/activate ID\n"
        "/deactivate ID\n"
        "/drawdate ID تاریخ ساعت\n"
        "/archive ID\n"
        "/participants ID\n"
        "/winner CAMPAIGN_ID USER_ID\n"
        "/announce ID\n\n"

        "📋 قوانین:\n"
        "/rulesadmin متن قوانین\n\n"

        "👥 کاربران:\n"
        "/users\n"
        "/referrals\n"
        "/chancesadmin\n\n"

        "📢 ارسال پیام:\n"
        "/broadcast متن\n\n"

        "🎧 پشتیبانی:\n"
        "/tickets\n"
        "/reply USER_ID متن\n\n"

        "📜 لاگ:\n"
        "/logs"
    )

    await update.message.reply_text(text)


# =========================================================
# STATS
# =========================================================

async def stats(update, context):

    if not await admin_required(update):
        return

    conn = db()

    users = conn.execute(
        "SELECT COUNT(*) AS c FROM users"
    ).fetchone()["c"]

    referrals = conn.execute(
        "SELECT COUNT(*) AS c FROM referrals"
    ).fetchone()["c"]

    participations = conn.execute(
        "SELECT COUNT(*) AS c FROM participations"
    ).fetchone()["c"]

    campaigns = conn.execute(
        """
        SELECT COUNT(*) AS c
        FROM campaigns
        WHERE active=1
        AND archived=0
        """
    ).fetchone()["c"]

    conn.close()

    data = get_network_counts()

    status = (
        "فعال ✅"
        if data["activated"]
        else "فعال نشده 🔒"
    )

    text = (
        "📊 آمار ربات\n\n"
        f"👥 کاربران: {users:,}\n"
        f"🔗 معرفی‌های موفق: {referrals:,}\n"
        f"🎟 مشارکت‌ها: {participations:,}\n"
        f"🎁 کمپین‌های فعال: {campaigns:,}\n\n"

        "🌐 شبکه‌ها:\n"
        f"📸 Instagram: {data['instagram']:,}\n"
        f"▶️ YouTube: {data['youtube']:,}\n"
        f"📢 Telegram: {data['telegram']:,}\n\n"

        f"🎯 حد فعال‌سازی هر شبکه: "
        f"{data['target']:,}\n"
        f"🔥 وضعیت: {status}"
    )

    await update.message.reply_text(text)


# =========================================================
# NETWORK STATUS COMMAND
# =========================================================

async def network_status_command(update, context):

    if not await admin_required(update):
        return

    await update.message.reply_text(
        "⏳ در حال دریافت آمار YouTube و Telegram..."
    )

    await update_network_counts(
        context.bot,
        post_update=False
    )

    await update.message.reply_text(
        network_status_text()
    )


# =========================================================
# MANUAL INSTAGRAM
# =========================================================

async def set_instagram_followers(update, context):

    if not await admin_required(update):
        return

    if not context.args:

        await update.message.reply_text(
            "مثال:\n"
            "/igfollowers 87420"
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
        count
    )

    if not all_networks_reached(conn):

        setting_set(
            conn,
            "networks_activated",
            0
        )

    conn.commit()
    conn.close()

    log_action(
        update.effective_user.id,
        f"instagram_followers={count}"
    )

    await update.message.reply_text(
        f"✅ Instagram روی {count:,} تنظیم شد.\n\n"
        + network_status_text()
    )


# =========================================================
# OLD FOLLOWERS COMMAND
# =========================================================

async def set_followers(update, context):

    if not await admin_required(update):
        return

    if not context.args:

        await update.message.reply_text(
            "مثال:\n/followers 100000\n\n"
            "این دستور فقط برای تست مقدار قدیمی است.\n"
            "فعال‌سازی واقعی بر اساس هر سه شبکه انجام می‌شود."
        )

        return

    try:

        count = int(
            context.args[0].replace(",", "")
        )

    except Exception:

        await update.message.reply_text(
            "❌ عدد صحیح وارد کن."
        )

        return

    conn = db()

    setting_set(
        conn,
        "followers",
        count
    )

    conn.close()

    log_action(
        update.effective_user.id,
        f"legacy_followers={count}"
    )

    await update.message.reply_text(
        f"✅ مقدار قدیمی followers روی {count:,} قرار گرفت.\n\n"
        "⚠️ این مقدار دیگر شرط فعال‌سازی سه‌شبکه‌ای نیست."
    )


# =========================================================
# ACTIVATION TARGET
# =========================================================

async def set_activation(update, context):

    if not await admin_required(update):
        return

    if not context.args:

        await update.message.reply_text(
            "مثال:\n/activation 100000"
        )

        return

    try:

        count = int(
            context.args[0].replace(",", "")
        )

        if count <= 0:
            raise ValueError

    except Exception:

        await update.message.reply_text(
            "❌ عدد صحیح مثبت وارد کن."
        )

        return

    conn = db()

    setting_set(
        conn,
        "activation_followers",
        count
    )

    setting_set(
        conn,
        "networks_activated",
        0
    )

    conn.close()

    log_action(
        update.effective_user.id,
        f"activation_followers={count}"
    )

    await update.message.reply_text(
        f"🎯 حد فعال‌سازی هر شبکه: {count:,}"
    )


async def set_max_followers(update, context):

    if not await admin_required(update):
        return

    if not context.args:

        await update.message.reply_text(
            "مثال:\n/maxfollowers 500000"
        )

        return

    try:

        value = int(
            context.args[0].replace(",", "")
        )

    except Exception:

        await update.message.reply_text(
            "❌ عدد صحیح وارد کن."
        )

        return

    conn = db()

    setting_set(
        conn,
        "plan_max_followers",
        value
    )

    conn.close()

    await update.message.reply_text(
        f"✅ حداکثر مقدار روی {value:,} تنظیم شد."
    )


async def set_daily_prize(update, context):

    if not await admin_required(update):
        return

    if not context.args:

        await update.message.reply_text(
            "مثال:\n/dailyprize 10000000"
        )

        return

    try:

        value = int(
            context.args[0].replace(",", "")
        )

    except Exception:

        await update.message.reply_text(
            "❌ عدد صحیح وارد کن."
        )

        return

    conn = db()

    setting_set(
        conn,
        "daily_prize_amount",
        value
    )

    conn.close()

    await update.message.reply_text(
        f"✅ مبلغ جایزه روزانه: {value:,}"
    )


# =========================================================
# NEW CAMPAIGN
# =========================================================

async def new_campaign(update, context):

    if not await admin_required(update):
        return

    raw = update.message.text[
        len("/newcampaign"):
    ].strip()

    parts = [
        x.strip()
        for x in raw.split("|")
    ]

    if len(parts) < 3:

        await update.message.reply_text(
            "فرمت:\n"
            "/newcampaign عنوان | توضیح | جایزه"
        )

        return

    title = parts[0]
    description = parts[1]
    prize = parts[2]

    conn = db()

    rules = setting_get(
        conn,
        "rules_text",
        ""
    )

    version = setting_int(
        conn,
        "rules_version",
        1
    )

    cursor = conn.execute(
        """
        INSERT INTO campaigns
        (
            title,
            description,
            prize,
            active,
            created_at,
            rules,
            rules_version,
            archived,
            prize_amount
        )
        VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (
            title,
            description,
            prize,
            0,
            datetime.utcnow().isoformat(),
            rules,
            version,
            0,
            0
        )
    )

    campaign_id = cursor.lastrowid

    conn.commit()
    conn.close()

    log_action(
        update.effective_user.id,
        f"new_campaign={campaign_id}"
    )

    await update.message.reply_text(
        f"✅ کمپین ساخته شد.\n"
        f"ID: {campaign_id}"
    )


# =========================================================
# ADMIN CAMPAIGNS
# =========================================================

async def campaigns_admin(update, context):

    if not await admin_required(update):
        return

    conn = db()

    rows = conn.execute(
        """
        SELECT *
        FROM campaigns
        ORDER BY id DESC
        """
    ).fetchall()

    conn.close()

    if not rows:

        await update.message.reply_text(
            "کمپینی وجود ندارد."
        )

        return

    text = "🎁 کمپین‌ها:\n\n"

    for row in rows:

        status = (
            "فعال ✅"
            if row["active"]
            else "غیرفعال 🔒"
        )

        archived = (
            " | آرشیو"
            if row["archived"]
            else ""
        )

        text += (
            f"ID: {row['id']}\n"
            f"عنوان: {row['title']}\n"
            f"وضعیت: {status}{archived}\n"
            f"جایزه: {row['prize'] or '-'}\n\n"
        )

    await update.message.reply_text(text)


async def activate_campaign(update, context):

    if not await admin_required(update):
        return

    if not context.args:

        await update.message.reply_text(
            "مثال:\n/activate 1"
        )

        return

    try:

        campaign_id = int(
            context.args[0]
        )

    except Exception:

        await update.message.reply_text(
            "❌ ID نامعتبر."
        )

        return

    if not lottery_is_active():

        await update.message.reply_text(
            "🔒 هنوز هر سه شبکه به حد نصاب نرسیده‌اند.\n\n"
            + network_status_text()
        )

        return

    conn = db()

    conn.execute(
        """
        UPDATE campaigns
        SET active=1,
            archived=0
        WHERE id=?
        """,
        (campaign_id,)
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "✅ کمپین فعال شد."
    )


async def deactivate_campaign(update, context):

    if not await admin_required(update):
        return

    if not context.args:

        await update.message.reply_text(
            "مثال:\n/deactivate 1"
        )

        return

    try:

        campaign_id = int(
            context.args[0]
        )

    except Exception:

        await update.message.reply_text(
            "❌ ID نامعتبر."
        )

        return

    conn = db()

    conn.execute(
        """
        UPDATE campaigns
        SET active=0
        WHERE id=?
        """,
        (campaign_id,)
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "✅ کمپین غیرفعال شد."
    )


async def set_draw_date(update, context):

    if not await admin_required(update):
        return

    if len(context.args) < 3:

        await update.message.reply_text(
            "فرمت:\n"
            "/drawdate ID 2026-10-01 20:00"
        )

        return

    try:

        campaign_id = int(
            context.args[0]
        )

        date = context.args[1]
        time = context.args[2]

        draw_at = f"{date} {time}"

    except Exception:

        await update.message.reply_text(
            "❌ فرمت اشتباه."
        )

        return

    conn = db()

    conn.execute(
        """
        UPDATE campaigns
        SET draw_at=?
        WHERE id=?
        """,
        (
            draw_at,
            campaign_id
        )
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ زمان قرعه‌کشی تنظیم شد:\n{draw_at}"
    )


# =========================================================
# RULE ADMIN
# =========================================================

async def rules_admin(update, context):

    if not await admin_required(update):
        return

    text = update.message.text[
        len("/rulesadmin"):
    ].strip()

    if not text:

        await update.message.reply_text(
            "فرمت:\n/rulesadmin متن قوانین"
        )

        return

    conn = db()

    version = (
        setting_int(
            conn,
            "rules_version",
            1
        ) + 1
    )

    setting_set(
        conn,
        "rules_text",
        text
    )

    setting_set(
        conn,
        "rules_version",
        version
    )

    conn.execute(
        """
        UPDATE campaigns
        SET rules=?,
            rules_version=?
        """,
        (
            text,
            version
        )
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ قوانین بروزرسانی شد.\n"
        f"نسخه: {version}"
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
        ORDER BY id DESC
        LIMIT 100
        """
    ).fetchall()

    conn.close()

    if not rows:

        await update.message.reply_text(
            "کاربری وجود ندارد."
        )

        return

    text = "👥 آخرین کاربران:\n\n"

    for row in rows:

        text += (
            f"ID: {row['id']}\n"
            f"Name: {row['first_name'] or '-'}\n"
            f"Username: @{row['username'] or '-'}\n"
            f"Chances: {row['chances']}\n\n"
        )

    await update.message.reply_text(text)


async def referrals_admin(update, context):

    if not await admin_required(update):
        return

    conn = db()

    rows = conn.execute(
        """
        SELECT
            r.referrer_id,
            r.referred_id,
            r.created_at,
            u.first_name
        FROM referrals r
        LEFT JOIN users u
            ON u.id=r.referrer_id
        ORDER BY r.id DESC
        LIMIT 100
        """
    ).fetchall()

    conn.close()

    if not rows:

        await update.message.reply_text(
            "هنوز معرفی موفقی ثبت نشده."
        )

        return

    text = "🔗 معرفی‌ها:\n\n"

    for row in rows:

        text += (
            f"Referrer: {row['referrer_id']} "
            f"({row['first_name'] or '-'})\n"
            f"Referred: {row['referred_id']}\n"
            f"{row['created_at']}\n\n"
        )

    await update.message.reply_text(text)


async def chances_admin(update, context):

    if not await admin_required(update):
        return

    conn = db()

    rows = conn.execute(
        """
        SELECT id, first_name, username, chances
        FROM users
        ORDER BY chances DESC
        LIMIT 100
        """
    ).fetchall()

    conn.close()

    text = "🍀 بیشترین شانس‌ها:\n\n"

    for row in rows:

        text += (
            f"{row['id']} | "
            f"{row['first_name'] or '-'} | "
            f"{row['chances']} شانس\n"
        )

    await update.message.reply_text(text)


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

    except Exception:

        await update.message.reply_text(
            "❌ ID نامعتبر."
        )

        return

    conn = db()

    rows = conn.execute(
        """
        SELECT
            p.user_id,
            p.created_at,
            u.first_name,
            u.username
        FROM participations p
        LEFT JOIN users u
            ON u.id=p.user_id
        WHERE p.campaign_id=?
        ORDER BY p.id ASC
        """,
        (campaign_id,)
    ).fetchall()

    conn.close()

    if not rows:

        await update.message.reply_text(
            "هنوز کسی شرکت نکرده."
        )

        return

    text = (
        f"🎟 شرکت‌کنندگان کمپین {campaign_id}\n\n"
    )

    for row in rows:

        text += (
            f"ID: {row['user_id']}\n"
            f"نام: {row['first_name'] or '-'}\n"
            f"Username: @{row['username'] or '-'}\n\n"
        )

    await update.message.reply_text(text)


# =========================================================
# WINNER ADMIN
# =========================================================

async def set_winner(update, context):

    if not await admin_required(update):
        return

    if len(context.args) < 2:

        await update.message.reply_text(
            "فرمت:\n/winner CAMPAIGN_ID USER_ID"
        )

        return

    try:

        campaign_id = int(
            context.args[0]
        )

        user_id = int(
            context.args[1]
        )

    except Exception:

        await update.message.reply_text(
            "❌ ID نامعتبر."
        )

        return

    conn = db()

    user = conn.execute(
        "SELECT id FROM users WHERE id=?",
        (user_id,)
    ).fetchone()

    campaign = conn.execute(
        "SELECT id FROM campaigns WHERE id=?",
        (campaign_id,)
    ).fetchone()

    if not user or not campaign:

        conn.close()

        await update.message.reply_text(
            "❌ کاربر یا کمپین پیدا نشد."
        )

        return

    conn.execute(
        """
        INSERT INTO winners
        (
            campaign_id,
            user_id,
            announced,
            created_at
        )
        VALUES(?,?,?,?)
        ON CONFLICT(campaign_id)
        DO UPDATE SET
            user_id=excluded.user_id,
            announced=excluded.announced,
            created_at=excluded.created_at
        """,
        (
            campaign_id,
            user_id,
            0,
            datetime.utcnow().isoformat()
        )
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "🏆 برنده ثبت شد."
    )


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

    except Exception:

        await update.message.reply_text(
            "❌ ID نامعتبر."
        )

        return

    conn = db()

    row = conn.execute(
        """
        SELECT
            w.user_id,
            u.first_name,
            u.username,
            c.title,
            c.prize
        FROM winners w
        LEFT JOIN users u
            ON u.id=w.user_id
        LEFT JOIN campaigns c
            ON c.id=w.campaign_id
        WHERE w.campaign_id=?
        """,
        (campaign_id,)
    ).fetchone()

    if not row:

        conn.close()

        await update.message.reply_text(
            "برای این کمپین برنده‌ای ثبت نشده."
        )

        return

    conn.execute(
        """
        UPDATE winners
        SET announced=1,
            announced_at=?
        WHERE campaign_id=?
        """,
        (
            datetime.utcnow().isoformat(),
            campaign_id
        )
    )

    conn.commit()
    conn.close()

    channel = os.environ.get(
        "TELEGRAM_CHANNEL",
        DEFAULT_TELEGRAM_CHANNEL
    )

    winner_name = (
        row["first_name"]
        or "برنده"
    )

    message = (
        "🏆🎉 برنده جدید محفل خوش شانس ها 🎉🏆\n\n"
        f"🎁 کمپین: {row['title'] or '-'}\n"
        f"🏆 جایزه: {row['prize'] or '-'}\n\n"
        f"🥇 برنده: {winner_name}\n"
    )

    try:

        await context.bot.send_message(
            chat_id=channel,
            text=message
        )

    except Exception as e:

        logger.exception(
            "Winner announcement error: %s",
            e
        )

    await update.message.reply_text(
        "✅ برنده اعلام شد."
    )


# =========================================================
# ARCHIVE ADMIN
# =========================================================

async def archive_campaign(update, context):

    if not await admin_required(update):
        return

    if not context.args:

        await update.message.reply_text(
            "مثال:\n/archive 1"
        )

        return

    try:

        campaign_id = int(
            context.args[0]
        )

    except Exception:

        await update.message.reply_text(
            "❌ ID نامعتبر."
        )

        return

    conn = db()

    conn.execute(
        """
        UPDATE campaigns
        SET archived=1,
            active=0
        WHERE id=?
        """,
        (campaign_id,)
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "🗄 کمپین به آرشیو منتقل شد."
    )


# =========================================================
# BROADCAST
# =========================================================

async def broadcast(update, context):

    if not await admin_required(update):
        return

    text = update.message.text[
        len("/broadcast"):
    ].strip()

    if not text:

        await update.message.reply_text(
            "فرمت:\n/broadcast متن پیام"
        )

        return

    conn = db()

    rows = conn.execute(
        "SELECT id FROM users"
    ).fetchall()

    conn.close()

    sent = 0
    failed = 0

    await update.message.reply_text(
        f"📢 ارسال پیام به {len(rows)} کاربر شروع شد..."
    )

    for row in rows:

        try:

            await context.bot.send_message(
                chat_id=row["id"],
                text=text
            )

            sent += 1

            await asyncio.sleep(0.05)

        except Exception:

            failed += 1

    await update.message.reply_text(
        "✅ ارسال تمام شد.\n\n"
        f"موفق: {sent}\n"
        f"ناموفق: {failed}"
    )


# =========================================================
# TICKETS
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
        LIMIT 50
        """
    ).fetchall()

    conn.close()

    if not rows:

        await update.message.reply_text(
            "🎧 تیکت باز نداریم."
        )

        return

    text = "🎧 تیکت‌های باز:\n\n"

    for row in rows:

        text += (
            f"#{row['id']}\n"
            f"User: {row['user_id']}\n"
            f"{row['message']}\n\n"
            f"/reply {row['user_id']} متن پاسخ\n\n"
        )

    await update.message.reply_text(text)


async def reply_ticket(update, context):

    if not await admin_required(update):
        return

    if len(context.args) < 2:

        await update.message.reply_text(
            "فرمت:\n"
            "/reply USER_ID متن پاسخ"
        )

        return

    try:

        user_id = int(
            context.args[0]
        )

    except Exception:

        await update.message.reply_text(
            "❌ USER_ID نامعتبر."
        )

        return

    reply_text = " ".join(
        context.args[1:]
    )

    conn = db()

    conn.execute(
        """
        UPDATE support_tickets
        SET status='closed',
            admin_reply=?,
            replied_at=?
        WHERE user_id=?
        AND status='open'
        """,
        (
            reply_text,
            datetime.utcnow().isoformat(),
            user_id
        )
    )

    conn.commit()
    conn.close()

    try:

        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "🎧 پاسخ پشتیبانی:\n\n"
                + reply_text
            )
        )

        await update.message.reply_text(
            "✅ پاسخ ارسال شد."
        )

    except Exception as e:

        await update.message.reply_text(
            f"❌ ارسال پاسخ انجام نشد:\n{e}"
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
        LIMIT 100
        """
    ).fetchall()

    conn.close()

    if not rows:

        await update.message.reply_text(
            "لاگی وجود ندارد."
        )

        return

    text = "📜 آخرین عملیات:\n\n"

    for row in rows:

        text += (
            f"{row['created_at']}\n"
            f"Admin: {row['admin_id']}\n"
            f"{row['action']}\n\n"
        )

    await update.message.reply_text(text)


# =========================================================
# CALLBACK HANDLER
# =========================================================

async def button_handler(update, context):

    query = update.callback_query

    await query.answer()

    data = query.data

    if data == "campaigns":

        await show_campaigns(
            update,
            context
        )

    elif data == "profile":

        await show_profile(
            update,
            context
        )

    elif data == "chances":

        await show_chances(
            update,
            context
        )

    elif data == "invite":

        await show_invite(
            update,
            context
        )

    elif data == "history":

        await show_history(
            update,
            context
        )

    elif data == "winners":

        await show_winners(
            update,
            context
        )

    elif data == "archive":

        await show_archive(
            update,
            context
        )

    elif data == "rules":

        await show_rules(
            update,
            context
        )

    elif data == "support":

        await show_support(
            update,
            context
        )

    elif data.startswith("campaign_"):

        campaign_id = int(
            data.split("_", 1)[1]
        )

        await show_campaign_details(
            update,
            context,
            campaign_id
        )

    elif data.startswith("rules_"):

        campaign_id = int(
            data.split("_", 1)[1]
        )

        await show_campaign_rules(
            update,
            context,
            campaign_id
        )

    elif data.startswith("accept_"):

        campaign_id = int(
            data.split("_", 1)[1]
        )

        await accept_rules(
            update,
            context,
            campaign_id
        )

    elif data.startswith("join_"):

        campaign_id = int(
            data.split("_", 1)[1]
        )

        await join_campaign(
            update,
            context,
            campaign_id
        )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(update, context):

    logger.exception(
        "Unhandled bot error",
        exc_info=context.error
    )


# =========================================================
# MAIN
# =========================================================

async def main():

    bot_token = os.environ.get(
        "BOT_TOKEN"
    )

    render_url = os.environ.get(
        "RENDER_EXTERNAL_URL"
    )

    if not bot_token:

        raise RuntimeError(
            "BOT_TOKEN is not configured."
        )

    if not render_url:

        raise RuntimeError(
            "RENDER_EXTERNAL_URL is not configured."
        )

    init_db()

    app = (
        Application
        .builder()
        .token(bot_token)
        .build()
    )

    # ---------------- USER ----------------

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    # ---------------- ADMIN ----------------

    app.add_handler(
        CommandHandler(
            "admin",
            admin_panel
        )
    )

    app.add_handler(
        CommandHandler(
            "stats",
            stats
        )
    )

    app.add_handler(
        CommandHandler(
            "networkstatus",
            network_status_command
        )
    )

    app.add_handler(
        CommandHandler(
            "igfollowers",
            set_instagram_followers
        )
    )

    app.add_handler(
        CommandHandler(
            "followers",
            set_followers
        )
    )

    app.add_handler(
        CommandHandler(
            "activation",
            set_activation
        )
    )

    app.add_handler(
        CommandHandler(
            "maxfollowers",
            set_max_followers
        )
    )

    app.add_handler(
        CommandHandler(
            "dailyprize",
            set_daily_prize
        )
    )

    app.add_handler(
        CommandHandler(
            "newcampaign",
            new_campaign
        )
    )

    app.add_handler(
        CommandHandler(
            "campaignsadmin",
            campaigns_admin
        )
    )

    app.add_handler(
        CommandHandler(
            "activate",
            activate_campaign
        )
    )

    app.add_handler(
        CommandHandler(
            "deactivate",
            deactivate_campaign
        )
    )

    app.add_handler(
        CommandHandler(
            "drawdate",
            set_draw_date
        )
    )

    app.add_handler(
        CommandHandler(
            "rulesadmin",
            rules_admin
        )
    )

    app.add_handler(
        CommandHandler(
            "users",
            users_admin
        )
    )

    app.add_handler(
        CommandHandler(
            "referrals",
            referrals_admin
        )
    )

    app.add_handler(
        CommandHandler(
            "chancesadmin",
            chances_admin
        )
    )

    app.add_handler(
        CommandHandler(
            "participants",
            participants_admin
        )
    )

    app.add_handler(
        CommandHandler(
            "winner",
            set_winner
        )
    )

    app.add_handler(
        CommandHandler(
            "announce",
            announce_winner
        )
    )

    app.add_handler(
        CommandHandler(
            "archive",
            archive_campaign
        )
    )

    app.add_handler(
        CommandHandler(
            "broadcast",
            broadcast
        )
    )

    app.add_handler(
        CommandHandler(
            "tickets",
            tickets_admin
        )
    )

    app.add_handler(
        CommandHandler(
            "reply",
            reply_ticket
        )
    )

    app.add_handler(
        CommandHandler(
            "logs",
            logs_admin
        )
    )

    # ---------------- SUPPORT ----------------

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            handle_support_message
        )
    )

    app.add_error_handler(
        error_handler
    )

    port = int(
        os.environ.get(
            "PORT",
            "10000"
        )
    )

    render_url = render_url.rstrip("/")

    # Initialize application
    await app.initialize()

    await app.start()

    # Webhook
    await app.updater.start_webhook(
        listen="0.0.0.0",
        port=port,
        url_path="telegram",
        webhook_url=(
            f"{render_url}/telegram"
        ),
    )

    logger.info(
        "MahfelShansBot started."
    )

    logger.info(
        "Network update interval: %s hours",
        NETWORK_UPDATE_HOURS
    )

    # Automatic network updater
    network_task = asyncio.create_task(
        periodic_network_update(app)
    )

    try:

        while True:

            await asyncio.sleep(3600)

    except asyncio.CancelledError:

        pass

    finally:

        network_task.cancel()

        try:
            await network_task
        except asyncio.CancelledError:
            pass

        await app.updater.stop()
        await app.stop()
        await app.shutdown()


if __name__ == "__main__":

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        logger.info(
            "Bot stopped."
        )
