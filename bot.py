from telethon.tl.functions.account import UpdateProfileRequest
import os
from datetime import datetime, timedelta
import requests
import jdatetime
import calendar
import matplotlib.pyplot as plt
import matplotlib
import matplotlib.font_manager as fm
from zoneinfo import ZoneInfo
import pytz
import sys
from telethon import TelegramClient, events
import time
import asyncio

# ============================
# تنظیم فونت فارسی برای matplotlib
# ============================
FONT_URL = "https://github.com/googlefonts/noto-fonts/blob/main/hinted/ttf/NotoSansArabic/NotoSansArabic-Regular.ttf?raw=true"
FONT_PATH = "NotoSansArabic-Regular.ttf"

if not os.path.exists(FONT_PATH):
    import urllib.request
    urllib.request.urlretrieve(FONT_URL, FONT_PATH)

prop = fm.FontProperties(fname=FONT_PATH)
matplotlib.rcParams['font.family'] = prop.get_name()

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
HOLIDAY_API = "https://holidayapi.ir/jalali/"
tehran_tz = pytz.timezone("Asia/Tehran")
SESSION_NAME = "pixiself_session"

if not os.path.exists(f"{SESSION_NAME}.session"):
    print("❌ فایل session پیدا نشد. لطفاً اول روی کامپیوتر یا Colab لاگین کن "
          "و فایل pixiself_session.session رو توی ریپو بذار.")
    sys.exit(1)

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

clock_enabled = False  # وضعیت ساعت

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
# تعطیلات و تقویم
# ============================
def make_holidays_image(holidays, out_path="calendar.png"):
    fig, ax = plt.subplots(figsize=(8, 10))
    ax.axis('off')
    ax.set_title("📌 مناسبت‌های ۱۰ روز آینده", fontsize=16, fontweight="bold")

    text = "\n".join([f"{i+1}. {h}" for i, h in enumerate(holidays)])
    ax.text(0.05, 0.95, text, fontsize=12, va="top", ha="left", wrap=True)

    plt.savefig(out_path, bbox_inches="tight", dpi=200)
    plt.close()

def get_holidays(days=7):
    today = jdatetime.date.today()
    holidays = []
    for i in range(days):
        d = today + jdatetime.timedelta(days=i)
        url = f"{HOLIDAY_API}{d.year}/{d.month}/{d.day}"
        try:
            res = requests.get(url).json()
            if "events" in res and res["events"]:
                holidays.append(f"{d.strftime('%Y/%m/%d')} → {', '.join(res['events'])}")
        except Exception:
            continue
    return holidays if holidays else ["هیچ تعطیلی یا مناسبتی در این بازه نیست."]

@client.on(events.NewMessage(pattern="^(تاریخ|تقویم)$"))
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

    holidays = get_holidays(10)
    make_holidays_image(holidays, out_path="calendar.png")

    caption = (
        f"⏰ ساعت: {datetime.now().strftime('%H:%M')}\n"
        f"📅 تاریخ شمسی: {today_jalali.strftime('%A %d %B %Y')}\n"
        f"📅 تاریخ قمری: {today_hijri}\n"
        f"📅 تاریخ میلادی: {today_gregorian.strftime('%A %d %B %Y')}\n\n"
        f"📊 روزهای سپری شده: {days_passed} ({percent:.2f}%)\n"
        f"📊 روزهای باقی‌مانده: {days_left} ({100 - percent:.2f}%)"
    )

    await event.reply(file="calendar.png", message=caption)

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
