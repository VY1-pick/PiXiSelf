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
import re
from datetime import datetime, timedelta

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
    1: "فروردین", 2: "اردیبهشت", 3: "خرداد", 4: "تیر",
    5: "مرداد", 6: "شهریور", 7: "مهر", 8: "آبان",
    9: "آذر", 10: "دی", 11: "بهمن", 12: "اسفند",
}

API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
SESSION_NAME = "pixiself_session"

ONE_API_KEY = os.environ.get("ONE_API_KEY", "").strip()
tehran_tz = pytz.timezone("Asia/Tehran")

if not os.path.exists(f"{SESSION_NAME}.session"):
    print("❌ فایل session پیدا نشد.")
    sys.exit(1)

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
clock_enabled = False  # وضعیت ساعت پروفایل

# ----------------------------
# توابع مرتبط با هوا و تقویم (مثل قبل)
# ----------------------------
def geocode_city_nominatim(city):
    try:
        url = "https://nominatim.openstreetmap.org/search"
        params = {"q": city, "format": "json", "limit": 1, "accept-language": "fa"}
        headers = {"User-Agent": "PiXiSelfBot/1.0"}
        r = requests.get(url, params=params, headers=headers, timeout=10)
        r.raise_for_status()
        arr = r.json()
        if not arr:
            return None
        return (float(arr[0]["lat"]), float(arr[0]["lon"]), arr[0].get("display_name", city))
    except Exception:
        return None

def get_weather_open_meteo_by_coord(lat, lon, tz="Asia/Tehran"):
    try:
        url = "https://api.open-meteo.com/v1/forecast"
        params = {"latitude": lat, "longitude": lon, "current_weather": "true", "timezone": tz}
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        cur = data.get("current_weather")
        if not cur:
            return None
        code_map = {
            0: "☀️ آسمان صاف", 1: "⛅ کمی ابری", 2: "☁️ نیمه‌ابری", 3: "☁️ ابری",
            45: "🌫️ مه", 51: "🌦️ نم‌نم باران", 61: "🌧️ باران", 71: "❄️ برف",
            80: "🌧️ بارش پراکنده", 95: "⛈️ رعدوبرق",
        }
        desc = code_map.get(cur.get("weathercode"), "نامشخص")
        msg = (
            f"📍 موقعیت: {lat}, {lon}\n\n"
            f"🌤 وضعیت: {desc}\n"
            f"🌡 دما: {cur.get('temperature')}°C\n"
            f"💨 سرعت باد: {cur.get('windspeed')} m/s\n"
            f"⏱ آخرین بروزرسانی: {cur.get('time')}"
        )
        return (msg, None)
    except Exception:
        return None

def get_weather(city="تهران"):
    # تلاش اولیه با One-API (اگر توکن باشد)
    if ONE_API_KEY:
        try:
            url = "https://one-api.ir/translate/"  # (نیاز نداریم اینجا) <-- فقط برای هماهنگی ساختار
            # از endpoint هواشناسی استفاده می‌کنیم:
            url = f"https://one-api.ir/weather/"
            headers = {
                "one-api-token": ONE_API_KEY,
                "Accept": "application/json",
                "User-Agent": "PiXiSelfBot/1.0"
            }
            params = {"action": "current", "city": city}
            r = requests.get(url, headers=headers, params=params, timeout=12)
            if r.status_code == 200:
                data = r.json()
                if data.get("status") == 200 and isinstance(data.get("result"), dict):
                    result = data["result"]
                    weather0 = (result.get("weather") or [{}])[0]
                    description = weather0.get("description") or "نامشخص"
                    temp = result.get("main", {}).get("temp")
                    humidity = result.get("main", {}).get("humidity")
                    wind = result.get("wind", {})
                    city_name = result.get("city") or city

                    lines = [
                        f"🌍 وضعیت هوا در **{city_name}**:",
                        f"🌤 وضعیت: {description}",
                    ]
                    if temp is not None: lines.append(f"🌡 دما: {temp}°C")
                    if humidity is not None: lines.append(f"💧 رطوبت: {humidity}%")
                    if wind.get("speed") is not None: lines.append(f"💨 باد: {wind.get('speed')} m/s")

                    return ("\n".join(lines), None)
            else:
                # لاگ دقیق برای دیباگ (مثلاً 403)
                print(f"[One-API weather] HTTP {r.status_code} — body: {r.text[:400]}")
        except Exception as e:
            print("Weather Error:", e)

    # fallback: Open-Meteo
    geo = geocode_city_nominatim(city)
    if geo:
        lat, lon, display = geo
        res = get_weather_open_meteo_by_coord(lat, lon)
        if res:
            msg, icon = res
            return (f"📍 {display}\n\n{msg}", icon)

    return (f"❌ نتونستم وضعیت هوا برای «{city}» رو بیارم.", None)

