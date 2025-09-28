# -----------------------------------------------------------------------------
# |                      World War Telegram Mini-Game Bot                     |
# |                  Refactored & Optimized for aiogram v3.7.x                |
# |                                By Amiro                                   |
# -----------------------------------------------------------------------------

import os
import logging
import psycopg2
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ChatMemberUpdated
from aiohttp import web

# -----------------------------
# تنظیمات پایه
# -----------------------------
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
BOT_USERNAME = os.getenv("BOT_USERNAME")

WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"https://{os.getenv('RAILWAY_PROJECT_URL')}{WEBHOOK_PATH}"
PORT = int(os.getenv("PORT", 8080))

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher()

# -----------------------------
# اتصال به دیتابیس Postgres
# -----------------------------
try:
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    logging.info("✅ اتصال به دیتابیس برقرار شد.")
except Exception as e:
    logging.error(f"❌ خطا در اتصال به دیتابیس: {e}")

# -----------------------------
# هندلر /start
# -----------------------------
@dp.message(Command("start"))
async def start_cmd(message: Message):
    if message.chat.type in ["group", "supergroup"]:
        # بررسی ادمین بودن ربات در گروه
        chat_member = await bot.get_chat_member(message.chat.id, bot.id)
        if not chat_member.is_chat_admin():
            await message.reply("سرباز! من رو ادمین کن تا بتونم فرماندهی کنم!")
            return

        await message.reply(
            f"🪖 سرباز {message.from_user.full_name}، آماده باش برای فرماندهی!",
        )
    else:
        # حالت خصوصی - دکمه افزودن به گروه
        add_button = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="➕ افزودن به گروه", url=f"https://t.me/{BOT_USERNAME}?startgroup=true")]
            ]
        )
        await message.answer(
            "سرباز! این میدان جنگ گروهیه، من رو به گروه اضافه کن تا شروع کنیم!",
            reply_markup=add_button
        )

# -----------------------------
# زمانی که نقش بات تغییر می‌کند
# -----------------------------
@dp.my_chat_member()
async def on_bot_role_change(event: ChatMemberUpdated):
    # اگر بات ادمین شد
    new_status = event.new_chat_member.status
    if new_status == "administrator":
        await bot.send_message(
            event.chat.id,
            "🪖 سرباز آماده دریافت دستورات باش!"
        )
    elif new_status == "member":  # یعنی از ادمین به عضو معمولی شد
        await bot.send_message(
            event.chat.id,
            "⚠ سرباز! فرماندهی ازت گرفته شد، دیگه نمی‌تونم دستور صادر کنم."
        )
        
# -----------------------------
# هندلر /panel در PV
# -----------------------------
@dp.message(Command("panel"))
async def panel_cmd(message: Message):
    if message.chat.type == "private":
        await message.answer("🎯 این پنل هنوز آماده نیست، اما به زودی می‌تونی اوضاع کشورت رو دید بزنی!")
    else:
        await message.reply("سرباز! پنل رو فقط در پیام خصوصی می‌تونی ببینی.")

# -----------------------------
# راه‌اندازی Webhook
# -----------------------------
async def on_startup(app: web.Application):
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
        update = await request.json()
        await dp.feed_webhook_update(bot, update)
    except Exception as e:
        logging.error(f"❌ خطا در پردازش وبهوک: {e}")
    return web.Response()

# -----------------------------
# اجرای برنامه WebApp
# -----------------------------
def main():
    app = web.Application()
    app.router.add_post(WEBHOOK_PATH, handle_webhook)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_shutdown)

    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()





