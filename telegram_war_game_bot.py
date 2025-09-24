# telegram_war_game_bot.py
# Python 3.11+
import os
import asyncio
from typing import Optional, Tuple

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton

# DB drivers
import aiosqlite
import asyncpg

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///game.db")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ------------------ DB adapter ------------------
class DBAdapter:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self._mode = "sqlite" if database_url.startswith("sqlite") else "postgres"
        self._pg_pool: Optional[asyncpg.Pool] = None

    async def init(self):
        if self._mode == "postgres":
            self._pg_pool = await asyncpg.create_pool(dsn=self.database_url, min_size=1, max_size=10)

    def _sqlite_path(self) -> str:
        parts = self.database_url.split("://", 1)
        path = parts[1] if len(parts) > 1 else "game.db"
        if path.startswith("/") and not self.database_url.startswith("sqlite:////"):
            path = path[1:]
        return path

    async def execute(self, sql: str, params: Tuple = ()):
        if self._mode == "sqlite":
            async with aiosqlite.connect(self._sqlite_path()) as db:
                await db.execute(sql, params)
                await db.commit()
        else:
            async with self._pg_pool.acquire() as conn:
                await conn.execute(sql, *params)

    async def fetchone(self, sql: str, params: Tuple = ()):
        if self._mode == "sqlite":
            async with aiosqlite.connect(self._sqlite_path()) as db:
                cur = await db.execute(sql, params)
                row = await cur.fetchone()
                return row
        else:
            async with self._pg_pool.acquire() as conn:
                row = await conn.fetchrow(sql, *params)
                return tuple(row) if row is not None else None

    async def fetchval(self, sql: str, params: Tuple = ()):
        if self._mode == "sqlite":
            async with aiosqlite.connect(self._sqlite_path()) as db:
                cur = await db.execute(sql, params)
                row = await cur.fetchone()
                return row[0] if row else None
        else:
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
    """Return True if new user created (and initial rig given)."""
    if db._mode == "postgres":
        row = await db.fetchone("SELECT has_initial_rig FROM users WHERE user_id = $1", (user.id,))
    else:
        row = await db.fetchone("SELECT has_initial_rig FROM users WHERE user_id = ?", (user.id,))
    if row is None:
        if db._mode == "postgres":
            await db.execute(
                "INSERT INTO users(user_id, username, first_name, last_name, money_amount, money_currency, oil_amount, level, has_initial_rig) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)",
                (user.id, user.username or "", user.first_name or "", user.last_name or "", 100.0, "USD", 100.0, 1, 1)
            )
            await db.execute(
                "INSERT INTO oil_rigs(owner_id, level, hp, capacity, extraction_speed, invulnerable) VALUES($1,$2,$3,$4,$5,$6)",
                (user.id, 1, 1000, 100, 1.0, 1)
            )
        else:
            await db.execute(
                "INSERT INTO users(user_id, username, first_name, last_name, money_amount, money_currency, oil_amount, level, has_initial_rig) VALUES(?,?,?,?,?,?,?,?,?)",
                (user.id, user.username or "", user.first_name or "", user.last_name or "", 100.0, "USD", 100.0, 1, 1)
            )
            await db.execute(
                "INSERT INTO oil_rigs(owner_id, level, hp, capacity, extraction_speed, invulnerable) VALUES(?,?,?,?,?,?)",
                (user.id, 1, 1000, 100, 1.0, 1)
            )
        return True
    return False

async def bot_groups_exist() -> bool:
    cnt = await db.fetchval("SELECT COUNT(*) FROM groups")
    return (cnt or 0) > 0

async def is_bot_admin(chat_id: int) -> bool:
    me = await bot.get_me()
    member = await bot.get_chat_member(chat_id, me.id)
    return member.status in ("administrator", "creator")

async def get_user_inventory(user_id: int) -> Optional[str]:
    if db._mode == "postgres":
        user = await db.fetchone("SELECT money_amount, money_currency, oil_amount, level FROM users WHERE user_id=$1", (user_id,))
    else:
        user = await db.fetchone("SELECT money_amount, money_currency, oil_amount, level FROM users WHERE user_id=?", (user_id,))
    if not user:
        return None
    
    money, currency, oil, level = user
    if db._mode == "postgres":
        rigs = await db.fetchone("SELECT COUNT(*), MIN(level), MAX(level) FROM oil_rigs WHERE owner_id=$1", (user_id,))
    else:
        rigs = await db.fetchone("SELECT COUNT(*), MIN(level), MAX(level) FROM oil_rigs WHERE owner_id=?", (user_id,))
    
    rigs_count, rigs_min, rigs_max = rigs or (0, None, None)
    return (
        f"💰 پول: {money} {currency}\n"
        f"🛢️ نفت: {oil}\n"
        f"🏗️ دکل‌ها: {rigs_count} (سطح {rigs_min} تا {rigs_max})\n"
        f"🛩️ جنگنده‌ها: 0 (فعلاً)\n"
        f"🎖️ سطح بازیکن: {level}"
    )

