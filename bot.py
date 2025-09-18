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
import xml.etree.ElementTree as ET
from datetime import datetime

# ============================
# تنظیمات و متغیرها
# ============================
# روزهای هفته فارسی
days_fa = {
    "Saturday": "شنبه",
    "Sunday": "یک‌شنبه",
    "Monday": "دوشنبه",
    "Tuesday": "سه‌شنبه",
    "Wednesday": "چهارشنبه",
    "Thursday": "پنج‌شنبه",
    "Friday": "جمعه",
}

# ماه‌های فارسی
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

# screenshotapi.net key (محیطی)
SCREENSHOT_API_KEY = os.environ.get("SCREENSHOT_API_KEY", "")
SCREENSHOT_ENDPOINT = "https://shot.screenshotapi.net/screenshot"

# selector برای بخش مناسبت‌های time.ir
DEFAULT_CALENDAR_SELECTOR = os.environ.get(
    "CALENDAR_SELECTOR",
    "EventList_root__Ub1m_ EventCalendar_root__eventList__chdpK"
)

# فایل cache metadata
CACHE_META = "calendar_cache.json"

# منطقه زمانی تهران
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
        "selector": ".EventCalendar_root__eventList__chdpK"
    }

    if selector:
        params["selector"] = selector

    try:
        r = requests.get(SCREENSHOT_ENDPOINT, params=params, timeout=60)
        if r.status_code == 200:
            with open("calendar.png", "wb") as f:
                f.write(r.content)
            return "calendar.png"
        else:
            print("❌ Screenshot API error:", r.text)
            return None
    except Exception as e:
        print("❌ خطا در تماس با Screenshot API:", e)
        return None

def get_or_create_calendar_image():
    cached = get_cached_if_current()
    if cached:
        return cached
    fname = fetch_screenshot_from_api()
    return fname

# ============================
# تابع گرفتن آب‌وهوا از Parsijoo API
# ============================
def get_weather_parsijoo(city="تهران"):
    url = f"http://parsijoo.ir/api?serviceType=weather-API&q={city}"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            return f"❌ خطا در دریافت آب‌وهوا برای {city}"
        root = ET.fromstring(r.content)
        day = root.find(".//day")
        if day is None:
            return f"❌ اطلاعات هوا برای {city} یافت نشد"

        status = day.findtext("status", default="—")
        temp = day.findtext("temp", default="—")
        min_temp = day.findtext("min-temp", default="—")
        max_temp = day.findtext("max-temp", default="—")
        city_name = day.findtext("city-name", default=city)

        msg = (
            f"🌤 وضعیت هوا در {city_name}:\n"
            f"• وضعیت: {status}\n"
            f"🌡 دما: {temp}°C\n"
            f"🔻 حداقل: {min_temp}°C    🔺 حداکثر: {max_temp}°C"
        )
        return msg
    except Exception as e:
        return f"❌ خطا در دریافت آب‌وهوا: {e}"

# ============================
# آپدیت ساعت پروفایل
# ============================
async def clock_updater():
    global clock_enabled
    while True:
        if clock_enabled:
            now = datetime.now(tehran_tz).strftime("%H:%M")
            try:
                await client(UpdateProfileRequest(last_name=f"❤ {now}"))
                print(f"✅ ساعت آپدیت شد: {now}")
            except Exception as e:
                print("❌ خطا در آپدیت ساعت:", e)
        await asyncio.sleep(60)

# ============================
# هندلرها
# ============================
@client.on(events.NewMessage(pattern="سلام"))
async def handler(event):
    if event.is_private and not event.out:
        await event.reply("سلام و درود 👋")

@client.on(events.NewMessage(pattern="پینگ"))
async def getping(event):
    if not event.out:
        return
    start = time.time()
    msg = await event.reply("🏓 پینگ...")
    end = time.time()
    latency = int((end - start) * 1000)
    await msg.edit(f"🏓 پینگ: {latency} ms\n✅ سرور فعاله")

@client.on(events.NewMessage(pattern="^(ساعت|امروز)$"))
async def getTime(event):
    if not event.out:
        return
    now = datetime.now(tehran_tz).strftime("%H:%M")
    weekday = datetime.now(tehran_tz).strftime("%A")
    date = jdatetime.date.today().strftime("%Y/%m/%d")
    weekday_fa = days_fa.get(weekday, weekday)
    await event.reply(
        f"⏰ ساعت به وقت ایران: **{now}**\n"
        f"📅 امروز **{weekday_fa}** هست\n"
        f"📌 تاریخ: **{date}**",
        parse_mode="markdown"
    )

