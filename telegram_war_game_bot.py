# telegram_war_game_bot.py
import os
import asyncio
import random
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple, List

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ChatMemberUpdated
import asyncpg

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

# ------------------ DB Init Safe ------------------
async def init_db():
    await db.init()
    
    # Users
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
    # اطمینان از ستون‌ها (در صورتی که از قبل جدول موجود باشد)
    existing_cols = await db.fetchall("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name='users';
    """)
    cols = [r["column_name"] for r in existing_cols]
    if "experience" not in cols:
        await db.execute("ALTER TABLE users ADD COLUMN experience INTEGER DEFAULT 0")
    if "level" not in cols:
        await db.execute("ALTER TABLE users ADD COLUMN level INTEGER DEFAULT 1")
    if "has_initial_rig" not in cols:
        await db.execute("ALTER TABLE users ADD COLUMN has_initial_rig INTEGER DEFAULT 0")

    # Oil rigs
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
    # Groups (گروه‌هایی که ربات عضوشان است)
    await db.execute("""
    CREATE TABLE IF NOT EXISTS groups (
        chat_id BIGINT PRIMARY KEY,
        title TEXT,
        username TEXT
    )
    """)
    # Challenges
    await db.execute("""
    CREATE TABLE IF NOT EXISTS challenges (
        id SERIAL PRIMARY KEY,
        text TEXT,
        answer TEXT,
        reward_money DOUBLE PRECISION DEFAULT 50.0,
        reward_oil DOUBLE PRECISION DEFAULT 50.0
    )
    """)
    # Active group challenges
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
    # Missions
    await db.execute("""
    CREATE TABLE IF NOT EXISTS missions (
        id SERIAL PRIMARY KEY,
        text TEXT,
        reward_money DOUBLE PRECISION DEFAULT 100.0,
        reward_oil DOUBLE PRECISION DEFAULT 100.0,
        type TEXT DEFAULT 'generic'
    )
    """)
    await db.execute("""
    CREATE TABLE IF NOT EXISTS group_missions (
        chat_id BIGINT,
        mission_id INT,
        user_id BIGINT,
        status TEXT DEFAULT 'pending',
        PRIMARY KEY(chat_id, mission_id, user_id)
    )
    """)
    await db.execute("""
    CREATE TABLE IF NOT EXISTS group_missions_schedule (
        chat_id BIGINT PRIMARY KEY,
        last_update TIMESTAMP
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
        f"✨ تجربه: {exp} (سطح {level})\n"
        f"📊 پیشرفت سطح: [{bar}]"
    )

# چک کردن ادمین بودن ربات قبل از پاسخ به درخواست‌ها
async def check_bot_admin(chat_id: int, cb_or_msg: Optional[types.CallbackQuery | types.Message] = None) -> bool:
    """اگر cb_or_msg داده شود پیغام مناسب به کاربر ارسال می‌شود، در غیر این صورت فقط مقدار True/False برمی‌گردد."""
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(chat_id, me.id)
    except Exception:
        # مثلاً اگر گروه حذف شده یا دسترسی نباشد
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
        # فقط وقتی cb_or_msg موجود است پیغام بده
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

# ------------------ Panel & Start ------------------
# نگهداری گروه فعال فعلی برای هر کاربر (در حافظه؛ می‌تونیم بعداً توی DB هم ذخیره کنیم)
user_active_group: Dict[int, int] = {}  # user_id -> chat_id

async def get_common_groups(user_id: int) -> List[Tuple[int, str]]:
    """
    گروه‌هایی که در جدول groups ثبت شده‌اند (ربات در آن‌ها عضو است)
    و کاربر نیز در آن‌ها عضو می‌باشد.
    """
    rows = await db.fetchall("SELECT chat_id, title FROM groups")
    valid_groups: List[Tuple[int, str]] = []
    for r in rows:
        chat_id = r["chat_id"]
        try:
            # بررسی وضعیت خود کاربر در گروه
            user_member = await bot.get_chat_member(chat_id, user_id)
            # اگر کاربر در گروه نیست یا اخراج شده باشد از لیست حذف می‌شود
            if user_member.status in ("left", "kicked"):
                continue
            # همچنین اطمینان از اینکه ربات هم در گروه است (در واقع چون groups از قبل پر شده فرض می‌کنیم)
            valid_groups.append((chat_id, r["title"]))
        except Exception:
            # اگر ارور داشتیم (مثلاً گروه خصوصی یا دسترسی نداریم) آن را نادیده می‌گیریم
            continue
    return valid_groups

# هنگامی که وضعیت my_chat_member (ربات) عوض شود، جدول groups را آپدیت کن
@dp.my_chat_member()
async def on_my_chat_member(update: ChatMemberUpdated):
    # update.chat — اطلاعات چت
    # update.new_chat_member.status — وضعیت جدید ربات در چت
    chat = update.chat
    old_status = getattr(update.old_chat_member, "status", None)
    new_status = getattr(update.new_chat_member, "status", None)
    chat_id = chat.id

    # وقتی ربات تازه اضافه شده به گروه (از left -> member/administrator/creator)
    if new_status in ("member", "administrator", "creator") and old_status in ("left", "kicked", None):
        # ثبت گروه در دیتابیس (در صورت وجود آپدیت می‌کنیم)
        try:
            await db.execute(
                "INSERT INTO groups(chat_id, title, username) VALUES($1,$2,$3) "
                "ON CONFLICT (chat_id) DO UPDATE SET title=$2, username=$3",
                (chat_id, chat.title or "", chat.username or "")
            )
        except Exception:
            pass

        # پیامی در گروه ارسال کن که ربات اضافه شد و ادمین شود (فقط یکبار)
        try:
            await bot.send_message(
                chat_id,
                "فرمانده: سربازان! من اکنون به گروه پیوستم. لطفاً مرا ادمین کنید تا بتوانم فرماندهی را به درستی اجرا کنم. ⚠️"
            )
        except Exception:
            pass

    # اگر ربات از گروه خارج شد یا اخراج شد، می‌توان رکورد را حذف یا علامت‌گذاری کرد
    if new_status in ("left", "kicked"):
        try:
            await db.execute("DELETE FROM groups WHERE chat_id=$1", (chat_id,))
        except Exception:
            pass

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await ensure_user(message.from_user)
    username = message.from_user.username or message.from_user.first_name
    groups = await get_common_groups(message.from_user.id)
    
    if not groups:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ انجام شد فرمانده", callback_data="done_add_group"),
                InlineKeyboardButton(text="➕ افزودن به گروه", url=f"https://t.me/{(await bot.get_me()).username}?startgroup=true")
            ]
        ])
        await message.answer(
            f"فرمانده:\nسرباز {username}، من هنوز هیچ گروه مشترکی با تو ندارم.\n"
            "اگر ربات را اضافه نکردی ابتدا او را به گروه اضافه کن. اگر ربات قبلاً اضافه شده—لطفاً آن را ادمین کن و سپس «انجام شد فرمانده» را بزن.",
            reply_markup=kb
        )
        return

    # اگر فقط یک گروه مشترک باشه، همون رو به عنوان گروه فعال تعیین کن و پنل رو نمایش بده
    if len(groups) == 1:
        user_active_group[message.from_user.id] = groups[0][0]
        await show_panel(message, username, groups[0][0])
        return

    # اگر چند گروه مشترک داشت، از کاربر بخواه گروه را انتخاب کند
    kb_rows = [[InlineKeyboardButton(text=title or str(chat_id), callback_data=f"group_{chat_id}")] for chat_id, title in groups]
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    await message.answer(
        f"فرمانده:\nسرباز {username}، چند گروه مشترک با ربات پیدا کردم. لطفاً گروهی که می‌خواهی در آن بازی کنی را انتخاب کن:",
        reply_markup=kb
    )

