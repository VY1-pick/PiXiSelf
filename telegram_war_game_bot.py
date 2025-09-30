# -----------------------------------------------------------------------------
# |                      World War Telegram Mini-Game Bot                     |
# |                  Refactored & Optimized for aiogram v3.7.x                |
# |                                By Amiro                                   |
# -----------------------------------------------------------------------------

import os
import logging
import asyncpg
import asyncio
from aiohttp import web

from aiogram import Bot, Dispatcher, Router, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, Regexp
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
router = Router()

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
# ساخت منوی شیشه‌ای
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
# حذف پیام بعد از 15 ثانیه
# -----------------------------
async def delete_after_delay(chat_id: int, message_id: int, delay: int = 15):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass  # اگر پیام حذف نشد، نادیده بگیریم

async def send_and_auto_delete(chat_id: int, text: str, **kwargs):
    msg = await bot.send_message(chat_id, text, **kwargs)
    asyncio.create_task(delete_after_delay(chat_id, msg.message_id))
    return msg

# -----------------------------
# هندلر /start
# -----------------------------
@router.message(Command("start"))
async def start_cmd(message: Message):
    asyncio.create_task(delete_after_delay(message.chat.id, message.message_id))

    if message.chat.type in ["group", "supergroup"]:
        chat_member = await bot.get_chat_member(message.chat.id, bot.id)
        if chat_member.status != "administrator":
            msg = await message.reply("سرباز! من رو ادمین کن تا بتونم فرماندهی کنم!")
            asyncio.create_task(delete_after_delay(message.chat.id, msg.message_id))
            return
        msg = await message.reply(
            f"🪖 سرباز {message.from_user.full_name}،آماده باش برای ورود فرماندهی!"
        )
        asyncio.create_task(delete_after_delay(message.chat.id, msg.message_id))
    else:
        add_button = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="➕ افزودن به گروه", url=f"https://t.me/{BOT_USERNAME}?startgroup=true")]
            ]
        )
        fullname = message.from_user.full_name
        text = (
            f"سرباز {hbold(fullname)}\n"
            f"به میدان جنگ خوش آمدی... البته خوش آمد که چه عرض کنم، "
            f"فعلاً خیلی دست‌وپا چلفتی هستی!\n\n"
            f"برای شروع، این اسباب‌بازی را به گروه اضافه کن تا ببینیم چقدر توان داری."
            f"\n\nاز دستور {hbold('/panel')} استفاده کن تا به پنل فرماندهی دسترسی داشته باشی."
        )
        msg = await message.answer(text, reply_markup=add_button)
        asyncio.create_task(delete_after_delay(message.chat.id, msg.message_id))

# -----------------------------
# وقتی نقش بات تغییر می‌کند
# -----------------------------
@router.my_chat_member()
async def on_bot_role_change(event: ChatMemberUpdated):
    new_status = event.new_chat_member.status
    if new_status == "administrator":
        msg1 = await bot.send_message(
            event.chat.id,
            "🪖 فرمانده در جایگاه حقیقی خود قرار گرفت، سربازان آماده دریافت دستورات باشین!"
        )
        asyncio.create_task(delete_after_delay(event.chat.id, msg1.message_id))

        msg2 = await bot.send_message(
            event.chat.id,
            "📜 کاری که میخوای انجام بدی رو انتخاب کن:",
            reply_markup=game_main_menu()
        )
        asyncio.create_task(delete_after_delay(event.chat.id, msg2.message_id))
    elif new_status == "member":
        msg = await bot.send_message(
            event.chat.id,
            "⚠ سربازان! وقتی در خواب بودم جایگاه من رو دزدیدن، من در این جایگاه نمیتوانم دستوری صادر کنم."
        )
        asyncio.create_task(delete_after_delay(event.chat.id, msg.message_id))

