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
from typing import Optional, List, Dict, Union

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ChatType
from aiogram.filters import Command
from aiogram.filters.chat_type import ChatType as ChatTypeFilter # نام مستعار برای خوانایی
from aiogram.filters.callback_data import CallbackData
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from aiogram.utils.keyboard import InlineKeyboardBuilder
import asyncpg
from dotenv import load_dotenv

# --- بخش ۱: بارگذاری تنظیمات و متغیرهای محیطی ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
if not BOT_TOKEN or not DATABASE_URL:
    raise ValueError("BOT_TOKEN و DATABASE_URL باید در فایل .env تعریف شوند.")

# --- بخش ۲: نمونه‌سازی ربات و دیسپچر ---
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# استخر اتصال به دیتابیس (Pool)
db_pool: Optional[asyncpg.Pool] = None
# کش برای وضعیت ادمین بودن ربات
_bot_admin_cache: Dict[int, Dict[str, Union[bool, datetime.datetime]]] = {}

# --- بخش ۳: تنظیمات و داده‌های ثابت بازی ---
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
JET_STATS = {"default": (100, 30, 10, 2)}  # health, attack_time(sec), fuel_consumption, missile_slots
MISSILE_STATS = {"default": (50, 1000)}  # damage, price
DEFENSE_STATS = {"default": (20, 25, 800)}  # damage_reduction_%, counter_damage, missile_cost
INITIAL_RIG = {"level": 1, "health": -1, "capacity": 1000, "production": 1}  # -1 health: indestructible

# --- بخش ۴: ساختارهای داده (CallbackData) ---
class PanelCallback(CallbackData, prefix="panel"):
    action: str
    chat_id: Optional[int] = None
    item_id: Optional[str] = None

# --- بخش ۵: توابع مربوط به دیتابیس ---
async def create_db_pool() -> asyncpg.Pool:
    """یک استخر اتصال به دیتابیس PostgreSQL ایجاد می‌کند."""
    return await asyncpg.create_pool(DATABASE_URL)

async def setup_tables(pool: asyncpg.Pool):
    """جداول مورد نیاز برنامه را در صورت عدم وجود ایجاد می‌کند."""
    async with pool.acquire() as conn:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT, chat_id BIGINT, country TEXT DEFAULT 'ایران',
            exp BIGINT DEFAULT 0, money BIGINT DEFAULT 10000,
            PRIMARY KEY (user_id, chat_id)
        );
        CREATE TABLE IF NOT EXISTS rigs (
            user_id BIGINT, chat_id BIGINT, level INT DEFAULT 1, health INT DEFAULT -1,
            oil BIGINT DEFAULT 0, capacity INT DEFAULT 1000, production INT DEFAULT 1,
            PRIMARY KEY (user_id, chat_id)
        );
        CREATE TABLE IF NOT EXISTS fighters (
            id SERIAL PRIMARY KEY, user_id BIGINT, chat_id BIGINT, name TEXT, health INT,
            last_attack TIMESTAMP, fuel_percent INT DEFAULT 100, missiles JSONB DEFAULT '[]'::jsonb
        );
        CREATE TABLE IF NOT EXISTS defenses (
            user_id BIGINT, chat_id BIGINT, reduction_percent INT DEFAULT 0,
            missiles JSONB DEFAULT '[]'::jsonb, PRIMARY KEY (user_id, chat_id)
        );
        CREATE TABLE IF NOT EXISTS groups (
            chat_id BIGINT PRIMARY KEY, chat_title TEXT
        );
        """)

async def add_user_profile_if_missing(pool: asyncpg.Pool, user_id: int, chat_id: int):
    """در صورت عدم وجود، پروفایل کاربر (جداول users و rigs) را برای یک گروه خاص ایجاد می‌کند."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO users (user_id, chat_id) VALUES ($1, $2) ON CONFLICT (user_id, chat_id) DO NOTHING;",
                user_id, chat_id
            )
            await conn.execute(
                """INSERT INTO rigs (user_id, chat_id, level, health, capacity, production)
                   VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT (user_id, chat_id) DO NOTHING;""",
                user_id, chat_id, INITIAL_RIG["level"], INITIAL_RIG["health"], INITIAL_RIG["capacity"], INITIAL_RIG["production"]
            )

# --- بخش ۶: توابع کمکی و Middleware ---
async def is_bot_admin(chat_id: int) -> bool:
    """بررسی می‌کند که آیا ربات در گروه ادمین است یا خیر (با استفاده از کش)."""
    now = datetime.datetime.now()
    # اگر نتیجه در کش موجود بود و کمتر از ۵ دقیقه از آن گذشته بود، از همان استفاده کن
    if chat_id in _bot_admin_cache and (now - _bot_admin_cache[chat_id]['time']).total_seconds() < 300:
        return _bot_admin_cache[chat_id]['status']
    
    try:
        me = await bot.get_chat_member(chat_id, bot.id)
        status = me.status in ("administrator", "creator")
    except Exception:
        status = False
    
    # نتیجه را در کش ذخیره کن
    _bot_admin_cache[chat_id] = {"status": status, "time": now}
    return status

