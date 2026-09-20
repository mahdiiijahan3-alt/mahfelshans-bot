import os
import sqlite3
import logging
import random
import asyncio
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import urlparse

import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# =========================
# CONFIG
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
BOT_USERNAME = os.getenv("BOT_USERNAME", "MahfelShansBot").strip().lstrip("@")
TELEGRAM_CHANNEL = os.getenv("TELEGRAM_CHANNEL", "@MahfelShans").strip()
INSTAGRAM_URL = os.getenv("INSTAGRAM_URL", "https://instagram.com/MAHFELSHANS").strip()
YOUTUBE_URL = os.getenv("YOUTUBE_URL", "https://youtube.com/@mahfelshans").strip()
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "").strip().lstrip("@")
DATABASE = os.getenv("DATABASE", "mahfelshans.db").strip()
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()
YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID", "").strip()

ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().lstrip("-").isdigit()
}

ACTIVATION_TARGET = int(os.getenv("ACTIVATION_TARGET", "100000"))

TELEGRAM_MEMBERSHIP_REQUIRED = (
    os.getenv("TELEGRAM_MEMBERSHIP_REQUIRED", "true").lower()
    in {"1", "true", "yes", "on"}
)

AUTO_POST_ENABLED = (
    os.getenv("AUTO_POST_ENABLED", "true").lower()
    in {"1", "true", "yes", "on"}
)

AUTO_POST_HOURS = max(1, int(os.getenv("AUTO_POST_HOURS", "2")))
PORT = int(os.getenv("PORT", "10000"))

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("MahfelShansBot")

DB_LOCK = asyncio.Lock()


# =========================
# DATABASE
# =========================

def db():
    conn = sqlite3.connect(
        DATABASE,
        timeout=30,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = db()

    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                created_at TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                chances INTEGER NOT NULL DEFAULT 1,
                rules_accepted INTEGER NOT NULL DEFAULT 0,
                referred_by INTEGER
            );

            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER NOT NULL,
                referred_id INTEGER NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS campaigns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                prize TEXT NOT NULL,
                capacity INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'draft',
                draw_at TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS participations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER NOT NULL,
                telegram_id INTEGER NOT NULL,
                chances INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                UNIQUE(campaign_id, telegram_id)
            );

            CREATE TABLE IF NOT EXISTS winners (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER NOT NULL,
                telegram_id INTEGER NOT NULL,
                prize TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS rule_acceptances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                version TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(telegram_id, version)
            );

            CREATE TABLE IF NOT EXISTS support_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sponsors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )

        defaults = {
            "instagram_followers": "0",
            "youtube_followers": "0",
            "telegram_followers": "0",
            "activation_target": str(ACTIVATION_TARGET),
            "network_active": "0",
            "rules_version": "1.0",
            "membership_required": "1"
            if TELEGRAM_MEMBERSHIP_REQUIRED
            else "0",
            "last_auto_post": "",
            "last_youtube_check": "",
            "card_number": "",
            "card_holder": "",
            "payment_note": "",
        }

        for key, value in defaults.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",
                (key, value),
            )

        # Migration برای دیتابیس‌های قدیمی
        migrations = (
            "ALTER TABLE campaigns ADD COLUMN capacity INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE campaigns ADD COLUMN status TEXT NOT NULL DEFAULT 'draft'",
            "ALTER TABLE campaigns ADD COLUMN draw_at TEXT",
        )

        for sql in migrations:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                pass

        conn.commit()

    finally:
        conn.close()


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_setting(key, default=None):
    conn = db()

    try:
        row = conn.execute(
            "SELECT value FROM settings WHERE key=?",
            (key,),
        ).fetchone()

        return row["value"] if row else default

    finally:
        conn.close()


def set_setting(key, value):
    conn = db()

    try:
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

    finally:
        conn.close()


def network_is_active():
    target = int(
        get_setting(
            "activation_target",
            ACTIVATION_TARGET,
        )
        or ACTIVATION_TARGET
    )

    ig = int(get_setting("instagram_followers", 0) or 0)
    yt = int(get_setting("youtube_followers", 0) or 0)
    tg = int(get_setting("telegram_followers", 0) or 0)

    active = (
        ig >= target
        and yt >= target
        and tg >= target
    )

    if active:
        set_setting("network_active", "1")

    return active


def ensure_user(user, referred_by=None):
    conn = db()

    try:
        stamp = now_iso()

        conn.execute(
            """
            INSERT INTO users(
                telegram_id,
                username,
                first_name,
                last_name,
                created_at,
                last_seen,
                referred_by
            )
            VALUES(?,?,?,?,?,?,?)

            ON CONFLICT(telegram_id)
            DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                last_name=excluded.last_name,
                last_seen=excluded.last_seen
            """,
            (
                user.id,
                user.username,
                user.first_name,
                user.last_name,
                stamp,
                stamp,
                referred_by,
            ),
        )

        conn.commit()

    finally:
        conn.close()


def add_referral(referrer_id, referred_id):
    if referrer_id == referred_id:
        return False

    conn = db()

    try:
        existing = conn.execute(
            "SELECT id FROM referrals WHERE referred_id=?",
            (referred_id,),
        ).fetchone()

        if existing:
            return False

        ref_exists = conn.execute(
            "SELECT telegram_id FROM users WHERE telegram_id=?",
            (referrer_id,),
        ).fetchone()

        if not ref_exists:
            return False

        conn.execute(
            """
            INSERT INTO referrals(
                referrer_id,
                referred_id,
                created_at
            )
            VALUES(?,?,?)
            """,
            (
                referrer_id,
                referred_id,
                now_iso(),
            ),
        )

        conn.execute(
            """
            UPDATE users
            SET chances=chances+1
            WHERE telegram_id=?
            """,
            (referrer_id,),
        )

        conn.commit()
        return True

    except sqlite3.IntegrityError:
        return False

    finally:
        conn.close()