@dp.callback_query(lambda cb: cb.data == "done_add_group")
async def done_add_group(cb: types.CallbackQuery):
    username = cb.from_user.username or cb.from_user.first_name
    groups = await get_common_groups(cb.from_user.id)
    if not groups:
        await cb.message.answer(
            f"فرمانده:\nسرباز {username}، هیچ گروه مشترکی پیدا نشد! مطمئن شو که ربات در گروه اضافه شده و ادمین است ⚠️"
        )
        return

    if len(groups) == 1:
        # اگر فقط یک گروه باشه مستقیم فعالش کن
        user_active_group[cb.from_user.id] = groups[0][0]
        await show_panel(cb.message, username, groups[0][0])
        return

    kb_rows = [[InlineKeyboardButton(text=title or str(chat_id), callback_data=f"group_{chat_id}")] for chat_id, title in groups]
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    await cb.message.answer(
        f"فرمانده:\nسرباز {username}، انتخاب کن در کدام گروه پروفایلت فعال شود. فرمانده مراقب توست 👀",
        reply_markup=kb
    )

@dp.callback_query(lambda cb: cb.data.startswith("group_"))
async def select_group(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    chat_id = int(cb.data.split("_", 1)[1])

    # بررسی اینکه کاربر واقعا عضو اون گروه هست (get_common_groups این کار رو انجام میده ولی دوبار چک اضافه مشکلی ایجاد نمیکنه)
    common = await get_common_groups(user_id)
    if not any(chat_id == g[0] for g in common):
        await cb.answer("⚠️ شما در این گروه عضو نیستید یا ربات هنوز عضو نیست.", show_alert=True)
        return

    # بررسی ادمین بودن ربات در آن گروه
    if not await check_bot_admin(chat_id, cb):
        return

    # ثبت گروه فعال برای کاربر
    user_active_group[user_id] = chat_id

    username = cb.from_user.username or cb.from_user.first_name
    await show_panel(cb.message, username, chat_id)

@dp.message(Command("panel"))
async def cmd_panel(message: types.Message):
    username = message.from_user.username or message.from_user.first_name
    # اگر کاربر گروه فعال قبلی داشت از اون استفاده کن
    chat_id = user_active_group.get(message.from_user.id)
    await show_panel(message, username, chat_id)

async def show_panel(message: types.Message, username: str, chat_id: Optional[int]):
    if chat_id is None:
        # اگر گروه فعال مشخص نباشه به کاربر می‌گیم اول گروه انتخاب کنه
        await message.answer("⚠️ ابتدا باید یک گروه انتخاب کنید. /start بزن و گروه را انتخاب کن.")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 موجودی", callback_data="inventory")],
        [InlineKeyboardButton(text="🛒 فروشگاه", callback_data="shop"),
         InlineKeyboardButton(text="💱 تبادل", callback_data="exchange")],
        [InlineKeyboardButton(text="🏗️ دکل‌ها", callback_data="rigs"),
         InlineKeyboardButton(text="🛩️ آشیانه‌ها", callback_data="hangars")],
        [InlineKeyboardButton(text="🌍 گروه سراری", callback_data="guilds")]
    ])
    await message.answer(f"فرمانده:\n سرباز {username}، پنل وضعیتت برای گروه انتخاب‌شده آماده است. دقت کن هر حرکتت ثبت می‌شود ⚔️", reply_markup=kb)

