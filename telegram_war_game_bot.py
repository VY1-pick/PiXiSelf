# bot.py

import os
import asyncio
import logging
import random
from datetime import datetime, timezone
import asyncpg
from aiogram.client.default import DefaultBotProperties
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    ChatMemberUpdated,
    ChatMemberAdministrator,
)
from aiogram.filters.chat_member_updated import ChatMemberUpdatedFilter, IS_NOT_MEMBER, MEMBER, ADMINISTRATOR

# --- کانفیگ و تنظیمات اولیه ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

# --- توکن و اطلاعات حساس از متغیرهای محیطی ---
# سرباز، اینا رو باید درست تنظیم کنی. شوخی ندارم.
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# --- ثابت‌های بازی ---
# این بخش، مغز متفکر استراتژی ماست. دستکاری بی‌مورد ممنوع.
INITIAL_MONEY = 10000
INITIAL_OIL = 500
QUIZ_REWARD = 500
# زمان چالش‌ها به دقیقه (حداقل و حداکثر)
QUIZ_INTERVAL_MIN_MINUTES = 20
QUIZ_INTERVAL_MAX_MINUTES = 300

# دیکشنری تجهیزات بر اساس کشور
# قدرت‌ها برای حفظ بالانس یکسان هستند، فقط نام‌ها تغییر می‌کنند
EQUIPMENT_DATA = {
    'آمریکا': {
        'fighters': {
            'F-16 Fighting Falcon': {'price': 150000, 'health': 100, 'fuel_capacity': 100, 'attack_cooldown_sec': 360, 'missile_slots': 5, 'compatible_missile': 'AIM-120 AMRAAM'},
        },
        'missiles': {
            'AIM-120 AMRAAM': {'price': 5000, 'damage': 25},
        }
    },
    'ایران': {
        'fighters': {
            'HESA Kowsar': {'price': 150000, 'health': 100, 'fuel_capacity': 100, 'attack_cooldown_sec': 360, 'missile_slots': 5, 'compatible_missile': 'Fakour-90'},
        },
        'missiles': {
            'Fakour-90': {'price': 5000, 'damage': 25},
        }
    },
    'روسیه': {
        'fighters': {
            'Sukhoi Su-35': {'price': 150000, 'health': 100, 'fuel_capacity': 100, 'attack_cooldown_sec': 360, 'missile_slots': 5, 'compatible_missile': 'R-77'},
        },
        'missiles': {
            'R-77': {'price': 5000, 'damage': 25},
        }
    },
    # آیتم‌های عمومی که وابسته به کشور نیستند
    'common': {
        'oil_rigs': {
            # سطح: {قیمت، تجربه لازم، ظرفیت، تولید در ساعت، سلامتی}
            2: {'price': 50000, 'xp_required': 100, 'capacity': 5000, 'production_per_hour': 500, 'health': 200},
            3: {'price': 200000, 'xp_required': 500, 'capacity': 20000, 'production_per_hour': 2000, 'health': 500},
        },
        'defense': {
            # سطح: {قیمت، تجربه لازم، درصد کاهش آسیب}
            1: {'price': 10000, 'xp_required': 50, 'reduction': 5},
            2: {'price': 50000, 'xp_required': 250, 'reduction': 10},
        }
    }
}


