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

# =========================
# SETTINGS
# =========================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

BOT_USERNAME = "MahfelShansBot"
DB_FILE = "mahfelshans.db"

INSTAGRAM_URL = "https://instagram.com/MAHFELSHANS"
YOUTUBE_URL = "https://youtube.com/@mahfelshans"

# =========================
# DATABASE
# =========================

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def column_exists(conn, table, column):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def add_column_if_missing(conn, table, column, definition):
    if not column_exists(conn, table, column):
        conn.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )


def init_db():
    conn = get_db()

    # -------------------------
    # USERS
    # -------------------------

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

    add_column_if_missing(
        conn, "users", "support_mode", "TEXT DEFAULT 'human'"
    )

    # -------------------------
    # REFERRALS
    # -------------------------

    conn.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER NOT NULL,
            referred_id INTEGER NOT NULL UNIQUE,
            created_at TEXT
        )
    """)

    # -------------------------
    # CAMPAIGNS
    # -------------------------

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

    add_column_if_missing(
        conn, "campaigns", "rules", "TEXT DEFAULT ''"
    )

    add_column_if_missing(
        conn, "campaigns", "rules_version", "TEXT DEFAULT '1'"
    )

    add_column_if_missing(
        conn, "campaigns", "draw_at", "TEXT DEFAULT ''"
    )

    add_column_if_missing(
        conn, "campaigns", "archived", "INTEGER DEFAULT 0"
    )

    add_column_if_missing(
        conn, "campaigns", "prize_amount", "INTEGER DEFAULT 0"
    )

    # -------------------------
    # PARTICIPATIONS
    # -------------------------

    conn.execute("""
        CREATE TABLE IF NOT EXISTS participations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            chances_used INTEGER DEFAULT 1,
            created_at TEXT,
            UNIQUE(campaign_id, user_id)
        )
    """)

    # -------------------------
    # RULE ACCEPTANCES
    # -------------------------

    conn.execute("""
        CREATE TABLE IF NOT EXISTS rule_acceptances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            campaign_id INTEGER NOT NULL,
            rules_version TEXT,
            accepted INTEGER DEFAULT 0,
            accepted_at TEXT,
            UNIQUE(user_id, campaign_id)
        )
    """)

    # -------------------------
    # WINNERS
    # -------------------------

    conn.execute("""
        CREATE TABLE IF NOT EXISTS winners (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            announced INTEGER DEFAULT 0,
            announced_at TEXT,
            created_at TEXT,
            UNIQUE(campaign_id)
        )
    """)

    # -------------------------
    # SUPPORT
    # -------------------------

    conn.execute("""
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

    # -------------------------
    # PAYMENTS - FUTURE
    # -------------------------

    conn.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            campaign_id INTEGER,
            amount INTEGER DEFAULT 0,
            gateway TEXT,
            transaction_code TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT,
            paid_at TEXT
        )
    """)

    # -------------------------
    # SETTINGS
    # -------------------------

    conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    default_settings = {
        "followers": "0",
        "activation_followers": "100000",
        "plan_max_followers": "500000",
        "daily_prize_amount": "10000000",
        "payment_enabled": "0",
        "rules_version": "1",
        "rules_text": (
            "شرایط و قوانین شرکت در کمپین:\n\n"
            "اطلاعات کامل هر کمپین در صفحه همان کمپین اعلام می‌شود.\n"
            "شرکت‌کننده باید اطلاعات خود را صحیح وارد کند.\n"
            "نتیجه قرعه‌کشی و شرایط دریافت جایزه طبق قوانین اعلام‌شده "
            "همان کمپین خواهد بود."
        ),
    }

    for key, value in default_settings.items():
        conn.execute(
            """
            INSERT OR IGNORE INTO settings (key, value)
            VALUES (?, ?)
            """,
            (key, value),
        )

    # -------------------------
    # OPERATION LOGS
    # -------------------------

    conn.execute("""
        CREATE TABLE IF NOT EXISTS operation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER,
            action TEXT,
            details TEXT,
            created_at TEXT
        )
    """)

    # -------------------------
    # INITIAL CAMPAIGN
    # -------------------------

    count = conn.execute(
        "SELECT COUNT(*) FROM campaigns"
    ).fetchone()[0]

    if count == 0:
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
                draw_at,
                archived,
                prize_amount
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "اولین کمپین محفل",
                "جزئیات کمپین به‌زودی اعلام می‌شود.",
                "جایزه ویژه محفل",
                0,
                datetime.utcnow().isoformat(),
                get_setting(conn, "rules_text"),
                get_setting(conn, "rules_version"),
                "",
                0,
                0,
            )
        )

    conn.commit()
    conn.close()


# =========================
# SETTINGS HELPERS
# =========================

def get_setting(conn, key, default=""):
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?",
        (key,)
    ).fetchone()

    if row:
        return row["value"]

    return default


def set_setting(conn, key, value):
    conn.execute(
        """
        INSERT INTO settings (key, value)
        VALUES (?, ?)
        ON CONFLICT(key)
        DO UPDATE SET value = excluded.value
        """,
        (key, str(value))
    )


def get_int_setting(conn, key, default=0):
    value = get_setting(conn, key, str(default))

    try:
        return int(value)
    except:
        return default


# =========================
# ADMIN
# =========================

def get_admin_ids():
    raw = os.environ.get("ADMIN_IDS", "")

    result = []

    for item in raw.split(","):
        item = item.strip()

        if item.isdigit():
            result.append(int(item))

    return result


def is_admin(user_id):
    return user_id in get_admin_ids()


async def admin_required(update):
    user = update.effective_user

    if not user or not is_admin(user.id):
        if update.message:
            await update.message.reply_text(
                "⛔ دسترسی مدیریت ندارید."
            )
        elif update.callback_query:
            await update.callback_query.answer(
                "⛔ دسترسی مدیریت ندارید.",
                show_alert=True
            )

        return False

    return True


def log_action(admin_id, action, details=""):
    conn = get_db()

    conn.execute(
        """
        INSERT INTO operation_logs
        (admin_id, action, details, created_at)
        VALUES (?, ?, ?, ?)
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


