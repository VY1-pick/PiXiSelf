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
SCREENSHOT_API_KEY = os.environ.get("SCREENSHOT_API_KEY", "")
SCREENSHOT_ENDPOINT = "https://shot.screenshotapi.net/screenshot"
DEFAULT_CALENDAR_SELECTOR = os.environ.get(
    "CALENDAR_SELECTOR", ".EventCalendar_root__eventList__chdpK"
)
ONE_API_KEY = os.environ.get("ONE_API_KEY", "")
CACHE_META = "calendar_cache.json"
tehran_tz = pytz.timezone("Asia/Tehran")

if not os.path.exists(f"{SESSION_NAME}.session"):
    print("❌ فایل session پیدا نشد. لطفاً اول روی سیستم لاگین کن "
          "و فایل pixiself_session.session رو توی پروژه بذار.")
    sys.exit(1)

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
clock_enabled = False  # وضعیت ساعت پروفایل

# ============================
# کش تقویم
# ============================
def read_cache_meta():
    if not os.path.exists(CACHE_META):
        return None
    try:
        with open(CACHE_META, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def write_cache_meta(meta: dict):
    with open(CACHE_META, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)

def cached_filename_for(j_year, j_month):
    return f"calendar_{j_year}_{j_month}.png"

def get_cached_if_current():
    meta = read_cache_meta()
    now_j = jdatetime.date.today()
    if not meta:
        return None
    try:
        if meta.get("jalali_year") == now_j.year and meta.get("jalali_month") == now_j.month:
            fname = meta.get("file")
            if fname and os.path.exists(fname):
                return fname
    except Exception:
        return None
    return None

# ============================
# ScreenshotAPI
# ============================
def fetch_screenshot_from_api(selector=None):
    params = {
        "token": SCREENSHOT_API_KEY,
        "url": "https://www.time.ir/",
        "output": "image",
        "file_type": "png",
        "device": "desktop",
        "width": 1920,
        "height": 1080,
        "wait_for_event": "load",
        "selector": DEFAULT_CALENDAR_SELECTOR
    }
    if selector:
        params["selector"] = selector
    try:
        r = requests.get(SCREENSHOT_ENDPOINT, params=params, timeout=60)
        if r.status_code == 200:
            with open("calendar.png", "wb") as f:
                f.write(r.content)
            now_j = jdatetime.date.today()
            meta = {"jalali_year": now_j.year, "jalali_month": now_j.month, "file": "calendar.png"}
            write_cache_meta(meta)
            return "calendar.png"
        else:
            print("❌ Screenshot API error:", r.text)
            return None
    except Exception as e:
        print("❌ خطا در Screenshot API:", e)
        return None

def get_or_create_calendar_image():
    cached = get_cached_if_current()
    if cached:
        return cached
    return fetch_screenshot_from_api()

# ============================
# Geocode
# ============================
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
        item = arr[0]
        return (float(item["lat"]), float(item["lon"]), item.get("display_name", city))
    except Exception:
        return None

# ============================
# Open-Meteo
# ============================
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

        temp = cur.get("temperature")
        windspeed = cur.get("windspeed")
        winddir = cur.get("winddirection")
        time_str = cur.get("time")
        weathercode = cur.get("weathercode")

        code_map = {
            0: "☀️ صاف", 1: "🌤 کمی ابری", 2: "⛅ ابری", 3: "☁️ کاملاً ابری",
            45: "🌫️ مه", 51: "🌦️ نم‌نم باران", 61: "🌧️ باران", 71: "❄️ برف",
            80: "🌧️ باران پراکنده", 95: "⛈️ رعدوبرق"
        }
        desc = code_map.get(weathercode, f"کد:{weathercode}")

        lines = [f"🌍 گزارش هواشناسی (Open-Meteo):"]
        if desc: lines.append(f"• وضعیت: {desc}")
        if temp is not None: lines.append(f"🌡 دما: {temp}°C")
        if windspeed is not None: lines.append(f"💨 باد: {windspeed} m/s (جهت: {winddir}°)")
        if time_str: lines.append(f"⏱ آخرین بروزرسانی: {time_str}")

        return ("\n".join(lines), None)
    except Exception:
        return None

# ============================
# Weather (One-API + fallback)
# ============================
def get_weather(city="تهران"):
    if ONE_API_KEY:
        try:
            url = f"https://one-api.ir/weather/?token={ONE_API_KEY}&action=current&city={city}"
            r = requests.get(url, timeout=12)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict) and data.get("status") == 200 and isinstance(data.get("result"), dict):
                    result = data["result"]
                    weather0 = (result.get("weather") or [{}])[0]
                    description = weather0.get("description") or weather0.get("main") or "نامشخص"
                    icon_code = weather0.get("icon")

                    main = result.get("main", {})
                    temp = main.get("temp")
                    feels_like = main.get("feels_like")
                    temp_min = main.get("temp_min")
                    temp_max = main.get("temp_max")
                    humidity = main.get("humidity")

                    wind = result.get("wind", {})
                    wind_speed = wind.get("speed")
                    wind_deg = wind.get("deg")

                    city_name = result.get("city") or result.get("name") or city
                    country = result.get("country") or (result.get("sys") or {}).get("country") or ""

                    lines = [f"🌤 وضعیت آب‌وهوا در **{city_name}{(' - ' + country) if country else ''}**:"]
                    if description: lines.append(f"• وضعیت: {description}")
                    if temp is not None:
                        lines.append(f"🌡 دما: {temp}°C" + (f" (احساس واقعی: {feels_like}°C)" if feels_like else ""))
                    if temp_min is not None and temp_max is not None:
                        lines.append(f"🔻 کمینه: {temp_min}°C    🔺 بیشینه: {temp_max}°C")
                    if humidity is not None:
                        lines.append(f"💧 رطوبت: {humidity}%")
                    if wind_speed is not None:
                        lines.append(f"💨 باد: {wind_speed} m/s" + (f" ({wind_deg}°)" if wind_deg else ""))

                    msg = "\n".join(lines)
                    icon_url = f"http://openweathermap.org/img/wn/{icon_code}@2x.png" if icon_code else None
                    return (msg, icon_url)
        except Exception as e:
            print("[One-API] Exception:", e)

    geo = geocode_city_nominatim(city)
    if geo:
        lat, lon, display = geo
        res = get_weather_open_meteo_by_coord(lat, lon, tz="Asia/Tehran")
        if res:
            msg, _ = res
            msg = f"📍 مکان: {display}\n" + msg
            return (msg, None)

    return (f"❌ نتونستم اطلاعات آب‌وهوا برای «{city}» رو پیدا کنم.", None)

