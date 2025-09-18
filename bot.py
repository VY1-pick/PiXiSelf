from telethon.tl.functions.account import UpdateProfileRequest
import os
import sys
import time
import asyncio
import requests
import jdatetime
import calendar
import pytz
from datetime import datetimefrom telethon.tl.functions.account import UpdateProfileRequest
import os
import sys
import time
import asyncio
import requests
import jdatetime
import calendar
import pytz
from datetime import datetime
from telethon import TelegramClient, events

# ============================
# داده‌ها و تنظیمات
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

API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
SESSION_NAME = "pixiself_session"
tehran_tz = pytz.timezone("Asia/Tehran")

# ScreenshotAPI تنظیمات
SCREENSHOT_API_KEY = os.environ.get("SCREENSHOT_API_KEY", "DG10VT9-7YZ4R94-PH9Q0HG-4XGMYVC")
SCREENSHOT_ENDPOINT = "https://shot.screenshotapi.net/screenshot"

if not os.path.exists(f"{SESSION_NAME}.session"):
    print("❌ فایل session پیدا نشد. لطفاً اول روی سیستم لاگین کن "
          "و فایل pixiself_session.session رو توی پروژه بذار.")
    sys.exit(1)

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
clock_enabled = False  # وضعیت ساعت پروفایل

# ============================
# آپدیت‌کننده ساعت پروفایل
# ============================
async def clock_updater():
    global clock_enabled
    while True:
        if clock_enabled:
            now = datetime.now(tehran_tz).strftime("%H:%M")
            try:
                await client(UpdateProfileRequest(
                    last_name=f"❤ {now}"
                ))
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
    weekday_fa = days_fa[weekday]
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

# ============================
# تعطیلات و تقویم (اسکرین‌شات از time.ir)
# ============================
def fetch_calendar_image():
    params = {
        "token": SCREENSHOT_API_KEY,
        "url": "https://www.time.ir/",
        "output": "image",
        "file_type": "png",
        "wait_for_event": "load",
        "device": "desktop",   # 🖥️ اینجا دسکتاپ انتخاب می‌کنیم
        "viewport": "1920x1080",
    }

    filename = "calendar.png"
    try:
        r = requests.get(SCREENSHOT_ENDPOINT, params=params, stream=True)
        if r.status_code == 200:
            with open(filename, "wb") as f:
                for chunk in r.iter_content(1024):
                    f.write(chunk)
            return filename
        else:
            print("❌ خطا در گرفتن اسکرین‌شات:", r.text)
            return None
    except Exception as e:
        print("❌ خطا در دانلود اسکرین‌شات:", e)
        return None

@client.on(events.NewMessage(pattern="^(تاریخ|تقویم|تعطیلات)$"))
async def send_calendar(event):
    if not event.out:
        return

    today_jalali = jdatetime.date.today()
    today_gregorian = datetime.today().date()
    today_hijri = "25 ربیع الاول 1447"  # TODO: از API قمری بگیریم

    days_passed = today_gregorian.timetuple().tm_yday
    total_days = 366 if calendar.isleap(today_gregorian.year) else 365
    days_left = total_days - days_passed
    percent = (days_passed / total_days) * 100

    caption = (
        f"⏰ ساعت: {datetime.now(tehran_tz).strftime('%H:%M')}\n"
        f"📅 تاریخ شمسی: {today_jalali.strftime('%A %d %B %Y')}\n"
        f"📅 تاریخ قمری: {today_hijri}\n"
        f"📅 تاریخ میلادی: {today_gregorian.strftime('%A %d %B %Y')}\n\n"
        f"📊 روزهای سپری شده: {days_passed} ({percent:.2f}%)\n"
        f"📊 روزهای باقی‌مانده: {days_left} ({100 - percent:.2f}%)"
    )

    img = fetch_calendar_image()
    if img:
        await event.reply(file=img, message=caption)
    else:
        await event.reply(caption + "\n\n❌ نتونستم عکس تقویم رو بگیرم.")

