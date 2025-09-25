# telegram_war_game_bot_part1.py
import os
import asyncio
import random
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, ChatMemberUpdatedFilter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ChatMemberUpdated
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
import asyncpg

# ------------------ Global tasks ------------------
group_challenge_tasks: dict[int, asyncio.Task] = {}
group_mission_tasks: dict[int, asyncio.Task] = {}

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

if not BOT_TOKEN or not DATABASE_URL:
    raise RuntimeError("BOT_TOKEN and DATABASE_URL environment variables are required")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ------------------ DB Adapter ------------------
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
            return dict(row) if row else None

    async def fetchall(self, sql: str, params: Tuple = ()):
        async with self._pg_pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
            return [dict(r) for r in rows]

db = DBAdapter(DATABASE_URL)

# ------------------ FSM ------------------
class CountryFSM(StatesGroup):
    waiting_for_country = State()
    waiting_for_rename = State()

COUNTRIES = ["ایران", "روسیه"]

# ------------------ DB Init ------------------
async def init_db():
    await db.init()
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
        experience INTEGER DEFAULT 0,
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
    await db.execute("""
    CREATE TABLE IF NOT EXISTS groups (
        chat_id BIGINT PRIMARY KEY,
        title TEXT,
        username TEXT
    )
    """)
    await db.execute("""
    CREATE TABLE IF NOT EXISTS temp_profiles (
        user_id BIGINT,
        chat_id BIGINT,
        country TEXT,
        PRIMARY KEY(user_id, chat_id)
    )
    """)
    await db.execute("""
    CREATE TABLE IF NOT EXISTS user_profiles (
        user_id BIGINT,
        chat_id BIGINT,
        country TEXT,
        oil DOUBLE PRECISION DEFAULT 0,
        money DOUBLE PRECISION DEFAULT 0,
        missiles INT DEFAULT 0,
        jets INT DEFAULT 0,
        defenses INT DEFAULT 0,
        level INT DEFAULT 1,
        PRIMARY KEY(user_id, chat_id)
    )
    """)

# ------------------ Helpers ------------------
async def ensure_user(user: types.User) -> bool:
    row = await db.fetchone("SELECT has_initial_rig FROM users WHERE user_id=$1", (user.id,))
    if row is None:
        await db.execute(
            "INSERT INTO users(user_id, username, first_name, last_name, money_amount, money_currency, oil_amount, level, experience, has_initial_rig) "
            "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
            (user.id, user.username or "", user.first_name or "", user.last_name or "", 100.0, "USD", 100.0, 1, 0, 1)
        )
        await db.execute(
            "INSERT INTO oil_rigs(owner_id, level, hp, capacity, extraction_speed, invulnerable) VALUES($1,$2,$3,$4,$5,$6)",
            (user.id, 1, 1000, 100, 1.0, 1)
        )
        return True
    return False

async def get_common_groups(user_id: int) -> List[Tuple[int, str]]:
    rows = await db.fetchall("SELECT chat_id, title FROM groups")
    valid_groups: List[Tuple[int, str]] = []
    for r in rows:
        chat_id = r["chat_id"]
        try:
            user_member = await bot.get_chat_member(chat_id, user_id)
            if user_member.status in ("left", "kicked"):
                continue
            valid_groups.append((chat_id, r["title"]))
        except Exception:
            continue
    return valid_groups

async def check_bot_admin(chat_id: int, cb_or_msg: Optional[types.CallbackQuery | types.Message] = None) -> bool:
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(chat_id, me.id)
    except Exception:
        if cb_or_msg:
            try:
                if isinstance(cb_or_msg, types.CallbackQuery):
                    await cb_or_msg.answer("⚠️ خطا در بررسی دسترسی ربات.", show_alert=True)
                else:
                    await cb_or_msg.answer("⚠️ خطا در بررسی دسترسی ربات.")
            except:
                pass
        return False
    if member.status not in ("administrator", "creator"):
        if cb_or_msg:
            try:
                if isinstance(cb_or_msg, types.CallbackQuery):
                    await cb_or_msg.answer("⚠️ فرمانده در جایگاه خودش نیست! لطفاً ربات را ادمین کنید.", show_alert=True)
                else:
                    await cb_or_msg.answer("⚠️ فرمانده در جایگاه خودش نیست! لطفاً ربات را ادمین کنید.")
            except:
                pass
        return False
    return True

