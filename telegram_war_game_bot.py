import os
import asyncio
import random
import datetime
import json
from typing import Optional, List, Dict

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ChatType
from aiogram.filters import Command, ChatTypeFilter
from aiogram.filters.callback_data import CallbackData
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from aiogram.utils.keyboard import InlineKeyboardBuilder
import asyncpg
from dotenv import load_dotenv

# --- بارگذاری متغیرهای محیطی ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
if not BOT_TOKEN or not DATABASE_URL:
    raise ValueError("BOT_TOKEN و DATABASE_URL باید در فایل .env تعریف شوند.")

# --- نمونه‌سازی ربات و دیسپچر ---
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# متغیر کلی اتصال دیتابیس
db_pool: Optional[asyncpg.Pool] = None

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
JET_STATS = {"default": (100, 30, 10, 2)} # health, attack_time(sec), fuel_consumption, missile_slots
MISSILE_STATS = {"default": (50, 1000)} # damage, price
DEFENSE_STATS = {"default": (20, 25, 800)} # damage_reduction_%, counter_damage, missile_cost
INITIAL_RIG = {"level": 1, "health": -1, "capacity": 1000, "production": 1} # -1 health: indestructible

# --- CallbackData برای مدیریت پنل ---
class PanelCallback(CallbackData, prefix="panel"):
    action: str
    chat_id: Optional[int] = None
    item_id: Optional[str] = None

# --- دیتابیس ---
async def create_db_pool() -> asyncpg.Pool:
    """ایجاد یک استخر اتصال به دیتابیس."""
    return await asyncpg.create_pool(DATABASE_URL)

async def setup_tables(pool: asyncpg.Pool):
    """ایجاد جداول دیتابیس در صورت عدم وجود."""
    async with pool.acquire() as conn:
        # جدول کاربران حالا به chat_id وابسته است
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT,
            chat_id BIGINT,
            country TEXT DEFAULT 'ایران',
            exp BIGINT DEFAULT 0,
            money BIGINT DEFAULT 10000,
            PRIMARY KEY (user_id, chat_id)
        );
        """)
        # جدول دکل‌ها
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS rigs (
            user_id BIGINT,
            chat_id BIGINT,
            level INT DEFAULT 1,
            health INT DEFAULT -1,
            oil BIGINT DEFAULT 0,
            capacity INT DEFAULT 1000,
            production INT DEFAULT 1,
            PRIMARY KEY (user_id, chat_id)
        );
        """)
        # جدول جنگنده‌ها
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS fighters (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            chat_id BIGINT,
            name TEXT,
            health INT,
            last_attack TIMESTAMP,
            fuel_percent INT DEFAULT 100,
            missiles JSONB DEFAULT '[]'::jsonb
        );
        """)
        # جدول پدافند
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS defenses (
            user_id BIGINT,
            chat_id BIGINT,
            reduction_percent INT DEFAULT 0,
            missiles JSONB DEFAULT '[]'::jsonb,
            PRIMARY KEY (user_id, chat_id)
        );
        """)
        # جدول گروه‌های ثبت‌شده
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            chat_id BIGINT PRIMARY KEY,
            chat_title TEXT
        );
        """)

# --- توابع کمکی ---
async def add_user_profile_if_missing(pool: asyncpg.Pool, user_id: int, chat_id: int):
    """یک پروفایل کاربری برای یک گروه خاص ایجاد می‌کند اگر وجود نداشته باشد."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            # افزودن به جدول users
            await conn.execute("""
            INSERT INTO users (user_id, chat_id, country) VALUES ($1, $2, 'ایران')
            ON CONFLICT (user_id, chat_id) DO NOTHING;
            """, user_id, chat_id)
            # افزودن دکل اولیه
            await conn.execute("""
            INSERT INTO rigs (user_id, chat_id, level, health, oil, capacity, production)
            VALUES ($1, $2, $3, $4, 0, $5, $6)
            ON CONFLICT (user_id, chat_id) DO NOTHING;
            """, user_id, chat_id, INITIAL_RIG["level"], INITIAL_RIG["health"], INITIAL_RIG["capacity"], INITIAL_RIG["production"])

