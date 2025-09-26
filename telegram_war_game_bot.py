# -----------------------------------------------------------------------------
# |                      World War Telegram Mini-Game Bot                     |
# |                  Refactored & Optimized for aiogram v3.7.x                |
# |                                By Amiro                                   |
# -----------------------------------------------------------------------------

import os
import asyncio
import random
import datetime
import json
from typing import Optional, List, Tuple, Dict, Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ChatType
from aiogram.filters import Command
from aiogram.types import Message
import asyncpg
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# --- تنظیمات بازی ---
JETS_BY_COUNTRY: Dict[str, List[str]] = {
    "ایران": ["کوثر", "صاعقه", "آذرخش"],
    "روسیه": ["سوخو-35", "میگ-29", "یاک-130"],
    "آمریکا": ["F-35", "F-16", "F-22"]
}
MISSILES_BY_COUNTRY: Dict[str, List[str]] = {
    "ایران": ["ذوالفقار", "خرمشهر", "قیام"],
    "روسیه": ["اسکندر", "کالیبر", "کینجال"],
    "آمریکا": ["تام‌هاوک", "جبلین", "پاترِئوت"]
}

# آمار پایه (متعادل)
JET_STATS = {
    # health, attack_time(sec), fuel_consumption_percent_per_attack, missile_slots
    "default": (100, 30, 10, 2)
}
MISSILE_STATS = {
    # damage, price
    "default": (50, 1000)
}
DEFENSE_STATS = {
    # damage_reduction_percent, counter_damage, missile_cost
    "default": (20, 25, 800)
}

# پارامترهای دکل اولیه
INITIAL_RIG = {
    "level": 1,
    "health": -1,  # -1 یعنی غیرقابل نابودی (دکل اولیه)
    "capacity": 1000,
    "production": 1
}

# متغیر کلی اتصال دیتابیس
db_pool: Optional[asyncpg.Pool] = None

# --- دیتابیس ---
async def create_db_pool() -> asyncpg.Pool:
    return await asyncpg.create_pool(DATABASE_URL)

async def setup_tables(pool: asyncpg.Pool):
    async with pool.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            country TEXT DEFAULT 'ایران',
            exp BIGINT DEFAULT 0,
            money BIGINT DEFAULT 0
        );
        """)
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS rigs (
            user_id BIGINT PRIMARY KEY,
            level INT DEFAULT 1,
            health INT DEFAULT -1,
            oil BIGINT DEFAULT 0,
            capacity INT DEFAULT 1000,
            production INT DEFAULT 1
        );
        """)
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS fighters (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            name TEXT,
            health INT,
            last_attack TIMESTAMP,
            fuel_percent INT DEFAULT 100,
            missiles JSONB DEFAULT '[]'::jsonb
        );
        """)
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS defenses (
            user_id BIGINT PRIMARY KEY,
            reduction_percent INT DEFAULT 0,
            missiles JSONB DEFAULT '[]'::jsonb
        );
        """)
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS group_missions (
            chat_id BIGINT,
            mission_id BIGINT,
            status TEXT,
            PRIMARY KEY (chat_id, mission_id)
        );
        """)
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            chat_id BIGINT PRIMARY KEY
        );
        """)

# --- کمک‌کننده‌ها ---
async def add_user_if_missing(pool: asyncpg.Pool, user_id: int, country: str = "ایران"):
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("""
            INSERT INTO users (user_id, country) VALUES ($1, $2)
            ON CONFLICT (user_id) DO NOTHING;
            """, user_id, country)
            await conn.execute("""
            INSERT INTO rigs (user_id, level, health, oil, capacity, production)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (user_id) DO NOTHING;
            """, user_id, INITIAL_RIG["level"], INITIAL_RIG["health"], 0, INITIAL_RIG["capacity"], INITIAL_RIG["production"])
            # defenses default row not created until needed