# ------------------ Start & FSM ------------------
user_active_group: Dict[int, int] = {}

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    if message.chat.type != "private":
        return
    await ensure_user(message.from_user)
    username = message.from_user.username or message.from_user.first_name
    groups = await get_common_groups(message.from_user.id)
    if not groups:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ انجام شد فرمانده", callback_data="done_add_group"),
            InlineKeyboardButton(text="➕ افزودن به گروه", url=f"https://t.me/{(await bot.get_me()).username}?startgroup=true")
        ]])
        await message.answer(
            f"فرمانده:\nسرباز {username}، هیچ گروه مشترکی با تو ندارم.\n"
            "اگر ربات را اضافه نکردی ابتدا او را به گروه اضافه کن و سپس «انجام شد فرمانده» را بزن.",
            reply_markup=kb
        )
        return

    if len(groups) == 1:
        user_active_group[message.from_user.id] = groups[0][0]
        await message.answer(f"فرمانده: گروه فعال شما {groups[0][1]} است. حالا کشور خود را انتخاب کنید.")
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=c, callback_data=f"select_country:{c}")] for c in COUNTRIES]
        )
        await message.answer("🌍 کشور خود را انتخاب کنید:", reply_markup=kb)
        await state.set_state(CountryFSM.waiting_for_country)
        await state.update_data(chat_id=groups[0][0])
        return

    kb_rows = [[InlineKeyboardButton(text=title or str(chat_id), callback_data=f"group_{chat_id}")] for chat_id, title in groups]
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    await message.answer(f"فرمانده:\nسرباز {username}، چند گروه مشترک با ربات پیدا کردم. لطفاً گروهی که می‌خواهی در آن بازی کنی را انتخاب کن:", reply_markup=kb)

# FSM callback country selection
@dp.callback_query(lambda cb: cb.data.startswith("select_country:"))
async def select_country(cb: types.CallbackQuery, state: FSMContext):
    country = cb.data.split(":",1)[1]
    data = await state.get_data()
    chat_id = data["chat_id"]
    count = await db.fetchone("SELECT COUNT(*) as c FROM user_profiles WHERE country LIKE $1", (f"{country}%",))
    if count["c"] > 0:
        country = f"{country}{count['c']+1}"
    await db.execute(
        "INSERT INTO temp_profiles(user_id, chat_id, country) VALUES($1,$2,$3) "
        "ON CONFLICT (user_id, chat_id) DO UPDATE SET country=$3",
        (cb.from_user.id, chat_id, country)
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ تایید", callback_data="confirm_country")],
        [InlineKeyboardButton(text="✏️ تغییر نام", callback_data="rename_country")]
    ])
    await cb.message.answer(f"🏳️ کشور انتخابی شما: {country}\nآیا می‌خواهید نام آن را تغییر دهید؟", reply_markup=kb)
    await cb.answer()
# ------------------ FSM ادامه: تایید یا تغییر نام کشور ------------------
@dp.callback_query(lambda cb: cb.data == "confirm_country")
async def confirm_country(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    chat_id = data["chat_id"]
    temp = await db.fetchone("SELECT country FROM temp_profiles WHERE user_id=$1 AND chat_id=$2", (cb.from_user.id, chat_id))
    country = temp["country"]
    # ثبت نهایی در user_profiles
    await db.execute(
        "INSERT INTO user_profiles(user_id, chat_id, country, oil, money, missiles, jets, defenses, level) "
        "VALUES($1,$2,$3,0,0,0,0,0,1) ON CONFLICT(user_id, chat_id) DO NOTHING",
        (cb.from_user.id, chat_id, country)
    )
    await cb.message.answer(f"🎉 خوش آمدید! کشور شما {country} ثبت شد.\nشما برای شروع یک دکل نفت سطح 1 دریافت کردید.")
    await show_panel(cb.message, cb.from_user.username or cb.from_user.first_name, chat_id)
    await state.clear()
    await cb.answer()

@dp.callback_query(lambda cb: cb.data == "rename_country")
async def rename_country(cb: types.CallbackQuery, state: FSMContext):
    await cb.message.answer("✏️ لطفاً نام جدید کشور خود را ارسال کنید:")
    await state.set_state(CountryFSM.waiting_for_rename)
    await cb.answer()

@dp.message(CountryFSM.waiting_for_rename)
async def process_rename(message: types.Message, state: FSMContext):
    new_name = message.text.strip()
    data = await state.get_data()
    chat_id = data["chat_id"]
    # اضافه کردن شماره اگر نام تکراری باشد
    count = await db.fetchone("SELECT COUNT(*) as c FROM user_profiles WHERE country LIKE $1", (f"{new_name}%",))
    if count["c"] > 0:
        new_name = f"{new_name}{count['c']+1}"
    await db.execute(
        "UPDATE temp_profiles SET country=$1 WHERE user_id=$2 AND chat_id=$3",
        (new_name, message.from_user.id, chat_id)
    )
    await message.answer(f"✅ نام کشور شما به {new_name} تغییر کرد.\nلطفاً تایید کنید.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ تایید", callback_data="confirm_country")]
    ]))
    await state.set_state(CountryFSM.waiting_for_country)