async def is_bot_admin(chat_id: int) -> bool:
    """بررسی می‌کند که آیا ربات در گروه ادمین است یا خیر."""
    try:
        me = await bot.get_chat_member(chat_id, bot.id)
        return me.status in ("administrator", "creator")
    except Exception:
        return False

# --- Middleware برای کنترل دسترسی در گروه‌ها ---
class AdminAccessMiddleware:
    async def __call__(self, handler, event: Message, data: dict):
        if event.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
            # اگر پیام یک کامند باشد یا از طرف یک کاربر باشد
            if event.text and event.text.startswith('/'):
                if not await is_bot_admin(event.chat.id):
                    await event.answer("فرمانده در جایگاه خودش نیست و علاقه‌ای به فرمان دادن ندارد.")
                    return
        return await handler(event, data)

dp.message.middleware(AdminAccessMiddleware())

# --- هندلرهای دستورات ---
@dp.message(Command("start"), ChatTypeFilter(ChatType.PRIVATE))
async def cmd_start_private(message: Message):
    """پاسخ به دستور /start در چت خصوصی."""
    bot_user = await bot.get_me()
    bot_username = bot_user.username
    
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(
        text="➕ افزودن ربات به گروه",
        url=f"https://t.me/{bot_username}?startgroup=true"
    ))
    
    welcome_text = (
        "<b>خوش‌آمدی سرباز!</b>\n\n"
        "من فرمانده میدان نبرد هستم. برای شروع، من را به گروه خود اضافه کن و ادمین کن تا پایگاه نظامی شما را ثبت کنم.\n\n"
        "<tg-spoiler>ℹ️ برای دسترسی به پنل مدیریت، از دستور /panel استفاده کن.</tg-spoiler>"
    )
    await message.answer(welcome_text, reply_markup=keyboard.as_markup())

@dp.message(F.new_chat_members)
async def on_new_chat_members(message: Message):
    """واکنش به اضافه شدن اعضای جدید به گروه (از جمله خود ربات)."""
    bot_user = await bot.get_me()
    if bot_user.id in [m.id for m in message.new_chat_members]:
        if await is_bot_admin(message.chat.id):
            await message.answer("✅ فرمانده در جایگاه خود قرار گرفت و آماده فرماندهی است.\n\nبرای ثبت رسمی این گروه در سیستم، از دستور /register_group استفاده کنید.")
        else:
            await message.answer("⚠️ فرمانده در جایگاه خودش نیست و علاقه‌ای به فرمان دادن ندارد. برای استفاده از قابلیت‌های ربات، لطفاً آن را ادمین کنید.")

@dp.message(Command("register_group"), ChatTypeFilter([ChatType.GROUP, ChatType.SUPERGROUP]))
async def cmd_register_group(message: Message):
    """ثبت گروه در دیتابیس برای شرکت در چالش‌ها و ..."""
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO groups (chat_id, chat_title) VALUES ($1, $2) ON CONFLICT (chat_id) DO UPDATE SET chat_title = $2;",
            message.chat.id, message.chat.title
        )
    await add_user_profile_if_missing(db_pool, message.from_user.id, message.chat.id)
    await message.answer(f"گروه <b>{message.chat.title}</b> با موفقیت ثبت شد. پروفایل شما برای این گروه ایجاد گردید. سربازان دیگر نیز با ارسال یک پیام در گروه پروفایل خود را دریافت خواهند کرد.")