@client.on(events.NewMessage(pattern="ساعت پروفایل"))
async def toggle_clock(event):
    global clock_enabled
    if not event.out:
        return
    if clock_enabled:
        clock_enabled = False
        await client(UpdateProfileRequest(last_name=""))
        await event.reply("❌ ساعت غیرفعال شد")
    else:
        clock_enabled = True
        await event.reply("⏰ ساعت فعال شد")

# بروزرسانی تقویم دستی
@client.on(events.NewMessage(pattern="^بروزرسانی تقویم$"))
async def refresh_calendar_command(event):
    if not event.out:
        return
    await event.reply("⏳ در حال بروزرسانی تقویم (اسکرین‌شات جدید)...")
    img = await asyncio.to_thread(lambda: fetch_screenshot_from_api(selector=DEFAULT_CALENDAR_SELECTOR))
    if img:
        await event.reply(file=img, message="✅ تقویم آپدیت شد (نسخهٔ جدید ماهیانه)")
    else:
        await event.reply("❌ بروزرسانی موفق نبود — دوباره تلاش کن یا لاگ‌ها را بررسی کن.")

# ارسال تقویم
@client.on(events.NewMessage(pattern="^(تاریخ|تقویم|تعطیلات)$"))
async def send_calendar(event):
    if not event.out:
        return

    today_jalali = jdatetime.date.today()
    today_gregorian = datetime.today().date()

    weekday_fa = days_fa[today_gregorian.strftime("%A")]
    date_fa = f"{today_jalali.day} {months_fa[today_jalali.month]} {today_jalali.year}"

    today_hijri = "الخميس - ۲۶ ربيع الأول ۱۴۴۷"  # فعلاً ثابت
    date_en = today_gregorian.strftime("%A - %Y %d %B")

    days_passed = today_gregorian.timetuple().tm_yday
    total_days = 366 if calendar.isleap(today_gregorian.year) else 365
    days_left = total_days - days_passed
    percent = (days_passed / total_days) * 100

    caption = (
        "◄ ساعت و تاریخ :   \n\n"
        f"• ساعت : {datetime.now(tehran_tz).strftime('%H:%M')}\n"
        f"• تاریخ امروز : {weekday_fa} - {date_fa}\n\n"
        f"• تاریخ قمری : {today_hijri}\n"
        f"• تاریخ میلادی : {date_en}\n\n"
        f"• روز های سپری شده : {days_passed} روز ( {percent:.2f} درصد )\n"
        f"• روز های باقی مانده : {days_left} روز ( {100 - percent:.2f} درصد )"
    )

    img = get_or_create_calendar_image()
    if img:
        await event.reply(file=img, message=caption)
    else:
        await event.reply(caption + "\n\n❌ نتونستم عکس تقویم رو بگیرم.")

# هندلر آب‌وهوا
@client.on(events.NewMessage(pattern="^(آب.?وهوا|هواشناسی)( .+)?$"))
async def weather_handler_parsijoo(event):
    if not event.out:
        return
    parts = event.raw_text.split(maxsplit=1)
    city = parts[1].strip() if len(parts) > 1 else "تهران"
    report = get_weather_parsijoo(city)
    await event.reply(report)

# ============================
# پیش‌بارگیری
# ============================
async def prefetch_calendar_on_start():
    await asyncio.sleep(2)
    print("⏳ چک کردن کش تقویم ماه جاری...")
    img = await asyncio.to_thread(get_or_create_calendar_image)
    if img:
        print("✅ کش تقویم حاضر است:", img)
    else:
        print("⚠️ نتوانست کش تقویم را بسازد.")

# ============================
# اجرا
# ============================
async def main():
    me = await client.get_me()
    print(f"✅ لاگین شدی به عنوان: {getattr(me, 'username', me.id)}")
    await client.send_message("me", "KishMish آماده به کار هستش ✅")
    client.loop.create_task(clock_updater())
    client.loop.create_task(prefetch_calendar_on_start())
    await client.run_until_disconnected()

if __name__ == "__main__":
    print("🚀 در حال اجرا ...")
    with client:
        client.loop.run_until_complete(main())
