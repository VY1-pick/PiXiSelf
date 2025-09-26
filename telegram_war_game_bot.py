# -----------------------------------------------------------------------------
# |                      World War Telegram Mini-Game Bot                     |
# |                  Refactored & Optimized for aiogram v3.7.x                |
# |                                By Amiro                                   |
# -----------------------------------------------------------------------------

# telegram_war_game_bot.py
import logging
import os
import asyncio
import psycopg2
from psycopg2.extras import DictCursor
from aiogram import Bot, Dispatcher
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.utils.markdown import hbold

# ================== لاگینگ ==================
logging.basicConfig(level=logging.INFO)

# ================== متغیرهای محیطی (Railway) ==================
TOKEN = os.getenv("BOT_TOKEN")       # BOT token در پنل Railway
BOT_USERNAME = os.getenv("BOT_USERNAME")  # مثلا WarCommanderBot
DATABASE_URL = os.getenv("DATABASE_URL")  # لینک کامل Postgres در Railway

if not TOKEN or not BOT_USERNAME or not DATABASE_URL:
    raise RuntimeError("⚠ توکن یا اطلاعات پایگاه داده در Railway ثبت نشده!")

# ================== اتصال پایگاه داده ==================
def get_db_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=DictCursor)

# ================== ساخت بات و دیسپچر ==================
bot = Bot(token=TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()

# ================== هندلر استارت ==================
@dp.message(Command("start"))
async def cmd_start(message: Message):
    fullname = message.from_user.full_name
    text = (
        f"سرباز {hbold(fullname)},\n"
        f"به میدان جنگ خوش آمدی... البته خوش‌آمد که چه عرض کنم، "
        f"فعلاً خیلی دست‌وپا چلفتی هستی!\n\n"
        f"برای شروع، این اسباب‌بازی را به گروه اضافه کن تا ببینیم چقدر توان داری."
        f"\n\nاز دستور {hbold('/panel')} در چت خصوصی استفاده کن تا به پنل دسترسی داشته باشی."
    )

    add_group_button = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="➕ افزودن به گروه",
                url=f"https://t.me/{BOT_USERNAME}?startgroup=true"
            )
        ]]
    )

    await message.answer(text, reply_markup=add_group_button)

# ================== اجرای بات ==================
async def main():
    logging.info("🚀 فرمانده: عملیات شروع شد...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