@dp.callback_query(lambda cb: cb.data == "inventory")
async def callback_inventory(cb: types.CallbackQuery):
    # گروه فعال کاربر را بگیر
    chat_id = user_active_group.get(cb.from_user.id)
    if not chat_id:
        await cb.answer("⚠️ ابتدا یک گروه انتخاب کن (از طریق /start).", show_alert=True)
        return
    # چک ادمین بودن ربات در آن گروه
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

# ------------------ Challenge & Missions ------------------
group_challenge_tasks: Dict[int, asyncio.Task] = {}
group_mission_tasks: Dict[int, asyncio.Task] = {}

active_challenges: Dict[int, Dict] = {}  # chat_id -> challenge info

async def run_group_challenges(chat_id: int):
    while True:
        delay = random.randint(5*60, 30*60)
        await asyncio.sleep(delay)

        # بررسی ادمین بودن قبل از ارسال پیام
        if not await check_bot_admin(chat_id, None):
            continue  # اگر ربات ادمین نیست، چالش اجرا نشود

        challenge = await db.fetchone("SELECT * FROM challenges ORDER BY RANDOM() LIMIT 1")
        if not challenge:
            continue

        try:
            msg = await bot.send_message(
                chat_id,
                f"فرمانده:\n سربازان! آماده باشید ⚔️\n\nچالش: {challenge['text']}\n⏱ زمان: 90 ثانیه"
            )
        except Exception:
            continue

        start_time = datetime.utcnow()
        end_time = start_time + timedelta(seconds=90)
        active_challenges[chat_id] = {
            "challenge": challenge,
            "message_id": msg.message_id,
            "start_time": start_time,
            "end_time": end_time,
            "answered_by": None
        }

        try:
            await db.execute(
                "INSERT INTO group_challenges(chat_id, challenge_id, message_id, start_time, end_time, active) "
                "VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT (chat_id) DO UPDATE SET "
                "challenge_id=$2, message_id=$3, start_time=$4, end_time=$5, active=$6",
                (chat_id, challenge['id'], msg.message_id, start_time, end_time, 1)
            )
        except Exception:
            pass

        # Timer — توجه: برای جلوگیری از rate-limit بهتره هر 2-3 ثانیه آپدیت کنید،
        # ولی برای تجربه دقیق شما این کد هر ثانیه آپدیت می‌کند (در صورت نیاز می‌توان کاهش داد)
        for remaining in range(90, 0, -1):
            try:
                await msg.edit_text(
                    f"فرمانده:\n سربازان! آماده باشید ⚔️\n\nچالش: {challenge['text']}\n⏱ زمان: {remaining} ثانیه"
                )
            except Exception:
                break
            await asyncio.sleep(1)

        # پایان چالش
        info = active_challenges.pop(chat_id, None)
        if info and not info["answered_by"]:
            try:
                await msg.edit_text(
                    f"فرمانده:\n زمان چالش به پایان رسید!\nپاسخ صحیح: {challenge['answer']}"
                )
            except Exception:
                pass

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
        # کسی قبلاً پاسخ صحیح داده، هیچ جایزه‌ای داده نشود
        return

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
        await message.reply(f"فرمانده:\n تبریک سرباز {message.from_user.username}! 🎉\n"
                            f"جوایز شما: 💰 {reward_money}, 🛢️ {reward_oil}")
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=info["message_id"],
                text=f"چالش: {challenge['text']}\n✅ پاسخ صحیح داده شد توسط {message.from_user.username}\n⏱ زمان باقی‌مانده: {(info['end_time'] - datetime.utcnow()).seconds} ثانیه"
            )
        except Exception:
            pass
        
