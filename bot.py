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

days_fa = {
    "Saturday": "شنبه",
    "Sunday": "یک‌شنبه",
    "Monday": "دوشنبه",
    "Tuesday": "سه‌شنبه",
    "Wednesday": "چهارشنبه",
    "Thursday": "پنج‌شنبه",
    "Friday": "جمعه",
    }

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

def make_calendar_image_gregorian(year, month, out_path="calendar.png"):
    tz = ZoneInfo("Asia/Tehran")
    now = datetime.now(tz)

    cal = calendar.monthcalendar(year, month)

    fig, ax = plt.subplots(figsize=(10, 7))
    ax.set_facecolor("#f0f8ff")  # بک‌گراند ملایم
    ax.axis('off')

    # عنوان ماه/سال
    month_name = calendar.month_name[month]
    ax.set_title(
        f"{month_name} {year}",
        fontsize=20,
        fontweight="bold",
        color="#333333",
        pad=20
    )

    # ساخت جدول
    table = ax.table(
        cellText=cal,
        colLabels=["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"],
        loc='center',
        cellLoc='center'
    )
    table.scale(1.2, 1.5)

    # استایل جدول
    for key, cell in table.get_celld().items():
        cell.set_edgecolor("#999999")
        cell.set_linewidth(0.5)
        cell.set_fontsize(12)

        # رنگ جمعه (ستون آخر)
        if key[0] > 0 and key[1] == 6:
            cell.set_facecolor("#ffe6e6")  # قرمز ملایم

        # رنگ امروز
        if key[0] > 0 and cal[key[0]-1][key[1]] == now.day and month == now.month and year == now.year:
            cell.set_facecolor("#c6f6c6")  # سبز ملایم
            cell.set_text_props(fontweight="bold", color="black")

    # استایل هدر ستون‌ها
    for i in range(7):
        table[(0, i)].set_facecolor("#dbeafe")  # آبی روشن
        table[(0, i)].set_fontsize(12)
        table[(0, i)].set_fontweight("bold")

    plt.savefig(out_path, bbox_inches="tight", dpi=200)
    plt.close()

def get_holidays_next_days(days=7):
    tz = ZoneInfo("Asia/Tehran")
    now = datetime.now(tz)
    results = []

    for i in range(days):
        d = now + timedelta(days=i)
        jd = jdatetime.date.fromgregorian(date=d)
        url = f"https://holidayapi.ir/jalali/{jd.year}/{jd.month}/{jd.day}"
        try:
            res = requests.get(url, timeout=6).json()
        except Exception:
            results.append((jd, d, False, []))
            continue

        is_holiday = res.get("is_holiday", False)
        events = []
        for ev in res.get("events", []):
            # اگر event به صورت dict باشه یا str، سعی می‌کنیم متنش رو بگیریم
            if isinstance(ev, dict):
                events.append(ev.get("description") or ev.get("title") or str(ev))
            else:
                events.append(str(ev))
        results.append((jd, d, is_holiday, events))
    return results

# هندلر برای تاریخ/تقویم
@client.on(events.NewMessage(pattern=r"^(تاریخ|تقویم)$"))
async def send_calendar(event):
    # فقط وقتی خودت فرستادی اجرا کن
    if not event.out:
        return

    tz = ZoneInfo("Asia/Tehran")
    now = datetime.now(tz)
    # تاریخ شمسی امروز
    jtoday = jdatetime.date.fromgregorian(date=now)
    jalali_str = jtoday.strftime("%Y/%m/%d")        # عددی شمسی
    gregorian_str = now.strftime("%Y/%m/%d")        # عددی میلادی
    weekday_fa = days_fa.get(now.strftime("%A"), now.strftime("%A"))

    # مناسبت‌ها/تعطیلات 7 روز آینده
    items = get_holidays_next_days(7)
    lines = []
    for jd, gd, is_hol, evs in items:
        day_label = f"{jd.strftime('%Y/%m/%d')} (معادل {gd.strftime('%Y/%m/%d')})"
        status = "🔴 تعطیل" if is_hol else "—"
        if evs:
            lines.append(f"• {day_label}: {status} — {'; '.join(evs)}")
        else:
            lines.append(f"• {day_label}: {status}")

    if not lines:
        lines_text = "هیچ مناسبت یا تعطیلی در ۷ روز آینده ثبت نشده."
    else:
        lines_text = "\n".join(lines)

    # ساخت عکس تقویم میلادی (ماه جاری) — همین که قبلاً می‌پسندیدی
    make_calendar_image_gregorian(now.year, now.month, out_path="calendar.png")

    # کپشن فارسی (این رو توی کپشن عکس می‌فرستیم)
    caption = (
        f"📌 امروز (شمسی): {jalali_str} — {weekday_fa}\n"
        f"📌 معادل میلادی: {gregorian_str}\n\n"
        f"📅 مناسبت‌ها و تعطیلات ۷ روز آینده:\n{lines_text}"
    )

    # ارسال به Saved Messages (یا می‌تونی event.reply کنی)
    await client.send_file("me", "calendar.png", caption=caption)



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







