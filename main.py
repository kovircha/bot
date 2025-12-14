import json
import os
import asyncio
import logging
import random
import time
import math
import aiosqlite
import sys
from colorama import init, Fore, Style
import aioconsole
import httpx

    
# --- КОНФИГУРАЦИЯ АКАДЕМИИ (SWISS EDITION) ---
ACAD_BASE_INCOME = 100       # Базовый доход (помидоры/час)
ACAD_INCOME_MULT = 50        # Сколько добавляет 1 уровень Менеджмента
ACAD_BASE_TIME = 6           # Базовое время AFK (часы)
ACAD_TIME_BONUS = 1          # Сколько часов добавляет 1 уровень Логистики
ACAD_DISCOUNT_PER_LVL = 0.02 # 2% скидка за уровень Агрономии (Макс 30%)

# Цены улучшений (База)
COST_MANAGEMENT = 1000
COST_LOGISTICS = 2500
COST_AGRONOMY = 5000

# --- КОНФИГУРАЦИЯ GO MARKET ---
GO_MARKET_URL = "http://localhost:8082"

# --- НАСТРОЙКИ КОНСОЛИ И РЕЖИМОВ ---
CONSOLE_LOGS = False      # Включен ли лог действий в консоли
MAINTENANCE_MODE = False  # Режим техработ (бот работает только для админов)

# Путь к папке с картинками (должна лежать рядом с main.py)
CARDS_DIR = "img_cards"

# Проверка, существует ли папка, если нет - создаем (чтобы не было ошибок)
if not os.path.exists(CARDS_DIR):
    os.makedirs(CARDS_DIR)

# Инициализация цветов
init(autoreset=True)
from aiogram import Bot, Dispatcher, F, types, BaseMiddleware
from aiogram.filters import Command, StateFilter
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, 
    InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery, Message, BotCommand, FSInputFile,
    InputMediaPhoto, ReplyKeyboardRemove 

)
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# --- КОНФИГУРАЦИЯ ---
TOKEN = '8482572401:AAHR91Uwrq6U2-ody9jYUmQxme3xOeyzyvg'

# --- НАСТРОЙКИ КАНАЛА ---
# ID канала (можно @username или числовой ID типа -100...)
# ВАЖНО: Бот должен быть админом в этом канале!
REQUIRED_CHANNEL_ID = "@molokofarmoff" 
REQUIRED_CHANNEL_URL = "https://t.me/molokofarmoff"

# --- ЗАГРУЗКА КАРТ ---
def load_cards():
    with open("cards.json", "r", encoding="utf-8") as f:
        return json.load(f)

CARDS = load_cards()

# --- ДИЗАЙН-КОНСТАНТЫ ---
UI_SEP = "━━━━━━━━━━━━━━━"
UI_BULLET = "▪️"
UI_SUB_BULLET = "▫️"

# --- НАСТРОЙКИ РЕДКОСТИ (PREMIUM STYLE) ---
RARITY_INFO = {
    "common": {
        "name": "Обычная", 
        "icon": "⚪", 
        "color_code": 0xA0A0A0 
    },
    "rare": {
        "name": "Редкая", 
        "icon": "🔵", 
        "color_code": 0x4169E1
    },
    "epic": {
        "name": "Эпическая", 
        "icon": "🟣", 
        "color_code": 0x8A2BE2
    },
    "limited": {
        "name": "Limited", 
        "icon": "💠", 
        "color_code": 0xFFD700 
    }
}

# Для ресурсов (Помидоры, Молоко)
class AdminEcoStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_amount = State()

class AdminCardStates(StatesGroup):
    waiting_for_card_id = State()
    waiting_for_target = State()
    
class AdminPanelStates(StatesGroup):
    waiting_for_user_id = State() # Ждем ID игрока
    waiting_for_value = State()   # Ждем число или текст

class MarketStates(StatesGroup):
    waiting_for_price = State()
    card_id_to_sell = State() # Тут будем временно хранить какую карту продаем

class BroadcastStates(StatesGroup):
    waiting_for_broadcast_text = State() 
    waiting_for_broadcast_confirm = State()    

# --- FSM ---
class GameStates(StatesGroup):
    waiting_for_code = State()

class PlotStates(StatesGroup):
    waiting_for_plot_id = State() 
    waiting_for_plot_confirm = State() # <-- НОВЫЙ STATE  

# --- MIDDLEWARE (ОБНОВЛЕННЫЙ) ---
class GameMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: Message, data: dict):
        # Получаем объект User (для сообщений или колбэков)
        if isinstance(event, Message):
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user
        else:
            return await handler(event, data)
            
        if not user: return await handler(event, data)

        # 1. Обновляем имя и ВРЕМЯ АКТИВНОСТИ
        current_time = time.time()
        asyncio.create_task(update_username(user.id, user.full_name))
        
        # Прямое обновление в БД для точности статистики (fire and forget)
        async def set_active():
            async with aiosqlite.connect(DB_NAME) as db:
                await db.execute('UPDATE users SET last_active = ? WHERE user_id = ?', (current_time, user.id))
                await db.commit()
        asyncio.create_task(set_active())

        # 1. Обновляем имя в БД
        asyncio.create_task(update_username(user.id, user.full_name))

        # 2. Пропускаем Админов без проверок
        if user.username and user.username.lower() in ADMINS:
            return await handler(event, data)

        # 1. ПРОВЕРКА ТЕХРАБОТ
        if MAINTENANCE_MODE and user.username.lower() not in ADMINS:
            if isinstance(event, Message):
                await event.answer("🚧 <b>Бот на техническом обслуживании.</b>\nПодождите пару минут.", parse_mode="HTML")
            elif isinstance(event, CallbackQuery):
                await event.answer("🚧 Техработы!", show_alert=True)
            return

        # 2. ЖИВОЙ ЛОГ В КОНСОЛЬ (Если включен)
        if CONSOLE_LOGS:
            # Красивый вывод: [ВРЕМЯ] [ID] Имя: Действие
            t = time.strftime("%H:%M:%S")
            
            # Раскраска в зависимости от типа
            color = Fore.CYAN if action_type == "MSG" else Fore.YELLOW
            
            print(f"{Style.DIM}[{t}]{Style.RESET_ALL} {Fore.MAGENTA}{user.id}{Style.RESET_ALL} | {Fore.WHITE}{user.full_name}{Style.RESET_ALL} -> {color}{content}{Style.RESET_ALL}")

        # 3. Обновляем активность в БД (Fire and Forget)
        current_time = time.time()
        asyncio.create_task(update_username(user.id, user.full_name))
        
        async def set_active():
            async with aiosqlite.connect(DB_NAME) as db:
                await db.execute('UPDATE users SET last_active = ? WHERE user_id = ?', (current_time, user.id))
                await db.commit()
        asyncio.create_task(set_active())

        # 4. Пропуск Админов (всегда разрешено)
        if user.username and user.username.lower() in ADMINS:
            return await handler(event, data)

        # --- ЛОГИКА ПРОВЕРКИ ПОДПИСКИ ---
        try:
            # Спрашиваем у Телеграма статус пользователя в канале
            chat_member = await bot.get_chat_member(chat_id=REQUIRED_CHANNEL_ID, user_id=user.id)
            
            # Если статус 'left' (ушел) или 'kicked' (выгнан) -> Блокируем
            if chat_member.status in ['left', 'kicked']:
                
                # Клавиатура подписки
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="📢 Подписаться на канал", url=REQUIRED_CHANNEL_URL)],
                    [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_subscription")]
                ])

                # Если нажали кнопку проверки, но подписки нет
                if isinstance(event, CallbackQuery) and event.data == "check_subscription":
                    await event.answer("❌ Вы еще не подписались! Проверьте подписку.", show_alert=True)
                    return 

                # Если пишут сообщение или жмут другие кнопки
                if isinstance(event, Message):
                    await event.answer(
                        "🔒 <b>Доступ закрыт!</b>\n\nДля игры необходимо быть подписчиком нашего канала.",
                        reply_markup=kb,
                        parse_mode="HTML"
                    )
                elif isinstance(event, CallbackQuery):
                    # Если это был клик по другой кнопке
                    await event.message.answer("🔒 Для продолжения подпишись на канал!", reply_markup=kb)
                    await event.answer()
                
                # Прерываем обработку (не пускаем дальше)
                return 
                
        except Exception as e:
            # Если бот не админ или канал указан неверно - пишем в консоль, но игрока пускаем
            print(f"Ошибка проверки подписки (Бот не админ?): {e}")

        # --- ЛОГИКА АНТИ-СПАМА (Остается как была) ---
        current_time = time.time()
        if user.id in muted_users:
            if current_time < muted_users[user.id]: return 
            else: del muted_users[user.id]

        if user.id not in user_timestamps: user_timestamps[user.id] = []
        user_timestamps[user.id] = [t for t in user_timestamps[user.id] if current_time - t < 1.0]
        user_timestamps[user.id].append(current_time)
        
        if len(user_timestamps[user.id]) > SPAM_LIMIT:
            muted_users[user.id] = current_time + MUTE_TIME
            if isinstance(event, Message):
                await event.answer(f"⛔️ <b>Остынь!</b> Мут на {MUTE_TIME} сек.", parse_mode="HTML")
            elif isinstance(event, CallbackQuery):
                await event.answer(f"⛔️ Остынь! Мут на {MUTE_TIME} сек.", show_alert=True)
            return 
        
        # Проверка старого меню (только для сообщений)
        valid_buttons = [
            "🥛 Сбор Молока", "💦 Полить грядку", "🏙 Город", "🎡 Развлечения", "👤 Личный Кабинет",
            "🎅 Сезонный Торговец", "📦 Хранилище", "🏆 Рейтинг", "📟 Терминал", "⤾ Назад",
            "🎲 Казино", "🎁 Ежедневный бонус", "🥔 Плантация", "🎴 Коллекция", "🎓 Академия", "🧬 Лаборатория", "💲 Торговец", "⚖️ Биржа Игроков"
            "🔄 Обновить данные"
        ]
        
        if isinstance(event, Message) and not event.text.startswith("/") and event.text not in valid_buttons:
             await event.answer("⚠️ Меню обновлено.", reply_markup=main_keyboard())

        return await handler(event, data)

# --- ЛОГИКА AFK-ФАРМА АКАДЕМИИ (IQ) ---

async def collect_afk_iq(user_id: int, u: aiosqlite.Row) -> (int, str):
    """Рассчитывает AFK-урожай с Академии."""
    
    iq_level = u['iq_level']
    last_collect = u['last_iq_collect']
    
    if iq_level == 0:
        return 0, ""

    now = time.time()
    
    elapsed_seconds = now - last_collect
    elapsed_hours = min(elapsed_seconds / 3600, AFK_FARM_MAX_HOURS)

    # Нечего собирать, или это первый вход (last_collect == 0)
    if elapsed_hours < 0.1 and last_collect != 0: 
        return 0, ""
        
    # Расчет урожая: Базовая ставка * Уровень * Часы
    harvest = int(AFK_FARM_BASE_RATE * iq_level * elapsed_hours)
    
    if harvest > 0:
        # Выдаем урожай
        await update_stat(user_id, "tomatoes", u['tomatoes'] + harvest)
        # Обновляем время сбора
        await update_stat(user_id, "last_iq_collect", now) 
        
        return harvest, (
            f"🧠 <b>АКАДЕМИЯ:</b> Интеллект принес {harvest} 🍅!\n"
            f"Учебный центр работал {round(elapsed_hours, 1)} из {AFK_FARM_MAX_HOURS} часов."
        )
    
    return 0, ""

# --- ИНИЦИАЛИЗАЦИЯ БОТА ---
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

dp.message.middleware(GameMiddleware())

# Пути к картинкам сундуков (положи файлы close_chest.jpg и open_chest.jpg в папку с ботом)
# Или используй ссылки, если файлов нет
CHEST_CLOSE_PATH = "closed_chest.png" 
CHEST_OPEN_PATH = "open_chest.png"

# Ссылки-заглушки (на случай если нет файлов)
URL_CHEST_CLOSE = ""
URL_CHEST_OPEN = "https://img.freepik.com/premium-vector/opened-wooden-chest-box-with-gold-coins-game-ui-asset-vector-illustration_1045168-19.jpg"

DAILY_COOLDOWN = 86400 # 24 часа в секундах
JACKPOT_CHANCE = 100000 # 1 к 100 000

# ... (в разделе, где у вас определены пути/настройки) ...

# --- ИВЕНТ ПУГАЛО (ОБНОВЛЕНО) ---
# Пути к файлам (закинь картинки scarecrow_bad.jpg и scarecrow_good.jpg в папку)
SCARECROW_BAD_PATH = "scarecrow_bad.jpg"   # Пугало в воронах
SCARECROW_GOOD_PATH = "scarecrow_good.jpg" # Довольное пугало

# Ссылки заглушки (Используйте прямые ссылки на картинки!)
URL_SCARECROW_BAD = "https://i.ibb.co/L5hY5Xn/scarecrow-bad.jpg"   # Пример URL-заглушки
URL_SCARECROW_GOOD = "https://i.ibb.co/9V40K5z/scarecrow-good.jpg" # Пример URL-заглушки

SCARECROW_COOLDOWN = 10800  # 3 часа (в секундах) - Оставляем
BOOST_DURATION = 600        # 10 минут действия буста (в секундах) <-- ИЗМЕНЕНО

# --- АНИМАЦИЯ ГРИНЧА (УДАЛИТЬ/ИГНОРИРОВАТЬ) --- 
# Эти переменные больше не используются, но могут остаться в коде, если вы их не удалите.
# GRINCH_FRAMES = ["grinch_1.jpg", ...]
# GRINCH_URLS = ["https://...", ...]

# Админы (без @)
ADMINS = ['silentglove', 'octoberchaos']

# Логотип (если есть файл logo.jpg - юзаем его, иначе ссылку)
LOGO_PATH = "logo new year.png"
DEFAULT_LOGO_URL = "https://storage.googleapis.com/pod_public/1300/243765.jpg"

# --- ИВЕНТ ПУГАЛО ---
# Пути к файлам (закинь картинки scarecrow_bad.jpg и scarecrow_good.jpg в папку)
SCARECROW_BAD_PATH = "scarecrow_bad.jpg"   # Пугало в воронах
SCARECROW_GOOD_PATH = "scarecrow_good.jpg" # Довольное пугало

# Ссылки заглушки
URL_SCARECROW_BAD = "https://img.freepik.com/premium-photo/scarecrow-standing-cornfield-with-crows-flying-around-generated-by-ai_1038957-257.jpg"
URL_SCARECROW_GOOD = "https://img.freepik.com/premium-photo/cute-scarecrow-cartoon-character-generated-ai_406939-9305.jpg"

SCARECROW_COOLDOWN = 10800  # 3 часа (в секундах)
BOOST_DURATION = 1800       # 30 минут действия буста (в секундах)

# --- БАЛАНС И ЦЕНЫ ---
MILK_PER_CLICK = 1
BASE_PLANT_COST = 5
BASE_CASINO_COST = 10
FERT_EFFECT = 5

# --- БАЗА ДАННЫХ ---
DB_NAME = 'farm_v4.db'

# --- ANTI-SPAM ---
SPAM_LIMIT = 12 # Чуть поднял лимит, чтобы веселее кликать
MUTE_TIME = 60
user_timestamps = {}
muted_users = {}



# 1. Нажали "Продать" в инвентаре
@dp.callback_query(F.data.startswith("sell_init_"))
async def sell_init(cb: CallbackQuery, state: FSMContext):
    card_id = cb.data.split("_")[2]
    
    await state.update_data(card_id=card_id)
    await state.set_state(MarketStates.waiting_for_price)
    
    card_name = CARDS[card_id]["name"]
    await cb.message.answer(f"💰 За сколько помидоров ты хочешь продать <b>{card_name}</b>?\n\n✍️ <i>Напиши цену числом (например: 1000)</i>", parse_mode="HTML")
    await cb.answer()

# 2. Игрок ввел цену
@dp.message(StateFilter(MarketStates.waiting_for_price))
async def sell_confirm(message: types.Message, state: FSMContext):
    try:
        price = int(message.text)
        if price < 1: raise ValueError
    except:
        await message.answer("❌ Введи нормальное число больше 0.")
        return

    data = await state.get_data()
    card_id = data['card_id']
    user_id = message.from_user.id
    username = message.from_user.full_name

    async with aiosqlite.connect(DB_NAME) as db:
        # Проверяем, есть ли карта (защита от дюпа)
        async with db.execute('SELECT count FROM user_cards WHERE user_id = ? AND card_id = ?', (user_id, card_id)) as c:
            row = await c.fetchone()
            
        if not row or row[0] < 1:
            await message.answer("❌ У тебя уже нет этой карты!")
            await state.clear()
            return

        # 1. Забираем карту у игрока
        new_count = row[0] - 1
        if new_count == 0:
            await db.execute('DELETE FROM user_cards WHERE user_id = ? AND card_id = ?', (user_id, card_id))
        else:
            await db.execute('UPDATE user_cards SET count = ? WHERE user_id = ? AND card_id = ?', (new_count, user_id, card_id))
            
        # 2. Выставляем на рынок
        await db.execute('INSERT INTO market (seller_id, seller_name, card_id, price) VALUES (?, ?, ?, ?)', 
                         (user_id, username, card_id, price))
        await db.commit()

    await message.answer(f"✅ Лот создан! <b>{CARDS[card_id]['name']}</b> выставлен за {price} 🍅.", parse_mode="HTML")
    await state.clear()

# Путь к папке с картинками
CARDS_DIR = "img_cards"

async def send_card_info(message: types.Message, card_id: str, count: int = 1):
    if card_id not in CARDS:
        await message.answer("❌ Ошибка: карта не найдена в базе.")
        return

    card = CARDS[card_id]
    rarity_data = RARITY_INFO.get(card["rarity"], RARITY_INFO["common"])
    
    # Стилизация имени редкости: [Цвет] Имя
    rarity_style = f"<font color=\"#{hex(rarity_data['color_code'])[2:]}\"><b>{rarity_data['name']}</b></font>"

    # Текст карточки
    caption = (
        f"{rarity_data['icon']} <b>{card['name']}</b>\n"
        f"➖➖➖➖➖➖➖➖\n"
        f"🎭 Редкость: {rarity_style}\n" # <--- ИСПОЛЬЗУЕМ СТИЛЬ
        f"📜 Описание: <i>{card.get('desc', 'Нет описания')}</i>\n"
        f"🎒 У тебя в наличии: <b>{count} шт.</b>"
    )
    # ... (Остальной код загрузки фото и кнопок без изменений) ...
    
    # Кнопка продажи
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💰 Продать карту", callback_data=f"sell_init_{card_id}")]
    ])

    # --- ЛОГИКА ЗАГРУЗКИ ФОТО ИЗ ПАПКИ (Оставляем как есть) ---
    image_filename = card.get("img", "default.jpg") 
    image_path = os.path.join(CARDS_DIR, image_filename)
    
    try:
        if os.path.exists(image_path):
            photo = FSInputFile(image_path)
            await message.answer_photo(photo, caption=caption, reply_markup=kb, parse_mode="HTML")
        else:
            await message.answer(
                f"🖼 <i>(Файл {image_filename} не найден)</i>\n\n" + caption, 
                reply_markup=kb, 
                parse_mode="HTML"
            )
    except Exception as e:
        await message.answer(f"Ошибка отправки фото: {e}\n\n" + caption, reply_markup=kb, parse_mode="HTML")

