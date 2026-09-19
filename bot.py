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
    ContextTypes,
    MessageHandler,
    filters,
)

# ============================================================
# MAHFEL SHANS BOT
# محفل خوش‌شانس‌ها
# Single-file production bot
# ============================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()

BOT_USERNAME = os.environ.get(
    "BOT_USERNAME",
    "MahfelShansBot"
).replace("@", "").strip()

TELEGRAM_CHANNEL = os.environ.get(
    "TELEGRAM_CHANNEL",
    "@MahfelShans"
).strip()

INSTAGRAM_URL = os.environ.get(
    "INSTAGRAM_URL",
    "https://instagram.com/MAHFELSHANS"
).strip()

YOUTUBE_URL = os.environ.get(
    "YOUTUBE_URL",
    "https://youtube.com/@mahfelshans"
).strip()

SUPPORT_USERNAME = os.environ.get(
    "SUPPORT_USERNAME",
    "@MahdiJahanshahi"
).strip()

DATABASE = os.environ.get(
    "DATABASE",
    "mahfelshans.db"
)

YOUTUBE_API_KEY = os.environ.get(
    "YOUTUBE_API_KEY",
    ""
).strip()

YOUTUBE_CHANNEL_ID = os.environ.get(
    "YOUTUBE_CHANNEL_ID",
    ""
).strip()

RENDER_EXTERNAL_URL = os.environ.get(
    "RENDER_EXTERNAL_URL",
    ""
).strip()

PORT = int(os.environ.get("PORT", "10000"))

WEBHOOK_PATH = os.environ.get(
    "WEBHOOK_PATH",
    "mahfelshans"
).strip("/")

ADMIN_IDS = set()

for item in os.environ.get("ADMIN_IDS", "").split(","):
    item = item.strip()
    if item:
        try:
            ADMIN_IDS.add(int(item))
        except ValueError:
            pass

ACTIVATION_TARGET = int(
    os.environ.get("ACTIVATION_TARGET", "100000")
)

TELEGRAM_MEMBERSHIP_REQUIRED = (
    os.environ.get(
        "TELEGRAM_MEMBERSHIP_REQUIRED",
        "1"
    ).lower()
    in ("1", "true", "yes", "on")
)

AUTO_POST_ENABLED = (
    os.environ.get(
        "AUTO_POST_ENABLED",
        "1"
    ).lower()
    in ("1", "true", "yes", "on")
)

AUTO_POST_HOURS = int(
    os.environ.get("AUTO_POST_HOURS", "2")
)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("MAHFELSHANS")


# ============================================================
# DATABASE
# ============================================================

def db():
    conn = sqlite3.connect(
        DATABASE,
        check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inviter_id INTEGER NOT NULL,
            invited_id INTEGER UNIQUE NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS participations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL,
            telegram_id INTEGER NOT NULL,
            chance_count INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            UNIQUE(campaign_id, telegram_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS winners (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id INTEGER NOT NULL,
            telegram_id INTEGER NOT NULL,
            prize TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS rule_acceptances (
            telegram_id INTEGER PRIMARY KEY,
            version TEXT NOT NULL,
            accepted_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            status TEXT DEFAULT 'open',
            created_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sponsors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            name TEXT,
            phone TEXT,
            budget TEXT,
            message TEXT,
            status TEXT DEFAULT 'new',
            created_at TEXT NOT NULL
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
        "networks_activated": "0",
        "rules_version": "1.0",
        "telegram_membership_required": (
            "1"
            if TELEGRAM_MEMBERSHIP_REQUIRED
            else "0"
        ),
        "last_auto_post": "",
        "last_youtube_check": "",
        "daily_prize_amount": "10000000",
    }

    for key, value in defaults.items():
        cur.execute(
            """
            INSERT OR IGNORE INTO settings(key, value)
            VALUES (?, ?)
            """,
            (key, value),
        )

    conn.commit()
    conn.close()


def get_setting(key, default=None):
    conn = db()
    row = conn.execute(
        "SELECT value FROM settings WHERE key=?",
        (key,),
    ).fetchone()
    conn.close()

    if row is None:
        return default

    return row["value"]


def set_setting(key, value):
    conn = db()
    conn.execute(
        """
        INSERT INTO settings(key,value)
        VALUES(?,?)
        ON CONFLICT(key)
        DO UPDATE SET value=excluded.value
        """,
        (key, str(value)),
    )
    conn.commit()
    conn.close()


def now():
    return datetime.now(timezone.utc).isoformat()


def get_user(telegram_id):
    conn = db()
    row = conn.execute(
        "SELECT * FROM users WHERE telegram_id=?",
        (telegram_id,),
    ).fetchone()
    conn.close()
    return row


def create_or_update_user(tg_user):
    conn = db()
    current = now()

    row = conn.execute(
        "SELECT id FROM users WHERE telegram_id=?",
        (tg_user.id,),
    ).fetchone()

    if row:
        conn.execute(
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
            ),
        )
    else:
        conn.execute(
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
            ),
        )

    conn.commit()
    conn.close()


def save_rules_acceptance(telegram_id):
    version = get_setting("rules_version", "1.0")

    conn = db()

    conn.execute(
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
        (telegram_id, version, now()),
    )

    conn.execute(
        """
        UPDATE users
        SET rules_accepted=1
        WHERE telegram_id=?
        """,
        (telegram_id,),
    )

    conn.commit()
    conn.close()


# ============================================================
# HELPERS
# ============================================================

def is_admin(user_id):
    return user_id in ADMIN_IDS


def fmt_number(number):
    try:
        return f"{int(number):,}"
    except Exception:
        return str(number)


def main_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🎁 جوایز و مسابقات",
                callback_data="campaigns"
            ),
        ],
        [
            InlineKeyboardButton(
                "🎟 شانس‌های من",
                callback_data="my_chances"
            ),
            InlineKeyboardButton(
                "👥 دعوت دوستان",
                callback_data="referral"
            ),
        ],
        [
            InlineKeyboardButton(
                "📱 اینستاگرام",
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
                url=f"https://t.me/{TELEGRAM_CHANNEL.lstrip('@')}"
            ),
        ],
        [
            InlineKeyboardButton(
                "✅ بررسی شرایط من",
                callback_data="eligibility"
            ),
        ],
        [
            InlineKeyboardButton(
                "📜 قوانین",
                callback_data="rules"
            ),
            InlineKeyboardButton(
                "🆘 پشتیبانی",
                callback_data="support"
            ),
        ],
    ])


