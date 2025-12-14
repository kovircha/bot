# ==========================================
# 1. ИМПОРТЫ И БИБЛИОТЕКИ
# ==========================================
import json
import os
import asyncio
import logging
import random
import time
import math
import sys
import aiosqlite
import aioconsole
from colorama import init, Fore, Style

from aiogram import Bot, Dispatcher, F, types, BaseMiddleware
from aiogram.filters import Command, StateFilter
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, 
    InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery, Message, FSInputFile,
    InputMediaPhoto, ReplyKeyboardRemove 
)
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# Инициализация цвета в консоли
init(autoreset=True)

# ==========================================
# 2. КОНФИГУРАЦИЯ И НАСТРОЙКИ
# ==========================================

# --- Основные настройки ---
TOKEN = '8482572401:AAHR91Uwrq6U2-ody9jYUmQxme3xOeyzyvg'
REQUIRED_CHANNEL_ID = "@molokofarmoff" 
REQUIRED_CHANNEL_URL = "https://t.me/molokofarmoff"
DB_NAME = 'farm_v4.db'
CARDS_DIR = "img_cards"
ADMINS = ['silentglove', 'octoberchaos']

# Проверка папки карт
if not os.path.exists(CARDS_DIR):
    os.makedirs(CARDS_DIR)

# --- Глобальные флаги ---
CONSOLE_LOGS = False      
MAINTENANCE_MODE = False  

# --- Баланс и Экономика ---
MILK_PER_CLICK = 1
BASE_PLANT_COST = 5
BASE_CASINO_COST = 10
FERT_EFFECT = 5
DAILY_COOLDOWN = 86400 
JACKPOT_CHANCE = 100000 
SCARECROW_COOLDOWN = 10800  
BOOST_DURATION = 600        

# --- Академия (Цены и статы) ---
ACAD_BASE_INCOME = 100       
ACAD_INCOME_MULT = 50        
ACAD_BASE_TIME = 6           
ACAD_TIME_BONUS = 1          
ACAD_DISCOUNT_PER_LVL = 0.02 
COST_MANAGEMENT = 1000
COST_LOGISTICS = 2500
COST_AGRONOMY = 5000

# --- Лаборатория и Крафт ---
MUTAGEN_SHOP_PRICE = 5000 
CRAFT_COST_MUTAGEN = 1    
CRAFT_CARDS_NEEDED = 3    

# --- Battle Pass (Сезон) ---
XP_PER_ACTION = 10       
XP_PER_LEVEL_BASE = 500  
MAX_BP_LEVEL = 50        

BP_REWARDS = {
    1: ("tomatoes", 1000), 2: ("milk", 500), 3: ("fertilizer", 1), 5: ("mutagen", 1),
    10: ("tomatoes", 10000), 15: ("mutagen", 3), 20: ("fertilizer", 10), 
    25: ("tomatoes", 50000), 50: ("mutagen", 10)
}

# --- Медиа (Пути и Ссылки) ---
CHEST_CLOSE_PATH = "closed_chest.png" 
CHEST_OPEN_PATH = "open_chest.png"
URL_CHEST_CLOSE = "https://i.ibb.co/vzDqHqN/chest-closed.jpg"
URL_CHEST_OPEN = "https://i.ibb.co/JqjZqX5/chest-open.jpg"
SCARECROW_BAD_PATH = "scarecrow_bad.jpg"   
SCARECROW_GOOD_PATH = "scarecrow_good.jpg"
URL_SCARECROW_BAD = "https://i.ibb.co/L5hY5Xn/scarecrow-bad.jpg"
URL_SCARECROW_GOOD = "https://i.ibb.co/9V40K5z/scarecrow-good.jpg" 
LOGO_PATH = "logo new year.png"
DEFAULT_LOGO_URL = "https://storage.googleapis.com/pod_public/1300/243765.jpg"

# --- Дизайн (Стили) ---
UI_SEP = "━━━━━━━━━━━━━━━"
UI_BULLET = "▪️"
UI_SUB_BULLET = "▫️"

RARITY_INFO = {
    "common": {"name": "Обычная", "icon": "⚪", "color_code": 0xA0A0A0},
    "rare": {"name": "Редкая", "icon": "🔵", "color_code": 0x4169E1},
    "epic": {"name": "Эпическая", "icon": "🟣", "color_code": 0x8A2BE2},
    "limited": {"name": "Limited", "icon": "💠", "color_code": 0xFFD700}
}