# ============================
# Clock updater
# ============================
async def clock_updater():
    global clock_enabled
    while True:
        if clock_enabled:
            now = datetime.now(tehran_tz).strftime("%H:%M")
            try:
                await client(UpdateProfileRequest(last_name=f"❤ {now}"))
                print(f"✅ ساعت پروفایل آپدیت شد: {now}")
            except Exception as e:
                print("❌ خطا در بروزرسانی ساعت:", e)
        await asyncio.sleep(60)

# ============================
# هندلرها
# ============================
@client.on(events.NewMessage(pattern="سلام"))
async def handler(event):
    if event.is_private and not event.out:
        await event.reply("سلام رفیق 🌹\nامیدوارم حالت عالی باشه ✨")

@client.on(events.NewMessage(pattern="پینگ"))
async def getping(event):
    if not event.out: return
    start = time.time()
    msg = await event.reply("⏳ در حال بررسی اتصال...")
    end = time.time()
    latency = int((end - start) * 1000)
    await msg.edit(f"🏓 پینگ: {latency} ms\n✅ اتصال سالم و فعال است.")

@client.on(events.NewMessage(pattern="^(ساعت|امروز)$"))
async def getTime(event):
    if not event.out: return
    now = datetime.now(tehran_tz).strftime("%H:%M")
    weekday = days_fa.get(datetime.now(tehran_tz).strftime("%A"), "")
    date = jdatetime.date.today().strftime("%Y/%m/%d")
    await event.reply(
        f"⏰ ساعت فعلی (ایران): **{now}**\n"
        f"📅 امروز: **{weekday}**\n"
        f"📌 تاریخ جلالی: **{date}**",
        parse_mode="markdown"
    )

