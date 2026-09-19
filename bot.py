import os
import sqlite3
import logging
import asyncio
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
    ContextTypes,
    MessageHandler,
    filters,
)

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# ============================================================
# CONFIG
# ============================================================

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
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "").strip()
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "").strip()

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


# ============================================================
# GENERAL
# ============================================================

RULES_VERSION = "1.0"

INSTAGRAM_VERIFICATION_ENABLED = False
YOUTUBE_VERIFICATION_ENABLED = False
TELEGRAM_MEMBERSHIP_REQUIRED = True


# ============================================================
# DATABASE
# ============================================================

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
            sponsor_id INTEGER,
            sponsor_name TEXT,
            sponsor_budget REAL DEFAULT 0,
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
            chance_number INTEGER,
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
            status TEXT DEFAULT 'open',
            created_at TEXT,
            replied_at TEXT,
            reply TEXT
        )
    """)

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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

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
            "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)",
            (key, value)
        )

    conn.commit()
    conn.close()


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

    conn.execute("""
        INSERT INTO settings(key, value)
        VALUES(?, ?)
        ON CONFLICT(key)
        DO UPDATE SET value=excluded.value
    """, (key, str(value)))

    conn.commit()
    conn.close()


def log_operation(admin_id, action, details=""):
    conn = db_connect()

    conn.execute("""
        INSERT INTO operation_logs(
            admin_id,
            action,
            details,
            created_at
        )
        VALUES(?,?,?,?)
    """, (
        admin_id,
        action,
        details,
        datetime.utcnow().isoformat()
    ))

    conn.commit()
    conn.close()


# ============================================================
# USER FUNCTIONS
# ============================================================

def get_user(user_id):
    conn = db_connect()

    row = conn.execute(
        "SELECT * FROM users WHERE id=?",
        (user_id,)
    ).fetchone()

    conn.close()

    return row


def create_user(tg_user, referred_by=None):
    conn = db_connect()

    existing = conn.execute(
        "SELECT * FROM users WHERE id=?",
        (tg_user.id,)
    ).fetchone()

    if existing:
        conn.execute("""
            UPDATE users
            SET first_name=?,
                username=?
            WHERE id=?
        """, (
            tg_user.first_name or "",
            tg_user.username or "",
            tg_user.id
        ))

        conn.commit()
        conn.close()

        return False

    conn.execute("""
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
    """, (
        tg_user.id,
        tg_user.first_name or "",
        tg_user.username or "",
        datetime.utcnow().isoformat(),
        1,
        referred_by,
        1
    ))

    if referred_by and referred_by != tg_user.id:
        inviter = conn.execute(
            "SELECT id FROM users WHERE id=?",
            (referred_by,)
        ).fetchone()

        if inviter:
            try:
                conn.execute("""
                    INSERT INTO referrals(
                        inviter_id,
                        invited_id,
                        created_at
                    )
                    VALUES(?,?,?)
                """, (
                    referred_by,
                    tg_user.id,
                    datetime.utcnow().isoformat()
                ))

                conn.execute("""
                    UPDATE users
                    SET chances = chances + 1
                    WHERE id=?
                """, (referred_by,))

            except sqlite3.IntegrityError:
                pass

    conn.commit()
    conn.close()

    return True


def accept_rules(user_id):
    conn = db_connect()

    conn.execute("""
        UPDATE users
        SET accepted_rules=1,
            rules_version=?
        WHERE id=?
    """, (
        RULES_VERSION,
        user_id
    ))

    conn.execute("""
        INSERT INTO rule_acceptances(
            user_id,
            rules_version,
            accepted_at
        )
        VALUES(?,?,?)
    """, (
        user_id,
        RULES_VERSION,
        datetime.utcnow().isoformat()
    ))

    conn.commit()
    conn.close()


# ============================================================
# NETWORK STATUS
# ============================================================

def get_network_counts():
    return {
        "instagram": int(get_setting("instagram_followers", "0") or 0),
        "youtube": int(get_setting("youtube_followers", "0") or 0),
        "telegram": int(get_setting("telegram_followers", "0") or 0),
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
        and counts["youtube"] >= target
        and counts["telegram"] >= target
    )


def lottery_is_active():
    return all_networks_reached()


def network_status_text():
    counts = get_network_counts()
    target = activation_target()

    active = all_networks_reached()

    status = "🟢 قرعه‌کشی فعال شده است" if active else "🔴 هنوز فعال نشده است"

    return (
        "📊 وضعیت شبکه محفل خوش‌شانس‌ها\n\n"
        f"📸 اینستاگرام: {counts['instagram']:,}\n"
        f"▶️ یوتیوب: {counts['youtube']:,}\n"
        f"📢 تلگرام: {counts['telegram']:,}\n\n"
        f"🎯 هدف فعال شدن قرعه‌کشی: {target:,}\n\n"
        f"وضعیت: {status}"
    )


# ============================================================
# YOUTUBE API
# ============================================================

def get_youtube_subscribers():
    if not YOUTUBE_API_KEY:
        return None

    try:
        params = urlencode({
            "part": "statistics",
            "forHandle": YOUTUBE_HANDLE,
            "key": YOUTUBE_API_KEY,
        })

        url = (
            "https://www.googleapis.com/youtube/v3/channels?"
            + params
        )

        request = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        with urlopen(request, timeout=20) as response:
            data = response.read().decode("utf-8")

        import json

        payload = json.loads(data)

        items = payload.get("items", [])

        if not items:
            return None

        statistics = items[0].get("statistics", {})

        count = statistics.get("subscriberCount")

        if count is None:
            return None

        return int(count)

    except Exception as e:
        logger.warning(
            "YouTube subscriber error: %s",
            e
        )

        return None


# ============================================================
# TELEGRAM MEMBERSHIP
# ============================================================

async def check_telegram_membership(bot, user_id):
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

    except Exception as e:
        logger.warning(
            "Telegram membership check error: %s",
            e
        )

        return False


# ============================================================
# ELIGIBILITY
# ============================================================

def eligibility_keyboard():
    bot_url = f"https://t.me/{BOT_USERNAME}"

    return InlineKeyboardMarkup([
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
            ),
        ],
        [
            InlineKeyboardButton(
                "🔄 بررسی عضویت",
                callback_data="verify_membership"
            )
        ],
        [
            InlineKeyboardButton(
                "🎧 پشتیبانی",
                url=bot_url
            )
        ],
    ])


async def verify_membership(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            "ابتدا وارد کانال محفل خوش‌شانس‌ها شوید و سپس "
            "روی «🔄 بررسی عضویت» بزنید.",
            reply_markup=eligibility_keyboard()
        )
        return

    await query.edit_message_text(
        "✅ عضویت تلگرام شما تأیید شد.\n\n"
        "📸 دنبال کردن اینستاگرام\n"
        "▶️ دنبال کردن یوتیوب\n"
        "📢 عضویت تلگرام\n\n"
        "این موارد برای دریافت جایزه الزامی هستند.\n\n"
        "⚠️ در نسخه فعلی، بررسی خودکار اینستاگرام و یوتیوب "
        "هنوز فعال نشده و در مرحله بعد به سیستم اضافه می‌شود.",
        reply_markup=InlineKeyboardMarkup([
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
        ])
    )


# ============================================================
# MAIN MENU
# ============================================================

def main_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🎁 مسابقات",
                callback_data="campaigns"
            ),
            InlineKeyboardButton(
                "👤 پروفایل",
                callback_data="profile"
            ),
        ],
        [
            InlineKeyboardButton(
                "🎟 شانس‌های من",
                callback_data="chances"
            ),
            InlineKeyboardButton(
                "👥 دعوت دوستان",
                callback_data="invite"
            ),
        ],
        [
            InlineKeyboardButton(
                "🏆 برندگان",
                callback_data="winners"
            ),
            InlineKeyboardButton(
                "📜 آرشیو",
                callback_data="archive"
            ),
        ],
        [
            InlineKeyboardButton(
                "📋 قوانین",
                callback_data="rules"
            ),
            InlineKeyboardButton(
                "🎧 پشتیبانی",
                callback_data="support"
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
                url=TELEGRAM_URL
            )
        ],
    ])


# ============================================================
# RULES
# ============================================================

RULES_TEXT = """
📋 قوانین محفل خوش‌شانس‌ها