# --- ПРОДВИНУТЫЙ РЫНОК ---

async def get_market_page(page: int = 0):
    LIMIT = 1  # Показываем по 1 лоту на странице (как карточки в Тиндере/Авито)
    offset = page * LIMIT
    
    async with aiosqlite.connect(DB_NAME) as db:
        # Считаем всего лотов
        async with db.execute('SELECT COUNT(*) FROM market') as c:
            total_lots = (await c.fetchone())[0]
            
        # Берем конкретный лот для текущей страницы
        async with db.execute('SELECT lot_id, seller_name, card_id, price, seller_id FROM market ORDER BY lot_id DESC LIMIT ? OFFSET ?', (LIMIT, offset)) as c:
            lot = await c.fetchone()
            
    return lot, total_lots

async def show_market_page(message_or_call, page=0):
    # 1. Получаем данные
    lot, total = await get_market_page(page)
    
    # 2. Если пусто
    if not lot:
        text = "⚖️ <b>ТОРГОВАЯ БИРЖА:</b> Лотов нет\nРазместите актив первым."
        kb = None
        if isinstance(message_or_call, CallbackQuery):
            await message_or_call.message.edit_text(text, parse_mode="HTML")
        else:
            await message_or_call.answer(text, parse_mode="HTML")
        return

    # 3. Распаковка
    lot_id, seller, card_id, price, seller_id = lot
    card_info = CARDS.get(card_id, {"name": "Неизвестный актив", "rarity": "common"})
    
    rarity_data = RARITY_INFO.get(card_info.get("rarity", "common"), RARITY_INFO["common"])
    rarity_text = f"<b>{rarity_data['name']}</b>"
    
    text = (
        f"⚖️ <b>ТОРГОВАЯ БИРЖА</b> | Лот #{page + 1}/{total}\n"
        f"{UI_SEP}\n"
        f"📦 <b>АКТИВ:</b> {card_info['name']}\n"
        f"💎 <b>КЛАСС:</b> {rarity_text}\n"
        f"👤 <b>ПРОДАВЕЦ:</b> {seller}\n"
        f"{UI_SEP}\n"
        f"💰 <b>СТОИМОСТЬ:</b> <code>{format_num(price)}</code> 🍅\n"
    )

    # 4. Кнопки
    buttons = []
    user_id = message_or_call.from_user.id
    
    if user_id == seller_id:
        buy_btn = InlineKeyboardButton(text="🗑 Удалить лот", callback_data=f"market_delete_{lot_id}")
    else:
        buy_btn = InlineKeyboardButton(text=f"💳 Купить ({format_num(price)})", callback_data=f"buy_lot_{lot_id}")
    
    buttons.append([buy_btn])
    
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="◀️", callback_data=f"market_page_{page-1}"))
    
    nav_row.append(InlineKeyboardButton(text=f"📄 {page+1}", callback_data="ignore"))
    
    if (page + 1) < total:
        nav_row.append(InlineKeyboardButton(text="▶️", callback_data=f"market_page_{page+1}"))
        
    buttons.append(nav_row)
    buttons.append([InlineKeyboardButton(text="🔄 Обновить список", callback_data=f"market_page_{page}")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    # 5. Отправка
    if isinstance(message_or_call, CallbackQuery):
        await message_or_call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await message_or_call.answer(text, reply_markup=kb, parse_mode="HTML")

# Хендлер перелистывания
@dp.callback_query(F.data.startswith("market_page_"))
async def market_nav(cb: CallbackQuery):
    page = int(cb.data.split("_")[2])
    await show_market_page(cb, page)
    await cb.answer()

# Хендлер удаления своего лота
@dp.callback_query(F.data.startswith("market_delete_"))
async def market_delete_own(cb: CallbackQuery):
    lot_id = int(cb.data.split("_")[2])
    user_id = cb.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        # Проверяем, что лот принадлежит юзеру
        async with db.execute('SELECT card_id FROM market WHERE lot_id = ? AND seller_id = ?', (lot_id, user_id)) as c:
            row = await c.fetchone()
            
        if not row:
            await cb.answer("❌ Лот не найден или уже продан.", show_alert=True)
            await show_market_page(cb, 0)
            return
            
        card_id = row[0]
        
        # Удаляем лот
        await db.execute('DELETE FROM market WHERE lot_id = ?', (lot_id,))
        
        # Возвращаем карту
        # Проверяем, есть ли уже запись в инвентаре
        async with db.execute('SELECT count FROM user_cards WHERE user_id = ? AND card_id = ?', (user_id, card_id)) as c:
            exists = await c.fetchone()
            
        if exists:
            await db.execute('UPDATE user_cards SET count = count + 1 WHERE user_id = ? AND card_id = ?', (user_id, card_id))
        else:
            await db.execute('INSERT INTO user_cards (user_id, card_id, count) VALUES (?, ?, 1)', (user_id, card_id))
            
        await db.commit()
        
    await cb.answer("✅ Лот удален, карта возвращена!")
    await show_market_page(cb, 0)

@dp.callback_query(F.data == "ignore")
async def ignore_click(cb: CallbackQuery):
    await cb.answer()

# Покупка лота
@dp.callback_query(F.data.startswith("buy_lot_"))
async def buy_lot(cb: CallbackQuery):
    lot_id = int(cb.data.split("_")[2])
    buyer_id = cb.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        # 1. Проверяем лот (не купили ли его уже)
        async with db.execute('SELECT seller_id, card_id, price FROM market WHERE lot_id = ?', (lot_id,)) as c:
            lot = await c.fetchone()
            
        if not lot:
            await cb.answer("❌ Лот уже куплен или удален!", show_alert=True)
            try: await cb.message.delete() # Удаляем устаревшее сообщение
            except: pass
            return
            
        seller_id, card_id, price = lot
        
        if buyer_id == seller_id:
            await cb.answer("🤨 Ты не можешь купить у самого себя!")
            return

        # 2. Проверяем деньги покупателя
        async with db.execute('SELECT tomatoes FROM users WHERE user_id = ?', (buyer_id,)) as c:
            buyer_tom = (await c.fetchone())[0]
            
        if buyer_tom < price:
            await cb.answer(f"❌ Не хватает помидоров! Нужно {price}", show_alert=True)
            return

        # --- ТРАНЗАКЦИЯ ---
        # Списываем у покупателя
        await db.execute('UPDATE users SET tomatoes = tomatoes - ? WHERE user_id = ?', (price, buyer_id))
        
        # Начисляем продавцу
        # (Можно добавить налог рынка 10% для вывода валюты из игры: int(price * 0.9))
        await db.execute('UPDATE users SET tomatoes = tomatoes + ? WHERE user_id = ?', (price, seller_id))
        
        # Выдаем карту покупателю
        # Проверяем, есть ли уже такая карта у покупателя
        async with db.execute('SELECT count FROM user_cards WHERE user_id = ? AND card_id = ?', (buyer_id, card_id)) as c:
            exists = await c.fetchone()
        
        if exists:
            await db.execute('UPDATE user_cards SET count = count + 1 WHERE user_id = ? AND card_id = ?', (buyer_id, card_id))
        else:
            await db.execute('INSERT INTO user_cards (user_id, card_id, count) VALUES (?, ?, 1)', (buyer_id, card_id))
            
        # Удаляем лот
        await db.execute('DELETE FROM market WHERE lot_id = ?', (lot_id,))
        
        await db.commit()
        
    await cb.answer("✅ Успешно куплено!")
    await cb.message.answer(f"🎉 Ты купил <b>{CARDS[card_id]['name']}</b> за {price} 🍅!", parse_mode="HTML")
    
    # Уведомляем продавца (если бот не в бане)
    try:
        await bot.send_message(seller_id, f"🤑 Твой лот <b>{CARDS[card_id]['name']}</b> купили за {price} 🍅!")
    except: pass

# В секции FSM
    
# Простая пасхалка на текст
@dp.message(F.text.lower().contains("я читер"))
async def easter_egg_1(message: types.Message):
    await message.answer("👀 <b>Я слежу за тобой...</b>\nАдмины уже выехали.", parse_mode="HTML")

@dp.message(F.text.lower().contains("хочу денег"))
async def easter_egg_2(message: types.Message):
    # Даем 1 помидор
    user = await get_user(message.from_user.id)
    await update_stat(message.from_user.id, "tomatoes", user[3] + 1)
    await message.answer("🍅 Держи помидорку, бедняк.")

@dp.message(F.text == "sudo rm -rf /")
async def easter_egg_linux(message: types.Message):
    await message.answer("🤖 <i>Kernel panic... System failure...</i>\n\nШучу. Не ломай меня.", parse_mode="HTML")

# --- БД: ИНИЦИАЛИЗАЦИЯ И МИГРАЦИИ ---
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                milk INTEGER DEFAULT 0,
                tomatoes INTEGER DEFAULT 0,
                
                -- Основные кликер-статы
                click_level INTEGER DEFAULT 1,
                tomato_level INTEGER DEFAULT 1, 
                fertilizer INTEGER DEFAULT 0,
                sosi_count INTEGER DEFAULT 0,
                is_banned INTEGER DEFAULT 0,
                
                -- Улучшения магазина
                luck_level INTEGER DEFAULT 0,
                safety_level INTEGER DEFAULT 0,
                eco_level INTEGER DEFAULT 0,
                casino_level INTEGER DEFAULT 0,
                gmo_level INTEGER DEFAULT 0,
                
                -- Таймеры и прочее
                last_daily_claim REAL DEFAULT 0,
                reg_date REAL DEFAULT 0,
                last_scarecrow REAL DEFAULT 0,
                active_boost TEXT DEFAULT '',
                boost_end REAL DEFAULT 0,
                mandarins INTEGER DEFAULT 0,
                prefix TEXT DEFAULT NULL,
                custom_status TEXT DEFAULT 'Фермер',
                is_admin INTEGER DEFAULT 0,
                last_active REAL DEFAULT 0,

                -- 🎓 АКАДЕМИЯ (НОВЫЕ ПОЛЯ) --
                acad_management INTEGER DEFAULT 0,  -- Доход
                acad_logistics INTEGER DEFAULT 0,   -- Время AFK
                acad_agronomy INTEGER DEFAULT 0,    -- Скидки
                last_acad_collect REAL DEFAULT 0    -- Время сбора
            )
        ''')
        # Таблицы карт, кодов и рынка оставляем без изменений...
        await db.execute('CREATE TABLE IF NOT EXISTS user_cards (user_id INTEGER, card_id TEXT, count INTEGER DEFAULT 0, PRIMARY KEY (user_id, card_id))')
        await db.execute('CREATE TABLE IF NOT EXISTS promo_codes (code TEXT PRIMARY KEY, uses_left INTEGER, reward_type TEXT, reward_amount INTEGER)')
        await db.execute('CREATE TABLE IF NOT EXISTS used_codes (user_id INTEGER, code TEXT, PRIMARY KEY (user_id, code))')
        await db.execute('CREATE TABLE IF NOT EXISTS market (lot_id INTEGER PRIMARY KEY AUTOINCREMENT, seller_id INTEGER, seller_name TEXT, card_id TEXT, price INTEGER)')
        await db.commit()
        # Миграции: Добавляем новые колонки в старую базу, если их нет
        new_columns = [
            ("luck_level", "INTEGER DEFAULT 0"),   # Удача (шанс дропа)
            ("safety_level", "INTEGER DEFAULT 0"), # Крышка (анти-разлив)
            ("eco_level", "INTEGER DEFAULT 0"),    # Насос (дешевле полив)
            ("casino_level", "INTEGER DEFAULT 0"), # Шулер (дешевле казино)
            ("gmo_level", "INTEGER DEFAULT 0"),     # ГМО (кэшбек молока)
            ("last_daily_claim", "REAL DEFAULT 0"),
            ("reg_date", "REAL DEFAULT 0"),
            ("last_scarecrow", "REAL DEFAULT 0"),    # Время последней игры с пугалом
            ("active_boost", "TEXT DEFAULT ''"),     # Тип активного буста (milk_x2, water_free и т.д.)
            ("boost_end", "REAL DEFAULT 0"),          # Время окончания буста
            ("mandarins", "INTEGER DEFAULT 0"),
            ("prefix", "TEXT DEFAULT NULL"),        # Префикс (например [VIP])
            ("custom_status", "TEXT DEFAULT 'Фермер'"), # Статус в профиле
            ("is_admin", "INTEGER DEFAULT 0"),   # 1 - админ, 0 - нет
            ("last_active", "REAL DEFAULT 0"),    # Время последней активности
            ("iq_level", "INTEGER DEFAULT 0"),
            ("iq_level_max_reached", "INTEGER DEFAULT 0"),
            ("last_iq_collect", "REAL DEFAULT 0"),
            ("acad_management", "INTEGER DEFAULT 0"),
            ("acad_logistics", "INTEGER DEFAULT 0"),
            ("acad_agronomy", "INTEGER DEFAULT 0"),
            ("last_acad_collect", "REAL DEFAULT 0"),
            ("is_hidden", "INTEGER DEFAULT 0"),
            ("mutagen", "INTEGER DEFAULT 0"),
            ("tractor_level", "INTEGER DEFAULT 0"),  # <-- НОВОЕ: Уровень авто-сборщика
            ("last_tractor_collect", "REAL DEFAULT 0") # <-- НОВОЕ: Время последнего сбора
        ]
        
        for col, definition in new_columns:
            try:
                await db.execute(f'ALTER TABLE users ADD COLUMN {col} {definition}')
            except:
                pass # Колонка уже есть
        # Для старых пользователей проставим текущее время, если там 0
        current_time = time.time()
        await db.execute(f'UPDATE users SET reg_date = ? WHERE reg_date = 0', (current_time,))
        await db.commit()

async def get_user(user_id):
    # Полный список полей для безопасного доступа
    SELECT_FIELDS = """
        user_id, username, milk, tomatoes, 
        click_level, tomato_level, fertilizer, sosi_count, is_banned,
        luck_level, safety_level, eco_level, casino_level, gmo_level, 
        last_daily_claim, reg_date, last_scarecrow, active_boost, boost_end, 
        mandarins, prefix, custom_status, is_admin, last_active,
        acad_management, acad_logistics, acad_agronomy, last_acad_collect
    """
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row 
        async with db.execute(f'SELECT {SELECT_FIELDS} FROM users WHERE user_id = ?', (user_id,)) as cursor:
            user = await cursor.fetchone()
            if not user:
                await db.execute('INSERT INTO users (user_id, username, reg_date) VALUES (?, ?, ?)',
                                 (user_id, "Newbie", time.time()))
                await db.commit()
                return await get_user(user_id) 
            return user

async def update_username(user_id, name):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('UPDATE users SET username = ? WHERE user_id = ?', (name, user_id))
        await db.commit()

async def update_stat(user_id, column, value):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(f'UPDATE users SET {column} = ? WHERE user_id = ?', (value, user_id))
        await db.commit()

def get_shop_text(user):
    return (
        f"🛒 <b>ЦЕНТР СНАБЖЕНИЯ</b>\n"
        f"{UI_SEP}\n"
        f"💵 <b>Доступный баланс:</b> <code>{format_num(user[3])}</code> 🍅\n\n"
        
        f"<b>📋 КАТАЛОГ ОБОРУДОВАНИЯ</b>\n"
        f"{UI_BULLET} <b>Бицепс:</b> +Молоко за клик\n"
        f"{UI_BULLET} <b>Сорт:</b> x2 Шанс урожая\n"
        f"{UI_BULLET} <b>Удача:</b> +Шанс дропа\n"
        f"{UI_BULLET} <b>Крышка:</b> -Шанс разлива\n"
        f"{UI_BULLET} <b>Насос:</b> -Расход воды\n"
        f"{UI_BULLET} <b>Шулер:</b> -Стоимость слотов\n"
        f"{UI_BULLET} <b>ГМО:</b> +Шанс кэшбека\n"
        f"{UI_SEP}\n"
        f"<i>Выберите улучшение для транзакции:</i>"
    )

# --- КРАСИВЫЙ ДИЗАЙН КЛАВИАТУР ---
def main_keyboard():
    kb = [
        # Основной геймплей всегда под рукой
        [KeyboardButton(text="🥛 Сбор Молока"), KeyboardButton(text="💦 Полить грядку")],
        # Категории
        [KeyboardButton(text="🏙 Город"), KeyboardButton(text="🎡 Развлечения")],
        # Профиль отдельно
        [KeyboardButton(text="👤 Личный Кабинет")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, input_field_placeholder="Главное меню")

def town_keyboard():
    kb = [
        [KeyboardButton(text="💲 Торговец"), KeyboardButton(text="📦 Хранилище")],
        [KeyboardButton(text="🎓 Академия"), KeyboardButton(text="🧬 Лаборатория")], # <--- ДОБАВИЛ ЛАБУ
        [KeyboardButton(text="🏆 Рейтинг"), KeyboardButton(text="📟 Терминал")], # <--- ДОБАВИЛ СЕЗОН
        [KeyboardButton(text="⤾ Назад")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, input_field_placeholder="Район: Город")
    
# ... (Остальные клавиатуры) ...

def fun_keyboard():
    kb = [
        [KeyboardButton(text="🎲 Казино"), KeyboardButton(text="🎁 Ежедневный бонус")],
        [KeyboardButton(text="🥔 Плантация")], # Ивент
        [KeyboardButton(text="⤾ Назад")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, input_field_placeholder="Район: Развлечения")

def upgrades_keyboard(u):
    # Считаем скидку
    lvl_agr = u['acad_agronomy']
    discount = min(0.30, lvl_agr * ACAD_DISCOUNT_PER_LVL) # Макс 30%
    price_factor = 1.0 - discount
    
    # Расчет цен с учетом скидки
    p_click = int(10 * u['click_level'] * price_factor)
    p_tomato = int(50 * u['tomato_level'] * price_factor)
    p_luck = int(30 * (u['luck_level'] + 1) * price_factor)
    p_safe = int(25 * (u['safety_level'] + 1) * price_factor)
    p_eco = int(100 * (u['eco_level'] + 1) * price_factor)
    p_cas = int(40 * (u['casino_level'] + 1) * price_factor)
    p_gmo = int(75 * (u['gmo_level'] + 1) * price_factor)
    p_tractor = int(5000 * (1.6 ** u['tractor_level']) * price_factor)

    # Иконка скидки
    d_text = f" 🔥-{int(discount*100)}%" if discount > 0 else ""

    kb = [
        [InlineKeyboardButton(text=f"💪 Бицепс ({p_click}🍅)", callback_data="buy_click"),
         InlineKeyboardButton(text=f"🧬 Сорт ({p_tomato}🍅)", callback_data="buy_tomato")],
        
        [InlineKeyboardButton(text=f"🍀 Удача ({p_luck}🍅)", callback_data="buy_luck"),
         InlineKeyboardButton(text=f"🛡 Крышка ({p_safe}🍅)", callback_data="buy_safe")],
         
        [InlineKeyboardButton(text=f"📉 Насос ({p_eco}🍅)", callback_data="buy_eco"),
         InlineKeyboardButton(text=f"🃏 Шулер ({p_cas}🍅)", callback_data="buy_cas")],
         
        [InlineKeyboardButton(text=f"{icon} Трактор ({format_num(p_tractor)}🍅)", callback_data=f"buy_tractor_{m}"),
        InlineKeyboardButton(text=f"🧪 ГМО ({p_gmo}🍅)", callback_data="buy_gmo")],
        
        [InlineKeyboardButton(text=f"🔄 Обновить цены{d_text}", callback_data="refresh_upgrades")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def inventory_keyboard(has_fert: int, mandarins: int):
    kb = []
    if has_fert > 0:
        kb.append([InlineKeyboardButton(text=f"🧪 Использовать химию (x{has_fert})", callback_data="use_all_fert_init")])
    
    if mandarins > 0:
        kb.append([InlineKeyboardButton(text=f"🎅 Сезонный торговец({mandarins} кг)", callback_data="santa_shop_open")])
    
    kb.append([InlineKeyboardButton(text="🎴 Коллекция", callback_data="show_cards_inline")])
    kb.append([InlineKeyboardButton(text="⚖️ Биржа Игроков", callback_data="show_market_inline")])
    kb.append([InlineKeyboardButton(text="🔄 Обновить данные", callback_data="refresh_inv")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

# --- ВСПОМОГАТЕЛЬНЫЕ ---
async def delete_later(msg, delay=2):
    await asyncio.sleep(delay)
    try: await msg.delete()
    except: pass

def format_num(num):
    return "{:,}".format(num).replace(",", " ")

def get_progress_bar(value, max_value=10):
    # Визуальная полоска
    percent = min(1.0, value / max_value)
    blocks = int(percent * 10)
    return "▓" * blocks + "░" * (10 - blocks)

@dp.callback_query(F.data == "check_subscription")
async def check_subscription_handler(cb: CallbackQuery):
    # Если код дошел сюда, значит Middleware пропустил юзера (он подписан)
    await cb.message.delete() # Удаляем сообщение с требованием подписки
    await cb.answer("✅ Спасибо за подписку! Приятной игры!")
    
    # Можно сразу отправить приветствие
    await cb.message.answer("🎉 Добро пожаловать на Ферму! Жми кнопки меню.", reply_markup=main_keyboard())

# --- ЛОГИКА ИГРЫ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user = await get_user(message.from_user.id)
    if user[8]: return # Ban

    caption = (
        f"🌾 <b>Молочная ферма v7.5 </b>\n\n"
        f"Привет, {message.from_user.first_name}!\n"
        f"Мы сбалансировали выпадение ресурсов/подарков, добавили описание улучшений,\n"
        f"добавили Плантация: каждые 3 часа нужно разгонять птиц, в награду вы получите случайный бафф на 10 минут.\n"
        f"Телеграм канал: https://t.me/molokofarmoff\n\n"
        f"👇 <b>Начинай работу:</b>"
    )
    
    try:
        photo = FSInputFile(LOGO_PATH)
        await message.answer_photo(photo, caption=caption, reply_markup=main_keyboard(), parse_mode="HTML")
    except:
        await message.answer_photo(DEFAULT_LOGO_URL, caption=caption, reply_markup=main_keyboard(), parse_mode="HTML")

# Вставь это в начало cmd_start
    # --- ЛОГИКА ТРАКТОРА ---
    u = await get_user(message.from_user.id)
    if u['tractor_level'] > 0:
        now = time.time()
        last_run = u['last_tractor_collect']
        if last_run == 0: last_run = now # Первый запуск
        
        diff = now - last_run
        # Лимит 12 часов (43200 сек), чтобы заходили чаще
        work_time = min(diff, 43200) 
        
        if work_time > 60: # Минимум минута
            # Формула: 10 помидоров в минуту * уровень
            income = int((work_time / 60) * 10 * u['tractor_level'])
            
            await update_stat(message.from_user.id, "tomatoes", u['tomatoes'] + income)
            await update_stat(message.from_user.id, "last_tractor_collect", now)
            
            await message.answer(f"🚜 <b>ТРАКТОР ОТЧЕТ:</b>\nПока вас не было, собрано: <b>{format_num(income)}</b> 🍅", parse_mode="HTML")
        else:
            # Просто обновляем таймер, чтобы не абузили
            await update_stat(message.from_user.id, "last_tractor_collect", now)
    else:
        # Если трактора нет, просто ставим таймер на сейчас
        await update_stat(message.from_user.id, "last_tractor_collect", time.time())

# --- ДОЙКА (С УЧЕТОМ НОВЫХ СТАТОВ) ---
@dp.message(F.text.in_({"🥛 Сбор Молока"}))
async def milk_handler(message: types.Message):
    user_id = message.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute('SELECT * FROM users WHERE user_id = ?', (user_id,)) as c:
            user = await c.fetchone()
        async with db.execute('SELECT active_boost, boost_end FROM users WHERE user_id = ?', (user_id,)) as c:
            b_row = await c.fetchone()
            active_boost = b_row[0] if b_row else ""
            boost_end = b_row[1] if b_row else 0

    is_boosted_milk = (time.time() < boost_end and active_boost == "milk_x2")
    is_boosted_luck = (time.time() < boost_end and active_boost == "luck_max")

    base_milk = MILK_PER_CLICK * user['click_level']
    if is_boosted_milk: base_milk *= 2

    # Шансы
    base_chance = 0.03 
    luck_bonus = user['luck_level'] * 0.005
    drop_chance = 1.0 if is_boosted_luck else (base_chance + luck_bonus)
    spill_chance = max(0, 0.05 - (user['safety_level'] * 0.01))

    rand = random.random()
    boost_icon = "⚡x2 " if is_boosted_milk else ""
    
    # Логика с начислением и текстом
    if rand < spill_chance:
        lost = max(1, int(user['milk'] * 0.1))
        # Сразу считаем новый итог
        new_total = max(0, user['milk'] - lost)
        await update_stat(user_id, "milk", new_total)
        
        text = f"⚠️ Разлито {lost} Л. Баланс: {format_num(new_total)} Л"
    
    elif rand > (1 - drop_chance):
        await update_stat(user_id, "fertilizer", user['fertilizer'] + 1)
        new_total = user['milk'] + base_milk
        await update_stat(user_id, "milk", new_total)
        
        text = f"🥛 {boost_icon}+{base_milk} Л + 🧪 Химия!"
    
    else:
        new_total = user['milk'] + base_milk
        await update_stat(user_id, "milk", new_total)
        
        text = f"🥛 {boost_icon}+{base_milk}"

    # Используем функцию "чистого чата"
    await message.answer(text, reply_markup=main_keyboard(), parse_mode="HTML")

# --- ПОЛИВ (С УЧЕТОМ ЭКОНОМИИ И ГМО) ---
@dp.message(F.text.in_({"💦 Полить грядку"}))
async def plant_handler(message: types.Message):
    # УБРАЛ удаление сообщения игрока
    # try: await message.delete()
    # except: pass
    
    user_id = message.from_user.id
    user = await get_user(user_id)
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT active_boost, boost_end FROM users WHERE user_id = ?', (user_id,)) as c:
            b_row = await c.fetchone()
            active_boost = b_row[0] if b_row else ""
            boost_end = b_row[1] if b_row else 0

    is_boosted_tom = (time.time() < boost_end and active_boost == "tomato_x2")
    is_free_water = (time.time() < boost_end and active_boost == "water_free")

    cost = 0 if is_free_water else int(max(1, BASE_PLANT_COST - (user[11] * 0.5)))
    
    if user[2] >= cost:
        crit_chance = user[5] * 0.05
        base_yield = 2 if random.random() < crit_chance else 1
        if is_boosted_tom: base_yield *= 2
        
        refund_text = ""
        real_cost = cost
        if not is_free_water and cost > 0:
            gmo_chance = user[13] * 0.05
            if random.random() < gmo_chance:
                refund = int(cost * 0.5)
                real_cost = cost - refund
                refund_text = f"\n♻️ <b>ГМО!</b> Возврат {refund} л."

        await update_stat(user_id, "milk", user[2] - real_cost)
        await update_stat(user_id, "tomatoes", user[3] + base_yield)
        
        boost_msg = "⚡️x2 " if is_boosted_tom else ""
        free_msg = "(Бесплатно!)" if is_free_water else f" (-{real_cost} л.)"
        
        text = f"🍅 Получено +{base_yield} ед.{free_msg}{refund_text}"
    else:
        text = f"💧 Недостаточно воды. Требуется {cost} Л."
    
    # ОТПРАВЛЯЕМ И НЕ УДАЛЯЕМ
    await message.answer(text, reply_markup=main_keyboard(), parse_mode="HTML")

# ... (код расчета урожая и обновления БД выше) ...

    # --- НОВОГОДНИЙ ДРОП (БАЛАНС: 20% ШАНС, 1-3 КГ) ---
    if random.random() < 0.20: # Шанс снижен до 20%
        # Теперь выпадает меньше: 1-3 кг
        mandarins_found = random.randint(1, 3)
        
        u_fresh = await get_user(user_id) 
        current_mandarins = u_fresh['mandarins']
        
        # Фикс багов с большими числами
        if current_mandarins > 1000000000: current_mandarins = 0
            
        new_total = int(current_mandarins + mandarins_found)
        await update_stat(message.from_user.id, "mandarins", new_total)
        
        # Красивое сообщение
        drop_text = (
            f"🍊 Ты откопал ящик мандаринов: <b>{mandarins_found} кг!</b>\n"
            f"📦 Теперь на складе: <b>{format_num(new_total)} кг</b>"
        )
        await message.answer(drop_text, parse_mode="HTML")


# --- СИСТЕМА ТОПОВ ---

# Форматирование времени (из секунд в дни/часы)
def format_time_spent(seconds_played):
    days = int(seconds_played // 86400)
    hours = int((seconds_played % 86400) // 3600)
    if days > 0:
        return f"{days} д. {hours} ч."
    return f"{hours} ч. {int((seconds_played % 3600) // 60)} мин."

# Генерация текста и кнопок
async def get_leaderboard_data(top_type="tomatoes"):
    async with aiosqlite.connect(DB_NAME) as db:
        # Добавляем фильтр WHERE is_hidden = 0
        if top_type == "tomatoes":
            query = 'SELECT user_id, username, tomatoes FROM users WHERE is_hidden = 0 ORDER BY tomatoes DESC LIMIT 10'
            title = "🍅 ТОП МАГНАТОВ (Помидоры)"
            prev, nxt = "time", "milk"
        elif top_type == "milk":
            query = 'SELECT user_id, username, milk FROM users WHERE is_hidden = 0 ORDER BY milk DESC LIMIT 10'
            title = "🥛 ТОП ДОЯРОК (Молоко)"
            prev, nxt = "tomatoes", "time"
        elif top_type == "time":
            query = 'SELECT user_id, username, reg_date FROM users WHERE is_hidden = 0 ORDER BY reg_date ASC LIMIT 10'
            title = "⏳ ТОП ОЛДОВ (В игре)"
            prev, nxt = "milk", "tomatoes"

        async with db.execute(query) as c:
            res = await c.fetchall()

    # 1. Формируем ТЕКСТОВЫЙ список (читаемый)
    text = f"🏆 <b>{title}</b>\n{UI_SEP}\n"
    
    if not res:
        text += "<i>Список пуст...</i>"
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Обновить", callback_data=f"top_{top_type}")]])
        return text, kb

    current_time = time.time()
    
    # Список кнопок-ссылок на профили
    profile_buttons = []
    
    for i, row in enumerate(res):
        uid = row[0]
        name = row[1]
        value = row[2]
        
        # Обрезаем слишком длинные ники для ТЕКСТА (чтобы не ломали верстку), но оставляем читаемыми
        display_name = name[:20] + "..." if len(name) > 20 else name
        
        # Форматирование значения
        if top_type == "time":
            val_str = format_time_spent(current_time - value)
        else:
            val_str = format_num(value)
            
        medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else f"{i+1}."
        
        # Строка в текстовом списке
        text += f"{medal} <b>{display_name}</b> — {val_str}\n"
        
        # Добавляем кнопку с номером места (1 👤, 2 👤 и т.д.)
        # Это компактно и удобно нажимать
        profile_buttons.append(InlineKeyboardButton(text=f"{i+1} 👤", callback_data=f"view_profile_{uid}"))

    text += f"\n<i>Нажми на кнопку с номером места, чтобы открыть профиль игрока:</i>"

    # 2. Собираем КЛАВИАТУРУ
    kb_rows = []
    
    # Разбиваем кнопки профилей на ряды по 5 штук (чтобы было красиво)
    # [1 👤] [2 👤] [3 👤] [4 👤] [5 👤]
    chunk_size = 5
    for i in range(0, len(profile_buttons), chunk_size):
        kb_rows.append(profile_buttons[i:i + chunk_size])

    # Добавляем навигацию в самый низ
    kb_rows.append([
        InlineKeyboardButton(text="⬅️", callback_data=f"top_{prev}"),
        InlineKeyboardButton(text="🔄 Обновить", callback_data=f"top_{top_type}"),
        InlineKeyboardButton(text="➡️", callback_data=f"top_{nxt}")
    ])
    
    return text, InlineKeyboardMarkup(inline_keyboard=kb_rows)

# --- КАЗИНО (С УЧЕТОМ ШУЛЕРА) ---
@dp.message(F.text == "🎲 Казино")
async def casino_handler(message: types.Message):
    user = await get_user(message.from_user.id)
    # Stats: 12-CasinoLvl
    
    # Ставка: База 10 - 1 за уровень Шулера (Мин 2)
    bet = max(2, BASE_CASINO_COST - user[12])
    
    if user[3] < bet:
        msg = await message.answer(f"❌ Ставка {bet} помидоров. У тебя мало!")
        asyncio.create_task(delete_later(msg))
        return

    await update_stat(message.from_user.id, "tomatoes", user[3] - bet)
    dice_msg = await message.answer_dice(emoji="🎰")
    await asyncio.sleep(2)
    
    # Логика слота (значение dice.value от 1 до 64)
    val = dice_msg.dice.value
    win = 0
    
    # 1, 22, 43, 64 - это комбинации (примерно)
    # Упростим: Value в dice 🎰: 
    # 1=bar, 22=grapes, 43=lemon, 64=seven (Jackpot)
    
    if val == 64: # Три семерки
        win = bet * 10
        res = f"🤑 <b>ДЖЕКПОТ!!!</b> (+{win})"
    elif val == 43: # Три лимона
        win = bet * 3
        res = f"🍋 <b>Сочно!</b> (+{win})"
    elif val == 22: # Виноград
        win = bet * 2
        res = f"🍇 <b>Вкусно!</b> (+{win})"
    elif val == 1: # Бар
        win = bet
        res = f"😐 <b>Возврат.</b> (+{win})"
    else:
        res = f"📉 <b>Мимо.</b> (-{bet})"
    
    if win > 0:
        await update_stat(message.from_user.id, "tomatoes", (user[3] - bet) + win)
    
    await message.answer(res, parse_mode="HTML")

# --- 💲 ТОРГОВЕЦ (МАГАЗИН) ---
@dp.message(F.text == "💲 Торговец")
async def shop_menu(message: types.Message):
    user = await get_user(message.from_user.id)
    # Используем твою функцию генерации текста
    text = get_shop_text(user)
    # info_mode=False (Режим покупки)
    await message.answer(text, reply_markup=upgrades_keyboard(user, info_mode=False), parse_mode="HTML")

@dp.callback_query(F.data.startswith("buy_"))
async def buy_upgrade(cb: CallbackQuery):
    type_up = cb.data.split("_")[1] # click, tomato, luck, safe, eco, cas, gmo
    user = await get_user(cb.from_user.id)
    tom = user[3]
    
    lvl_agr = user['acad_agronomy']
    discount = min(0.30, lvl_agr * ACAD_DISCOUNT_PER_LVL)
    price_factor = 1.0 - discount
    # Определение цены и колонки
    cost = 0
    col = ""
    new_lvl = 0
    
    if type_up == "click":
        base_cost = 10 * user['click_level']
        col = "click_level"
        new_lvl = user[4] + 1
    elif type_up == "tomato":
        cost = 50 * user[5]
        col = "tomato_level"
        new_lvl = user[5] + 1
    elif type_up == "luck":
        cost = 30 * (user[9] + 1)
        col = "luck_level"
        new_lvl = user[9] + 1
    elif type_up == "safe":
        cost = 25 * (user[10] + 1)
        col = "safety_level"
        new_lvl = user[10] + 1
    elif type_up == "eco":
        cost = 100 * (user[11] + 1)
        col = "eco_level"
        new_lvl = user[11] + 1
    elif type_up == "cas":
        cost = 40 * (user[12] + 1)
        col = "casino_level"
        new_lvl = user[12] + 1
    elif type_up == "gmo":
        cost = 75 * (user[13] + 1)
        col = "gmo_level"
        new_lvl = user[13] + 1
    elif type_up == "tractor":
        raw_cost = 5000 * (1.6 ** user['tractor_level'])
        col = "tractor_level"; new_lvl = user['tractor_level'] + 1

    if tom >= cost:
        await update_stat(cb.from_user.id, "tomatoes", tom - cost)
        await update_stat(cb.from_user.id, col, new_lvl)
        await cb.answer(f"✅ Улучшение '{type_up.upper()}' куплено!")
        
        cost = int(base_cost * price_factor) # Финальная цена
        
        # Обновляем меню
        u = await get_user(cb.from_user.id)
        try: await cb.message.edit_text(
            # Редактируем сообщение, используя тот же красивый текст
                get_shop_text(u), 
                reply_markup=upgrades_keyboard(u), 
                parse_mode="HTML"
        )
        except: pass
    else:
        await cb.answer(f"❌ Нужно {cost} помидоров!", show_alert=True)

@dp.callback_query(F.data == "refresh_upgrades")
async def refresh_shop(cb: CallbackQuery):
    u = await get_user(cb.from_user.id)
    try: 
        await cb.message.edit_text(
            get_shop_text(u), 
            reply_markup=upgrades_keyboard(u), 
            parse_mode="HTML"
        )
    except: pass
    await cb.answer()

# --- ПРОФИЛЬ (ОБНОВЛЕННЫЙ) ---
@dp.message(F.text == "👤 Личный Кабинет") 
@dp.message(F.text == "👤 Мой Профиль")   
async def profile_new(m: types.Message):
    user = await get_user(m.from_user.id)
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT prefix, custom_status FROM users WHERE user_id = ?', (m.from_user.id,)) as c:
            meta = await c.fetchone()
            prefix = meta[0]
            status = meta[1]

    display_name = m.from_user.full_name
    if prefix:
        display_name = f"[{prefix}] {display_name}"

    text = (
        f"<b>👤 ПАНЕЛЬ УПРАВЛЕНИЯ</b>\n"
        f"{UI_SEP}\n"
        f"💳 <b>ID:</b> <code>{user[0]}</code>\n"
        f"🏷 <b>Имя:</b> {display_name}\n"
        f"🔰 <b>Статус:</b> {status}\n\n"
        
        f"<b>📊 АКТИВЫ И РЕСУРСЫ</b>\n"
        f"{UI_BULLET} Молоко: <code>{format_num(user[2])}</code> Л\n"
        f"{UI_BULLET} Помидоры: <code>{format_num(user[3])}</code> шт\n"
        f"{UI_BULLET} Мандарины: <code>{format_num(user['mandarins'])}</code> кг\n"
        f"{UI_BULLET} Реагенты: <code>{format_num(user['fertilizer'])}</code> ед\n\n"
        
        f"<b>⚙️ ТЕХНОЛОГИЧЕСКИЙ УРОВЕНЬ</b>\n"
        f"{UI_SUB_BULLET} Сила клика: <code>Ур. {user[4]}</code>\n"
        f"{UI_SUB_BULLET} Агрономия: <code>Ур. {user[5]}</code>\n"
        f"{UI_SUB_BULLET} Удача: <code>{user[9]}</code> {get_progress_bar(user[9], 20)}\n"
        f"{UI_SUB_BULLET} Защита: <code>{user[10]}</code> {get_progress_bar(user[10], 5)}\n"
        f"{UI_SUB_BULLET} Насос: <code>{user[11]}</code> {get_progress_bar(user[11], 8)}\n"
        f"{UI_SUB_BULLET} Риски: <code>{user[12]}</code> {get_progress_bar(user[12], 10)}\n"
        f"{UI_SUB_BULLET} ГМО-Лаб: <code>{user[13]}</code> {get_progress_bar(user[13], 15)}"
    )
    await m.answer(text, parse_mode="HTML")

# --- СКЛАД ---
# Хендлер для просмотра списка карт (без фото, чтобы не спамить)
@dp.message(F.text == "📦 Хранилище")
@dp.message(F.text == "🎒 Склад")
@dp.callback_query(F.data == "refresh_inv")
async def show_inventory(message_or_call: types.Union[Message, CallbackQuery]):
    user_id = message_or_call.from_user.id
    u = await get_user(user_id)
    
    fertilizer_count = u['fertilizer']
    mandarin_count = u['mandarins']
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT card_id, count FROM user_cards WHERE user_id = ? AND count > 0', (user_id,)) as c:
            my_cards = await c.fetchall()
            
    card_list_text = ""
    if my_cards:
        card_lines = []
        for c_id, count in my_cards:
             card_name = CARDS.get(c_id, {'name': '???'})['name']
             card_lines.append(f"  └ <b>{card_name}</b> — {count} шт.")
        card_list_text = "\n" + "\n".join(card_lines)
    else:
        card_list_text = "\n  └ <i>Активы отсутствуют</i>"
        
    text = (
        f"📦 <b>СОСТОЯНИЕ СКЛАДА</b>\n"
        f"{UI_SEP}\n"
        f"🧪 <b>Химикаты:</b> <code>{fertilizer_count}</code> ед.\n"
        f"🍊 <b>Сезонная валюта:</b> <code>{format_num(mandarin_count)}</code> кг\n\n"
        f"📂 <b>КОЛЛЕКЦИОННЫЕ АКТИВЫ:</b>"
        f"{card_list_text}\n"
        f"{UI_SEP}"
    )
    
    kb = inventory_keyboard(fertilizer_count, mandarin_count)
    
    if isinstance(message_or_call, CallbackQuery):
        try:
            await message_or_call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
            await message_or_call.answer()
        except:
            await message_or_call.answer("✅ Данные актуальны")
    else:
        await message_or_call.answer(text, reply_markup=kb, parse_mode="HTML")

# Хендлер инициации использования химии
@dp.callback_query(F.data == "use_all_fert_init")
async def use_all_fert_init(cb: CallbackQuery):
    u = await get_user(cb.from_user.id)
    fert_count = u[6]
    
    if fert_count == 0:
        await cb.answer("❌ У тебя нет химии.", show_alert=True)
        return
    
    total_gain = fert_count * FERT_EFFECT
    
    text = (
        f"⚠️ <b>ПОДТВЕРДИ ДЕЙСТВИЕ</b>\n\n"
        f"Ты собираешься использовать <b>{fert_count} шт.</b> химии.\n"
        f"Это принесет: <b>{total_gain}</b> 🍅"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ Подтвердить ({total_gain} 🍅)", callback_data="use_all_fert_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="use_all_fert_cancel")]
    ])
    
    await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await cb.answer()

# Хендлер отмены использования химии
@dp.callback_query(F.data == "use_all_fert_cancel")
async def use_all_fert_cancel(cb: CallbackQuery):
    # Просто возвращаемся в меню склада
    await cb.answer("Отменено.")
    await show_inventory(cb)

# Хендлер подтверждения использования химии
@dp.callback_query(F.data == "use_all_fert_confirm")
async def use_all_fert_confirm(cb: CallbackQuery):
    user_id = cb.from_user.id
    u = await get_user(user_id)
    fert_count = u[6]
    
    if fert_count == 0:
        await cb.answer("❌ У тебя нет химии.", show_alert=True)
        await show_inventory(cb)
        return
        
    total_gain = fert_count * FERT_EFFECT
    
    # 1. Начисляем помидоры и списываем химию
    await update_stat(user_id, "tomatoes", u[3] + total_gain)
    await update_stat(user_id, "fertilizer", 0)
    
    await cb.answer(f"✅ Использовано {fert_count} шт. (+{total_gain} 🍅)", show_alert=True)
    
    # Редактируем сообщение с результатом и возвращаемся в Склад
    result_text = f"🎉 <b>ВСЯ ХИМИЯ ИСПОЛЬЗОВАНА!</b>\n\n" \
                  f"Конвертировано <b>{fert_count} шт.</b> химии в <b>{total_gain}</b> 🍅."
                  
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⤾ На склад", callback_data="refresh_inv")]
    ])
    
    try:
        await cb.message.edit_text(result_text, reply_markup=kb, parse_mode="HTML")
    except:
        await cb.message.answer(result_text, reply_markup=kb, parse_mode="HTML")
        
# Хендлеры для встроенных кнопок склада (чтобы они работали)
@dp.callback_query(F.data == "show_cards_inline")
async def show_cards_list_inline(cb: CallbackQuery):
    # Здесь вызывается ваш старый хендлер show_cards_list
    await show_cards_list(cb.message)
    await cb.answer()

@dp.callback_query(F.data == "show_market_inline")
async def show_market_inline(cb: CallbackQuery):
    # Используем существующий хендлер рынка
    await show_market_page(cb, page=0)
    await cb.answer()

@dp.callback_query(F.data == "delete_msg")
async def delete_msg_handler(cb: CallbackQuery):
    await cb.message.delete()

# --- АДМИН И ПРОЧЕЕ (без изменений) ---
@dp.message(F.text == "🏆 Рейтинг")
async def top_users_handler(m: Message):
    # По умолчанию открываем топ по помидорам
    text, kb = await get_leaderboard_data("tomatoes")
    await m.answer(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("top_"))
async def top_navigation(cb: CallbackQuery):
    # Получаем тип топа из data (например, top_milk -> milk)
    top_type = cb.data.split("_")[1]
    
    text, kb = await get_leaderboard_data(top_type)
    
    # Редактируем сообщение (чтобы не спамить новыми)
    # Используем try-except, чтобы не было ошибки если текст не изменился
    try:
        await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except:
        pass
    await cb.answer()

@dp.message(F.text == "📟 Терминал")
async def code_start(m: Message, state: FSMContext):
    await m.answer("Введи код:", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(GameStates.waiting_for_code)

@dp.message(StateFilter(GameStates.waiting_for_code))
async def code_proc(m: Message, state: FSMContext):
    code_input = m.text.strip() # Убираем пробелы
    user_id = m.from_user.id
    
    # Секретный старый код (пасхалка)
    if code_input == "sosi":
        u = await get_user(user_id)
        if u[7] < 5:
            await update_stat(user_id, "milk", u[2] + 10)
            await update_stat(user_id, "sosi_count", u[7] + 1)
            await m.answer("✅ +10 молока (Пасхалка)", reply_markup=main_keyboard())
        else: 
            await m.answer("Лимит пасхалки исчерпан.", reply_markup=main_keyboard())
        await state.clear()
        return

    # --- ПРОВЕРКА ПРОМОКОДОВ ИЗ БД ---
    async with aiosqlite.connect(DB_NAME) as db:
        # 1. Ищем код в базе
        async with db.execute('SELECT uses_left, reward_type, reward_amount FROM promo_codes WHERE code = ?', (code_input,)) as c:
            promo = await c.fetchone()
            
        if not promo:
            await m.answer("❌ Неверный код или срок действия истек.", reply_markup=main_keyboard())
            await state.clear()
            return
            
        uses_left, res_type, amount = promo
        
        # 2. Проверяем, не закончились ли использования
        if uses_left == 0:
            await m.answer("❌ Этот код уже активирован максимальное число раз!", reply_markup=main_keyboard())
            await state.clear()
            return
            
        # 3. Проверяем, вводил ли игрок этот код ранее
        async with db.execute('SELECT 1 FROM used_codes WHERE user_id = ? AND code = ?', (user_id, code_input)) as c:
            is_used = await c.fetchone()
            
        if is_used:
            await m.answer("🤨 Ты уже активировал этот код!", reply_markup=main_keyboard())
            await state.clear()
            return
            
        # --- ВСЕ ОК, ВЫДАЕМ НАГРАДУ ---
        
        # Начисляем ресурс
        await db.execute(f'UPDATE users SET {res_type} = {res_type} + ? WHERE user_id = ?', (amount, user_id))
        
        # Записываем, что игрок использовал код
        await db.execute('INSERT INTO used_codes VALUES (?, ?)', (user_id, code_input))
        
        # Отнимаем использование (если не бесконечный)
        if uses_left > 0:
            await db.execute('UPDATE promo_codes SET uses_left = uses_left - 1 WHERE code = ?', (code_input,))
            
        await db.commit()

        # Красивый вывод
        res_names = {"milk": "молока", "tomatoes": "помидоров", "mandarins": "мандаринов", "fertilizer": "химии"}
        res_name = res_names.get(res_type, res_type)
        
        await m.answer(f"🎉 <b>Код активирован!</b>\nПолучено: +{amount} {res_name}", reply_markup=main_keyboard(), parse_mode="HTML")
        await state.clear()
# --- ХЕНДЛЕРЫ РАССЫЛКИ ---

# --- ЕЖЕДНЕВНЫЕ НАГРАДЫ ---

@dp.message(F.text.in_({"🎁 Ежедневный бонус"}))
async def daily_reward_menu(message: types.Message):
    user = await get_user(message.from_user.id)
    # user[14] - это last_daily_claim (так как мы добавили её последней в миграции)
    # Но надежнее запросить конкретно, если структура менялась, но пока возьмем по индексу или запросом
    
    # Чтобы не путаться с индексами, сделаем отдельный селект для времени
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT last_daily_claim FROM users WHERE user_id = ?', (message.from_user.id,)) as c:
            res = await c.fetchone()
            last_claim = res[0] if res else 0

    now = time.time()
    elapsed = now - last_claim

    if elapsed < DAILY_COOLDOWN:
        # Еще рано
        wait_time = DAILY_COOLDOWN - elapsed
        hours = int(wait_time // 3600)
        minutes = int((wait_time % 3600) // 60)
        await message.answer(f"⏳ <b>Сундук закрыт на замок!</b>\nПриходи через {hours} ч. {minutes} мин.", parse_mode="HTML")
        return

    # Если можно забрать - показываем ЗАКРЫТЫЙ сундук
    caption = "🎁 <b>Ежедневный сундук</b>\nВнутри может быть молоко, помидоры или джекпот!\n\n👇 Жми кнопку, чтобы открыть:"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 Открыть сундук", callback_data="open_daily_chest")]
    ])

    try:
        # Пытаемся отправить локальный файл
        photo = FSInputFile(CHEST_CLOSE_PATH)
        await message.answer_photo(photo, caption=caption, reply_markup=kb, parse_mode="HTML")
    except:
        # Если файла нет - шлем ссылку
        await message.answer_photo(URL_CHEST_CLOSE, caption=caption, reply_markup=kb, parse_mode="HTML")


@dp.callback_query(F.data == "open_daily_chest")
async def open_chest_handler(cb: CallbackQuery):
    user_id = cb.from_user.id
    
    # Снова проверяем время (защита от быстрых кликов/багов)
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT last_daily_claim FROM users WHERE user_id = ?', (user_id,)) as c:
            res = await c.fetchone()
            last_claim = res[0] if res else 0

    if time.time() - last_claim < DAILY_COOLDOWN:
        await cb.answer("❌ Ты уже открыл сундук сегодня!", show_alert=True)
        await cb.message.delete()
        return

    # --- ГЕНЕРАЦИЯ НАГРАДЫ ---
    
    # 1. Проверка на ДЖЕКПОТ (1 к 100 000)
    jackpot_roll = random.randint(1, JACKPOT_CHANCE)
    
    reward_text = ""
    is_jackpot = False
    
    if jackpot_roll == 777: # Счастливое число
        is_jackpot = True
        prize_tomatoes = 1000000 # Миллион помидоров
        
        # Начисляем
        user = await get_user(user_id)
        await update_stat(user_id, "tomatoes", user[3] + prize_tomatoes)
        
        reward_text = (
            f"😱 <b>ДЖЕКПОТ!!! НЕВЕРОЯТНО!!!</b> 😱\n"
            f"ТЫ ВЫБИЛ 1 К {JACKPOT_CHANCE}!\n\n"
            f"💰 <b>Твой приз:</b> {format_num(prize_tomatoes)} ПОМИДОРОВ!"
        )
    else:
        # Обычный дроп (рандомизация)
        # Шансы: 50% Молоко, 40% Помидоры, 10% Химия
        type_roll = random.random()
        user = await get_user(user_id)
        
        if type_roll < 0.5:
            # Молоко (от 100 до 500)
            amount = random.randint(100, 500)
            await update_stat(user_id, "milk", user[2] + amount)
            reward_text = f"🥛 Внутри оказалось <b>{amount} л. молока</b>!"
            
        elif type_roll < 0.95: # Было 0.9, теперь 0.95 (шанс на химию остался 0.05)
            # Помидоры (от 50 до 200)
            amount = random.randint(50, 200)
            await update_stat(user_id, "tomatoes", user[3] + amount)
            reward_text = f"🍅 Внутри оказалось <b>{amount} помидоров</b>!"
            
        else:
            # Химия (Строго 1 шт, чтобы ценили!)
            amount = 1 
            await update_stat(user_id, "fertilizer", user[6] + amount)
            reward_text = f"🧪 Большая редкость! Ты нашел <b>{amount} шт. химии</b>!"

    # Записываем время получения
    await update_stat(user_id, "last_daily_claim", time.time())

    # --- ВИЗУАЛИЗАЦИЯ (ОТКРЫТЫЙ СУНДУК) ---
    
    # Удаляем старое сообщение с кнопкой
    try: await cb.message.delete()
    except: pass
    
    final_caption = f"🔓 <b>Сундук открыт!</b>\n\n{reward_text}\n\n<i>Приходи завтра за новой наградой!</i>"
    
    try:
        photo = FSInputFile(CHEST_OPEN_PATH)
        await cb.message.answer_photo(photo, caption=final_caption, parse_mode="HTML")
    except:
        await cb.message.answer_photo(URL_CHEST_OPEN, caption=final_caption, parse_mode="HTML")
        
    await cb.answer()

@dp.message(Command("broadcast"))
async def start_broadcast(message: types.Message, state: FSMContext):
    # Проверка на админа
    if not message.from_user.username or message.from_user.username.lower() not in ADMINS:
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel")]
    ])
    
    await message.answer(
        "📢 <b>Режим рассылки (Шаг 1/2)</b>\n"
        "Напиши текст сообщения, которое получат все игроки. (Макс. 4096 символов)", 
        reply_markup=kb,
        parse_mode="HTML"
    )
    await state.set_state(BroadcastStates.waiting_for_broadcast_text)

@dp.message(StateFilter(BroadcastStates.waiting_for_broadcast_text))
async def process_broadcast_text(message: types.Message, state: FSMContext):
    text_to_send = message.text
    
    # Защита от слишком длинного сообщения
    if len(text_to_send) > 4096:
        await message.answer("❌ Слишком длинное сообщение (макс. 4096 символов).")
        return
        
    await state.update_data(broadcast_text=text_to_send)
    
    # --- ШАГ ПОДТВЕРЖДЕНИЯ ---
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить и отправить", callback_data="broadcast_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel")]
    ])
    
    confirm_text = (
        "⚠️ <b>ПОДТВЕРЖДЕНИЕ РАССЫЛКИ (Шаг 2/2)</b>\n\n"
        "<b>ПРЕДПРОСМОТР:</b>\n"
        "➖➖➖➖➖➖➖➖\n"
        f"🔔 <b>ОБЪЯВЛЕНИЕ</b>\n\n{text_to_send}\n"
        "➖➖➖➖➖➖➖➖\n\n"
        "Ты уверен, что хочешь отправить это ВСЕМ игрокам? Это необратимо."
    )
    
    await message.answer(confirm_text, reply_markup=kb, parse_mode="HTML")
    await state.set_state(BroadcastStates.waiting_for_broadcast_confirm)

    # --- ИВЕНТ ПУГАЛО ---

# Покупка лота
@dp.callback_query(F.data.startswith("buy_lot_"))
# ... (Код без изменений) ...

# --- ИВЕНТ ПУГАЛО / ГРИНЧ ---

# Вспомогательная функция для безопасной загрузки медиа (которую мы добавили ранее)
def get_grinch_media_safe(frame_index: int, caption: str):
    """Пытается загрузить локальный файл, при ошибке использует URL-заглушку."""
    
    path = GRINCH_FRAMES[frame_index]
    url = GRINCH_URLS[frame_index]
    
    media_source = url
    # Пробуем локальный файл
    if os.path.exists(path):
        media_source = FSInputFile(path)
        
    return InputMediaPhoto(media=media_source, caption=caption, parse_mode="HTML")

# Вспомогательная функция для безопасной загрузки медиа (для Пугала)
def get_scarecrow_media_safe(is_good: bool, caption: str):
    """Пытается загрузить локальный файл Пугала, при ошибке использует URL-заглушку."""
    
    if is_good:
        path = SCARECROW_GOOD_PATH
        url = URL_SCARECROW_GOOD
    else:
        path = SCARECROW_BAD_PATH
        url = URL_SCARECROW_BAD
    
    media_source = url
    if os.path.exists(path):
        media_source = FSInputFile(path)
        
    return InputMediaPhoto(media=media_source, caption=caption, parse_mode="HTML")


@dp.message(F.text == "🥔 Плантация") # Оставляем старое название кнопки
async def scarecrow_event_menu(message: types.Message):
    user_id = message.from_user.id
    now = time.time()
    
    # 1. Проверка кулдауна
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT last_scarecrow FROM users WHERE user_id = ?', (user_id,)) as c:
            last = (await c.fetchone())[0]

    wait_time = SCARECROW_COOLDOWN - (now - last)
    
    if wait_time > 0:
        hours = int(wait_time // 3600)
        minutes = int((wait_time % 3600) // 60)
        
        await message.answer(
            f"⏳ Пугало придет в себя через {hours} ч. {minutes} мин.!", 
            reply_markup=fun_keyboard()
        )
        return

    # 2. Если можно играть - отправляем первый кадр (Пугало BAD) с кнопкой
    
    caption = (
        "🌾 <b>Пугало в беде!</b>\n"
        "Вороны съедают весь урожай. Прогони их, чтобы Пугало дало тебе награду!"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🐦 Прогнать ворон", callback_data="scarecrow_kick")]
    ])
    
    try:
        media = get_scarecrow_media_safe(False, caption) # False для плохого пугала
        await message.answer_photo(media.media, caption=media.caption, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        print(f"Ошибка отправки первого кадра Пугала: {e}")
        await message.answer(caption, reply_markup=kb, parse_mode="HTML")


@dp.callback_query(F.data == "scarecrow_kick")
async def scarecrow_handler(cb: CallbackQuery):
    user_id = cb.from_user.id
    now = time.time()
    
    # 1. Проверка кулдауна (на случай миссклика)
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT last_scarecrow FROM users WHERE user_id = ?', (user_id,)) as c:
            last = (await c.fetchone())[0]
            
    if now - last < SCARECROW_COOLDOWN:
        await cb.answer("❌ Уже слишком поздно или рано! Жди!", show_alert=True)
        return

    # 2. Логика награды (ТОЛЬКО БУСТ)
    
    boosts = ["milk_x2", "tomato_x2", "water_free", "luck_max"]
    chosen_boost = random.choices(boosts, weights=[40, 30, 20, 10], k=1)[0]
    boost_names = {
        "milk_x2": "🥛 Молочный поток (x2 молоко)", 
        "tomato_x2": "🍅 Гига-Томат (x2 урожай)",
        "water_free": "🌊 Дождь (Бесплатный полив)", 
        "luck_max": "🍀 Клевер (Макс. шанс дропа)"
    }
    
    # Запись в БД
    end_time = now + BOOST_DURATION # BOOST_DURATION = 600 сек (10 мин)
    async with aiosqlite.connect(DB_NAME) as db:
        # Обновляем таймеры ивента
        await db.execute(
            'UPDATE users SET last_scarecrow = ?, active_boost = ?, boost_end = ? WHERE user_id = ?', 
            (now, chosen_boost, end_time, user_id)
        )
        await db.commit()

    # --- ЗАПУСК АНИМАЦИИ (2 КАДРА) ---
    
    await cb.answer("🎉 Вороны прогнаны!") 
    
    # КАДР 1: Промежуточный (Просто сообщение, пока картинка не поменялась)
    await cb.message.edit_caption(caption="💨 Вороны улетают...")
    await asyncio.sleep(0.5) 

    # КАДР 2: Финал (Пугало GOOD + Награды)
    final_caption = (
        f"✅ <b>Пугало довольно!</b>\n"
        f"Урожай спасен! За это ты получаешь:\n\n"
        f"⚡️ <b>Активирован буст:</b> {boost_names[chosen_boost]} (10 минут)"
    )
    
    media_good = get_scarecrow_media_safe(True, final_caption) # True для довольного пугала
    
    # Редактируем сообщение, чтобы поменять картинку и текст
    try:
        await cb.message.edit_media(media=media_good)
    except Exception as e:
        print(f"Ошибка при редактировании медиа (Кадр 2): {e}")
        # Если редактирование не удалось, отправляем новое сообщение
        await cb.message.answer_photo(media_good.media, caption=media_good.caption, parse_mode="HTML")

@dp.callback_query(F.data == "broadcast_cancel", StateFilter(BroadcastStates.waiting_for_broadcast_text))
@dp.callback_query(F.data == "broadcast_cancel", StateFilter(BroadcastStates.waiting_for_broadcast_confirm))
async def broadcast_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("🚫 Рассылка отменена.")
    await cb.answer()@dp.callback_query(F.data == "broadcast_cancel", StateFilter(BroadcastStates.waiting_for_broadcast_text))
@dp.callback_query(F.data == "broadcast_cancel", StateFilter(BroadcastStates.waiting_for_broadcast_confirm))
async def broadcast_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("🚫 Рассылка отменена.")
    await cb.answer()

@dp.callback_query(F.data == "broadcast_confirm", StateFilter(BroadcastStates.waiting_for_broadcast_confirm))
async def execute_broadcast(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    text_to_send = data.get('broadcast_text')
    
    if not text_to_send:
        await cb.answer("❌ Ошибка: Текст не найден в памяти.", show_alert=True)
        await state.clear()
        return

    await cb.message.edit_text("🚀 Начинаю рассылку...")
    await state.clear()
    
    success_count = 0
    block_count = 0
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT user_id FROM users') as cursor:
            users = await cursor.fetchall()

    start_time = time.time()
    
    # Форматирование финального текста
    final_message = f"🔔 <b>ОБЪЯВЛЕНИЕ</b>\n\n{text_to_send}"

    # Проходимся по всем
    for row in users:
        user_id = row[0]
        try:
            # ОТПРАВЛЯЕМ С ReplyKeyboardRemove для удаления игровых кнопок
            await bot.send_message(
                user_id, 
                final_message, 
                parse_mode="HTML",
                reply_markup=ReplyKeyboardRemove() 
            )
            success_count += 1
            await asyncio.sleep(0.05) 
        except Exception:
            block_count += 1

    duration = round(time.time() - start_time, 2)
    
    await cb.message.edit_text(
        f"✅ <b>Рассылка завершена!</b>\n"
        f"⏱ Время: {duration} сек.\n"
        f"📩 Доставлено: {success_count}\n"
        f"🚫 Недоставлено (блок): {block_count}",
        parse_mode="HTML"
    )
    await cb.answer()


@dp.message(F.text == "🎅 Сезонный торговец")
async def santa_shop(message: types.Message):
    # Получаем мандарины (предположим, колонка mandarins)
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT mandarins FROM users WHERE user_id = ?', (message.from_user.id,)) as c:
            mandarins = (await c.fetchone())[0]

    text = (
        f"🎅 <b>Хо-хо-хо! Добро пожаловать!</b>\n"
        f"У тебя есть: <b>{mandarins} 🍊</b>\n\n"
        f"Что хочешь купить?"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Большой Подарок (50 🍊)", callback_data="buy_gift_box")],
        [InlineKeyboardButton(text="🧪 Ящик Химии (30 🍊)", callback_data="buy_fert_box")],
        [InlineKeyboardButton(text="💰 Обменять на помидоры (10 🍊 = 500🍅)", callback_data="ex_mand_tom")]
    ])
    
    # Картинка Санты (найди в инете santa.jpg)
    # await message.answer_photo(FSInputFile("santa.jpg"), caption=text, reply_markup=kb, parse_mode="HTML")
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

# Хендлер покупки подарка
@dp.callback_query(F.data == "buy_gift_box")
async def buy_gift(cb: CallbackQuery):
    user_id = cb.from_user.id
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT mandarins, tomatoes, milk, fertilizer FROM users WHERE user_id = ?', (user_id,)) as c:
            u = await c.fetchone()
            
    if u[0] >= 50:
        # Списываем
        await update_stat(user_id, "mandarins", u[0] - 50)
        
        # Рандомный приз
        prize_roll = random.random()
        if prize_roll < 0.5:
            prize = 5000
            await update_stat(user_id, "tomatoes", u[1] + prize)
            res = f"🍅 {prize} помидоров!"
        elif prize_roll < 0.8:
            prize = 3000
            await update_stat(user_id, "milk", u[2] + prize)
            res = f"🥛 {prize} л. молока!"
        else:
            prize = 10
            await update_stat(user_id, "fertilizer", u[3] + prize)
            res = f"🧪 {prize} шт. химии!"
            
        await cb.message.edit_text(f"🎁 <b>Ты открыл подарок!</b>\nВнутри: <b>{res}</b>", parse_mode="HTML")
    else:
        await cb.answer("❌ Не хватает мандаринов!", show_alert=True)

# --- НАВИГАЦИЯ ПО МЕНЮ ---

@dp.message(F.text == "🏙 Город")
async def nav_town(message: types.Message):
    await message.answer("🏙 Вы пришли на городскую площадь.", reply_markup=town_keyboard())

@dp.message(F.text == "🎴 Коллекция") # Старый хендлер "Карточки"
async def show_cards(message: types.Message):
    # Теперь эта кнопка просто переадресует на новый Склад
    await show_inventory(message)

# --- ИСПРАВЛЕНИЕ: Функция просмотра списка карт ---

async def show_cards_list(message: types.Message):
    """Показывает список карт в виде кнопок для просмотра."""
    user_id = message.from_user.id # В сообщении от callback это работает так же
    
    # Пытаемся определить ID, если message пришел из callback (иногда user_id может быть не в том поле)
    # Но обычно cb.message.chat.id == user_id в личных сообщениях.
    # Для надежности в aiogram 3.x лучше передавать ID явно или брать из chat.id
    target_id = message.chat.id

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT card_id, count FROM user_cards WHERE user_id = ? AND count > 0', (target_id,)) as c:
            my_cards = await c.fetchall()

    if not my_cards:
        text = "🎒 <b>Твой альбом с рэперами пуст.</b>\nЗагляни в Лавку Санты!"
        try:
            await message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⤾ Назад", callback_data="refresh_inv")]]), parse_mode="HTML")
        except:
            await message.answer(text, parse_mode="HTML")
        return

    text = "🎒 <b>ТВОЯ КОЛЛЕКЦИЯ</b>\n<i>Жми на рэпера, чтобы посмотреть карточку:</i>\n\n"
    kb_builder = []
    
    for card_id, count in my_cards:
        if card_id not in CARDS: continue
        
        card_data = CARDS[card_id]
        # Безопасное получение иконки
        rarity_key = card_data.get("rarity", "common")
        rarity_icon = RARITY_INFO.get(rarity_key, RARITY_INFO["common"])["icon"]
        
        # Кнопка: [ 🟢 Morgenshtern (x2) ] -> view_card_morgen
        btn_text = f"{rarity_icon} {card_data['name']} (x{count})"
        kb_builder.append([InlineKeyboardButton(text=btn_text, callback_data=f"view_card_{card_id}")])

    kb_builder.append([InlineKeyboardButton(text="⤾ Назад в Склад", callback_data="refresh_inv")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_builder)
    
    # Пытаемся отредактировать сообщение, если не выйдет - шлем новое
    try:
        await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except:
        await message.answer(text, reply_markup=kb, parse_mode="HTML")

@dp.message(F.text == "🎡 Развлечения")
async def nav_fun(message: types.Message):
    await message.answer("🎪 Добро пожаловать в парк развлечений!", reply_markup=fun_keyboard())

# --- НОВАЯ АДМИН ПАНЕЛЬ ---

@dp.message(Command("admin"))
async def admin_panel_start(message: types.Message, state: FSMContext):
    if message.from_user.username.lower() not in ADMINS: return
    await state.clear()
    
    text = "🕵️‍♂️ <b>ПАНЕЛЬ АДМИНИСТРАТОРА</b>\nВыберите категорию:"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Ресурсы (Give/Set)", callback_data="admin_cat_eco")],
        [InlineKeyboardButton(text="🃏 Карточки (Give/Take)", callback_data="admin_cat_cards")],
        [InlineKeyboardButton(text="❌ Закрыть", callback_data="admin_close")]
    ])
    try: await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except: await message.answer(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "admin_close")
async def admin_close_handler(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.delete()

@dp.callback_query(F.data == "admin_back_main")
async def admin_back(cb: CallbackQuery, state: FSMContext):
    await admin_panel_start(cb.message, state)

# ================================
# ЛОГИКА КАРТОЧЕК (AdminCardStates)
# ================================
@dp.callback_query(F.data == "admin_cat_cards")
async def admin_cards_menu(cb: CallbackQuery):
    text = "🃏 <b>УПРАВЛЕНИЕ КАРТАМИ</b>"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ ВЫДАТЬ Карту", callback_data="adm_card_op_give")],
        [InlineKeyboardButton(text="➖ ЗАБРАТЬ Карту", callback_data="adm_card_op_take")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back_main")]
    ])
    await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("adm_card_op_"))
async def admin_card_op_select(cb: CallbackQuery, state: FSMContext):
    op = cb.data.split("_")[3]
    await state.update_data(op=op)
    # Переходим в состояние КАРТЫ (ждет текст)
    await state.set_state(AdminCardStates.waiting_for_card_id)
    await cb.message.edit_text("✍️ <b>Введите ID КАРТЫ</b> (текстом):\nПример: <code>morgen</code>, <code>52</code>...", parse_mode="HTML")

@dp.message(StateFilter(AdminCardStates.waiting_for_card_id))
async def admin_card_get_id(message: types.Message, state: FSMContext):
    card_id = message.text.strip()
    if card_id not in CARDS:
        await message.answer("❌ Такой карты нет в базе.")
        return
    
    await state.update_data(card_id=card_id)
    
    # Кнопка для выдачи ВСЕМ
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 ВЫДАТЬ ВСЕМ", callback_data="adm_target_all_cards")]
    ])
    
    await message.answer(f"✅ Карта: <b>{CARDS[card_id]['name']}</b>\nТеперь введите <b>ID ИГРОКА</b> (число) или нажмите кнопку:", reply_markup=kb, parse_mode="HTML")
    await state.set_state(AdminCardStates.waiting_for_target)

# Выдача ВСЕМ (Карты)
@dp.callback_query(F.data == "adm_target_all_cards", StateFilter(AdminCardStates.waiting_for_target))
async def admin_card_target_all(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    card_id = data['card_id']
    op = data['op']
    
    if op == "take":
        await cb.answer("❌ Нельзя забрать у всех сразу.", show_alert=True); return

    await cb.message.edit_text("🚀 <b>Выдача карт всем...</b>", parse_mode="HTML")
    
    async with aiosqlite.connect(DB_NAME) as db:
        users = await db.execute_fetchall('SELECT user_id FROM users')
        count = 0
        for (uid,) in users:
            exists = await db.execute_fetchall('SELECT 1 FROM user_cards WHERE user_id = ? AND card_id = ?', (uid, card_id))
            if exists:
                await db.execute('UPDATE user_cards SET count = count + 1 WHERE user_id = ? AND card_id = ?', (uid, card_id))
            else:
                await db.execute('INSERT INTO user_cards (user_id, card_id, count) VALUES (?, ?, 1)', (uid, card_id))
            count += 1
        await db.commit()
        
    await cb.message.edit_text(f"✅ Карта <b>{card_id}</b> выдана {count} игрокам!", parse_mode="HTML")
    await state.clear()

# Выдача ОДНОМУ (Карты)
@dp.message(StateFilter(AdminCardStates.waiting_for_target))
async def admin_card_target_single(message: types.Message, state: FSMContext):
    try:
        target_id = int(message.text)
    except:
        await message.answer("❌ ID игрока должен быть числом!")
        return
        
    data = await state.get_data()
    op = data['op']
    card_id = data['card_id']
    
    async with aiosqlite.connect(DB_NAME) as db:
        if op == "give":
            exists = await db.execute_fetchall('SELECT 1 FROM user_cards WHERE user_id = ? AND card_id = ?', (target_id, card_id))
            if exists:
                await db.execute('UPDATE user_cards SET count = count + 1 WHERE user_id = ? AND card_id = ?', (target_id, card_id))
            else:
                await db.execute('INSERT INTO user_cards (user_id, card_id, count) VALUES (?, ?, 1)', (target_id, card_id))
            action = "выдана"
        else:
            await db.execute('DELETE FROM user_cards WHERE user_id = ? AND card_id = ?', (target_id, card_id))
            action = "забрана"
        await db.commit()
        
    await message.answer(f"✅ Карта <b>{card_id}</b> {action} у ID {target_id}.", parse_mode="HTML")
    await state.clear()


# ================================
# ЛОГИКА РЕСУРСОВ (AdminEcoStates)
# ================================
@dp.callback_query(F.data == "admin_cat_eco")
async def admin_eco_menu(cb: CallbackQuery):
    text = "💰 <b>УПРАВЛЕНИЕ РЕСУРСАМИ</b>"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍅 Помидоры", callback_data="adm_res_tomatoes"),
         InlineKeyboardButton(text="🥛 Молоко", callback_data="adm_res_milk")],
        [InlineKeyboardButton(text="🍊 Мандарины", callback_data="adm_res_mandarins"),
         InlineKeyboardButton(text="🧪 Химия", callback_data="adm_res_fertilizer")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back_main")]
    ])
    await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("adm_res_"))
async def admin_select_resource(cb: CallbackQuery, state: FSMContext):
    res = cb.data.split("_")[2]
    await state.update_data(res=res)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ ВЫДАТЬ", callback_data="adm_op_add"),
         InlineKeyboardButton(text="➖ ЗАБРАТЬ", callback_data="adm_op_remove")],
        [InlineKeyboardButton(text="✏️ УСТАНОВИТЬ", callback_data="adm_op_set")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="admin_cat_eco")]
    ])
    await cb.message.edit_text(f"⚙️ Ресурс: <b>{res.upper()}</b>. Действие:", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("adm_op_"))
async def admin_select_op(cb: CallbackQuery, state: FSMContext):
    op = cb.data.split("_")[2]
    await state.update_data(op=op)
    
    kb = None
    if op in ["add", "remove"]:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="👥 ПРИМЕНИТЬ КО ВСЕМ", callback_data="adm_target_all_res")]])
    
    # Переходим в состояние ЭКОНОМИКИ (ждет ID)
    await state.set_state(AdminEcoStates.waiting_for_user_id)
    await cb.message.edit_text("✍️ <b>Введите ID ИГРОКА</b> или нажмите кнопку:", reply_markup=kb, parse_mode="HTML")

# Кнопка ВСЕМ (Ресурсы)
@dp.callback_query(F.data == "adm_target_all_res", StateFilter(AdminEcoStates.waiting_for_user_id))
async def admin_res_all(cb: CallbackQuery, state: FSMContext):
    await state.update_data(target_user_id="ALL")
    await state.set_state(AdminEcoStates.waiting_for_amount)
    await cb.message.edit_text("✍️ <b>Введите КОЛИЧЕСТВО</b> для всех:", parse_mode="HTML")

# Ввод ID вручную (Ресурсы)
@dp.message(StateFilter(AdminEcoStates.waiting_for_user_id))
async def admin_res_get_id(message: types.Message, state: FSMContext):
    try:
        user_id = int(message.text)
        await state.update_data(target_user_id=user_id)
        await state.set_state(AdminEcoStates.waiting_for_amount)
        await message.answer("✍️ <b>Введите КОЛИЧЕСТВО:</b>", parse_mode="HTML")
    except:
        await message.answer("❌ ID должен быть числом.")

# Финал (Ресурсы)
@dp.message(StateFilter(AdminEcoStates.waiting_for_amount))
async def admin_res_final(message: types.Message, state: FSMContext):
    try:
        amount = int(message.text)
    except:
        await message.answer("❌ Введите число.")
        return
        
    data = await state.get_data()
    target = data['target_user_id']
    res = data['res']
    op = data['op']
    
    async with aiosqlite.connect(DB_NAME) as db:
        if target == "ALL":
            if op == "add": await db.execute(f'UPDATE users SET {res} = {res} + ?', (amount,))
            elif op == "remove": await db.execute(f'UPDATE users SET {res} = MAX(0, {res} - ?)', (amount,))
            await db.commit()
            await message.answer(f"✅ <b>{op.upper()} {amount} {res}</b> выполнено для ВСЕХ.", parse_mode="HTML")
        else:
            # Одиночное действие
            if op == "add": await db.execute(f'UPDATE users SET {res} = {res} + ? WHERE user_id = ?', (amount, target))
            elif op == "remove": await db.execute(f'UPDATE users SET {res} = MAX(0, {res} - ?) WHERE user_id = ?', (amount, target))
            elif op == "set": await db.execute(f'UPDATE users SET {res} = ? WHERE user_id = ?', (amount, target))
            await db.commit()
            await message.answer(f"✅ Успешно для ID {target}.", parse_mode="HTML")
    
    await state.clear()

# --- ХЕНДЛЕР ПРОСМОТРА КАРТЫ (ИСПРАВЛЕННЫЙ) ---
@dp.callback_query(F.data.startswith("view_card_"))
async def view_card_handler(cb: CallbackQuery):
    try:
        # data format: view_card_morgenshtern
        card_id = cb.data.split("_", 2)[2] # split(_, 2) чтобы не ломалось если в ID есть "_"
        user_id = cb.from_user.id
        
        # Проверяем наличие карты
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute('SELECT count FROM user_cards WHERE user_id = ? AND card_id = ?', (user_id, card_id)) as c:
                res = await c.fetchone()
                count = res[0] if res else 0

        # Отправляем инфо. Важно: send_card_info отправляет НОВОЕ сообщение.
        # Чтобы не спамить, можно удалять старое меню или просто слать вниз.
        # По логике "чистого чата" лучше прислать новое.
        await send_card_info(cb.message, card_id, count)
        await cb.answer()
        
    except Exception as e:
        print(f"Ошибка просмотра карты: {e}")
        await cb.answer("Ошибка доступа к карте", show_alert=True)

# --- ХЕНДЛЕР: ПРОСМОТР ЧУЖОГО ПРОФИЛЯ ---
@dp.callback_query(F.data.startswith("view_profile_"))
async def view_other_profile(cb: CallbackQuery):
    target_id = int(cb.data.split("_")[2])
    
    # Загружаем данные ЦЕЛИ (target_id), а не свои
    user = await get_user(target_id)
    
    if not user:
        await cb.answer("❌ Игрок не найден (возможно, удален).", show_alert=True)
        return

    # Красивый вывод (как в Мой Профиль, но для другого)
    text = (
        f"🕵️‍♂️ <b>ДОСЬЕ ИГРОКА</b>\n"
        f"{UI_SEP}\n"
        f"💳 <b>ID:</b> <code>{user['user_id']}</code>\n"
        f"🏷 <b>Имя:</b> {user['username']}\n"
        f"🔰 <b>Статус:</b> {user['custom_status']}\n\n"
        
        f"<b>📊 СТАТИСТИКА</b>\n"
        f"{UI_BULLET} Молоко: <code>{format_num(user['milk'])}</code> Л\n"
        f"{UI_BULLET} Помидоры: <code>{format_num(user['tomatoes'])}</code> шт\n"
        f"{UI_BULLET} Уровень клика: <code>{user['click_level']}</code>\n"
        f"{UI_SEP}"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📂 Коллекция игрока", callback_data=f"view_collection_{target_id}")],
        [InlineKeyboardButton(text="⤾ Назад в топ", callback_data="top_tomatoes")]
    ])
    
    try:
        await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except:
        await cb.message.answer(text, reply_markup=kb, parse_mode="HTML")

# --- КОМАНДЫ СКРЫТИЯ (HIDE / UNHIDE) ---

@dp.message(Command("hide"))
async def cmd_hide(message: types.Message):
    # Проверка на админа
    if message.from_user.username.lower() not in ADMINS:
        return

    args = message.text.split()
    # Варианты: /hide admins, /hide admin @nick, /hide admin 12345
    
    if len(args) < 2:
        await message.answer("⚠️ Используйте: `/hide admins` или `/hide admin <user>`", parse_mode="Markdown")
        return

    target_type = args[1].lower()

    async with aiosqlite.connect(DB_NAME) as db:
        
        # 1. Скрыть ВСЕХ админов
        if target_type == "admins":
            await db.execute('UPDATE users SET is_hidden = 1 WHERE is_admin = 1')
            await db.commit()
            await message.answer("🕵️‍♂️ <b>ОПЕРАЦИЯ ВЫПОЛНЕНА:</b>\nВсе администраторы скрыты из топов.", parse_mode="HTML")

        # 2. Скрыть КОНКРЕТНОГО игрока
        elif target_type == "admin" or target_type == "user":
            if len(args) < 3:
                await message.answer("⚠️ Укажите ник или ID.", parse_mode="Markdown")
                return
            
            target_input = args[2]
            # Определяем поиск по ID или Нику
            if target_input.isdigit():
                where_clause = "user_id = ?"
                val = int(target_input)
            else:
                where_clause = "username LIKE ?"
                val = target_input.replace("@", "")

            # Проверяем и обновляем
            async with db.execute(f'SELECT username FROM users WHERE {where_clause}', (val,)) as c:
                user = await c.fetchone()
            
            if user:
                await db.execute(f'UPDATE users SET is_hidden = 1 WHERE {where_clause}', (val,))
                await db.commit()
                await message.answer(f"✅ Игрок <b>{user[0]}</b> скрыт из топов.", parse_mode="HTML")
            else:
                await message.answer("❌ Игрок не найден.")
        else:
             await message.answer("⚠️ Неверный аргумент. Используйте admins или admin.")

@dp.message(Command("unhide"))
async def cmd_unhide(message: types.Message):
    # Проверка на админа
    if message.from_user.username.lower() not in ADMINS:
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("⚠️ Используйте: `/unhide admins` или `/unhide admin <user>`", parse_mode="Markdown")
        return

    target_type = args[1].lower()

    async with aiosqlite.connect(DB_NAME) as db:
        
        # 1. Раскрыть ВСЕХ админов
        if target_type == "admins":
            await db.execute('UPDATE users SET is_hidden = 0 WHERE is_admin = 1')
            await db.commit()
            await message.answer("👁 <b>ОПЕРАЦИЯ ВЫПОЛНЕНА:</b>\nАдминистраторы снова видны в топах.", parse_mode="HTML")

        # 2. Раскрыть КОНКРЕТНОГО игрока
        elif target_type == "admin" or target_type == "user":
            if len(args) < 3:
                await message.answer("⚠️ Укажите ник или ID.", parse_mode="Markdown")
                return
            
            target_input = args[2]
            if target_input.isdigit():
                where_clause = "user_id = ?"
                val = int(target_input)
            else:
                where_clause = "username LIKE ?"
                val = target_input.replace("@", "")

            async with db.execute(f'SELECT username FROM users WHERE {where_clause}', (val,)) as c:
                user = await c.fetchone()
            
            if user:
                await db.execute(f'UPDATE users SET is_hidden = 0 WHERE {where_clause}', (val,))
                await db.commit()
                await message.answer(f"✅ Игрок <b>{user[0]}</b> возвращен в топы.", parse_mode="HTML")
            else:
                await message.answer("❌ Игрок не найден.")

# --- ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ ДЛЯ ГЕНЕРАЦИИ КНОПОК КАРТЫ ---
async def get_card_keyboard(current_id, user_id, is_owner, target_id_if_not_owner=None):
    """Генерирует кнопки: Стрелки и Продать (если владелец)"""
    
    # 1. Получаем список всех карт пользователя для навигации
    async with aiosqlite.connect(DB_NAME) as db:
        # Получаем ID всех карт по порядку добавления
        async with db.execute('SELECT card_id FROM user_cards WHERE user_id = ?', (user_id,)) as c:
            all_cards = [row[0] for row in await c.fetchall()]
    
    kb_rows = []
    
    # 2. Логика навигации (Пред. / След.)
    if current_id in all_cards:
        idx = all_cards.index(current_id)
        prev_card = all_cards[idx - 1] if idx > 0 else all_cards[-1] # Круговая навигация
        next_card = all_cards[idx + 1] if idx < len(all_cards) - 1 else all_cards[0]
        
        # Если я владелец - используем view_card, если смотрю чужое - peek_card
        if is_owner:
            btn_prev = InlineKeyboardButton(text="⬅️", callback_data=f"view_card_{prev_card}")
            btn_next = InlineKeyboardButton(text="➡️", callback_data=f"view_card_{next_card}")
        else:
            # target_id_if_not_owner - это ID того, чьи карты мы смотрим
            btn_prev = InlineKeyboardButton(text="⬅️", callback_data=f"peek_card_{target_id_if_not_owner}_{prev_card}")
            btn_next = InlineKeyboardButton(text="➡️", callback_data=f"peek_card_{target_id_if_not_owner}_{next_card}")
            
        kb_rows.append([btn_prev, InlineKeyboardButton(text=f"{idx+1}/{len(all_cards)}", callback_data="ignore"), btn_next])

    # 3. Кнопка действия
    if is_owner:
        # Если это мои карты - кнопка Продать
        kb_rows.append([InlineKeyboardButton(text=f"💰 Продать", callback_data=f"sell_init_{current_id}")])
        kb_rows.append([InlineKeyboardButton(text="⤾ Назад в Склад", callback_data="refresh_inv")])
    else:
        # Если чужие - только Назад
        kb_rows.append([InlineKeyboardButton(text="⤾ К профилю игрока", callback_data=f"view_profile_{target_id_if_not_owner}")])

    return InlineKeyboardMarkup(inline_keyboard=kb_rows)

# --- ОТПРАВКА КАРТОЧКИ (УНИВЕРСАЛЬНАЯ) ---
async def render_card_message(message_or_call, card_id, count, is_owner, owner_id):
    if card_id not in CARDS:
        return

    card = CARDS[card_id]
    rarity_data = RARITY_INFO.get(card.get("rarity", "common"), RARITY_INFO["common"])
    
    caption = (
        f"{rarity_data['icon']} <b>{card['name']}</b>\n"
        f"{UI_SEP}\n"
        f"🎭 <b>Редкость:</b> {rarity_data['name']}\n"
        f"📜 <b>Описание:</b> <i>{card.get('desc', '...')}</i>\n\n"
        f"🎒 <b>В наличии:</b> {count} шт."
    )

    # Генерируем умную клавиатуру со стрелочками
    kb = await get_card_keyboard(card_id, owner_id, is_owner, owner_id if not is_owner else None)

    image_filename = card.get("img", "default.jpg") 
    image_path = os.path.join(CARDS_DIR, image_filename)
    
    # Отправка
    media = None
    if os.path.exists(image_path):
        media = FSInputFile(image_path)
    
    # Если это Callback (редактируем старое сообщение) - это для стрелочек
    if isinstance(message_or_call, CallbackQuery):
        # Телеграм не дает поменять фото через edit_text, поэтому:
        # Если сообщение уже с фото - меняем media. Если нет - удаляем и шлем новое.
        try:
            if media:
                await message_or_call.message.edit_media(
                    media=InputMediaPhoto(media=media, caption=caption, parse_mode="HTML"),
                    reply_markup=kb
                )
            else:
                # Если фото нет, просто текст меняем
                await message_or_call.message.edit_caption(caption=caption, reply_markup=kb, parse_mode="HTML")
        except:
            # Если не вышло отредактировать (например, тип сообщения другой), шлем новое
            await message_or_call.message.delete()
            if media:
                await message_or_call.message.answer_photo(media, caption=caption, reply_markup=kb, parse_mode="HTML")
            else:
                await message_or_call.message.answer(caption, reply_markup=kb, parse_mode="HTML")
    else:
        # Обычная отправка
        if media:
            await message_or_call.answer_photo(media, caption=caption, reply_markup=kb, parse_mode="HTML")
        else:
            await message_or_call.answer(caption, reply_markup=kb, parse_mode="HTML")


# --- ХЕНДЛЕР 1: СМОТРЮ СВОИ КАРТЫ (view_card_ID) ---
@dp.callback_query(F.data.startswith("view_card_"))
async def view_my_card_handler(cb: CallbackQuery):
    try:
        card_id = cb.data.split("_")[2]
        user_id = cb.from_user.id
        
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute('SELECT count FROM user_cards WHERE user_id = ? AND card_id = ?', (user_id, card_id)) as c:
                res = await c.fetchone()
                count = res[0] if res else 0

        # is_owner = True
        await render_card_message(cb, card_id, count, True, user_id)
        await cb.answer()
    except Exception as e:
        print(e)
        await cb.answer("Ошибка карты")

# --- ХЕНДЛЕР 2: СМОТРЮ ЧУЖИЕ КАРТЫ (peek_card_OWNERID_CARDID) ---
@dp.callback_query(F.data.startswith("peek_card_"))
async def peek_other_card_handler(cb: CallbackQuery):
    try:
        # data: peek_card_123456_morgen
        parts = cb.data.split("_")
        target_id = int(parts[2])
        card_id = parts[3]
        
        async with aiosqlite.connect(DB_NAME) as db:
            async with db.execute('SELECT count FROM user_cards WHERE user_id = ? AND card_id = ?', (target_id, card_id)) as c:
                res = await c.fetchone()
                count = res[0] if res else 0

        # is_owner = False
        await render_card_message(cb, card_id, count, False, target_id)
        await cb.answer()
    except Exception as e:
        print(e)
        await cb.answer("Ошибка просмотра")

# --- ХЕНДЛЕР 3: СПИСОК ЧУЖИХ КАРТ (view_collection_TARGETID) ---
@dp.callback_query(F.data.startswith("view_collection_"))
async def view_other_collection(cb: CallbackQuery):
    target_id = int(cb.data.split("_")[2])
    
    async with aiosqlite.connect(DB_NAME) as db:
        # Имя владельца
        async with db.execute('SELECT username FROM users WHERE user_id = ?', (target_id,)) as c:
            res = await c.fetchone()
            owner_name = res[0] if res else "Unknown"

        # Список карт
        async with db.execute('SELECT card_id, count FROM user_cards WHERE user_id = ? AND count > 0', (target_id,)) as c:
            target_cards = await c.fetchall()

    if not target_cards:
        await cb.answer(f"У {owner_name} нет карточек.", show_alert=True)
        return

    text = f"📂 <b>КОЛЛЕКЦИЯ:</b> {owner_name}\n<i>Нажми на карту для просмотра:</i>\n\n"
    kb_builder = []
    
    for card_id, count in target_cards:
        if card_id not in CARDS: continue
        card_data = CARDS[card_id]
        rarity_icon = RARITY_INFO.get(card_data.get("rarity", "common"), RARITY_INFO["common"])["icon"]
        
        # ВАЖНО: Используем peek_card, чтобы бот знал, что это ЧУЖАЯ карта
        btn_text = f"{rarity_icon} {card_data['name']} (x{count})"
        kb_builder.append([InlineKeyboardButton(text=btn_text, callback_data=f"peek_card_{target_id}_{card_id}")])

    kb_builder.append([InlineKeyboardButton(text="⤾ К профилю", callback_data=f"view_profile_{target_id}")])
    
    await cb.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_builder), parse_mode="HTML")

# --- АДМИН-КОНСОЛЬ ---
async def admin_console_loop(bot: Bot):
    global CONSOLE_LOGS, MAINTENANCE_MODE
    
    # Очистка и приветствие
    os.system('cls' if os.name == 'nt' else 'clear')
    print(f"{Fore.LIGHTBLUE_EX}╔══════════════════════════════════════════════════════════════╗")
    print(f"║ {Fore.LIGHTGREEN_EX}👑 MOLOKO FARM запущен нах v4.0                                   {Fore.LIGHTBLUE_EX}║")
    print(f"║ {Fore.WHITE}Управление: sql, logs, maint, ban, give, list, stats         {Fore.LIGHTBLUE_EX}║")
    print(f"╚══════════════════════════════════════════════════════════════╝{Style.RESET_ALL}")
    
    while True:
        try:
             # --- ИСПРАВЛЕНИЕ БАГА С КОНСОЛЬЮ WINDOWS ---
            # 1. Формируем строку приглашения
            prompt_text = f"\n{Fore.LIGHTBLUE_EX}root@{bot.token.split(':')[0][:8]} {Fore.RED}»{Style.RESET_ALL} "
            
            # 2. Пишем её напрямую в поток вывода (минуя input)
            sys.stdout.write(prompt_text)
            sys.stdout.flush() # Принудительно выталкиваем текст на экран
            
            # 3. Ждем ввод БЕЗ текста приглашения (так курсор не улетит)
            command_raw = await aioconsole.ainput("")
            # -------------------------------------------
            
            if not command_raw: continue
            parts = command_raw.split()
            cmd = parts[0].lower()


 # === RESTART (Перезапуск процесса) ===
            if cmd == "restart":
                print(f"{Fore.RED}⚠️ ПЕРЕЗАГРУЗКА СИСТЕМЫ...{Style.RESET_ALL}")
                print("Бот будет остановлен и запущен заново.")
                # Эта команда полностью перезапускает скрипт
                os.execl(sys.executable, sys.executable, *sys.argv)

            # === CHECK (Полная инфа об игроке) ===
            elif cmd == "check":
                if len(parts) < 2:
                    print("📝 Юз: check <username/id>")
                    continue
                
                target = parts[1]
                query_val = target
                query_col = "user_id" if target.isdigit() else "username"
                
                if query_col == "username":
                    query_val = target.replace("@", "")

                async with aiosqlite.connect(DB_NAME) as db:
                    db.row_factory = aiosqlite.Row # Чтобы обращаться по именам колонок
                    async with db.execute(f'SELECT * FROM users WHERE {query_col} = ?', (query_val,)) as c:
                        user = await c.fetchone()
                
                if not user:
                    print(f"{Fore.RED}❌ Игрок не найден.{Style.RESET_ALL}")
                else:
                    print(f"\n{Fore.CYAN}--- ДОСЬЕ ИГРОКА ---{Style.RESET_ALL}")
                    # Выводим все поля красиво
                    for key in user.keys():
                        val = user[key]
                        # Красим важные поля
                        color = Fore.WHITE
                        if key == "tomatoes": color = Fore.LIGHTRED_EX
                        if key == "milk": color = Fore.WHITE
                        if key == "is_admin" and val == 1: val = f"{Fore.GREEN}YES{Style.RESET_ALL}"
                        if key == "is_banned" and val == 1: val = f"{Fore.RED}YES{Style.RESET_ALL}"
                        
                        print(f"{key:<20}: {color}{val}{Style.RESET_ALL}")
                    print("-" * 30)

            # === CODE (Управление промокодами) ===
            elif cmd == "code":
                if len(parts) < 2:
                    print("📝 Юз: code <create/list/delete>")
                    continue
                
                subcmd = parts[1].lower()
                
                # --- CODE LIST ---
                if subcmd == "list":
                    async with aiosqlite.connect(DB_NAME) as db:
                        async with db.execute('SELECT * FROM promo_codes') as c:
                            codes = await c.fetchall()
                    
                    print(f"\n🎟 {Fore.MAGENTA}АКТИВНЫЕ ПРОМОКОДЫ:{Style.RESET_ALL}")
                    if not codes: print("Нет активных кодов.")
                    
                    for row in codes:
                        c_name, uses, r_type, r_amount = row
                        uses_str = "♾ Бесконечно" if uses == -1 else f"{uses} шт."
                        print(f"🔹 {Fore.YELLOW}{c_name}{Style.RESET_ALL} -> Дает: {r_amount} {r_type} | Осталось: {uses_str}")

                # --- CODE CREATE ---
                # code create <название> <кол-во> <ресурс> <сумма>
                # code create FREE_MONEY 100 tomatoes 5000
                # code create OMEGA -1 milk 1000
                elif subcmd == "create":
                    if len(parts) < 6:
                        print("❌ Формат: code create <код> <кол-во/-1> <ресурс> <сумма>")
                        continue
                        
                    c_name = parts[2]
                    try:
                        c_uses = int(parts[3])
                        c_res = parts[4]
                        c_amount = int(parts[5])
                    except:
                        print("❌ Кол-во и сумма должны быть числами!")
                        continue
                        
                    async with aiosqlite.connect(DB_NAME) as db:
                        try:
                            await db.execute('INSERT INTO promo_codes VALUES (?, ?, ?, ?)', (c_name, c_uses, c_res, c_amount))
                            await db.commit()
                            print(f"{Fore.GREEN}✅ Код {c_name} создан!{Style.RESET_ALL}")
                        except Exception as e:
                            print(f"{Fore.RED}❌ Ошибка (такой код уже есть?): {e}{Style.RESET_ALL}")

                # --- CODE DELETE ---
                elif subcmd == "delete":
                    if len(parts) < 3:
                        print("❌ Формат: code delete <код>")
                        continue
                    
                    c_name = parts[2]
                    async with aiosqlite.connect(DB_NAME) as db:
                        await db.execute('DELETE FROM promo_codes WHERE code = ?', (c_name,))
                        await db.execute('DELETE FROM used_codes WHERE code = ?', (c_name,)) # Удаляем историю ввода, если надо
                        await db.commit()
                    print(f"🗑 Код {c_name} удален.")

            # === 1. УПРАВЛЕНИЕ ЛОГАМИ ===
            if cmd == "logs":
                CONSOLE_LOGS = not CONSOLE_LOGS
                status = f"{Fore.GREEN}ON{Style.RESET_ALL}" if CONSOLE_LOGS else f"{Fore.RED}OFF{Style.RESET_ALL}"
                print(f"📡 Живой лог действий: {status}")

            # === 2. РЕЖИМ ТЕХРАБОТ ===
            elif cmd == "maint":
                MAINTENANCE_MODE = not MAINTENANCE_MODE
                status = f"{Fore.RED}АКТИВЕН (Игроки заблокированы){Style.RESET_ALL}" if MAINTENANCE_MODE else f"{Fore.GREEN}ВЫКЛЮЧЕН (Игра идет){Style.RESET_ALL}"
                print(f"🚧 Режим техработ: {status}")

            # === 3. SETADMIN (Выдать админку) ===
            elif cmd == "setadmin":
                if len(parts) < 3:
                    print(f"{Fore.YELLOW}📝 Юз: setadmin <username> <1/0>{Style.RESET_ALL}")
                    continue
                
                target_name = parts[1].replace("@", "").lower()
                try:
                    lvl = int(parts[2]) # 1 = админ, 0 = не админ
                except:
                    print("❌ Значение должно быть 1 или 0"); continue

                async with aiosqlite.connect(DB_NAME) as db:
                    # Проверяем существование
                    async with db.execute('SELECT user_id FROM users WHERE username LIKE ?', (target_name,)) as c:
                        res = await c.fetchone()
                    
                    if not res:
                        print(f"{Fore.RED}❌ Игрок @{target_name} не найден в БД.{Style.RESET_ALL}")
                        continue
                    
                    uid = res[0]
                    await db.execute('UPDATE users SET is_admin = ? WHERE user_id = ?', (lvl, uid))
                    await db.commit()
                
                # Обновляем список в оперативной памяти
                if lvl == 1:
                    if target_name not in ADMINS: ADMINS.append(target_name)
                    print(f"{Fore.GREEN}✅ Пользователь {target_name} теперь АДМИН!{Style.RESET_ALL}")
                    try: await bot.send_message(uid, "😎 <b>ВАМ ВЫДАНЫ ПРАВА АДМИНИСТРАТОРА!</b>")
                    except: pass
                else:
                    if target_name in ADMINS: ADMINS.remove(target_name)
                    print(f"{Fore.YELLOW}🔸 С пользователя {target_name} сняты права.{Style.RESET_ALL}")

            # === 4. BC (Broadcast - Рассылка) ===
            elif cmd == "bc":
                text = " ".join(parts[1:])
                if not text:
                    print("❌ Введите текст рассылки.")
                    continue
                
                print(f"{Fore.YELLOW}🚀 Начинаю рассылку...{Style.RESET_ALL}")
                async with aiosqlite.connect(DB_NAME) as db:
                    async with db.execute('SELECT user_id FROM users') as c:
                        users = await c.fetchall()
                
                count = 0
                for r in users:
                    try:
                        await bot.send_message(r[0], f"🔔 <b>ОБЪЯВЛЕНИЕ:</b>\n\n{text}", parse_mode="HTML")
                        count += 1
                        # Небольшая задержка чтобы не словить флуд-лимит
                        if count % 20 == 0: await asyncio.sleep(1) 
                    except: pass
                
                print(f"{Fore.GREEN}✅ Рассылка завершена. Доставлено: {count} чел.{Style.RESET_ALL}")

            # === 5. SAY / MSG (Личное сообщение) ===
            elif cmd in ["say", "msg"]:
                if len(parts) < 3:
                    print("📝 Юз: say <id/username> <текст>")
                    continue
                
                target = parts[1]
                text = " ".join(parts[2:])
                
                # Поиск ID если введен ник
                target_id = None
                if not target.isdigit():
                    async with aiosqlite.connect(DB_NAME) as db:
                        async with db.execute('SELECT user_id FROM users WHERE username LIKE ?', (target.replace("@",""),)) as c:
                            res = await c.fetchone()
                            if res: target_id = res[0]
                else:
                    target_id = int(target)
                
                if target_id:
                    try:
                        await bot.send_message(target_id, f"📨 <b>СООБЩЕНИЕ ОТ АДМИНА:</b>\n\n{text}", parse_mode="HTML")
                        print(f"{Fore.GREEN}✅ Отправлено игроку {target_id}{Style.RESET_ALL}")
                    except Exception as e:
                        print(f"{Fore.RED}❌ Не удалось отправить (блок?): {e}{Style.RESET_ALL}")
                else:
                    print(f"{Fore.RED}❌ Игрок не найден.{Style.RESET_ALL}")

            # === 6. SET (Установить значение) ===
            elif cmd == "set":
                if len(parts) < 4:
                    print(f"{Fore.YELLOW}📝 Юз: set <id/nick> <field> <value>{Style.RESET_ALL}")
                    print("Доступные поля: tomatoes, milk, fertilizer, mandarins, click_level, luck_level...")
                    continue
                
                target_input, field, value = parts[1], parts[2].lower(), parts[3]
                
                # Защита от дурака (список разрешенных полей)
                allowed_fields = [
                    "milk", "tomatoes", "fertilizer", "mandarins", 
                    "click_level", "tomato_level", "luck_level", "safety_level", 
                    "eco_level", "casino_level", "gmo_level", 
                    "acad_management", "acad_logistics", "acad_agronomy"
                ]
                
                if field not in allowed_fields:
                    print(f"{Fore.RED}❌ Поле '{field}' менять нельзя! Только ресурсы и уровни.{Style.RESET_ALL}")
                    continue

                async with aiosqlite.connect(DB_NAME) as db:
                    # Поиск ID
                    target_id = target_input
                    if not target_input.isdigit():
                        async with db.execute('SELECT user_id FROM users WHERE username LIKE ?', (target_input.replace("@",""),)) as c:
                            res = await c.fetchone()
                            if res: target_id = res[0]
                            else: 
                                print("❌ Игрок не найден"); continue

                    await db.execute(f'UPDATE users SET {field} = ? WHERE user_id = ?', (value, target_id))
                    await db.commit()
                
                print(f"{Fore.GREEN}✅ Игроку {target_id} установлено {field} = {value}{Style.RESET_ALL}")

            # === 3. SQL (Самая мощная команда) ===
            # Пример: sql SELECT * FROM users WHERE user_id = 123
            # Пример: sql UPDATE users SET tomatoes = 999999
            elif cmd == "sql":
                query = " ".join(parts[1:])
                if not query:
                    print(f"{Fore.YELLOW}⚠️ Введи SQL запрос.{Style.RESET_ALL}")
                    continue
                
                try:
                    async with aiosqlite.connect(DB_NAME) as db:
                        async with db.execute(query) as cursor:
                            # Если это SELECT - показываем таблицу
                            if query.strip().upper().startswith("SELECT"):
                                rows = await cursor.fetchall()
                                headers = [description[0] for description in cursor.description]
                                
                                # Красивый вывод таблицы
                                print(f"{Fore.CYAN}" + " | ".join(f"{h:<12}" for h in headers) + f"{Style.RESET_ALL}")
                                print("-" * (len(headers) * 15))
                                for row in rows:
                                    print(" | ".join(f"{str(item):<12}" for item in row))
                                print(f"\n{Fore.GREEN}Найдено строк: {len(rows)}{Style.RESET_ALL}")
                            else:
                                # Если UPDATE/DELETE/INSERT
                                await db.commit()
                                print(f"{Fore.GREEN}✅ Запрос выполнен успішно! Изменений в БД.{Style.RESET_ALL}")
                except Exception as e:
                    print(f"{Fore.RED}💥 SQL Error: {e}{Style.RESET_ALL}")

            # === 4. LIST (Обновленный) ===
            elif cmd == "list":
                async with aiosqlite.connect(DB_NAME) as db:
                    async with db.execute('SELECT user_id, username, tomatoes, milk, last_active FROM users ORDER BY last_active DESC LIMIT 20') as c:
                        users = await c.fetchall()
                
                print(f"\n{Fore.LIGHTYELLOW_EX}--- ПОСЛЕДНИЕ АКТИВНЫЕ ИГРОКИ ---{Style.RESET_ALL}")
                print(f"{'ID':<12} | {'Имя':<15} | {'Помидоры':<10} | {'Молоко':<10} | {'Статус'}")
                print("-" * 65)
                
                now = time.time()
                for u in users:
                    uid, name, tom, milk, last = u
                    name = (name[:13] + '..') if name and len(name) > 13 else (name or "Unknown")
                    
                    # Статус
                    if (now - last) < 300: status = f"{Fore.GREEN}ONLINE{Style.RESET_ALL}"
                    elif (now - last) < 3600: status = f"{Fore.YELLOW}1h ago{Style.RESET_ALL}"
                    else: status = f"{Fore.RED}OFFLINE{Style.RESET_ALL}"
                    
                    print(f"{uid:<12} | {name:<15} | {format_num(tom):<10} | {format_num(milk):<10} | {status}")

            # === 5. GIVE (Улучшенный) ===
            elif cmd == "give":
                if len(parts) < 4:
                    print("📝 Юз: give <id/username> <res> <amount>")
                    continue
                
                target, res, amount = parts[1], parts[2], int(parts[3])
                
                async with aiosqlite.connect(DB_NAME) as db:
                    # Попытка найти по username если это не число
                    if not target.isdigit():
                        async with db.execute('SELECT user_id FROM users WHERE username = ?', (target,)) as c:
                            found = await c.fetchone()
                            if found: target = found[0]
                            else: 
                                print("❌ Юзернейм не найден"); continue
                    
                    await db.execute(f'UPDATE users SET {res} = {res} + ? WHERE user_id = ?', (amount, target))
                    await db.commit()
                
                print(f"{Fore.GREEN}✅ Выдано {amount} {res} игроку {target}{Style.RESET_ALL}")
                try: await bot.send_message(target, f"🎁 <b>АДМИН:</b> Вам начислено {format_num(amount)} {res}!")
                except: pass

            # === 6. MESSAGE (ЛС) ===
            elif cmd == "msg":
                if len(parts) < 3:
                    print("📝 Юз: msg <id> <текст>")
                    continue
                
                uid = parts[1]
                text = " ".join(parts[2:])
                try:
                    await bot.send_message(uid, f"📨 <b>СООБЩЕНИЕ ОТ АДМИНА:</b>\n\n{text}", parse_mode="HTML")
                    print(f"{Fore.GREEN}✅ Отправлено.{Style.RESET_ALL}")
                except Exception as e:
                    print(f"{Fore.RED}❌ Ошибка: {e}{Style.RESET_ALL}")

            # === 7. STATS ===
            elif cmd == "stats":
                async with aiosqlite.connect(DB_NAME) as db:
                    users_cnt = (await (await db.execute('SELECT count(*) FROM users')).fetchone())[0]
                    money = (await (await db.execute('SELECT sum(tomatoes) FROM users')).fetchone())[0]
                
                print(f"\n📊 <b>СТАТИСТИКА:</b>")
                print(f"👥 Игроков: {Fore.CYAN}{users_cnt}{Style.RESET_ALL}")
                print(f"💰 Всего помидоров: {Fore.GREEN}{format_num(money)}{Style.RESET_ALL}")
                print(f"📡 Логи: {CONSOLE_LOGS} | 🚧 Техработы: {MAINTENANCE_MODE}")

            # === HELP ===
            elif cmd == "commands":
                print(f"""
{Fore.YELLOW}Команды:{Style.RESET_ALL}
 🔄 {Fore.CYAN}restart{Style.RESET_ALL} - Перезагрузить бота
 👤 {Fore.CYAN}check <nick/id>{Style.RESET_ALL} - Досье на игрока
 🎟 {Fore.CYAN}code <create/list/delete>{Style.RESET_ALL} - Промокоды
 🛠 {Fore.CYAN}set, setadmin, give, bc, sql, logs{Style.RESET_ALL} - Стандартные
                """)

            else:
                print(f"{Fore.RED}Неизвестная команда. Пиши command{Style.RESET_ALL}")

        except Exception as e:
            print(f"{Fore.RED}CRITICAL ERROR: {e}{Style.RESET_ALL}")

# --- ЛОГИКА АКАДЕМИИ (СВЯЗЬ С GO) ---

def get_academy_render_data(u, harvest_msg=""):
    stats = get_academy_stats(u)
    
    text = (
        f"🏛 <b>УПРАВЛЕНИЕ АКАДЕМИЕЙ</b>\n"
        f"{UI_SEP}\n"
        f"🎓 <b>Звание:</b> {stats['title']} (Ранг {stats['total_lvl']})\n"
        f"{harvest_msg}\n\n"
        
        f"<b>📈 СТАТУС ОТДЕЛОВ</b>\n"
        f"{UI_BULLET} <b>Менеджмент (Доход):</b>\n"
        f"   └ <code>{stats['income']}</code> 🍅 / час\n"
        
        f"{UI_BULLET} <b>Логистика (Склад):</b>\n"
        f"   └ <code>{stats['max_time']}</code> часов (лимит AFK)\n"
        
        f"{UI_BULLET} <b>Агрономия (Льготы):</b>\n"
        f"   └ <code>-{int(stats['discount']*100)}%</code> скидка в магазине\n"
        f"{UI_SEP}\n"
        f"<i>Инвестируйте в образование для роста эффективности.</i>"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬆️ Повысить квалификацию", callback_data="acad_upgrades")],
        [InlineKeyboardButton(text="🔄 Обновить данные", callback_data="acad_refresh")]
    ])
    
    return text, kb

# --- ХЕНДЛЕРЫ АКАДЕМИИ ---

@dp.message(F.text == "🎓 Академия")
async def nav_academy(message: types.Message):
    user_id = message.from_user.id
    u = await get_user(user_id)
    
    # 1. Автосбор дохода
    harvest, msg = await collect_academy_income(user_id, u)
    if harvest > 0:
        # Если собрали урожай - обновляем данные пользователя
        u = await get_user(user_id)
        # Добавляем сообщение о сборе прямо в меню
        msg = f"\n💰 <b>Собрано при входе:</b> +{harvest} 🍅"
    
    # 2. Генерируем меню
    text, kb = get_academy_render_data(u, harvest_msg=msg)
    
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "acad_refresh")
async def acad_refresh(cb: CallbackQuery):
    # БЕРЕМ ID ИГРОКА, КОТОРЫЙ НАЖАЛ КНОПКУ
    user_id = cb.from_user.id 
    u = await get_user(user_id)
    
    # 1. Тоже пробуем собрать доход при обновлении
    harvest, msg = await collect_academy_income(user_id, u)
    if harvest > 0:
        u = await get_user(user_id)
        msg = f"\n💰 <b>Собрано:</b> +{harvest} 🍅"
        # Показываем уведомление всплывающим окном
        await cb.answer(f"Собрано {harvest} помидоров!", show_alert=False)
    else:
        await cb.answer("Данные обновлены")
        
    # 2. Генерируем меню
    text, kb = get_academy_render_data(u, harvest_msg=msg)
    
    # 3. Редактируем сообщение (чтобы не моргало)
    try:
        await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        # Если текст не изменился, телеграм выдаст ошибку, игнорируем её
        pass

# Измените определение функции (добавьте аргумент user_data=None)
@dp.callback_query(F.data == "acad_upgrades")
async def acad_upgrades_menu(cb: CallbackQuery, user_data=None):
    user_id = cb.from_user.id
    
    # ЕСЛИ мы передали свежие данные (после покупки) - используем их.
    # ИНАЧЕ - загружаем из базы (обычный вход в меню).
    if user_data:
        u = user_data
    else:
        u = await get_user(user_id)
    
    # Получаем статистику
    stats = get_academy_stats(u)
    
    lvl_man = u['acad_management']
    lvl_log = u['acad_logistics']
    lvl_agr = u['acad_agronomy']
    
    # Формулы цен
    price_man = int(COST_MANAGEMENT * (1.5 ** lvl_man))
    price_log = int(COST_LOGISTICS * (1.6 ** lvl_log))
    price_agr = int(COST_AGRONOMY * (1.8 ** lvl_agr))
    
    # Предпросмотр (что будет на СЛЕДУЮЩЕМ уровне)
    # Менеджмент: след. уровень
    next_income = ACAD_BASE_INCOME + (lvl_man * ACAD_INCOME_MULT)
    # Логистика: след. уровень
    next_time = ACAD_BASE_TIME + ((lvl_log + 1) * ACAD_TIME_BONUS)
    # Агрономия: след. уровень
    next_disc = min(0.30, (lvl_agr + 1) * ACAD_DISCOUNT_PER_LVL)

    text = (
        f"🎓 <b>УЧЕБНАЯ ЧАСТЬ</b>\n"
        f"Твой ранг: <b>{stats['title']}</b> (Суммарный LVL: {stats['total_lvl']})\n"
        f"До след. ранга: {5 - stats['total_lvl'] if stats['total_lvl'] < 5 else '??'} уровней\n"
        f"➖➖➖➖➖➖➖➖\n"
        f"📈 <b>Менеджмент (LVL {lvl_man})</b>\n"
        f"Текущий: {stats['income']} 🍅/ч ➡ <b>{next_income} 🍅/ч</b>\n\n"
        f"⏳ <b>Логистика (LVL {lvl_log})</b>\n"
        f"Текущий: {stats['max_time']} ч. ➡ <b>{next_time} ч.</b>\n\n"
        f"🧬 <b>Агрономия (LVL {lvl_agr})</b>\n"
        f"Скидка: {int(stats['discount']*100)}% ➡ <b>{int(next_disc*100)}%</b>\n"
        f"➖➖➖➖➖➖➖➖"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📈 Улучшить ({format_num(price_man)} 🍅)", 
                              callback_data=f"acad_buy_man_{price_man}")],
        [InlineKeyboardButton(text=f"⏳ Улучшить ({format_num(price_log)} 🍅)", 
                              callback_data=f"acad_buy_log_{price_log}")],
        [InlineKeyboardButton(text=f"🧬 Улучшить ({format_num(price_agr)} 🍅)", 
                              callback_data=f"acad_buy_agr_{price_agr}")],
        [InlineKeyboardButton(text="⤾ Назад в Холл", callback_data="acad_refresh")]
    ])
    
    # Используем edit_text
    await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

# --- НАСТРОЙКИ КРАФТА ---
MUTAGEN_SHOP_PRICE = 5000 # Цена мутагена в магазине (помидоры)
CRAFT_COST_MUTAGEN = 1    # Сколько мутагена нужно на 1 крафт
CRAFT_CARDS_NEEDED = 3    # Сколько одинаковых карт нужно сжечь для крафта

# --- 🧬 ЛАБОРАТОРИЯ ---
@dp.message(F.text == "🧬 Лаборатория")
async def lab_menu(message: types.Message):
    user_id = message.from_user.id
    u = await get_user(user_id)
    
    text = (
        f"🧬 <b>ГЕННАЯ ЛАБОРАТОРИЯ</b>\n"
        f"{UI_SEP}\n"
        f"🧪 Мутаген: <code>{u['mutagen']}</code> ед.\n\n"
        f"<b>🔬 СИНТЕЗ КАРТ:</b>\n"
        f"Требуется: <b>{CRAFT_CARDS_NEEDED} копии</b> одной карты + <b>{CRAFT_COST_MUTAGEN} мутаген</b>.\n"
        f"Результат: <b>1 Случайная карта</b> более высокой редкости.\n"
        f"{UI_SEP}\n"
        f"👇 <i>Выберите действие:</i>"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🧪 Купить Мутаген ({format_num(MUTAGEN_SHOP_PRICE)} 🍅)", callback_data="buy_mutagen")],
        [InlineKeyboardButton(text="⚗️ Начать Синтез", callback_data="start_craft_list")],
        [InlineKeyboardButton(text="🔙 Закрыть", callback_data="delete_msg")]
    ])
    
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "buy_mutagen")
async def buy_mutagen_handler(cb: CallbackQuery):
    user_id = cb.from_user.id
    u = await get_user(user_id)
    
    if u['tomatoes'] >= MUTAGEN_SHOP_PRICE:
        await update_stat(user_id, "tomatoes", u['tomatoes'] - MUTAGEN_SHOP_PRICE)
        await update_stat(user_id, "mutagen", u['mutagen'] + 1)
        await cb.answer("✅ Мутаген приобретен!", show_alert=True)
        await lab_menu(cb.message) # Обновляем меню
        await cb.message.delete()
    else:
        await cb.answer("❌ Недостаточно средств!", show_alert=True)

@dp.callback_query(F.data == "start_craft_list")
async def craft_list_handler(cb: CallbackQuery):
    user_id = cb.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT card_id, count FROM user_cards WHERE user_id = ? AND count >= ?', (user_id, CRAFT_CARDS_NEEDED)) as c:
            candidates = await c.fetchall()
            
    if not candidates:
        await cb.answer(f"❌ Нет подходящих карт (нужно {CRAFT_CARDS_NEEDED} копии)", show_alert=True)
        return
        
    kb_rows = []
    for card_id, count in candidates:
        if card_id not in CARDS: continue
        card_name = CARDS[card_id]['name']
        rarity = CARDS[card_id].get('rarity', 'common')
        
        if rarity == 'limited': continue 
        
        btn_text = f"{card_name} ({count} шт)"
        kb_rows.append([InlineKeyboardButton(text=btn_text, callback_data=f"do_craft_{card_id}")])
        
    kb_rows.append([InlineKeyboardButton(text="🔙 Отмена", callback_data="delete_msg")])
    
    await cb.message.edit_text("⚗️ <b>СЕЛЕКЦИЯ:</b>\nВыберите образец для мутации:", 
                               reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows), parse_mode="HTML")

@dp.callback_query(F.data.startswith("do_craft_"))
async def execute_craft(cb: CallbackQuery):
    card_id_input = cb.data.split("_")[2]
    user_id = cb.from_user.id
    u = await get_user(user_id)
    
    if u['mutagen'] < CRAFT_COST_MUTAGEN:
        await cb.answer(f"❌ Требуется {CRAFT_COST_MUTAGEN} мутаген!", show_alert=True)
        return
        
    input_rarity = CARDS[card_id_input].get('rarity', 'common')
    
    # Логика повышения редкости
    target_rarity = "rare"
    if input_rarity == "rare": target_rarity = "epic"
    elif input_rarity == "epic": target_rarity = "limited"
    
    potential_rewards = [cid for cid, cdata in CARDS.items() if cdata.get('rarity') == target_rarity]
    
    if not potential_rewards:
        await cb.answer("❌ Ошибка базы (нет карт такой редкости).", show_alert=True)
        return
        
    reward_card_id = random.choice(potential_rewards)
    reward_name = CARDS[reward_card_id]['name']
    
    async with aiosqlite.connect(DB_NAME) as db:
        # Списываем
        await db.execute('UPDATE user_cards SET count = count - ? WHERE user_id = ? AND card_id = ?', (CRAFT_CARDS_NEEDED, user_id, card_id_input))
        await db.execute('UPDATE users SET mutagen = mutagen - ? WHERE user_id = ?', (CRAFT_COST_MUTAGEN, user_id))
        
        # Начисляем новую
        exists = await db.execute_fetchall('SELECT 1 FROM user_cards WHERE user_id = ? AND card_id = ?', (user_id, reward_card_id))
        if exists:
            await db.execute('UPDATE user_cards SET count = count + 1 WHERE user_id = ? AND card_id = ?', (user_id, reward_card_id))
        else:
            await db.execute('INSERT INTO user_cards (user_id, card_id, count) VALUES (?, ?, 1)', (user_id, reward_card_id))
        await db.commit()
        
    await cb.message.edit_text(f"🧬 <b>СИНТЕЗ УСПЕШЕН!</b>\nПолучена карта: {reward_name}", parse_mode="HTML")
    # Показываем карту
    await send_card_info(cb.message, reward_card_id, 1)

@dp.callback_query(F.data.startswith("acad_buy_"))
async def buy_course_handler(cb: CallbackQuery):
    # Разбор данных: acad_buy_man_1000
    parts = cb.data.split("_")
    course_type = parts[2] # man, log, agr
    price = int(parts[3])
    
    user_id = cb.from_user.id
    u = await get_user(user_id)
    
    # Проверка баланса
    if u['tomatoes'] < price:
        await cb.answer(f"❌ Не хватает помидоров! Нужно {format_num(price)}", show_alert=True)
        return
    
    # Определение колонок
    col_name = ""
    nice_name = ""
    
    if course_type == "man":
        col_name = "acad_management"
        nice_name = "Менеджмент"
    elif course_type == "log":
        col_name = "acad_logistics"
        nice_name = "Логистика"
    elif course_type == "agr":
        col_name = "acad_agronomy"
        nice_name = "Агрономия"
        
    current_lvl = u[col_name]
    
    # 1. Списываем средства и повышаем уровень в БД
    await update_stat(user_id, "tomatoes", u['tomatoes'] - price)
    await update_stat(user_id, col_name, current_lvl + 1)
    
    # Если это первая покупка Менеджмента, запускаем таймер
    if course_type == "man" and current_lvl == 0:
        await update_stat(user_id, "last_acad_collect", time.time())
    
    await cb.answer(f"✅ Курс '{nice_name}' изучен!", show_alert=False)
    
    # 2. КРИТИЧЕСКИЙ МОМЕНТ:
    # Принудительно загружаем ОБНОВЛЕННОГО пользователя из БД
    fresh_user = await get_user(user_id)
    
    # 3. Передаем свежие данные в меню, чтобы цифры обновились сразу
    await acad_upgrades_menu(cb, user_data=fresh_user)

# --- ЛОГИКА АКАДЕМИИ (МАТЕМАТИКА) ---

def get_academy_stats(u: aiosqlite.Row):
    """Возвращает словарь со всеми рассчитанными параметрами академии."""
    lvl_man = u['acad_management']
    lvl_log = u['acad_logistics']
    lvl_agr = u['acad_agronomy']
    
    # 1. Расчет дохода (Менеджмент)
    income_per_hour = 0
    if lvl_man > 0:
        # Ур 1 = База. Ур 2 = База + Бонус
        income_per_hour = ACAD_BASE_INCOME + (lvl_man - 1) * ACAD_INCOME_MULT
        
    # 2. Расчет времени (Логистика)
    # База + (Уровень * Бонус)
    max_hours = ACAD_BASE_TIME + (lvl_log * ACAD_TIME_BONUS)
    
    # 3. Расчет скидки (Агрономия) - Максимум 30%
    discount_percent = min(0.30, lvl_agr * ACAD_DISCOUNT_PER_LVL)
    
    # 4. Расчет Звания (Суммарный уровень)
    total_lvl = lvl_man + lvl_log + lvl_agr
    
    # Логика званий:
    if total_lvl == 0: title = "Абитуриент"
    elif total_lvl < 5: title = "Студент"     # 1-4 уровня
    elif total_lvl < 15: title = "Бакалавр"   # 5-14 уровней
    elif total_lvl < 30: title = "Магистр"    # 15-29 уровней
    else: title = "Профессор"                 # 30+ уровней
    
    return {
        "income": income_per_hour,
        "max_time": max_hours,
        "discount": discount_percent,
        "title": title,
        "total_lvl": total_lvl
    }

async def collect_academy_income(user_id: int, u: aiosqlite.Row) -> (int, str):
    """Собирает накопленный доход при входе."""
    stats = get_academy_stats(u)
    income_rate = stats['income']
    max_time_sec = stats['max_time'] * 3600
    
    last_collect = u['last_acad_collect']
    if income_rate == 0 or last_collect == 0:
        # Если это первый запуск, ставим таймер на сейчас
        if last_collect == 0:
             await update_stat(user_id, "last_acad_collect", time.time())
        return 0, ""

    now = time.time()
    elapsed = now - last_collect
    
    # Ограничиваем временем логистики
    effective_time = min(elapsed, max_time_sec)
    
    # Если прошло меньше 1 минуты, не собираем (чтобы не спамить базой)
    if effective_time < 60:
        return 0, ""
        
    # Расчет (доход в час * часы)
    harvest = int(income_rate * (effective_time / 3600))
    
    if harvest > 0:
        await update_stat(user_id, "tomatoes", u['tomatoes'] + harvest)
        await update_stat(user_id, "last_acad_collect", now)
        
        hours_worked = round(effective_time / 3600, 1)
        return harvest, f"🎓 <b>Стипендия:</b> +{harvest} 🍅 (за {hours_worked} ч.)"
        
    return 0, ""

@dp.callback_query(F.data == "santa_shop_open")
async def santa_shop_menu(cb: CallbackQuery):
    u = await get_user(cb.from_user.id)
    mandarins = u['mandarins']
    
    text = (
        f"🎅 <b>ЛАВКА САНТЫ</b>\n"
        f"<i>Обменивай мандарины на ресурсы и карточки!</i>\n\n"
        f"Твой баланс: <b>{format_num(mandarins)} кг</b>\n"
        f"➖➖➖➖➖➖➖➖"
    )
    
    # НОВЫЕ ЦЕНЫ (x5 - x10 от старых)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍅 1 000 Помидоров (50 кг 🍊)", callback_data="santa_buy_tomatoes")],
        [InlineKeyboardButton(text="🥛 500 Молока (50 кг 🍊)", callback_data="santa_buy_milk")],
        [InlineKeyboardButton(text="🧪 5 шт. Химии (100 кг 🍊)", callback_data="santa_buy_fert")],
        [InlineKeyboardButton(text="🃏 Карточка (200 кг 🍊)", callback_data="santa_buy_card")],
        [InlineKeyboardButton(text="⤾ Назад в Склад", callback_data="refresh_inv")]
    ])
    
    await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("santa_buy_"))
async def santa_buy_handler(cb: CallbackQuery):
    item = cb.data.split("_")[2]
    user_id = cb.from_user.id
    u = await get_user(user_id)
    
    price = 0
    reward_msg = ""
    
    # ЛОГИКА НОВЫХ ЦЕН
    if item == "tomatoes":
        price = 50
        if u['mandarins'] >= price:
            await update_stat(user_id, "tomatoes", u['tomatoes'] + 1000)
            reward_msg = "Получено 1000 помидоров!"
            
    elif item == "milk":
        price = 50
        if u['mandarins'] >= price:
            await update_stat(user_id, "milk", u['milk'] + 500)
            reward_msg = "Получено 500 молока!"
            
    elif item == "fert":
        price = 100
        if u['mandarins'] >= price:
            await update_stat(user_id, "fertilizer", u['fertilizer'] + 5)
            reward_msg = "Получено 5 химии!"
            
    elif item == "card":
        price = 1000
        if u['mandarins'] >= price:
            # Выдаем случайную карту
            random_card = random.choice(list(CARDS.keys()))
            card_info = CARDS[random_card]
            card_name = card_info['name']
            
            async with aiosqlite.connect(DB_NAME) as db:
                async with db.execute('SELECT count FROM user_cards WHERE user_id = ? AND card_id = ?', (user_id, random_card)) as c:
                    res = await c.fetchone()
                
                if res:
                    await db.execute('UPDATE user_cards SET count = count + 1 WHERE user_id = ? AND card_id = ?', (user_id, random_card))
                else:
                    await db.execute('INSERT INTO user_cards (user_id, card_id, count) VALUES (?, ?, 1)', (user_id, random_card))
                await db.commit()
            
            reward_msg = f"Выпал рэпер: <b>{card_name}</b>!"

    if price > 0 and u['mandarins'] >= price:
        # Списываем мандарины
        await update_stat(user_id, "mandarins", u['mandarins'] - price)
        await cb.answer(f"✅ {reward_msg}", show_alert=True)
        # Обновляем меню
        await santa_shop_menu(cb)
    else:
        await cb.answer(f"❌ Не хватает мандаринов! Нужно {price} кг", show_alert=True)

# --- ДОБАВЛЕНИЕ "НАЗАД" ---

@dp.message(F.text == "⤾ Назад (Город)")
async def nav_back_to_town(message: types.Message):
    await message.answer("🏡 Вы вернулись на городскую площадь.", reply_markup=town_keyboard())

# --- ОБНОВЛЕНИЕ СТАРЫХ НАВИГАЦИОННЫХ КНОПОК ---

@dp.message(F.text == "⤾ Назад")
async def nav_back(message: types.Message):
    # Если мы в Городе или Развлечениях, возвращаемся в Main
    if message.text == "⤾ Назад" and message.reply_to_message and \
       ("Город" in message.reply_to_message.text or "Развлечения" in message.reply_to_message.text):
        await message.answer("🏡 Вы вернулись на ферму.", reply_markup=main_keyboard())
    else:
        # Для безопасности (всегда возвращаемся в Main)
        await message.answer("🏡 Вы вернулись на ферму.", reply_markup=main_keyboard())

# Callback для возврата в меню участка
@dp.callback_query(F.data == "go_plot_menu")
async def go_to_plot_menu_callback(cb: CallbackQuery, state: FSMContext):
    # Эмулируем нажатие кнопки, чтобы вызвать AFK-сбор и обновить меню
    await nav_plot_menu(cb.message, state) 
    await cb.answer()

# Вставьте этот код где-то ближе к концу файла, ПЕРЕД функцией main()

async def set_menu(bot: Bot):
    # Устанавливаем кнопку "Меню" слева от поля ввода
    await bot.set_my_commands([
        BotCommand(command='/start', description='Главное меню')
    ])

# --- ЗАПУСК ---
async def main():
    await init_db() # Тут пройдут миграции
    
    # --- ЗАГРУЗКА АДМИНОВ ИЗ БД ---
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT username FROM users WHERE is_admin = 1') as c:
            db_admins = await c.fetchall()
            for row in db_admins:
                if row[0] and row[0].lower() not in ADMINS:
                    ADMINS.append(row[0].lower())
    print(f"👮‍♂️ Загружено админов: {len(ADMINS)}")
    # ------------------------------

    await bot.delete_webhook(drop_pending_updates=True)
    await set_menu(bot)
    # Отключаем лишний мусор в логах, чтобы консоль была чистой
    logging.basicConfig(level=logging.ERROR)
    
    print(f"{Fore.GREEN}✅ Бот 🎄 Новогоднее Обновление: Операция Оливье запущен!{Style.RESET_ALL}")
    
    # Запускаем бота и консоль параллельно
    await asyncio.gather(
        dp.start_polling(bot),
        admin_console_loop(bot)
    )

if __name__ == "__main__":

    asyncio.run(main())




