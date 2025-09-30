# -----------------------------------------------------------------------------
# |                      World War Telegram Mini-Game Bot                     |
# |           Aiogram v3.x | Dispatcher Direct | Modern Logging System        |
# -----------------------------------------------------------------------------

import os
import logging
import asyncio
import asyncpg
import json
from datetime import datetime, UTC
from aiohttp import web
from logging.handlers import RotatingFileHandler
from functools import wraps

from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    ChatMemberUpdated, Update
)
from aiogram.utils.markdown import hbold

# ==============================
# Environment Variables
# ==============================
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
BOT_USERNAME = os.getenv("BOT_USERNAME")
RAILWAY_PROJECT_URL = os.getenv("RAILWAY_PROJECT_URL")
PORT = int(os.getenv("PORT", 8080))

WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"https://{RAILWAY_PROJECT_URL}{WEBHOOK_PATH}"

# ==============================
# Bot & Dispatcher
# ==============================
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

# ==============================
# Modern Logging
# ==============================
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "time": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "module": record.module,
            "funcName": record.funcName,
            "message": record.getMessage()
        }
        if record.exc_info:
            log_record["error"] = self.formatException(record.exc_info)
        return json.dumps(log_record, ensure_ascii=False)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
console_formatter = logging.Formatter(
    "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
console_handler.setFormatter(console_formatter)

file_handler = RotatingFileHandler(
    os.path.join(LOG_DIR, "bot.log"),
    maxBytes=5*1024*1024,
    backupCount=5,
    encoding="utf-8"
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(JsonFormatter())

logger = logging.getLogger("WWBot")
logger.setLevel(logging.DEBUG)
logger.addHandler(console_handler)
logger.addHandler(file_handler)

# ==============================
# Exception Logging Decorator
# ==============================
def log_exceptions(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception:
            logger.exception(f"Exception in handler: {func.__name__}")
            raise
    return wrapper

# ==============================
# Database Structure
# ==============================
CREATE_GROUPS_TABLE = """
CREATE TABLE IF NOT EXISTS groups (
    id BIGSERIAL PRIMARY KEY,
    group_key TEXT UNIQUE,
    chat_id BIGINT UNIQUE,
    title TEXT
);
"""

CREATE_USER_PROFILES_TABLE = """
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id BIGINT NOT NULL,
    group_key TEXT NOT NULL,
    money INTEGER DEFAULT 0,
    oil INTEGER DEFAULT 0,
    level INTEGER DEFAULT 1,
    PRIMARY KEY (user_id, group_key),
    FOREIGN KEY (group_key) REFERENCES groups(group_key)
);
"""

async def get_db():
    return await asyncpg.connect(DATABASE_URL)

async def init_db():
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute(CREATE_GROUPS_TABLE)
    await conn.execute(CREATE_USER_PROFILES_TABLE)
    await conn.close()
    logger.info("Database initialized successfully.")

# ==============================
# Utility Functions
# ==============================
async def delete_after_delay(chat_type: str, chat_id: int, message_id: int, delay: int = 20):
    if chat_type in ["group", "supergroup"]:
        await asyncio.sleep(delay)
        try:
            await bot.delete_message(chat_id, message_id)
            logger.debug(f"Deleted message {message_id} in chat {chat_id}")
        except Exception as e:
            logger.warning(f"Failed to delete message {message_id} in chat {chat_id}: {e}")

def game_main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💰 وضعیت منابع", callback_data="view_resources"),
            InlineKeyboardButton(text="⚔ حمله به دشمن", callback_data="attack_enemy")
        ],
        [
            InlineKeyboardButton(text="🏗 ارتقاء ساختمان", callback_data="upgrade_building"),
            InlineKeyboardButton(text="🛡 تقویت دفاع", callback_data="defense_up")
        ],
        [
            InlineKeyboardButton(text="📈 ارتقاء سطح", callback_data="level_up"),
            InlineKeyboardButton(text="🪙 خرید منابع", callback_data="buy_resources")
        ]
    ])

# ==============================
# Handlers
# ==============================
@dp.message(Command("start"))
@log_exceptions
async def start_cmd(message: Message, **kwargs):
    logger.info(f"/start from user {message.from_user.id} in {message.chat.type}")
    if message.chat.type in ["group", "supergroup"]:
        asyncio.create_task(delete_after_delay(message.chat.type, message.chat.id, message.message_id))
        chat_member = await bot.get_chat_member(message.chat.id, bot.id)
        if chat_member.status != "administrator":
            msg = await message.reply("سرباز! من رو ادمین کن تا بتونم فرماندهی کنم!")
            asyncio.create_task(delete_after_delay(message.chat.type, message.chat.id, msg.message_id))
            return
        msg = await message.reply(
            f"🪖 سرباز {message.from_user.full_name}، آماده باش برای ورود فرماندهی!"
        )
        asyncio.create_task(delete_after_delay(message.chat.type, message.chat.id, msg.message_id))
    else:
        add_button = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="➕ افزودن به گروه", url=f"https://t.me/{BOT_USERNAME}?startgroup=true")]
            ]
        )
        text = (
            f"سرباز {hbold(message.from_user.full_name)}\n"
            f"به میدان جنگ خوش آمدی.\n"
            f"برای شروع این بات را به گروه اضافه کن.\n"
            f"از دستور {hbold('/panel')} استفاده کن."
        )
        await message.answer(text, reply_markup=add_button)