# ============================
# ترجمه — تشخیص اتوماتیک زبان + ارسال توکن در هدر
# ============================
def detect_lang_simple(text: str) -> str:
    # اگر حروف فارسی وجود داشته باشد => fa، در غیر این صورت en
    if re.search(r'[\u0600-\u06FF]', text):
        return "fa"
    return "en"

def translate_text_auto(text: str):
    """
    برمی‌گرداند (result_text, error_or_None)
    از One-API استفاده می‌کند و توکن را در هدر 'one-api-token' می‌فرستد.
    """
    if not ONE_API_KEY:
        return ("❌ توکن One-API تنظیم نشده. لطفاً مقدار محیطی ONE_API_KEY را قرار بده.", None)

    src = detect_lang_simple(text)
    if src == "fa":
        lang = "fa|en"
        src_name, dst_name = "فارسی", "انگلیسی"
    else:
        lang = "en|fa"
        src_name, dst_name = "English", "فارسی"

    endpoint = "https://one-api.ir/translate/"
    headers = {
        "one-api-token": ONE_API_KEY,
        "Accept": "application/json",
        "User-Agent": "PiXiSelfBot/1.0"
    }
    params = {
        "action": "google",
        "lang": lang,
        "q": text
    }

    try:
        r = requests.get(endpoint, headers=headers, params=params, timeout=12)
        # لاگ‌برداری برای کمک به دیباگ (در صورت خطا)
        if r.status_code != 200:
            print(f"[One-API translate] HTTP {r.status_code} — body: {r.text[:600]}")
        r.raise_for_status()
        data = r.json()
        # بررسی ساختار پاسخ
        if not isinstance(data, dict):
            return ("❌ پاسخ نامعتبر از سرویس ترجمه.", None)
        if data.get("status") != 200:
            # خطای API — پیام داخل response را نشان بده
            msg = data.get("message") or str(data)
            return (f"❌ خطای سرویس ترجمه: {msg}", None)
        result = data.get("result")
        if not result:
            return ("❌ سرویس ترجمه پاسخی نداد.", None)

        # قالب زیبا برای پیام خروجی
        out = (
            f"🌐 **ترجمه خودکار** ({src_name} → {dst_name})\n\n"
            f"📎 متن اصلی:\n`{text}`\n\n"
            f"🔁 ترجمه:\n{result}"
        )
        return (out, None)
    except requests.HTTPError as he:
        # اگر 403 یا 401 یا ... باشه، در لاگ چاپ کن و پیام مناسبی به کاربر بده
        status = getattr(he.response, "status_code", None)
        body = getattr(he.response, "text", "")
        print(f"[One-API translate] HTTPError {status} — {body[:800]}")
        if status == 401:
            return ("❌ خطا: توکن نامعتبر است (401). لطفاً ONE_API_KEY را بررسی کن.", None)
        if status == 403:
            return ("❌ خطا: مجوز کافی نیست (403). احتمالاً توکن یا دسترسی نامناسب است.", None)
        return (f"❌ خطای HTTP در ترجمه: {status}", None)
    except Exception as e:
        print("Translate Exception:", e)
        return (f"❌ خطا در تماس با سرویس ترجمه: {e}", None)


# ============================
# آپدیت ساعت پروفایل
# ============================
async def clock_updater():
    global clock_enabled
    while True:
        if clock_enabled:
            now = datetime.now(tehran_tz).strftime("%H:%M")
            try:
                await client(UpdateProfileRequest(last_name=f"🕒 {now}"))
            except Exception as e:
                print("❌ خطا در آپدیت ساعت:", e)
        await asyncio.sleep(60)