# =========================
# MAIN MENU
# =========================

def main_keyboard():
    return InlineKeyboardMarkup([
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
                "📋 سوابق شرکت",
                callback_data="history"
            )
        ],
        [
            InlineKeyboardButton(
                "🏆 برندگان",
                callback_data="winners"
            ),
            InlineKeyboardButton(
                "🗃 آرشیو",
                callback_data="archive"
            )
        ],
        [
            InlineKeyboardButton(
                "📜 قوانین",
                callback_data="rules"
            ),
            InlineKeyboardButton(
                "💬 پشتیبانی",
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
        ]
    ])


# =========================
# START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    conn = get_db()

    existing = conn.execute(
        "SELECT id FROM users WHERE id = ?",
        (user.id,)
    ).fetchone()

    # =====================================================
    # این قسمت منطق دعوت قبلی را حفظ می‌کند
    # =====================================================

    if not existing:

        referrer_id = None

        if context.args:

            arg = context.args[0]

            if arg.startswith("ref_"):

                possible_referrer = arg[4:]

                if possible_referrer.isdigit():

                    possible_referrer = int(possible_referrer)

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
            (
                id,
                first_name,
                username,
                chances,
                invited_by,
                created_at
            )
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
                    (
                        referrer_id,
                        referred_id,
                        created_at
                    )
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

    followers = get_int_setting(
        conn,
        "followers",
        0
    )

    activation = get_int_setting(
        conn,
        "activation_followers",
        100000
    )

    conn.close()

    if followers >= activation:

        status_text = (
            "🎉 قرعه‌کشی‌ها فعال شدند!"
        )

    else:

        status_text = (
            "🔒 قرعه‌کشی‌ها هنوز فعال نشده‌اند."
        )

    text = f"""
🎉 سلام {user.first_name or 'دوست عزیز'}!

به «محفل خوش‌شانس‌ها» خوش اومدی ❤️

{status_text}

🎁 کمپین‌ها و جوایز
👥 دعوت از دوستان
🎟 مدیریت شانس‌ها
📋 سوابق شرکت
🏆 برندگان

👇 از منوی زیر شروع کن:
"""

    if update.message:

        await update.message.reply_text(
            text,
            reply_markup=main_keyboard()
        )