async def user_is_admin_in_chat(chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except Exception:
        return False

async def get_user(pool: asyncpg.Pool, user_id: int) -> Optional[asyncpg.Record]:
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM users WHERE user_id=$1;", user_id)

async def change_money(pool: asyncpg.Pool, user_id: int, delta: int):
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET money = money + $1 WHERE user_id=$2;", delta, user_id)

async def change_exp(pool: asyncpg.Pool, user_id: int, delta: int):
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET exp = exp + $1 WHERE user_id=$2;", delta, user_id)

# --- حلقه‌های پس‌زمینه ---
async def produce_oil_loop(pool: asyncpg.Pool):
    while True:
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch("SELECT user_id, oil, production, capacity FROM rigs;")
                for r in rows:
                    new_oil = min(r["oil"] + r["production"], r["capacity"])
                    if new_oil != r["oil"]:
                        await conn.execute("UPDATE rigs SET oil=$1 WHERE user_id=$2;", new_oil, r["user_id"])
        except Exception:
            pass
        await asyncio.sleep(60)

async def reduce_rig_health_loop(pool: asyncpg.Pool):
    while True:
        try:
            async with pool.acquire() as conn:
                await conn.execute("""
                UPDATE rigs SET health = health - 1
                WHERE health > 0;
                """)
        except Exception:
            pass
        await asyncio.sleep(2 * 3600)

async def random_challenges_loop(pool: asyncpg.Pool):
    while True:
        delay = random.randint(20 * 60, 300 * 60)
        await asyncio.sleep(delay)
        try:
            async with pool.acquire() as conn:
                groups = await conn.fetch("SELECT chat_id FROM groups;")
                for g in groups:
                    mission_id = random.randint(1, 999999)
                    await conn.execute("""
                    INSERT INTO group_missions (chat_id, mission_id, status)
                    VALUES ($1, $2, 'active')
                    ON CONFLICT (chat_id, mission_id) DO NOTHING;
                    """, g["chat_id"], mission_id)
                    try:
                        await bot.send_message(g["chat_id"], f"چالش جدید: ماموریت #{mission_id} فعال شد. فرمانده میگه آماده شین.")
                    except Exception:
                        pass
        except Exception:
            pass

# --- دستورات و منطق بازی ---
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await add_user_if_missing(db_pool, message.from_user.id, "ایران")
    await message.answer("خوش‌آمدی سرباز. فرمانده اینجاس؛ اطاعت کن یا از بین برو.")

@dp.message(Command("register_group"))
async def cmd_register_group(message: Message):
    if message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        is_admin = await user_is_admin_in_chat(message.chat.id, message.from_user.id)
        if not is_admin:
            await message.answer("من ادمین نیستم، همین.")
            return
        async with db_pool.acquire() as conn:
            await conn.execute("INSERT INTO groups (chat_id) VALUES ($1) ON CONFLICT (chat_id) DO NOTHING;", message.chat.id)
        await message.answer("گروه ثبت شد. آماده باش برای دستور بعدی از طرف من.")
    else:
        await message.answer("این دستور فقط برای گروه‌هاست. خصوصی؟ بزن ادامه رو.")

@dp.message(Command("shop"))
async def cmd_shop(message: Message):
    if message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        is_admin = await user_is_admin_in_chat(message.chat.id, message.from_user.id)
        if not is_admin:
            await message.answer("من ادمین نیستم، همین.")
            return
    text = (
        "فروشگاه:\n"
        "/buy_rig - خرید دکل (+سطح، سلامتی محدود)\n"
        "/upgrade_rig - ارتقاء دکل (نیاز تجربه و پول)\n"
        "/buy_fighter - خرید جنگنده\n"
        "/buy_missile - خرید موشک برای پدافند یا جنگنده\n"
        "/status - دیدن وضعیت کلی\n"
    )
    await message.answer(text)

@dp.message(Command("buy_rig"))
async def cmd_buy_rig(message: Message):
    if message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        is_admin = await user_is_admin_in_chat(message.chat.id, message.from_user.id)
        if not is_admin:
            await message.answer("من ادمین نیستم، همین.")
            return
    user_id = message.from_user.id
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT money, exp FROM users WHERE user_id=$1;", user_id)
        if not row:
            await add_user_if_missing(db_pool, user_id)
            row = await conn.fetchrow("SELECT money, exp FROM users WHERE user_id=$1;", user_id)
        money = row["money"]
        exp = row["exp"]
        cost = 5000
        exp_req = 100
        if money < cost or exp < exp_req:
            await message.answer("پول یا تجربه نداری. برو کار کن بعد بیا.")
            return
        async with conn.transaction():
            await conn.execute("UPDATE users SET money = money - $1 WHERE user_id=$2;", cost, user_id)
            await conn.execute("""
            UPDATE rigs SET level = level + 1, health = 10, capacity = capacity + 500, production = production + 1
            WHERE user_id=$1;
            """, user_id)
        await message.answer("دکل خریدی. این یکی قابل نابود شدنه، مراقب باش.")

@dp.message(Command("upgrade_rig"))
async def cmd_upgrade_rig(message: Message):
    if message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        is_admin = await user_is_admin_in_chat(message.chat.id, message.from_user.id)
        if not is_admin:
            await message.answer("من ادمین نیستم، همین.")
            return
    user_id = message.from_user.id
    async with db_pool.acquire() as conn:
        rig = await conn.fetchrow("SELECT level FROM rigs WHERE user_id=$1;", user_id)
        if not rig:
            await add_user_if_missing(db_pool, user_id)
            rig = await conn.fetchrow("SELECT level FROM rigs WHERE user_id=$1;", user_id)
        next_level = rig["level"] + 1
        cost = next_level * 4000
        exp_req = next_level * 200
        user = await conn.fetchrow("SELECT money, exp FROM users WHERE user_id=$1;", user_id)
        if user["money"] < cost or user["exp"] < exp_req:
            await message.answer("پول یا تجربه کافی نداری برای ارتقاء. تلاش کن.")
            return
        async with conn.transaction():
            await conn.execute("UPDATE users SET money = money - $1, exp = exp - $2 WHERE user_id=$3;", cost, exp_req, user_id)
            await conn.execute("UPDATE rigs SET level = level + 1, health = 15, capacity = capacity + 700, production = production + 2 WHERE user_id=$1;", user_id)
        await message.answer("دکل ارتقاء یافت. قدرتمند شدی ولی مسئولیت هم داری.")

@dp.message(Command("rig"))
async def cmd_rig_status(message: Message):
    user_id = message.from_user.id
    async with db_pool.acquire() as conn:
        rig = await conn.fetchrow("SELECT level, health, oil, capacity, production FROM rigs WHERE user_id=$1;", user_id)
        if not rig:
            await add_user_if_missing(db_pool, user_id)
            rig = await conn.fetchrow("SELECT level, health, oil, capacity, production FROM rigs WHERE user_id=$1;", user_id)
        health_text = "نامحدود" if rig["health"] == -1 else str(rig["health"])
        await message.answer(f"دکل: سطح {rig['level']}\nسلامت: {health_text}\nنفت: {rig['oil']}/{rig['capacity']}\nتولید: {rig['production']}/دقیقه")

@dp.message(Command("buy_fighter"))
async def cmd_buy_fighter(message: Message):
    if message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        is_admin = await user_is_admin_in_chat(message.chat.id, message.from_user.id)
        if not is_admin:
            await message.answer("من ادمین نیستم، همین.")
            return
    user_id = message.from_user.id
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT money, country FROM users WHERE user_id=$1;", user_id)
        if not user:
            await add_user_if_missing(db_pool, user_id)
            user = await conn.fetchrow("SELECT money, country FROM users WHERE user_id=$1;", user_id)
        cost = 2000
        if user["money"] < cost:
            await message.answer("پول نداری. زود باش کار کن.")
            return
        jets = JETS_BY_COUNTRY.get(user["country"], JETS_BY_COUNTRY["ایران"])
        name = random.choice(jets)
        health, attack_time, fuel_cons, missile_slots = JET_STATS["default"]
        async with conn.transaction():
            await conn.execute("UPDATE users SET money = money - $1 WHERE user_id=$2;", cost, user_id)
            await conn.execute("""
            INSERT INTO fighters (user_id, name, health, last_attack, fuel_percent, missiles)
            VALUES ($1, $2, $3, $4, $5, $6);
            """, user_id, name, health, datetime.datetime.utcnow(), 100, json.dumps([]))
        await message.answer(f"جنگنده خریدی: {name}. سوخت 100%، موشک نداری فعلاً.")

@dp.message(Command("buy_missile"))
async def cmd_buy_missile(message: Message):
    if message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        is_admin = await user_is_admin_in_chat(message.chat.id, message.from_user.id)
        if not is_admin:
            await message.answer("من ادمین نیستم، همین.")
            return
    user_id = message.from_user.id
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT money, country FROM users WHERE user_id=$1;", user_id)
        if not user:
            await add_user_if_missing(db_pool, user_id)
            user = await conn.fetchrow("SELECT money, country FROM users WHERE user_id=$1;", user_id)
        missiles = MISSILES_BY_COUNTRY.get(user["country"], MISSILES_BY_COUNTRY["ایران"])
        name = random.choice(missiles)
        damage, price = MISSILE_STATS["default"]
        if user["money"] < price:
            await message.answer("پول نداری. برگرد پول جمع کن.")
            return
        async with conn.transaction():
            await conn.execute("UPDATE users SET money = money - $1 WHERE user_id=$2;", price, user_id)
            row = await conn.fetchrow("SELECT missiles FROM defenses WHERE user_id=$1;", user_id)
            if row:
                current = row["missiles"]
                new_list = current + [name]
                await conn.execute("UPDATE defenses SET missiles = $1 WHERE user_id=$2;", json.dumps(new_list), user_id)
            else:
                await conn.execute("INSERT INTO defenses (user_id, reduction_percent, missiles) VALUES ($1, $2, $3);", user_id, DEFENSE_STATS["default"][0], json.dumps([name]))
        await message.answer(f"موشک {name} خریداری شد. آماده دفاع یا ضدحمله.")

@dp.message(Command("status"))
async def cmd_status(message: Message):
    user_id = message.from_user.id
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT money, exp, country FROM users WHERE user_id=$1;", user_id)
        if not user:
            await add_user_if_missing(db_pool, user_id)
            user = await conn.fetchrow("SELECT money, exp, country FROM users WHERE user_id=$1;", user_id)
        rig = await conn.fetchrow("SELECT level, health, oil, capacity, production FROM rigs WHERE user_id=$1;", user_id)
        fighters = await conn.fetch("SELECT id, name, health, fuel_percent, missiles FROM fighters WHERE user_id=$1;", user_id)
        defense = await conn.fetchrow("SELECT reduction_percent, missiles FROM defenses WHERE user_id=$1;", user_id)
        health_text = "نامحدود" if rig["health"] == -1 else str(rig["health"])
        text = f"پول: {user['money']}\nتجربه: {user['exp']}\nکشور: {user['country']}\n\nدکل: سطح {rig['level']}, سلامت: {health_text}, نفت: {rig['oil']}/{rig['capacity']}\n\nجنگنده‌ها:\n"
        if fighters:
            for f in fighters:
                text += f"- #{f['id']} {f['name']} | سلامتی: {f['health']} | سوخت: {f['fuel_percent']}% | موشک‌ها: {len(f['missiles'])}\n"
        else:
            text += "هیچ جنگنده‌ای نداری.\n"
        if defense:
            text += f"\nپدافند: کاهش {defense['reduction_percent']}% | موشک‌ها: {len(defense['missiles'])}\n"
        await message.answer(text)

@dp.message(Command("launch_attack"))
async def cmd_launch_attack(message: Message):
    # دستور: /launch_attack <target_user_id> <fighter_id> [use_missile]
    if message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        is_admin = await user_is_admin_in_chat(message.chat.id, message.from_user.id)
        if not is_admin:
            await message.answer("من ادمین نیستم، همین.")
            return
    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("دستور اشتباهه. فرمت: /launch_attack <target_user_id> <fighter_id> [use_missile]")
        return
    try:
        target_id = int(parts[1])
        fighter_id = int(parts[2])
        use_missile_flag = False
        if len(parts) >= 4 and parts[3].lower() in ("1", "true", "yes", "y"):
            use_missile_flag = True
    except Exception:
        await message.answer("پارامترها نامعتبر هستند.")
        return
    attacker_id = message.from_user.id
    async with db_pool.acquire() as conn:
        attacker_fighter = await conn.fetchrow("SELECT id, name, health, last_attack, fuel_percent, missiles FROM fighters WHERE id=$1 AND user_id=$2;", fighter_id, attacker_id)
        if not attacker_fighter:
            await message.answer("جنگنده پیدا نشد یا برای تو نیست.")
            return
        now = datetime.datetime.utcnow()
        last_attack = attacker_fighter["last_attack"] or (now - datetime.timedelta(seconds=99999))
        attack_interval = JET_STATS["default"][1]
        elapsed = (now - last_attack).total_seconds()
        if elapsed < attack_interval:
            await message.answer(f"آماده نیستی هنوز. باید {int(attack_interval - elapsed)} ثانیه صبر کنی.")
            return
        if attacker_fighter["fuel_percent"] < JET_STATS["default"][2]:
            await message.answer("سوخت جنگنده کافی نیست.")
            return
        # محاسبه دمیج
        base_damage = 30
        missile_damage = 0
        missiles_list = attacker_fighter["missiles"] or []
        if use_missile_flag and missiles_list:
            missile_name = missiles_list[0]
            missile_damage = MISSILE_STATS["default"][0]
            missiles_list = missiles_list[1:]
            await conn.execute("UPDATE fighters SET missiles = $1 WHERE id=$2;", json.dumps(missiles_list), fighter_id)
        total_damage = base_damage + missile_damage
        # کاهش سوخت
        new_fuel = max(0, attacker_fighter["fuel_percent"] - JET_STATS["default"][2])
        await conn.execute("UPDATE fighters SET fuel_percent=$1, last_attack=$2 WHERE id=$3;", new_fuel, now, fighter_id)
        # هدف: کاهش سلامتی دکل یا جنگنده هدف (اگر جنگنده داره)
        target_fighter = await conn.fetchrow("SELECT id, user_id, name, health FROM fighters WHERE id=$1;", target_id)
        if target_fighter:
            # هدف یک جنگنده است
            defender = await conn.fetchrow("SELECT reduction_percent, missiles FROM defenses WHERE user_id=$1;", target_fighter["user_id"])
            reduction = defender["reduction_percent"] if defender else 0
            damage_after = int(total_damage * (100 - reduction) / 100)
            # اعمال دمیج
            new_health = target_fighter["health"] - damage_after
            await conn.execute("UPDATE fighters SET health=$1 WHERE id=$2;", new_health, target_id)
            # پدافند ممکن است ضدحمله کند
            if defender and defender["missiles"]:
                def_missiles = list(defender["missiles"])
                counter_missile = def_missiles.pop(0)
                counter_damage = DEFENSE_STATS["default"][1]
                await conn.execute("UPDATE defenses SET missiles=$1 WHERE user_id=$2;", json.dumps(def_missiles), target_fighter["user_id"])
                # اعمال دمیج به جنگنده مهاجم (به سادگی اولین جنگنده مهاجم)
                await conn.execute("UPDATE fighters SET health = health - $1 WHERE id=$2;", counter_damage, fighter_id)
                await message.answer(f"حمله اجرا شد. هدف: جنگنده #{target_id}. کاهش پدافند {reduction}%. پدافند دشمن با موشک {counter_missile} ضدحمله کرد.")
            else:
                await message.answer(f"حمله اجرا شد. هدف: جنگنده #{target_id}. دمیج وارد شد: {damage_after}.")
            return
        # اگر هدف جنگنده نبود، فرض را بر دکل می‌گذاریم
        rig = await conn.fetchrow("SELECT user_id, level, health FROM rigs WHERE user_id=$1;", target_id)
        if rig:
            defender = await conn.fetchrow("SELECT reduction_percent, missiles FROM defenses WHERE user_id=$1;", target_id)
            reduction = defender["reduction_percent"] if defender else 0
            damage_after = int(total_damage * (100 - reduction) / 100)
            # اگر health == -1 (غیرقابل نابودی)، فقط کاهش نفت یا اثر نمایشی
            if rig["health"] == -1:
                # کاهش نفت به عنوان پیام: مقدار کوچکی کم می‌شود
                await conn.execute("UPDATE rigs SET oil = GREATEST(oil - $1, 0) WHERE user_id=$2;", damage_after, target_id)
                await message.answer(f"حمله به دکل بی‌اثر بود؛ دکل اولیه غیرقابل نابودیست اما نفتش {damage_after} واحد کاهش یافت.")
            else:
                new_health = rig["health"] - damage_after
                await conn.execute("UPDATE rigs SET health=$1 WHERE user_id=$2;", new_health, target_id)
                if defender and defender["missiles"]:
                    def_missiles = list(defender["missiles"])
                    counter_missile = def_missiles.pop(0)
                    counter_damage = DEFENSE_STATS["default"][1]
                    await conn.execute("UPDATE defenses SET missiles=$1 WHERE user_id=$2;", json.dumps(def_missiles), target_id)
                    await conn.execute("UPDATE fighters SET health = health - $1 WHERE id=$2;", counter_damage, fighter_id)
                    await message.answer(f"دکل ضربه خورد. پدافند هدف با موشک {counter_missile} ضدحمله کرد.")
                else:
                    await message.answer(f"دکل ضربه خورد. {damage_after} واحد آسیب وارد شد.")
            return
        await message.answer("هدف پیدا نشد. گیر دادم به هوا؟")

# هندلر عمومی برای جلوگیری از باز شدن پنل یا عملکرد مدیریتی در گروه توسط کاربران عادی
@dp.message()
async def catch_all(message: Message):
    if message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        is_admin = await user_is_admin_in_chat(message.chat.id, message.from_user.id)
        if not is_admin:
            await message.answer("من ادمین نیستم، همین.")
            return
    return

# --- شروع برنامه ---
async def main():
    global db_pool
    db_pool = await create_db_pool()
    await setup_tables(db_pool)
    # حلقه‌های پس‌زمینه
    asyncio.create_task(produce_oil_loop(db_pool))
    asyncio.create_task(reduce_rig_health_loop(db_pool))
    asyncio.create_task(random_challenges_loop(db_pool))
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