@dp.message(lambda m: m.text and m.text.lower() == "شروع جنگ")
@log_exceptions
async def start_war(message: Message, **kwargs):
    if message.chat.type not in ["group", "supergroup"]:
        await message.answer("⚠ این دستور فقط در گروه اجرا می‌شود.")
        return
    asyncio.create_task(delete_after_delay(message.chat.type, message.chat.id, message.message_id))
    chat_member = await bot.get_chat_member(message.chat.id, bot.id)
    if chat_member.status != "administrator":
        msg = await message.answer("سرباز! من رو ادمین کن تا بتونم فرماندهی کنم!")
        asyncio.create_task(delete_after_delay(message.chat.type, message.chat.id, msg.message_id))
        return
    conn = await get_db()
    await conn.execute("""
        INSERT INTO groups (group_key, chat_id, title)
        VALUES (gen_random_uuid()::text, $1, $2)
        ON CONFLICT (chat_id) DO NOTHING;
    """, message.chat.id, message.chat.title)
    await conn.close()
    msg = await message.answer("🪖 گروه ثبت شد و آماده دریافت دستورات است!", reply_markup=game_main_menu())
    asyncio.create_task(delete_after_delay(message.chat.type, message.chat.id, msg.message_id))

@dp.message(Command("panel"))
@log_exceptions
async def cmd_panel(message: Message, **kwargs):
    if message.chat.type in ["group", "supergroup"]:
        asyncio.create_task(delete_after_delay(message.chat.type, message.chat.id, message.message_id))
        msg = await message.answer("⚠ این دستور فقط در چت خصوصی اجرا می‌شود.")
        asyncio.create_task(delete_after_delay(message.chat.type, message.chat.id, msg.message_id))
        return
    conn = await get_db()
    rows = await conn.fetch("""
        SELECT g.title, up.money, up.oil, up.level
        FROM user_profiles up
        JOIN groups g ON g.group_key = up.group_key
        WHERE up.user_id = $1
    """, message.from_user.id)
    await conn.close()
    if not rows:
        await message.answer("📭 شما در هیچ گروهی عضو نیستید.")
        return
    text = "\n".join([
        f"{hbold(r['title'])} | 💰 {r['money']} | 🛢 {r['oil']} | 📈 Level {r['level']}"
        for r in rows
    ])
    await message.answer(text)

@dp.callback_query()
@log_exceptions
async def process_menu_selection(callback: types.CallbackQuery, **kwargs):
    chat_type = callback.message.chat.type
    data = callback.data
    logger.info(f"Callback {data} from user {callback.from_user.id}")
    msg = None
    if data == "view_resources":
        conn = await get_db()
        row = await conn.fetchrow("""
            SELECT money, oil, level
            FROM user_profiles
            JOIN groups g ON g.group_key = user_profiles.group_key
            WHERE user_id = $1 AND g.chat_id = $2
        """, callback.from_user.id, callback.message.chat.id)
        await conn.close()
        msg_text = f"💰 پول: {row['money']} | 🛢 نفت: {row['oil']} | 📈 Level {row['level']}" if row else "📭 موجودی یافت نشد."
        msg = await callback.message.answer(msg_text)
    elif data == "attack_enemy":
        msg = await callback.message.answer("⚔ عملیات حمله آغاز شد!")
    elif data == "upgrade_building":
        msg = await callback.message.answer("🏗 ارتقاء ساختمان شروع شد.")
    elif data == "defense_up":
        msg = await callback.message.answer("🛡 دفاع تقویت شد!")
    elif data == "level_up":
        msg = await callback.message.answer("📈 سطح ارتقاء یافت!")
    elif data == "buy_resources":
        msg = await callback.message.answer("🪙 منابع خریداری شد!")
    if msg and chat_type in ["group", "supergroup"]:
        asyncio.create_task(delete_after_delay(chat_type, callback.message.chat.id, msg.message_id))
    await callback.answer()

# ==============================
# Webhook Setup
# ==============================
async def on_startup(app: web.Application):
    logger.info("Bot starting...")
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(WEBHOOK_URL)
    logger.info(f"Webhook set to {WEBHOOK_URL}")

async def on_shutdown(app: web.Application):
    logger.warning("Bot shutting down...")
    await bot.delete_webhook()
    await bot.session.close()

async def handle_webhook(request: web.Request):
    data = await request.json()
    update = Update.model_validate(data)
    await dp.feed_webhook_update(bot, update)
    return web.Response()

def main():
    use_polling = os.getenv("USE_POLLING", "false").lower() == "true"
    if use_polling:
        asyncio.run(dp.start_polling(bot))
    else:
        app = web.Application()
        app.router.add_post(WEBHOOK_PATH, handle_webhook)
        app.on_startup.append(on_startup)
        app.on_cleanup.append(on_shutdown)
        web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
