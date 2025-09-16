from telethon import TelegramClient

api_id = 1457734
api_hash = 'a2f5892fd700d1c4d46676b771ebe02e'

client = TelegramClient('self', api_id, api_hash)

async def main():
    me = await client.get_me()
    print(me.stringify())

    # ارسال پیام تستی به خودت
    await client.send_message('me', 'سلام از PiXiSelf آماده به کار میباشد 👋')

with client:
    client.loop.run_until_complete(main())