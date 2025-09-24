# telegram_war_game_bot.py
# Python 3.11+
import os
import asyncio
from typing import Optional, Tuple

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

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
        exp INTEGER DEFAULT 0,
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
                "INSERT INTO users(user_id, username, first_name, last_name, money_amount, money_currency, oil_amount, level, exp, has_initial_rig) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
                (user.id, user.username or "", user.first_name or "", user.last_name or "", 100.0, "USD", 100.0, 1, 0, 1)
            )
            await db.execute(
                "INSERT INTO oil_rigs(owner_id, level, hp, capacity, extraction_speed, invulnerable) VALUES($1,$2,$3,$4,$5,$6)",
                (user.id, 1, 1000, 100, 1.0, 1)
            )
        else:
            await db.execute(
                "INSERT INTO users(user_id, username, first_name, last_name, money_amount, money_currency, oil_amount, level, exp, has_initial_rig) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (user.id, user.username or "", user.first_name or "", user.last_name or "", 100.0, "USD", 100.0, 1, 0, 1)
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

def next_level_exp(level: int) -> int:
    """تجربه لازم برای رسیدن به سطح بعدی"""
    return 25 * level ** 2 + 50 * level  # فرمول ساده

def exp_bar(exp: int, next_level: int, size: int = 10) -> str:
    filled = int((exp / next_level) * size)
    empty = size - filled
    return "█" * filled + "░" * empty

async def get_user_inventory(user_id: int) -> Optional[str]:
    if db._mode == "postgres":
        user = await db.fetchone("SELECT money_amount, money_currency, oil_amount, level, exp FROM users WHERE user_id=$1", (user_id,))
    else:
        user = await db.fetchone("SELECT money_amount, money_currency, oil_amount, level, exp FROM users WHERE user_id=?", (user_id,))
    if not user:
        return None
    
    money, currency, oil, level, exp = user
    next_exp_val = next_level_exp(level)
    bar = exp_bar(exp, next_exp_val, size=10)

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
        f"🎖️ سطح: {level}\n"
        f"✨ سطح تجربه: {level} \n[{bar}] ({exp} / {next_exp_val} تجربه)"
    )

# ------------------ Handlers ------------------
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    me = await bot.get_me()
    bot_username = me.username or "YOUR_BOT_USERNAME"

    # بررسی اینکه کاربر جدید هست یا نه
    is_new = await ensure_user(message.from_user)

    # متن خوش آمد
    game_summary = (
        "🎮 خوش اومدی به بازی استراتژی-اکشن گروهی!\n\n"
        "📌 توضیح کوتاه:\n"
        "- هر بازیکن یک کشور انتخاب می‌کند (اسم کشور قابل تغییر).\n"
        "- تجهیزات اولیه: جنگنده و موشک (برای بتا).\n"
        "- منابع: پول و نفت.\n"
        "- هر بازیکن یک دکل نفت سطح ۱ **غیرقابل تخریب** دریافت می‌کند.\n\n"
        "پنل شیشه‌ای شما در ادامه قرار دارد:"
    )

    # ساخت پنل شیشه‌ای InlineKeyboard
    panel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 موجودی", callback_data="inventory")],
        [InlineKeyboardButton(text="🛒 فروشگاه", callback_data="shop"),
         InlineKeyboardButton(text="💱 تبادل", callback_data="exchange")],
        [InlineKeyboardButton(text="🏗️ دکل‌ها", callback_data="rigs"),
         InlineKeyboardButton(text="🛩️ آشیانه‌ها", callback_data="hangars")],
        [InlineKeyboardButton(text="🌍 گروه سراری", callback_data="guilds")]
    ])

    await message.answer(game_summary, reply_markup=panel_kb)

# ------------------ callback handlers ------------------
@dp.callback_query(lambda cb: cb.data == "inventory")
async def callback_inventory(cb: types.CallbackQuery):
    data = await get_user_inventory(cb.from_user.id)
    if data:
        await cb.message.edit_text("📊 موجودی شما:\n\n" + data, reply_markup=cb.message.reply_markup)
    else:
        await cb.message.answer("❌ شما هنوز وارد بازی نشده‌اید. لطفاً /start بزنید.")

@dp.callback_query(lambda cb: cb.data in ("shop","exchange","rigs","hangars","guilds"))
async def callback_other(cb: types.CallbackQuery):
    await cb.answer(f"💡 شما {cb.data} را زدید. این بخش هنوز در دست ساخت است.", show_alert=True)

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
