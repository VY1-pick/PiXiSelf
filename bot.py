from telethon.tl.functions.account import UpdateProfileRequest
import os
from datetime import datetime
import pytz
import sys
from telethon import TelegramClient, events
import time
import asyncio

# گرفتن API_ID و API_HASH از Environment Variables
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")

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
            tehran_tz = pytz.timezone("Asia/Tehran")
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

@client.on(events.NewMessage(pattern="^(ساعت|امروز|تاریخ)$"))
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
    date = datetime.now(tehran_tz).strftime("%Y/%m/%d")
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



async def main():
    me = await client.get_me()
    print(f"✅ لاگین شدی به عنوان: {getattr(me, 'username', me.id)}")

    # پیام خوشامد توی Saved Messages
    await client.send_message("me", "PiXiSelf آماده به کار هستش ✅")

    # اجرای ساعت در بک‌گراند
    client.loop.create_task(clock_updater())

    # منتظر بودن برای پیام‌ها
    await client.run_until_disconnected()

if __name__ == "__main__":
    print("🚀 در حال اجرا ...")
    with client:
        client.loop.run_until_complete(main())