1️⃣ ثبت‌نام و دریافت شانس در این مرحله رایگان است.

2️⃣ برای دریافت شانس بیشتر می‌توانید دوستان خود را دعوت کنید.

3️⃣ برای دریافت جایزه، رعایت شرایط اعلام‌شده مسابقه الزامی است.

4️⃣ عضویت در کانال تلگرام برای دریافت جایزه الزامی است.

5️⃣ دنبال کردن اینستاگرام و یوتیوب نیز جزو شرایط دریافت جایزه است.
بررسی خودکار این دو مورد در مرحله بعد به سیستم اضافه می‌شود.

6️⃣ قرعه‌کشی پس از رسیدن شبکه‌های تعیین‌شده به حد فعال‌سازی انجام می‌شود.

7️⃣ در حال حاضر هدف فعال‌سازی:
100,000 دنبال‌کننده / عضو برای هر شبکه تعیین شده است.

8️⃣ محفل خوش‌شانس‌ها در این مرحله هیچ مبلغی بابت شانس قرعه‌کشی دریافت نمی‌کند.

9️⃣ در صورت عدم رعایت شرایط جایزه، امکان عدم تأیید یا لغو جایزه وجود دارد.

🔟 تصمیم نهایی درباره اجرای هر کمپین مطابق قوانین همان کمپین اعلام خواهد شد.
"""


# ============================================================
# START
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    referred_by = None

    if context.args:
        arg = context.args[0].strip()

        if arg.startswith("ref_"):
            try:
                referred_by = int(
                    arg.replace("ref_", "", 1)
                )
            except ValueError:
                referred_by = None

    is_new = create_user(
        user,
        referred_by=referred_by
    )

    db_user = get_user(user.id)

    if not db_user:
        return

    if not db_user["accepted_rules"]:
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ مطالعه و پذیرش قوانین",
                    callback_data="accept_rules"
                )
            ]
        ])

        await update.message.reply_text(
            "🎉 به محفل خوش‌شانس‌ها خوش آمدید!\n\n"
            "قبل از شروع، قوانین را مطالعه و تأیید کنید.\n\n"
            "🎁 ثبت‌نام رایگان است.",
            reply_markup=keyboard
        )

        return

    await update.message.reply_text(
        "🎉 خوش آمدی به محفل خوش‌شانس‌ها!\n\n"
        "🎁 ثبت‌نام رایگان است.\n"
        "👥 با دعوت دوستان شانس بیشتری می‌گیری.\n"
        "🏆 با رسیدن شبکه به هدف ۱۰۰ هزار، قرعه‌کشی فعال می‌شود.",
        reply_markup=main_menu()
    )


# ============================================================
# ACCEPT RULES
# ============================================================

async def accept_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    await query.answer()

    accept_rules(query.from_user.id)

    await query.edit_message_text(
        "✅ قوانین با موفقیت پذیرفته شد.\n\n"
        "به محفل خوش‌شانس‌ها خوش آمدی! 🎉\n\n"
        "🎁 ثبت‌نام رایگان است.\n"
        "👥 دوستانت را دعوت کن و شانس بیشتری بگیر.\n"
        "🏆 قرعه‌کشی پس از رسیدن شبکه به هدف فعال می‌شود.",
        reply_markup=main_menu()
    )


# ============================================================
# CAMPAIGNS
# ============================================================

async def show_campaigns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    await query.answer()

    if not lottery_is_active():
        await query.edit_message_text(
            "⏳ قرعه‌کشی هنوز فعال نشده است.\n\n"
            f"🎯 هدف فعال‌سازی: {activation_target():,}\n\n"
            "برای باز شدن قرعه‌کشی باید شبکه‌های محفل "
            "به حد تعیین‌شده برسند.\n\n"
            + network_status_text(),
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "📢 عضویت تلگرام",
                        url=TELEGRAM_URL
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔙 بازگشت",
                        callback_data="back_main"
                    )
                ]
            ])
        )
        return

    conn = db_connect()

    rows = conn.execute("""
        SELECT *
        FROM campaigns
        WHERE status='active'
        ORDER BY id DESC
    """).fetchall()

    conn.close()

    if not rows:
        await query.edit_message_text(
            "🎁 در حال حاضر مسابقه فعالی وجود ندارد.\n\n"
            "به‌زودی مسابقات جدید اعلام می‌شود.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 بازگشت",
                        callback_data="back_main"
                    )
                ]
            ])
        )
        return

    buttons = []

    for campaign in rows:
        buttons.append([
            InlineKeyboardButton(
                f"🎁 {campaign['title']}",
                callback_data=f"campaign_{campaign['id']}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(
            "🔙 بازگشت",
            callback_data="back_main"
        )
    ])

    await query.edit_message_text(
        "🎁 مسابقات فعال\n\n"
        "یک مسابقه را انتخاب کن:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def show_campaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    await query.answer()

    try:
        campaign_id = int(
            query.data.split("_", 1)[1]
        )
    except Exception:
        return

    conn = db_connect()

    campaign = conn.execute(
        "SELECT * FROM campaigns WHERE id=?",
        (campaign_id,)
    ).fetchone()

    conn.close()

    if not campaign:
        await query.edit_message_text(
            "❌ مسابقه پیدا نشد.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 بازگشت",
                        callback_data="campaigns"
                    )
                ]
            ])
        )
        return

    text = (
        f"🎁 {campaign['title']}\n\n"
        f"{campaign['description'] or ''}\n\n"
        f"🏆 جایزه: {campaign['prize']}\n"
        f"🎯 تعداد جوایز: {campaign['prize_count']}\n\n"
        "📌 شرایط دریافت جایزه:\n"
        "📢 عضویت در کانال تلگرام الزامی است.\n"
        "📸 دنبال کردن اینستاگرام الزامی است.\n"
        "▶️ دنبال کردن یوتیوب الزامی است.\n\n"
        "⚠️ بررسی خودکار اینستاگرام و یوتیوب در نسخه فعلی "
        "هنوز فعال نشده و در مرحله بعد اضافه خواهد شد."
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔐 بررسی شرایط شرکت",
                callback_data="verify_membership"
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
                "📢 تلگرام",
                url=TELEGRAM_URL
            ),
            InlineKeyboardButton(
                "📸 اینستاگرام",
                url=INSTAGRAM_URL
            ),
        ],
        [
            InlineKeyboardButton(
                "▶️ یوتیوب",
                url=YOUTUBE_URL
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 مسابقات",
                callback_data="campaigns"
            )
        ]
    ])

    await query.edit_message_text(
        text,
        reply_markup=keyboard
    )


# ============================================================
# JOIN CAMPAIGN
# ============================================================

async def join_campaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    await query.answer()

    try:
        campaign_id = int(
            query.data.split("_", 1)[1]
        )
    except Exception:
        return

    user_id = query.from_user.id

    user = get_user(user_id)

    if not user:
        await query.edit_message_text(
            "ابتدا /start را بزنید."
        )
        return

    if not user["accepted_rules"]:
        await query.edit_message_text(
            "ابتدا باید قوانین را بپذیرید.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "📋 پذیرش قوانین",
                        callback_data="accept_rules"
                    )
                ]
            ])
        )
        return

    if not lottery_is_active():
        await query.edit_message_text(
            "⏳ قرعه‌کشی هنوز فعال نشده است.\n\n"
            "پس از رسیدن شبکه به هدف ۱۰۰ هزار، مسابقات فعال می‌شوند.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 بازگشت",
                        callback_data="campaigns"
                    )
                ]
            ])
        )
        return

    if TELEGRAM_MEMBERSHIP_REQUIRED:
        is_member = await check_telegram_membership(
            context.bot,
            user_id
        )

        if not is_member:
            await query.edit_message_text(
                "❌ برای شرکت در مسابقه باید عضو کانال "
                "محفل خوش‌شانس‌ها باشید.\n\n"
                "📢 ابتدا عضو کانال شوید و سپس "
                "«🔄 بررسی عضویت» را بزنید.",
                reply_markup=eligibility_keyboard()
            )
            return

    conn = db_connect()

    campaign = conn.execute(
        "SELECT * FROM campaigns WHERE id=? AND status='active'",
        (campaign_id,)
    ).fetchone()

    if not campaign:
        conn.close()

        await query.edit_message_text(
            "❌ این مسابقه دیگر فعال نیست.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 مسابقات",
                        callback_data="campaigns"
                    )
                ]
            ])
        )
        return

    already = conn.execute("""
        SELECT COUNT(*) AS count
        FROM participations
        WHERE campaign_id=?
        AND user_id=?
    """, (
        campaign_id,
        user_id
    )).fetchone()["count"]

    if already:
        conn.close()

        await query.edit_message_text(
            "⚠️ شما قبلاً در این مسابقه شرکت کرده‌اید.\n\n"
            "هر شانس شما به صورت یک بلیت جداگانه در قرعه‌کشی ثبت شده است.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 مسابقات",
                        callback_data="campaigns"
                    )
                ]
            ])
        )
        return

    chances = max(
        1,
        int(user["chances"] or 1)
    )

    for number in range(1, chances + 1):
        conn.execute("""
            INSERT INTO participations(
                campaign_id,
                user_id,
                chance_number,
                created_at
            )
            VALUES(?,?,?,?)
        """, (
            campaign_id,
            user_id,
            number,
            datetime.utcnow().isoformat()
        ))

    conn.commit()
    conn.close()

    await query.edit_message_text(
        "🎉 ثبت شرکت شما با موفقیت انجام شد!\n\n"
        f"🎟 تعداد شانس‌های ثبت‌شده: {chances}\n\n"
        "📢 توجه:\n"
        "عضویت تلگرام و شرایط شبکه‌های اجتماعی برای دریافت "
        "جایزه الزامی است.\n\n"
        "👥 دوستان بیشتری دعوت کن تا شانس بیشتری داشته باشی.",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "👥 دعوت دوستان",
                    callback_data="invite"
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
# PROFILE
# ============================================================

async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    await query.answer()

    user = get_user(query.from_user.id)

    if not user:
        return

    username = (
        f"@{user['username']}"
        if user["username"]
        else "ندارد"
    )

    text = (
        "👤 پروفایل شما\n\n"
        f"🆔 شناسه: {user['id']}\n"
        f"👤 نام: {user['first_name'] or '-'}\n"
        f"📱 نام کاربری: {username}\n"
        f"🎟 شانس‌ها: {user['chances']}\n"
        f"📅 عضویت: {user['joined_at'][:10]}\n\n"
        "🎁 ثبت‌نام رایگان است."
    )

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 بازگشت",
                    callback_data="back_main"
                )
            ]
        ])
    )


# ============================================================
# CHANCES
# ============================================================

async def show_chances(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    await query.answer()

    user = get_user(query.from_user.id)

    chances = user["chances"] if user else 0

    conn = db_connect()

    participated = conn.execute("""
        SELECT COUNT(DISTINCT campaign_id) AS count
        FROM participations
        WHERE user_id=?
    """, (
        query.from_user.id,
    )).fetchone()["count"]

    conn.close()

    await query.edit_message_text(
        "🎟 شانس‌های شما\n\n"
        f"🎟 تعداد شانس فعلی: {chances}\n"
        f"🎁 مسابقات شرکت‌کرده: {participated}\n\n"
        "👥 با دعوت دوستان می‌توانی شانس بیشتری بگیری.",
        reply_markup=InlineKeyboardMarkup([
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
        ])
    )


# ============================================================
# INVITE
# ============================================================

async def show_invite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    invite_link = (
        f"https://t.me/{BOT_USERNAME}"
        f"?start=ref_{user_id}"
    )

    conn = db_connect()

    count = conn.execute("""
        SELECT COUNT(*)
        FROM referrals
        WHERE inviter_id=?
    """, (
        user_id,
    )).fetchone()[0]

    conn.close()

    text = (
        "👥 دعوت دوستان\n\n"
        "دوستانت را به محفل خوش‌شانس‌ها دعوت کن.\n\n"
        "🎟 هر دعوت موفق یک شانس اضافه برای دعوت‌کننده ایجاد می‌کند.\n\n"
        f"👥 تعداد دعوت‌های موفق: {count}\n\n"
        "🔗 لینک اختصاصی شما:\n"
        f"{invite_link}\n\n"
        "🎁 ثبت‌نام رایگان است."
    )

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "📤 اشتراک‌گذاری لینک",
                    url=(
                        "https://t.me/share/url?"
                        + urlencode({
                            "url": invite_link,
                            "text": "🎁 به محفل خوش‌شانس‌ها بپیوند!"
                        })
                    )
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 بازگشت",
                    callback_data="back_main"
                )
            ]
        ])
    )


# ============================================================
# WINNERS
# ============================================================

async def show_winners(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    await query.answer()

    conn = db_connect()

    rows = conn.execute("""
        SELECT
            winners.*,
            users.first_name,
            users.username,
            campaigns.title
        FROM winners
        LEFT JOIN users
            ON users.id=winners.user_id
        LEFT JOIN campaigns
            ON campaigns.id=winners.campaign_id
        WHERE winners.announced=1
        ORDER BY winners.id DESC
        LIMIT 20
    """).fetchall()

    conn.close()

    if not rows:
        text = (
            "🏆 هنوز برنده‌ای اعلام نشده است.\n\n"
            "اولین برندگان به‌زودی در همین بخش اعلام خواهند شد."
        )
    else:
        lines = ["🏆 برندگان محفل خوش‌شانس‌ها\n"]

        for row in rows:
            name = row["first_name"] or "کاربر"

            if row["username"]:
                name += f" (@{row['username']})"

            lines.append(
                f"🎁 {row['title']}\n"
                f"👤 {name}\n"
                f"🏆 {row['prize']}\n"
            )

        text = "\n".join(lines)

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 بازگشت",
                    callback_data="back_main"
                )
            ]
        ])
    )


# ============================================================
# ARCHIVE
# ============================================================

async def show_archive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    await query.answer()

    conn = db_connect()

    rows = conn.execute("""
        SELECT *
        FROM campaigns
        WHERE status='closed'
        ORDER BY id DESC
        LIMIT 20
    """).fetchall()

    conn.close()

    if not rows:
        text = "📜 هنوز آرشیوی ثبت نشده است."
    else:
        lines = ["📜 آرشیو مسابقات\n"]

        for row in rows:
            lines.append(
                f"🎁 {row['title']}\n"
                f"🏆 {row['prize']}\n"
                f"📅 {row['draw_date'] or '-'}\n"
            )

        text = "\n".join(lines)

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 بازگشت",
                    callback_data="back_main"
                )
            ]
        ])
    )


# ============================================================
# RULES SCREEN
# ============================================================

async def show_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    await query.answer()

    await query.edit_message_text(
        RULES_TEXT,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 بازگشت",
                    callback_data="back_main"
                )
            ]
        ])
    )


# ============================================================
# SUPPORT
# ============================================================

async def show_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    await query.answer()

    context.user_data["support_mode"] = True

    await query.edit_message_text(
        "🎧 پشتیبانی محفل خوش‌شانس‌ها\n\n"
        "پیام خود را همینجا ارسال کنید.\n\n"
        "اگر اسپانسر هستید، مشخصات و پیشنهاد همکاری خود را "
        "ارسال کنید تا تیم پشتیبانی بررسی کند.",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 بازگشت",
                    callback_data="back_main"
                )
            ]
        ])
    )


async def receive_support_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not context.user_data.get("support_mode"):
        return False

    if not update.message:
        return False

    message = update.message.text.strip()

    if not message:
        return True

    user_id = update.effective_user.id

    conn = db_connect()

    cursor = conn.execute("""
        INSERT INTO support_tickets(
            user_id,
            message,
            status,
            created_at
        )
        VALUES(?,?,?,?)
    """, (
        user_id,
        message,
        "open",
        datetime.utcnow().isoformat()
    ))

    ticket_id = cursor.lastrowid

    conn.commit()
    conn.close()

    context.user_data["support_mode"] = False

    await update.message.reply_text(
        f"✅ پیام شما ثبت شد.\n\n"
        f"🎫 شماره تیکت: #{ticket_id}\n\n"
        "پشتیبانی پیام شما را بررسی می‌کند.",
        reply_markup=main_menu()
    )

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                "🎧 تیکت جدید\n\n"
                f"🎫 شماره: #{ticket_id}\n"
                f"👤 کاربر: {user_id}\n\n"
                f"💬 پیام:\n{message}\n\n"
                f"برای پاسخ:\n"
                f"/reply {ticket_id} متن پاسخ"
            )
        except Exception as e:
            logger.warning(
                "Could not notify admin %s: %s",
                admin_id,
                e
            )

    return True


# ============================================================
# CALLBACK ROUTER
# ============================================================

async def callback_router(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    if not query:
        return

    data = query.data or ""

    if data == "accept_rules":
        await accept_rules(update, context)
        return

    if data == "verify_membership":
        await verify_membership(update, context)
        return

    if data == "campaigns":
        await show_campaigns(update, context)
        return

    if data.startswith("campaign_"):
        await show_campaign(update, context)
        return

    if data.startswith("join_"):
        await join_campaign(update, context)
        return

    if data == "profile":
        await show_profile(update, context)
        return

    if data == "chances":
        await show_chances(update, context)
        return

    if data == "invite":
        await show_invite(update, context)
        return

    if data == "winners":
        await show_winners(update, context)
        return

    if data == "archive":
        await show_archive(update, context)
        return

    if data == "rules":
        await show_rules(update, context)
        return

    if data == "support":
        await show_support(update, context)
        return

    if data == "back_main":
        await query.answer()

        await query.edit_message_text(
            "🏠 منوی اصلی",
            reply_markup=main_menu()
        )
        return

    await query.answer()


# ============================================================
# TEXT MESSAGE HANDLER
# ============================================================

async def text_message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    handled = await receive_support_message(
        update,
        context
    )

    if handled:
        return

    if update.message:
        await update.message.reply_text(
            "از منوی زیر استفاده کنید:",
            reply_markup=main_menu()
        )


# ============================================================
# ADMIN CHECK
# ============================================================

def is_admin(user_id):
    return user_id in ADMIN_IDS


# ============================================================
# ADMIN MENU
# ============================================================

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    await update.message.reply_text(
        "🛠 پنل مدیریت\n\n"
        "/stats\n"
        "/network\n"
        "/igfollowers 100000\n"
        "/ytfollowers 100000\n"
        "/tgfollowers 100000\n"
        "/activation 100000\n"
        "/maxfollowers 1000000\n"
        "/dailyprize 10000000\n"
        "/newcampaign عنوان | توضیحات | جایزه\n"
        "/newsponsor نام | تلفن | بودجه | توضیحات\n"
        "/sponsorbudget مبلغ\n"
        "/draw ID\n"
        "/announce ID\n"
        "/rulesadmin متن\n"
        "/users\n"
        "/participants ID\n"
        "/tickets\n"
        "/reply ID متن\n"
        "/broadcast متن\n"
        "/postnow\n"
        "/logs"
    )


# ============================================================
# ADMIN STATS
# ============================================================

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    conn = db_connect()

    users = conn.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]

    active_users = conn.execute(
        "SELECT COUNT(*) FROM users WHERE is_active=1"
    ).fetchone()[0]

    referrals = conn.execute(
        "SELECT COUNT(*) FROM referrals"
    ).fetchone()[0]

    campaigns = conn.execute(
        "SELECT COUNT(*) FROM campaigns"
    ).fetchone()[0]

    active_campaigns = conn.execute(
        "SELECT COUNT(*) FROM campaigns WHERE status='active'"
    ).fetchone()[0]

    participations = conn.execute(
        "SELECT COUNT(*) FROM participations"
    ).fetchone()[0]

    winners = conn.execute(
        "SELECT COUNT(*) FROM winners"
    ).fetchone()[0]

    tickets = conn.execute(
        "SELECT COUNT(*) FROM support_tickets WHERE status='open'"
    ).fetchone()[0]

    conn.close()

    await update.message.reply_text(
        "📊 آمار سیستم\n\n"
        f"👥 کل کاربران: {users:,}\n"
        f"🟢 کاربران فعال: {active_users:,}\n"
        f"👥 دعوت‌ها: {referrals:,}\n"
        f"🎁 کل مسابقات: {campaigns:,}\n"
        f"🎯 مسابقات فعال: {active_campaigns:,}\n"
        f"🎟 مشارکت‌ها: {participations:,}\n"
        f"🏆 برندگان: {winners:,}\n"
        f"🎧 تیکت‌های باز: {tickets:,}\n\n"
        + network_status_text()
    )


# ============================================================
# ADMIN NETWORK
# ============================================================

async def network(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    await update.message.reply_text(
        network_status_text()
    )


async def igfollowers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text(
            "مثال:\n/igfollowers 100000"
        )
        return

    try:
        value = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "عدد صحیح وارد کنید."
        )
        return

    set_setting(
        "instagram_followers",
        value
    )

    log_operation(
        update.effective_user.id,
        "igfollowers",
        str(value)
    )

    await update.message.reply_text(
        f"✅ تعداد اینستاگرام روی {value:,} تنظیم شد.\n\n"
        + network_status_text()
    )


async def ytfollowers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text(
            "مثال:\n/ytfollowers 100000"
        )
        return

    try:
        value = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "عدد صحیح وارد کنید."
        )
        return

    set_setting(
        "youtube_followers",
        value
    )

    log_operation(
        update.effective_user.id,
        "ytfollowers",
        str(value)
    )

    await update.message.reply_text(
        f"✅ تعداد یوتیوب روی {value:,} تنظیم شد.\n\n"
        + network_status_text()
    )


async def tgfollowers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text(
            "مثال:\n/tgfollowers 100000"
        )
        return

    try:
        value = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "عدد صحیح وارد کنید."
        )
        return

    set_setting(
        "telegram_followers",
        value
    )

    log_operation(
        update.effective_user.id,
        "tgfollowers",
        str(value)
    )

    await update.message.reply_text(
        f"✅ تعداد تلگرام روی {value:,} تنظیم شد.\n\n"
        + network_status_text()
    )


async def activation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text(
            f"🎯 مقدار فعلی: {activation_target():,}\n\n"
            "برای تغییر:\n"
            "/activation 100000"
        )
        return

    try:
        value = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "عدد صحیح وارد کنید."
        )
        return

    set_setting(
        "activation_followers",
        value
    )

    log_operation(
        update.effective_user.id,
        "activation",
        str(value)
    )

    await update.message.reply_text(
        f"✅ هدف فعال‌سازی روی {value:,} تنظیم شد."
    )


async def maxfollowers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text(
            f"حد فعلی: {get_setting('plan_max_followers', '1000000')}"
        )
        return

    try:
        value = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "عدد صحیح وارد کنید."
        )
        return

    set_setting(
        "plan_max_followers",
        value
    )

    await update.message.reply_text(
        f"✅ سقف شبکه روی {value:,} تنظیم شد."
    )


async def dailyprize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text(
            f"مبلغ فعلی: {get_setting('daily_prize_amount')}"
        )
        return

    try:
        value = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "عدد صحیح وارد کنید."
        )
        return

    set_setting(
        "daily_prize_amount",
        value
    )

    await update.message.reply_text(
        f"✅ مبلغ جایزه تنظیم شد: {value:,}"
    )


# ============================================================
# ADMIN NEW CAMPAIGN
# ============================================================

async def newcampaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    raw = " ".join(context.args)

    parts = [
        part.strip()
        for part in raw.split("|")
    ]

    if len(parts) < 3:
        await update.message.reply_text(
            "فرمت:\n\n"
            "/newcampaign عنوان | توضیحات | جایزه\n\n"
            "مثال:\n"
            "/newcampaign قرعه بزرگ | جایزه ویژه | 10000000 تومان"
        )
        return

    title = parts[0]
    description = parts[1]
    prize = parts[2]

    conn = db_connect()

    cursor = conn.execute("""
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
    """, (
        title,
        description,
        prize,
        1,
        None,
        "active",
        datetime.utcnow().isoformat()
    ))

    campaign_id = cursor.lastrowid

    conn.commit()
    conn.close()

    log_operation(
        update.effective_user.id,
        "newcampaign",
        str(campaign_id)
    )

    await update.message.reply_text(
        f"✅ مسابقه ساخته شد.\n\n"
        f"🆔 ID: {campaign_id}\n"
        f"🎁 {title}\n"
        f"🏆 {prize}"
    )


# ============================================================
# SPONSORS
# ============================================================

async def newsponsor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    raw = " ".join(context.args)

    parts = [
        part.strip()
        for part in raw.split("|")
    ]

    if len(parts) < 4:
        await update.message.reply_text(
            "فرمت:\n"
            "/newsponsor نام | تلفن | بودجه | توضیحات"
        )
        return

    name = parts[0]
    phone = parts[1]

    try:
        budget = float(parts[2])
    except ValueError:
        budget = 0

    description = parts[3]

    conn = db_connect()

    cursor = conn.execute("""
        INSERT INTO sponsors(
            name,
            phone,
            budget,
            description,
            created_at
        )
        VALUES(?,?,?,?,?)
    """, (
        name,
        phone,
        budget,
        description,
        datetime.utcnow().isoformat()
    ))

    sponsor_id = cursor.lastrowid

    conn.execute("""
        UPDATE settings
        SET value = CAST(value AS REAL) + ?
        WHERE key='total_sponsor_budget'
    """, (budget,))

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ اسپانسر ثبت شد.\n\n"
        f"🆔 ID: {sponsor_id}\n"
        f"👤 {name}\n"
        f"💰 بودجه: {budget:,.0f}"
    )


async def sponsorbudget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        total = get_setting(
            "total_sponsor_budget",
            "0"
        )

        await update.message.reply_text(
            f"💰 مجموع بودجه اسپانسرها: {float(total):,.0f}"
        )
        return

    try:
        value = float(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "مبلغ صحیح وارد کنید."
        )
        return

    set_setting(
        "total_sponsor_budget",
        value
    )

    await update.message.reply_text(
        f"✅ بودجه کل اسپانسرها: {value:,.0f}"
    )


# ============================================================
# DRAW HELPERS
# ============================================================

async def get_eligible_tickets(
    bot,
    campaign_id,
    excluded_users=None
):
    excluded_users = excluded_users or set()

    conn = db_connect()

    rows = conn.execute("""
        SELECT
            p.user_id,
            p.chance_number
        FROM participations p
        WHERE p.campaign_id=?
        ORDER BY p.id ASC
    """, (
        campaign_id,
    )).fetchall()

    conn.close()

    eligible_tickets = []
    checked_users = {}

    for row in rows:
        user_id = row["user_id"]

        if user_id in excluded_users:
            continue

        if user_id not in checked_users:
            checked_users[user_id] = await check_telegram_membership(
                bot,
                user_id
            )

        if checked_users[user_id]:
            eligible_tickets.append(user_id)

    return eligible_tickets


# ============================================================
# ADMIN DRAW
# ============================================================

async def draw(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            "ID صحیح وارد کنید."
        )
        return

    conn = db_connect()

    campaign = conn.execute(
        "SELECT * FROM campaigns WHERE id=?",
        (campaign_id,)
    ).fetchone()

    if not campaign:
        conn.close()

        await update.message.reply_text(
            "❌ مسابقه پیدا نشد."
        )
        return

    if campaign["status"] != "active":
        conn.close()

        await update.message.reply_text(
            "❌ این مسابقه فعال نیست."
        )
        return

    conn.close()

    eligible_tickets = await get_eligible_tickets(
        context.bot,
        campaign_id
    )

    if not eligible_tickets:
        await update.message.reply_text(
            "❌ هیچ شرکت‌کننده واجد شرایطی پیدا نشد.\n\n"
            "بررسی شد که شرکت‌کننده باید عضو کانال تلگرام باشد."
        )
        return

    winner_id = random.choice(
        eligible_tickets
    )

    conn = db_connect()

    conn.execute("""
        INSERT INTO winners(
            campaign_id,
            user_id,
            prize,
            selected_at,
            announced
        )
        VALUES(?,?,?,?,?)
    """, (
        campaign_id,
        winner_id,
        campaign["prize"],
        datetime.utcnow().isoformat(),
        0
    ))

    conn.execute("""
        UPDATE campaigns
        SET status='closed',
            draw_date=?
        WHERE id=?
    """, (
        datetime.utcnow().isoformat(),
        campaign_id
    ))

    conn.commit()
    conn.close()

    log_operation(
        update.effective_user.id,
        "draw",
        f"campaign={campaign_id},winner={winner_id}"
    )

    await update.message.reply_text(
        "🎉 قرعه‌کشی انجام شد.\n\n"
        f"🎁 مسابقه: {campaign['title']}\n"
        f"👤 شناسه برنده: {winner_id}\n\n"
        "⚠️ وضعیت عضویت در تلگرام هنگام قرعه‌کشی بررسی شد.\n"
        "برای اعلام عمومی از /announce استفاده کنید."
    )


# ============================================================
# ADMIN ANNOUNCE
# ============================================================

async def announce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text(
            "مثال:\n/announce 1"
        )
        return

    try:
        campaign_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "ID صحیح وارد کنید."
        )
        return

    conn = db_connect()

    winner = conn.execute("""
        SELECT
            winners.*,
            campaigns.title
        FROM winners
        JOIN campaigns
            ON campaigns.id=winners.campaign_id
        WHERE winners.campaign_id=?
        AND winners.announced=0
        ORDER BY winners.id DESC
        LIMIT 1
    """, (
        campaign_id,
    )).fetchone()

    conn.close()

    if not winner:
        await update.message.reply_text(
            "❌ برنده‌ای برای اعلام پیدا نشد."
        )
        return

    # بررسی دوباره عضویت قبل از اعلام جایزه
    still_member = await check_telegram_membership(
        context.bot,
        winner["user_id"]
    )

    if not still_member:
        await update.message.reply_text(
            "⚠️ برنده فعلی در زمان اعلام دیگر عضو کانال نیست.\n\n"
            "❌ جایزه برای این شخص تأیید نمی‌شود.\n\n"
            "برای جلوگیری از واگذاری جایزه به فرد فاقد شرایط، "
            "قرعه‌کشی مجدد انجام می‌شود."
        )

        conn = db_connect()

        conn.execute("""
            UPDATE winners
            SET announced=-1
            WHERE id=?
        """, (
            winner["id"],
        ))

        conn.commit()
        conn.close()

        # قرعه‌کشی مجدد با حذف برنده قبلی
        excluded = {winner["user_id"]}

        eligible_tickets = await get_eligible_tickets(
            context.bot,
            campaign_id,
            excluded_users=excluded
        )

        if not eligible_tickets:
            await update.message.reply_text(
                "❌ فرد واجد شرایط دیگری برای قرعه‌کشی پیدا نشد."
            )
            return

        new_winner_id = random.choice(
            eligible_tickets
        )

        conn = db_connect()

        conn.execute("""
            INSERT INTO winners(
                campaign_id,
                user_id,
                prize,
                selected_at,
                announced
            )
            VALUES(?,?,?,?,?)
        """, (
            campaign_id,
            new_winner_id,
            winner["prize"],
            datetime.utcnow().isoformat(),
            0
        ))

        conn.commit()
        conn.close()

        await update.message.reply_text(
            "🔄 قرعه‌کشی مجدد انجام شد.\n\n"
            f"👤 برنده جدید: {new_winner_id}\n\n"
            "در صورت تأیید شرایط، دوباره /announce را اجرا کنید."
        )

        return

    conn = db_connect()

    conn.execute("""
        UPDATE winners
        SET announced=1
        WHERE id=?
    """, (
        winner["id"],
    ))

    conn.commit()
    conn.close()

    user = get_user(
        winner["user_id"]
    )

    name = (
        user["first_name"]
        if user and user["first_name"]
        else "برنده"
    )

    announcement = (
        "🏆🎉 برنده جدید محفل خوش‌شانس‌ها 🎉🏆\n\n"
        f"🎁 مسابقه: {winner['title']}\n"
        f"👤 برنده: {name}\n"
        f"🏆 جایزه: {winner['prize']}\n\n"
        "✅ شرایط عضویت تلگرام بررسی شد.\n\n"
        "📢 برای دریافت جایزه باید شرایط اعلام‌شده "
        "مسابقه را رعایت کرده باشید.\n\n"
        "🎉 به برنده تبریک می‌گوییم!"
    )

    await update.message.reply_text(
        announcement
    )

    try:
        await context.bot.send_message(
            winner["user_id"],
            announcement
        )
    except Exception as e:
        logger.warning(
            "Could not notify winner: %s",
            e
        )

    try:
        await context.bot.send_message(
            TELEGRAM_CHANNEL,
            announcement
        )
    except Exception as e:
        logger.warning(
            "Could not announce in channel: %s",
            e
        )


# ============================================================
# ADMIN RULES
# ============================================================

async def rulesadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    text = " ".join(context.args).strip()

    if not text:
        await update.message.reply_text(
            "متن جدید قوانین را وارد کنید."
        )
        return

    global RULES_TEXT

    RULES_TEXT = text

    await update.message.reply_text(
        "✅ قوانین در حافظه برنامه به‌روزرسانی شد."
    )


# ============================================================
# ADMIN USERS
# ============================================================

async def users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    conn = db_connect()

    rows = conn.execute("""
        SELECT id, first_name, username, chances, joined_at
        FROM users
        ORDER BY id DESC
        LIMIT 50
    """).fetchall()

    conn.close()

    if not rows:
        await update.message.reply_text(
            "کاربری وجود ندارد."
        )
        return

    lines = ["👥 آخرین کاربران\n"]

    for row in rows:
        username = (
            f"@{row['username']}"
            if row["username"]
            else "-"
        )

        lines.append(
            f"🆔 {row['id']} | "
            f"{row['first_name'] or '-'} | "
            f"{username} | "
            f"🎟 {row['chances']}"
        )

    await update.message.reply_text(
        "\n".join(lines)
    )


# ============================================================
# ADMIN PARTICIPANTS
# ============================================================

async def participants(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text(
            "مثال:\n/participants 1"
        )
        return

    try:
        campaign_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "ID صحیح وارد کنید."
        )
        return

    conn = db_connect()

    rows = conn.execute("""
        SELECT
            p.user_id,
            COUNT(*) AS chances,
            users.first_name,
            users.username
        FROM participations p
        LEFT JOIN users
            ON users.id=p.user_id
        WHERE p.campaign_id=?
        GROUP BY p.user_id
        ORDER BY chances DESC
    """, (
        campaign_id,
    )).fetchall()

    conn.close()

    if not rows:
        await update.message.reply_text(
            "شرکت‌کننده‌ای وجود ندارد."
        )
        return

    lines = [
        f"🎟 شرکت‌کنندگان مسابقه {campaign_id}\n"
    ]

    for row in rows:
        lines.append(
            f"👤 {row['first_name'] or '-'} "
            f"({row['user_id']}) "
            f"🎟 {row['chances']}"
        )

    await update.message.reply_text(
        "\n".join(lines)
    )


# ============================================================
# ADMIN TICKETS
# ============================================================

async def tickets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    conn = db_connect()

    rows = conn.execute("""
        SELECT *
        FROM support_tickets
        WHERE status='open'
        ORDER BY id DESC
        LIMIT 30
    """).fetchall()

    conn.close()

    if not rows:
        await update.message.reply_text(
            "🎧 تیکت بازی وجود ندارد."
        )
        return

    lines = ["🎧 تیکت‌های باز\n"]

    for row in rows:
        lines.append(
            f"#{row['id']} | "
            f"user={row['user_id']}\n"
            f"{row['message']}\n"
        )

    await update.message.reply_text(
        "\n".join(lines)
    )


# ============================================================
# ADMIN REPLY
# ============================================================

async def reply_ticket(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not is_admin(update.effective_user.id):
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "فرمت:\n/reply شماره_تیکت متن پاسخ"
        )
        return

    try:
        ticket_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "شماره تیکت صحیح نیست."
        )
        return

    reply_text = " ".join(
        context.args[1:]
    )

    conn = db_connect()

    ticket = conn.execute("""
        SELECT *
        FROM support_tickets
        WHERE id=?
    """, (
        ticket_id,
    )).fetchone()

    if not ticket:
        conn.close()

        await update.message.reply_text(
            "❌ تیکت پیدا نشد."
        )
        return

    conn.execute("""
        UPDATE support_tickets
        SET status='closed',
            replied_at=?,
            reply=?
        WHERE id=?
    """, (
        datetime.utcnow().isoformat(),
        reply_text,
        ticket_id
    ))

    conn.commit()
    conn.close()

    try:
        await context.bot.send_message(
            ticket["user_id"],
            "🎧 پاسخ پشتیبانی\n\n"
            + reply_text
        )
    except Exception as e:
        logger.warning(
            "Could not send support reply: %s",
            e
        )

    await update.message.reply_text(
        "✅ پاسخ ارسال شد."
    )


# ============================================================
# ADMIN BROADCAST
# ============================================================

async def broadcast(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not is_admin(update.effective_user.id):
        return

    text = " ".join(
        context.args
    ).strip()

    if not text:
        await update.message.reply_text(
            "مثال:\n/broadcast متن پیام"
        )
        return

    conn = db_connect()

    rows = conn.execute("""
        SELECT id
        FROM users
        WHERE is_active=1
    """).fetchall()

    conn.close()

    sent = 0

    for row in rows:
        try:
            await context.bot.send_message(
                row["id"],
                text
            )

            sent += 1

            await asyncio.sleep(0.05)

        except Exception:
            pass

    await update.message.reply_text(
        f"✅ پیام برای {sent:,} کاربر ارسال شد."
    )


# ============================================================
# AUTOMATIC CHANNEL POSTS
# ============================================================

CHANNEL_MESSAGES = [
    """
