# telegram_war_game_bot.py
# Python 3.11+
import os
import asyncio
from typing import Optional, Tuple, Any

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# DB drivers
import aiosqlite
import asyncpg

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required")

# DATABASE_URL examples:
# - sqlite (default): sqlite:///game.db
# - postgres: postgres://user:pass@host:port/dbname
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
        if self._mode == "sqlite":
            # nothing to init besides ensuring path exists at connect time
            pass
        else:
            # create pg pool
            self._pg_pool = await asyncpg.create_pool(dsn=self.database_url, min_size=1, max_size=10)

    def _sqlite_path(self) -> str:
        # DATABASE_URL like sqlite:///game.db or sqlite:////absolute/path/to/game.db
        parts = self.database_url.split("://", 1)
        path = parts[1] if len(parts) > 1 else "game.db"
        # for typical sqlite:///game.db -> path starts with /game.db, remove leading slash
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

# ------------------ DB init (tables) ------------------
async def init_db():
    await db.init()
    # Create tables compatible with both SQLite and Postgres
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
        invulnerable INTEGER DEFAULT 0,
        FOREIGN KEY(owner_id) REFERENCES users(user_id) ON DELETE CASCADE
    )
    """)

# ------------------ helpers ------------------
async def ensure_user(user: types.User) -> bool:
    """Return True if new user created (and initial rig given)."""
    if db._mode == "postgres":
        row = await db.fetchone("SELECT has_initial_rig FROM users WHERE user_id = $1", (user.id,))
    else:
        row = await db.fetchone("SELECT has_initial_rig FROM users WHERE user_id = ?", (user.id,))
    if row is None:
        currency = "USD"
        if db._mode == "postgres":
            await db.execute(
                "INSERT INTO users(user_id, username, first_name, last_name, money_amount, money_currency, oil_amount, level, has_initial_rig) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)",
                (user.id, user.username or "", user.first_name or "", user.last_name or "", 100.0, currency, 100.0, 1, 1)
            )
            await db.execute(
                "INSERT INTO oil_rigs(owner_id, level, hp, capacity, extraction_speed, invulnerable) VALUES($1,$2,$3,$4,$5,$6)",
                (user.id, 1, 1000, 100, 1.0, 1)
            )
        else:
            await db.execute(
                "INSERT INTO users(user_id, username, first_name, last_name, money_amount, money_currency, oil_amount, level, has_initial_rig) VALUES(?,?,?,?,?,?,?,?,?)",
                (user.id, user.username or "", user.first_name or "", user.last_name or "", 100.0, currency, 100.0, 1, 1)
            )
            await db.execute(
                "INSERT INTO oil_rigs(owner_id, level, hp, capacity, extraction_speed, invulnerable) VALUES(?,?,?,?,?,?)",
                (user.id, 1, 1000, 100, 1.0, 1)
            )
        return True
    else:
        return False

async def bot_groups_exist() -> bool:
    cnt = await db.fetchval("SELECT COUNT(*) FROM groups")
    return (cnt or 0) > 0

# ------------------ Handlers ------------------
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    me = await bot.get_me()
    bot_username = me.username or "YOUR_BOT_USERNAME"

    game_summary = (
        "🎮 خوش اومدی به بازی استراتژی-اکشن گروهی!\n\n"
        "📌 توضیح کوتاه:\n"
        "- هر بازیکن یک کشور انتخاب می‌کند (اسم کشور قابل تغییر).\n"
        "- تجهیزات اولیه: جنگنده و موشک (برای بتا). همه قدرت‌ها یکسان اما نام‌ها متفاوتند.\n"
        "- منابع: پول و نفت (بعداً طلا/الماس اضافه میشه).\n"
        "- پول بر اساس ارز کشور نمایش داده میشه — اما مقدار پایه برابر است.\n"
        "- هر بازیکن در شروع یک دکل نفت سطح ۱ **غیرقابل تخریب** دریافت می‌کند.\n\n"
        "برای تجربه گروهی: لطفاً ربات را به یک گروه اضافه کنید و بازی را از آنجا ادامه دهید."
    )

    if message.chat.type == types.ChatType.PRIVATE:
        is_new = await ensure_user(message.from_user)
        groups_exist = await bot_groups_exist()
        if not groups_exist:
            add_link = f"https://t.me/{bot_username}?startgroup=true"
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="اضافه کردن ربات به گروه ➕", url=add_link)],
                [InlineKeyboardButton(text="راهنمای سریع", callback_data="help_quick")]
            ])
            await message.answer(
                "سلام! من ربات بازی گروهی هستم. برای اجرای بازی در گروه‌ها، لطفاً من را به یک گروه اضافه کنید.\n\n"
                "وقتی ربات به گروه اضافه شد، سیستم به شما دکل نفت سطح ۱ غیرقابل تخریب می‌دهد (اگر هنوز نگرفته باشید).",
                reply_markup=kb
            )
        else:
            if is_new:
                await message.answer(game_summary + "\n\n✅ شما اکنون یک دکل نفت سطح ۱ (غیرقابل تخریب) دریافت کرده‌اید — موفق باشید!")
            else:
                await message.answer(game_summary + "\n\n🔔 شما قبلاً به بازی معرفی شده‌اید. اگر می‌خواهید بازی را از گروه شروع کنید، ربات را به گروه اضافه کنید یا داخل گروه فرمان‌ها را اجرا کنید.")
    else:
        await message.reply("ربات بازی فعال شد — اینجا بازی گروهی اجرا می‌شود. هر کاربر با /start در خصوصی می‌تواند خلاصه و دکل شروع را دریافت کند.")

@dp.my_chat_member()
async def my_chat_member_updated(event: types.ChatMemberUpdated):
    chat = event.chat
    new_status = event.new_chat_member.status
    if db._mode == "postgres":
        if new_status in ("member","administrator","creator"):
            await db.execute(
                "INSERT INTO groups(chat_id, title, username) VALUES($1,$2,$3) ON CONFLICT (chat_id) DO UPDATE SET title = $2, username = $3",
                (chat.id, chat.title or "", chat.username or "")
            )
        else:
            await db.execute("DELETE FROM groups WHERE chat_id = $1", (chat.id,))
    else:
        if new_status in ("member","administrator","creator"):
            await db.execute("INSERT OR REPLACE INTO groups(chat_id, title, username) VALUES(?,?,?)", (chat.id, chat.title or "", chat.username or ""))
        else:
            await db.execute("DELETE FROM groups WHERE chat_id = ?", (chat.id,))

@dp.callback_query(lambda c: c.data == "help_quick")
async def _help_quick(cb: types.CallbackQuery):
    await cb.message.answer(
        "راهنمای سریع:\n"
        "1. ربات را با دکمه «اضافه کردن ربات به گروه» به گروه اضافه کنید.\n"
        "2. بعد از اضافه شدن ربات، در گروه از دستورالعمل‌های بازی استفاده خواهد شد.\n"
        "3. بازیکنان برای شروع باید در چت خصوصی /start را بزنند تا دکل و پروفایل‌شان ساخته شود.\n\n"
        "من آماده‌ام که بخش‌های بعدی (خرید جنگنده/موشک، حمله، سوالات تصادفی، ماموریت‌ها و غیره) را با هم پیاده‌سازی کنیم."
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
