import json
import os
import requests
import re
import time
import random

# Настройки
CARDS_FILE = "cards.json"
OUTPUT_DIR = "img_cards"

# Притворяемся обычным браузером (чтобы не забанили)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5"
}

def get_image_url_from_bing(query):
    """Ищет прямую ссылку на картинку через Bing Images"""
    try:
        # q = запрос
        # first=1 = первая картинка
        # adlt=off = без цензуры (иногда нужно для реперов)
        url = "https://www.bing.com/images/search"
        params = {
            "q": query,
            "first": 1,
            "count": 1
        }
        
        response = requests.get(url, headers=HEADERS, params=params, timeout=15)
        
        # Bing прячет ссылки внутри HTML в параметре murl
        # Ищем ссылку на jpg/png/jpeg
        match = re.search(r'murl&quot;:&quot;(http[^&]+?\.(?:jpg|jpeg|png))&quot;', response.text)
        
        if match:
            return match.group(1)
            
    except Exception as e:
        print(f"   ❌ Ошибка поиска: {e}")
    return None

def download_image(url, filename):
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code == 200:
            with open(filename, 'wb') as f:
                f.write(response.content)
            return True
    except Exception as e:
        print(f"   ❌ Ошибка скачивания: {e}")
    return False

def main():
    # 1. Создаем папку
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    # 2. Читаем JSON
    try:
        with open(CARDS_FILE, "r", encoding="utf-8") as f:
            cards = json.load(f)
    except FileNotFoundError:
        print(f"❌ Файл {CARDS_FILE} не найден!")
        return

    print(f"🚀 Начинаю поиск (Умный режим) для {len(cards)} карт...")
    
    count = 0
    for card_id, data in cards.items():
        # БЕРЕМ ПОЛНОЕ ИМЯ ИЗ JSON
        full_name = data['name'] 
        
        # Имя файла берем из конфига или делаем из ID
        img_name = data.get('img', f"{card_id}.jpg")
        file_path = os.path.join(OUTPUT_DIR, img_name)

        # Если файл уже есть - пропускаем
        if os.path.exists(file_path):
            print(f"✅ {full_name} уже есть. Пропуск.")
            continue

        # --- ФОРМИРОВАНИЕ ЗАПРОСА ---
        # Добавляем слова "face portrait photoshoot", чтобы искало лицо
        search_query = f"{full_name} rapper face portrait photoshoot best quality"
        
        print(f"🔍 Ищу: {full_name} (Запрос: '{search_query}')...")
        
        # 1. Ищем ссылку
        img_url = get_image_url_from_bing(search_query)
        
        if img_url:
            # 2. Скачиваем
            if download_image(img_url, file_path):
                print(f"   💾 Сохранено: {img_name}")
                count += 1
            else:
                print(f"   ⚠️ Ссылка найдена, но скачать не удалось.")
        else:
            print(f"   🚫 Картинка не найдена.")

        # Случайная пауза от 1 до 3 секунд (чтобы не забанили)
        time.sleep(random.uniform(1.0, 3.0))

    print(f"\n🏁 Готово! Скачано новых: {count}")

if __name__ == "__main__":
    main()