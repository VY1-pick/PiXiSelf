from telethon.tl.functions.account import UpdateProfileRequest
from telethon import TelegramClient, events
import os
import sys
import time
import asyncio
import requests
import jdatetime
import calendar
import pytz
import json
from datetime import datetime
import re

# ============================
# تنظیمات و متغیرها
# ============================
days_fa = {
    "Saturday": "شنبه",
    "Sunday": "یک‌شنبه",
    "Monday": "دوشنبه",
    "Tuesday": "سه‌شنبه",
    "Wednesday": "چهارشنبه",
    "Thursday": "پنج‌شنبه",
    "Friday": "جمعه",
}

months_fa = {
    1: "فروردین",
    2: "اردیبهشت",
    3: "خرداد",
    4: "تیر",
    5: "مرداد",
    6: "شهریور",
    7: "مهر",
    8: "آبان",
    9: "آذر",
    10: "دی",
    11: "بهمن",
    12: "اسفند",
}

API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
SESSION_NAME = "pixiself_session"

ONE_API_KEY = os.environ.get("ONE_API_KEY", "")

tehran_tz = pytz.timezone("Asia/Tehran")

if not os.path.exists(f"{SESSION_NAME}.session"):
    print("❌ فایل session پیدا نشد.")
    sys.exit(1)

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

clock_enabled = False  # وضعیت ساعت پروفایل

# ============================
# تابع تشخیص زبان متن
# ============================
def detect_lang(text: str) -> str:
    # اگر متن فقط حروف انگلیسی و فاصله بود → en
    if re.match(r'^[A-Za-z0-9\s.,!?;:()"\']+$', text):
        return "en"
    # اگر متن شامل حروف فارسی بود → fa
    if re.search(r'[\u0600-\u06FF]', text):
        return "fa"
    # پیش‌فرض انگلیسی
    return "en"

# ============================
# تابع ترجمه با One-API
# ============================
def translate_text_auto(text: str) -> str:
    if not ONE_API_KEY:
        return "❌ توکن One-API تنظیم نشده!"
    try:
        src_lang = detect_lang(text)
        if src_lang == "fa":
            lang = "fa|en"
        else:
            lang = "en|fa"

        url = f"https://one-api.ir/translate/?token={ONE_API_KEY}&action=google&lang={lang}&q={text}"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict) and data.get("status") == 200:
                result = data.get("result")
                return f"🌐 ترجمه ({lang}):\n\n{result}"
            else:
                return f"❌ خطا در ترجمه: {data}"
        else:
            return f"❌ خطای HTTP: {r.status_code}"
    except Exception as e:
        return f"❌ خطا در ترجمه: {e}"

# ============================
# هندلر ترجمه در تلگرام
# ============================
@client.on(events.NewMessage(pattern=r'^ترجمه\s+(.+)$'))
async def translate_handler(event):
    if not event.out:
        return
    text = event.pattern_match.group(1).strip()
    translated = translate_text_auto(text)
    await event.reply(translated)

# ============================
# ادامه کدهای قبلی (پینگ، ساعت، تقویم، هواشناسی، ...)
# ============================
# این بخش همونطور که نوشتی باقی می‌مونه
# فقط ترجمه بهش اضافه شد
# ============================

async def main():
    me = await client.get_me()
    print(f"✅ لاگین شدی به عنوان: {getattr(me, 'username', me.id)}")
    await client.send_message("me", "KishMish آماده به کار هستش ✅")
    await client.run_until_disconnected()

if __name__ == "__main__":
    print("🚀 در حال اجرا ...")
    with client:
        client.loop.run_until_complete(main())