@dp.message(Command("panel"), ChatTypeFilter(ChatType.PRIVATE))
async def cmd_panel(message: Message):
    """نمایش پنل اصلی مدیریت در چت خصوصی."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⚔️ آشیانه", callback_data=PanelCallback(action="hangar").pack()),
        InlineKeyboardButton(text="🛒 فروشگاه", callback_data=PanelCallback(action="shop").pack())
    )
    builder.row(
        InlineKeyboardButton(text="⛽️ دکل‌ها", callback_data=PanelCallback(action="rigs").pack()),
        InlineKeyboardButton(text="👤 پروفایل", callback_data=PanelCallback(action="profile").pack())
    )
    builder.row(InlineKeyboardButton(text="🌐 چت سراسری", url="https://t.me/WorldWarMiniGame"))
    
    await message.answer("پنل فرماندهی:", reply_markup=builder.as_markup())

# --- هندلرهای Callback ---
@dp.callback_query(PanelCallback.filter(F.chat_id == None))
async def handle_panel_action(query: CallbackQuery, callback_data: PanelCallback):
    """مرحله اول: پس از کلیک روی دکمه پنل، گروه‌ها را برای انتخاب نمایش می‌دهد."""
    user_id = query.from_user.id
    async with db_pool.acquire() as conn:
        # گروه‌هایی که کاربر در آنها عضو است و ربات هم عضو است را پیدا کن
        # این بخش نیاز به بهینه‌سازی دارد، در حال حاضر گروه‌های ثبت‌شده کاربر را می‌گیریم
        rows = await conn.fetch("SELECT g.chat_id, g.chat_title FROM groups g JOIN users u ON g.chat_id = u.chat_id WHERE u.user_id = $1", user_id)
    
    if not rows:
        await query.answer("شما در هیچ گروه ثبت‌شده‌ای پروفایل ندارید! ابتدا در یک گروه با ربات فعال باشید و دستور /register_group را بزنید.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for row in rows:
        builder.row(InlineKeyboardButton(
            text=f"📍 {row['chat_title']}",
            callback_data=PanelCallback(action=callback_data.action, chat_id=row['chat_id']).pack()
        ))
    
    await query.message.edit_text("لطفاً پروفایل گروه مورد نظر را انتخاب کنید:", reply_markup=builder.as_markup())
    await query.answer()

@dp.callback_query(PanelCallback.filter(F.chat_id != None))
async def handle_group_selection(query: CallbackQuery, callback_data: PanelCallback):
    """مرحله دوم: پس از انتخاب گروه، عملیات اصلی را اجرا می‌کند."""
    action = callback_data.action
    chat_id = callback_data.chat_id
    user_id = query.from_user.id

    # اطمینان از وجود پروفایل
    await add_user_profile_if_missing(db_pool, user_id, chat_id)

    # مسیریابی به تابع مربوطه
    if action == "profile":
        await show_profile(query, user_id, chat_id)
    elif action == "rigs":
        await show_rigs(query, user_id, chat_id)
    # ... سایر اکشن‌ها
    else:
        await query.answer(f"عملکرد '{action}' هنوز پیاده‌سازی نشده است.", show_alert=True)
    
    await query.answer()

# --- توابع نمایش اطلاعات پنل ---
async def show_profile(query: CallbackQuery, user_id: int, chat_id: int):
    """نمایش اطلاعات پروفایل کاربر در گروه انتخاب‌شده."""
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id=$1 AND chat_id=$2", user_id, chat_id)
        group = await conn.fetchrow("SELECT chat_title FROM groups WHERE chat_id=$1", chat_id)
        
    if not user or not group:
        await query.message.edit_text("خطا در دریافت اطلاعات پروفایل.")
        return

    text = (
        f"<b>👤 پروفایل شما در گروه «{group['chat_title']}»</b>\n\n"
        f"🎖 <b>تجربه (EXP):</b> {user['exp']}\n"
        f"💵 <b>پول:</b> ${user['money']:,}\n"
        f"🇮🇷 <b>کشور:</b> {user['country']}\n"
    )
    # دکمه بازگشت به پنل اصلی
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="⬅️ بازگشت به پنل", callback_data="back_to_panel"))
    await query.message.edit_text(text, reply_markup=builder.as_markup())

async def show_rigs(query: CallbackQuery, user_id: int, chat_id: int):
    """نمایش اطلاعات دکل‌های کاربر در گروه انتخاب‌شده."""
    async with db_pool.acquire() as conn:
        rig = await conn.fetchrow("SELECT * FROM rigs WHERE user_id=$1 AND chat_id=$2", user_id, chat_id)
        group = await conn.fetchrow("SELECT chat_title FROM groups WHERE chat_id=$1", chat_id)

    if not rig or not group:
        await query.message.edit_text("خطا در دریافت اطلاعات دکل‌ها.")
        return
        
    health_text = "نامحدود (اولیه)" if rig['health'] == -1 else f"{rig['health']} ❤️"
    text = (
        f"<b>⛽️ دکل‌های شما در گروه «{group['chat_title']}»</b>\n\n"
        f"🔹 <b>سطح:</b> {rig['level']}\n"
        f"❤️ <b>سلامتی:</b> {health_text}\n"
        f"🛢 <b>نفت استخراج‌شده:</b> {rig['oil']}/{rig['capacity']}\n"
        f"⏱ <b>تولید:</b> {rig['production']} نفت در دقیقه\n"
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="💰 جمع‌آوری نفت", callback_data=PanelCallback(action="collect_oil", chat_id=chat_id).pack()),
        InlineKeyboardButton(text="⏫ ارتقاء دکل", callback_data=PanelCallback(action="upgrade_rig", chat_id=chat_id).pack())
    )
    builder.row(InlineKeyboardButton(text="⬅️ بازگشت به پنل", callback_data="back_to_panel"))

    await query.message.edit_text(text, reply_markup=builder.as_markup())

@dp.callback_query(F.data == "back_to_panel")
async def back_to_panel(query: CallbackQuery):
    """هندلر دکمه بازگشت به پنل اصلی."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⚔️ آشیانه", callback_data=PanelCallback(action="hangar").pack()),
        InlineKeyboardButton(text="🛒 فروشگاه", callback_data=PanelCallback(action="shop").pack())
    )
    builder.row(
        InlineKeyboardButton(text="⛽️ دکل‌ها", callback_data=PanelCallback(action="rigs").pack()),
        InlineKeyboardButton(text="👤 پروفایل", callback_data=PanelCallback(action="profile").pack())
    )
    builder.row(InlineKeyboardButton(text="🌐 چت سراسری", url="https://t.me/WorldWarMiniGame"))
    
    await query.message.edit_text("پنل فرماندهی:", reply_markup=builder.as_markup())
    await query.answer()

