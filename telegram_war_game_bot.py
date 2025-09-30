# -----------------------------------------------------------------------------
# |                      World War Telegram Mini-Game Bot                     |
# |                   Optimized for aiogram v3.x without Router               |
# -----------------------------------------------------------------------------

import os
import logging
import asyncpg
import asyncio
from aiohttp import web

from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ChatMemberUpdated,
    Update
)
from aiogram.utils.markdown import hbold

# -----------------------------
# تنظیمات پایه
# -----------------------------
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
BOT_USERNAME = os.getenv("BOT_USERNAME")
RAILWAY_PROJECT_URL = os.getenv("RAILWAY_PROJECT_URL")
PORT = int(os.getenv("PORT", 8080))

WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"https://{RAILWAY_PROJECT_URL}{WEBHOOK_PATH}"

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

# -----------------------------
# کوئری‌های ایجاد جدول‌ها
# -----------------------------
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

# -----------------------------
# اتصال و ساخت دیتابیس
# -----------------------------
async def get_db():
    return await asyncpg.connect(DATABASE_URL)

async def init_db():
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute(CREATE_GROUPS_TABLE)
    await conn.execute(CREATE_USER_PROFILES_TABLE)
    await conn.close()

# -----------------------------
# حذف پیام بعد از 20 ثانیه فقط در گروه‌ها
# -----------------------------
async def delete_after_delay(chat_type: str, chat_id: int, message_id: int, delay: int = 20):
    if chat_type in ["group", "supergroup"]:
        await asyncio.sleep(delay)
        try:
            await bot.delete_message(chat_id, message_id)
        except Exception:
            pass

# -----------------------------
# منوی شیشه‌ای
# -----------------------------
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

# -----------------------------
# هندلر /start
# -----------------------------
@dp.message(Command("start"))
async def start_cmd(message: Message):
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
        fullname = message.from_user.full_name
        text = (
            f"سرباز {hbold(fullname)}\n"
            f"به میدان جنگ خوش آمدی.\n\n"
            f"برای شروع، این ربات را به گروه اضافه کن.\n"
            f"از دستور {hbold('/panel')} استفاده کن تا به پنل فرماندهی دسترسی داشته باشی."
        )
        await message.answer(text, reply_markup=add_button)

# -----------------------------
# هندلر تغییر نقش بات
# -----------------------------
@dp.my_chat_member()
async def on_bot_role_change(event: ChatMemberUpdated):
    # حذف پیام ادمین شدم
    pass

# -----------------------------
# هندلر شروع جنگ (متن فارسی)
# -----------------------------
@dp.message(lambda m: m.text and m.text.strip() == "شروع جنگ")
async def start_war(message: Message):
    if message.chat.type not in ["group", "supergroup"]:
        await message.answer("⚠ این دستور باید در گروه اجرا شود، نه در چت خصوصی!")
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

    msg = await message.answer("🪖 آماده دریافت دستورات باشین!")
    asyncio.create_task(delete_after_delay(message.chat.type, message.chat.id, msg.message_id))

# -----------------------------
# هندلر /panel
# -----------------------------
@dp.message(Command("panel"))
async def cmd_panel(message: Message):
    if message.chat.type in ["group", "supergroup"]:
        asyncio.create_task(delete_after_delay(message.chat.type, message.chat.id, message.message_id))
        msg = await message.answer("⚠ این دستور فقط در چت خصوصی قابل استفاده است. لطفاً به من پیام بده!")
        asyncio.create_task(delete_after_delay(message.chat.type, message.chat.id, msg.message_id))
        return

    elif message.chat.type == "private":
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
            f"{hbold(row['title'])} | 💰 {row['money']} | 🛢 {row['oil']} | 📈 Level {row['level']}"
            for row in rows
        ])
        await message.answer(text)

# -----------------------------
# هندلر نمایش موجودی در گروه
# -----------------------------
@dp.message(lambda m: m.text and "سرمایه" in m.text)
async def check_investment_pattern(message: Message):
    if message.chat.type in ["group", "supergroup"]:
        asyncio.create_task(delete_after_delay(message.chat.type, message.chat.id, message.message_id))

    conn = await get_db()
    row = await conn.fetchrow("""
        SELECT money, oil, level
        FROM user_profiles
        JOIN groups g ON g.group_key = user_profiles.group_key
        WHERE user_id = $1 AND g.chat_id = $2
    """, message.from_user.id, message.chat.id)
    await conn.close()

    text = (
        f"💰 پول: {row['money']} | 🛢 نفت: {row['oil']} | 📈 Level {row['level']}"
        if row else "📭 شما هیچ موجودی در این گروه ندارید."
    )

    msg = await message.answer(text)
    if message.chat.type in ["group", "supergroup"]:
        asyncio.create_task(delete_after_delay(message.chat.type, message.chat.id, msg.message_id))

# -----------------------------
# هندلر منوی شیشه‌ای
# -----------------------------
@dp.callback_query()
async def process_menu_selection(callback: types.CallbackQuery):
    chat_type = callback.message.chat.type
    data = callback.data

    if data == "view_resources":
        conn = await get_db()
        row = await conn.fetchrow("""
            SELECT money, oil, level
            FROM user_profiles
            JOIN groups g ON g.group_key = user_profiles.group_key
            WHERE user_id = $1 AND g.chat_id = $2
        """, callback.from_user.id, callback.message.chat.id)
        await conn.close()

        msg_text = (f"💰 پول: {row['money']} | 🛢 نفت: {row['oil']} | 📈 Level {row['level']}"
                    if row else "📭 موجودی یافت نشد.")
        msg = await callback.message.answer(msg_text)

    elif data == "attack_enemy":
        msg = await callback.message.answer("⚔ عملیات حمله شروع شد!")
    elif data == "upgrade_building":
        msg = await callback.message.answer("🏗 ساختمان در حال ارتقاء است...")
    elif data == "defense_up":
        msg = await callback.message.answer("🛡 دفاع نیروها تقویت شد!")
    elif data == "level_up":
        msg = await callback.message.answer("📈 سطح شما افزایش یافت!")
    elif data == "buy_resources":
        msg = await callback.message.answer("🪙 خرید منابع انجام شد!")
    else:
        msg = None

    if msg and chat_type in ["group", "supergroup"]:
        asyncio.create_task(delete_after_delay(chat_type, callback.message.chat.id, msg.message_id))

    await callback.answer()

# -----------------------------
# راه‌اندازی Webhook
# -----------------------------
async def on_startup(app: web.Application):
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(WEBHOOK_URL)

async def on_shutdown(app: web.Application):
    await bot.delete_webhook()
    await bot.session.close()

async def handle_webhook(request: web.Request):
    data = await request.json()
    update = Update.model_validate(data)
    await dp.feed_webhook_update(bot, update)
    return web.Response()

def main():
    app = web.Application()
    app.router.add_post(WEBHOOK_PATH, handle_webhook)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_shutdown)
    web.run_app(app, host="0.0.0.0", port=PORT)
    print("Bot Is Running! Update? Coming Soon")

if __name__ == "__main__":
    main()