def admin_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📊 وضعیت سیستم",
                callback_data="admin_status"
            ),
        ],
        [
            InlineKeyboardButton(
                "👥 کاربران",
                callback_data="admin_users"
            ),
            InlineKeyboardButton(
                "🎁 مسابقات",
                callback_data="admin_campaigns"
            ),
        ],
        [
            InlineKeyboardButton(
                "📢 ارسال تبلیغ",
                callback_data="admin_post"
            ),
            InlineKeyboardButton(
                "▶️ یوتیوب",
                callback_data="admin_youtube"
            ),
        ],
        [
            InlineKeyboardButton(
                "📈 شبکه‌ها",
                callback_data="admin_networks"
            ),
        ],
        [
            InlineKeyboardButton(
                "🎲 آخرین قرعه",
                callback_data="admin_last_draw"
            ),
        ],
        [
            InlineKeyboardButton(
                "🏠 منوی اصلی",
                callback_data="home"
            ),
        ],
    ])


def rules_text():
    return (
        "📜 <b>قوانین محفل خوش‌شانس‌ها</b>\n\n"
        "1️⃣ شرکت در محفل در حالت فعلی رایگان است.\n"
        "2️⃣ برای دریافت جایزه باید شرایط اعلام‌شده همان مسابقه را داشته باشید.\n"
        "3️⃣ عضویت در کانال تلگرام در صورت فعال بودن شرط، الزامی است.\n"
        "4️⃣ در صورت فعال شدن احراز اینستاگرام و یوتیوب، "
        "رعایت آن‌ها نیز برای دریافت جایزه الزامی خواهد بود.\n"
        "5️⃣ هر دعوت موفق می‌تواند طبق قوانین مسابقه شانس اضافه ایجاد کند.\n"
        "6️⃣ قرعه‌کشی فقط از بین افراد واجد شرایط انجام می‌شود.\n"
        "7️⃣ هر مسابقه قوانین و جایزه مشخص خود را دارد.\n"
        "8️⃣ نتیجه قرعه‌کشی در کانال رسمی اعلام می‌شود.\n\n"
        "⚠️ شرایط قانونی مسابقات باید متناسب با محل فعالیت و قوانین "
        "مربوطه بررسی و رعایت شود."
    )


def promotional_text():
    return (
        "🔥 <b>محفل خوش‌شانس‌ها در حال بزرگ شدن است!</b> 🔥\n\n"
        "🎁 مسابقات و جوایز بزرگ در راه است.\n"
        "🚀 هدف مرحله فعال‌سازی: <b>100,000 نفر</b>\n\n"
        "👥 دوستات رو وارد محفل کن و طبق قوانین، شانس بیشتری بگیر.\n"
        "📱 اینستاگرام رو دنبال کن\n"
        "▶️ یوتیوب رو دنبال کن\n"
        "📢 عضو کانال تلگرام باش\n\n"
        "⚠️ رعایت شرایط اعلام‌شده برای احراز صلاحیت دریافت جایزه الزامی است.\n\n"
        "👇 از همین حالا وارد ربات شو:\n"
        f"https://t.me/{BOT_USERNAME}\n\n"
        "🤝 اسپانسرها و برندهایی که می‌خواهند در مسابقات حضور داشته باشند، "
        "برای همکاری با پشتیبانی در ارتباط باشند."
    )


# ============================================================
# NETWORK STATUS
# ============================================================

def get_networks():
    return {
        "instagram": int(get_setting(
            "instagram_followers", "0"
        )),
        "youtube": int(get_setting(
            "youtube_followers", "0"
        )),
        "telegram": int(get_setting(
            "telegram_followers", "0"
        )),
    }


def check_activation():
    networks = get_networks()
    target = int(get_setting(
        "activation_target",
        ACTIVATION_TARGET
    ))

    active = all(
        value >= target
        for value in networks.values()
    )

    set_setting(
        "networks_activated",
        "1" if active else "0"
    )

    return active