# ============================
# هندلرها
# ============================
@client.on(events.NewMessage(pattern="سلام"))
async def handler(event):
    if event.is_private and not event.out:
        await event.reply("🌹 سلام! امیدوارم حالت عالی باشه ✨")

@client.on(events.NewMessage(pattern="پینگ"))
async def getping(event):
    if not event.out: return
    start = time.time()
    msg = await event.reply("⏳ در حال اندازه‌گیری...")
    latency = int((time.time() - start) * 1000)
    await msg.edit(f"🏓 پینگ: **{latency} ms**\n✅ همه‌چی مرتب است!")

@client.on(events.NewMessage(pattern="^(ساعت|امروز)$"))
async def getTime(event):
    if not event.out: return
    now = datetime.now(tehran_tz).strftime("%H:%M")
    weekday = datetime.now(tehran_tz).strftime("%A")
    weekday_fa = days_fa.get(weekday, weekday)
    today_jalali = jdatetime.date.today()
    date_fa = f"{today_jalali.day} {months_fa[today_jalali.month]} {today_jalali.year}"
    await event.reply(
        f"⏰ ساعت: **{now}**\n"
        f"📅 امروز: **{weekday_fa}**\n"
        f"📌 تاریخ: **{date_fa}**"
    )

@client.on(events.NewMessage(pattern="ساعت پروفایل"))
async def toggle_clock(event):
    global clock_enabled
    if not event.out: return
    clock_enabled = not clock_enabled
    if not clock_enabled:
        await client(UpdateProfileRequest(last_name=""))
        await event.reply("❌ ساعت پروفایل غیرفعال شد.")
    else:
        await event.reply("✅ ساعت پروفایل فعال شد.")

@client.on(events.NewMessage(pattern="^(تاریخ|تقویم|تعطیلات)$"))
async def send_calendar(event):
    if not event.out: return
    today = datetime.now(tehran_tz).date()
    jalali_today = jdatetime.date.today()
    weekday_fa = days_fa[today.strftime("%A")]
    date_fa = f"{jalali_today.day} {months_fa[jalali_today.month]} {jalali_today.year}"
    days_passed = today.timetuple().tm_yday
    total_days = 366 if calendar.isleap(today.year) else 365
    days_left = total_days - days_passed
    percent = (days_passed / total_days) * 100

    # مثال: گرفتن تعطیلات ۷ روز آینده می‌تونه با فراخوانی API مشخص انجام بشه.
    # اکنون نمونهٔ ثابت می‌ذاریم (تو می‌تونی بعداً از holidayapi.ir یا time.ir بخونی).
    holidays = [
        "🛑 جمعه - تعطیل هفتگی",
    ]

    caption = (
        f"📅 امروز: **{weekday_fa} - {date_fa}**\n\n"
        f"📊 روزهای سپری‌شده: {days_passed} ({percent:.2f}%)\n"
        f"📊 روزهای باقی‌مانده: {days_left} ({100 - percent:.2f}%)\n\n"
    )
    await event.reply(caption)

# ============================
# هندلر ترجمه — فقط وقتی خودت پیام می‌فرستی (event.out)
# ============================
@client.on(events.NewMessage(pattern=r'^ترجمه\s+(.+)$'))
async def translate_handler(event):
    if not event.out:
        return
    text = event.pattern_match.group(1).strip()
    result_text, _ = translate_text_auto_wrapper = translate_text_auto(text)  # تابع ترجمه بالا
    # translate_text_auto برمی‌گرداند (text, None)
    if isinstance(result_text, tuple):
        # safety: if accidentally returned tuple
        result_text = result_text[0]
    await event.reply(result_text)

# ============================
# اجرا
# ============================
async def main():
    me = await client.get_me()
    print(f"✅ لاگین شدی به عنوان: {getattr(me, 'username', me.id)}")
    await client.send_message("me", "✅ ربات آماده به کاره!")
    client.loop.create_task(clock_updater())
    await client.run_until_disconnected()

if __name__ == "__main__":
    print("🚀 در حال اجرا ...")
    with client:
        client.loop.run_until_complete(main())