🔥 محفل خوش‌شانس‌ها داره بزرگ‌تر میشه!

🎯 هدف بزرگ ما: رسیدن شبکه به ۱۰۰,۰۰۰ نفر

بعد از رسیدن به حد فعال‌سازی، قرعه‌کشی‌ها باز می‌شوند. 🎁

👥 دوستات رو دعوت کن
🎟 شانس رایگان بیشتری بگیر
📢 عضو کانال تلگرام باش
📸 اینستاگرام محفل رو دنبال کن
▶️ یوتیوب محفل رو دنبال کن

⚠️ رعایت شرایط شبکه‌های اجتماعی برای دریافت جایزه الزامی است.

🤝 اگر اسپانسر هستید و می‌خواهید در جوایز محفل حضور داشته باشید، از طریق پشتیبانی پیام بدهید.
""",

    """
🚨 محفل خوش‌شانس‌ها منتظر توئه!

هنوز اول راهیم و هر نفر مهمه. 🔥

👥 دوستات رو وارد محفل کن
🎟 شانس رایگان بگیر
📢 کانال رو از دست نده
📸 اینستاگرام رو دنبال کن
▶️ یوتیوب رو دنبال کن

🎯 وقتی شبکه به ۱۰۰,۰۰۰ برسد، مرحله قرعه‌کشی فعال می‌شود.