# ------------------ Panel & Inventory ------------------
async def show_panel(message: types.Message, username: str, chat_id: int):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 موجودی", callback_data="inventory")],
        [InlineKeyboardButton(text="🛒 فروشگاه", callback_data="shop"),
         InlineKeyboardButton(text="💱 تبادل", callback_data="exchange")],
        [InlineKeyboardButton(text="🏗️ دکل‌ها", callback_data="rigs"),
         InlineKeyboardButton(text="🛩️ آشیانه‌ها", callback_data="hangars")],
        [InlineKeyboardButton(text="🌍 گروه سراری", callback_data="guilds")]
    ])
    await message.answer(f"فرمانده:\n سرباز {username}، پنل وضعیتت آماده است ⚔️", reply_markup=kb)

async def get_user_inventory(user_id: int) -> Optional[str]:
    user = await db.fetchone("SELECT money_amount, money_currency, oil_amount, level, experience FROM users WHERE user_id=$1", (user_id,))
    if not user:
        return None
    money, currency, oil, level, exp = user["money_amount"], user["money_currency"], user["oil_amount"], user["level"], user["experience"]
    bar = "█" * min(level,10) + "░" * (10 - min(level,10))
    rigs = await db.fetchone("SELECT COUNT(*) as cnt, MIN(level) as min_level, MAX(level) as max_level FROM oil_rigs WHERE owner_id=$1", (user_id,))
    rigs_count, rigs_min, rigs_max = rigs["cnt"], rigs["min_level"], rigs["max_level"]
    return (
        f"💰 پول: {money} {currency}\n"
        f"🛢️ نفت: {oil}\n"
        f"🏗️ دکل‌ها: {rigs_count} (سطح {rigs_min} تا {rigs_max})\n"
        f"🎖️ سطح: {level}\n"
        f"✨ تجربه: {exp}\n"
        f"📊 پیشرفت سطح: [{bar}]"
    )

@dp.callback_query(lambda cb: cb.data == "inventory")
async def callback_inventory(cb: types.CallbackQuery):
    chat_id = user_active_group.get(cb.from_user.id)
    if not chat_id:
        await cb.answer("⚠️ ابتدا یک گروه انتخاب کن (از طریق /start).", show_alert=True)
        return
    if not await check_bot_admin(chat_id, cb):
        return
    data = await get_user_inventory(cb.from_user.id)
    if data:
        await cb.message.edit_text(f"فرمانده:\n {cb.from_user.username}, موجودی شما:\n\n{data}", reply_markup=cb.message.reply_markup)
    else:
        await cb.message.answer(f"فرمانده:\n سرباز {cb.from_user.username}، شما هنوز وارد بازی نشده‌اید. لطفاً /start بزنید.")

@dp.callback_query(lambda cb: cb.data in ("shop","exchange","rigs","hangars","guilds"))
async def callback_other(cb: types.CallbackQuery):
    chat_id = user_active_group.get(cb.from_user.id)
    if not chat_id:
        await cb.answer("⚠️ ابتدا یک گروه انتخاب کن (از طریق /start).", show_alert=True)
        return
    if not await check_bot_admin(chat_id, cb):
        return
    await cb.answer(f"💡 بخش {cb.data} هنوز در دست ساخت است.", show_alert=True)

