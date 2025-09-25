# bot.py
import os
import asyncio
import logging
import random
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager

import asyncpg
from aiogram.client.default import DefaultBotProperties
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ChatMemberUpdated
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mini_war_bot")

# ---------- Config ----------
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

if not BOT_TOKEN or not DATABASE_URL:
    raise RuntimeError("BOT_TOKEN and DATABASE_URL environment variables are required")

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)
dp = Dispatcher()

# ---------- Constants / Game Balances ----------
START_MONEY = 100.0
START_OIL = 100.0

MISSILE_PRICE = 20.0
JET_PRICE = 50.0
OIL_SELL_PRICE = 1.0  # per oil unit

JET_OIL_COST = 10.0
MISSILE_OIL_COST = 0.0
JET_DAMAGE = 0.35
MISSILE_DAMAGE = 0.25
VERBAL_REWARD = 5.0
VERBAL_COOLDOWN = 100  # seconds
ATTACK_TARGET_COOLDOWN = 30 * 60  # 30 minutes

QUIZ_INTERVAL_SECONDS = 5 * 60
MISSION_INTERVAL_SECONDS = 7 * 60

COUNTRY_CURRENCIES = {
    "ایران": "تومان",
    "روسیه": "روبل",
    "آمریکا": "دلار",
}
COUNTRIES = ["ایران", "روسیه", "آمریکا"]

# ---------- DB Adapter ----------
class DBAdapter:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool: Optional[asyncpg.pool.Pool] = None

    async def init(self):
        self.pool = await asyncpg.create_pool(dsn=self.dsn, min_size=1, max_size=10)

    async def close(self):
        if self.pool:
            await self.pool.close()
            self.pool = None

    async def execute(self, sql: str, *params):
        if not self.pool:
            raise RuntimeError("DB pool not initialized")
        async with self.pool.acquire() as conn:
            await conn.execute(sql, *params)

    async def fetchrow(self, sql: str, *params):
        if not self.pool:
            raise RuntimeError("DB pool not initialized")
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(sql, *params)
            return dict(row) if row else None

    async def fetch(self, sql: str, *params):
        if not self.pool:
            raise RuntimeError("DB pool not initialized")
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
            return [dict(r) for r in rows]

    @asynccontextmanager
    async def transaction(self):
        """
        Usage:
            async with db.transaction() as conn:
                # use conn.fetchrow / conn.execute (these are asyncpg.Connection methods)
        This context manager starts a transaction, yields a connection, commits on success,
        rollbacks on exception and always releases connection back to pool.
        """
        if not self.pool:
            raise RuntimeError("DB pool not initialized")
        conn = await self.pool.acquire()
        tr = conn.transaction()
        await tr.start()
        try:
            yield conn
            await tr.commit()
        except Exception:
            await tr.rollback()
            raise
        finally:
            await self.pool.release(conn)

db = DBAdapter(DATABASE_URL)

# ---------- FSM ----------
class CountryFSM(StatesGroup):
    waiting_for_country = State()
    waiting_for_rename = State()

# ---------- In-memory tasks ----------
group_challenge_tasks: Dict[int, asyncio.Task] = {}
group_mission_tasks: Dict[int, asyncio.Task] = {}
user_active_group: Dict[int, int] = {}  # user_id -> chat_id