# هندلر catch-all برای ایجاد پروفایل برای کاربران جدید در گروه
@dp.message(ChatTypeFilter([ChatType.GROUP, ChatType.SUPERGROUP]))
async def create_profile_on_message(message: Message):
    """با ارسال اولین پیام کاربر در گروه، پروفایلش برای آن گروه ساخته می‌شود."""
    # فقط در صورتی که ربات ادمین باشد، پروفایل بساز
    if await is_bot_admin(message.chat.id):
        await add_user_profile_if_missing(db_pool, message.from_user.id, message.chat.id)
    # این تابع نباید پیامی ارسال کند تا در کار ربات اختلال ایجاد نکند


# --- حلقه‌های پس‌زمینه (نیاز به بازنویسی برای سیستم چندپروفیلی) ---
async def produce_oil_loop(pool: asyncpg.Pool):
    while True:
        await asyncio.sleep(60)
        try:
            async with pool.acquire() as conn:
                # به‌روزرسانی برای تمام پروفایل‌ها
                await conn.execute("""
                UPDATE rigs SET oil = LEAST(capacity, oil + production);
                """)
        except Exception as e:
            print(f"Error in produce_oil_loop: {e}")

# --- شروع برنامه ---
async def set_bot_commands():
    """تنظیم دستورات ربات برای نمایش در تلگرام."""
    commands = [
        BotCommand(command="start", description="شروع کار با ربات و دریافت راهنما"),
        BotCommand(command="panel", description="باز کردن پنل مدیریت (فقط در چت خصوصی)"),
        BotCommand(command="register_group", description="ثبت گروه برای فعال شدن قابلیت‌ها"),
    ]
    await bot.set_my_commands(commands)

async def main():
    global db_pool
    db_pool = await create_db_pool()
    await setup_tables(db_pool)
    await set_bot_commands()
    
    # اجرای حلقه‌های پس‌زمینه
    asyncio.create_task(produce_oil_loop(db_pool))
    
    print("ربات با موفقیت راه‌اندازی شد...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("ربات خاموش شد.")
