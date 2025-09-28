# -----------------------------------------------------------------------------
# |                      World War Telegram Mini-Game Bot                     |
# |                  Refactored & Optimized for aiogram v3.7.x                |
# |                                By Amiro                                   |
# -----------------------------------------------------------------------------

import os
import logging
import asyncpg
from aiohttp import web
from aiogram import Bot, Dispatcher, Router, types
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

logging.info(f"BOT_TOKEN: {BOT_TOKEN}")
logging.info(f"RAILWAY_PROJECT_URL: {RAILWAY_PROJECT_URL}")
logging.info(f"PORT: {PORT}")
logging.info(f"WEBHOOK_URL: {WEBHOOK_URL}")

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
    logging.info("✅ دیتابیس و جدول‌ها ساخته شدند یا وجود داشتند.")

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
# هندلر /start
# -----------------------------
@router.message(Command("start"))
async def start_cmd(message: Message):
    if message.chat.type in ["group", "supergroup"]:
        chat_member = await bot.get_chat_member(message.chat.id, bot.id)
        if chat_member.status != "administrator":
            await message.reply("سرباز! من رو ادمین کن تا بتونم فرماندهی کنم!")
            return
        await message.reply(
            f"🪖 سرباز {message.from_user.full_name}،آماده باش برای ورود فرماندهی!",
        )
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
        await message.answer(
            text,
            reply_markup=add_button
        )

# -----------------------------
# وقتی نقش بات تغییر می‌کند
# -----------------------------
@router.my_chat_member()
async def on_bot_role_change(event: ChatMemberUpdated):
    new_status = event.new_chat_member.status
    if new_status == "administrator":
        await bot.send_message(
            event.chat.id,
            "🪖 فرمانده در جایگاه حقیقی خود قرار گرفت، سربازان آماده دریافت دستورات باشین!"
        )
        await bot.send_message(
            event.chat.id,
            "📜 کاری که میخوای انجام بدی رو انتخاب کن:",
            reply_markup=game_main_menu()
        )
    elif new_status == "member":
        await bot.send_message(
            event.chat.id,
            "⚠ سربازان! وقتی در خواب بودم جایگاه من رو دزدیدن، من در این جایگاه نمیتوانم دستوری صادر کنم."
        )

# -----------------------------
# هندلر /panel
# -----------------------------
@router.message(Command("panel"))
async def cmd_panel(message: Message):
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
# هندلر منوی شیشه‌ای (callback)
# -----------------------------
@router.callback_query()
async def process_menu_selection(callback: types.CallbackQuery):
    if callback.data == "view_resources":
        await callback.message.answer("💰 منابع شما: پول = 0 ، نفت = 0")
    elif callback.data == "attack_enemy":
        await callback.message.answer("⚔ عملیات حمله شروع شد!")
    elif callback.data == "upgrade_building":
        await callback.message.answer("🏗 ساختمان در حال ارتقاء است...")
    elif callback.data == "defense_up":
        await callback.message.answer("🛡 دفاع نیروها تقویت شد!")
    elif callback.data == "level_up":
        await callback.message.answer("📈 سطح شما افزایش یافت!")
    elif callback.data == "buy_resources":
        await callback.message.answer("🪙 خرید منابع انجام شد!")
    await callback.answer()

# -----------------------------
# راه‌اندازی Webhook
# -----------------------------
async def on_startup(app: web.Application):
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(WEBHOOK_URL)
    logging.info(f"✅ Webhook فعال شد: {WEBHOOK_URL}")

async def on_shutdown(app: web.Application):
    await bot.delete_webhook()
    await bot.session.close()
    logging.info("🛑 Webhook خاموش شد.")

# -----------------------------
# دریافت آپدیت‌ها از Webhook
# -----------------------------
async def handle_webhook(request: web.Request):
    try:
        data = await request.json()
        update = Update.model_validate(data)
        await dp.feed_webhook_update(bot, update)
    except Exception as e:
        logging.error(f"❌ خطا در پردازش وبهوک: {e}")
    return web.Response()

# -----------------------------
# اجرای برنامه WebApp
# -----------------------------
def main():
    dp.include_router(router)

    app = web.Application()
    app.router.add_post(WEBHOOK_PATH, handle_webhook)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_shutdown)

    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