# ---------- DB Init ----------
async def init_db():
    await db.init()

    # users global table
    await db.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        money_amount DOUBLE PRECISION DEFAULT 0.0,
        money_currency TEXT DEFAULT 'USD',
        oil_amount DOUBLE PRECISION DEFAULT 0.0,
        level INTEGER DEFAULT 1,
        experience INTEGER DEFAULT 0,
        has_initial_rig INTEGER DEFAULT 0
    )
    """)

    # oil rigs per user (can have many per user)
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

    # groups (chats)
    await db.execute("""
    CREATE TABLE IF NOT EXISTS groups (
        chat_id BIGINT PRIMARY KEY,
        title TEXT,
        username TEXT,
        active BOOLEAN DEFAULT TRUE
    )
    """)

    # temp profile while selecting country per chat
    await db.execute("""
    CREATE TABLE IF NOT EXISTS temp_profiles (
        user_id BIGINT,
        chat_id BIGINT,
        country TEXT,
        PRIMARY KEY(user_id, chat_id)
    )
    """)

    # user profiles per group (the main per-group game state)
    await db.execute("""
    CREATE TABLE IF NOT EXISTS user_profiles (
        user_id BIGINT,
        chat_id BIGINT,
        country TEXT,
        oil DOUBLE PRECISION DEFAULT 0.0,
        money DOUBLE PRECISION DEFAULT 0.0,
        missiles INT DEFAULT 0,
        jets INT DEFAULT 0,
        defenses INT DEFAULT 0,
        level INT DEFAULT 1,
        PRIMARY KEY(user_id, chat_id)
    )
    """)

    # store attack cooldowns: per attacker -> per target last attack time
    await db.execute("""
    CREATE TABLE IF NOT EXISTS attack_cooldowns (
        attacker_id BIGINT,
        target_id BIGINT,
        chat_id BIGINT,
        last_attack TIMESTAMP,
        PRIMARY KEY(attacker_id, target_id, chat_id)
    )
    """)

    # verbal attack cooldowns per attacker
    await db.execute("""
    CREATE TABLE IF NOT EXISTS verbal_cooldowns (
        user_id BIGINT PRIMARY KEY,
        last_verbal TIMESTAMP
    )
    """)

    # challenges (quiz questions)
    await db.execute("""
    CREATE TABLE IF NOT EXISTS challenges (
        id SERIAL PRIMARY KEY,
        text TEXT,
        answer TEXT,
        reward_money DOUBLE PRECISION DEFAULT 50.0,
        reward_oil DOUBLE PRECISION DEFAULT 50.0
    )
    """)

    # active group challenge
    await db.execute("""
    CREATE TABLE IF NOT EXISTS group_challenges (
        chat_id BIGINT PRIMARY KEY,
        challenge_id INT,
        message_id BIGINT,
        start_time TIMESTAMP,
        end_time TIMESTAMP,
        active INTEGER DEFAULT 1
    )
    """)

    # missions (definitions)
    await db.execute("""
    CREATE TABLE IF NOT EXISTS missions (
        id SERIAL PRIMARY KEY,
        text TEXT,
        reward_money DOUBLE PRECISION DEFAULT 100.0,
        reward_oil DOUBLE PRECISION DEFAULT 100.0,
        type TEXT DEFAULT 'generic'
    )
    """)

    # group missions state (first complete wins)
    await db.execute("""
    CREATE TABLE IF NOT EXISTS group_missions (
        chat_id BIGINT,
        mission_id INT,
        user_id BIGINT,
        status TEXT DEFAULT 'pending',
        PRIMARY KEY(chat_id, mission_id)
    )
    """)

# ---------- Helpers ----------
async def ensure_user_global(user: types.User):
    row = await db.fetchrow("SELECT user_id FROM users WHERE user_id=$1", user.id)
    if not row:
        await db.execute(
            "INSERT INTO users(user_id, username, first_name, last_name, money_amount, money_currency, oil_amount, level, experience, has_initial_rig) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
            user.id, user.username or "", user.first_name or "", user.last_name or "", START_MONEY, "USD", START_OIL, 1, 0, 1
        )
        # initial invulnerable rig
        await db.execute(
            "INSERT INTO oil_rigs(owner_id, level, hp, capacity, extraction_speed, invulnerable) VALUES($1,$2,$3,$4,$5,$6)",
            user.id, 1, 1000, 100, 1.0, 1
        )

def format_money(amount: float, country: Optional[str] = None) -> str:
    currency = COUNTRY_CURRENCIES.get(country, "USD")
    return f"{amount:.2f} {currency}"

async def get_user_profile(user_id: int, chat_id: int) -> Optional[dict]:
    return await db.fetchrow("SELECT * FROM user_profiles WHERE user_id=$1 AND chat_id=$2", user_id, chat_id)

async def create_default_profile(user_id: int, chat_id: int, country: str):
    await db.execute(
        "INSERT INTO user_profiles(user_id, chat_id, country, oil, money, missiles, jets, defenses, level) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9) "
        "ON CONFLICT (user_id, chat_id) DO NOTHING",
        user_id, chat_id, country, START_OIL, START_MONEY, 0, 0, 0, 1
    )

async def check_bot_admin(chat_id: int, cb_or_msg: Optional[Any] = None) -> bool:
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(chat_id, me.id)
        if member.status not in ("administrator", "creator"):
            if cb_or_msg:
                txt = "⚠️ من ادمین نیستم؛ لطفاً ربات را ادمین کنید تا بازی کار کند."
                if isinstance(cb_or_msg, types.CallbackQuery):
                    await cb_or_msg.answer(txt, show_alert=True)
                else:
                    await cb_or_msg.answer(txt)
            return False
    except Exception:
        logger.exception("check_bot_admin error")
        if cb_or_msg:
            txt = "⚠️ خطا در بررسی دسترسی ربات."
            if isinstance(cb_or_msg, types.CallbackQuery):
                await cb_or_msg.answer(txt, show_alert=True)
            else:
                await cb_or_msg.answer(txt)
        return False
    return True

# ---------- Group utilities ----------
async def add_group_if_missing(chat: types.Chat):
    await db.execute(
        "INSERT INTO groups(chat_id, title, username, active) VALUES($1,$2,$3,$4) ON CONFLICT (chat_id) DO UPDATE SET title=$2, username=$3, active=$4",
        chat.id, chat.title or "", chat.username or "", True
    )

async def start_group_tasks(chat_id: int):
    if chat_id not in group_challenge_tasks:
        group_challenge_tasks[chat_id] = asyncio.create_task(run_group_challenges(chat_id))
    if chat_id not in group_mission_tasks:
        group_mission_tasks[chat_id] = asyncio.create_task(run_group_missions(chat_id))

async def stop_group_tasks(chat_id: int):
    t1 = group_challenge_tasks.pop(chat_id, None)
    if t1:
        t1.cancel()
    t2 = group_mission_tasks.pop(chat_id, None)
    if t2:
        t2.cancel()

# ---------- Handlers: my_chat_member ----------
@dp.my_chat_member()
async def bot_membership_changed(event: ChatMemberUpdated):
    chat_id = event.chat.id
    new_status = event.new_chat_member.status

    if new_status == "member":
        await db.execute(
            "INSERT INTO groups(chat_id, title, username, active) VALUES($1,$2,$3,$4) ON CONFLICT (chat_id) DO UPDATE SET title=$2, username=$3, active=$4",
            chat_id, event.chat.title or "", event.chat.username or "", True
        )
        try:
            await bot.send_message(chat_id, "من به گروه اضافه شدم ✅\nبرای عملکرد کامل، لطفاً منو ادمین کنید ⚔️ (فقط حق ارسال پیام و مدیریت پیام‌ها لازمه).")
        except Exception:
            pass
        await start_group_tasks(chat_id)
    elif new_status in ("administrator", "creator"):
        await db.execute("UPDATE groups SET active=$2 WHERE chat_id=$1", chat_id, True)
        try:
            await bot.send_message(chat_id, "خیلی خب! من الان ادمین شدم — آماده‌ام برای نبرد و کوییزها! 🛡️")
        except Exception:
            pass
        await start_group_tasks(chat_id)
    elif new_status in ("left", "kicked"):
        await db.execute("DELETE FROM groups WHERE chat_id=$1", chat_id)
        await stop_group_tasks(chat_id)
        logger.info(f"Removed group {chat_id} from DB.")

# ---------- Commands: start, panel, select group ----------
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    if message.chat.type != "private":
        return
    await ensure_user_global(message.from_user)
    groups = await db.fetch("SELECT chat_id, title FROM groups WHERE active=TRUE")
    groups_valid = []
    for g in groups:
        gid = g["chat_id"]
        try:
            member = await bot.get_chat_member(gid, message.from_user.id)
            if member.status in ("left", "kicked"):
                continue
            groups_valid.append((gid, g["title"]))
        except Exception:
            continue

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="➕ افزودن به گروه", url=f"https://t.me/{(await bot.get_me()).username}")
    ]])
    txt = f"سلام فرمانده {message.from_user.first_name or ''}!\nمن یک ربات بازی مینی‌جنگم — آماده‌ام تا جهان رو فتح (یا حداقل نفتشو بدزیم) کنیم 😏\nبرای شروع، منو به گروه اضافه کن."
    if groups_valid:
        txt += "\n\n💡 برای باز کردن پنل در هر گروه، ابتدا در آن گروه دستور /panel را ارسال کن یا از اینجا گروه فعال را انتخاب کن."
        kb2 = InlineKeyboardMarkup(inline_keyboard=[])
        for gid, title in groups_valid:
            kb2.add(InlineKeyboardButton(text=f"{title[:30]}", callback_data=f"set_active_group:{gid}"))
        await message.answer(txt, reply_markup=kb)
        await message.answer("گروه‌های مشترک شما:", reply_markup=kb2)
    else:
        await message.answer(txt, reply_markup=kb)

@dp.callback_query(lambda c: c.data and c.data.startswith("set_active_group:"))
async def set_active_group_cb(cq: types.CallbackQuery):
    user_id = cq.from_user.id
    gid = int(cq.data.split(":")[1])
    try:
        member = await bot.get_chat_member(gid, user_id)
        if member.status in ("left", "kicked"):
            await cq.answer("شما دیگر در این گروه نیستید.", show_alert=True)
            return
    except Exception:
        await cq.answer("خطا در بررسی عضویت.", show_alert=True)
        return
    user_active_group[user_id] = gid
    await cq.answer("گروه فعال تنظیم شد ✅")
    try:
        await cq.message.edit_text("گروه فعال شما تنظیم شد. اکنون /panel را در خصوصی یا گروه اجرا کن.")
    except Exception:
        pass

@dp.message(Command("panel"))
async def cmd_panel(message: types.Message):
    if message.chat.type == "private":
        gid = user_active_group.get(message.from_user.id)
        if not gid:
            await message.answer("ابتدا یک گروه فعال انتخاب کن (از /start یا دکمه‌های پیام قبل).")
            return
        chat_id = gid
    else:
        chat_id = message.chat.id

    if not await check_bot_admin(chat_id, message):
        await message.answer("پنل محدود: برای عملکرد کامل، ربات باید ادمین باشد.")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 موجودی من", callback_data="panel_inventory")],
        [InlineKeyboardButton(text="⚒️ ساخت دکل نفت", callback_data="panel_build_rig")],
        [InlineKeyboardButton(text="⚔️ حمله", callback_data="panel_attack")],
        [InlineKeyboardButton(text="🎯 ماموریت‌ها", callback_data="panel_missions")],
        [InlineKeyboardButton(text="❓ کوییز گروهی", callback_data="panel_quiz")],
    ])
    await message.answer("پنل فرماندهی حاضر است. چه عملی می‌خواهی انجام دهی؟", reply_markup=kb)

# ---------- FSM: select country ----------
@dp.message(Command("join"))
async def cmd_join(message: types.Message, state: FSMContext):
    if message.chat.type != "private":
        await message.answer("این دستور در چت خصوصی استفاده می‌شود. ابتدا گروه فعال انتخاب کن.")
        return
    gid = user_active_group.get(message.from_user.id)
    if not gid:
        await message.answer("ابتدا یک گروه فعال انتخاب کن.")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=c, callback_data=f"select_country:{c}")] for c in COUNTRIES])
    await state.set_state(CountryFSM.waiting_for_country)
    await state.update_data(chat_id=gid)
    await message.answer("کشور خود را انتخاب کن 🇺🇳", reply_markup=kb)

@dp.callback_query(lambda c: c.data and c.data.startswith("select_country:"))
async def select_country_cb(cq: types.CallbackQuery, state: FSMContext):
    user_id = cq.from_user.id
    country = cq.data.split(":", 1)[1]
    data = await state.get_data()
    chat_id = data.get("chat_id") or user_active_group.get(user_id)
    if not chat_id:
        await cq.answer("گروه فعال پیدا نشد.", show_alert=True)
        return
    count_row = await db.fetchrow("SELECT COUNT(*)::INT AS c FROM user_profiles WHERE chat_id=$1 AND country=$2", chat_id, country)
    count = count_row["c"] if count_row else 0
    final_country = country if count == 0 else f"{country}{count+1}"
    await create_default_profile(user_id, chat_id, final_country)
    await db.execute("INSERT INTO temp_profiles(user_id, chat_id, country) VALUES($1,$2,$3) ON CONFLICT (user_id, chat_id) DO UPDATE SET country=$3", user_id, chat_id, final_country)
    await ensure_user_global(cq.from_user)
    user_active_group[user_id] = chat_id
    await state.clear()
    await cq.answer(f"کشور «{final_country}» ساخته شد ✅")
    try:
        await bot.send_message(chat_id, f"فرمانده {cq.from_user.first_name} به گروه پیوست با کشور {final_country}! خوش اومدی 👋")
    except Exception:
        pass

# ---------- Profile / Inventory ----------
@dp.callback_query(lambda c: c.data == "panel_inventory")
async def panel_inventory_cb(cq: types.CallbackQuery):
    user_id = cq.from_user.id
    gid = user_active_group.get(user_id)
    if not gid:
        await cq.answer("گروه فعال پیدا نشد.", show_alert=True)
        return
    profile = await get_user_profile(user_id, gid)
    if not profile:
        await cq.answer("پروفایل در گروه پیدا نشد؛ ابتدا با /join کشور انتخاب کن.", show_alert=True)
        return
    txt = (f"📜 پروفایل {cq.from_user.first_name} در گروه:\n"
           f"کشور: {profile['country']}\n"
           f"سطح: {profile['level']}\n"
           f"پول: {format_money(profile['money'], profile['country'])}\n"
           f"نفت: {profile['oil']:.2f} واحد\n"
           f"موشک‌ها: {profile['missiles']}\n"
           f"جنگنده‌ها: {profile['jets']}\n"
           f"دفاع‌ها: {profile['defenses']}\n")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"خرید موشک ({MISSILE_PRICE} USD)", callback_data="buy_missile")],
        [InlineKeyboardButton(text=f"خرید جنگنده ({JET_PRICE} USD)", callback_data="buy_jet")],
        [InlineKeyboardButton(text="فروختن نفت", callback_data="sell_oil")],
    ])
    await cq.answer()
    await cq.message.answer(txt, reply_markup=kb)

@dp.callback_query(lambda c: c.data == "buy_missile")
async def buy_missile_cb(cq: types.CallbackQuery):
    user_id = cq.from_user.id
    gid = user_active_group.get(user_id)
    if not gid:
        await cq.answer("گروه فعال مشخص نیست.", show_alert=True)
        return
    profile = await get_user_profile(user_id, gid)
    if not profile:
        await cq.answer("ابتدا کشور انتخاب کن (/join).", show_alert=True)
        return
    if profile["money"] < MISSILE_PRICE:
        await cq.answer("پول کافی نداری 😢", show_alert=True)
        return
    await db.execute("UPDATE user_profiles SET money=money-$2, missiles=missiles+1 WHERE user_id=$1 AND chat_id=$3", user_id, MISSILE_PRICE, gid)
    await cq.answer("موشک خریدی! بزن بریم 💥")

@dp.callback_query(lambda c: c.data == "buy_jet")
async def buy_jet_cb(cq: types.CallbackQuery):
    user_id = cq.from_user.id
    gid = user_active_group.get(user_id)
    if not gid:
        await cq.answer("گروه فعال مشخص نیست.", show_alert=True)
        return
    profile = await get_user_profile(user_id, gid)
    if not profile:
        await cq.answer("ابتدا کشور انتخاب کن (/join).", show_alert=True)
        return
    if profile["money"] < JET_PRICE:
        await cq.answer("پول کافی نداری 😢", show_alert=True)
        return
    await db.execute("UPDATE user_profiles SET money=money-$2, jets=jets+1 WHERE user_id=$1 AND chat_id=$3", user_id, JET_PRICE, gid)
    await cq.answer("جنگنده خریدی! آسمون مال تو ✈️")

@dp.callback_query(lambda c: c.data == "sell_oil")
async def sell_oil_cb(cq: types.CallbackQuery):
    user_id = cq.from_user.id
    gid = user_active_group.get(user_id)
    if not gid:
        await cq.answer("گروه فعال مشخص نیست.", show_alert=True)
        return
    profile = await get_user_profile(user_id, gid)
    if not profile:
        await cq.answer("ابتدا کشور انتخاب کن (/join).", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="فروش 10 نفت", callback_data="sell_oil_qty:10")],
        [InlineKeyboardButton(text="فروش 50 نفت", callback_data="sell_oil_qty:50")],
        [InlineKeyboardButton(text="فروش همه", callback_data="sell_oil_qty:all")],
    ])
    await cq.answer()
    await cq.message.answer("چقدر نفت می‌خوای بفروشی؟", reply_markup=kb)

@dp.callback_query(lambda c: c.data and c.data.startswith("sell_oil_qty:"))
async def sell_oil_qty_cb(cq: types.CallbackQuery):
    user_id = cq.from_user.id
    gid = user_active_group.get(user_id)
    if not gid:
        await cq.answer("گروه فعال مشخص نیست.", show_alert=True)
        return
    qty_str = cq.data.split(":", 1)[1]
    profile = await get_user_profile(user_id, gid)
    if not profile:
        await cq.answer("پروفایل پیدا نشد.", show_alert=True)
        return
    if qty_str == "all":
        qty = float(profile["oil"])
    else:
        qty = float(qty_str)
    if qty <= 0 or profile["oil"] < qty:
        await cq.answer("نفت کافی نداری.", show_alert=True)
        return
    revenue = qty * OIL_SELL_PRICE
    await db.execute("UPDATE user_profiles SET oil=oil-$2, money=money+$3 WHERE user_id=$1 AND chat_id=$4", user_id, qty, revenue, gid)
    await cq.answer(f"فروختی {qty} نفت و {revenue:.2f} پول گرفتی. پولتو خرج سربازی خوب کن 😎")

# ---------- Attacks ----------
def _now():
    return datetime.utcnow()

async def can_attack_target(attacker_id: int, target_id: int, chat_id: int) -> bool:
    row = await db.fetchrow("SELECT last_attack FROM attack_cooldowns WHERE attacker_id=$1 AND target_id=$2 AND chat_id=$3", attacker_id, target_id, chat_id)
    if not row:
        return True
    last_attack = row["last_attack"]
    if (datetime.utcnow() - last_attack).total_seconds() >= ATTACK_TARGET_COOLDOWN:
        return True
    return False

async def update_attack_cooldown(attacker_id: int, target_id: int, chat_id: int):
    now = datetime.utcnow()
    await db.execute("INSERT INTO attack_cooldowns(attacker_id, target_id, chat_id, last_attack) VALUES($1,$2,$3,$4) "
                     "ON CONFLICT (attacker_id, target_id, chat_id) DO UPDATE SET last_attack=$4",
                     attacker_id, target_id, chat_id, now)

@dp.callback_query(lambda c: c.data == "panel_attack")
async def panel_attack_cb(cq: types.CallbackQuery):
    user_id = cq.from_user.id
    gid = user_active_group.get(user_id)
    if not gid:
        await cq.answer("ابتدا گروه فعال انتخاب کن.", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="حمله با موشک", callback_data="attack_choose:missile")],
        [InlineKeyboardButton(text="حمله با جنگنده", callback_data="attack_choose:jet")],
        [InlineKeyboardButton(text="حمله لفظی (رایگان)", callback_data="attack_choose:verbal")],
    ])
    await cq.answer()
    await cq.message.answer("برای حمله، ابتدا هدف را مشخص کن: در گروه هدف را منشن یا ریپلای کن و سپس نوع حمله را انتخاب کن. (در پیام خصوصی: /attack <group_id> <target_user_id>)", reply_markup=kb)

@dp.message(Command("attack"))
async def cmd_attack(message: types.Message):
    if message.chat.type == "private":
        parts = (message.text or "").split()
        if len(parts) < 3:
            await message.answer("استفاده: /attack <group_id> <target_user_id>")
            return
        try:
            gid = int(parts[1])
            target_id = int(parts[2])
        except ValueError:
            await message.answer("پارامترها نامعتبر هستند.")
            return
        user_id = message.from_user.id
        profile = await get_user_profile(user_id, gid)
        if not profile:
            await message.answer("پروفایل در آن گروه پیدا نشد. ابتدا /join در خصوصی انجام دهید.")
            return
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="موشک", callback_data=f"do_attack:{gid}:{target_id}:missile")],
            [InlineKeyboardButton(text="جنگنده", callback_data=f"do_attack:{gid}:{target_id}:jet")],
            [InlineKeyboardButton(text="لفظی", callback_data=f"do_attack:{gid}:{target_id}:verbal")],
        ])
        await message.answer("نوع حمله را انتخاب کن:", reply_markup=kb)
    else:
        await message.answer("برای حمله در گروه: به پیام هدف ریپلای کن و دکمهٔ حمله را از پنل انتخاب کن یا از /attack در خصوصی استفاده کن.")

@dp.callback_query(lambda c: c.data and c.data.startswith("do_attack:"))
async def do_attack_cb(cq: types.CallbackQuery):
    parts = cq.data.split(":")
    if len(parts) != 4:
        await cq.answer("فرمت نادرست.", show_alert=True)
        return
    chat_id = int(parts[1])
    target_id = int(parts[2])
    attack_type = parts[3]
    attacker_id = cq.from_user.id

    attacker_profile = await get_user_profile(attacker_id, chat_id)
    target_profile = await get_user_profile(target_id, chat_id)
    if not attacker_profile:
        await cq.answer("شما در این گروه پروفایل ندارید. /join کن.", show_alert=True)
        return
    if not target_profile:
        await cq.answer("هدف در این گروه پروفایل ندارد.", show_alert=True)
        return
    if attacker_id == target_id:
        await cq.answer("به خودت حمله نمی‌کنی، فرمانده؟ 🤨", show_alert=True)
        return

    if attack_type == "verbal":
        row = await db.fetchrow("SELECT last_verbal FROM verbal_cooldowns WHERE user_id=$1", attacker_id)
        if row and (datetime.utcnow() - row["last_verbal"]).total_seconds() < VERBAL_COOLDOWN:
            await cq.answer("چند ثانیه صبر کن تا دوباره فحش بدی 😅", show_alert=True)
            return
        reward = VERBAL_REWARD
        await db.execute("UPDATE user_profiles SET money=money+$2 WHERE user_id=$1 AND chat_id=$3", attacker_id, reward, chat_id)
        now = datetime.utcnow()
        await db.execute("INSERT INTO verbal_cooldowns(user_id, last_verbal) VALUES($1,$2) ON CONFLICT (user_id) DO UPDATE SET last_verbal=$2", attacker_id, now)
        await cq.answer(f"حمله لفظی انجام شد! {reward:.2f} پول جایزه گرفتی. (به سبکِ زرنگِ دیپلماتیک 😂)")
        await try_complete_mission(chat_id, attacker_id, "verbal")
        return

    if not await can_attack_target(attacker_id, target_id, chat_id):
        await cq.answer("نمی‌تونی همین حالا دوباره به همین هدف حمله کنی — ۳۰ دقیقه باید صبر کنی.", show_alert=True)
        return

    if attack_type == "missile":
        damage_pct = MISSILE_DAMAGE
        oil_cost = MISSILE_OIL_COST
        weapon_check = ("missiles", 1)
    elif attack_type == "jet":
        damage_pct = JET_DAMAGE
        oil_cost = JET_OIL_COST
        weapon_check = ("jets", 1)
    else:
        await cq.answer("نوع حمله نامعتبر است.", show_alert=True)
        return

    if attacker_profile["oil"] < oil_cost:
        await cq.answer("نفت کافی برای انجام حمله نداری.", show_alert=True)
        return

    # Transactional execution using connection-level FOR UPDATE checks
    try:
        async with db.transaction() as conn:
            # lock attacker and target rows to avoid race
            attacker_row = await conn.fetchrow("SELECT missiles, jets, oil, money FROM user_profiles WHERE user_id=$1 AND chat_id=$2 FOR UPDATE", attacker_id, chat_id)
            target_row = await conn.fetchrow("SELECT oil, money FROM user_profiles WHERE user_id=$1 AND chat_id=$2 FOR UPDATE", target_id, chat_id)
            if not attacker_row or not target_row:
                await cq.answer("خطا در خواندن پروفایل‌ها. دوباره تلاش کن.", show_alert=True)
                return

            # re-check resources after locking
            if weapon_check[0] == "missiles" and attacker_row["missiles"] <= 0:
                await cq.answer("کسی قبل از شما موشک‌ها را استفاده کرده 😅", show_alert=True)
                return
            if weapon_check[0] == "jets" and attacker_row["jets"] <= 0:
                await cq.answer("کسی قبل از شما جنگنده‌ها را استفاده کرده 😅", show_alert=True)
                return
            if attacker_row["oil"] < oil_cost:
                await cq.answer("نفت کافی برای اجرای حمله وجود ندارد.", show_alert=True)
                return

            cap = 0.5
            effective_pct = min(damage_pct, cap)
            oil_loot = target_row["oil"] * effective_pct
            money_loot = target_row["money"] * effective_pct

            # consume weapon and oil
            if weapon_check[0] == "missiles":
                await conn.execute("UPDATE user_profiles SET missiles=missiles-1, oil=oil-$3 WHERE user_id=$1 AND chat_id=$2", attacker_id, chat_id, oil_cost)
            else:
                await conn.execute("UPDATE user_profiles SET jets=jets-1, oil=oil-$3 WHERE user_id=$1 AND chat_id=$2", attacker_id, chat_id, oil_cost)

            # deduct from target and add to attacker
            await conn.execute("UPDATE user_profiles SET oil=GREATEST(oil-$2,0), money=GREATEST(money-$3,0) WHERE user_id=$1 AND chat_id=$4", target_id, oil_loot, money_loot, chat_id)
            await conn.execute("UPDATE user_profiles SET oil=oil+$2, money=money+$3 WHERE user_id=$1 AND chat_id=$4", attacker_id, oil_loot, money_loot, chat_id)

            # update cooldown
            now = datetime.utcnow()
            await conn.execute("INSERT INTO attack_cooldowns(attacker_id, target_id, chat_id, last_attack) VALUES($1,$2,$3,$4) ON CONFLICT (attacker_id, target_id, chat_id) DO UPDATE SET last_attack=$4", attacker_id, target_id, chat_id, now)

    except Exception:
        logger.exception("attack transaction failed")
        await cq.answer("خطایی رخ داد؛ دوباره تلاش کن.", show_alert=True)
        return

    await cq.answer(f"حمله با {attack_type} انجام شد! \nغارت: {money_loot:.2f} پول و {oil_loot:.2f} نفت به دست آمد.", show_alert=True)
    try:
        await bot.send_message(chat_id, f"💥 حمله‌ای توسط {cq.from_user.first_name} به user({target_id}) صورت گرفت! \nغارت: {money_loot:.2f} پول و {oil_loot:.2f} نفت.")
    except Exception:
        pass

    await try_complete_mission(chat_id, attacker_id, attack_type)

# ---------- Missions ----------
async def try_complete_mission(chat_id: int, user_id: int, action_type: str):
    mission_rows = await db.fetch("SELECT m.* FROM missions m LEFT JOIN group_missions gm ON gm.mission_id=m.id AND gm.chat_id=$1 WHERE gm.status IS NULL OR gm.status='pending'", chat_id)
    if not mission_rows:
        return
    for m in mission_rows:
        if m["type"] in (None, "", "generic") or action_type in (m["type"], "attack", "verbal"):
            try:
                # insert as completed if none exists (first completer wins)
                await db.execute("INSERT INTO group_missions(chat_id, mission_id, user_id, status) VALUES($1,$2,$3,$4) ON CONFLICT (chat_id, mission_id) DO NOTHING", chat_id, m["id"], user_id, "completed")
                # give reward (safe update)
                await db.execute("UPDATE user_profiles SET money=money+$2, oil=oil+$3 WHERE user_id=$1 AND chat_id=$4", user_id, m["reward_money"], m["reward_oil"], chat_id)
                try:
                    await bot.send_message(chat_id, f"🏆 ماموریت گروهی انجام شد! برنده: user({user_id}). جایزه: {m['reward_money']} پول و {m['reward_oil']} نفت.")
                except Exception:
                    pass
            except Exception:
                logger.exception("mission completion failed")
            break

async def run_group_missions(chat_id: int):
    while True:
        try:
            m = await db.fetchrow("SELECT * FROM missions ORDER BY RANDOM() LIMIT 1")
            if m:
                await db.execute("INSERT INTO group_missions(chat_id, mission_id, user_id, status) VALUES($1,$2,$3,$4) ON CONFLICT (chat_id, mission_id) DO UPDATE SET status='pending', user_id=NULL", chat_id, m["id"], None, "pending")
                try:
                    await bot.send_message(chat_id, f"🎯 ماموریت جدید: {m['text']}\nاولین کسی که انجام دهد جایزه می‌گیرد: {m['reward_money']} پول و {m['reward_oil']} نفت.")
                except Exception:
                    pass
            await asyncio.sleep(max(30, MISSION_INTERVAL_SECONDS + random.randint(-60, 60)))
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("run_group_missions error")
            await asyncio.sleep(30)

# ---------- Quizzes ----------
async def run_group_challenges(chat_id: int):
    while True:
        try:
            c = await db.fetchrow("SELECT * FROM challenges ORDER BY RANDOM() LIMIT 1")
            if not c:
                await db.execute("INSERT INTO challenges(text, answer, reward_money, reward_oil) VALUES($1,$2,$3,$4)", "چه رنگی آسمان است؟", "آبی", 10.0, 5.0)
                await asyncio.sleep(10)
                continue
            start = datetime.utcnow()
            end = start + timedelta(seconds=QUIZ_INTERVAL_SECONDS // 2)
            try:
                msg = await bot.send_message(chat_id, f"❓ کوییز گروهی:\n{c['text']}\n(پاسخ را در این چت تایپ کنید)")
                msg_id = msg.message_id
            except Exception:
                msg_id = None
            await db.execute("INSERT INTO group_challenges(chat_id, challenge_id, message_id, start_time, end_time, active) VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT (chat_id) DO UPDATE SET challenge_id=$2, message_id=$3, start_time=$4, end_time=$5, active=$6", chat_id, c["id"], msg_id, start, end, 1)
            await asyncio.sleep(QUIZ_INTERVAL_SECONDS // 2)
            # mark inactive if still active
            await db.execute("UPDATE group_challenges SET active=0 WHERE chat_id=$1 AND challenge_id=$2", chat_id, c["id"])
            await asyncio.sleep(max(30, QUIZ_INTERVAL_SECONDS + random.randint(-60, 60)))
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("run_group_challenges error")
            await asyncio.sleep(30)

@dp.message()
async def all_messages_handler(message: types.Message):
    if message.chat.type != "private":
        gc = await db.fetchrow(
            "SELECT gc.*, c.answer, c.reward_money, c.reward_oil FROM group_challenges gc JOIN challenges c ON c.id=gc.challenge_id WHERE gc.chat_id=$1 AND gc.active=1",
            message.chat.id
        )
        if gc and gc.get("answer"):
            answer = (gc["answer"] or "").strip().lower()
            candidate = (message.text or "").strip().lower()
            if candidate and candidate == answer:
                try:
                    async with db.transaction() as conn:
                        cur = await conn.fetchrow("SELECT active FROM group_challenges WHERE chat_id=$1 AND challenge_id=$2 FOR UPDATE", message.chat.id, gc["challenge_id"])
                        if not cur or cur["active"] == 0:
                            return
                        await conn.execute("UPDATE group_challenges SET active=0 WHERE chat_id=$1 AND challenge_id=$2", message.chat.id, gc["challenge_id"])
                        await conn.execute("UPDATE user_profiles SET money=money+$2, oil=oil+$3 WHERE user_id=$1 AND chat_id=$4", message.from_user.id, gc["reward_money"], gc["reward_oil"], message.chat.id)
                    await bot.send_message(message.chat.id, f"🎉 {message.from_user.first_name} پاسخ درست داد و {gc['reward_money']} پول و {gc['reward_oil']} نفت جایزه گرفت!")
                except Exception:
                    logger.exception("quiz awarding failed")
    # Potentially add other message-based triggers here

# ---------- Oil Rigs (Build / Upgrade / Destroy) ----------
@dp.callback_query(lambda c: c.data == "panel_build_rig")
async def panel_build_rig_cb(cq: types.CallbackQuery):
    user_id = cq.from_user.id
    gid = user_active_group.get(user_id)
    if not gid:
        await cq.answer("ابتدا گروه فعال انتخاب کن.", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="ساخت دکل سطح 2 (200 پول)", callback_data="build_rig:2")],
        [InlineKeyboardButton(text="ساخت دکل سطح 3 (500 پول)", callback_data="build_rig:3")],
    ])
    await cq.answer()
    await cq.message.answer("انتخاب کن چه دکلی بسازی:", reply_markup=kb)

@dp.callback_query(lambda c: c.data and c.data.startswith("build_rig:"))
async def build_rig_cb(cq: types.CallbackQuery):
    user_id = cq.from_user.id
    level = int(cq.data.split(":")[1])
    gid = user_active_group.get(user_id)
    if not gid:
        await cq.answer("گروه فعال مشخص نیست.", show_alert=True)
        return
    if level == 2:
        price = 200.0
        hp = 1500
        cap = 200
        speed = 1.5
    elif level == 3:
        price = 500.0
        hp = 2500
        cap = 500
        speed = 2.0
    else:
        await cq.answer("سطح نامعتبر.", show_alert=True)
        return
    profile = await get_user_profile(user_id, gid)
    if not profile:
        await cq.answer("ابتدا کشور انتخاب کن (/join).", show_alert=True)
        return
    if profile["money"] < price:
        await cq.answer("پول کافی نداری.", show_alert=True)
        return
    await db.execute("UPDATE user_profiles SET money=money-$2 WHERE user_id=$1 AND chat_id=$3", user_id, price, gid)
    await db.execute("INSERT INTO oil_rigs(owner_id, level, hp, capacity, extraction_speed, invulnerable) VALUES($1,$2,$3,$4,$5,$6)", user_id, level, hp, cap, speed, 0)
    await cq.answer(f"دکل سطح {level} ساخته شد! نفتت داره با کلاس استخراج میشه ⛽️")

# ---------- Startup / Bootstrap ----------
async def bootstrap_group_tasks():
    groups = await db.fetch("SELECT chat_id FROM groups WHERE active=TRUE")
    for g in groups:
        chat_id = g["chat_id"]
        if chat_id not in group_challenge_tasks:
            group_challenge_tasks[chat_id] = asyncio.create_task(run_group_challenges(chat_id))
        if chat_id not in group_mission_tasks:
            group_mission_tasks[chat_id] = asyncio.create_task(run_group_missions(chat_id))

async def seed_data():
    m = await db.fetchrow("SELECT id FROM missions LIMIT 1")
    if not m:
        await db.execute("INSERT INTO missions(text, reward_money, reward_oil, type) VALUES($1,$2,$3,$4)", "انجام یک حمله عادی (موشک یا جنگنده)", 100.0, 50.0, "attack")
        await db.execute("INSERT INTO missions(text, reward_money, reward_oil, type) VALUES($1,$2,$3,$4)", "انجام یک حمله لفظی", 20.0, 5.0, "verbal")
    ch = await db.fetchrow("SELECT id FROM challenges LIMIT 1")
    if not ch:
        await db.execute("INSERT INTO challenges(text, answer, reward_money, reward_oil) VALUES($1,$2,$3,$4)", "چه رنگی آسمان است؟", "آبی", 10.0, 5.0)

# ---------- Main ----------
async def main():
    await init_db()
    await seed_data()
    await bootstrap_group_tasks()
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Starting polling...")
    try:
        await dp.start_polling(bot)
    finally:
        # graceful shutdown: cancel tasks and close db & bot
        for t in list(group_challenge_tasks.values()):
            t.cancel()
        for t in list(group_mission_tasks.values()):
            t.cancel()
        await asyncio.gather(*group_challenge_tasks.values(), return_exceptions=True)
        await asyncio.gather(*group_mission_tasks.values(), return_exceptions=True)
        await db.close()
        await bot.session.close()
        logger.info("Shutdown complete")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped")

