# bot.py (نسخهٔ آپدیت‌شده — شامل اصلاحات هواشناسی)
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

# ScreenshotAPI (اختیاری)
SCREENSHOT_API_KEY = os.environ.get("SCREENSHOT_API_KEY", "")
SCREENSHOT_ENDPOINT = "https://shot.screenshotapi.net/screenshot"

# selector برای بخش مناسبت‌های time.ir (اختیاری)
DEFAULT_CALENDAR_SELECTOR = os.environ.get(
    "CALENDAR_SELECTOR",
    ".EventCalendar_root__eventList__chdpK"
)

# OneAPI توکن هواشناسی (بذار توی Railway)
ONE_API_KEY = os.environ.get("ONE_API_KEY", "")

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
# ScreenshotAPI (اختیاری)
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
            # نوشته متا برای کش ماه جاری
            now_j = jdatetime.date.today()
            meta = {"jalali_year": now_j.year, "jalali_month": now_j.month, "file": "calendar.png"}
            write_cache_meta(meta)
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
# هواشناسی با one-api.ir (طبق داکیومنت)
# ============================
def get_weather_oneapi(city="تهران"):
    """
    برگشت: (message_string, icon_url_or_None)
    طبق داکیومنت: https://one-api.ir/... (action=current یا hourly)
    """
    if not ONE_API_KEY:
        return (f"❌ توکن One-API تنظیم نشده. متغیر محیطی ONE_API_KEY را قرار بده.", None)

    # city ممکنه به فارسی باشه؛ urlencode خود requests رو انجام میده
    url = f"https://one-api.ir/weather/?token={ONE_API_KEY}&action=current&city={city}"

    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return (f"❌ خطا در تماس با سرویس هواشناسی: {e}", None)

    # بررسی وضعیت پاسخ
    if not isinstance(data, dict) or data.get("status") != 200:
        # ممکنه پیام خطا در فیلدهای دیگر باشد
        msg_err = data.get("message") if isinstance(data, dict) else str(data)
        return (f"❌ نتوانستم اطلاعات هوا را دریافت کنم: {msg_err}", None)

    result = data.get("result", {})
    # طبق مثال داکیومنت: result شامل weather (لیست)، main، wind، sys، country و غیره است
    weather_list = result.get("weather") or []
    weather0 = weather_list[0] if weather_list else {}
    description = weather0.get("description") or weather0.get("main") or "نامشخص"
    icon_code = weather0.get("icon")  # مثل "01d"

    main = result.get("main", {})
    temp = main.get("temp")
    feels_like = main.get("feels_like")
    temp_min = main.get("temp_min")
    temp_max = main.get("temp_max")
    pressure = main.get("pressure")
    humidity = main.get("humidity")

    wind = result.get("wind", {})
    wind_speed = wind.get("speed")
    wind_deg = wind.get("deg")

    city_name = result.get("city") or result.get("name") or city
    country = result.get("country") or (result.get("sys") or {}).get("country") or ""

    # ساخت متن خوانا (فارسی)
    lines = []
    lines.append(f"🌤 وضعیت هوا در {city_name}{(' - ' + country) if country else ''}:")
    if description:
        lines.append(f"• وضعیت: {description}")
    if temp is not None:
        lines.append(f"🌡 دما: {temp}°C" + (f" (احساس: {feels_like}°C)" if feels_like is not None else ""))
    if temp_min is not None and temp_max is not None:
        lines.append(f"🔻 حداقل: {temp_min}°C    🔺 حداکثر: {temp_max}°C")
    if humidity is not None:
        lines.append(f"💧 رطوبت: {humidity}%")
    if wind_speed is not None:
        lines.append(f"💨 باد: {wind_speed} m/s" + (f" ({wind_deg}°)" if wind_deg is not None else ""))

    msg = "\n".join(lines)

    # ساخت URL آیکون (اگر فقط کد داده شده باشد از OpenWeather استفاده می‌کنیم)
    icon_url = None
    if icon_code:
        # اگر api یک URL کامل داده باشه آن را برمی‌گردانیم (چک کوتاه)
        if icon_code.startswith("http"):
            icon_url = icon_code
        else:
            icon_url = f"http://openweathermap.org/img/wn/{icon_code}@2x.png"

    return (msg, icon_url)

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

# ============================
# هندلر آب‌وهوا (پذیرش 'آ' یا 'ا' در ابتدای آب)
# ============================
# الگو: قبول کنه "آب و هوا" یا "اب و هوا" یا "آب‌وهوا" یا "هواشناسی"
@client.on(events.NewMessage(pattern=r'^(?:[آا]ب\s*و\s*هوا|هواشناسی)(?:\s+(.+))?$'))
async def weather_handler_oneapi(event):
    if not event.out:
        return
    # از pattern_match گروه 1 (شهر) را بگیریم اگر وجود داشته باشد
    m = event.pattern_match
    city = None
    if m and m.group(1):
        city = m.group(1).strip()
    else:
        # fallback به تفکیک متن خام (اگر کاربر نوشت: "آب و هوا" بدون شهر)
        parts = event.raw_text.split(maxsplit=1)
        if len(parts) > 1:
            city = parts[1].strip()
    if not city:
        city = "تهران"

    report, icon = get_weather_oneapi(city)
    try:
        if icon:
            # اگر آدرس آیکون معتبر باشه ارسال کن
            await event.reply(report, file=icon)
        else:
            await event.reply(report)
    except Exception as e:
        # در صورت بروز خطا (مثلاً فایل آیکون در دسترس نباشد)، فقط متن را بفرست
        await event.reply(report + f"\n\n(تصویر آیکون قابل بارگیری نیست: {e})")

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
