import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart

import os

# توکن ربات را از متغیر محیطی در Railway دریافت می‌کنیم
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("لطفاً متغیر محیطی BOT_TOKEN را در Railway تنظیم کنید.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def start_handler(message: types.Message):
    await message.answer("سلام 👋\nمن یک ربات ساده هستم که با aiogram ساخته شدم.")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
    