# ------------------ Handlers ------------------
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    me = await bot.get_me()
    bot_username = me.username or "YOUR_BOT_USERNAME"

    game_summary = (
        "🎮 خوش اومدی به بازی استراتژی-اکشن گروهی!\n\n"
        "📌 توضیح کوتاه:\n"
        "- هر بازیکن یک کشور انتخاب می‌کند (اسم کشور قابل تغییر).\n"
        "- تجهیزات اولیه: جنگنده و موشک (برای بتا).\n"
        "- منابع: پول و نفت.\n"
        "- هر بازیکن یک دکل نفت سطح ۱ **غیرقابل تخریب** دریافت می‌کند.\n\n"
        "برای تجربه گروهی: لطفاً ربات را به یک گروه اضافه کنید."
    )

    if message.chat.type == "private":
        is_new = await ensure_user(message.from_user)
        groups_exist = await bot_groups_exist()
        if not groups_exist:
            add_link = f"https://t.me/{bot_username}?startgroup=true"
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ اضافه کردن ربات به گروه", url=add_link)],
                [InlineKeyboardButton(text="📖 راهنمای سریع", callback_data="help_quick")]
            ])
            await message.answer(
                "سلام! برای اجرای بازی در گروه‌ها، ربات را به یک گروه اضافه کنید.\n\n"
                "وقتی اضافه شد، شما یک دکل نفت سطح ۱ غیرقابل تخریب خواهید داشت.",
                reply_markup=kb
            )
        else:
            if is_new:
                await message.answer(game_summary + "\n\n✅ شما یک دکل نفت سطح ۱ (غیرقابل تخریب) دریافت کردید!")
            else:
                await message.answer(game_summary + "\n\n🔔 شما قبلاً ثبت‌نام کرده‌اید.")
    else:
        await message.reply("✅ ربات در این گروه فعال شد.")

# پنل کاربری
@dp.message(Command("panel"))
async def panel_cmd(message: types.Message):
    if message.chat.type != "private":
        return
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 موجودی")],
            [KeyboardButton(text="🛒 فروشگاه"), KeyboardButton(text="💱 تبادل")],
            [KeyboardButton(text="🏗️ دکل‌ها"), KeyboardButton(text="🛩️ آشیانه‌ها")],
            [KeyboardButton(text="🌍 گروه سراری")]
        ],
        resize_keyboard=True
    )
    await message.answer("🔧 پنل کاربری:", reply_markup=kb)

# موجودی در پیوی
@dp.message(lambda msg: msg.chat.type == "private" and msg.text == "📊 موجودی")
async def inventory_private(message: types.Message):
    data = await get_user_inventory(message.from_user.id)
    if data:
        await message.answer("📊 موجودی کامل شما:\n\n" + data)
    else:
        await message.answer("❌ شما هنوز وارد بازی نشده‌اید. لطفاً /start بزنید.")

# موجودی در گروه
@dp.message(lambda msg: msg.chat.type in ("group", "supergroup") and msg.text.lower() == "موجودی")
async def inventory_group(message: types.Message):
    if not await is_bot_admin(message.chat.id):
        await message.reply("⚠️ برای استفاده از ربات، باید ربات ادمین گروه باشد.")
        return
    
    data = await get_user_inventory(message.from_user.id)
    if data:
        lines = data.split("\n")
        summary = "\n".join(lines[:2])  # پول و نفت
        await message.reply("📊 موجودی شما:\n" + summary)

@dp.my_chat_member()
async def my_chat_member_updated(event: types.ChatMemberUpdated):
    chat = event.chat
    new_status = event.new_chat_member.status
    if db._mode == "postgres":
        if new_status in ("member","administrator","creator"):
            await db.execute(
                "INSERT INTO groups(chat_id, title, username) VALUES($1,$2,$3) ON CONFLICT (chat_id) DO UPDATE SET title=$2, username=$3",
                (chat.id, chat.title or "", chat.username or "")
            )
        else:
            await db.execute("DELETE FROM groups WHERE chat_id=$1", (chat.id,))
    else:
        if new_status in ("member","administrator","creator"):
            await db.execute("INSERT OR REPLACE INTO groups(chat_id, title, username) VALUES(?,?,?)", (chat.id, chat.title or "", chat.username or ""))
        else:
            await db.execute("DELETE FROM groups WHERE chat_id=?", (chat.id,))

@dp.callback_query(lambda c: c.data == "help_quick")
async def _help_quick(cb: types.CallbackQuery):
    await cb.message.answer(
        "راهنمای سریع:\n"
        "1. ربات را با دکمه «➕ اضافه کردن ربات به گروه» به گروه اضافه کنید.\n"
        "2. بعد از اضافه شدن، بازیکنان باید در خصوصی /start بزنند.\n"
        "3. سپس می‌توانید در گروه با دستورات بازی کنید."
    )
    await cb.answer()

# ------------------ bootstrap ------------------
async def main():
    await init_db()
    print("DB initialized. Mode:", db._mode)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        if db._pg_pool:
            await db._pg_pool.close()

if __name__ == "__main__":
    asyncio.run(main())