# ============================
# اجرای اصلی
# ============================
async def main():
    me = await client.get_me()
    print(f"✅ لاگین شدی به عنوان: {getattr(me, 'username', me.id)}")
    await client.send_message("me", "KishMish آماده به کار هستش ✅")
    client.loop.create_task(clock_updater())
    await client.run_until_disconnected()

if __name__ == "__main__":
    print("🚀 در حال اجرا ...")
    with client:
        client.loop.run_until_complete(main())

from telethon import TelegramClient, events

# ============================
# داده‌ها و تنظیمات
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

API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
SESSION_NAME = "pixiself_session"
tehran_tz = pytz.timezone("Asia/Tehran")

if not os.path.exists(f"{SESSION_NAME}.session"):
    print("❌ فایل session پیدا نشد. لطفاً اول روی سیستم لاگین کن "
          "و فایل pixiself_session.session رو توی پروژه بذار.")
    sys.exit(1)

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
clock_enabled = False  # وضعیت ساعت پروفایل

# ============================
# آپدیت‌کننده ساعت پروفایل
# ============================
async def clock_updater():
    global clock_enabled
    while True:
        if clock_enabled:
            now = datetime.now(tehran_tz).strftime("%H:%M")
            try:
                await client(UpdateProfileRequest(
                    last_name=f"❤ {now}"
                ))
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
    weekday_fa = days_fa[weekday]
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

# ============================
# تعطیلات و تقویم (با اسکرین‌شات سرویس بیرونی)
# ============================
def fetch_calendar_image():
    # ⚠️ این URL باید با سرویس اسکرین‌شات جایگزین بشه (مثلاً urlbox.io یا سرویس شخصی)
    # نمونه: https://api.screenshotapi.net/screenshot?token=YOUR_TOKEN&url=https://www.time.ir/
    url = os.environ.get("CALENDAR_SHOT_URL", "")
    filename = "calendar.png"

    if not url:
        print("❌ CALENDAR_SHOT_URL ست نشده.")
        return None

    try:
        r = requests.get(url)
        if r.status_code == 200:
            with open(filename, "wb") as f:
                f.write(r.content)
            return filename
        else:
            print("❌ خطا در گرفتن اسکرین‌شات:", r.text)
            return None
    except Exception as e:
        print("❌ خطا در دانلود اسکرین‌شات:", e)
        return None

@client.on(events.NewMessage(pattern="^(تاریخ|تقویم|تعطیلات)$"))
async def send_calendar(event):
    if not event.out:
        return

    today_jalali = jdatetime.date.today()
    today_gregorian = datetime.today().date()
    today_hijri = "25 ربیع الاول 1447"  # TODO: از API بگیر

    days_passed = today_gregorian.timetuple().tm_yday
    total_days = 366 if calendar.isleap(today_gregorian.year) else 365
    days_left = total_days - days_passed
    percent = (days_passed / total_days) * 100

    caption = (
        f"⏰ ساعت: {datetime.now(tehran_tz).strftime('%H:%M')}\n"
        f"📅 تاریخ شمسی: {today_jalali.strftime('%A %d %B %Y')}\n"
        f"📅 تاریخ قمری: {today_hijri}\n"
        f"📅 تاریخ میلادی: {today_gregorian.strftime('%A %d %B %Y')}\n\n"
        f"📊 روزهای سپری شده: {days_passed} ({percent:.2f}%)\n"
        f"📊 روزهای باقی‌مانده: {days_left} ({100 - percent:.2f}%)"
    )

    img = fetch_calendar_image()
    if img:
        await event.reply(file=img, message=caption)
    else:
        await event.reply(caption + "\n\n❌ نتونستم عکس تقویم رو بگیرم.")

# ============================
# اجرای اصلی
# ============================
async def main():
    me = await client.get_me()
    print(f"✅ لاگین شدی به عنوان: {getattr(me, 'username', me.id)}")
    await client.send_message("me", "KishMish آماده به کار هستش ✅")
    client.loop.create_task(clock_updater())
    await client.run_until_disconnected()

if __name__ == "__main__":
    print("🚀 در حال اجرا ...")
    with client:
        client.loop.run_until_complete(main())