# --- Загрузка карт ---
def load_cards():
    try:
        with open("cards.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except: return {}

CARDS = load_cards()

# ==========================================
# 3. СОСТОЯНИЯ (FSM)
# ==========================================

# Админка: Ресурсы
class AdminEcoStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_amount = State()

# Админка: Карточки
class AdminCardStates(StatesGroup):
    waiting_for_card_id = State()
    waiting_for_target = State()

# Рынок
class MarketStates(StatesGroup):
    waiting_for_price = State()
    card_id_to_sell = State()

# Рассылка
class BroadcastStates(StatesGroup):
    waiting_for_broadcast_text = State() 
    waiting_for_broadcast_confirm = State()    

# Промокоды
class GameStates(StatesGroup):
    waiting_for_code = State()

# ==========================================
# 4. БАЗА ДАННЫХ И МИГРАЦИИ
# ==========================================

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        
        # Основная таблица пользователей
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY, username TEXT, milk INTEGER DEFAULT 0, tomatoes INTEGER DEFAULT 0,
                click_level INTEGER DEFAULT 1, tomato_level INTEGER DEFAULT 1, fertilizer INTEGER DEFAULT 0,
                sosi_count INTEGER DEFAULT 0, is_banned INTEGER DEFAULT 0, luck_level INTEGER DEFAULT 0,
                safety_level INTEGER DEFAULT 0, eco_level INTEGER DEFAULT 0, casino_level INTEGER DEFAULT 0,
                gmo_level INTEGER DEFAULT 0, last_daily_claim REAL DEFAULT 0, reg_date REAL DEFAULT 0,
                last_scarecrow REAL DEFAULT 0, active_boost TEXT DEFAULT '', boost_end REAL DEFAULT 0,
                mandarins INTEGER DEFAULT 0, prefix TEXT DEFAULT NULL, custom_status TEXT DEFAULT 'Фермер',
                is_admin INTEGER DEFAULT 0, last_active REAL DEFAULT 0, iq_level INTEGER DEFAULT 0,
                iq_level_max_reached INTEGER DEFAULT 0, last_iq_collect REAL DEFAULT 0,
                acad_management INTEGER DEFAULT 0, acad_logistics INTEGER DEFAULT 0, acad_agronomy INTEGER DEFAULT 0,
                last_acad_collect REAL DEFAULT 0, is_hidden INTEGER DEFAULT 0, mutagen INTEGER DEFAULT 0,
                tractor_level INTEGER DEFAULT 0, last_tractor_collect REAL DEFAULT 0,
                bp_level INTEGER DEFAULT 1, bp_xp INTEGER DEFAULT 0, bp_claimed TEXT DEFAULT ''
            )
        ''')
        
        # Остальные таблицы
        await db.execute('CREATE TABLE IF NOT EXISTS user_cards (user_id INTEGER, card_id TEXT, count INTEGER DEFAULT 0, PRIMARY KEY (user_id, card_id))')
        await db.execute('CREATE TABLE IF NOT EXISTS promo_codes (code TEXT PRIMARY KEY, uses_left INTEGER, reward_type TEXT, reward_amount INTEGER)')
        await db.execute('CREATE TABLE IF NOT EXISTS used_codes (user_id INTEGER, code TEXT, PRIMARY KEY (user_id, code))')
        await db.execute('CREATE TABLE IF NOT EXISTS market (lot_id INTEGER PRIMARY KEY AUTOINCREMENT, seller_id INTEGER, seller_name TEXT, card_id TEXT, price INTEGER)')
        await db.commit()
        
        # Миграции (на случай обновлений)
        cols = [
            ("tractor_level", "INTEGER DEFAULT 0"), ("last_tractor_collect", "REAL DEFAULT 0"),
            ("mutagen", "INTEGER DEFAULT 0"), ("is_hidden", "INTEGER DEFAULT 0"),
            ("bp_level", "INTEGER DEFAULT 1"), ("bp_xp", "INTEGER DEFAULT 0"), ("bp_claimed", "TEXT DEFAULT ''")
        ]
        for c, d in cols:
            try: await db.execute(f'ALTER TABLE users ADD COLUMN {c} {d}')
            except: pass
        await db.commit()

# --- SQL Хелперы ---
async def get_user(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('SELECT * FROM users WHERE user_id = ?', (user_id,)) as c:
            user = await c.fetchone()
            if not user:
                await db.execute('INSERT INTO users (user_id, username, reg_date) VALUES (?, ?, ?)', (user_id, "Newbie", time.time()))
                await db.commit()
                return await get_user(user_id)
            return user

async def update_stat(user_id, column, value):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(f'UPDATE users SET {column} = ? WHERE user_id = ?', (value, user_id))
        await db.commit()

async def update_username(user_id, name):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('UPDATE users SET username = ? WHERE user_id = ?', (name, user_id))
        await db.commit()

# ==========================================
# 5. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (Утилиты)
# ==========================================

def format_num(num):
    try: return "{:,}".format(int(float(num))).replace(",", " ")
    except: return "0"

def get_progress_bar(value, max_value=10):
    percent = min(1.0, value / max_value)
    blocks = int(percent * 10)
    return "▓" * blocks + "░" * (10 - blocks)

def format_time_spent(seconds_played):
    days = int(seconds_played // 86400)
    hours = int((seconds_played % 86400) // 3600)
    if days > 0: return f"{days} д. {hours} ч."
    return f"{hours} ч. {int((seconds_played % 3600) // 60)} мин."

# Система чистого чата (удаление предыдущих сообщений)
LAST_MESSAGES = {}
async def send_with_cleanup(message: types.Message, text: str, reply_markup=None):
    user_id = message.from_user.id
    try:
        new_bot_msg = await message.answer(text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception as e:
        print(f"Ошибка отправки: {e}")
        return

    if user_id in LAST_MESSAGES:
        last_bot_msg_id, last_user_msg_id = LAST_MESSAGES[user_id]
        try: await bot.delete_message(chat_id=user_id, message_id=last_bot_msg_id)
        except: pass 
        try: await bot.delete_message(chat_id=user_id, message_id=last_user_msg_id)
        except: pass

    LAST_MESSAGES[user_id] = [new_bot_msg.message_id, message.message_id]

async def delete_later(msg, delay=2):
    await asyncio.sleep(delay)
    try: await msg.delete()
    except: pass

async def add_xp(user_id, amount, message):
    """Начисление опыта для Battle Pass"""
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('SELECT bp_level, bp_xp FROM users WHERE user_id = ?', (user_id,)) as c:
            user = await c.fetchone()
            
        current_lvl, current_xp = user['bp_level'], user['bp_xp'] + amount
        needed_xp = current_lvl * XP_PER_LEVEL_BASE
        
        if current_xp >= needed_xp and current_lvl < MAX_BP_LEVEL:
            current_xp -= needed_xp
            current_lvl += 1
            try: await message.answer(f"🎉 <b>LEVEL UP!</b> Новый уровень пропуска: {current_lvl}", parse_mode="HTML")
            except: pass
            
        await db.execute('UPDATE users SET bp_level = ?, bp_xp = ? WHERE user_id = ?', (current_lvl, current_xp, user_id))
        await db.commit()

# ==========================================
# 6. КЛАВИАТУРЫ И ГЕНЕРАЦИЯ МЕНЮ
# ==========================================

def main_keyboard():
    kb = [[KeyboardButton(text="🥛 Сбор Молока"), KeyboardButton(text="💦 Полить грядку")],
          [KeyboardButton(text="🏙 Город"), KeyboardButton(text="🎡 Развлечения")],
          [KeyboardButton(text="👤 Личный Кабинет")]]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, input_field_placeholder="Главное меню")

def town_keyboard():
    kb = [[KeyboardButton(text="💲 Торговец"), KeyboardButton(text="📦 Хранилище")],
          [KeyboardButton(text="🎓 Академия"), KeyboardButton(text="🧬 Лаборатория")], 
          [KeyboardButton(text="🏆 Рейтинг"), KeyboardButton(text="📟 Терминал")], 
          [KeyboardButton(text="⤾ Назад")]]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, input_field_placeholder="Город")

def fun_keyboard():
    kb = [[KeyboardButton(text="🎲 Казино"), KeyboardButton(text="🎁 Ежедневный бонус")],
          [KeyboardButton(text="🥔 Плантация"), KeyboardButton(text="🎟 Сезон")], 
          [KeyboardButton(text="⤾ Назад")]]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, input_field_placeholder="Развлечения")

def upgrades_keyboard(u, info_mode=False):
    lvl_agr = u['acad_agronomy']
    discount = min(0.30, lvl_agr * ACAD_DISCOUNT_PER_LVL)
    price_factor = 1.0 - discount
    
    # Расчет цен (Экспонента)
    p_click = int(50 * (1.4 ** u['click_level']) * price_factor)
    p_tomato = int(150 * (1.5 ** u['tomato_level']) * price_factor)
    p_luck = int(500 * (1.6 ** u['luck_level']) * price_factor)
    p_safe = int(300 * (1.4 ** u['safety_level']) * price_factor)
    p_eco = int(1000 * (1.5 ** u['eco_level']) * price_factor)
    p_cas = int(750 * (1.3 ** u['casino_level']) * price_factor)
    p_gmo = int(2000 * (1.7 ** u['gmo_level']) * price_factor)
    p_tractor = int(5000 * (1.6 ** u['tractor_level']) * price_factor)

    d_text = f" 🔥-{int(discount*100)}%" if discount > 0 else ""
    icon = "ℹ️" if info_mode else "🛒"
    mode_btn = "🔙 К покупке" if info_mode else "❔ Инфо режим"
    mode_cb = "shop_mode_buy" if info_mode else "shop_mode_info"
    m = "i" if info_mode else "b" 

    kb = [
        [InlineKeyboardButton(text=f"{icon} Бицепс ({format_num(p_click)})", callback_data=f"buy_click_{m}"),
         InlineKeyboardButton(text=f"{icon} Сорт ({format_num(p_tomato)})", callback_data=f"buy_tomato_{m}")],
        [InlineKeyboardButton(text=f"{icon} Удача ({format_num(p_luck)})", callback_data=f"buy_luck_{m}"),
         InlineKeyboardButton(text=f"{icon} Крышка ({format_num(p_safe)})", callback_data=f"buy_safe_{m}")],
        [InlineKeyboardButton(text=f"{icon} Насос ({format_num(p_eco)})", callback_data=f"buy_eco_{m}"),
         InlineKeyboardButton(text=f"{icon} Шулер ({format_num(p_cas)})", callback_data=f"buy_cas_{m}")],
        [InlineKeyboardButton(text=f"{icon} Трактор ({format_num(p_tractor)})", callback_data=f"buy_tractor_{m}"),
         InlineKeyboardButton(text=f"{icon} ГМО ({format_num(p_gmo)})", callback_data=f"buy_gmo_{m}")],
        [InlineKeyboardButton(text=mode_btn, callback_data=mode_cb)],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_upgrades")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def inventory_keyboard(has_fert: int, mandarins: int):
    kb = []
    if has_fert > 0: kb.append([InlineKeyboardButton(text=f"🧪 Юз химии (x{has_fert})", callback_data="use_all_fert_init")])
    if mandarins > 0: kb.append([InlineKeyboardButton(text=f"🎅 Лавка ({format_num(mandarins)} кг)", callback_data="santa_shop_open")])
    kb.append([InlineKeyboardButton(text="🎴 Коллекция", callback_data="show_cards_inline")])
    kb.append([InlineKeyboardButton(text="⚖️ Биржа", callback_data="show_market_inline")])
    kb.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_inv")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_shop_text(user):
    return (f"🛒 <b>ЦЕНТР СНАБЖЕНИЯ</b>\n{UI_SEP}\n💵 Баланс: <code>{format_num(user['tomatoes'])}</code> 🍅")

def get_academy_render_data(u, harvest_msg=""):
    stats = get_academy_stats(u)
    text = (
        f"🏛 <b>АКАДЕМИЯ</b>\n{UI_SEP}\n{harvest_msg}\n"
        f"🎓 Звание: {stats['title']}\n"
        f"📈 Доход: {stats['income']} 🍅/ч\n"
        f"⏳ Склад: {stats['max_time']} ч.\n"
        f"🧬 Скидка: -{int(stats['discount']*100)}%"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬆️ Улучшить", callback_data="acad_upgrades")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="acad_refresh")]
    ])
    return text, kb

def get_academy_stats(u):
    lvl_man, lvl_log, lvl_agr = u['acad_management'], u['acad_logistics'], u['acad_agronomy']
    income = 0 if lvl_man == 0 else ACAD_BASE_INCOME + (lvl_man - 1) * ACAD_INCOME_MULT
    max_time = ACAD_BASE_TIME + (lvl_log * ACAD_TIME_BONUS)
    discount = min(0.30, lvl_agr * ACAD_DISCOUNT_PER_LVL)
    total_lvl = lvl_man + lvl_log + lvl_agr
    
    title = "Абитуриент"
    if total_lvl >= 5: title = "Студент"
    if total_lvl >= 15: title = "Бакалавр"
    if total_lvl >= 30: title = "Магистр"
    
    return {"income": income, "max_time": max_time, "discount": discount, "title": title, "total_lvl": total_lvl}

async def collect_academy_income(user_id, u):
    stats = get_academy_stats(u)
    if stats['income'] == 0: return 0, ""
    
    now = time.time()
    last = u['last_acad_collect'] or now
    if last == 0: 
        await update_stat(user_id, "last_acad_collect", now)
        return 0, ""
        
    diff = min(now - last, stats['max_time'] * 3600)
    if diff < 60: return 0, ""
    
    harvest = int(stats['income'] * (diff / 3600))
    if harvest > 0:
        await update_stat(user_id, "tomatoes", u['tomatoes'] + harvest)
        await update_stat(user_id, "last_acad_collect", now)
        return harvest, f"🎓 Стипендия: +{harvest} 🍅"
    return 0, ""

async def get_card_keyboard(current_id, user_id, is_owner, target_id_if_not_owner=None):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT card_id FROM user_cards WHERE user_id = ?', (user_id,)) as c:
            all_cards = [row[0] for row in await c.fetchall()]
    
    kb_rows = []
    if current_id in all_cards:
        idx = all_cards.index(current_id)
        prev_card = all_cards[idx - 1] if idx > 0 else all_cards[-1]
        next_card = all_cards[idx + 1] if idx < len(all_cards) - 1 else all_cards[0]
        
        if is_owner:
            btn_prev = InlineKeyboardButton(text="⬅️", callback_data=f"view_card_{prev_card}")
            btn_next = InlineKeyboardButton(text="➡️", callback_data=f"view_card_{next_card}")
        else:
            btn_prev = InlineKeyboardButton(text="⬅️", callback_data=f"peek_card_{target_id_if_not_owner}_{prev_card}")
            btn_next = InlineKeyboardButton(text="➡️", callback_data=f"peek_card_{target_id_if_not_owner}_{next_card}")
            
        kb_rows.append([btn_prev, InlineKeyboardButton(text=f"{idx+1}/{len(all_cards)}", callback_data="ignore"), btn_next])

    if is_owner:
        kb_rows.append([InlineKeyboardButton(text=f"💰 Продать", callback_data=f"sell_init_{current_id}")])
        kb_rows.append([InlineKeyboardButton(text="⤾ Назад в Склад", callback_data="refresh_inv")])
    else:
        kb_rows.append([InlineKeyboardButton(text="⤾ К профилю", callback_data=f"view_profile_{target_id_if_not_owner}")])

    return InlineKeyboardMarkup(inline_keyboard=kb_rows)

async def send_card_info(message, card_id, count, is_owner=True, owner_id=None):
    if card_id not in CARDS: return
    if owner_id is None: owner_id = message.chat.id

    card = CARDS[card_id]
    rarity_data = RARITY_INFO.get(card.get("rarity", "common"), RARITY_INFO["common"])
    
    caption = (
        f"{rarity_data['icon']} <b>{card['name']}</b>\n{UI_SEP}\n"
        f"🎭 Редкость: <b>{rarity_data['name']}</b>\n"
        f"📜 Описание: <i>{card.get('desc', '...')}</i>\n"
        f"🎒 В наличии: <b>{count} шт.</b>"
    )

    kb = await get_card_keyboard(card_id, owner_id, is_owner, owner_id if not is_owner else None)
    
    image_filename = card.get("img", "default.jpg") 
    image_path = os.path.join(CARDS_DIR, image_filename)
    
    try:
        if isinstance(message, CallbackQuery): message = message.message
        if os.path.exists(image_path):
            photo = FSInputFile(image_path)
            await message.answer_photo(photo, caption=caption, reply_markup=kb, parse_mode="HTML")
        else:
            await message.answer(f"🖼 <i>(Нет фото)</i>\n\n" + caption, reply_markup=kb, parse_mode="HTML")
    except: pass

async def get_market_page(page=0):
    async with aiosqlite.connect(DB_NAME) as db:
        cnt = await (await db.execute("SELECT COUNT(*) FROM market")).fetchone()
        lot = await (await db.execute("SELECT * FROM market LIMIT 1 OFFSET ?", (page,))).fetchone()
    return lot, cnt[0]

async def show_market_page(msg, page=0):
    lot, total = await get_market_page(page)
    if not lot:
        text = "⚖️ <b>БИРЖА:</b> Пусто."
        kb = None
        if isinstance(msg, CallbackQuery): await msg.message.edit_text(text, parse_mode="HTML")
        else: await msg.answer(text, parse_mode="HTML")
        return

    lid, seller, _, cid, price = lot[0], lot[2], lot[1], lot[3], lot[4]
    cname = CARDS.get(cid, {}).get("name", "?")
    
    text = f"⚖️ <b>ЛОТ {page+1}/{total}</b>\n📦 {cname}\n👤 {seller}\n💰 {format_num(price)} 🍅"
    
    uid = msg.from_user.id
    act_btn = InlineKeyboardButton(text="🗑 Удалить", callback_data=f"market_delete_{lid}") if uid == seller else InlineKeyboardButton(text="💳 Купить", callback_data=f"buy_lot_{lid}")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [act_btn],
        [InlineKeyboardButton(text="⬅️", callback_data=f"market_page_{page-1}"), 
         InlineKeyboardButton(text=f"{page+1}", callback_data="ignore"),
         InlineKeyboardButton(text="➡️", callback_data=f"market_page_{page+1}")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data=f"market_page_{page}")]
    ])
    
    if isinstance(msg, CallbackQuery): await msg.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else: await msg.answer(text, reply_markup=kb, parse_mode="HTML")

# ==========================================
# 7. ГЛАВНЫЕ ХЕНДЛЕРЫ И МИДДЛВАРЬ
# ==========================================

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())
dp.message.middleware(GameMiddleware())

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    u = await get_user(user_id)
    if u['is_banned']: return

    # Трактор (AFK фарм)
    if u['tractor_level'] > 0:
        now = time.time()
        last = u['last_tractor_collect'] or now
        diff = min(now - last, 43200) # Макс 12 часов
        if diff > 60:
            income = int((diff / 60) * 10 * u['tractor_level'])
            await update_stat(user_id, "tomatoes", u['tomatoes'] + income)
            await update_stat(user_id, "last_tractor_collect", now)
            await message.answer(f"🚜 <b>ТРАКТОР:</b> Собрано {format_num(income)} 🍅 while AFK.", parse_mode="HTML")
        else:
            await update_stat(user_id, "last_tractor_collect", now)
    else:
        await update_stat(user_id, "last_tractor_collect", time.time())

    await message.answer("🌾 <b>Молочная ферма v7.5</b>\nДобро пожаловать!", reply_markup=main_keyboard(), parse_mode="HTML")

# --- ФАРМ ---
@dp.message(F.text.in_({"🥛 Сбор Молока"}))
async def milk_handler(message: types.Message):
    user_id = message.from_user.id
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('SELECT * FROM users WHERE user_id = ?', (user_id,)) as c: user = await c.fetchone()
        async with db.execute('SELECT active_boost, boost_end FROM users WHERE user_id = ?', (user_id,)) as c: 
            b_row = await c.fetchone()
            active_boost, boost_end = (b_row[0], b_row[1]) if b_row else ("", 0)

    is_boosted_milk = (time.time() < boost_end and active_boost == "milk_x2")
    is_boosted_luck = (time.time() < boost_end and active_boost == "luck_max")
    
    base_milk = int(MILK_PER_CLICK * user['click_level'] * (2 if is_boosted_milk else 1))
    drop_chance = 1.0 if is_boosted_luck else (0.03 + user['luck_level'] * 0.005)
    spill_chance = max(0, 0.05 - (user['safety_level'] * 0.01))

    if random.random() < spill_chance:
        lost = max(1, int(user['milk'] * 0.1))
        new_total = max(0, user['milk'] - lost)
        await update_stat(user_id, "milk", new_total)
        text = f"⚠️ Разлито {lost} Л. Баланс: {format_num(new_total)} Л"
    elif random.random() > (1 - drop_chance):
        await update_stat(user_id, "fertilizer", user['fertilizer'] + 1)
        new_total = user['milk'] + base_milk
        await update_stat(user_id, "milk", new_total)
        text = f"🥛 +{base_milk} Л + 🧪 Химия! (Всего: {format_num(new_total)} Л)"
        await add_xp(user_id, XP_PER_ACTION, message)
    else:
        new_total = user['milk'] + base_milk
        await update_stat(user_id, "milk", new_total)
        text = f"🥛 +{base_milk} Л (Всего: {format_num(new_total)} Л)"
        await add_xp(user_id, XP_PER_ACTION, message)

    await send_with_cleanup(message, text, reply_markup=main_keyboard())

@dp.message(F.text.in_({"💦 Полить грядку"}))
async def plant_handler(message: types.Message):
    user_id = message.from_user.id
    user = await get_user(user_id)
    is_boosted_tom = (user['active_boost'] == "tomato_x2" and time.time() < user['boost_end'])
    is_free = (user['active_boost'] == "water_free" and time.time() < user['boost_end'])
    
    cost = 0 if is_free else int(max(1, BASE_PLANT_COST - (user['eco_level'] * 0.5)))
    
    if user['milk'] >= cost:
        base_yield = 2 if random.random() < (user['tomato_level'] * 0.05) else 1
        if is_boosted_tom: base_yield *= 2
        
        refund = 0
        if not is_free and random.random() < (user['gmo_level'] * 0.05):
            refund = int(cost * 0.5)
            
        real_cost = cost - refund
        await update_stat(user_id, "milk", user['milk'] - real_cost)
        await update_stat(user_id, "tomatoes", user['tomatoes'] + base_yield)
        
        ref_txt = f" (Кэшбек {refund}Л)" if refund else ""
        text = f"🍅 +{base_yield} шт. (-{real_cost} Л){ref_txt}"
        await add_xp(user_id, XP_PER_ACTION, message)
        
        if random.random() < 0.20:
            m_found = random.randint(1, 3)
            await update_stat(user_id, "mandarins", user['mandarins'] + m_found)
            await message.answer(f"🍊 Найдено {m_found} кг мандаринов!", parse_mode="HTML")
    else:
        text = f"💧 Не хватает воды! Нужно {cost} Л."
        
    await send_with_cleanup(message, text, reply_markup=main_keyboard())

# --- ТОРГОВЕЦ (ФИКС) ---
@dp.message(F.text == "💲 Торговец")
async def shop_menu(message: types.Message):
    user = await get_user(message.from_user.id)
    text = get_shop_text(user)
    await message.answer(text, reply_markup=upgrades_keyboard(user, info_mode=False), parse_mode="HTML")

@dp.callback_query(F.data.startswith("shop_mode_"))
async def switch_shop_mode(cb: CallbackQuery):
    mode = cb.data.split("_")[2]
    user = await get_user(cb.from_user.id)
    try: await cb.message.edit_reply_markup(reply_markup=upgrades_keyboard(user, info_mode=(mode == "info")))
    except: pass
    await cb.answer()

@dp.callback_query(F.data.startswith("buy_"))
async def buy_upgrade(cb: CallbackQuery):
    parts = cb.data.split("_")
    if len(parts) < 3: return
    type_up, mode = parts[1], parts[2]
    
    if mode == "i":
        desc = {
            "click": "Сила клика (+1 молока)", "tomato": "Шанс x2 урожая", "luck": "Шанс дропа химии",
            "safe": "Меньше разлива", "eco": "Дешевле полив", "cas": "Дешевле казино",
            "gmo": "Шанс вернуть молоко", "tractor": "Авто-фарм пока ты спишь"
        }
        await cb.answer(desc.get(type_up, "Нет описания"), show_alert=True)
        return

    user = await get_user(cb.from_user.id)
    tom = user['tomatoes']
    lvl_agr = user['acad_agronomy']
    price_factor = 1.0 - min(0.30, lvl_agr * ACAD_DISCOUNT_PER_LVL)
    
    raw = 0; col = ""; new_lvl = 0
    if type_up == "click": raw = 50 * (1.4 ** user['click_level']); col="click_level"; new_lvl=user[col]+1
    elif type_up == "tomato": raw = 150 * (1.5 ** user['tomato_level']); col="tomato_level"; new_lvl=user[col]+1
    elif type_up == "luck": raw = 500 * (1.6 ** user['luck_level']); col="luck_level"; new_lvl=user[col]+1
    elif type_up == "safe": raw = 300 * (1.4 ** user['safety_level']); col="safety_level"; new_lvl=user[col]+1
    elif type_up == "eco": raw = 1000 * (1.5 ** user['eco_level']); col="eco_level"; new_lvl=user[col]+1
    elif type_up == "cas": raw = 750 * (1.3 ** user['casino_level']); col="casino_level"; new_lvl=user[col]+1
    elif type_up == "gmo": raw = 2000 * (1.7 ** user['gmo_level']); col="gmo_level"; new_lvl=user[col]+1
    elif type_up == "tractor": raw = 5000 * (1.6 ** user['tractor_level']); col="tractor_level"; new_lvl=user[col]+1

    cost = int(raw * price_factor)
    if tom >= cost:
        await update_stat(cb.from_user.id, "tomatoes", tom - cost)
        await update_stat(cb.from_user.id, col, new_lvl)
        if type_up == "tractor" and new_lvl == 1:
            await update_stat(cb.from_user.id, "last_tractor_collect", time.time())
        await cb.answer("Куплено!")
        try: await cb.message.edit_text(get_shop_text(await get_user(cb.from_user.id)), reply_markup=upgrades_keyboard(await get_user(cb.from_user.id), False), parse_mode="HTML")
        except: pass
    else:
        await cb.answer(f"Не хватает {format_num(cost)}!", show_alert=True)

# --- ЛАБОРАТОРИЯ (ФИКС) ---
@dp.message(F.text == "🧬 Лаборатория")
async def lab_menu(message: types.Message):
    user = await get_user(message.from_user.id)
    text = (f"🧬 <b>ГЕННАЯ ЛАБОРАТОРИЯ</b>\n{UI_SEP}\n🧪 Мутаген: {user['mutagen']} ед.\n"
            f"<b>СИНТЕЗ:</b> {CRAFT_CARDS_NEEDED} карты + {CRAFT_COST_MUTAGEN} мутаген = 1 крутая карта.")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Купить Мутаген ({format_num(MUTAGEN_SHOP_PRICE)})", callback_data="buy_mutagen")],
        [InlineKeyboardButton(text="Начать Синтез", callback_data="start_craft_list")],
        [InlineKeyboardButton(text="Закрыть", callback_data="delete_msg")]
    ])
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "buy_mutagen")
async def buy_mutagen_handler(cb: CallbackQuery):
    u = await get_user(cb.from_user.id)
    if u['tomatoes'] >= MUTAGEN_SHOP_PRICE:
        await update_stat(cb.from_user.id, "tomatoes", u['tomatoes'] - MUTAGEN_SHOP_PRICE)
        await update_stat(cb.from_user.id, "mutagen", u['mutagen'] + 1)
        await cb.answer("Куплено!")
        await lab_menu(cb.message); await cb.message.delete()
    else: await cb.answer("Нет денег", show_alert=True)

@dp.callback_query(F.data == "start_craft_list")
async def craft_list_handler(cb: CallbackQuery):
    user_id = cb.from_user.id
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT card_id, count FROM user_cards WHERE user_id = ? AND count >= ?', (user_id, CRAFT_CARDS_NEEDED)) as c:
            rows = await c.fetchall()
    
    if not rows: return await cb.answer("Нет карт для крафта", show_alert=True)
    kb = []
    for cid, cnt in rows:
        if cid in CARDS and CARDS[cid].get('rarity') != 'limited':
            kb.append([InlineKeyboardButton(text=f"{CARDS[cid]['name']} ({cnt})", callback_data=f"do_craft_{cid}")])
    kb.append([InlineKeyboardButton(text="Назад", callback_data="delete_msg")])
    await cb.message.edit_text("Выберите карту для сжигания:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("do_craft_"))
async def execute_craft(cb: CallbackQuery):
    cid = cb.data.split("_")[2]
    u = await get_user(cb.from_user.id)
    if u['mutagen'] < CRAFT_COST_MUTAGEN: return await cb.answer("Нет мутагена!", show_alert=True)
    
    in_rarity = CARDS[cid].get('rarity', 'common')
    tgt_rarity = "rare" if in_rarity == "common" else "epic" if in_rarity == "rare" else "limited"
    pool = [c for c, d in CARDS.items() if d.get('rarity') == tgt_rarity]
    if not pool: return await cb.answer("Ошибка базы", show_alert=True)
    
    reward = random.choice(pool)
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('UPDATE user_cards SET count = count - ? WHERE user_id = ? AND card_id = ?', (CRAFT_CARDS_NEEDED, cb.from_user.id, cid))
        await db.execute('UPDATE users SET mutagen = mutagen - ? WHERE user_id = ?', (CRAFT_COST_MUTAGEN, cb.from_user.id))
        exists = await db.execute_fetchall('SELECT 1 FROM user_cards WHERE user_id = ? AND card_id = ?', (cb.from_user.id, reward))
        if exists: await db.execute('UPDATE user_cards SET count = count + 1 WHERE user_id = ? AND card_id = ?', (cb.from_user.id, reward))
        else: await db.execute('INSERT INTO user_cards (user_id, card_id, count) VALUES (?, ?, 1)', (cb.from_user.id, reward))
        await db.commit()
        
    await cb.message.edit_text(f"Успех! Получено: {CARDS[reward]['name']}")
    await send_card_info(cb.message, reward, 1, True, cb.from_user.id)

# --- АКАДЕМИЯ ---
@dp.message(F.text == "🎓 Академия")
async def nav_academy(message: types.Message):
    user_id = message.from_user.id
    u = await get_user(user_id)
    harvest, msg = await collect_academy_income(user_id, u)
    if harvest > 0: msg = f"\n💰 Собрано: +{harvest} 🍅"
    text, kb = get_academy_render_data(u, harvest_msg=msg)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "acad_refresh")
async def acad_refresh(cb: CallbackQuery):
    user_id = cb.from_user.id
    u = await get_user(user_id)
    harvest, msg = await collect_academy_income(user_id, u)
    if harvest > 0: 
        await cb.answer(f"Собрано {harvest}!", show_alert=False)
        u = await get_user(user_id)
        msg = f"\n💰 Собрано: +{harvest} 🍅"
    else: await cb.answer("Актуально")
    
    text, kb = get_academy_render_data(u, harvest_msg=msg)
    try: await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except: pass

@dp.callback_query(F.data == "acad_upgrades")
async def acad_upgrades_menu(cb: CallbackQuery):
    u = await get_user(cb.from_user.id)
    lvl_man, lvl_log, lvl_agr = u['acad_management'], u['acad_logistics'], u['acad_agronomy']
    
    pm = int(COST_MANAGEMENT * (1.5 ** lvl_man))
    pl = int(COST_LOGISTICS * (1.6 ** lvl_log))
    pa = int(COST_AGRONOMY * (1.8 ** lvl_agr))
    
    text = (f"🎓 <b>ОБУЧЕНИЕ</b>\nМенеджмент (Доход): {lvl_man}\nЛогистика (Время): {lvl_log}\nАгрономия (Скидки): {lvl_agr}")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Доход ({format_num(pm)})", callback_data=f"acad_buy_man_{pm}")],
        [InlineKeyboardButton(text=f"Время ({format_num(pl)})", callback_data=f"acad_buy_log_{pl}")],
        [InlineKeyboardButton(text=f"Скидка ({format_num(pa)})", callback_data=f"acad_buy_agr_{pa}")],
        [InlineKeyboardButton(text="Назад", callback_data="acad_refresh")]
    ])
    await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("acad_buy_"))
async def acad_buy(cb: CallbackQuery):
    parts = cb.data.split("_")
    ctype, price = parts[2], int(parts[3])
    u = await get_user(cb.from_user.id)
    if u['tomatoes'] < price: return await cb.answer("Не хватает денег", show_alert=True)
    
    col = "acad_management" if ctype=="man" else "acad_logistics" if ctype=="log" else "acad_agronomy"
    await update_stat(cb.from_user.id, "tomatoes", u['tomatoes']-price)
    await update_stat(cb.from_user.id, col, u[col]+1)
    if ctype=="man" and u[col]==0: await update_stat(cb.from_user.id, "last_acad_collect", time.time())
    
    await cb.answer("Изучено!")
    await acad_upgrades_menu(cb)

# --- НАВИГАЦИЯ И ПРОФИЛЬ ---
@dp.message(F.text == "🏙 Город")
async def nav_town(message: types.Message):
    await message.answer("🏙 Город", reply_markup=town_keyboard())

@dp.message(F.text == "🎡 Развлечения")
async def nav_fun(message: types.Message):
    await message.answer("🎡 Парк", reply_markup=fun_keyboard())

@dp.message(F.text == "⤾ Назад")
async def nav_back(message: types.Message):
    await message.answer("🏡 Ферма", reply_markup=main_keyboard())

@dp.message(F.text == "👤 Личный Кабинет")
async def profile_new(message: types.Message):
    user = await get_user(message.from_user.id)
    text = (f"👤 <b>ПРОФИЛЬ</b>\nID: {user['user_id']}\n"
            f"🍅 {format_num(user['tomatoes'])} | 🥛 {format_num(user['milk'])} | 🧪 {user['fertilizer']}\n"
            f"🍊 Мандарины: {format_num(user['mandarins'])} кг")
    await message.answer(text, parse_mode="HTML")

# --- РЫНОК И КАРТЫ ---
@dp.message(F.text == "🎴 Коллекция")
async def show_cards(message: types.Message):
    await show_inventory(message)

@dp.callback_query(F.data.startswith("view_card_"))
async def view_card(cb: CallbackQuery):
    parts = cb.data.split("_")
    if len(parts) < 3: return
    cid = parts[2]
    user_id = cb.from_user.id
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT count FROM user_cards WHERE user_id=? AND card_id=?', (user_id, cid)) as c:
            cnt = (await c.fetchone() or [0])[0]
    await send_card_info(cb.message, cid, cnt, True, user_id)
    await cb.answer()

@dp.callback_query(F.data.startswith("peek_card_"))
async def peek_card(cb: CallbackQuery):
    parts = cb.data.split("_")
    uid, cid = int(parts[2]), parts[3]
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT count FROM user_cards WHERE user_id=? AND card_id=?', (uid, cid)) as c:
            cnt = (await c.fetchone() or [0])[0]
    await send_card_info(cb.message, cid, cnt, False, uid)
    await cb.answer()

@dp.callback_query(F.data == "delete_msg")
async def del_msg(cb: CallbackQuery): await cb.message.delete()

@dp.message(F.text == "⚖️ Биржа Игроков")
async def show_market(message: types.Message):
    await show_market_page(message)

@dp.callback_query(F.data.startswith("market_page_"))
async def market_page_h(cb: CallbackQuery):
    await show_market_page(cb, int(cb.data.split("_")[2]))
    await cb.answer()

@dp.callback_query(F.data.startswith("buy_lot_"))
async def buy_lot_h(cb: CallbackQuery):
    await buy_lot(cb)

# --- КАЗИНО ---
@dp.message(F.text == "🎲 Казино")
async def casino_handler(message: types.Message):
    user = await get_user(message.from_user.id)
    bet = max(2, BASE_CASINO_COST - user['casino_level'])
    if user['tomatoes'] < bet: return await send_with_cleanup(message, "Нет денег")
    
    await update_stat(message.from_user.id, "tomatoes", user['tomatoes'] - bet)
    dice = await message.answer_dice("🎰")
    await asyncio.sleep(2)
    val = dice.dice.value
    win = 0
    if val == 64: win = bet * 10
    elif val == 43: win = bet * 3
    elif val == 22: win = bet * 2
    elif val == 1: win = bet
    
    if win: await update_stat(message.from_user.id, "tomatoes", user['tomatoes'] - bet + win)
    try: await dice.delete()
    except: pass
    await send_with_cleanup(message, f"Результат: {'Выигрыш '+str(win) if win else 'Проигрыш'}", reply_markup=fun_keyboard())

# --- ТЕРМИНАЛ (ПРОМОКОДЫ) ---
@dp.message(F.text == "📟 Терминал")
async def code_start(m: Message, state: FSMContext):
    await m.answer("Введи код:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(GameStates.waiting_for_code)

@dp.message(StateFilter(GameStates.waiting_for_code))
async def code_proc(m: Message, state: FSMContext):
    code = m.text.strip()
    user_id = m.from_user.id
    if code == "sosi":
        await update_stat(user_id, "milk", (await get_user(user_id))['milk']+10)
        await m.answer("Пасхалка!", reply_markup=main_keyboard())
    else:
        async with aiosqlite.connect(DB_NAME) as db:
            c = await db.execute("SELECT * FROM promo_codes WHERE code=?", (code,))
            promo = await c.fetchone()
            if promo:
                used = await db.execute("SELECT 1 FROM used_codes WHERE user_id=? AND code=?", (user_id, code))
                if not await used.fetchone() and promo[1] != 0:
                    await db.execute(f"UPDATE users SET {promo[2]}={promo[2]}+? WHERE user_id=?", (promo[3], user_id))
                    await db.execute("INSERT INTO used_codes VALUES (?,?)", (user_id, code))
                    if promo[1] > 0: await db.execute("UPDATE promo_codes SET uses_left=uses_left-1 WHERE code=?", (code,))
                    await db.commit()
                    await m.answer(f"Код активирован! +{promo[3]} {promo[2]}", reply_markup=main_keyboard())
                else: await m.answer("Уже использован или кончился.", reply_markup=main_keyboard())
            else: await m.answer("Неверный код.", reply_markup=main_keyboard())
    await state.clear()

# --- СЕЗОН (BATTLE PASS) ---
@dp.message(F.text == "🎟 Сезон")
async def battle_pass_menu(message: types.Message):
    u = await get_user(message.from_user.id)
    lvl, xp = u['bp_level'], u['bp_xp']
    req = lvl * XP_PER_LEVEL_BASE
    claimed = u['bp_claimed'].split(',') if u['bp_claimed'] else []
    
    kb = []
    for r_lvl, (rt, ra) in BP_REWARDS.items():
        if lvl >= r_lvl and str(r_lvl) not in claimed:
            kb.append([InlineKeyboardButton(text=f"🎁 Забрать за {r_lvl} ур: {ra} {rt}", callback_data=f"bp_claim_{r_lvl}")])
            
    text = f"🎟 <b>СЕЗОН</b>\nУровень: {lvl}\nXP: {xp}/{req}"
    if not kb: text += "\nНаград пока нет."
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb) if kb else None, parse_mode="HTML")

@dp.callback_query(F.data.startswith("bp_claim_"))
async def bp_claim(cb: CallbackQuery):
    rlvl = int(cb.data.split("_")[2])
    uid = cb.from_user.id
    u = await get_user(uid)
    cl = u['bp_claimed'].split(',') if u['bp_claimed'] else []
    
    if str(rlvl) in cl or u['bp_level'] < rlvl: return await cb.answer("Ошибка")
    
    rtype, ramt = BP_REWARDS[rlvl]
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(f'UPDATE users SET {rtype} = {rtype} + ? WHERE user_id = ?', (ramt, uid))
        cl.append(str(rlvl))
        await db.execute('UPDATE users SET bp_claimed = ? WHERE user_id = ?', (",".join(cl), uid))
        await db.commit()
    await cb.answer("Получено!")
    await cb.message.delete()

# --- НОВАЯ АДМИН ПАНЕЛЬ (GUI) ---
@dp.message(Command("admin"))
async def admin_gui(message: types.Message, state: FSMContext):
    if message.from_user.username.lower() not in ADMINS: return
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Ресурсы", callback_data="adm_eco"), InlineKeyboardButton(text="Карты", callback_data="adm_cards")],
        [InlineKeyboardButton(text="Закрыть", callback_data="delete_msg")]
    ])
    await message.answer("Админка", reply_markup=kb)

@dp.callback_query(F.data == "delete_msg")
async def delete_msg(cb: CallbackQuery): await cb.message.delete()

@dp.callback_query(F.data == "adm_eco")
async def adm_eco(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdminEcoStates.waiting_for_user_id)
    await cb.message.edit_text("Введи ID юзера (или ALL):")

@dp.message(StateFilter(AdminEcoStates.waiting_for_user_id))
async def adm_eco_id(msg: Message, state: FSMContext):
    await state.update_data(uid=msg.text)
    await state.set_state(AdminEcoStates.waiting_for_amount)
    await msg.answer("Введи: resource amount (пример: tomatoes 1000)")

@dp.message(StateFilter(AdminEcoStates.waiting_for_amount))
async def adm_eco_fin(msg: Message, state: FSMContext):
    data = await state.get_data()
    uid = data['uid']
    try:
        res, amt = msg.text.split()
        amt = int(amt)
        async with aiosqlite.connect(DB_NAME) as db:
            if uid == "ALL": await db.execute(f"UPDATE users SET {res}={res}+?", (amt,))
            else: await db.execute(f"UPDATE users SET {res}={res}+? WHERE user_id=?", (amt, int(uid)))
            await db.commit()
        await msg.answer("Готово.")
    except: await msg.answer("Ошибка.")
    await state.clear()

@dp.callback_query(F.data == "adm_cards")
async def adm_cards(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdminCardStates.waiting_for_card_id)
    await cb.message.edit_text("Введи ID карты:")

@dp.message(StateFilter(AdminCardStates.waiting_for_card_id))
async def adm_card_id(msg: Message, state: FSMContext):
    if msg.text not in CARDS: return await msg.answer("Нет такой карты.")
    await state.update_data(cid=msg.text)
    await state.set_state(AdminCardStates.waiting_for_target)
    await msg.answer("Введи ID юзера (или ALL):")

@dp.message(StateFilter(AdminCardStates.waiting_for_target))
async def adm_card_fin(msg: Message, state: FSMContext):
    data = await state.get_data()
    cid = data['cid']
    uid = msg.text
    async with aiosqlite.connect(DB_NAME) as db:
        targets = [uid] if uid != "ALL" else [r[0] for r in await db.execute_fetchall("SELECT user_id FROM users")]
        for t in targets:
            exists = await db.execute_fetchall("SELECT 1 FROM user_cards WHERE user_id=? AND card_id=?", (t, cid))
            if exists: await db.execute("UPDATE user_cards SET count=count+1 WHERE user_id=? AND card_id=?", (t, cid))
            else: await db.execute("INSERT INTO user_cards VALUES (?,?,1)", (t, cid))
        await db.commit()
    await msg.answer(f"Выдано {len(targets)} игрокам.")
    await state.clear()

# --- КОНСОЛЬ ---
async def admin_console_loop(bot: Bot):
    global CONSOLE_LOGS, MAINTENANCE_MODE
    os.system('cls' if os.name == 'nt' else 'clear')
    print("Bot Started!")
    while True:
        try:
            sys.stdout.write("\nadmin> "); sys.stdout.flush()
            cmd = await aioconsole.ainput("")
            if not cmd: continue
            parts = cmd.split()
            c = parts[0].lower()
            
            if c == "restart": os.execl(sys.executable, sys.executable, *sys.argv)
            elif c == "logs": CONSOLE_LOGS = not CONSOLE_LOGS; print(f"Logs: {CONSOLE_LOGS}")
            elif c == "give" and len(parts)>3:
                async with aiosqlite.connect(DB_NAME) as db:
                    await db.execute(f"UPDATE users SET {parts[2]}={parts[2]}+? WHERE user_id=?", (int(parts[3]), int(parts[1])))
                    await db.commit()
                print("Given.")
            elif c == "sql":
                q = " ".join(parts[1:])
                async with aiosqlite.connect(DB_NAME) as db:
                    await db.execute(q); await db.commit()
                print("Executed.")
        except Exception as e: print(e)

# --- START ---
async def main():
    await init_db()
    async with aiosqlite.connect(DB_NAME) as db:
        admins = await db.execute_fetchall("SELECT username FROM users WHERE is_admin=1")
        for (a,) in admins: 
            if a and a.lower() not in ADMINS: ADMINS.append(a.lower())
    
    await bot.delete_webhook(drop_pending_updates=True)
    await asyncio.gather(dp.start_polling(bot), admin_console_loop(bot))

if __name__ == "__main__":
    asyncio.run(main())
