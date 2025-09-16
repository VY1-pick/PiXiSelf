import os
import sys
from telethon import TelegramClient, events

# گرفتن API_ID و API_HASH از Environment Variables
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")

# نام فایل session
SESSION_NAME = "pixiself_session"

if not os.path.exists(f"{SESSION_NAME}.session"):
    print("❌ فایل session پیدا نشد. لطفاً اول روی کامپیوتر یا Colab لاگین کن "
          "و فایل pixiself_session.session رو توی ریپو بذار.")
    sys.exit(1)

# ساخت کلاینت بدون پروکسی
client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

# مثال ساده از هندلر
@client.on(events.NewMessage(pattern="سلام"))
async def handler(event):
    await event.reply("سلام از Render 👋 (بدون پروکسی)")

async def main():
    me = await client.get_me()
    print(f"✅ لاگین شدی به عنوان: {getattr(me, 'username', me.id)}")
    await client.send_message("me", "بوت روی Render بالا اومد ✅ (بدون پروکسی)")
    await client.run_until_disconnected()

if __name__ == "__main__":
    print("🚀 در حال اجرا (بدون پروکسی)...")
    with client:
        client.loop.run_until_complete(main())