def save_rules_acceptance(telegram_id):
    version = get_setting(
        "rules_version",
        "1.0",
    )

    conn = db()

    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO rule_acceptances(
                telegram_id,
                version,
                created_at
            )
            VALUES(?,?,?)
            """,
            (
                telegram_id,
                version,
                now_iso(),
            ),
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

    finally:
        conn.close()


def user_chances(telegram_id):
    conn = db()

    try:
        row = conn.execute(
            "SELECT chances FROM users WHERE telegram_id=?",
            (telegram_id,),
        ).fetchone()

        return int(row["chances"]) if row else 0

    finally:
        conn.close()


# =========================
# UI
# =========================

def main_menu():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🎯 مسابقات و جوایز",
                    callback_data="campaigns",
                )
            ],
            [
                InlineKeyboardButton(
                    "🎟 شانس‌های من",
                    callback_data="my_chances",
                ),
                InlineKeyboardButton(
                    "👥 دعوت دوستان",
                    callback_data="referral",
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
                )
            ],
            [
                InlineKeyboardButton(
                    "✅ شرایط شرکت",
                    callback_data="eligibility",
                ),
                InlineKeyboardButton(
                    "📜 قوانین",
                    callback_data="rules",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🆘 پشتیبانی",
                    callback_data="support",
                )
            ],
        ]
    )


def admin_menu():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📊 وضعیت شبکه",
                    callback_data="admin_status",
                ),
                InlineKeyboardButton(
                    "👥 کاربران",
                    callback_data="admin_users",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🎁 مسابقات",
                    callback_data="admin_campaigns",
                ),
                InlineKeyboardButton(
                    "📣 ارسال پست",
                    callback_data="admin_post",
                ),
            ],
            [
                InlineKeyboardButton(
                    "💳 تنظیمات پرداخت",
                    callback_data="admin_payment",
                )
            ],
            [
                InlineKeyboardButton(
                    "▶️ بررسی یوتیوب",
                    callback_data="admin_youtube",
                ),
                InlineKeyboardButton(
                    "🌐 شبکه‌ها",
                    callback_data="admin_networks",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🏠 خانه",
                    callback_data="home",
                )
            ],
        ]
    )


def rules_text():
    return (
        "📜 <b>قوانین محفل خوش‌شانس‌ها</b>\n\n"
        "1) شرکت در برنامه‌های فعلی رایگان است.\n"
        "2) برای دریافت جایزه باید شرایط همان مسابقه را کامل داشته باشید.\n"
        "3) عضویت در کانال تلگرام در صورت فعال بودن شرط، هنگام بررسی برنده کنترل می‌شود.\n"
        "4) دنبال‌کردن اینستاگرام و یوتیوب از شرایط اعلام‌شده برای واجدشرایط‌بودن است؛ راستی‌آزمایی خودکار این دو شبکه در نسخه فعلی هنوز فعال نشده است.\n"
        "5) فعال‌شدن قرعه‌کشی اصلی پس از رسیدن هر سه شبکه به ۱۰۰٬۰۰۰ دنبال‌کننده/عضو انجام می‌شود.\n"
        "6) نتیجه قرعه‌کشی و شرایط هر جایزه باید از مسیرهای رسمی محفل اعلام شود."
    )


def home_text(user):
    return (
        f"🎉 <b>به محفل خوش‌شانس‌ها خوش آمدی، "
        f"{user.first_name or 'دوست عزیز'}!</b>\n\n"
        "اینجا شرکت در برنامه‌های محفل رایگان است و "
        "با دعوت دوستان می‌توانی شانس‌های بیشتری بگیری.\n\n"
        "🎯 هدف بزرگ: رسیدن شبکه محفل به ۱۰۰٬۰۰۰\n"
        "🎁 پس از فعال‌شدن شبکه، قرعه‌کشی‌ها طبق قوانین اعلام می‌شوند.\n\n"
        "برای شروع، یکی از گزینه‌های زیر را انتخاب کن."
    )


# =========================
# CHECKS
# =========================

async def check_telegram_membership(bot, user_id):
    required = get_setting(
        "membership_required",
        "1",
    ) == "1"

    if not required:
        return True

    try:
        member = await bot.get_chat_member(
            TELEGRAM_CHANNEL,
            user_id,
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
                    False,
                )
            )

        return False

    except Exception as exc:
        logger.warning(
            "Telegram membership check failed for %s: %s",
            user_id,
            exc,
        )
        return False


def youtube_followers_from_api():
    if not YOUTUBE_API_KEY or not YOUTUBE_CHANNEL_ID:
        raise RuntimeError(
            "YOUTUBE_API_KEY و YOUTUBE_CHANNEL_ID تنظیم نشده‌اند"
        )

    response = requests.get(
        "https://www.googleapis.com/youtube/v3/channels",
        params={
            "part": "statistics",
            "id": YOUTUBE_CHANNEL_ID,
            "key": YOUTUBE_API_KEY,
        },
        timeout=20,
    )

    response.raise_for_status()

    data = response.json()

    items = data.get("items") or []

    if not items:
        raise RuntimeError(
            "کانال یوتیوب پیدا نشد یا Channel ID اشتباه است"
        )

    return int(
        items[0]["statistics"].get(
            "subscriberCount",
            0,
        )
    )


# =========================
# TEXT HANDLERS
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    referrer_id = None

    if context.args:
        raw = context.args[0].strip()

        if raw.isdigit():
            referrer_id = int(raw)

    ensure_user(
        user,
        referrer_id,
    )

    if referrer_id is not None:
        add_referral(
            referrer_id,
            user.id,
        )

    await update.message.reply_text(
        home_text(user),
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(),
    )


async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Telegram ID شما:\n"
        f"<code>{update.effective_user.id}</code>",
        parse_mode=ParseMode.HTML,
    )


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text(
            "⛔ دسترسی ندارید."
        )
        return

    await update.message.reply_text(
        "🛠 <b>پنل مدیریت محفل</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_menu(),
    )


async def admin_payment_menu(query, context):
    if query.from_user.id not in ADMIN_IDS:
        return

    card = get_setting(
        "card_number",
        "",
    )

    holder = get_setting(
        "card_holder",
        "",
    )

    note = get_setting(
        "payment_note",
        "",
    )

    text = (
        "💳 <b>تنظیمات پرداخت</b>\n\n"
        f"شماره کارت: <code>{card or 'ثبت نشده'}</code>\n"
        f"صاحب کارت: {holder or 'ثبت نشده'}\n"
        f"توضیح: {note or 'ثبت نشده'}\n\n"
        "از دکمه‌های زیر برای ثبت یا تغییر اطلاعات استفاده کن."
    )

    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "💳 ثبت/تغییر شماره کارت",
                    callback_data="pay_set_card",
                )
            ],
            [
                InlineKeyboardButton(
                    "👤 ثبت/تغییر صاحب کارت",
                    callback_data="pay_set_holder",
                )
            ],
            [
                InlineKeyboardButton(
                    "📝 ثبت/تغییر توضیح",
                    callback_data="pay_set_note",
                )
            ],
            [
                InlineKeyboardButton(
                    "🗑 حذف شماره کارت",
                    callback_data="pay_clear_card",
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 پنل مدیریت",
                    callback_data="admin_home",
                )
            ],
        ]
    )

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
    )


async def admin_payment_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    card = get_setting(
        "card_number",
        "",
    )

    holder = get_setting(
        "card_holder",
        "",
    )

    note = get_setting(
        "payment_note",
        "",
    )

    await update.message.reply_text(
        f"💳 شماره کارت: <code>{card or 'ثبت نشده'}</code>\n"
        f"👤 صاحب کارت: {holder or 'ثبت نشده'}\n"
        f"📝 توضیح: {note or 'ثبت نشده'}",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "💳 مدیریت اطلاعات",
                        callback_data="admin_payment",
                    )
                ]
            ]
        ),
    )


async def adminhelp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    text = (
        "<b>دستورات مدیریت</b>\n\n"
        "/status\n"
        "/users\n"
        "/igfollowers 100000\n"
        "/tgfollowers 100000\n"
        "/ytfollowers\n"
        "/createcampaign عنوان | توضیح | جایزه\n"
        "/campaigns\n"
        "/draw ID\n"
        "/postnow\n"
        "/paymentsettings\n\n"
        "برای تنظیم شماره کارت، از پنل ادمین → "
        "💳 تنظیمات پرداخت استفاده کن."
    )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    target = int(
        get_setting(
            "activation_target",
            ACTIVATION_TARGET,
        )
    )

    ig = int(
        get_setting(
            "instagram_followers",
            0,
        )
    )

    yt = int(
        get_setting(
            "youtube_followers",
            0,
        )
    )

    tg = int(
        get_setting(
            "telegram_followers",
            0,
        )
    )

    active = network_is_active()

    conn = db()

    try:
        users = conn.execute(
            "SELECT COUNT(*) c FROM users"
        ).fetchone()["c"]

        campaigns = conn.execute(
            "SELECT COUNT(*) c FROM campaigns WHERE active=1"
        ).fetchone()["c"]

    finally:
        conn.close()

    text = (
        "📊 <b>وضعیت محفل</b>\n\n"
        f"اینستاگرام: {ig:,}\n"
        f"یوتیوب: {yt:,}\n"
        f"تلگرام: {tg:,}\n"
        f"هدف: {target:,}\n"
        f"فعال‌شدن شبکه: "
        f"{'✅ بله' if active else '❌ خیر'}\n"
        f"کاربران ربات: {users:,}\n"
        f"مسابقات فعال: {campaigns:,}"
    )

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
    )


async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    conn = db()

    try:
        total = conn.execute(
            "SELECT COUNT(*) c FROM users"
        ).fetchone()["c"]

        refs = conn.execute(
            "SELECT COUNT(*) c FROM referrals"
        ).fetchone()["c"]

    finally:
        conn.close()

    await update.message.reply_text(
        f"👥 کاربران: {total:,}\n"
        f"👥 دعوت‌های ثبت‌شده: {refs:,}"
    )


async def set_ig_followers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    if (
        not context.args
        or not context.args[0].isdigit()
    ):
        await update.message.reply_text(
            "مثال: /igfollowers 100000"
        )
        return

    set_setting(
        "instagram_followers",
        int(context.args[0]),
    )

    network_is_active()

    await update.message.reply_text(
        "✅ تعداد اینستاگرام ثبت شد."
    )


async def set_tg_followers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    if (
        not context.args
        or not context.args[0].isdigit()
    ):
        await update.message.reply_text(
            "مثال: /tgfollowers 100000"
        )
        return

    set_setting(
        "telegram_followers",
        int(context.args[0]),
    )

    network_is_active()

    await update.message.reply_text(
        "✅ تعداد تلگرام ثبت شد."
    )


async def set_yt_followers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    try:
        count = youtube_followers_from_api()

        set_setting(
            "youtube_followers",
            count,
        )

        set_setting(
            "last_youtube_check",
            now_iso(),
        )

        network_is_active()

        await update.message.reply_text(
            f"✅ مشترکین یوتیوب: {count:,}"
        )

    except Exception as exc:
        await update.message.reply_text(
            f"❌ بررسی یوتیوب انجام نشد:\n{exc}"
        )


async def create_campaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    raw = " ".join(context.args)

    parts = [
        p.strip()
        for p in raw.split("|")
    ]

    if len(parts) != 3 or not all(parts):
        await update.message.reply_text(
            "فرمت:\n"
            "/createcampaign عنوان | توضیح | جایزه"
        )
        return

    conn = db()

    try:
        cur = conn.execute(
            """
            INSERT INTO campaigns(
                title,
                description,
                prize,
                created_at
            )
            VALUES(?,?,?,?)
            """,
            (
                parts[0],
                parts[1],
                parts[2],
                now_iso(),
            ),
        )

        conn.commit()

        cid = cur.lastrowid

    finally:
        conn.close()

    await update.message.reply_text(
        f"✅ مسابقه #{cid} ساخته شد."
    )


async def campaigns_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = db()

    try:
        rows = conn.execute(
            """
            SELECT *
            FROM campaigns
            WHERE active=1
            ORDER BY id DESC
            """
        ).fetchall()

    finally:
        conn.close()

    if not rows:
        await update.message.reply_text(
            "🎁 فعلاً مسابقه فعالی وجود ندارد."
        )
        return

    lines = [
        "🎁 <b>مسابقات فعال</b>"
    ]

    for r in rows:
        lines.append(
            f"\n<b>#{r['id']} — {r['title']}</b>\n"
            f"{r['description']}\n"
            f"🎁 جایزه: {r['prize']}"
        )

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
    )


async def draw_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    if (
        not context.args
        or not context.args[0].isdigit()
    ):
        await update.message.reply_text(
            "مثال: /draw 1"
        )
        return

    campaign_id = int(
        context.args[0]
    )

    if not network_is_active():
        await update.message.reply_text(
            "⛔ شبکه هنوز به هدف ۱۰۰٬۰۰۰ نرسیده است."
        )
        return

    conn = db()

    try:
        campaign = conn.execute(
            """
            SELECT *
            FROM campaigns
            WHERE id=?
            AND active=1
            """,
            (campaign_id,),
        ).fetchone()

        if not campaign:
            await update.message.reply_text(
                "مسابقه پیدا نشد یا غیرفعال است."
            )
            return

        participants = conn.execute(
            """
            SELECT telegram_id,chances
            FROM participations
            WHERE campaign_id=?
            """,
            (campaign_id,),
        ).fetchall()

    finally:
        conn.close()

    eligible = []

    for p in participants:
        if await check_telegram_membership(
            context.bot,
            p["telegram_id"],
        ):
            eligible.extend(
                [p["telegram_id"]]
                * max(
                    1,
                    int(p["chances"]),
                )
            )

    if not eligible:
        await update.message.reply_text(
            "❌ شرکت‌کننده واجدشرایطی پیدا نشد."
        )
        return

    winner = random.choice(
        eligible
    )

    conn = db()

    try:
        conn.execute(
            """
            INSERT INTO winners(
                campaign_id,
                telegram_id,
                prize,
                created_at
            )
            VALUES(?,?,?,?)
            """,
            (
                campaign_id,
                winner,
                campaign["prize"],
                now_iso(),
            ),
        )

        conn.execute(
            """
            UPDATE campaigns
            SET active=0,
                status='completed'
            WHERE id=?
            """,
            (campaign_id,),
        )

        conn.commit()

    finally:
        conn.close()

    await update.message.reply_text(
        f"🏆 برنده مسابقه #{campaign_id}: "
        f"<code>{winner}</code>\n"
        f"🎁 جایزه: {campaign['prize']}",
        parse_mode=ParseMode.HTML,
    )

    try:
        await context.bot.send_message(
            winner,
            f"🎉 تبریک! شما برنده مسابقه "
            f"<b>{campaign['title']}</b> شدید.\n"
            f"🎁 جایزه: {campaign['prize']}",
            parse_mode=ParseMode.HTML,
        )

    except Exception:
        logger.info(
            "Could not DM winner %s",
            winner,
        )


async def postnow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    ok = await send_auto_post(
        context.bot
    )

    await update.message.reply_text(
        "✅ پست ارسال شد."
        if ok
        else
        "❌ ارسال پست ناموفق بود. "
        "دسترسی ادمین کانال را بررسی کن."
    )


# =========================
# CALLBACKS
# =========================

async def campaigns_callback(query, context):
    conn = db()

    try:
        rows = conn.execute(
            """
            SELECT *
            FROM campaigns
            WHERE active=1
            ORDER BY id DESC
            """
        ).fetchall()

    finally:
        conn.close()

    if not rows:
        await query.edit_message_text(
            "🎁 فعلاً مسابقه فعالی وجود ندارد.",
            reply_markup=main_menu(),
        )
        return

    buttons = []

    text = "🎁 <b>مسابقات فعال</b>\n\n"

    for r in rows:
        text += (
            f"<b>#{r['id']} — {r['title']}</b>\n"
            f"{r['description']}\n"
            f"🎁 {r['prize']}\n"
            f"🔢 ظرفیت: {r['capacity']:,}\n\n"
        )

        buttons.append(
            [
                InlineKeyboardButton(
                    f"🎟 شرکت در #{r['id']}",
                    callback_data=f"join:{r['id']}",
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                "🔙 خانه",
                callback_data="home",
            )
        ]
    )

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def join_campaign(query, context, campaign_id):
    user_id = query.from_user.id

    if not network_is_active():
        await query.answer(
            "هنوز شبکه به ۱۰۰٬۰۰۰ نرسیده است.",
            show_alert=True,
        )
        return

    if not await check_telegram_membership(
        context.bot,
        user_id,
    ):
        await query.answer(
            "ابتدا باید عضو کانال تلگرام محفل شوی.",
            show_alert=True,
        )
        return

    conn = db()

    try:
        campaign = conn.execute(
            """
            SELECT *
            FROM campaigns
            WHERE id=?
            AND active=1
            """,
            (campaign_id,),
        ).fetchone()

        if not campaign:
            await query.answer(
                "این مسابقه فعال نیست.",
                show_alert=True,
            )
            return

        if int(
            campaign["capacity"] or 0
        ) > 0:

            count = conn.execute(
                """
                SELECT COUNT(*) c
                FROM participations
                WHERE campaign_id=?
                """,
                (campaign_id,),
            ).fetchone()["c"]

            already = conn.execute(
                """
                SELECT 1
                FROM participations
                WHERE campaign_id=?
                AND telegram_id=?
                """,
                (
                    campaign_id,
                    user_id,
                ),
            ).fetchone()

            if (
                not already
                and count >= int(
                    campaign["capacity"]
                )
            ):
                await query.answer(
                    "ظرفیت این مسابقه تکمیل شده است.",
                    show_alert=True,
                )
                return

        chances = user_chances(
            user_id
        )

        conn.execute(
            """
            INSERT INTO participations(
                campaign_id,
                telegram_id,
                chances,
                created_at
            )
            VALUES(?,?,?,?)

            ON CONFLICT(
                campaign_id,
                telegram_id
            )
            DO UPDATE SET
                chances=excluded.chances
            """,
            (
                campaign_id,
                user_id,
                max(
                    1,
                    chances,
                ),
                now_iso(),
            ),
        )

        conn.commit()

    finally:
        conn.close()

    await query.answer(
        "🎟 ثبت شد!",
        show_alert=True,
    )


async def eligibility_callback(query, context):
    user_id = query.from_user.id

    tg = await check_telegram_membership(
        context.bot,
        user_id,
    )

    active = network_is_active()

    text = (
        "✅ <b>بررسی شرایط</b>\n\n"
        f"عضویت تلگرام: {'✅' if tg else '❌'}\n"
        "اینستاگرام: شرط اعلام‌شده است؛ "
        "بررسی خودکار هنوز فعال نشده\n"
        "یوتیوب: شرط اعلام‌شده است؛ "
        "بررسی خودکار هنوز فعال نشده\n"
        f"فعال‌شدن قرعه‌کشی شبکه: "
        f"{'✅' if active else '❌'}"
    )

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🔙 خانه",
                        callback_data="home",
                    )
                ]
            ]
        ),
    )


async def referral_callback(query, context):
    uid = query.from_user.id

    link = (
        f"https://t.me/"
        f"{BOT_USERNAME}"
        f"?start={uid}"
    )

    text = (
        "👥 <b>دعوت دوستان</b>\n\n"
        "این لینک اختصاصی توست:\n"
        f"<code>{link}</code>\n\n"
        "هر دعوت معتبر، یک شانس اضافه برایت ثبت می‌کند."
    )

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🔙 خانه",
                        callback_data="home",
                    )
                ]
            ]
        ),
    )


async def my_chances_callback(query, context):
    chances = user_chances(
        query.from_user.id
    )

    await query.edit_message_text(
        f"🎟 <b>شانس‌های تو</b>\n\n"
        f"تعداد شانس فعلی: <b>{chances}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🔙 خانه",
                        callback_data="home",
                    )
                ]
            ]
        ),
    )


async def rules_callback(query, context):
    buttons = [
        [
            InlineKeyboardButton(
                "✅ قوانین را می‌پذیرم",
                callback_data="accept_rules",
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 خانه",
                callback_data="home",
            )
        ],
    ]

    await query.edit_message_text(
        rules_text(),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def accept_rules(query, context):
    save_rules_acceptance(
        query.from_user.id
    )

    await query.answer(
        "قوانین ثبت شد.",
        show_alert=True,
    )

    await query.edit_message_text(
        "✅ پذیرش قوانین با موفقیت ثبت شد.",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🔙 خانه",
                        callback_data="home",
                    )
                ]
            ]
        ),
    )


async def support_callback(query, context):
    if SUPPORT_USERNAME:
        markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "💬 ارتباط با پشتیبانی",
                        url=f"https://t.me/{SUPPORT_USERNAME}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔙 خانه",
                        callback_data="home",
                    )
                ],
            ]
        )

        text = (
            "🆘 <b>پشتیبانی</b>\n\n"
            "برای ارتباط با پشتیبانی روی دکمه زیر بزن."
        )

    else:
        markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🔙 خانه",
                        callback_data="home",
                    )
                ]
            ]
        )

        text = (
            "🆘 پشتیبانی هنوز تنظیم نشده است."
        )

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
    )


async def admin_status_callback(query, context):
    if query.from_user.id not in ADMIN_IDS:
        return

    target = int(
        get_setting(
            "activation_target",
            ACTIVATION_TARGET,
        )
    )

    ig = int(
        get_setting(
            "instagram_followers",
            0,
        )
    )

    yt = int(
        get_setting(
            "youtube_followers",
            0,
        )
    )

    tg = int(
        get_setting(
            "telegram_followers",
            0,
        )
    )

    text = (
        f"📊 IG: {ig:,}\n"
        f"▶️ YT: {yt:,}\n"
        f"📢 TG: {tg:,}\n"
        f"🎯 هدف: {target:,}\n"
        f"🌐 فعال: "
        f"{'✅' if network_is_active() else '❌'}"
    )

    await query.edit_message_text(
        text,
        reply_markup=admin_menu(),
    )


async def admin_users_callback(query, context):
    if query.from_user.id not in ADMIN_IDS:
        return

    conn = db()

    try:
        users = conn.execute(
            "SELECT COUNT(*) c FROM users"
        ).fetchone()["c"]

        refs = conn.execute(
            "SELECT COUNT(*) c FROM referrals"
        ).fetchone()["c"]

    finally:
        conn.close()

    await query.edit_message_text(
        f"👥 کاربران: {users:,}\n"
        f"👥 دعوت‌ها: {refs:,}",
        reply_markup=admin_menu(),
    )


async def admin_campaigns_callback(query, context):
    if query.from_user.id not in ADMIN_IDS:
        return

    conn = db()

    try:
        rows = conn.execute(
            """
            SELECT
                id,
                title,
                active,
                status,
                capacity
            FROM campaigns
            ORDER BY id DESC
            LIMIT 20
            """
        ).fetchall()

    finally:
        conn.close()

    lines = [
        "🎁 <b>مدیریت مسابقات</b>",
        "",
    ]

    buttons = []

    for r in rows:
        if r["active"]:
            status = "🟢 فعال"
        elif r["status"] == "queued":
            status = "🟡 صف"
        elif r["status"] == "completed":
            status = "🏁 پایان‌یافته"
        else:
            status = "⚪ بسته"

        lines.append(
            f"#{r['id']} — "
            f"{r['title']} — "
            f"{status} — "
            f"ظرفیت {r['capacity']:,}"
        )

        if (
            not r["active"]
            and r["status"] in (
                "queued",
                "draft",
            )
        ):
            buttons.append(
                [
                    InlineKeyboardButton(
                        f"🟢 ورود #{r['id']} به چرخه",
                        callback_data=f"activate_campaign:{r['id']}",
                    )
                ]
            )

    text = "\n".join(lines)

    buttons.append(
        [
            InlineKeyboardButton(
                "➕ ساخت مسابقه جدید",
                callback_data="campaign_new",
            )
        ]
    )

    buttons.append(
        [
            InlineKeyboardButton(
                "🔙 پنل مدیریت",
                callback_data="admin_home",
            )
        ]
    )

    markup = InlineKeyboardMarkup(
        buttons
    )

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
    )


async def admin_post_callback(query, context):
    if query.from_user.id not in ADMIN_IDS:
        return

    ok = await send_auto_post(
        context.bot
    )

    await query.answer(
        "ارسال شد."
        if ok
        else
        "ارسال ناموفق بود.",
        show_alert=True,
    )


async def admin_youtube_callback(query, context):
    if query.from_user.id not in ADMIN_IDS:
        return

    try:
        count = youtube_followers_from_api()

        set_setting(
            "youtube_followers",
            count,
        )

        set_setting(
            "last_youtube_check",
            now_iso(),
        )

        network_is_active()

        await query.edit_message_text(
            f"▶️ مشترکین یوتیوب: {count:,}",
            reply_markup=admin_menu(),
        )

    except Exception as exc:
        await query.edit_message_text(
            f"❌ خطا: {exc}",
            reply_markup=admin_menu(),
        )


async def admin_networks_callback(query, context):
    if query.from_user.id not in ADMIN_IDS:
        return

    text = (
        f"🌐 <b>شبکه‌ها</b>\n\n"
        f"Instagram: "
        f"{get_setting('instagram_followers', '0')}\n"
        f"YouTube: "
        f"{get_setting('youtube_followers', '0')}\n"
        f"Telegram: "
        f"{get_setting('telegram_followers', '0')}\n"
        f"Target: "
        f"{get_setting('activation_target', ACTIVATION_TARGET)}\n"
        f"Active: "
        f"{'YES' if network_is_active() else 'NO'}"
    )

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=admin_menu(),
    )


# =========================
# CALLBACK ROUTER
# =========================

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    await query.answer()

    data = query.data or ""

    if data == "home":

        await query.edit_message_text(
            home_text(
                query.from_user
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu(),
        )

    elif data == "campaigns":

        await campaigns_callback(
            query,
            context,
        )

    elif data.startswith("join:"):

        try:
            cid = int(
                data.split(
                    ":",
                    1,
                )[1]
            )

            await join_campaign(
                query,
                context,
                cid,
            )

        except ValueError:

            await query.answer(
                "شناسه مسابقه نامعتبر است.",
                show_alert=True,
            )

    elif data == "my_chances":

        await my_chances_callback(
            query,
            context,
        )

    elif data == "referral":

        await referral_callback(
            query,
            context,
        )

    elif data == "eligibility":

        await eligibility_callback(
            query,
            context,
        )

    elif data == "rules":

        await rules_callback(
            query,
            context,
        )

    elif data == "accept_rules":

        await accept_rules(
            query,
            context,
        )

    elif data == "support":

        await support_callback(
            query,
            context,
        )

    elif data == "admin_status":

        await admin_status_callback(
            query,
            context,
        )

    elif data == "admin_users":

        await admin_users_callback(
            query,
            context,
        )

    elif data == "admin_campaigns":

        await admin_campaigns_callback(
            query,
            context,
        )

    elif data == "admin_post":

        await admin_post_callback(
            query,
            context,
        )

    elif data == "admin_youtube":

        await admin_youtube_callback(
            query,
            context,
        )

    elif data == "admin_networks":

        await admin_networks_callback(
            query,
            context,
        )

    elif data.startswith("activate_campaign:"):

        if query.from_user.id not in ADMIN_IDS:
            return

        try:

            cid = int(
                data.split(
                    ":",
                    1,
                )[1]
            )

            conn = db()

            try:

                campaign = conn.execute(
                    "SELECT * FROM campaigns WHERE id=?",
                    (cid,),
                ).fetchone()

                if not campaign:

                    await query.answer(
                        "مسابقه پیدا نشد.",
                        show_alert=True,
                    )

                    return

                # فقط یک مسابقه فعال
                conn.execute(
                    """
                    UPDATE campaigns
                    SET active=0
                    WHERE active=1
                    """
                )

                conn.execute(
                    """
                    UPDATE campaigns
                    SET active=1,
                        status='active'
                    WHERE id=?
                    """,
                    (cid,),
                )

                conn.commit()

            finally:
                conn.close()

            await query.answer(
                "مسابقه وارد چرخه شد.",
                show_alert=True,
            )

            await admin_campaigns_callback(
                query,
                context,
            )

        except Exception as exc:

            logger.exception(
                "activate campaign failed: %s",
                exc,
            )

            await query.answer(
                "خطا در فعال‌سازی.",
                show_alert=True,
            )

    elif data == "campaign_new":

        context.user_data[
            "campaign_wizard"
        ] = {
            "step": "title"
        }

        await query.edit_message_text(
            "➕ <b>ساخت مسابقه جدید</b>\n\n"
            "🎁 نام جایزه/مسابقه را وارد کن.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔙 انصراف",
                            callback_data="campaign_new_cancel",
                        )
                    ]
                ]
            ),
        )

    elif data == "campaign_new_cancel":

        context.user_data.pop(
            "campaign_wizard",
            None,
        )

        await admin_campaigns_callback(
            query,
            context,
        )

    elif data == "admin_home":

        await query.edit_message_text(
            "🛠 <b>پنل مدیریت محفل</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_menu(),
        )

    elif data == "admin_payment":

        await admin_payment_menu(
            query,
            context,
        )

    elif data == "pay_set_card":

        context.user_data[
            "admin_input"
        ] = "card_number"

        await query.edit_message_text(
            "💳 شماره کارت را به صورت ۱۶ رقم وارد کن.\n"
            "مثال: <code>1234567812345678</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔙 انصراف",
                            callback_data="admin_payment",
                        )
                    ]
                ]
            ),
        )

    elif data == "pay_set_holder":

        context.user_data[
            "admin_input"
        ] = "card_holder"

        await query.edit_message_text(
            "👤 نام صاحب کارت را وارد کن.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔙 انصراف",
                            callback_data="admin_payment",
                        )
                    ]
                ]
            ),
        )

    elif data == "pay_set_note":

        context.user_data[
            "admin_input"
        ] = "payment_note"

        await query.edit_message_text(
            "📝 توضیحی که می‌خواهی کنار "
            "اطلاعات پرداخت نمایش داده شود را وارد کن.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔙 انصراف",
                            callback_data="admin_payment",
                        )
                    ]
                ]
            ),
        )

    elif data == "pay_clear_card":

        set_setting(
            "card_number",
            "",
        )

        await admin_payment_menu(
            query,
            context,
        )


# =========================
# TEXT MESSAGE
# =========================

async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        update.message.text or ""
    ).strip()

    if text.startswith("/"):
        return

    # =========================
    # ADMIN CAMPAIGN WIZARD
    # =========================

    if (
        update.effective_user.id in ADMIN_IDS
        and context.user_data.get(
            "campaign_wizard"
        )
    ):

        wiz = context.user_data[
            "campaign_wizard"
        ]

        step = wiz.get(
            "step"
        )

        if step == "title":

            wiz["title"] = text[:150]
            wiz["step"] = "prize"

            await update.message.reply_text(
                "🎁 جایزه دقیق را وارد کن."
            )

            return

        if step == "prize":

            wiz["prize"] = text[:300]
            wiz["step"] = "description"

            await update.message.reply_text(
                "📝 توضیحات مسابقه را وارد کن."
            )

            return

        if step == "description":

            wiz["description"] = text[:1000]
            wiz["step"] = "capacity"

            await update.message.reply_text(
                "🔢 ظرفیت را به عدد وارد کن. "
                "مثال: 2000"
            )

            return

        if step == "capacity":

            if (
                not text.isdigit()
                or int(text) < 1
            ):

                await update.message.reply_text(
                    "❌ ظرفیت باید یک عدد بزرگ‌تر از صفر باشد."
                )

                return

            wiz["capacity"] = int(text)

            conn = db()

            try:

                cur = conn.execute(
                    """
                    INSERT INTO campaigns(
                        title,
                        description,
                        prize,
                        capacity,
                        active,
                        status,
                        created_at
                    )
                    VALUES(?,?,?,?,?,?,?)
                    """,
                    (
                        wiz["title"],
                        wiz["description"],
                        wiz["prize"],
                        wiz["capacity"],
                        0,
                        "queued",
                        now_iso(),
                    ),
                )

                cid = cur.lastrowid

                conn.commit()

            finally:
                conn.close()

            context.user_data.pop(
                "campaign_wizard",
                None,
            )

            await update.message.reply_text(
                f"✅ مسابقه #{cid} ساخته شد "
                f"و در صف مسابقات قرار گرفت.\n\n"
                f"🎁 {wiz['title']}\n"
                f"🎁 جایزه: {wiz['prize']}\n"
                f"🔢 ظرفیت: {wiz['capacity']:,}",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "🎁 مدیریت مسابقات",
                                callback_data="admin_campaigns",
                            )
                        ]
                    ]
                ),
            )

            return

    # =========================
    # ADMIN PAYMENT INPUT
    # =========================

    if (
        update.effective_user.id in ADMIN_IDS
        and context.user_data.get(
            "admin_input"
        )
    ):

        field = context.user_data.pop(
            "admin_input"
        )

        if field == "card_number":

            digits = "".join(
                ch
                for ch in text
                if ch.isdigit()
            )

            if len(digits) != 16:

                context.user_data[
                    "admin_input"
                ] = "card_number"

                await update.message.reply_text(
                    "❌ شماره کارت باید دقیقاً "
                    "۱۶ رقم باشد. دوباره وارد کن."
                )

                return

            set_setting(
                "card_number",
                digits,
            )

            await update.message.reply_text(
                "✅ شماره کارت ذخیره شد.",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "💳 بازگشت به تنظیمات پرداخت",
                                callback_data="admin_payment",
                            )
                        ]
                    ]
                ),
            )

            return

        if field == "card_holder":

            if not text:

                await update.message.reply_text(
                    "❌ نام صاحب کارت نمی‌تواند خالی باشد."
                )

                return

            set_setting(
                "card_holder",
                text[:100],
            )

            await update.message.reply_text(
                "✅ نام صاحب کارت ذخیره شد.",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "💳 بازگشت به تنظیمات پرداخت",
                                callback_data="admin_payment",
                            )
                        ]
                    ]
                ),
            )

            return

        if field == "payment_note":

            set_setting(
                "payment_note",
                text[:500],
            )

            await update.message.reply_text(
                "✅ توضیح پرداخت ذخیره شد.",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "💳 بازگشت به تنظیمات پرداخت",
                                callback_data="admin_payment",
                            )
                        ]
                    ]
                ),
            )

            return

    # =========================
    # SUPPORT MESSAGE
    # =========================

    ensure_user(
        update.effective_user
    )

    if text:

        conn = db()

        try:

            conn.execute(
                """
                INSERT INTO support_tickets(
                    telegram_id,
                    message,
                    created_at
                )
                VALUES(?,?,?)
                """,
                (
                    update.effective_user.id,
                    text,
                    now_iso(),
                ),
            )

            conn.commit()

        finally:
            conn.close()

        await update.message.reply_text(
            "پیامت دریافت شد. "
            "برای درخواست‌های پشتیبانی، "
            "از بخش 🆘 پشتیبانی استفاده کن."
        )


# =========================
# AUTO POSTS / JOBS
# =========================

async def send_auto_post(bot):

    if not AUTO_POST_ENABLED:
        return False

    target = int(
        get_setting(
            "activation_target",
            ACTIVATION_TARGET,
        )
    )

    ig = int(
        get_setting(
            "instagram_followers",
            0,
        )
    )

    yt = int(
        get_setting(
            "youtube_followers",
            0,
        )
    )

    tg = int(
        get_setting(
            "telegram_followers",
            0,
        )
    )

    text = (
        "🎉 <b>محفل خوش‌شانس‌ها</b>\n\n"
        "🎁 مسابقات و جوایز آینده محفل "
        "برای اعضای واقعی جامعه محفل است.\n\n"
        "👥 دوستانت را دعوت کن تا شانس‌های بیشتری بگیری.\n"
        "📸 اینستاگرام را دنبال کن.\n"
        "▶️ یوتیوب را دنبال کن.\n"
        "📢 عضو کانال تلگرام باش.\n\n"
        f"🎯 هدف فعال‌شدن قرعه‌کشی شبکه: "
        f"{target:,}\n"
        f"📊 وضعیت فعلی: "
        f"IG {ig:,} | YT {yt:,} | TG {tg:,}\n\n"
        "⚠️ رعایت شرایط اعلام‌شده "
        "برای دریافت جایزه الزامی است.\n"
        "🤝 اسپانسرها برای همکاری "
        "می‌توانند با پشتیبانی تماس بگیرند."
    )

    try:

        await bot.send_message(
            TELEGRAM_CHANNEL,
            text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )

        set_setting(
            "last_auto_post",
            now_iso(),
        )

        return True

    except Exception as exc:

        logger.error(
            "Auto post failed: %s",
            exc,
        )

        return False


async def auto_post_job(context: ContextTypes.DEFAULT_TYPE):
    await send_auto_post(
        context.bot
    )


async def youtube_job(context: ContextTypes.DEFAULT_TYPE):

    if not YOUTUBE_API_KEY or not YOUTUBE_CHANNEL_ID:
        return

    try:

        count = await asyncio.to_thread(
            youtube_followers_from_api
        )

        set_setting(
            "youtube_followers",
            count,
        )

        set_setting(
            "last_youtube_check",
            now_iso(),
        )

        network_is_active()

    except Exception as exc:

        logger.warning(
            "YouTube background update failed: %s",
            exc,
        )


# =========================
# RENDER HEALTH SERVER
# =========================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):

        path = urlparse(
            self.path
        ).path

        if path in (
            "/",
            "/health",
            "/healthz",
        ):

            body = b"MahfelShansBot OK"

            self.send_response(
                200
            )

            self.send_header(
                "Content-Type",
                "text/plain; charset=utf-8",
            )

            self.send_header(
                "Content-Length",
                str(len(body)),
            )

            self.end_headers()

            self.wfile.write(
                body
            )

            return

        self.send_response(
            404
        )

        self.end_headers()

    def log_message(
        self,
        format,
        *args
    ):
        return


def start_health_server():

    server = ThreadingHTTPServer(
        (
            "0.0.0.0",
            PORT,
        ),
        HealthHandler,
    )

    thread = Thread(
        target=server.serve_forever,
        daemon=True,
    )

    thread.start()

    logger.info(
        "Health server listening on 0.0.0.0:%s",
        PORT,
    )

    return server


# =========================
# APP
# =========================

async def post_init(application: Application):

    init_db()

    commands = [
        (
            "start",
            "شروع",
        ),
        (
            "myid",
            "نمایش شناسه تلگرام",
        ),
        (
            "admin",
            "پنل مدیریت",
        ),
        (
            "status",
            "وضعیت شبکه",
        ),
        (
            "users",
            "آمار کاربران",
        ),
        (
            "campaigns",
            "مسابقات",
        ),
        (
            "postnow",
            "ارسال پست کانال",
        ),
    ]

    try:

        await application.bot.set_my_commands(
            commands
        )

    except Exception as exc:

        logger.warning(
            "Could not set commands: %s",
            exc,
        )

    if application.job_queue is not None:

        if AUTO_POST_ENABLED:

            application.job_queue.run_repeating(
                auto_post_job,
                interval=AUTO_POST_HOURS * 3600,
                first=30,
                name="auto-post",
            )

        if (
            YOUTUBE_API_KEY
            and YOUTUBE_CHANNEL_ID
        ):

            application.job_queue.run_repeating(
                youtube_job,
                interval=3600,
                first=60,
                name="youtube-update",
            )


def build_application():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN در Environment Variables تنظیم نشده است"
        )

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    application.add_handler(
        CommandHandler(
            "myid",
            myid,
        )
    )

    application.add_handler(
        CommandHandler(
            "admin",
            admin,
        )
    )

    application.add_handler(
        CommandHandler(
            "adminhelp",
            adminhelp,
        )
    )

    application.add_handler(
        CommandHandler(
            "status",
            status,
        )
    )

    application.add_handler(
        CommandHandler(
            "users",
            users_cmd,
        )
    )

    application.add_handler(
        CommandHandler(
            "igfollowers",
            set_ig_followers,
        )
    )

    application.add_handler(
        CommandHandler(
            "tgfollowers",
            set_tg_followers,
        )
    )

    application.add_handler(
        CommandHandler(
            "ytfollowers",
            set_yt_followers,
        )
    )

    application.add_handler(
        CommandHandler(
            "createcampaign",
            create_campaign,
        )
    )

    application.add_handler(
        CommandHandler(
            "campaigns",
            campaigns_cmd,
        )
    )

    application.add_handler(
        CommandHandler(
            "draw",
            draw_cmd,
        )
    )

    application.add_handler(
        CommandHandler(
            "postnow",
            postnow,
        )
    )

    application.add_handler(
        CommandHandler(
            "paymentsettings",
            admin_payment_command,
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
            text_message,
        )
    )

    return application


def main():

    init_db()

    start_health_server()

    application = build_application()

    logger.info(
        "MahfelShansBot starting with polling..."
    )

    application.run_polling(
        drop_pending_updates=False,
        allowed_updates=Update.ALL_TYPES,
    )


if __name__ == "__main__":
    main()
