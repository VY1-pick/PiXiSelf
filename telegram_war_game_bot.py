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
from aiogram.client.default import DefaultBotProperties
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.utils.markdown import hbold

# ================== لاگینگ ==================
logging.basicConfig(level=logging.INFO)

# ================== متغیرهای محیطی (Railway) ==================
TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME")
DATABASE_URL = os.getenv("DATABASE_URL")

if not TOKEN or not BOT_USERNAME or not DATABASE_URL:
    raise RuntimeError("⚠ فرمانده: توکن یا اطلاعات پایگاه داده در Railway ثبت نشده!")

# ================== اتصال پایگاه داده ==================
def get_db_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=DictCursor)

# ================== ساخت بات و دیسپچر ==================
bot = Bot(
    token=TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

# ================== هندلر ها ==================
@dp.message(Command("start"))
async def cmd_start(message: Message):
    # اگر محیط گروه است
    if message.chat.type in ("group", "supergroup"):
        bot_member = await bot.get_chat_member(message.chat.id, bot.id)
        
        if bot_member.status in ("administrator", "creator"):
            await message.reply(
                f"سرباز {hbold(message.from_user.full_name)},\n"
                f"فرمانده حاضر و آمادهٔ عملیات است! آماده باشید برای نبرد... 🔥"
            )
        else:
            await message.reply(
                f"سرباز {hbold(message.from_user.full_name)},\n"
                f"ها! فرمانده رو کردین سرباز صفر؟! 🚫\n"
                f"برای فرماندهی باید من رو فوراً به ادمین ارتقاء بدین."
            )
        return  # چون پیام افزودن به گروه اینجا لازم نیست
    
    # اگر محیط خصوصی یا غیرگروه است
    fullname = message.from_user.full_name
    text = (
        f"سرباز {hbold(fullname)}\n"
        f"به میدان جنگ خوش آمدی... البته خوش آمد که چه عرض کنم، "
        f"فعلاً خیلی دست‌وپا چلفتی هستی!\n\n"
        f"برای شروع، این اسباب‌بازی را به گروه اضافه کن تا ببینیم چقدر توان داری."
        f"\n\nاز دستور {hbold('/panel')} استفاده کن تا به پنل فرماندهی دسترسی داشته باشی."
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

@dp.message(Command("panel"))
async def cmd_panel(message: Message):
    # تشخیص محیط
    if message.chat.type in ("group", "supergroup"):
        # اگر توی گروه زد، هدایتش به pv
        panel_button = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(
                    text="📋 ورود به پنل فرماندهی",
                    url=f"https://t.me/{BOT_USERNAME}?start=panel"
                )
            ]]
        )
        await message.reply(
            "سرباز! پنل فرماندهی فقط در چت خصوصی باز می‌شود.\n"
            "روی دکمه زیر بزن و بیا تا درجه‌ات را بررسی کنم.",
            reply_markup=panel_button
        )
    else:
        # محیط خصوصی: نمایش پیغام پنل
        panel_button = InlineKeyboardMarkup(
            inline_keyboard=[[
                InlineKeyboardButton(
                    text="📋 شروع پنل فرماندهی",
                    url=f"https://t.me/{BOT_USERNAME}?start=panel"  # بعداً آدرس واقعی یا بخش داخلی رو میزاری
                )
            ]]
        )
        await message.answer(
            "به پنل فرماندهی خوش آمدی...\n"
            "اینجا جاییست که تصمیمات بزرگ گرفته می‌شود.",
            reply_markup=panel_button
        )

# ================== اجرای بات ==================
async def main():
    logging.info("🚀 فرمانده: عملیات شروع شد...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())