def activation_text():
    networks = get_networks()
    target = int(get_setting(
        "activation_target",
        ACTIVATION_TARGET
    ))

    active = check_activation()

    if active:
        return (
            "🚀 <b>محفل فعال شده است!</b>\n\n"
            "🎉 هر سه شبکه به حد نصاب رسیده‌اند.\n"
            "اکنون مسابقات فعال قابل مشاهده هستند."
        )

    def line(name, value):
        percent = min(
            100,
            int((value / target) * 100)
        ) if target else 0

        return (
            f"{name}: "
            f"<b>{fmt_number(value)}</b> / "
            f"{fmt_number(target)} "
            f"({percent}%)"
        )

    return (
        "🚀 <b>مسیر رسیدن به 100K</b>\n\n"
        f"📸 {line('Instagram', networks['instagram'])}\n"
        f"▶️ {line('YouTube', networks['youtube'])}\n"
        f"📢 {line('Telegram', networks['telegram'])}\n\n"
        "🎯 وقتی هر سه شبکه به حد نصاب برسند، "
        "مرحله فعال‌سازی مسابقات آغاز می‌شود."
    )


# ============================================================
# YOUTUBE
# ============================================================

def fetch_youtube_followers():
    if not YOUTUBE_API_KEY or not YOUTUBE_CHANNEL_ID:
        return None

    url = "https://www.googleapis.com/youtube/v3/channels"

    params = {
        "part": "statistics",
        "id": YOUTUBE_CHANNEL_ID,
        "key": YOUTUBE_API_KEY,
    }

    try:
        response = requests.get(
            url,
            params=params,
            timeout=20
        )

        if response.status_code != 200:
            logger.error(
                "YouTube API HTTP %s: %s",
                response.status_code,
                response.text[:500]
            )
            return None

        data = response.json()

        items = data.get("items", [])

        if not items:
            return None

        stats = items[0].get(
            "statistics",
            {}
        )

        count = stats.get(
            "subscriberCount"
        )

        if count is None:
            return None

        return int(count)

    except Exception as exc:
        logger.exception(
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
            "Telegram membership error: %s",
            exc
        )
        return False


# ============================================================
# ELIGIBILITY
# ============================================================

async def get_eligibility(bot, user_id):
    telegram_ok = await check_telegram_membership(
        bot,
        user_id
    )

    return {
        "telegram": telegram_ok,
        "instagram": True,
        "youtube": True,
    }


def eligibility_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📢 عضویت در تلگرام",
                url=f"https://t.me/{TELEGRAM_CHANNEL.lstrip('@')}"
            ),
        ],
        [
            InlineKeyboardButton(
                "📸 دنبال کردن اینستاگرام",
                url=INSTAGRAM_URL
            ),
            InlineKeyboardButton(
                "▶️ دنبال کردن یوتیوب",
                url=YOUTUBE_URL
            ),
        ],
        [
            InlineKeyboardButton(
                "🔄 بررسی دوباره",
                callback_data="verify_membership"
            ),
        ],
        [
            InlineKeyboardButton(
                "🏠 منوی اصلی",
                callback_data="home"
            ),
        ],
    ])


# ============================================================
# COMMANDS
# ============================================================

async def start(update, context):
    user = update.effective_user

    create_or_update_user(user)

    referral_code = None

    if context.args:
        referral_code = context.args[0]

    if referral_code:
        try:
            inviter_id = int(referral_code)

            if (
                inviter_id != user.id
                and get_user(inviter_id)
            ):
                conn = db()

                existing = conn.execute(
                    """
                    SELECT id
                    FROM referrals
                    WHERE invited_id=?
                    """,
                    (user.id,),
                ).fetchone()

                if not existing:
                    conn.execute(
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
                            now(),
                        ),
                    )

                    conn.execute(
                        """
                        UPDATE users
                        SET referral_count=
                            referral_count+1,
                            chances=chances+1
                        WHERE telegram_id=?
                        """,
                        (inviter_id,),
                    )

                    conn.commit()

                conn.close()

        except Exception:
            pass

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📜 مطالعه و پذیرش قوانین",
                callback_data="accept_rules"
            ),
        ],
    ])

    await update.message.reply_text(
        "🎉 <b>به محفل خوش‌شانس‌ها خوش آمدید!</b>\n\n"
        "اینجا قرعه‌کشی‌ها و مسابقات ویژه برگزار می‌شود.\n\n"
        "🎁 شرکت فعلی رایگان است.\n"
        "👥 دعوت دوستان می‌تواند طبق قوانین برایت شانس اضافه ایجاد کند.\n"
        "🚀 مرحله فعال‌سازی پس از رسیدن شبکه‌ها به حد نصاب انجام می‌شود.\n\n"
        "برای ورود، ابتدا قوانین را مطالعه و تأیید کن.",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def myid(update, context):
    user = update.effective_user

    await update.message.reply_text(
        f"🆔 <b>Telegram ID شما:</b>\n\n"
        f"<code>{user.id}</code>",
        parse_mode=ParseMode.HTML,
    )


async def admin_command(update, context):
    user = update.effective_user

    if not is_admin(user.id):
        await update.message.reply_text(
            "❌ دسترسی ادمین ندارید.\n\n"
            f"🆔 Telegram ID شما:\n"
            f"<code>{user.id}</code>\n\n"
            "این عدد را در Render در قسمت "
            "<code>ADMIN_IDS</code> قرار دهید.",
            parse_mode=ParseMode.HTML,
        )
        return

    await update.message.reply_text(
        "🛠 <b>پنل مدیریت محفل خوش‌شانس‌ها</b>\n\n"
        "مدیریت کامل ربات از این بخش انجام می‌شود.",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_menu(),
    )


async def adminhelp(update, context):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(
            "❌ دسترسی ادمین ندارید."
        )
        return

    text = (
        "🛠 <b>دستورات مدیریت</b>\n\n"
        "/admin — پنل مدیریت\n"
        "/myid — شناسه عددی شما\n"
        "/status — وضعیت کامل\n"
        "/ytfollowers — تعداد یوتیوب\n"
        "/igfollowers 100000 — تعداد اینستاگرام\n"
        "/tgfollowers 100000 — تعداد تلگرام\n"
        "/createcampaign عنوان | توضیحات | جایزه\n"
        "/campaigns — مسابقات\n"
        "/draw ID — قرعه‌کشی\n"
        "/postnow — ارسال تبلیغ\n"
        "/users — آمار کاربران\n"
        "/adminhelp — راهنما"
    )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
    )


