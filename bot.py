from telethon.tl.functions.account import UpdateProfileRequest
import os
from datetime import datetime, timedelta
import requests
import jdatetime
import calendar
import matplotlib.pyplot as plt
import matplotlib
import pytz
import sys
from telethon import TelegramClient, events
import time
import asyncio

# تنظیمات فونت فارسی برای matplotlib
matplotlib.rcParams['font.family'] = 'DejaVu Sans'

# گرفتن API_ID و API_HASH از Environment Variables
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")

# توکن API تعطیلات
HOLIDAY_API = "https://holidayapi.ir/jalali/"

# تعریف timezone تهران
tehran_tz = pytz.timezone("Asia/Tehran")

# نام فایل session
SESSION_NAME = "pixiself_session"

if not os.path.exists(f"{SESSION_NAME}.session"):
    print("❌ فایل session پیدا نشد. لطفاً اول روی کامپیوتر یا Colab لاگین کن "
          "و فایل pixiself_session.session رو توی ریپو بذار.")
    sys.exit(1)

client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

# وضعیت ساعت (فعال/غیرفعال)
clock_enabled = False

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
        await asyncio.sleep(60)  # هر ۶۰ ثانیه

# هندلر تستی
@client.on(events.NewMessage(pattern="سلام"))
async def handler(event):
    if not event.is_private:
        return
    
    if event.out:
        return
    
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
    
    days_fa = {
    "Saturday": "شنبه",
    "Sunday": "یک‌شنبه",
    "Monday": "دوشنبه",
    "Tuesday": "سه‌شنبه",
    "Wednesday": "چهارشنبه",
    "Thursday": "پنج‌شنبه",
    "Friday": "جمعه",
    }

    now = datetime.now(tehran_tz).strftime("%H:%M")
    weekday = datetime.now(tehran_tz).strftime("%A")
    date = jdatetime.date.today().strftime("%Y/%m/%d")
    weekday_fa = days_fa[weekday]

    await event.reply(
        f"⏰ ساعت به وقت ایران: **{now}**\n"
        f"📅 امروز **{weekday_fa}** هست\n"
        f"📌 تاریخ: **{date}**", parse_mode = "markdown"
    )

# فعال/غیرفعال کردن ساعت با دستور "ساعت پروفایل"
@client.on(events.NewMessage(pattern="ساعت پروفایل"))
async def toggle_clock(event):
    global clock_enabled
    
    if not event.out:
        return
        
    if clock_enabled:
        clock_enabled = False
        # پاک کردن last name
        await client(UpdateProfileRequest(last_name=""))
        await event.reply("❌ ساعت غیرفعال شد")
    else:
        clock_enabled = True
        await event.reply("⏰ ساعت فعال شد")


def make_calendar_image(year, month):
    cal = calendar.monthcalendar(year, month)
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.axis('off')
    ax.set_title(f"📅 {year}/{month}", fontsize=18, fontweight="bold")

    table = ax.table(
        cellText=cal,
        colLabels=["د", "س", "چ", "پ", "ج", "ش", "ی"],
        loc='center',
        cellLoc='center'
    )
    table.scale(1, 2)
    plt.savefig("calendar.png")
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
                holidays.append(f"{d} → {', '.join(res['events'])}")
        except Exception:
            continue

    return holidays if holidays else ["هیچ تعطیلی یا مناسبتی در ۷ روز آینده نیست."]

# هندلر برای تاریخ/تقویم
@client.on(events.NewMessage(pattern="^(تاریخ|تقویم)$"))
async def send_calendar(event):
    if not event.out:  # فقط پیام‌های خودت
        return

    # تاریخ امروز
    today_jalali = jdatetime.date.today()
    today_gregorian = datetime.today().date()

    # گرفتن مناسبت‌ها
    holidays = get_holidays(7)

    # ساخت عکس تقویم
    make_calendar_image(today_jalali.year, today_jalali.month)

    # متن نهایی
    text = (
        f"📌 امروز: {today_jalali.strftime('%A %d %B %Y')} (شمسی)\n"
        f"📌 معادل میلادی: {today_gregorian.strftime('%A %d %B %Y')}\n\n"
        f"📅 مناسبت‌ها و تعطیلات ۷ روز آینده:\n" +
        "\n".join(holidays)
    )

    await client.send_file("me", "calendar.png", caption=text)



async def main():
    me = await client.get_me()
    print(f"✅ لاگین شدی به عنوان: {getattr(me, 'username', me.id)}")

    # پیام خوشامد توی Saved Messages
    await client.send_message("me", "KishMish آماده به کار هستش ✅")

    # اجرای ساعت در بک‌گراند
    client.loop.create_task(clock_updater())

    # منتظر بودن برای پیام‌ها
    await client.run_until_disconnected()

if __name__ == "__main__":
    print("🚀 در حال اجرا ...")
    with client:
        client.loop.run_until_complete(main())