@client.on(events.NewMessage(pattern="ساعت پروفایل"))
async def toggle_clock(event):
    global clock_enabled
    if not event.out: return
    if clock_enabled:
        clock_enabled = False
        await client(UpdateProfileRequest(last_name=""))
        await event.reply("❌ نمایش ساعت روی پروفایل غیرفعال شد.")
    else:
        clock_enabled = True
        await event.reply("⏰ نمایش ساعت روی پروفایل فعال شد.")

@client.on(events.NewMessage(pattern="^بروزرسانی تقویم$"))
async def refresh_calendar_command(event):
    if not event.out: return
    await event.reply("📥 در حال دریافت نسخه‌ی جدید تقویم...")
    img = await asyncio.to_thread(lambda: fetch_screenshot_from_api(selector=DEFAULT_CALENDAR_SELECTOR))
    if img:
        await event.reply(file=img, message="✅ تقویم با موفقیت بروزرسانی شد 🌙")
    else:
        await event.reply("❌ مشکلی پیش اومد! نتونستم تقویم رو بروزرسانی کنم.")

@client.on(events.NewMessage(pattern="^(تاریخ|تقویم|تعطیلات)$"))
async def send_calendar(event):
    if not event.out: return
    today_jalali = jdatetime.date.today()
    today_gregorian = datetime.today().date()
    weekday_fa = days_fa[today_gregorian.strftime("%A")]
    date_fa = f"{today_jalali.day} {months_fa[today_jalali.month]} {today_jalali.year}"
    today_hijri = "الخميس - ۲۶ ربيع الأول ۱۴۴۷"  # ثابت
    date_en = today_gregorian.strftime("%A - %Y %d %B")

    days_passed = today_gregorian.timetuple().tm_yday
    total_days = 366 if calendar.isleap(today_gregorian.year) else 365
    days_left = total_days - days_passed
    percent = (days_passed / total_days) * 100

    caption = (
        "📅 **گزارش کامل تاریخ و زمان**\n\n"
        f"⏰ ساعت: {datetime.now(tehran_tz).strftime('%H:%M')}\n"
        f"📌 امروز: {weekday_fa} - {date_fa}\n\n"
        f"🌙 تاریخ قمری: {today_hijri}\n"
        f"🌍 تاریخ میلادی: {date_en}\n\n"
        f"📊 روزهای سپری‌شده: {days_passed} ({percent:.2f}%)\n"
        f"📊 روزهای باقی‌مانده: {days_left} ({100 - percent:.2f}%)"
    )

    img = get_or_create_calendar_image()
    if img:
        await event.reply(file=img, message=caption)
    else:
        await event.reply(caption + "\n\n⚠️ نتونستم تصویر تقویم رو بگیرم.")

@client.on(events.NewMessage(pattern=r'^(?:[آا]ب[\s‌]*و[\s‌]*هوا|هواشناسی)(?:\s+(.+))?$'))
async def weather_handler_oneapi(event):
    if not event.out: return
    m = event.pattern_match
    city = m.group(1).strip() if m and m.group(1) else "تهران"
    report, icon = get_weather(city)
    try:
        if icon:
            await event.reply(report, file=icon)
        else:
            await event.reply(report)
    except:
        await event.reply(report + "\n\n⚠️ آیکون هواشناسی قابل بارگیری نبود.")

# ============================
# Pre-fetch calendar
# ============================
async def prefetch_calendar_on_start():
    await asyncio.sleep(2)
    print("⏳ بررسی کش تقویم ماه جاری...")
    img = await asyncio.to_thread(get_or_create_calendar_image)
    if img: print("✅ کش تقویم آماده است:", img)
    else: print("⚠️ نتونستم کش تقویم رو بسازم.")

# ============================
# اجرا
# ============================
async def main():
    me = await client.get_me()
    print(f"✅ لاگین شدی به عنوان: {getattr(me, 'username', me.id)}")
    await client.send_message("me", "✨ KishMish با موفقیت راه‌اندازی شد ✅")
    client.loop.create_task(clock_updater())
    client.loop.create_task(prefetch_calendar_on_start())
    await client.run_until_disconnected()

if __name__ == "__main__":
    print("🚀 در حال اجرا ...")
    with client:
        client.loop.run_until_complete(main())