async def status(update, context):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(
            "❌ دسترسی ادمین ندارید.\n\n"
            f"🆔 ID: {update.effective_user.id}"
        )
        return

    conn = db()

    users = conn.execute(
        "SELECT COUNT(*) AS c FROM users"
    ).fetchone()["c"]

    referrals = conn.execute(
        "SELECT COUNT(*) AS c FROM referrals"
    ).fetchone()["c"]

    campaigns = conn.execute(
        "SELECT COUNT(*) AS c FROM campaigns"
    ).fetchone()["c"]

    winners = conn.execute(
        "SELECT COUNT(*) AS c FROM winners"
    ).fetchone()["c"]

    conn.close()

    networks = get_networks()

    active = check_activation()

    await update.message.reply_text(
        "📊 <b>وضعیت کامل محفل</b>\n\n"
        f"👥 کاربران: <b>{fmt_number(users)}</b>\n"
        f"🤝 دعوت‌های موفق: <b>{fmt_number(referrals)}</b>\n"
        f"🎁 مسابقات: <b>{fmt_number(campaigns)}</b>\n"
        f"🏆 برندگان: <b>{fmt_number(winners)}</b>\n\n"
        f"📸 Instagram: <b>{fmt_number(networks['instagram'])}</b>\n"
        f"▶️ YouTube: <b>{fmt_number(networks['youtube'])}</b>\n"
        f"📢 Telegram: <b>{fmt_number(networks['telegram'])}</b>\n\n"
        f"🚀 وضعیت فعال‌سازی: "
        f"<b>{'فعال' if active else 'در انتظار'}</b>\n\n"
        f"🆔 Admin ID: <code>{update.effective_user.id}</code>",
        parse_mode=ParseMode.HTML,
    )


async def users_command(update, context):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(
            "❌ دسترسی ادمین ندارید."
        )
        return

    conn = db()

    total = conn.execute(
        "SELECT COUNT(*) AS c FROM users"
    ).fetchone()["c"]

    accepted = conn.execute(
        """
        SELECT COUNT(*) AS c
        FROM users
        WHERE rules_accepted=1
        """
    ).fetchone()["c"]

    referrals = conn.execute(
        "SELECT COUNT(*) AS c FROM referrals"
    ).fetchone()["c"]

    conn.close()

    await update.message.reply_text(
        "👥 <b>آمار کاربران</b>\n\n"
        f"کل کاربران: <b>{fmt_number(total)}</b>\n"
        f"قوانین پذیرفته‌شده: <b>{fmt_number(accepted)}</b>\n"
        f"دعوت موفق: <b>{fmt_number(referrals)}</b>",
        parse_mode=ParseMode.HTML,
    )


async def igfollowers(update, context):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(
            "❌ دسترسی ادمین ندارید."
        )
        return

    if not context.args:
        await update.message.reply_text(
            "مثال:\n/igfollowers 100000"
        )
        return

    try:
        value = int(
            context.args[0].replace(",", "")
        )
    except ValueError:
        await update.message.reply_text(
            "❌ عدد معتبر وارد کنید."
        )
        return

    set_setting(
        "instagram_followers",
        value
    )

    active = check_activation()

    await update.message.reply_text(
        f"📸 Instagram ثبت شد:\n"
        f"<b>{fmt_number(value)}</b>\n\n"
        f"🚀 فعال‌سازی: "
        f"<b>{'فعال' if active else 'در انتظار'}</b>",
        parse_mode=ParseMode.HTML,
    )


