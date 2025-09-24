# telegram_war_game_bot.py
# Python 3.11+
import os
import asyncio
from typing import Optional, Tuple

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# DB drivers
import asyncpg

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

if not BOT_TOKEN or not DATABASE_URL:
    raise RuntimeError("BOT_TOKEN and DATABASE_URL environment variables are required")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ------------------ DB adapter ------------------
class DBAdapter:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self._pg_pool: Optional[asyncpg.Pool] = None

    async def init(self):
        self._pg_pool = await asyncpg.create_pool(dsn=self.database_url, min_size=1, max_size=10)

    async def execute(self, sql: str, params: Tuple = ()):
        async with self._pg_pool.acquire() as conn:
            await conn.execute(sql, *params)

    async def fetchone(self, sql: str, params: Tuple = ()):
        async with self._pg_pool.acquire() as conn:
            row = await conn.fetchrow(sql, *params)
            return tuple(row) if row is not None else None

    async def fetchval(self, sql: str, params: Tuple = ()):
        async with self._pg_pool.acquire() as conn:
            return await conn.fetchval(sql, *params)

db = DBAdapter(DATABASE_URL)

# ------------------ DB init ------------------
async def init_db():
    await db.init()
    await db.execute("""
    CREATE TABLE IF NOT EXISTS groups (
        chat_id BIGINT PRIMARY KEY,
        title TEXT,
        username TEXT
    )
    """)
    await db.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        money_amount DOUBLE PRECISION DEFAULT 100.0,
        money_currency TEXT DEFAULT 'USD',
        oil_amount DOUBLE PRECISION DEFAULT 100.0,
        level INTEGER DEFAULT 1,
        has_initial_rig INTEGER DEFAULT 0
    )
    """)
    await db.execute("""
    CREATE TABLE IF NOT EXISTS oil_rigs (
        id SERIAL PRIMARY KEY,
        owner_id BIGINT,
        level INTEGER,
        hp INTEGER,
        capacity INTEGER,
        extraction_speed DOUBLE PRECISION,
        invulnerable INTEGER DEFAULT 0
    )
    """)

# ------------------ Helpers ------------------
async def ensure_user(user: types.User) -> bool:
    row = await db.fetchone("SELECT has_initial_rig FROM users WHERE user_id=$1", (user.id,))
    if row is None:
        await db.execute(
            "INSERT INTO users(user_id, username, first_name, last_name, money_amount, money_currency, oil_amount, level, has_initial_rig) "
            "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)",
            (user.id, user.username or "", user.first_name or "", user.last_name or "", 100.0, "USD", 100.0, 1, 1)
        )
        await db.execute(
            "INSERT INTO oil_rigs(owner_id, level, hp, capacity, extraction_speed, invulnerable) VALUES($1,$2,$3,$4,$5,$6)",
            (user.id, 1, 1000, 100, 1.0, 1)
        )
        return True
    return False

async def get_user_inventory(user_id: int) -> Optional[str]:
    user = await db.fetchone("SELECT money_amount, money_currency, oil_amount, level FROM users WHERE user_id=$1", (user_id,))
    if not user:
        return None
    money, currency, oil, level = user
    bar = "█" * level + "░" * (10 - level)
    rigs = await db.fetchone("SELECT COUNT(*), MIN(level), MAX(level) FROM oil_rigs WHERE owner_id=$1", (user_id,))
    rigs_count, rigs_min, rigs_max = rigs or (0, None, None)
    return (
        f"💰 پول: {money} {currency}\n"
        f"🛢️ نفت: {oil}\n"
        f"🏗️ دکل‌ها: {rigs_count} (سطح {rigs_min} تا {rigs_max})\n"
        f"🎖️ سطح: {level}\n"
        f"✨ پیشرفت سطح: [{bar}]"
    )

async def is_bot_admin(chat_id: int) -> bool:
    me = await bot.get_me()
    member = await bot.get_chat_member(chat_id, me.id)
    return member.status in ("administrator", "creator")

async def get_common_groups(user_id: int) -> list[Tuple[int, str]]:
    rows = await db._pg_pool.fetch("SELECT chat_id, title FROM groups")
    return [(r["chat_id"], r["title"]) for r in rows]  # ساده، همه گروه‌ها را نشان می‌دهد

# ------------------ Handlers ------------------
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await ensure_user(message.from_user)
    username = message.from_user.username or message.from_user.first_name
    # بررسی گروه مشترک
    groups = await get_common_groups(message.from_user.id)
    if not groups:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ انجام شد فرمانده", callback_data="done_add_group")]
        ])
        await message.answer(f"فرمانده: سرباز {username}، می‌بینم که هنوز ربات رو به گروهت اضافه نکردی 😡", reply_markup=kb)
        return
    # اگر گروه مشترک هست مستقیم پنل نشان بده
    await show_panel(message, username, None)

@dp.callback_query(lambda cb: cb.data == "done_add_group")
async def done_add_group(cb: types.CallbackQuery):
    username = cb.from_user.username or cb.from_user.first_name
    groups = await get_common_groups(cb.from_user.id)
    if not groups:
        await cb.message.answer(f"فرمانده: سرباز {username}، گروه مشترک پیدا نشد! مطمئن شو که ربات در گروه اضافه شده است ⚠️")
        return
    # لیست گروه‌ها
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=title, callback_data=f"group_{chat_id}")] for chat_id, title in groups
    ])
    await cb.message.answer(f"فرمانده: سرباز {username}، انتخاب کن در کدام گروه پروفایلت فعال شود. فرمانده مراقب توست 👀", reply_markup=kb)

@dp.callback_query(lambda cb: cb.data.startswith("group_"))
async def select_group(cb: types.CallbackQuery):
    chat_id = int(cb.data.split("_")[1])
    username = cb.from_user.username or cb.from_user.first_name
    await show_panel(cb.message, username, chat_id)

@dp.message(Command("panel"))
async def cmd_panel(message: types.Message):
    username = message.from_user.username or message.from_user.first_name
    await show_panel(message, username, None)

# ------------------ Panel ------------------
async def show_panel(message: types.Message, username: str, chat_id: Optional[int]):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 موجودی", callback_data="inventory")],
        [InlineKeyboardButton(text="🛒 فروشگاه", callback_data="shop"),
         InlineKeyboardButton(text="💱 تبادل", callback_data="exchange")],
        [InlineKeyboardButton(text="🏗️ دکل‌ها", callback_data="rigs"),
         InlineKeyboardButton(text="🛩️ آشیانه‌ها", callback_data="hangars")],
        [InlineKeyboardButton(text="🌍 گروه سراری", callback_data="guilds")]
    ])
    await message.answer(f"فرمانده: سرباز {username}، پنل وضعیتت آماده است. دقت کن هر حرکتت ثبت می‌شود ⚔️", reply_markup=kb)

@dp.callback_query(lambda cb: cb.data == "inventory")
async def callback_inventory(cb: types.CallbackQuery):
    data = await get_user_inventory(cb.from_user.id)
    if data:
        await cb.message.edit_text(f"فرمانده: {cb.from_user.username}, موجودی شما:\n\n{data}", reply_markup=cb.message.reply_markup)
    else:
        await cb.message.answer(f"فرمانده: سرباز {cb.from_user.username}، شما هنوز وارد بازی نشده‌اید. لطفاً /start بزنید.")

@dp.callback_query(lambda cb: cb.data in ("shop","exchange","rigs","hangars","guilds"))
async def callback_other(cb: types.CallbackQuery):
    await cb.answer(f"💡 بخش {cb.data} هنوز در دست ساخت است.", show_alert=True)

# ------------------ bootstrap ------------------
async def main():
    await init_db()
    print("DB initialized.")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        if db._pg_pool:
            await db._pg_pool.close()

if __name__ == "__main__":
    asyncio.run(main())