# بخش اضافی برای اجرای ماموریت‌ها و اهدا جایزه
async def check_mission_completion(chat_id: int):
    missions = await db.fetchall("SELECT * FROM group_missions WHERE chat_id=$1 AND status='pending'", (chat_id,))
    for mission in missions:
        # مثال ساده: چک کنیم اگر ماموریت تکمیل شده باشد، کاربر مشخص برنده شود
        # فرض می‌کنیم user_id ست شده وقتی کاربر ماموریت را انجام داد
        if mission["user_id"] != 0:
            user = await db.fetchone("SELECT username FROM users WHERE user_id=$1", (mission["user_id"],))
            if not user:
                continue
            # اهدا جایزه به برنده
            reward_money = 100  # می‌توان متغیر گذاشت
            reward_oil = 100
            try:
                await db.execute(
                    "UPDATE users SET money_amount = money_amount + $1, oil_amount = oil_amount + $2 WHERE user_id=$3",
                    (reward_money, reward_oil, mission["user_id"])
                )
                # تغییر وضعیت ماموریت
                await db.execute(
                    "UPDATE group_missions SET status='completed' WHERE chat_id=$1 AND mission_id=$2 AND user_id=$3",
                    (chat_id, mission["mission_id"], mission["user_id"])
                )
            except Exception:
                pass

            # اگر ربات ادمین نیست پیام گروه ارسال نشود
            if not await check_bot_admin(chat_id, None):
                continue
            # ارسال پیام در گروه
            try:
                await bot.send_message(
                    chat_id,
                    f"فرمانده:\n سرباز {user['username']} ماموریت `{mission['mission_id']}` را تکمیل کرد! 🎖️\n"
                    f"جوایز: 💰 {reward_money}, 🛢️ {reward_oil}"
                )
            except Exception:
                pass


async def run_group_missions(chat_id: int):
    while True:
        row = await db.fetchone("SELECT last_update FROM group_missions_schedule WHERE chat_id=$1", (chat_id,))
        now = datetime.utcnow()
        if row is None or (now - row["last_update"]).total_seconds() >= 8*3600:
            # refresh missions
            missions = await db.fetchall("SELECT * FROM missions ORDER BY RANDOM() LIMIT 3")
            await db.execute("DELETE FROM group_missions WHERE chat_id=$1", (chat_id,))
            for m in missions:
                await db.execute("INSERT INTO group_missions(chat_id, mission_id, user_id, status) VALUES($1,$2,0,'pending')", (chat_id, m['id']))
            await db.execute("INSERT INTO group_missions_schedule(chat_id, last_update) VALUES($1,$2) "
                             "ON CONFLICT (chat_id) DO UPDATE SET last_update=$2", (chat_id, now))
        await check_mission_completion(chat_id)
        await asyncio.sleep(300)  # check every 5 minutes

# ------------------ Bootstrap ------------------
async def main():
    await init_db()
    # create tasks for groups that are already known in DB
    groups = await db.fetchall("SELECT chat_id FROM groups")
    for g in groups:
        chat_id = g["chat_id"]
        # create tasks if not already existing
        if chat_id not in group_challenge_tasks:
            c_task = asyncio.create_task(run_group_challenges(chat_id))
            group_challenge_tasks[chat_id] = c_task
        if chat_id not in group_mission_tasks:
            m_task = asyncio.create_task(run_group_missions(chat_id))
            group_mission_tasks[chat_id] = m_task

    print("Start polling...")
    # حذف webhook قبلی برای جلوگیری از TelegramConflictError
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped!")