async def tgfollowers(update, context):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(
            "❌ دسترسی ادمین ندارید."
        )
        return

    if not context.args:
        await update.message.reply_text(
            "مثال:\n/tgfollowers 100000"
        )
        return

    try:
        value = int(
            context.args[0].replace(",", "")
        )
    except ValueError:
        await update.message.reply_text(
            "❌ عدد معتبر وارد کنید."
        )
        return

    set_setting(
        "telegram_followers",
        value
    )

    active = check_activation()

    await update.message.reply_text(
        f"📢 Telegram ثبت شد:\n"
        f"<b>{fmt_number(value)}</b>\n\n"
        f"🚀 فعال‌سازی: "
        f"<b>{'فعال' if active else 'در انتظار'}</b>",
        parse_mode=ParseMode.HTML,
    )


async def ytfollowers(update, context):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(
            "❌ دسترسی ادمین ندارید.\n\n"
            f"ID: <code>{update.effective_user.id}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    await update.message.reply_text(
        "⏳ در حال دریافت آمار یوتیوب..."
    )

    count = fetch_youtube_followers()

    if count is None:
        await update.message.reply_text(
            "❌ دریافت تعداد مشترکان یوتیوب انجام نشد.\n\n"
            "بررسی کنید:\n"
            "• YOUTUBE_API_KEY\n"
            "• YOUTUBE_CHANNEL_ID\n"
            "• فعال بودن YouTube Data API"
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
        "▶️ <b>YouTube</b>\n\n"
        f"مشترکان: <b>{fmt_number(count)}</b>\n"
        f"حد نصاب: <b>{fmt_number(ACTIVATION_TARGET)}</b>\n\n"
        f"🚀 فعال‌سازی: "
        f"<b>{'فعال' if active else 'در انتظار'}</b>",
        parse_mode=ParseMode.HTML,
    )