class AdminAccessMiddleware:
    """
    این Middleware بررسی می‌کند که آیا ربات در گروه ادمین است یا خیر.
    اگر ادمین نباشد، از اجرای دستورات جلوگیری می‌کند.
    """
    async def __call__(self, handler, event: Message, data: dict):
        if event.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
            if event.text and event.text.startswith('/'):
                if not await is_bot_admin(event.chat.id):
                    await event.answer("فرمانده در جایگاه خودش نیست و علاقه‌ای به فرمان دادن ندارد.", protect_content=True)
                    return
        return await handler(event, data)

# ثبت Middleware
dp.message.middleware(AdminAccessMiddleware())

# --- بخش ۷: هندلرهای اصلی دستورات ---
@dp.message(Command("start"), ChatTypeFilter("private"))
async def cmd_start_private(message: Message):
    """پاسخ به دستور /start در چت خصوصی."""
    bot_user = await bot.get_me()
    keyboard = InlineKeyboardBuilder().add(InlineKeyboardButton(
        text="➕ افزودن ربات به گروه", url=f"https://t.me/{bot_user.username}?startgroup=true"
    )).as_markup()
    
    welcome_text = (
        "<b>خوش‌آمدی سرباز!</b>\n\n"
        "من فرمانده میدان نبرد هستم. برای شروع، من را به گروه خود اضافه کن و ادمین کن تا پایگاه نظامی شما را ثبت کنم.\n\n"
        "<tg-spoiler>ℹ️ برای دسترسی به پنل مدیریت، از دستور /panel استفاده کن.</tg-spoiler>"
    )
    await message.answer(welcome_text, reply_markup=keyboard)

@dp.message(F.new_chat_members)
async def on_new_chat_members(message: Message):
    """واکنش به اضافه شدن اعضای جدید (از جمله خود ربات) به گروه."""
    bot_user = await bot.get_me()
    if bot_user.id in [m.id for m in message.new_chat_members]:
        if await is_bot_admin(message.chat.id):
            await message.answer("✅ فرمانده در جایگاه خود قرار گرفت و آماده فرماندهی است.\n\nبرای ثبت رسمی این گروه در سیستم، از دستور /register_group استفاده کنید.")
        else:
            await message.answer("⚠️ فرمانده در جایگاه خودش نیست. برای استفاده از قابلیت‌های ربات، لطفاً آن را ادمین کنید و سپس دستور /register_group را ارسال نمایید.")

@dp.message(Command("register_group"), ChatTypeFilter(["group", "supergroup"]))
async def cmd_register_group(message: Message):
    """ثبت گروه در دیتابیس و ایجاد پروفایل برای کاربر درخواست‌دهنده."""
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO groups (chat_id, chat_title) VALUES ($1, $2) ON CONFLICT (chat_id) DO UPDATE SET chat_title = $2;",
            message.chat.id, message.chat.title
        )
    await add_user_profile_if_missing(db_pool, message.from_user.id, message.chat.id)
    await message.answer(f"گروه <b>{message.chat.title}</b> با موفقیت ثبت شد. پروفایل شما برای این گروه ایجاد گردید.")

@dp.message(Command("panel"), ChatTypeFilter("private"))
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