# -----------------------------
# هندلر /panel
# -----------------------------
@router.message(Command("panel"))
async def cmd_panel(message: Message):
    asyncio.create_task(delete_after_delay(message.chat.id, message.message_id))
    
    if message.chat.type == "private":
        text = "🎯 پنل میدیریت کشور فقط در چت خصوصی در دسترس هست!"
        msg = await message.answer(text)
        asyncio.create_task(delete_after_delay(message.chat.id, msg.message_id))

    conn = await get_db()
    rows = await conn.fetch("""
        SELECT g.title, up.money, up.oil, up.level
        FROM user_profiles up
        JOIN groups g ON g.group_key = up.group_key
        WHERE up.user_id = $1
    """, message.from_user.id)
    await conn.close()

    if not rows:
        msg = await message.answer("📭 شما در هیچ گروهی عضو نیستید.")
        asyncio.create_task(delete_after_delay(message.chat.id, msg.message_id))
        return

    text = "\n".join([
        f"{hbold(row['title'])} | 💰 {row['money']} | 🛢 {row['oil']} | 📈 Level {row['level']}"
        for row in rows
    ])
    msg = await message.answer(text)
    asyncio.create_task(delete_after_delay(message.chat.id, msg.message_id))

# -----------------------------
# نمایش موجودی بعد از ارسال سرمایه در گروه
# -----------------------------
@router.message(Regexp(r"سرمایه"))
async def check_investment_pattern(message: Message):
    asyncio.create_task(delete_after_delay(message.chat.id, message.message_id))

    # دیتابیس
    conn = await get_db()
    row = await conn.fetchrow("""
        SELECT money, oil, level
        FROM user_profiles
        JOIN groups g ON g.group_key = user_profiles.group_key
        WHERE user_id = $1 AND g.chat_id = $2
    """, message.from_user.id, message.chat.id)
    await conn.close()

    if row:
        text = f"💰 پول: {row['money']} | 🛢 نفت: {row['oil']} | 📈 Level {row['level']}"
    else:
        text = "📭 شما هیچ موجودی در این گروه ندارید."

    msg = await message.answer(text)
    asyncio.create_task(delete_after_delay(message.chat.id, msg.message_id))

# -----------------------------
# هندلر منوی شیشه‌ای (callback)
# -----------------------------
@router.callback_query()
async def process_menu_selection(callback: types.CallbackQuery):
    if callback.data == "view_resources":
        conn = await get_db()
        row = await conn.fetchrow("""
            SELECT money, oil, level
            FROM user_profiles
            JOIN groups g ON g.group_key = user_profiles.group_key
            WHERE user_id = $1 AND g.chat_id = $2
        """, callback.from_user.id, callback.message.chat.id)
        await conn.close()

        if row:
            msg = await callback.message.answer(
                f"💰 پول: {row['money']} | 🛢 نفت: {row['oil']} | 📈 Level {row['level']}"
            )
            asyncio.create_task(delete_after_delay(callback.message.chat.id, msg.message_id))
        else:
            msg = await callback.message.answer("📭 موجودی یافت نشد.")
            asyncio.create_task(delete_after_delay(callback.message.chat.id, msg.message_id))

    elif callback.data == "attack_enemy":
        msg = await callback.message.answer("⚔ عملیات حمله شروع شد!")
        asyncio.create_task(delete_after_delay(callback.message.chat.id, msg.message_id))
    elif callback.data == "upgrade_building":
        msg = await callback.message.answer("🏗 ساختمان در حال ارتقاء است...")
        asyncio.create_task(delete_after_delay(callback.message.chat.id, msg.message_id))
    elif callback.data == "defense_up":
        msg = await callback.message.answer("🛡 دفاع نیروها تقویت شد!")
        asyncio.create_task(delete_after_delay(callback.message.chat.id, msg.message_id))
    elif callback.data == "level_up":
        msg = await callback.message.answer("📈 سطح شما افزایش یافت!")
        asyncio.create_task(delete_after_delay(callback.message.chat.id, msg.message_id))
    elif callback.data == "buy_resources":
        msg = await callback.message.answer("🪙 خرید منابع انجام شد!")
        asyncio.create_task(delete_after_delay(callback.message.chat.id, msg.message_id))

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
    dp.include_router(router)
    app = web.Application()
    app.router.add_post(WEBHOOK_PATH, handle_webhook)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_shutdown)
    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()