🏆 برای دریافت جایزه، رعایت شرایط اعلام‌شده مسابقه الزامی است.

💼 اسپانسرها برای همکاری و حمایت از جوایز با پشتیبانی در ارتباط باشند.
""",

    """
🎁 می‌خوای وارد قرعه‌کشی‌های محفل خوش‌شانس‌ها بشی؟

پس از همین الان همراه باش!

1️⃣ عضو کانال تلگرام
2️⃣ دنبال کردن اینستاگرام
3️⃣ دنبال کردن یوتیوب
4️⃣ دعوت دوستان
5️⃣ جمع کردن شانس‌های رایگان

🎯 هدف فعال شدن قرعه‌کشی: ۱۰۰,۰۰۰ نفر

🔥 این تازه شروع محفل است.

🤝 اسپانسر هستی؟
برای همکاری با پشتیبانی پیام بده.
""",

    """
🚀 محفل خوش‌شانس‌ها رو با دوستات بساز!

هر عضو جدید یعنی یک قدم نزدیک‌تر به باز شدن مرحله قرعه‌کشی. 🎯

🎟 ثبت‌نام رایگان
👥 دعوت دوستان
🏆 جوایز ویژه
📢 عضویت تلگرام الزامی برای دریافت جایزه
📸 دنبال کردن اینستاگرام الزامی
▶️ دنبال کردن یوتیوب الزامی