# ------------------ Challenges Timer ------------------
active_challenges: Dict[int, Dict] = {}

async def run_group_challenges(chat_id: int):
    while True:
        delay = random.randint(5*60, 60*60)  # بین 5 تا 60 دقیقه
        await asyncio.sleep(delay)
        if not await check_bot_admin(chat_id, None):
            continue
        challenge = await db.fetchone("SELECT * FROM challenges ORDER BY RANDOM() LIMIT 1")
        if not challenge:
            continue
        try:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏱ زمان باقی‌مانده", callback_data=f"time_{chat_id}")]
            ])
            msg = await bot.send_message(chat_id, f"فرمانده:\n سربازان! آماده باشید ⚔️\n\nچالش: {challenge['text']}", reply_markup=kb)
        except Exception:
            continue
        start_time = datetime.utcnow()
        end_time = start_time + timedelta(seconds=90)
        active_challenges[chat_id] = {"challenge": challenge, "message_id": msg.message_id, "start_time": start_time, "end_time": end_time, "answered_by": None}
        await db.execute(
            "INSERT INTO group_challenges(chat_id, challenge_id, message_id, start_time, end_time, active) "
            "VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT(chat_id) DO UPDATE SET challenge_id=$2, message_id=$3, start_time=$4, end_time=$5, active=$6",
            (chat_id, challenge['id'], msg.message_id, start_time, end_time, 1)
        )
        for remaining in range(90, 0, -1):
            try:
                await msg.edit_text(f"فرمانده:\n سربازان! آماده باشید ⚔️\n\nچالش: {challenge['text']}\n⏱ زمان: {remaining} ثانیه")
            except Exception:
                break
            await asyncio.sleep(1)
        info = active_challenges.pop(chat_id, None)
        if info and not info["answered_by"]:
            try:
                await msg.edit_text(f"فرمانده:\n زمان چالش به پایان رسید!\nپاسخ صحیح: {challenge['answer']}")
            except Exception:
                pass

@dp.callback_query(lambda cb: cb.data.startswith("time_"))
async def show_remaining_time(cb: types.CallbackQuery):
    chat_id = int(cb.data.split("_")[1])
    info = active_challenges.get(chat_id)
    if not info:
        await cb.answer("⏱ هیچ چالشی فعال نیست!", show_alert=True)
        return
    remaining = int((info["end_time"] - datetime.utcnow()).total_seconds())
    if remaining < 0:
        await cb.answer("⏱ زمان به پایان رسیده!", show_alert=True)
    else:
        await cb.answer(f"⏱ زمان باقی‌مانده: {remaining} ثانیه", show_alert=True)
# ------------------ Handling Challenge Replies ------------------
@dp.message()
async def handle_challenge_reply(message: types.Message):
    if not message.reply_to_message:
        return
    chat_id = message.chat.id
    if not await check_bot_admin(chat_id, message):
        return
    if chat_id not in active_challenges:
        return
    info = active_challenges[chat_id]
    if message.reply_to_message.message_id != info["message_id"]:
        return
    if info["answered_by"] is not None:
        return  # پاسخ قبلاً داده شده

    challenge = info["challenge"]
    if message.text.strip().lower() == (challenge["answer"] or "").strip().lower():
        info["answered_by"] = message.from_user.id
        reward_money = challenge["reward_money"]
        reward_oil = challenge["reward_oil"]
        try:
            await db.execute(
                "UPDATE users SET money_amount = money_amount + $1, oil_amount = oil_amount + $2 WHERE user_id=$3",
                (reward_money, reward_oil, message.from_user.id)
            )
        except Exception:
            pass
        await message.reply(
            f"فرمانده:\n تبریک سرباز {message.from_user.username}! 🎉\nجوایز شما: 💰 {reward_money}, 🛢️ {reward_oil}"
        )
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=info["message_id"],
                text=f"چالش: {challenge['text']}\n✅ پاسخ صحیح داده شد توسط {message.from_user.username}\n⏱ زمان باقی‌مانده: {(info['end_time'] - datetime.utcnow()).seconds} ثانیه"
            )
        except Exception:
            pass