# --- بخش ۸: هندلرهای دکمه‌های پنل (Callback) ---
@dp.callback_query(PanelCallback.filter(F.chat_id == None))
async def handle_panel_action_select_group(query: CallbackQuery, callback_data: PanelCallback):
    """مرحله ۱: نمایش گروه‌ها برای انتخاب پروفایل."""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT g.chat_id, g.chat_title FROM groups g JOIN users u ON g.chat_id = u.chat_id WHERE u.user_id = $1", query.from_user.id)
    
    if not rows:
        await query.answer("شما در هیچ گروه ثبت‌شده‌ای پروفایل ندارید! ابتدا در یک گروه با ربات فعال باشید.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for row in rows:
        builder.row(InlineKeyboardButton(
            text=f"📍 {row['chat_title']}",
            callback_data=PanelCallback(action=callback_data.action, chat_id=row['chat_id']).pack()
        ))
    builder.row(InlineKeyboardButton(text="✖️ انصراف", callback_data=PanelCallback(action="back_to_main").pack()))
    await query.message.edit_text("لطفاً پروفایل گروه مورد نظر را انتخاب کنید:", reply_markup=builder.as_markup())
    await query.answer()

@dp.callback_query(PanelCallback.filter(F.chat_id != None))
async def handle_group_selection_action(query: CallbackQuery, callback_data: PanelCallback):
    """مرحله ۲: اجرای عملیات اصلی پس از انتخاب گروه."""
    action, chat_id, user_id = callback_data.action, callback_data.chat_id, query.from_user.id
    await add_user_profile_if_missing(db_pool, user_id, chat_id)

    # مسیریابی اکشن‌ها
    action_map = {
        "profile": show_profile,
        "rigs": show_rigs,
    }
    handler = action_map.get(action)
    if handler:
        await handler(query, user_id, chat_id)
    else:
        await query.answer(f"عملکرد '{action}' هنوز پیاده‌سازی نشده است.", show_alert=True)
    await query.answer()

# --- بخش ۹: توابع نمایش اطلاعات پنل ---
async def show_profile(query: CallbackQuery, user_id: int, chat_id: int):
    """نمایش اطلاعات پروفایل کاربر."""
    async with db_pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE user_id=$1 AND chat_id=$2", user_id, chat_id)
        group = await conn.fetchrow("SELECT chat_title FROM groups WHERE chat_id=$1", chat_id)
    if not user or not group:
        return await query.message.edit_text("خطا در دریافت اطلاعات پروفایل.")

    text = (
        f"<b>👤 پروفایل شما در «{group['chat_title']}»</b>\n\n"
        f"🎖 <b>تجربه (EXP):</b> {user['exp']}\n"
        f"💵 <b>پول:</b> ${user['money']:,}\n"
        f"🇮🇷 <b>کشور:</b> {user['country']}"
    )
    builder = InlineKeyboardBuilder().add(InlineKeyboardButton(text="⬅️ بازگشت به پنل", callback_data=PanelCallback(action="back_to_main").pack()))
    await query.message.edit_text(text, reply_markup=builder.as_markup())

async def show_rigs(query: CallbackQuery, user_id: int, chat_id: int):
    """نمایش اطلاعات دکل‌های نفتی کاربر."""
    async with db_pool.acquire() as conn:
        rig = await conn.fetchrow("SELECT * FROM rigs WHERE user_id=$1 AND chat_id=$2", user_id, chat_id)
        group = await conn.fetchrow("SELECT chat_title FROM groups WHERE chat_id=$1", chat_id)
    if not rig or not group:
        return await query.message.edit_text("خطا در دریافت اطلاعات دکل‌ها.")

    health_text = "نامحدود (اولیه)" if rig['health'] == -1 else f"{rig['health']} ❤️"
    text = (
        f"<b>⛽️ دکل‌ها در «{group['chat_title']}»</b>\n\n"
        f"🔹 <b>سطح:</b> {rig['level']}\n"
        f"❤️ <b>سلامتی:</b> {health_text}\n"
        f"🛢 <b>نفت استخراج‌شده:</b> {rig['oil']}/{rig['capacity']}\n"
        f"⏱ <b>تولید:</b> {rig['production']} نفت در دقیقه"
    )
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="💰 جمع‌آوری نفت", callback_data=PanelCallback(action="collect_oil", chat_id=chat_id).pack()),
        InlineKeyboardButton(text="⏫ ارتقاء دکل", callback_data=PanelCallback(action="upgrade_rig", chat_id=chat_id).pack())
    )
    builder.row(InlineKeyboardButton(text="⬅️ بازگشت به پنل", callback_data=PanelCallback(action="back_to_main").pack()))
    await query.message.edit_text(text, reply_markup=builder.as_markup())

@dp.callback_query(PanelCallback.filter(F.action == "back_to_main"))
async def back_to_main_panel_handler(query: CallbackQuery):
    """هندلر دکمه بازگشت به پنل اصلی."""
    await cmd_panel(query.message) # فراخوانی مجدد تابع پنل اصلی
    await query.answer()

# --- بخش ۱۰: هندلر عمومی و حلقه‌های پس‌زمینه ---
@dp.message(F.text, ChatTypeFilter(["group", "supergroup"]))
async def create_profile_on_message(message: Message):
    """با ارسال اولین پیام متنی کاربر در گروه، پروفایلش برای آن گروه ساخته می‌شود."""
    if not message.from_user.is_bot and await is_bot_admin(message.chat.id):
        await add_user_profile_if_missing(db_pool, message.from_user.id, message.chat.id)

async def produce_oil_loop(pool: asyncpg.Pool):
    """حلقه پس‌زمینه برای تولید نفت در تمام دکل‌ها هر ۶۰ ثانیه."""
    while True:
        await asyncio.sleep(60)
        try:
            async with pool.acquire() as conn:
                await conn.execute("UPDATE rigs SET oil = LEAST(capacity, oil + production);")
        except Exception as e:
            print(f"Error in produce_oil_loop: {e}")

# --- بخش ۱۱: توابع راه‌اندازی و اجرای ربات ---
async def set_bot_commands():
    """تنظیم دستورات ربات برای نمایش در منوی تلگرام."""
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
    
    # اجرای حلقه پس‌زمینه
    asyncio.create_task(produce_oil_loop(db_pool))
    
    print("--- ربات با موفقیت راه‌اندازی شد ---")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("--- ربات خاموش شد ---")