⚠️ شرایط دریافت جایزه باید کامل رعایت شود.

🔥 عدد بعدی ما: ۱۰۰,۰۰۰

💼 برای اسپانسری و همکاری با پشتیبانی در ارتباط باشید.
"""
]


async def send_channel_post(app):
    index = random.randrange(
        len(CHANNEL_MESSAGES)
    )

    base_message = CHANNEL_MESSAGES[index]

    try:
        status = network_status_text()

        message = (
            base_message
            + "\n\n"
            + "━━━━━━━━━━━━━━\n"
            + status
        )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🎁 ورود به محفل",
                    url=f"https://t.me/{BOT_USERNAME}"
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
                    "🎧 پشتیبانی / اسپانسری",
                    url=f"https://t.me/{BOT_USERNAME}"
                )
            ]
        ])

        await app.bot.send_message(
            chat_id=TELEGRAM_CHANNEL,
            text=message,
            reply_markup=keyboard
        )

        logger.info(
            "Automatic channel post sent."
        )

    except Exception as e:
        logger.warning(
            "Automatic channel post failed: %s",
            e
        )


async def automatic_channel_posts(app):
    await asyncio.sleep(30)

    while True:
        try:
            await send_channel_post(app)
        except Exception as e:
            logger.warning(
                "Channel post loop error: %s",
                e
            )

        await asyncio.sleep(
            CHANNEL_POST_INTERVAL_HOURS * 60 * 60
        )


# ============================================================
# NETWORK UPDATE LOOP
# ============================================================

async def update_network_counts(app):
    # YouTube automatic
    youtube_count = get_youtube_subscribers()

    if youtube_count is not None:
        set_setting(
            "youtube_followers",
            youtube_count
        )

    # Telegram automatic
    try:
        telegram_count = await app.bot.get_chat_member_count(
            TELEGRAM_CHANNEL
        )

        set_setting(
            "telegram_followers",
            telegram_count
        )

    except Exception as e:
        logger.warning(
            "Telegram member count error: %s",
            e
        )

    # Instagram فعلاً دستی است
    set_setting(
        "network_last_update",
        datetime.utcnow().isoformat()
    )

    set_setting(
        "networks_activated",
        "1" if all_networks_reached() else "0"
    )


async def network_loop(app):
    await asyncio.sleep(20)

    while True:
        try:
            await update_network_counts(app)
        except Exception as e:
            logger.warning(
                "Network loop error: %s",
                e
            )

        await asyncio.sleep(
            NETWORK_UPDATE_HOURS * 60 * 60
        )


# ============================================================
# ADMIN POST NOW
# ============================================================

async def postnow(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not is_admin(update.effective_user.id):
        return

    await send_channel_post(
        context.application
    )

    await update.message.reply_text(
        "✅ پیام کانال ارسال شد."
    )


# ============================================================
# ADMIN LOGS
# ============================================================

async def logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    conn = db_connect()

    rows = conn.execute("""
        SELECT *
        FROM operation_logs
        ORDER BY id DESC
        LIMIT 30
    """).fetchall()

    conn.close()

    if not rows:
        await update.message.reply_text(
            "لاگی وجود ندارد."
        )
        return

    lines = ["📝 آخرین عملیات\n"]

    for row in rows:
        lines.append(
            f"#{row['id']} | "
            f"admin={row['admin_id']} | "
            f"{row['action']} | "
            f"{row['details']}"
        )

    await update.message.reply_text(
        "\n".join(lines)
    )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):
    logger.exception(
        "Unhandled exception:",
        exc_info=context.error
    )


# ============================================================
# POST INIT
# ============================================================

async def post_init(application):
    init_db()

    logger.info(
        "Database initialized."
    )

    logger.info(
        "Starting background network task."
    )

    asyncio.create_task(
        network_loop(application)
    )

    logger.info(
        "Starting automatic channel post task."
    )

    asyncio.create_task(
        automatic_channel_posts(application)
    )


# ============================================================
# MAIN
# ============================================================

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN is not set."
        )

    init_db()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.post_init = post_init

    # ----------------------------
    # USER
    # ----------------------------

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            callback_router
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_message_handler
        )
    )

    # ----------------------------
    # ADMIN
    # ----------------------------

    application.add_handler(
        CommandHandler(
            "admin",
            admin
        )
    )

    application.add_handler(
        CommandHandler(
            "stats",
            stats
        )
    )

    application.add_handler(
        CommandHandler(
            "network",
            network
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
            "activation",
            activation
        )
    )

    application.add_handler(
        CommandHandler(
            "maxfollowers",
            maxfollowers
        )
    )

    application.add_handler(
        CommandHandler(
            "dailyprize",
            dailyprize
        )
    )

    application.add_handler(
        CommandHandler(
            "newcampaign",
            newcampaign
        )
    )

    application.add_handler(
        CommandHandler(
            "newsponsor",
            newsponsor
        )
    )

    application.add_handler(
        CommandHandler(
            "sponsorbudget",
            sponsorbudget
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
            "announce",
            announce
        )
    )

    application.add_handler(
        CommandHandler(
            "rulesadmin",
            rulesadmin
        )
    )

    application.add_handler(
        CommandHandler(
            "users",
            users
        )
    )

    application.add_handler(
        CommandHandler(
            "participants",
            participants
        )
    )

    application.add_handler(
        CommandHandler(
            "tickets",
            tickets
        )
    )

    application.add_handler(
        CommandHandler(
            "reply",
            reply_ticket
        )
    )

    application.add_handler(
        CommandHandler(
            "broadcast",
            broadcast
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
            "logs",
            logs
        )
    )

    application.add_error_handler(
        error_handler
    )

    # ========================================================
    # RENDER
    # ========================================================

    if RENDER_EXTERNAL_URL:
        webhook_url = (
            RENDER_EXTERNAL_URL.rstrip("/")
            + f"/{BOT_TOKEN}"
        )

        logger.info(
            "Starting webhook on port %s",
            PORT
        )

        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=webhook_url,
        )

    else:
        logger.info(
            "Starting polling."
        )

        application.run_polling(
            drop_pending_updates=True
        )


if __name__ == "__main__":
    main()