async def createcampaign(update, context):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(
            "❌ دسترسی ادمین ندارید."
        )
        return

    raw = " ".join(context.args)

    parts = [
        x.strip()
        for x in raw.split("|")
    ]

    if len(parts) < 3:
        await update.message.reply_text(
            "فرمت صحیح:\n\n"
            "/createcampaign عنوان | توضیحات | جایزه"
        )
        return

    title = parts[0]
    description = parts[1]
    prize = parts[2]

    conn = db()

    cur = conn.execute(
        """
        INSERT INTO campaigns(
            title,
            description,
            prize,
            created_at
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            title,
            description,
            prize,
            now(),
        ),
    )

    campaign_id = cur.lastrowid

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "✅ <b>مسابقه ساخته شد</b>\n\n"
        f"🆔 ID: <code>{campaign_id}</code>\n"
        f"🎁 {title}\n"
        f"💰 جایزه: {prize}",
        parse_mode=ParseMode.HTML,
    )


async def campaigns_command(update, context):
    conn = db()

    rows = conn.execute(
        """
        SELECT *
        FROM campaigns
        ORDER BY id DESC
        LIMIT 20
        """
    ).fetchall()

    conn.close()

    if not rows:
        await update.message.reply_text(
            "🎁 هنوز مسابقه‌ای ساخته نشده است."
        )
        return

    text = "🎁 <b>مسابقات محفل</b>\n\n"

    for row in rows:
        state = (
            "🟢 فعال"
            if row["active"]
            and not row["draw_completed"]
            else "🔴 پایان‌یافته"
        )

        text += (
            f"#{row['id']} — <b>{row['title']}</b>\n"
            f"🎁 {row['prize']}\n"
            f"{state}\n\n"
        )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
    )


async def draw(update, context):
    if not is_admin(update.effective_user.id):
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
        campaign_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "❌ شناسه مسابقه صحیح نیست."
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
            "❌ مسابقه پیدا نشد."
        )
        return

    if campaign["draw_completed"]:
        conn.close()

        await update.message.reply_text(
            "❌ این مسابقه قبلاً قرعه‌کشی شده است."
        )
        return

    rows = conn.execute(
        """
        SELECT p.telegram_id,
               p.chance_count
        FROM participations p
        JOIN users u
          ON u.telegram_id=p.telegram_id
        WHERE p.campaign_id=?
          AND u.blocked=0
        """,
        (campaign_id,),
    ).fetchall()

    conn.close()

    eligible = []

    for row in rows:
        try:
            ok = await check_telegram_membership(
                context.bot,
                row["telegram_id"]
            )
        except Exception:
            ok = False

        if ok:
            repeat = max(
                1,
                int(row["chance_count"])
            )

            eligible.extend(
                [row["telegram_id"]] * repeat
            )

    if not eligible:
        await update.message.reply_text(
            "❌ هیچ شرکت‌کننده واجد شرایطی پیدا نشد."
        )
        return

    winner_id = random.choice(eligible)

    conn = db()

    conn.execute(
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

    conn.execute(
        """
        UPDATE campaigns
        SET draw_completed=1,
            active=0
        WHERE id=?
        """,
        (campaign_id,),
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "🎉 <b>قرعه‌کشی انجام شد!</b>\n\n"
        f"🎁 مسابقه: <b>{campaign['title']}</b>\n"
        f"🏆 جایزه: <b>{campaign['prize']}</b>\n"
        f"🆔 برنده: <code>{winner_id}</code>",
        parse_mode=ParseMode.HTML,
    )

    try:
        await context.bot.send_message(
            chat_id=TELEGRAM_CHANNEL,
            text=(
                "🎉 <b>نتیجه قرعه‌کشی</b>\n\n"
                f"🎁 <b>{campaign['title']}</b>\n"
                f"🏆 جایزه: <b>{campaign['prize']}</b>\n\n"
                f"🆔 شناسه برنده: <code>{winner_id}</code>\n\n"
                "برای اطلاع از مسابقات بعدی، "
                "در محفل بمانید. 🔥"
            ),
            parse_mode=ParseMode.HTML,
        )
    except Exception as exc:
        logger.warning(
            "Winner channel post failed: %s",
            exc
        )


async def postnow(update, context):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(
            "❌ دسترسی ادمین ندارید."
        )
        return

    try:
        message = await context.bot.send_message(
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
            "✅ پیام تبلیغاتی در کانال ارسال شد.\n"
            f"Message ID: {message.message_id}"
        )

    except Exception as exc:
        logger.exception(
            "postnow failed: %s",
            exc
        )

        await update.message.reply_text(
            "❌ ارسال نشد.\n\n"
            "مطمئن شوید ربات در کانال ادمین است "
            "و اجازه ارسال پیام دارد."
        )


# ============================================================
# AUTO POST
# ============================================================

async def automatic_channel_post(context):
    if not AUTO_POST_ENABLED:
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

        logger.info(
            "Automatic channel post sent."
        )

    except Exception as exc:
        logger.warning(
            "Automatic post failed: %s",
            exc
        )


# ============================================================
# CALLBACKS
# ============================================================

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
        "به محفل خوش آمدی! 🎉\n\n"
        "حالا می‌توانی وارد بخش‌های مختلف شوی.",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(),
    )


async def home_callback(update, context):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "🏠 <b>منوی اصلی محفل خوش‌شانس‌ها</b>\n\n"
        "انتخاب کن:",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(),
    )


async def rules_callback(update, context):
    query = update.callback_query
    await query.answer()

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ پذیرش قوانین",
                callback_data="accept_rules"
            ),
        ],
        [
            InlineKeyboardButton(
                "🔙 بازگشت",
                callback_data="home"
            ),
        ],
    ])

    await query.edit_message_text(
        rules_text(),
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def eligibility_callback(update, context):
    query = update.callback_query
    await query.answer()

    result = await get_eligibility(
        context.bot,
        query.from_user.id
    )

    telegram_status = (
        "✅ تأیید شده"
        if result["telegram"]
        else "❌ تأیید نشده"
    )

    await query.edit_message_text(
        "🔎 <b>وضعیت شرایط شما</b>\n\n"
        f"📢 عضویت تلگرام: {telegram_status}\n"
        "📸 اینستاگرام: ℹ️ احراز خودکار هنوز فعال نشده\n"
        "▶️ یوتیوب: ℹ️ احراز خودکار هنوز فعال نشده\n\n"
        "⚠️ برای دریافت جایزه، شرایط نهایی "
        "هر مسابقه ملاک خواهد بود.",
        parse_mode=ParseMode.HTML,
        reply_markup=eligibility_keyboard(),
    )


async def verify_membership(update, context):
    query = update.callback_query

    result = await get_eligibility(
        context.bot,
        query.from_user.id
    )

    await query.answer(
        "عضویت تلگرام تأیید شد ✅"
        if result["telegram"]
        else "عضویت تلگرام هنوز تأیید نشده ❌",
        show_alert=True,
    )

    await eligibility_callback(
        update,
        context
    )


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

    link = (
        f"https://t.me/{BOT_USERNAME}"
        f"?start={query.from_user.id}"
    )

    await query.edit_message_text(
        "👥 <b>دعوت دوستان</b>\n\n"
        f"🎟 شانس‌های فعلی: "
        f"<b>{user['chances']}</b>\n"
        f"👥 دعوت‌های موفق: "
        f"<b>{user['referral_count']}</b>\n\n"
        "دوستت را با لینک زیر وارد محفل کن:\n\n"
        f"<code>{link}</code>\n\n"
        "🎁 طبق قوانین هر مسابقه، دعوت موفق "
        "می‌تواند شانس اضافه ایجاد کند.",
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
        f"🎟 تعداد شانس: <b>{user['chances']}</b>\n"
        f"👥 دعوت موفق: <b>{user['referral_count']}</b>\n\n"
        "شانس‌ها فقط طبق قوانین هر مسابقه "
        "برای همان مسابقه قابل استفاده هستند.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "👥 دعوت دوستان",
                    callback_data="referral"
                ),
            ],
            [
                InlineKeyboardButton(
                    "🏠 منوی اصلی",
                    callback_data="home"
                ),
            ],
        ]),
    )


async def campaigns_callback(update, context):
    query = update.callback_query
    await query.answer()

    conn = db()

    rows = conn.execute(
        """
        SELECT *
        FROM campaigns
        WHERE active=1
          AND draw_completed=0
        ORDER BY id DESC
        """
    ).fetchall()

    conn.close()

    if not rows:
        await query.edit_message_text(
            "🎁 <b>مسابقه فعال فعلاً وجود ندارد.</b>\n\n"
            "🚀 محفل در حال آماده‌سازی مراحل بعدی است.",
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


async def campaign_details(update, context):
    query = update.callback_query
    await query.answer()

    try:
        campaign_id = int(
            query.data.split(":")[1]
        )
    except Exception:
        return

    conn = db()

    row = conn.execute(
        """
        SELECT *
        FROM campaigns
        WHERE id=?
        """,
        (campaign_id,),
    ).fetchone()

    conn.close()

    if not row:
        await query.edit_message_text(
            "❌ مسابقه پیدا نشد."
        )
        return

    await query.edit_message_text(
        f"🎁 <b>{row['title']}</b>\n\n"
        f"{row['description']}\n\n"
        f"🏆 <b>جایزه:</b> {row['prize']}\n\n"
        "برای شرکت باید شرایط مسابقه را داشته باشی.",
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
            ],
        ]),
    )


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

    member_ok = await check_telegram_membership(
        context.bot,
        query.from_user.id
    )

    if not member_ok:
        await query.answer(
            "ابتدا باید عضو کانال تلگرام باشید.",
            show_alert=True
        )

        await query.edit_message_text(
            "❌ <b>شرط عضویت تأیید نشد.</b>\n\n"
            "ابتدا عضو کانال شو و سپس روی "
            "«بررسی دوباره» بزن.",
            parse_mode=ParseMode.HTML,
            reply_markup=eligibility_keyboard(),
        )
        return

    if not check_activation():
        await query.answer(
            "محفل هنوز به حد نصاب فعال‌سازی نرسیده است.",
            show_alert=True
        )
        return

    conn = db()

    campaign = conn.execute(
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
        conn.close()

        await query.answer(
            "این مسابقه فعال نیست.",
            show_alert=True
        )
        return

    existing = conn.execute(
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
        conn.close()

        await query.answer(
            "قبلاً در این مسابقه ثبت‌نام کرده‌ای.",
            show_alert=True
        )
        return

    user = conn.execute(
        """
        SELECT chances
        FROM users
        WHERE telegram_id=?
        """,
        (query.from_user.id,),
    ).fetchone()

    chances = (
        int(user["chances"])
        if user
        else 1
    )

    conn.execute(
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
            now(),
        ),
    )

    conn.commit()
    conn.close()

    await query.answer(
        "با موفقیت وارد مسابقه شدی 🎉",
        show_alert=True
    )

    await query.edit_message_text(
        "🎉 <b>ثبت‌نام شما انجام شد!</b>\n\n"
        f"🎁 {campaign['title']}\n"
        f"🏆 جایزه: {campaign['prize']}\n\n"
        f"🎟 شانس‌های ثبت‌شده: <b>{chances}</b>\n\n"
        "شرایط عضویت هنگام قرعه‌کشی دوباره بررسی می‌شود.",
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


async def support_callback(update, context):
    query = update.callback_query
    await query.answer()

    await query.edit_message_text(
        "🆘 <b>پشتیبانی</b>\n\n"
        "اگر مشکل یا سوالی داری، پیام خودت را همینجا "
        "ارسال کن تا ثبت شود.\n\n"
        f"👤 پشتیبانی مستقیم: {SUPPORT_USERNAME}",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "💬 ارتباط با پشتیبانی",
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
            ],
        ]),
    )


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
                    "🏠 منوی اصلی",
                    callback_data="home"
                )
            ],
        ]),
    )


# ============================================================
# ADMIN CALLBACKS
# ============================================================

async def admin_status_callback(update, context):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        await query.answer(
            "دسترسی ندارید.",
            show_alert=True
        )
        return

    conn = db()

    users = conn.execute(
        "SELECT COUNT(*) c FROM users"
    ).fetchone()["c"]

    campaigns = conn.execute(
        "SELECT COUNT(*) c FROM campaigns"
    ).fetchone()["c"]

    winners = conn.execute(
        "SELECT COUNT(*) c FROM winners"
    ).fetchone()["c"]

    conn.close()

    networks = get_networks()

    await query.edit_message_text(
        "📊 <b>وضعیت مدیریت</b>\n\n"
        f"👥 کاربران: <b>{fmt_number(users)}</b>\n"
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
        ]),
    )


async def admin_users_callback(update, context):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        return

    conn = db()

    total = conn.execute(
        "SELECT COUNT(*) c FROM users"
    ).fetchone()["c"]

    accepted = conn.execute(
        """
        SELECT COUNT(*) c
        FROM users
        WHERE rules_accepted=1
        """
    ).fetchone()["c"]

    refs = conn.execute(
        "SELECT COUNT(*) c FROM referrals"
    ).fetchone()["c"]

    conn.close()

    await query.edit_message_text(
        "👥 <b>آمار کاربران</b>\n\n"
        f"کل: <b>{fmt_number(total)}</b>\n"
        f"پذیرش قوانین: <b>{fmt_number(accepted)}</b>\n"
        f"دعوت‌ها: <b>{fmt_number(refs)}</b>",
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


async def admin_networks_callback(update, context):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        return

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


async def admin_youtube_callback(update, context):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        return

    count = fetch_youtube_followers()

    if count is None:
        text = (
            "❌ دریافت یوتیوب ناموفق بود.\n\n"
            "YOUTUBE_API_KEY و YOUTUBE_CHANNEL_ID "
            "را بررسی کنید."
        )
    else:
        set_setting(
            "youtube_followers",
            count
        )

        check_activation()

        text = (
            "▶️ <b>YouTube بروزرسانی شد</b>\n\n"
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


async def admin_post_callback(update, context):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        return

    try:
        await context.bot.send_message(
            chat_id=TELEGRAM_CHANNEL,
            text=promotional_text(),
            parse_mode=ParseMode.HTML,
        )

        text = "✅ تبلیغ در کانال ارسال شد."

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
        ]),
    )


async def admin_campaigns_callback(update, context):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        return

    conn = db()

    rows = conn.execute(
        """
        SELECT *
        FROM campaigns
        ORDER BY id DESC
        LIMIT 15
        """
    ).fetchall()

    conn.close()

    if not rows:
        text = "🎁 هنوز مسابقه‌ای ساخته نشده."
    else:
        text = "🎁 <b>مسابقات</b>\n\n"

        for row in rows:
            text += (
                f"#{row['id']} "
                f"<b>{row['title']}</b>\n"
                f"🏆 {row['prize']}\n"
                f"وضعیت: "
                f"{'فعال' if row['active'] else 'غیرفعال'}\n\n"
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


async def admin_last_draw_callback(update, context):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        return

    conn = db()

    rows = conn.execute(
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

    conn.close()

    if not rows:
        text = "🎲 هنوز قرعه‌کشی انجام نشده."
    else:
        text = "🎲 <b>آخرین برندگان</b>\n\n"

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
        ]),
    )


async def admin_callback(update, context):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        await query.answer(
            "دسترسی ادمین ندارید.",
            show_alert=True
        )
        return

    await query.edit_message_text(
        "🛠 <b>پنل مدیریت</b>\n\n"
        "همه بخش‌های مدیریتی از اینجا قابل کنترل است.",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_menu(),
    )


# ============================================================
# TEXT MESSAGES
# ============================================================

async def text_message(update, context):
    user = update.effective_user

    create_or_update_user(user)

    text = update.message.text.strip()

    conn = db()

    conn.execute(
        """
        INSERT INTO support_tickets(
            telegram_id,
            message,
            created_at
        )
        VALUES (?, ?, ?)
        """,
        (
            user.id,
            text,
            now(),
        ),
    )

    conn.commit()
    conn.close()

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=(
                    "🆘 <b>پیام جدید پشتیبانی</b>\n\n"
                    f"👤 {user.full_name}\n"
                    f"🆔 <code>{user.id}</code>\n\n"
                    f"{text}"
                ),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

    await update.message.reply_text(
        "✅ پیام شما برای پشتیبانی ثبت شد.\n\n"
        "در صورت نیاز با شما تماس گرفته خواهد شد.",
        reply_markup=main_menu(),
    )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(update, context):
    logger.exception(
        "Unhandled exception: %s",
        context.error
    )

    try:
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "⚠️ یک خطای موقت رخ داد. دوباره تلاش کنید."
            )
    except Exception:
        pass


# ============================================================
# APPLICATION
# ============================================================

def build_application():
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

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

    # Rules
    application.add_handler(
        CallbackQueryHandler(
            accept_rules,
            pattern="^accept_rules$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            rules_callback,
            pattern="^rules$"
        )
    )

    # Main
    application.add_handler(
        CallbackQueryHandler(
            home_callback,
            pattern="^home$"
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
            verify_membership,
            pattern="^verify_membership$"
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

    application.add_handler(
        CallbackQueryHandler(
            support_callback,
            pattern="^support$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            network_callback,
            pattern="^network$"
        )
    )

    # Admin
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
            admin_youtube_callback,
            pattern="^admin_youtube$"
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
            admin_last_draw_callback,
            pattern="^admin_last_draw$"
        )
    )

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
# STARTUP
# ============================================================

async def post_init(application):
    logger.info(
        "MAHFELSHANS BOT started."
    )

    logger.info(
        "Admins: %s",
        sorted(ADMIN_IDS)
    )

    logger.info(
        "Channel: %s",
        TELEGRAM_CHANNEL
    )

    if AUTO_POST_ENABLED:
        application.job_queue.run_repeating(
            automatic_channel_post,
            interval=AUTO_POST_HOURS * 60 * 60,
            first=60,
            name="mahfel_auto_post",
        )

    if YOUTUBE_API_KEY and YOUTUBE_CHANNEL_ID:
        application.job_queue.run_repeating(
            youtube_background_update,
            interval=60 * 60,
            first=120,
            name="youtube_update",
        )


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

        logger.info(
            "YouTube subscribers updated: %s",
            count
        )

    except Exception as exc:
        logger.warning(
            "Background YouTube update failed: %s",
            exc
        )


def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN environment variable is missing."
        )

    init_db()

    application = build_application()

    application.post_init = post_init

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
            "Starting polling..."
        )

        application.run_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES,
        )


if __name__ == "__main__":
    main()