# =========================
# HELP
# =========================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "ℹ️ راهنمای محفل\n\n"
        "🎁 کمپین‌ها و جوایز\n"
        "👤 پروفایل من\n"
        "🎟 شانس‌های من\n"
        "👥 دعوت از دوستان\n"
        "📋 سوابق شرکت\n"
        "🏆 برندگان\n"
        "🗃 آرشیو\n"
        "📜 قوانین\n"
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
        SELECT chances
        FROM users
        WHERE id = ?
        """,
        (user_id,)
    ).fetchone()

    conn.close()

    chances = row["chances"] if row else 0

    await query.message.reply_text(
        f"🎟 شانس‌های من\n\n"
        f"تعداد شانس‌های شما: {chances}\n\n"
        f"👥 با معرفی دوستان می‌توانید شانس‌های بیشتری "
        f"به دست بیاورید."
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
        SELECT COUNT(*)
        FROM referrals
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
        f"لینک را برای دوستانت ارسال کن.\n"
        f"با ورود موفق دوست جدید، یک شانس برای شما ثبت می‌شود. 🎟"
    )


# =========================
# CAMPAIGNS
# =========================

async def show_campaigns(query):

    conn = get_db()

    followers = get_int_setting(
        conn,
        "followers",
        0
    )

    activation = get_int_setting(
        conn,
        "activation_followers",
        100000
    )

    max_followers = get_int_setting(
        conn,
        "plan_max_followers",
        500000
    )

    daily_prize = get_int_setting(
        conn,
        "daily_prize_amount",
        10000000
    )

    campaigns = conn.execute(
        """
        SELECT *
        FROM campaigns
        WHERE active = 1
        AND archived = 0
        ORDER BY id DESC
        """
    ).fetchall()

    conn.close()

    if followers < activation:

        await query.message.reply_text(
            "🔒 قرعه‌کشی‌ها هنوز فعال نشده‌اند.\n\n"
            f"👥 فالوور ثبت‌شده: {followers:,}\n"
            f"🎯 حد فعال‌شدن: {activation:,}\n\n"
            "به‌محض رسیدن به حد تعیین‌شده، "
            "کمپین‌ها طبق تنظیمات مدیریت فعال می‌شوند."
        )

        return

    text = (
        "🎉 قرعه‌کشی‌ها فعال شدند!\n\n"
        f"📈 برنامه فعلی:\n"
        f"از {activation:,} تا {max_followers:,} فالوور\n"
        f"🎁 جایزه روزانه: {daily_prize:,} تومان\n\n"
    )

    if not campaigns:

        text += "🎁 در حال حاضر کمپین فعالی وجود ندارد."

        await query.message.reply_text(text)

        return

    keyboard = []

    for campaign in campaigns:

        keyboard.append([
            InlineKeyboardButton(
                f"🏆 {campaign['title']}",
                callback_data=f"campaign_{campaign['id']}"
            )
        ])

    await query.message.reply_text(
        text + "👇 کمپین موردنظر را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================
# CAMPAIGN DETAILS
# =========================

async def show_campaign_details(query, campaign_id):

    conn = get_db()

    campaign = conn.execute(
        """
        SELECT *
        FROM campaigns
        WHERE id = ?
        """,
        (campaign_id,)
    ).fetchone()

    followers = get_int_setting(
        conn,
        "followers",
        0
    )

    activation = get_int_setting(
        conn,
        "activation_followers",
        100000
    )

    existing_participation = conn.execute(
        """
        SELECT id
        FROM participations
        WHERE campaign_id = ?
        AND user_id = ?
        """,
        (
            campaign_id,
            query.from_user.id
        )
    ).fetchone()

    acceptance = conn.execute(
        """
        SELECT accepted
        FROM rule_acce
