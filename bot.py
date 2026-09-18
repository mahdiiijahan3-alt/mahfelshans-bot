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

# =========================================================
# SETTINGS
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

BOT_USERNAME = "MahfelShansBot"
DB_FILE = "mahfelshans.db"

INSTAGRAM_URL = "https://instagram.com/MAHFELSHANS"
YOUTUBE_URL = "https://youtube.com/@mahfelshans"


# =========================================================
# DATABASE
# =========================================================

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


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
    except (ValueError, TypeError):
        return default


def init_db():
    conn = get_db()

    # USERS
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
        conn,
        "users",
        "support_mode",
        "TEXT DEFAULT 'human'"
    )

    # REFERRALS
    conn.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER NOT NULL,
            referred_id INTEGER NOT NULL UNIQUE,
            created_at TEXT
        )
    """)

    # CAMPAIGNS
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
        conn,
        "campaigns",
        "rules",
        "TEXT DEFAULT ''"
    )

    add_column_if_missing(
        conn,
        "campaigns",
        "rules_version",
        "TEXT DEFAULT '1'"
    )

    add_column_if_missing(
        conn,
        "campaigns",
        "draw_at",
        "TEXT DEFAULT ''"
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

    # PARTICIPATIONS
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

    # RULE ACCEPTANCES
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

    # WINNERS
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

    # SUPPORT
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

    # PAYMENTS - READY FOR FUTURE
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

    # SETTINGS
    conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    defaults = {
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
            "نتیجه قرعه‌کشی و شرایط دریافت جایزه طبق قوانین "
            "اعلام‌شده همان کمپین خواهد بود."
        ),
    }

    for key, value in defaults.items():
        conn.execute(
            """
            INSERT OR IGNORE INTO settings (key, value)
            VALUES (?, ?)
            """,
            (key, value)
        )

    # LOGS
    conn.execute("""
        CREATE TABLE IF NOT EXISTS operation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER,
            action TEXT,
            details TEXT,
            created_at TEXT
        )
    """)

    # FIRST CAMPAIGN
    count = conn.execute(
        "SELECT COUNT(*) FROM campaigns"
    ).fetchone()[0]

    if count == 0:
        conn.execute(
            """
            INSERT INTO campaigns (
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


# =========================================================
# ADMIN
# =========================================================

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


# =========================================================
# MAIN MENU
# =========================================================

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


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not user:
        return

    conn = get_db()

    existing = conn.execute(
        "SELECT id FROM users WHERE id = ?",
        (user.id,)
    ).fetchone()

    # حفظ کامل منطق قبلی دعوت
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
            INSERT INTO users (
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
                    INSERT INTO referrals (
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

    else:

        conn.execute(
            """
            UPDATE users
            SET first_name = ?,
                username = ?
            WHERE id = ?
            """,
            (
                user.first_name or "",
                user.username or "",
                user.id
            )
        )

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

    conn.commit()
    conn.close()

    if followers >= activation:
        status_text = "🎉 قرعه‌کشی‌ها فعال شدند!"
    else:
        status_text = "🔒 قرعه‌کشی‌ها هنوز فعال نشده‌اند."

    text = (
        f"🎉 سلام {user.first_name or 'دوست عزیز'}!\n\n"
        "به «محفل خوش‌شانس‌ها» خوش اومدی ❤️\n\n"
        f"{status_text}\n\n"
        "🎁 کمپین‌ها و جوایز\n"
        "👥 دعوت از دوستان\n"
        "🎟 مدیریت شانس‌ها\n"
        "📋 سوابق شرکت\n"
        "🏆 برندگان\n\n"
        "👇 از منوی زیر شروع کن:"
    )

    if update.message:
        await update.message.reply_text(
            text,
            reply_markup=main_keyboard()
        )


# =========================================================
# HELP
# =========================================================

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


# =========================================================
# PROFILE
# =========================================================

async def show_profile(query):
    user_id = query.from_user.id

    conn = get_db()

    row = conn.execute(
        "SELECT * FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()

    referral_count = conn.execute(
        """
        SELECT COUNT(*)
        FROM referrals
        WHERE referrer_id = ?
        """,
        (user_id,)
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


# =========================================================
# CHANCES
# =========================================================

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
        "👥 با معرفی دوستان می‌توانید شانس‌های بیشتری "
        "به دست بیاورید."
    )


# =========================================================
# INVITE
# =========================================================

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
        "لینک را برای دوستانت ارسال کن.\n"
        "با ورود موفق دوست جدید، یک شانس برای شما ثبت می‌شود. 🎟"
    )


# =========================================================
# CAMPAIGNS
# =========================================================

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

        await query.message.reply_text(
            text + "🎁 در حال حاضر کمپین فعالی وجود ندارد."
        )

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


# =========================================================
# CAMPAIGN DETAILS
# =========================================================

async def show_campaign_details(query, campaign_id):
    conn = get_db()

    campaign = conn.execute(
        """
        SELECT *
        FROM campaigns
        WHERE id = ?
        AND active = 1
        AND archived = 0
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

    acceptance = conn.execute(
        """
        SELECT accepted
        FROM rule_acceptances
        WHERE user_id = ?
        AND campaign_id = ?
        """,
        (
            query.from_user.id,
            campaign_id
        )
    ).fetchone()

    participation = conn.execute(
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

    conn.close()

    if followers < activation:
        await query.message.reply_text(
            "🔒 قرعه‌کشی‌ها هنوز فعال نشده‌اند."
        )
        return

    if not campaign:
        await query.message.reply_text(
            "❌ این کمپین پیدا نشد."
        )
        return

    text = (
        f"🏆 {campaign['title']}\n\n"
        f"🎁 جایزه:\n{campaign['prize']}\n\n"
        f"📝 توضیحات:\n{campaign['description'] or '---'}\n\n"
    )

    if campaign["draw_at"]:
        text += f"🕐 زمان قرعه‌کشی: {campaign['draw_at']}\n\n"

    keyboard = []

    if participation:
        text += "✅ شما در این کمپین ثبت‌نام کرده‌اید.\n"
    elif acceptance and acceptance["accepted"]:

        keyboard.append([
            InlineKeyboardButton(
                "🎟 شرکت در کمپین",
                callback_data=f"join_{campaign_id}"
            )
        ])

    else:

        keyboard.append([
            InlineKeyboardButton(
                "📜 مشاهده و پذیرش قوانین",
                callback_data=f"rules_campaign_{campaign_id}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "🔙 کمپین‌ها",
            callback_data="campaigns"
        )
    ])

    await query.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================================================
# CAMPAIGN RULES
# =========================================================

async def show_campaign_rules(query, campaign_id):
    conn = get_db()

    campaign = conn.execute(
        """
        SELECT *
        FROM campaigns
        WHERE id = ?
        """,
        (campaign_id,)
    ).fetchone()

    conn.close()

    if not campaign:
        await query.message.reply_text(
            "❌ کمپین پیدا نشد."
        )
        return

    rules = campaign["rules"] or "قوانین این کمپین هنوز ثبت نشده است."

    text = (
        f"📜 قوانین کمپین\n\n"
        f"🏆 {campaign['title']}\n\n"
        f"{rules}\n\n"
        "«قوانین و شرایط شرکت در کمپین را مطالعه کردم و می‌پذیرم.»"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ می‌پذیرم و ادامه می‌دهم",
                callback_data=f"accept_{campaign_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 بازگشت",
                callback_data=f"campaign_{campaign_id}"
            )
        ]
    ])

    await query.message.reply_text(
        text,
        reply_markup=keyboard
    )


# =========================================================
# ACCEPT RULES
# =========================================================

async def accept_rules(query, campaign_id):
    user_id = query.from_user.id

    conn = get_db()

    campaign = conn.execute(
        """
        SELECT *
        FROM campaigns
        WHERE id = ?
        AND active = 1
        AND archived = 0
        """,
        (campaign_id,)
    ).fetchone()

    if not campaign:
        conn.close()

        await query.message.reply_text(
            "❌ کمپین فعال نیست."
        )
        return

    version = campaign["rules_version"] or "1"

    conn.execute(
        """
        INSERT INTO rule_acceptances (
            user_id,
            campaign_id,
            rules_version,
            accepted,
            accepted_at
        )
        VALUES (?, ?, ?, 1, ?)
        ON CONFLICT(user_id, campaign_id)
        DO UPDATE SET
            rules_version = excluded.rules_version,
            accepted = 1,
            accepted_at = excluded.accepted_at
        """,
        (
            user_id,
            campaign_id,
            version,
            datetime.utcnow().isoformat()
        )
    )

    conn.commit()
    conn.close()

    await query.message.reply_text(
        "✅ پذیرش قوانین ثبت شد.\n\n"
        "حالا می‌توانید در کمپین شرکت کنید.",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🎟 شرکت در کمپین",
                    callback_data=f"join_{campaign_id}"
                )
            ]
        ])
    )


# =========================================================
# JOIN CAMPAIGN
# =========================================================

async def join_campaign(query, campaign_id):
    user_id = query.from_user.id

    conn = get_db()

    campaign = conn.execute(
        """
        SELECT *
        FROM campaigns
        WHERE id = ?
        AND active = 1
        AND archived = 0
        """,
        (campaign_id,)
    ).fetchone()

    if not campaign:
        conn.close()

        await query.message.reply_text(
            "❌ این کمپین فعال نیست."
        )
        return

    accepted = conn.execute(
        """
        SELECT accepted
        FROM rule_acceptances
        WHERE user_id = ?
        AND campaign_id = ?
        """,
        (
            user_id,
            campaign_id
        )
    ).fetchone()

    if not accepted or not accepted["accepted"]:

        conn.close()

        await query.message.reply_text(
            "ابتدا باید قوانین کمپین را بپذیرید.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "📜 مشاهده قوانین",
                        callback_data=f"rules_campaign_{campaign_id}"
                    )
                ]
            ])
        )

        return

    already = conn.execute(
        """
        SELECT id
        FROM participations
        WHERE campaign_id = ?
        AND user_id = ?
        """,
        (
            campaign_id,
            user_id
        )
    ).fetchone()

    if already:

        conn.close()

        await query.message.reply_text(
            "✅ شما قبلاً در این کمپین ثبت‌نام کرده‌اید."
        )

        return

    conn.execute(
        """
        INSERT INTO participations (
            campaign_id,
            user_id,
            chances_used,
            created_at
        )
        VALUES (?, ?, 1, ?)
        """,
        (
            campaign_id,
            user_id,
            datetime.utcnow().isoformat()
        )
    )

    conn.commit()
    conn.close()

    await query.message.reply_text(
        "🎉 ثبت‌نام شما با موفقیت انجام شد!\n\n"
        f"🏆 کمپین: {campaign['title']}\n"
        "🎟 وضعیت: شرکت‌کننده ثبت شد."
    )


# =========================================================
# HISTORY
# =========================================================

async def show_history(query):
    user_id = query.from_user.id

    conn = get_db()

    rows = conn.execute(
        """
        SELECT
            p.created_at,
            c.title,
            c.prize
        FROM participations p
        JOIN campaigns c
        ON c.id = p.campaign_id
        WHERE p.user_id = ?
        ORDER BY p.id DESC
        """,
        (user_id,)
    ).fetchall()

    conn.close()

    if not rows:

        await query.message.reply_text(
            "📋 هنوز سابقه‌ای برای شرکت شما ثبت نشده است."
        )

        return

    text = "📋 سوابق شرکت من\n\n"

    for row in rows:

        text += (
            f"🏆 {row['title']}\n"
            f"🎁 {row['prize']}\n"
            f"📅 {row['created_at']}\n\n"
        )

    await query.message.reply_text(text)


# =========================================================
# WINNERS
# =========================================================

async def show_winners(query):
    conn = get_db()

    rows = conn.execute(
        """
        SELECT
            w.*,
            c.title,
            u.first_name,
            u.username
        FROM winners w
        JOIN campaigns c
        ON c.id = w.campaign_id
        JOIN users u
        ON u.id = w.user_id
        WHERE w.announced = 1
        ORDER BY w.id DESC
        LIMIT 50
        """
    ).fetchall()

    conn.close()

    if not rows:

        await query.message.reply_text(
            "🏆 هنوز برنده‌ای اعلام نشده است."
        )

        return

    text = "🏆 برندگان محفل\n\n"

    for row in rows:

        username = (
            f"@{row['username']}"
            if row["username"]
            else ""
        )

        text += (
            f"🏆 {row['title']}\n"
            f"👤 {row['first_name']} {username}\n"
            f"📅 {row['announced_at'] or ''}\n\n"
        )

    await query.message.reply_text(text)


# =========================================================
# ARCHIVE
# =========================================================

async def show_archive(query):
    conn = get_db()

    rows = conn.execute(
        """
        SELECT *
        FROM campaigns
        WHERE archived = 1
        ORDER BY id DESC
        """
    ).fetchall()

    conn.close()

    if not rows:

        await query.message.reply_text(
            "🗃 آرشیو هنوز خالی است."
        )

        return

    text = "🗃 آرشیو کمپین‌ها\n\n"

    for row in rows:

        text += (
            f"🏆 {row['title']}\n"
            f"🎁 {row['prize']}\n"
            f"🕐 {row['draw_at'] or '---'}\n\n"
        )

    await query.message.reply_text(text)


# =========================================================
# GENERAL RULES
# =========================================================

async def show_rules(query):
    conn = get_db()

    rules = get_setting(
        conn,
        "rules_text",
        "قوانین هنوز ثبت نشده است."
    )

    version = get_setting(
        conn,
        "rules_version",
        "1"
    )

    conn.close()

    await query.message.reply_text(
        f"📜 قوانین محفل\n\n"
        f"نسخه قوانین: {version}\n\n"
        f"{rules}"
    )


# =========================================================
# SUPPORT
# =========================================================

async def show_support(query):
    await query.message.reply_text(
        "💬 پشتیبانی محفل\n\n"
        "پیام یا سوالت را همینجا ارسال کن.\n"
        "پیام برای پشتیبانی ثبت می‌شود و مدیریت بررسی می‌کند."
    )


async def receive_support_message(update, context):
    if not update.message:
        return

    text = update.message.text

    if not text or text.startswith("/"):
        return

    user = update.effective_user

    if not user:
        return

    conn = get_db()

    conn.execute(
        """
        INSERT INTO support_tickets (
            user_id,
            message,
            status,
            created_at
        )
        VALUES (?, ?, 'open', ?)
        """,
        (
            user.id,
            text,
            datetime.utcnow().isoformat()
        )
    )

    ticket_id = conn.execute(
        "SELECT last_insert_rowid()"
    ).fetchone()[0]

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "✅ پیام شما ثبت شد.\n\n"
        f"🎫 شماره درخواست: {ticket_id}\n"
        "پشتیبانی آن را بررسی می‌کند."
    )

    # اطلاع به ادمین‌ها
    for admin_id in get_admin_ids():

        try:

            await context.bot.send_message(
                chat_id=admin_id,
                text=(
                    "🔔 درخواست پشتیبانی جدید\n\n"
                    f"🎫 شماره: {ticket_id}\n"
                    f"👤 کاربر: {user.first_name}\n"
                    f"🆔 ID: {user.id}\n\n"
                    f"💬 پیام:\n{text}\n\n"
                    f"برای پاسخ:\n"
                    f"/reply {user.id} متن پاسخ"
                )
            )

        except Exception as e:

            logging.warning(
                f"Cannot notify admin {admin_id}: {e}"
            )


# =========================================================
# ADMIN MENU
# =========================================================

async def admin_command(update, context):
    if not await admin_required(update):
        return

    await update.message.reply_text(
        "🔐 پنل مدیریت محفل\n\n"
        "/stats - آمار کلی\n"
        "/followers 100000 - تعداد فالوور\n"
        "/activation 100000 - حد فعال‌سازی\n"
        "/maxfollowers 500000 - سقف برنامه\n"
        "/dailyprize 10000000 - جایزه روزانه\n\n"
        "/newcampaign عنوان | توضیحات | جایزه\n"
        "/campaignsadmin - مدیریت کمپین‌ها\n"
        "/activate ID - فعال کردن کمپین\n"
        "/deactivate ID - غیرفعال کردن کمپین\n"
        "/drawdate ID تاریخ ساعت\n"
        "/rulesadmin متن قوانین\n\n"
        "/users - کاربران\n"
        "/referrals - دعوت‌ها\n"
        "/chancesadmin - شانس‌ها\n"
        "/participants ID - شرکت‌کنندگان\n"
        "/winner CAMPAIGN_ID USER_ID\n"
        "/announce ID - اعلام برنده\n"
        "/archive ID - آرشیو کمپین\n\n"
        "/tickets - درخواست‌های پشتیبانی\n"
        "/reply USER_ID متن\n"
        "/broadcast متن - ارسال همگانی\n"
        "/logs - گزارش عملیات"
    )


# =========================================================
# STATS
# =========================================================

async def stats_command(update, context):
    if not await admin_required(update):
        return

    conn = get_db()

    users = conn.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]

    referrals = conn.execute(
        "SELECT COUNT(*) FROM referrals"
    ).fetchone()[0]

    participants = conn.execute(
        "SELECT COUNT(*) FROM participations"
    ).fetchone()[0]

    campaigns = conn.execute(
        """
        SELECT COUNT(*)
        FROM campaigns
        WHERE active = 1
        AND archived = 0
        """
    ).fetchone()[0]

    followers = get_int_setting(
        conn,
        "followers",
        0
    )

    conn.close()

    await update.message.reply_text(
        "📊 آمار محفل\n\n"
        f"👤 کاربران: {users:,}\n"
        f"👥 معرفی موفق: {referrals:,}\n"
        f"🎟 شرکت‌ها: {participants:,}\n"
        f"🎁 کمپین‌های فعال: {campaigns:,}\n"
        f"📈 فالوورها: {followers:,}"
    )


# =========================================================
# FOLLOWERS
# =========================================================

async def followers_command(update, context):
    if not await admin_required(update):
        return

    if not context.args or not context.args[0].isdigit():

        await update.message.reply_text(
            "فرمت:\n/followers 100000"
        )
        return

    value = int(context.args[0])

    conn = get_db()
    set_setting(conn, "followers", value)
    conn.commit()
    conn.close()

    log_action(
        update.effective_user.id,
        "followers",
        str(value)
    )

    await update.message.reply_text(
        f"✅ تعداد فالوورها روی {value:,} تنظیم شد."
    )


# =========================================================
# ACTIVATION
# =========================================================

async def activation_command(update, context):
    if not await admin_required(update):
        return

    if not context.args or not context.args[0].isdigit():

        await update.message.reply_text(
            "فرمت:\n/activation 100000"
        )
        return

    value = int(context.args[0])

    conn = get_db()
    set_setting(conn, "activation_followers", value)
    conn.commit()
    conn.close()

    log_action(
        update.effective_user.id,
        "activation",
        str(value)
    )

    await update.message.reply_text(
        f"✅ حد فعال‌سازی روی {value:,} تنظیم شد."
    )


# =========================================================
# MAX FOLLOWERS
# =========================================================

async def maxfollowers_command(update, context):
    if not await admin_required(update):
        return

    if not context.args or not context.args[0].isdigit():

        await update.message.reply_text(
            "فرمت:\n/maxfollowers 500000"
        )
        return

    value = int(context.args[0])

    conn = get_db()
    set_setting(conn, "plan_max_followers", value)
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ سقف برنامه روی {value:,} تنظیم شد."
    )


# =========================================================
# DAILY PRIZE
# =========================================================

async def dailyprize_command(update, context):
    if not await admin_required(update):
        return

    if not context.args or not context.args[0].isdigit():

        await update.message.reply_text(
            "فرمت:\n/dailyprize 10000000"
        )
        return

    value = int(context.args[0])

    conn = get_db()
    set_setting(conn, "daily_prize_amount", value)
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ جایزه روزانه روی {value:,} تومان تنظیم شد."
    )


# =========================================================
# NEW CAMPAIGN
# =========================================================

async def newcampaign_command(update, context):
    if not await admin_required(update):
        return

    raw = " ".join(context.args)

    parts = [x.strip() for x in raw.split("|")]

    if len(parts) < 3:

        await update.message.reply_text(
            "فرمت درست:\n\n"
            "/newcampaign عنوان | توضیحات | جایزه"
        )
        return

    title = parts[0]
    description = parts[1]
    prize = parts[2]

    conn = get_db()

    rules = get_setting(
        conn,
        "rules_text",
        ""
    )

    version = get_setting(
        conn,
        "rules_version",
        "1"
    )

    conn.execute(
        """
        INSERT INTO campaigns (
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
        VALUES (?, ?, ?, 0, ?, ?, ?, '', 0, 0)
        """,
        (
            title,
            description,
            prize,
            datetime.utcnow().isoformat(),
            rules,
            version
        )
    )

    campaign_id = conn.execute(
        "SELECT last_insert_rowid()"
    ).fetchone()[0]

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ کمپین ساخته شد.\n\n"
        f"ID: {campaign_id}\n"
        f"🏆 {title}\n\n"
        "برای فعال‌سازی:\n"
        f"/activate {campaign_id}"
    )


# =========================================================
# CAMPAIGNS ADMIN
# =========================================================

async def campaignsadmin_command(update, context):
    if not await admin_required(update):
        return

    conn = get_db()

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
            "هیچ کمپینی وجود ندارد."
        )
        return

    text = "🎁 مدیریت کمپین‌ها\n\n"

    for row in rows:

        status = "فعال" if row["active"] else "غیرفعال"
        archived = "آرشیو" if row["archived"] else ""

        text += (
            f"ID: {row['id']}\n"
            f"🏆 {row['title']}\n"
            f"وضعیت: {status} {archived}\n"
            f"🎁 {row['prize']}\n"
            f"🕐 {row['draw_at'] or '---'}\n\n"
        )

    await update.message.reply_text(text)


# =========================================================
# ACTIVATE
# =========================================================

async def activate_command(update, context):
    if not await admin_required(update):
        return

    if not context.args or not context.args[0].isdigit():

        await update.message.reply_text(
            "فرمت:\n/activate 1"
        )
        return

    campaign_id = int(context.args[0])

    conn = get_db()

    conn.execute(
        """
        UPDATE campaigns
        SET active = 1,
            archived = 0
        WHERE id = ?
        """,
        (campaign_id,)
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ کمپین {campaign_id} فعال شد."
    )


# =========================================================
# DEACTIVATE
# =========================================================

async def deactivate_command(update, context):
    if not await admin_required(update):
        return

    if not context.args or not context.args[0].isdigit():

        await update.message.reply_text(
            "فرمت:\n/deactivate 1"
        )
        return

    campaign_id = int(context.args[0])

    conn = get_db()

    conn.execute(
        """
        UPDATE campaigns
        SET active = 0
        WHERE id = ?
        """,
        (campaign_id,)
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"⛔ کمپین {campaign_id} غیرفعال شد."
    )


# =========================================================
# DRAW DATE
# =========================================================

async def drawdate_command(update, context):
    if not await admin_required(update):
        return

    if len(context.args) < 3:

        await update.message.reply_text(
            "فرمت:\n"
            "/drawdate 1 2026-10-01 20:00"
        )
        return

    campaign_id = context.args[0]

    if not campaign_id.isdigit():

        await update.message.reply_text(
            "ID کمپین باید عدد باشد."
        )
        return

    draw_at = f"{context.args[1]} {context.args[2]}"

    conn = get_db()

    conn.execute(
        """
        UPDATE campaigns
        SET draw_at = ?
        WHERE id = ?
        """,
        (
            draw_at,
            int(campaign_id)
        )
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ زمان قرعه‌کشی تنظیم شد:\n{draw_at}"
    )


# =========================================================
# RULES ADMIN
# =========================================================

async def rulesadmin_command(update, context):
    if not await admin_required(update):
        return

    text = " ".join(context.args).strip()

    if not text:

        await update.message.reply_text(
            "فرمت:\n"
            "/rulesadmin متن قوانین"
        )
        return

    conn = get_db()

    old_version = get_setting(
        conn,
        "rules_version",
        "1"
    )

    try:
        version = str(int(old_version) + 1)
    except (ValueError, TypeError):
        version = "2"

    set_setting(conn, "rules_text", text)
    set_setting(conn, "rules_version", version)

    conn.execute(
        """
        UPDATE campaigns
        SET rules = ?,
            rules_version = ?
        WHERE active = 0
        """,
        (
            text,
            version
        )
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ قوانین ثبت شد.\n"
        f"نسخه جدید: {version}"
    )


# =========================================================
# USERS
# =========================================================

async def users_command(update, context):
    if not await admin_required(update):
        return

    conn = get_db()

    rows = conn.execute(
        """
        SELECT id, first_name, username, chances, created_at
        FROM users
        ORDER BY id DESC
        LIMIT 50
        """
    ).fetchall()

    total = conn.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]

    conn.close()

    text = f"👤 کاربران\nکل کاربران: {total:,}\n\n"

    for row in rows:

        username = (
            f"@{row['username']}"
            if row["username"]
            else ""
        )

        text += (
            f"ID: {row['id']}\n"
            f"👤 {row['first_name']} {username}\n"
            f"🎟 {row['chances']}\n\n"
        )

    await update.message.reply_text(text[:4000])


# =========================================================
# REFERRALS ADMIN
# =========================================================

async def referrals_command(update, context):
    if not await admin_required(update):
        return

    conn = get_db()

    rows = conn.execute(
        """
        SELECT
            referrer_id,
            COUNT(*) AS total
        FROM referrals
        GROUP BY referrer_id
        ORDER BY total DESC
        LIMIT 50
        """
    ).fetchall()

    conn.close()

    if not rows:

        await update.message.reply_text(
            "👥 هنوز معرفی‌ای ثبت نشده است."
        )
        return

    text = "👥 آمار دعوت‌ها\n\n"

    for row in rows:

        text += (
            f"👤 User ID: {row['referrer_id']}\n"
            f"👥 معرفی موفق: {row['total']}\n\n"
        )

    await update.message.reply_text(text)


# =========================================================
# CHANCES ADMIN
# =========================================================

async def chancesadmin_command(update, context):
    if not await admin_required(update):
        return

    conn = get_db()

    rows = conn.execute(
        """
        SELECT id, first_name, username, chances
        FROM users
        ORDER BY chances DESC
        LIMIT 50
        """
    ).fetchall()

    conn.close()

    text = "🎟 بیشترین شانس‌ها\n\n"

    for row in rows:

        text += (
            f"ID: {row['id']}\n"
            f"👤 {row['first_name']}\n"
            f"🎟 {row['chances']}\n\n"
        )

    await update.message.reply_text(text)


# =========================================================
# PARTICIPANTS
# =========================================================

async def participants_command(update, context):
    if not await admin_required(update):
        return

    if not context.args or not context.args[0].isdigit():

        await update.message.reply_text(
            "فرمت:\n/participants 1"
        )
        return

    campaign_id = int(context.args[0])

    conn = get_db()

    rows = conn.execute(
        """
        SELECT
            p.user_id,
            p.created_at,
            u.first_name,
            u.username
        FROM participations p
        JOIN users u
        ON u.id = p.user_id
        WHERE p.campaign_id = ?
        ORDER BY p.id DESC
        """,
        (campaign_id,)
    ).fetchall()

    conn.close()

    text = (
        f"👥 شرکت‌کنندگان کمپین {campaign_id}\n\n"
        f"تعداد: {len(rows)}\n\n"
    )

    for row in rows[:100]:

        text += (
            f"🆔 {row['user_id']}\n"
            f"👤 {row['first_name']}\n"
            f"@{row['username'] if row['username'] else '---'}\n\n"
        )

    await update.message.reply_text(text[:4000])


# =========================================================
# REGISTER WINNER
# =========================================================

async def winner_command(update, context):
    if not await admin_required(update):
        return

    if len(context.args) < 2:

        await update.message.reply_text(
            "فرمت:\n/winner CAMPAIGN_ID USER_ID"
        )
        return

    if not context.args[0].isdigit() or not context.args[1].isdigit():

        await update.message.reply_text(
            "هر دو ID باید عدد باشند."
        )
        return

    campaign_id = int(context.args[0])
    user_id = int(context.args[1])

    conn = get_db()

    participant = conn.execute(
        """
        SELECT id
        FROM participations
        WHERE campaign_id = ?
        AND user_id = ?
        """,
        (
            campaign_id,
            user_id
        )
    ).fetchone()

    if not participant:

        conn.close()

        await update.message.reply_text(
            "❌ این کاربر شرکت‌کننده این کمپین نیست."
        )
        return

    try:

        conn.execute(
            """
            INSERT INTO winners (
                campaign_id,
                user_id,
                announced,
                created_at
            )
            VALUES (?, ?, 0, ?)
            """,
            (
                campaign_id,
                user_id,
                datetime.utcnow().isoformat()
            )
        )

        conn.commit()

    except sqlite3.IntegrityError:

        conn.close()

        await update.message.reply_text(
            "❌ برای این کمپین قبلاً برنده ثبت شده است."
        )
        return

    conn.close()

    await update.message.reply_text(
        "✅ برنده ثبت شد.\n\n"
        f"کمپین: {campaign_id}\n"
        f"کاربر: {user_id}\n\n"
        "برای اعلام عمومی:\n"
        f"/announce {campaign_id}"
    )


# =========================================================
# ANNOUNCE WINNER
# =========================================================

async def announce_command(update, context):
    if not await admin_required(update):
        return

    if not context.args or not context.args[0].isdigit():

        await update.message.reply_text(
            "فرمت:\n/announce 1"
        )
        return

    campaign_id = int(context.args[0])

    conn = get_db()

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
        ON c.id = w.campaign_id
        JOIN users u
        ON u.id = w.user_id
        WHERE w.campaign_id = ?
        """,
        (campaign_id,)
    ).fetchone()

    if not row:

        conn.close()

        await update.message.reply_text(
            "❌ برنده‌ای برای این کمپین ثبت نشده است."
        )
        return

    announced_at = datetime.utcnow().isoformat()

    conn.execute(
        """
        UPDATE winners
        SET announced = 1,
            announced_at = ?
        WHERE campaign_id = ?
        """,
        (
            announced_at,
            campaign_id
        )
    )

    conn.commit()

    users = conn.execute(
        "SELECT id FROM users"
    ).fetchall()

    conn.close()

    username = (
        f"@{row['username']}"
        if row["username"]
        else ""
    )

    announcement = (
        "🏆 برنده جدید محفل خوش‌شانس‌ها 🎉\n\n"
        f"🎁 کمپین: {row['title']}\n"
        f"👤 برنده: {row['first_name']} {username}\n"
        f"🎁 جایزه: {row['prize']}\n\n"
        "تبریک به برنده ❤️"
    )

    sent = 0

    for user in users:

        try:

            await context.bot.send_message(
                chat_id=user["id"],
                text=announcement
            )

            sent += 1

        except Exception:
            pass

    await update.message.reply_text(
        f"✅ برنده اعلام شد.\n"
        f"📨 ارسال موفق: {sent}"
    )


# =========================================================
# ARCHIVE ADMIN
# =========================================================

async def archive_command(update, context):
    if not await admin_required(update):
        return

    if not context.args or not context.args[0].isdigit():

        await update.message.reply_text(
            "فرمت:\n/archive 1"
        )
        return

    campaign_id = int(context.args[0])

    conn = get_db()

    conn.execute(
        """
        UPDATE campaigns
        SET archived = 1,
            active = 0
        WHERE id = ?
        """,
        (campaign_id,)
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"🗃 کمپین {campaign_id} به آرشیو منتقل شد."
    )


# =========================================================
# BROADCAST
# =========================================================

async def broadcast_command(update, context):
    if not await admin_required(update):
        return

    text = " ".join(context.args).strip()

    if not text:

        await update.message.reply_text(
            "فرمت:\n/broadcast متن پیام"
        )
        return

    conn = get_db()

    users = conn.execute(
        "SELECT id FROM users"
    ).fetchall()

    conn.close()

    sent = 0

    for user in users:

        try:

            await context.bot.send_message(
                chat_id=user["id"],
                text=text
            )

            sent += 1

        except Exception:
            pass

    await update.message.reply_text(
        f"📢 پیام همگانی ارسال شد.\n"
        f"تعداد موفق: {sent}"
    )


# =========================================================
# TICKETS
# =========================================================

async def tickets_command(update, context):
    if not await admin_required(update):
        return

    conn = get_db()

    rows = conn.execute(
        """
        SELECT *
        FROM support_tickets
        WHERE status = 'open'
        ORDER BY id DESC
        LIMIT 30
        """
    ).fetchall()

    conn.close()

    if not rows:

        await update.message.reply_text(
            "💬 درخواست باز وجود ندارد."
        )
        return

    text = "💬 درخواست‌های پشتیبانی باز\n\n"

    for row in rows:

        text += (
            f"🎫 Ticket: {row['id']}\n"
            f"👤 User: {row['user_id']}\n"
            f"💬 {row['message']}\n\n"
        )

    await update.message.reply_text(text[:4000])


# =========================================================
# REPLY
# =========================================================

async def reply_command(update, context):
    if not await admin_required(update):
        return

    if len(context.args) < 2:

        await update.message.reply_text(
            "فرمت:\n/reply USER_ID متن پاسخ"
        )
        return

    if not context.args[0].isdigit():

        await update.message.reply_text(
            "USER_ID باید عدد باشد."
        )
        return

    user_id = int(context.args[0])
    reply_text = " ".join(context.args[1:])

    try:

        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "💬 پاسخ پشتیبانی محفل:\n\n"
                f"{reply_text}"
            )
        )

    except Exception as e:

        await update.message.reply_text(
            f"❌ ارسال پیام انجام نشد:\n{e}"
        )
        return

    conn = get_db()

    ticket = conn.execute(
        """
        SELECT id
        FROM support_tickets
        WHERE user_id = ?
        AND status = 'open'
        ORDER BY id DESC
        LIMIT 1
        """,
        (user_id,)
    ).fetchone()

    if ticket:

        conn.execute(
            """
            UPDATE support_tickets
            SET status = 'closed',
                admin_reply = ?,
                replied_at = ?
            WHERE id = ?
            """,
            (
                reply_text,
                datetime.utcnow().isoformat(),
                ticket["id"]
            )
        )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "✅ پاسخ برای کاربر ارسال شد."
    )


# =========================================================
# LOGS
# =========================================================

async def logs_command(update, context):
    if not await admin_required(update):
        return

    conn = get_db()

    rows = conn.execute(
        """
        SELECT *
        FROM operation_logs
        ORDER BY id DESC
        LIMIT 50
        """
    ).fetchall()

    conn.close()

    if not rows:

        await update.message.reply_text(
            "گزارشی ثبت نشده است."
        )
        return

    text = "📋 گزارش عملیات\n\n"

    for row in rows:

        text += (
            f"👤 Admin: {row['admin_id']}\n"
            f"⚙️ {row['action']}\n"
            f"📝 {row['details']}\n"
            f"🕐 {row['created_at']}\n\n"
        )

    await update.message.reply_text(text[:4000])


# =========================================================
# BUTTON HANDLER
# =========================================================

async def button_handler(update, context):
    query = update.callback_query

    await query.answer()

    data = query.data

    if data == "campaigns":
        await show_campaigns(query)

    elif data == "profile":
        await show_profile(query)

    elif data == "chances":
        await show_chances(query)

    elif data == "invite":
        await show_invite(query)

    elif data == "history":
        await show_history(query)

    elif data == "winners":
        await show_winners(query)

    elif data == "archive":
        await show_archive(query)

    elif data == "rules":
        await show_rules(query)

    elif data == "support":
        await show_support(query)

    elif data.startswith("campaign_"):

        campaign_id = data.split("_")[1]

        if campaign_id.isdigit():
            await show_campaign_details(
                query,
                int(campaign_id)
            )

    elif data.startswith("rules_campaign_"):

        campaign_id = data.replace(
            "rules_campaign_",
            ""
        )

        if campaign_id.isdigit():
            await show_campaign_rules(
                query,
                int(campaign_id)
            )

    elif data.startswith("accept_"):

        campaign_id = data.replace(
            "accept_",
            ""
        )

        if campaign_id.isdigit():
            await accept_rules(
                query,
                int(campaign_id)
            )

    elif data.startswith("join_"):

        campaign_id = data.replace(
            "join_",
            ""
        )

        if campaign_id.isdigit():
            await join_campaign(
                query,
                int(campaign_id)
            )


# =========================================================
# MAIN
# =========================================================

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

    # USER COMMANDS
    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        CommandHandler("help", help_command)
    )

    # ADMIN COMMANDS
    app.add_handler(
        CommandHandler("admin", admin_command)
    )

    app.add_handler(
        CommandHandler("stats", stats_command)
    )

    app.add_handler(
        CommandHandler("followers", followers_command)
    )

    app.add_handler(
        CommandHandler("activation", activation_command)
    )

    app.add_handler(
        CommandHandler("maxfollowers", maxfollowers_command)
    )

    app.add_handler(
        CommandHandler("dailyprize", dailyprize_command)
    )

    app.add_handler(
        CommandHandler("newcampaign", newcampaign_command)
    )

    app.add_handler(
        CommandHandler("campaignsadmin", campaignsadmin_command)
    )

    app.add_handler(
        CommandHandler("activate", activate_command)
    )

    app.add_handler(
        CommandHandler("deactivate", deactivate_command)
    )

    app.add_handler(
        CommandHandler("drawdate", drawdate_command)
    )

    app.add_handler(
        CommandHandler("rulesadmin", rulesadmin_command)
    )

    app.add_handler(
        CommandHandler("users", users_command)
    )

    app.add_handler(
        CommandHandler("referrals", referrals_command)
    )

    app.add_handler(
        CommandHandler("chancesadmin", chancesadmin_command)
    )

    app.add_handler(
        CommandHandler("participants", participants_command)
    )

    app.add_handler(
        CommandHandler("winner", winner_command)
    )

    app.add_handler(
        CommandHandler("announce", announce_command)
    )

    app.add_handler(
        CommandHandler("archive", archive_command)
    )

    app.add_handler(
        CommandHandler("broadcast", broadcast_command)
    )

    app.add_handler(
        CommandHandler("tickets", tickets_command)
    )

    app.add_handler(
        CommandHandler("reply", reply_command)
    )

    app.add_handler(
        CommandHandler("logs", logs_command)
    )

    # BUTTONS
    app.add_handler(
        CallbackQueryHandler(button_handler)
    )

    # TEXT / SUPPORT
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


if __name__ == "__main__":
    asyncio.run(main())