# --- کلاس مدیریت پایگاه داده ---
# تمام عملیات جنگی ما روی این ستون‌ها بنا شده.
class DBAdapter:
    def __init__(self, dsn):
        self.dsn = dsn
        self.pool = None

    async def connect(self):
        try:
            self.pool = await asyncpg.create_pool(self.dsn)
            logger.info("اتصال به پایگاه داده برقرار شد. آماده دریافت دستورات.")
        except Exception as e:
            logger.critical(f"خطای فاجعه‌بار در اتصال به دیتابیس: {e}")
            raise

    async def close(self):
        if self.pool:
            await self.pool.close()
            logger.info("اتصال به پایگاه داده قطع شد. پایان عملیات.")

    async def execute(self, query, *args):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                return await conn.execute(query, *args)

    async def fetch(self, query, *args):
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, *args)

    async def fetchrow(self, query, *args):
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query, *args)

    async def fetchval(self, query, *args):
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, *args)

    async def setup_schema(self):
        # بازسازی ساختار پایگاه داده برای عملیات جدید
        schema_queries = [
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                country TEXT,
                money BIGINT DEFAULT 0,
                oil BIGINT DEFAULT 0,
                xp INT DEFAULT 0,
                defense_level INT DEFAULT 0,
                active_group BIGINT,
                last_updated TIMESTAMP WITH TIME ZONE
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS oil_rigs (
                rig_id SERIAL PRIMARY KEY,
                owner_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                level INT NOT NULL,
                health INT, -- NULL for invulnerable rigs
                capacity INT NOT NULL,
                production_per_hour INT NOT NULL,
                is_invulnerable BOOLEAN DEFAULT FALSE,
                last_collected TIMESTAMP WITH TIME ZONE
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS fighters (
                fighter_id SERIAL PRIMARY KEY,
                owner_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                fighter_type TEXT NOT NULL,
                health INT NOT NULL,
                fuel INT NOT NULL,
                last_attack_time TIMESTAMP WITH TIME ZONE
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS missiles (
                missile_id SERIAL PRIMARY KEY,
                owner_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                missile_type TEXT NOT NULL,
                quantity INT NOT NULL,
                UNIQUE(owner_id, missile_type)
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS groups (
                chat_id BIGINT PRIMARY KEY,
                name TEXT,
                is_active BOOLEAN DEFAULT TRUE
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS group_missions (
                chat_id BIGINT NOT NULL,
                mission_id INT NOT NULL,
                user_id BIGINT,
                status TEXT DEFAULT 'pending',
                PRIMARY KEY (chat_id, mission_id)
            );
            """,
        ]
        logger.info("بررسی و اجرای ساختار پایگاه داده...")
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                for query in schema_queries:
                    await conn.execute(query)
        logger.info("ساختار پایگاه داده آماده است.")

    # --- متدهای مربوط به کاربر ---
    async def create_user(self, user_id):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # ایجاد کاربر
                await conn.execute(
                    "INSERT INTO users (user_id, money, oil, last_updated) VALUES ($1, $2, $3, $4) ON CONFLICT (user_id) DO NOTHING",
                    user_id, INITIAL_MONEY, INITIAL_OIL, datetime.now(timezone.utc)
                )
                # ایجاد دکل نفت اولیه و غیرقابل تخریب
                # چک می‌کنیم که کاربر از قبل دکل اولیه نداشته باشد
                has_initial_rig = await conn.fetchval(
                    "SELECT 1 FROM oil_rigs WHERE owner_id = $1 AND is_invulnerable = TRUE", user_id
                )
                if not has_initial_rig:
                    await conn.execute(
                        """
                        INSERT INTO oil_rigs (owner_id, level, health, capacity, production_per_hour, is_invulnerable, last_collected)
                        VALUES ($1, 1, NULL, 1000, 100, TRUE, $2)
                        """,
                        user_id, datetime.now(timezone.utc)
                    )

    async def get_user(self, user_id):
        # قبل از هر چیز، منابع کاربر رو آپدیت می‌کنیم
        await self.update_user_resources(user_id)
        return await self.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)

    async def set_user_country(self, user_id, country):
        await self.execute("UPDATE users SET country = $1 WHERE user_id = $2", country, user_id)

    async def get_user_rigs(self, user_id):
        return await self.fetch("SELECT * FROM oil_rigs WHERE owner_id = $1 ORDER BY level", user_id)

    async def update_user_resources(self, user_id):
        """
        این متد حیاتی، تولید نفت و کاهش سلامتی دکل‌ها را بر اساس زمان سپری شده محاسبه می‌کند.
        این کار به جای یک تسک پس‌زمینه انجام می‌شود تا بهینه باشد.
        """
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                user = await conn.fetchrow("SELECT oil, last_updated FROM users WHERE user_id = $1", user_id)
                if not user or not user['last_updated']:
                    return # کاربر یا آپدیت اولیه ندارد

                current_time = datetime.now(timezone.utc)
                time_diff_seconds = (current_time - user['last_updated']).total_seconds()
                
                # 1. محاسبه تولید نفت
                rigs = await conn.fetch("SELECT rig_id, production_per_hour, capacity, last_collected FROM oil_rigs WHERE owner_id = $1", user_id)
                total_oil_produced = 0
                for rig in rigs:
                    production_time_seconds = (current_time - rig['last_collected']).total_seconds()
                    # نفت تولید شده در این بازه
                    oil_this_rig = (rig['production_per_hour'] / 3600) * production_time_seconds
                    
                    # استخراج موجودی نفت از دکل (بدون سرریز شدن ظرفیت کل کاربر)
                    current_oil_in_storage = await conn.fetchval("SELECT oil FROM users WHERE user_id = $1", user_id)
                    
                    # ظرفیت خالی برای ذخیره نفت
                    # اینجا باید یک منطق کلی برای ظرفیت کل تعریف کنیم، فعلا فرض می‌کنیم بی‌نهایت است
                    # اما برای دکل، تولید نباید از ظرفیت خودش بیشتر بشه
                    
                    # TODO: منطق ظرفیت کلی انبار نفت
                    
                    total_oil_produced += oil_this_rig
                    await conn.execute("UPDATE oil_rigs SET last_collected = $1 WHERE rig_id = $2", current_time, rig['rig_id'])

                if total_oil_produced > 0:
                    await conn.execute("UPDATE users SET oil = oil + $1 WHERE user_id = $2", int(total_oil_produced), user_id)

                # 2. محاسبه کاهش سلامتی دکل‌های آسیب‌پذیر
                # هر 2 ساعت (7200 ثانیه) 1 واحد سلامتی کم می‌شود
                health_decay_amount = int(time_diff_seconds // 7200)
                if health_decay_amount > 0:
                    await conn.execute(
                        """
                        UPDATE oil_rigs
                        SET health = health - $1
                        WHERE owner_id = $2 AND is_invulnerable = FALSE AND health > 0
                        """,
                        health_decay_amount, user_id
                    )
                    # جلوگیری از منفی شدن سلامتی
                    await conn.execute(
                        "UPDATE oil_rigs SET health = 0 WHERE health < 0 AND owner_id = $1", user_id
                    )

                # 3. ثبت زمان آخرین آپدیت
                await conn.execute("UPDATE users SET last_updated = $1 WHERE user_id = $2", current_time, user_id)


# --- ماشین وضعیت برای انتخاب کشور ---
class Form(StatesGroup):
    choosing_country = State()

# --- نمونه‌سازی‌ها ---
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML)
dp = Dispatcher()
db = DBAdapter(DATABASE_URL)

# --- کوئری‌های از پیش آماده شده ---
# اینها برای ماموریت‌های گروهی استفاده می‌شوند
MISSIONS = [
    {"id": 1, "question": "پایتخت ایران کجاست؟", "answer": "تهران"},
    {"id": 2, "question": "فرمانده کل قوا کیست؟", "answer": "خودم"}, # شوخی نظامی!
    {"id": 3, "question": "کدام عدد اول است: 9 یا 11؟", "answer": "11"},
]


# --- کنترلرهای رویدادها (Handlers) ---

@dp.message(CommandStart())
async def command_start_handler(message: Message, state: FSMContext) -> None:
    """
    وقتی یک سرباز جدید به پایگاه می‌پیوندد.
    """
    user_id = message.from_user.id
    await db.create_user(user_id)
    user = await db.get_user(user_id)

    if user and user['country']:
        await message.answer(f"سرباز {message.from_user.first_name}، به پایگاه برگشتی. وقت تلف نکن. برای دیدن وضعیتت از دستور /panel استفاده کن.")
    else:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🇮🇷 ایران", callback_data="country_ایران")],
            [InlineKeyboardButton(text="🇺🇸 آمریکا", callback_data="country_آمریکا")],
            [InlineKeyboardButton(text="🇷🇺 روسیه", callback_data="country_روسیه")],
        ])
        await message.answer("هویتت رو مشخص کن، سرباز. به کدام جبهه وفاداری؟", reply_markup=keyboard)
        await state.set_state(Form.choosing_country)

@dp.callback_query(Form.choosing_country, F.data.startswith("country_"))
async def process_country_choice(callback: CallbackQuery, state: FSMContext):
    country = callback.data.split("_")[1]
    user_id = callback.from_user.id
    await db.set_user_country(user_id, country)
    await callback.message.edit_text(f"بسیار خب. وفاداری تو به {country} ثبت شد. حالا برو سر پستت. با دستور /panel وضعیتت رو چک کن.")
    await state.clear()
    await callback.answer()


@dp.message(Command("panel"))
async def panel_handler(message: Message):
    """
    پنل گزارش وضعیت سرباز.
    """
    if message.chat.type != 'private':
        await message.reply("پنل شخصی فقط در چت خصوصی قابل دسترسی است، نه در میدان جنگ.")
        return

    user_id = message.from_user.id
    user = await db.get_user(user_id)
    if not user or not user['country']:
        await message.answer("اول باید هویتت رو با /start مشخص کنی. سریع!")
        return
    
    # واکشی اطلاعات دارایی‌ها
    rigs = await db.get_user_rigs(user_id)
    # fighters = await db.get_user_fighters(user_id) # TODO
    # missiles = await db.get_user_missiles(user_id) # TODO

    # ساخت متن گزارش
    report = f"<b>گزارش وضعیت، سرباز {message.from_user.first_name}</b>\n\n"
    report += f"<b>جبهه:</b> {user['country']}\n"
    report += f"<b>خزانه:</b> {user['money']:,} سکه\n"
    report += f"<b>ذخیره نفت:</b> {user['oil']:,} لیتر\n"
    report += f"<b>درجه (XP):</b> {user['xp']}\n"
    report += f"<b>سطح پدافند:</b> {user['defense_level']}\n\n"
    report += "<b>--- تأسیسات نفتی ---</b>\n"
    if rigs:
        for rig in rigs:
            health_status = "عملیاتی" if rig['is_invulnerable'] else f"{rig['health']}%"
            report += f" - دکل سطح {rig['level']}: [ظرفیت: {rig['capacity']:,}] [تولید: {rig['production_per_hour']:,}/ساعت] [وضعیت: {health_status}]\n"
    else:
        report += "هیچ دکل نفتی‌ای در اختیار نداری. وضعیت اسفناک است.\n"
    
    # TODO: اضافه کردن گزارش جنگنده‌ها و موشک‌ها

    # ساخت دکمه‌های عملیاتی
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="فروشگاه", callback_data="shop_main")],
        [InlineKeyboardButton(text="حمله", callback_data="attack_target_select")],
        [InlineKeyboardButton(text="تعمیر و سوخت‌گیری", callback_data="maintenance_menu")],
    ])

    await message.answer(report, reply_markup=keyboard)


# --- مدیریت گروه ---
async def check_bot_admin(chat_id: int) -> bool:
    """بررسی می‌کند که آیا ربات در گروه ادمین است یا خیر."""
    try:
        chat_admins = await bot.get_chat_administrators(chat_id)
        bot_member = await bot.get_chat_member(chat_id, bot.id)
        return bot_member.status == 'administrator' or bot.id in [admin.user.id for admin in chat_admins]
    except Exception as e:
        logger.warning(f"خطا در بررسی ادمین بودن ربات در گروه {chat_id}: {e}")
        return False

@dp.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=(IS_NOT_MEMBER | MEMBER) >> ADMINISTRATOR))
async def bot_promoted_to_admin(event: ChatMemberUpdated):
    chat_id = event.chat.id
    await db.execute(
        "INSERT INTO groups (chat_id, name) VALUES ($1, $2) ON CONFLICT (chat_id) DO UPDATE SET is_active = TRUE, name = $2",
        chat_id, event.chat.title
    )
    logger.info(f"ربات در گروه '{event.chat.title}' ({chat_id}) به ادمین ارتقا یافت. گروه فعال شد.")
    try:
        await bot.send_message(chat_id, "فرماندهی این گروه را به دست گرفتم. از این پس، اینجا تحت نظارت من است.")
    except Exception as e:
        logger.error(f"Failed to send promotion message to {chat_id}: {e}")

@dp.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=ADMINISTRATOR >> (IS_NOT_MEMBER | MEMBER)))
async def bot_demoted_or_left(event: ChatMemberUpdated):
    chat_id = event.chat.id
    await db.execute("UPDATE groups SET is_active = FALSE WHERE chat_id = $1", chat_id)
    logger.info(f"ربات از ادمینی در گروه '{event.chat.title}' ({chat_id}) برکنار یا خارج شد. گروه غیرفعال شد.")


# --- تسک پس‌زمینه برای چالش‌های گروهی ---
async def run_group_missions():
    await asyncio.sleep(10) # تاخیر اولیه برای اطمینان از اتصال کامل
    logger.info("سرویس چالش‌های گروهی آغاز به کار کرد.")
    while True:
        try:
            active_groups = await db.fetch("SELECT chat_id FROM groups WHERE is_active = TRUE")
            for group in active_groups:
                chat_id = group['chat_id']
                
                # بررسی ادمین بودن قبل از ارسال پیام
                if not await check_bot_admin(chat_id):
                    logger.warning(f"ربات در گروه {chat_id} ادمین نیست. چالش ارسال نشد.")
                    await db.execute("UPDATE groups SET is_active = FALSE WHERE chat_id = $1", chat_id)
                    continue

                mission = random.choice(MISSIONS)
                # بررسی اینکه آیا این ماموریت قبلا در این گروه اجرا شده یا نه
                existing = await db.fetchval("SELECT 1 FROM group_missions WHERE chat_id = $1 AND mission_id = $2", chat_id, mission['id'])
                if existing:
                    # اگر همه ماموریت‌ها انجام شده، ریست می‌کنیم
                    count_missions = len(MISSIONS)
                    count_done = await db.fetchval("SELECT COUNT(*) FROM group_missions WHERE chat_id = $1", chat_id)
                    if count_done >= count_missions:
                        await db.execute("DELETE FROM group_missions WHERE chat_id = $1", chat_id)
                        logger.info(f"تمام ماموریت‌ها در گروه {chat_id} ریست شد.")
                    else:
                        continue # برو سراغ گروه بعدی

                await db.execute(
                    "INSERT INTO group_missions (chat_id, mission_id, status) VALUES ($1, $2, 'pending') ON CONFLICT (chat_id, mission_id) DO NOTHING",
                    chat_id, mission['id']
                )

                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="پاسخ بده", callback_data=f"quiz_answer_{mission['id']}")]
                ])
                # در این نسخه، به جای دکمه، مستقیما از کاربر می‌خواهیم جواب را ریپلای کند.
                await bot.send_message(chat_id, f"<b>چالش جدید!</b>\n\n{mission['question']}\n\nاولین نفری که به این پیام ریپلای صحیح بدهد، {QUIZ_REWARD} سکه جایزه می‌گیرد.")

        except Exception as e:
            logger.error(f"خطا در اجرای تسک چالش گروهی: {e}")

        # زمان انتظار تصادفی بین 20 تا 300 دقیقه
        sleep_duration = random.randint(QUIZ_INTERVAL_MIN_MINUTES * 60, QUIZ_INTERVAL_MAX_MINUTES * 60)
        logger.info(f"چالش بعدی تا {sleep_duration // 60} دقیقه دیگر اجرا خواهد شد.")
        await asyncio.sleep(sleep_duration)


@dp.message(F.reply_to_message)
async def handle_quiz_reply(message: Message):
    """
    پردازش پاسخ به پیام چالش.
    """
    if not message.reply_to_message or not message.reply_to_message.from_user.is_bot:
        return

    # پیدا کردن ماموریت مربوط به این پیام
    question_text = message.reply_to_message.text.split('\n\n')[1]
    mission = next((m for m in MISSIONS if m["question"] == question_text), None)

    if not mission:
        return

    chat_id = message.chat.id
    mission_status = await db.fetchrow("SELECT * FROM group_missions WHERE chat_id = $1 AND mission_id = $2", chat_id, mission['id'])

    if not mission_status or mission_status['status'] != 'pending':
        await message.reply("دیر رسیدی، سرباز. این چالش قبلاً حل شده.")
        return

    if message.text.strip().lower() == mission['answer'].lower():
        user_id = message.from_user.id
        user = await db.get_user(user_id)
        if not user:
            await db.create_user(user_id)
        
        await db.execute("UPDATE users SET money = money + $1 WHERE user_id = $2", QUIZ_REWARD, user_id)
        await db.execute(
            "UPDATE group_missions SET status = 'answered', user_id = $1 WHERE chat_id = $2 AND mission_id = $3",
            user_id, chat_id, mission['id']
        )
        
        await message.reply(f"پاسخ صحیح بود. {message.from_user.first_name} مبلغ {QUIZ_REWARD} سکه دریافت کرد. آفرین سرباز.")
        # ویرایش پیام اصلی برای جلوگیری از پاسخ‌های بیشتر
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message.reply_to_message.message_id,
                text=f"<b>چالش حل شد!</b>\n\n{mission['question']}\n\nپاسخ صحیح: {mission['answer']}\nبرنده: {message.from_user.first_name}"
            )
        except Exception as e:
            logger.warning(f"Failed to edit quiz message in {chat_id}: {e}")

# --- تابع اصلی برای اجرای ربات ---
async def main() -> None:
    # چک کردن توکن قبل از هر کاری
    if not BOT_TOKEN:
        logger.critical("توکن ربات تعریف نشده! عملیات لغو شد.")
        return
    if not DATABASE_URL:
        logger.critical("آدرس پایگاه داده تعریف نشده! عملیات لغو شد.")
        return

    # اتصال و راه‌اندازی پایگاه داده
    await db.connect()
    await db.setup_schema()

    # ایجاد تسک پس‌زمینه
    asyncio.create_task(run_group_missions())

    # شروع به گوش دادن به دستورات
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("دریافت سیگنال خاموشی... در حال پایان دادن به عملیات.")
    finally:
        # اطمینان از بسته شدن اتصال دیتابیس در هنگام خروج
        loop = asyncio.get_event_loop()
        loop.run_until_complete(db.close())
        logger.info("عملیات به پایان رسید.")