# ------------------ Missions ------------------
async def check_mission_completion(chat_id: int):
    missions = await db.fetchall("SELECT * FROM group_missions WHERE chat_id=$1 AND status='pending'", (chat_id,))
    for mission in missions:
        if mission["user_id"] != 0:
            user = await db.fetchone("SELECT username FROM users WHERE user_id=$1", (mission["user_id"],))
            if not user:
                continue
            reward_money = 100
            reward_oil = 100
            try:
                await db.execute(
                    "UPDATE users SET money_amount = money_amount + $1, oil_amount = oil_amount + $2 WHERE user_id=$3",
                    (reward_money, reward_oil, mission["user_id"])
                )
                await db.execute(
                    "UPDATE group_missions SET status='completed' WHERE chat_id=$1 AND mission_id=$2 AND user_id=$3",
                    (chat_id, mission["mission_id"], mission["user_id"])
                )
            except Exception:
                pass
            if not await check_bot_admin(chat_id, None):
                continue
            try:
                await bot.send_message(
                    chat_id,
                    f"فرمانده:\n سرباز {user['username']} ماموریت `{mission['mission_id']}` را تکمیل کرد! 🎖️\nجوایز: 💰 {reward_money}, 🛢️ {reward_oil}"
                )
            except Exception:
                pass

async def wait_until_next(hour: int, minute: int = 0):
    now = datetime.utcnow()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    await asyncio.sleep((target - now).total_seconds())

async def run_group_missions(chat_id: int):
    while True:
        now = datetime.utcnow()
        if now.hour < 12:
            await wait_until_next(12, 0)
        else:
            await wait_until_next(0, 0)
        missions = await db.fetchall("SELECT * FROM missions ORDER BY RANDOM() LIMIT 3")
        await db.execute("DELETE FROM group_missions WHERE chat_id=$1", (chat_id,))
        for m in missions:
            await db.execute(
                "INSERT INTO group_missions(chat_id, mission_id, user_id, status) VALUES($1,$2,0,'pending')",
                (chat_id, m['id'])
            )
        await db.execute(
            "INSERT INTO group_missions_schedule(chat_id, last_update) VALUES($1,$2) "
            "ON CONFLICT (chat_id) DO UPDATE SET last_update=$2",
            (chat_id, datetime.utcnow())
        )
        for _ in range(12 * 60 // 5):
            await check_mission_completion(chat_id)
            await asyncio.sleep(300)


# هندلر برای تغییر وضعیت ربات در گروه
@dp.my_chat_member(ChatMemberUpdatedFilter())
async def on_bot_status_change(event: ChatMemberUpdated):
    chat = event.chat
    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status

    # ✅ وقتی ربات به گروه اضافه یا ادمین میشه
    if new_status in ("member", "administrator"):
        await db.execute(
            "INSERT INTO groups(chat_id, title, username) VALUES($1, $2, $3) "
            "ON CONFLICT (chat_id) DO UPDATE SET title=$2, username=$3",
            (chat.id, chat.title, chat.username or "")
        )
        await bot.send_message(
            chat.id,
            "🫡 فرمانده وارد شد!\n\n"
            "لطفاً من رو به مقام ادمین ارتقا بدین تا بتونم فرماندهی واقعی داشته باشم ⚔️"
        )

    # ❌ وقتی ربات از گروه حذف یا کیک میشه
    elif new_status in ("left", "kicked"):
        await db.execute("DELETE FROM groups WHERE chat_id=$1", (chat.id,))
        # این خط اختیاریه، فقط جهت اطلاع ادمین
        print(f"ربات از گروه {chat.title} ({chat.id}) حذف شد و از دیتابیس پاک شد.")
        
# ------------------ Bootstrap ------------------
async def main():
    await init_db()
    groups = await db.fetchall("SELECT chat_id FROM groups")
    for g in groups:
        chat_id = g["chat_id"]
        if chat_id not in group_challenge_tasks:
            c_task = asyncio.create_task(run_group_challenges(chat_id))
            group_challenge_tasks[chat_id] = c_task
        if chat_id not in group_mission_tasks:
            m_task = asyncio.create_task(run_group_missions(chat_id))
            group_mission_tasks[chat_id] = m_task
    print("Start polling...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped!")


