import telebot
from telebot import types
import datetime
import requests
import schedule
import time
import threading
import os
import sqlite3
import logging
from datetime import datetime, timedelta
import traceback
import random
import sys
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from flask import Flask, request
from dotenv import load_dotenv
load_dotenv()  # загружает переменные из .env

# Создаём Flask-приложение
app = Flask(__name__)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# Перехват необработанных исключений
def log_error(exc_type, exc_value, exc_traceback):
    logger.error("Необработанное исключение:", exc_info=(exc_type, exc_value, exc_traceback))


# Устанавливаем обработчик для необработанных исключений
import sys

sys.excepthook = log_error

# Инициализация бота
BOT_TOKEN = os.environ.get('BOT_TOKEN')
try:
    bot = telebot.TeleBot(BOT_TOKEN)
    logger.info("Бот успешно инициализирован")
except Exception as e:
    logger.error(f"Ошибка инициализации бота: {e}")
    raise

# API ключи для сервисов
WEATHER_API_KEYS = os.environ.get('OPENWEATHER_API_KEYS').split(',')
WEATHER_API_KEYS = [key.strip() for key in WEATHER_API_KEYS if key.strip()]

# Настройки базы данных
DB_NAME = "morning_phoenix.db"


# Создание и инициализация базы данных
def init_database():
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        # Создаем таблицу пользователей
        cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    chat_id INTEGER,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                ''')

        # Создаем таблицу настроек
        cursor.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    user_id INTEGER PRIMARY KEY,
                    notification_time TEXT DEFAULT '09:00',
                    weather BOOLEAN DEFAULT 1,
                    social_media BOOLEAN DEFAULT 1,
                    reminders BOOLEAN DEFAULT 1,
                    news BOOLEAN DEFAULT 0,
                    motivation BOOLEAN DEFAULT 0,
                    quotes BOOLEAN DEFAULT 0,
                    self_analysis BOOLEAN DEFAULT 0,
                    horoscope BOOLEAN DEFAULT 0,
                    city TEXT DEFAULT 'Moscow',
                    news_category TEXT DEFAULT 'general',
                    zodiac_sign TEXT DEFAULT 'general',
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
                ''')

        # Создаем таблицу для хранения задач пользователя
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            text TEXT,
            date TEXT,
            is_completed BOOLEAN DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
        ''')

        conn.commit()
        conn.close()
        logger.info("База данных успешно инициализирована")
    except Exception as e:
        logger.error(f"Ошибка инициализации базы данных: {e}")
        raise


def add_missing_columns():
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        # Проверяем наличие колонки zodiac_sign
        cursor.execute("PRAGMA table_info(settings)")
        columns = [column[1] for column in cursor.fetchall()]

        if 'zodiac_sign' not in columns:
            cursor.execute("ALTER TABLE settings ADD COLUMN zodiac_sign TEXT DEFAULT 'general'")
            conn.commit()
            logger.info("Добавлена отсутствующая колонка zodiac_sign в таблицу settings")

        conn.close()
    except Exception as e:
        logger.error(f"Ошибка при добавлении недостающих колонок: {e}")

# Функции для работы с базой данных
def add_user(user_id, chat_id, username, first_name, last_name):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        # Проверяем, существует ли пользователь
        cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()

        if not user:
            # Добавляем пользователя
            cursor.execute(
                "INSERT INTO users (user_id, chat_id, username, first_name, last_name) VALUES (?, ?, ?, ?, ?)",
                (user_id, chat_id, username, first_name, last_name)
            )
            # Добавляем настройки по умолчанию
            cursor.execute(
                "INSERT INTO settings (user_id) VALUES (?)",
                (user_id,)
            )
            conn.commit()
            logger.info(f"Добавлен новый пользователь: {user_id} ({username})")

        conn.close()
        return True
    except sqlite3.Error as e:
        logger.error(f"Ошибка SQLite при добавлении пользователя {user_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"Неизвестная ошибка при добавлении пользователя {user_id}: {e}")
        return False


def get_user_settings(user_id):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM settings WHERE user_id = ?", (user_id,))
        settings_row = cursor.fetchone()

        if not settings_row:
            # Если настройки не найдены, создаем их по умолчанию
            cursor.execute(
                "INSERT INTO settings (user_id) VALUES (?)",
                (user_id,)
            )
            conn.commit()
            cursor.execute("SELECT * FROM settings WHERE user_id = ?", (user_id,))
            settings_row = cursor.fetchone()

        # Получаем имена колонок
        cursor.execute("PRAGMA table_info(settings)")
        columns = [col[1] for col in cursor.fetchall()]

        conn.close()

        # Создаем словарь настроек
        settings = {}
        for i, col in enumerate(columns):
            # Преобразуем булевы значения из SQLite (0/1) в Python (False/True)
            if col in ['weather', 'social_media', 'reminders', 'news', 'motivation', 'quotes', 'self_analysis',
                       'horoscope']:
                settings[col] = bool(settings_row[i])
            else:
                settings[col] = settings_row[i]

        return settings
    except sqlite3.Error as e:
        logger.error(f"Ошибка SQLite при получении настроек пользователя {user_id}: {e}")
        # Возвращаем настройки по умолчанию в случае ошибки
        return {
            'notification_time': '09:00',
            'weather': True,
            'social_media': True,
            'reminders': True,
            'news': False,
            'motivation': False,
            'quotes': False,
            'self_analysis': False,
            'horoscope': False,
            'city': 'Moscow',
            'news_category': 'general'
        }
    except Exception as e:
        logger.error(f"Неизвестная ошибка при получении настроек пользователя {user_id}: {e}")
        # Возвращаем настройки по умолчанию в случае ошибки
        return {
            'notification_time': '09:00',
            'weather': True,
            'social_media': True,
            'reminders': True,
            'news': False,
            'motivation': False,
            'quotes': False,
            'self_analysis': False,
            'horoscope': False,
            'city': 'Moscow',
            'news_category': 'general'
        }


def update_user_setting(user_id, setting_name, setting_value):
    try:
        if setting_name == 'zodiac_sign':
            logger.info(f"Попытка обновления знака зодиака для пользователя {user_id}: {setting_value}")

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        # Проверяем, существует ли колонка
        cursor.execute("PRAGMA table_info(settings)")
        columns = [column[1] for column in cursor.fetchall()]

        if setting_name not in columns:
            logger.error(f"Колонка {setting_name} не существует в таблице settings")
            conn.close()
            return False

        # Проверяем, существует ли пользователь
        cursor.execute("SELECT user_id FROM settings WHERE user_id = ?", (user_id,))
        user_settings = cursor.fetchone()

        result = False  # Инициализируем result здесь

        if user_settings:
            # Обновляем настройку
            query = f"UPDATE settings SET {setting_name} = ? WHERE user_id = ?"
            cursor.execute(query, (setting_value, user_id))
            conn.commit()
            logger.info(f"Обновлена настройка {setting_name}={setting_value} для пользователя {user_id}")
            result = True
        else:
            # Если настроек нет, создаем их
            query = f"INSERT INTO settings (user_id, {setting_name}) VALUES (?, ?)"
            cursor.execute(query, (user_id, setting_value))
            conn.commit()
            logger.info(f"Создана настройка {setting_name}={setting_value} для пользователя {user_id}")
            result = True

        # Проверка после обновления (только если успешно)
        if setting_name == 'zodiac_sign' and result:
            cursor.execute("SELECT zodiac_sign FROM settings WHERE user_id = ?", (user_id,))
            current_value = cursor.fetchone()
            logger.info(f"Проверка сохраненного знака зодиака для пользователя {user_id}: {current_value}")

        conn.close()
        return result
    except sqlite3.Error as e:
        logger.error(f"Ошибка SQLite при обновлении настройки {setting_name} для пользователя {user_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"Неизвестная ошибка при обновлении настройки {setting_name} для пользователя {user_id}: {e}")
        return False


def add_reminder(user_id, text, date):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        cursor.execute(
            "INSERT INTO reminders (user_id, text, date) VALUES (?, ?, ?)",
            (user_id, text, date)
        )

        conn.commit()
        reminder_id = cursor.lastrowid
        conn.close()

        logger.info(f"Добавлено напоминание для пользователя {user_id}: {text} на {date}")
        return reminder_id
    except sqlite3.Error as e:
        logger.error(f"Ошибка SQLite при добавлении напоминания для пользователя {user_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Неизвестная ошибка при добавлении напоминания для пользователя {user_id}: {e}")
        return None


def get_reminders_for_today(user_id):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        today = datetime.now().strftime("%Y-%m-%d")
        cursor.execute(
            "SELECT id, text FROM reminders WHERE user_id = ? AND date = ? AND is_completed = 0",
            (user_id, today)
        )

        reminders = cursor.fetchall()
        conn.close()

        return reminders
    except sqlite3.Error as e:
        logger.error(f"Ошибка SQLite при получении напоминаний для пользователя {user_id}: {e}")
        return []
    except Exception as e:
        logger.error(f"Неизвестная ошибка при получении напоминаний для пользователя {user_id}: {e}")
        return []


def mark_reminder_completed(reminder_id):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        cursor.execute(
            "UPDATE reminders SET is_completed = 1 WHERE id = ?",
            (reminder_id,)
        )

        conn.commit()
        conn.close()

        logger.info(f"Напоминание {reminder_id} отмечено как выполненное")
        return True
    except sqlite3.Error as e:
        logger.error(f"Ошибка SQLite при обновлении статуса напоминания {reminder_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"Неизвестная ошибка при обновлении статуса напоминания {reminder_id}: {e}")
        return False


def get_all_users_for_notification(time_str):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT u.user_id, u.chat_id FROM users u
            JOIN settings s ON u.user_id = s.user_id
            WHERE s.notification_time = ?
        """, (time_str,))

        users = cursor.fetchall()
        conn.close()

        return users
    except sqlite3.Error as e:
        logger.error(f"Ошибка SQLite при получении пользователей для уведомления в {time_str}: {e}")
        return []
    except Exception as e:
        logger.error(f"Неизвестная ошибка при получении пользователей для уведомления в {time_str}: {e}")
        return []


# Глобальная переменная для кэша погоды
weather_cache = {}

# Словарь ID основных городов России
city_ids = {
    "москва": 524901,
    "санкт-петербург": 498817,
    "новосибирск": 1496747,
    "екатеринбург": 1486209,
    "казань": 551487,
    "нижний новгород": 520555,
    "челябинск": 1508291,
    "самара": 499099,
    "омск": 1496153,
    "ростов-на-дону": 501175
}


def get_weather(city="Moscow", is_default_city=False):
    try:
        city_key = city.lower()
        current_time = time.time()

        # Проверяем кэш (кэшируем на 30 минут)
        if city_key in weather_cache and current_time - weather_cache[city_key]['time'] < 1800:
            logger.info(f"Используем кэшированные данные о погоде для города {city}")
            return weather_cache[city_key]['data']

        base_url = "https://api.openweathermap.org/data/2.5/weather"
        params_template = {
            'units': 'metric',
            'lang': 'ru'
        }

        # Определяем параметры: по ID или по названию
        if city_key in city_ids:
            logger.info(f"Используем ID города {city_ids[city_key]} для {city}")
            params_template['id'] = city_ids[city_key]
        else:
            params_template['q'] = city

        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1.0,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)

        # Пробуем все ключи по порядку
        for i, api_key in enumerate(WEATHER_API_KEYS):
            try:
                params = params_template.copy()
                params['appid'] = api_key.strip()

                logger.info(
                    f"Попытка {i + 1}/{len(WEATHER_API_KEYS)}: запрос погоды для '{city}' с ключом {api_key[:5]}...")

                response = session.get(base_url, params=params, timeout=20)
                if response.status_code == 401:
                    logger.warning(f"Ключ {api_key[:5]}... недействителен или превышен лимит. Пробуем следующий.")
                    continue
                if response.status_code == 429:
                    logger.warning(f"Ключ {api_key[:5]}... исчерпал лимит запросов. Пробуем следующий.")
                    continue
                response.raise_for_status()

                # Успешный ответ — обрабатываем
                weather_data = response.json()
                temp = weather_data['main']['temp']
                feels_like = weather_data['main']['feels_like']
                description = weather_data['weather'][0]['description']
                humidity = weather_data['main']['humidity']
                wind_speed = weather_data['wind']['speed']
                weather_id = weather_data['weather'][0]['id']
                city_name = weather_data.get('name', city)

                # Эмодзи
                if weather_id < 300:
                    emoji = "⛈"
                elif weather_id < 400:
                    emoji = "🌧"
                elif weather_id < 600:
                    emoji = "🌦"
                elif weather_id < 700:
                    emoji = "❄️"
                elif weather_id < 800:
                    emoji = "🌫"
                elif weather_id == 800:
                    emoji = "☀️"
                else:
                    emoji = "☁️"

                weather_message = f"{emoji} *Погода в {city_name}:*\n"
                if is_default_city:
                    weather_message += "ℹ️ _Вы не выбрали свой город. Показана погода для Москвы._\n"
                weather_message += (
                    f"• Температура: {round(temp)}°C (ощущается как {round(feels_like)}°C)\n"
                    f"• {description.capitalize()}\n"
                    f"• Влажность: {humidity}%\n"
                    f"• Ветер: {round(wind_speed)} м/с\n"
                )

                # Сохраняем в кэш
                weather_cache[city_key] = {
                    'time': current_time,
                    'data': weather_message
                }

                logger.info(f"Успешно получена погода для {city} с ключом {api_key[:5]}...")
                return weather_message

            except (
            requests.exceptions.Timeout, requests.exceptions.ConnectionError, requests.exceptions.HTTPError) as e:
                logger.warning(f"Ключ {api_key[:5]}... не сработал: {e}. Пробуем следующий.")
                continue  # переходим к следующему ключу

        # Если ни один ключ не сработал
        logger.error(f"Все {len(WEATHER_API_KEYS)} ключей исчерпаны. Невозможно получить погоду для {city}.")
        if city_key in weather_cache:
            fallback = weather_cache[city_key]['data']
            return fallback + "\n⚠️ _Данные устарели — серверы погоды временно недоступны._"
        else:
            return (
                "🌤 *Погода:*\n"
                "Информация временно недоступна.\n"
                "Все API-ключи исчерпаны или серверы OpenWeather недоступны."
            )

    except Exception as e:
        logger.error(f"Критическая ошибка в get_weather: {e}")
        return "🌤 *Погода:*\nПроизошла неизвестная ошибка при загрузке данных."


# Функция получения новостей с обработкой ошибок
def get_news(WHEATER_API, lang="ru", max_articles=1):
    try:
        base_url = "https://gnews.io/api/v4/top-headlines"
        params = {
            'lang': lang,
            'max': max_articles,
            'apikey': api_key
        }
        response = requests.get(base_url, params=params, timeout=10)
        response.raise_for_status()
        news_data = response.json()

        if not news_data.get('articles'):
            logger.warning("GNews: Нет новостей")
            return "📰 Нет доступных новостей на данный момент."

        article = news_data['articles'][0]
        title = article.get('title', 'Без заголовка')
        description = article.get('description', 'Нет описания')[:150] + "..."
        url = article.get('url', '#')
        source = article.get('source', {}).get('name', 'Источник')

        return (
            f"📰 *Главные новости:*\n"
            f"*{title}*\n"
            f"{description}\n"
            f"Источник: {source}\n"
            f"[Подробнее]({url})"
        )

    except Exception as e:
        logger.error(f"Ошибка GNews: {e}")
        return "📰 Не удалось загрузить новости."


# Функция для получения мотивационной цитаты
def get_motivation_quote():
    try:
        with open('data/motivation.txt', 'r', encoding='utf-8') as f:
            quotes = [line.strip() for line in f if line.strip()]
        if not quotes:
            return "💫 *Мотивация дня:*\n_Верь в свои силы, и ты преодолеешь любые трудности!_"
        quote = random.choice(quotes)
        return f"💫 *Мотивация дня:*\n_{quote}_"
    except Exception as e:
        logger.error(f"Ошибка при чтении мотиваций: {e}")
        return "💫 *Мотивация дня:*\n_Верь в свои силы, и ты преодолеешь любые трудности!_"


def get_quote():
    try:
        with open('data/quotes.txt', 'r', encoding='utf-8') as f:
            quotes = [line.strip() for line in f if line.strip()]
        if not quotes:
            return "💬 *Цитата дня:*\n_Величайшая слава не в том, чтобы никогда не падать, а в том, чтобы подниматься каждый раз, когда падаешь._"
        quote = random.choice(quotes)
        return f"💬 *Цитата дня:*\n_{quote}_"
    except Exception as e:
        logger.error(f"Ошибка при чтении цитат: {e}")
        return "💬 *Цитата дня:*\n_Величайшая слава не в том, чтобы никогда не падать, а в том, чтобы подниматься каждый раз, когда падаешь._"


# Функция для получения вопроса для самоанализа
def get_self_analysis_question():
    try:
        with open('data/self_analysis.txt', 'r', encoding='utf-8') as f:
            questions = [line.strip() for line in f if line.strip()]
        if not questions:
            return "🔍 *Вопрос для размышления:*\n_Что самое важное для тебя сегодня?_"
        question = random.choice(questions)
        return f"🔍 *Вопрос для размышления:*\n_{question}_"
    except Exception as e:
        logger.error(f"Ошибка при чтении вопросов: {e}")
        return "🔍 *Вопрос для размышления:*\n_Что самое важное для тебя сегодня?_"


# Функция для получения гороскопа
def get_horoscope(sign="general"):
    try:
        logger.info(f"Запрошен гороскоп для знака: {sign}")
        horoscopes = {}
        with open('data/horoscope.txt', 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and ':' in line:
                    key, value = line.split(':', 1)
                    horoscopes[key.strip().lower()] = [v.strip() for v in value.split('||') if v.strip()]

        sign = sign.lower()
        if sign in horoscopes:
            variants = horoscopes[sign]
            chosen = random.choice(variants)
            logger.info(f"Выбран гороскоп для '{sign}': {chosen[:50]}...")

            zodiac_symbol = {
                "овен": "♈", "телец": "♉", "близнецы": "♊",
                "рак": "♋", "лев": "♌", "дева": "♍",
                "весы": "♎", "скорпион": "♏", "стрелец": "♐",
                "козерог": "♑", "водолей": "♒", "рыбы": "♓",
                "general": "♈"
            }.get(sign, "♈")
            return f"{zodiac_symbol} *Гороскоп ({sign.capitalize()}):*\n_{chosen}_"
        else:
            logger.warning(f"Знак '{sign}' не найден, используется 'general'")
            default = random.choice(horoscopes.get('general', ["Звёзды сегодня на вашей стороне!"]))
            return f"♈ *Гороскоп:*\n_{default}_"

    except Exception as e:
        logger.error(f"Ошибка при получении гороскопа: {e}")
        return "♈ *Гороскоп:*\n_Звёзды сегодня благоволят вам! Используйте этот день с максимальной пользой._"


# Функция для генерации утреннего сообщения
def generate_morning_message(user_id, settings=None):
    try:
        if settings is None:
            settings = get_user_settings(user_id)

        # Отладочный вывод
        zodiac_sign = settings.get('zodiac_sign', 'general')
        logger.info(f"Пользователь {user_id}, используется знак зодиака: {zodiac_sign}")

        # Приветствия в зависимости от времени суток
        current_hour = datetime.now().hour
        if 4 <= current_hour < 12:
            greeting = "☀️ Доброе утро!"
        elif 12 <= current_hour < 18:
            greeting = "🌤 Добрый день!"
        elif 18 <= current_hour < 22:
            greeting = "🌆 Добрый вечер!"
        else:
            greeting = "🌙 Доброй ночи!"

        message_parts = [greeting + "\n"]

        # Дата и день недели
        weekdays = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
        today = datetime.now()
        weekday = weekdays[today.weekday()]
        message_parts.append(f"Сегодня {today.strftime('%d.%m.%Y')}, {weekday}.\n")

        # Погода
        if settings.get('weather', True):
            city = settings.get('city', 'Moscow')
            message_parts.append(get_weather(city))

        # Напоминания
        if settings.get('reminders', True):
            reminders = get_reminders_for_today(user_id)
            if reminders:
                message_parts.append("📝 *Ваши задачи на сегодня:*")
                for reminder_id, text in reminders:
                    message_parts.append(f"• {text}")
                message_parts.append("")

        # Новости
        if settings.get('news', False):
            message_parts.append(get_news() + "\n")

        # Мотивация
        if settings.get('motivation', False):
            message_parts.append(get_motivation_quote() + "\n")

        # Цитата
        if settings.get('quotes', False):
            message_parts.append(get_quote() + "\n")

        # Вопрос для самоанализа
        if settings.get('self_analysis', False):
            message_parts.append(get_self_analysis_question() + "\n")

        # Гороскоп
        if settings.get('horoscope', False):
            zodiac_sign = settings.get('zodiac_sign', 'general')
            logger.info(f"Получение гороскопа для знака: {zodiac_sign}")
            message_parts.append(get_horoscope(zodiac_sign) + "\n")

        # Пожелание хорошего дня
        wishes = [
            "Пусть этот день принесет вам радость и успех! ✨",
            "Желаю продуктивного и счастливого дня! 🚀",
            "Удачи во всех начинаниях сегодня! 🍀",
            "Пусть все задуманное сегодня осуществится! 🌟",
            "Хорошего настроения и успехов в течение дня! 🌈"
        ]
        message_parts.append(wishes[random.randint(0, len(wishes) - 1)])

        return "\n".join(message_parts)
    except Exception as e:
        logger.error(f"Ошибка при генерации утреннего сообщения для пользователя {user_id}: {e}")
        return "🌅 Доброе утро!\n\nК сожалению, произошла ошибка при генерации вашего утреннего сообщения. Мы работаем над её исправлением."


# Обработчик команды /start
@bot.message_handler(commands=['start'])
def send_welcome(message):
    try:
        user_id = message.from_user.id
        chat_id = message.chat.id
        username = message.from_user.username
        first_name = message.from_user.first_name
        last_name = message.from_user.last_name

        # Добавляем или обновляем пользователя в базе данных
        add_user(user_id, chat_id, username, first_name, last_name)

        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        item1 = types.KeyboardButton("⚙️ Настройки")
        item2 = types.KeyboardButton("📝 Мои напоминания")
        item3 = types.KeyboardButton("⏰ Установить время")
        item4 = types.KeyboardButton("🌆 Установить город")
        item5 = types.KeyboardButton("🔍 Тестовое сообщение")
        markup.add(item1, item2)
        markup.add(item3, item4)
        markup.add(item5)

        bot.send_message(
            message.chat.id,
            "Привет! Я твой утренний помощник Феникс. Я буду присылать тебе важную информацию каждое утро.",
            reply_markup=markup
        )
        logger.info(f"Пользователь {user_id} ({username}) запустил бота")
    except Exception as e:
        logger.error(f"Ошибка в обработчике /start: {e}")
        bot.send_message(
            message.chat.id,
            "😔 Произошла ошибка при запуске бота. Пожалуйста, попробуйте позже или обратитесь к администратору."
        )


@bot.message_handler(commands=['help'])
def send_help(message):
    try:
        bot.send_message(
            message.chat.id,
            "🌟 *Утренний Феникс - Помощь*\n\n"
            "Я создан, чтобы облегчить твоё утро, предоставляя всю необходимую информацию в одном сообщении.\n\n"
            "*Основные команды:*\n"
            "/start - Запустить бота и начать настройку\n"
            "/settings - Настроить контент утреннего сообщения\n"
            "/time - Изменить время отправки сообщения\n"
            "/city - Изменить город для прогноза погоды\n"
            "/test - Получить тестовое утреннее сообщение\n"
            "/reminders - Управление напоминаниями\n"
            "/help - Показать эту справку\n\n"
            "Используй кнопки в меню для быстрой навигации по функциям.",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка в обработчике /help: {e}")
        bot.send_message(
            message.chat.id,
            "😔 Произошла ошибка при отправке справки. Пожалуйста, попробуйте позже."
        )


@bot.message_handler(commands=['settings'])
def settings_command(message):
    try:
        settings_menu(message)
    except Exception as e:
        logger.error(f"Ошибка в обработчике /settings: {e}")
        bot.send_message(
            message.chat.id,
            "😔 Произошла ошибка при открытии настроек. Пожалуйста, попробуйте позже."
        )


@bot.message_handler(commands=['test'])
def test_command(message):
    try:
        send_test_message(message)
    except Exception as e:
        logger.error(f"Ошибка в обработчике /test: {e}")
        bot.send_message(
            message.chat.id,
            "😔 Произошла ошибка при отправке тестового сообщения. Пожалуйста, попробуйте позже."
        )


@bot.message_handler(func=lambda message: message.text == "⚙️ Настройки")
def settings_menu(message):
    try:
        user_id = message.from_user.id
        settings = get_user_settings(user_id)

        markup = types.InlineKeyboardMarkup(row_width=2)

        # Кнопки для основных функций
        weather = types.InlineKeyboardButton(
            f"🌤 Погода {'✅' if settings['weather'] else '❌'}",
            callback_data="toggle_weather"
        )
        social = types.InlineKeyboardButton(
            f"📱 Соцсети {'✅' if settings['social_media'] else '❌'}",
            callback_data="toggle_social"
        )
        reminders = types.InlineKeyboardButton(
            f"📝 Напоминания {'✅' if settings['reminders'] else '❌'}",
            callback_data="toggle_reminders"
        )
        news = types.InlineKeyboardButton(
            f"📰 Новости {'✅' if settings['news'] else '❌'}",
            callback_data="toggle_news"
        )

        # Кнопки для дополнительных функций
        motivation = types.InlineKeyboardButton(
            f"💫 Мотивация {'✅' if settings['motivation'] else '❌'}",
            callback_data="toggle_motivation"
        )
        quotes = types.InlineKeyboardButton(
            f"💬 Цитаты {'✅' if settings['quotes'] else '❌'}",
            callback_data="toggle_quotes"
        )
        self_analysis = types.InlineKeyboardButton(
            f"🔍 Вопрос дня {'✅' if settings['self_analysis'] else '❌'}",
            callback_data="toggle_self_analysis"
        )
        horoscope = types.InlineKeyboardButton(
            f"♈ Гороскоп {'✅' if settings['horoscope'] else '❌'}",
            callback_data="toggle_horoscope"
        )

        markup.add(weather, social)
        markup.add(reminders, news)
        markup.add(motivation, quotes)
        markup.add(self_analysis, horoscope)

        bot.send_message(
            message.chat.id,
            "⚙️ *Настройки содержания утреннего сообщения*\n\n"
            "Выберите, какую информацию включить в вашу утреннюю сводку:",
            reply_markup=markup,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка при открытии меню настроек: {e}")
        bot.send_message(
            message.chat.id,
            "😔 Произошла ошибка при открытии настроек. Пожалуйста, попробуйте позже."
        )


@bot.callback_query_handler(func=lambda call: call.data.startswith("toggle_"))
def toggle_settings(call):
    try:
        user_id = call.from_user.id
        callback_data = call.data

        # Исправление обработки параметра feature
        if callback_data == "toggle_self_analysis":
            feature = "self_analysis"
        elif callback_data == "toggle_social":
            feature = "social_media"
        elif callback_data == "toggle_quotes":
            feature = "quotes"
        else:
            feature = callback_data.split("_")[1]

        # Получаем текущие настройки
        settings = get_user_settings(user_id)

        # Переключаем значение
        new_value = not settings.get(feature, False)

        # Обновляем настройки в БД
        update_user_setting(user_id, feature, new_value)

        # Получаем обновленные настройки для обновления UI
        settings = get_user_settings(user_id)

        # Инициализация markup - добавьте эту строку
        markup = types.InlineKeyboardMarkup(row_width=2)

        # Если пользователь включил гороскоп, запрашиваем знак зодиака
        if feature == "horoscope" and new_value:
            # Сначала отвечаем на callback, чтобы не было таймаута
            bot.answer_callback_query(call.id, "Функция 'Гороскоп' включена!")

            # Создаем клавиатуру с знаками зодиака
            markup = types.InlineKeyboardMarkup(row_width=3)
            zodiac_signs = [
                ("♈ Овен", "zodiac_aries"),
                ("♉ Телец", "zodiac_taurus"),
                ("♊ Близнецы", "zodiac_gemini"),
                ("♋ Рак", "zodiac_cancer"),
                ("♌ Лев", "zodiac_leo"),
                ("♍ Дева", "zodiac_virgo"),
                ("♎ Весы", "zodiac_libra"),
                ("♏ Скорпион", "zodiac_scorpio"),
                ("♐ Стрелец", "zodiac_sagittarius"),
                ("♑ Козерог", "zodiac_capricorn"),
                ("♒ Водолей", "zodiac_aquarius"),
                ("♓ Рыбы", "zodiac_pisces")
            ]

            buttons = [types.InlineKeyboardButton(text, callback_data=data)
                       for text, data in zodiac_signs]
            markup.add(*buttons)

            # Отправляем сообщение с выбором знака зодиака
            bot.send_message(
                call.message.chat.id,
                "♈ *Выберите ваш знак зодиака для персонализированного гороскопа:*",
                reply_markup=markup,
                parse_mode="Markdown"
            )

            # Возвращаемся, чтобы не продолжать обновление сообщения с настройками
            return

        weather = types.InlineKeyboardButton(
            f"🌤 Погода {'✅' if settings.get('weather', False) else '❌'}",
            callback_data="toggle_weather"
        )
        social = types.InlineKeyboardButton(
            f"📱 Соцсети {'✅' if settings.get('social_media', False) else '❌'}",
            callback_data="toggle_social"
        )
        reminders = types.InlineKeyboardButton(
            f"📝 Напоминания {'✅' if settings.get('reminders', False) else '❌'}",
            callback_data="toggle_reminders"
        )
        news = types.InlineKeyboardButton(
            f"📰 Новости {'✅' if settings.get('news', False) else '❌'}",
            callback_data="toggle_news"
        )
        motivation = types.InlineKeyboardButton(
            f"💫 Мотивация {'✅' if settings.get('motivation', False) else '❌'}",
            callback_data="toggle_motivation"
        )
        quotes = types.InlineKeyboardButton(
            f"💬 Цитаты {'✅' if settings.get('quotes', False) else '❌'}",
            callback_data="toggle_quotes"
        )
        self_analysis = types.InlineKeyboardButton(
            f"🔍 Вопрос дня {'✅' if settings.get('self_analysis', False) else '❌'}",
            callback_data="toggle_self_analysis"
        )
        horoscope = types.InlineKeyboardButton(
            f"♈ Гороскоп {'✅' if settings.get('horoscope', False) else '❌'}",
            callback_data="toggle_horoscope"
        )

        markup.add(weather, social)
        markup.add(reminders, news)
        markup.add(motivation, quotes)
        markup.add(self_analysis, horoscope)

        # Используйте try/except для обработки ошибки неизмененного сообщения
        try:
            bot.edit_message_reply_markup(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                reply_markup=markup
            )
        except telebot.apihelper.ApiTelegramException as e:
            if "message is not modified" not in str(e).lower():
                raise  # если ошибка не связана с неизмененным сообщением, пробросим ее дальше

        status = "включена" if new_value else "отключена"
        readable_feature = {
            "weather": "Погода",
            "social_media": "Соцсети",
            "reminders": "Напоминания",
            "news": "Новости",
            "motivation": "Мотивация",
            "quotes": "Цитаты",
            "self_analysis": "Вопрос дня",
            "horoscope": "Гороскоп"
        }.get(feature, feature)

        bot.answer_callback_query(
            call.id,
            f"Функция '{readable_feature}' {status}!"
        )
    except Exception as e:
        logger.error(f"Ошибка при переключении настройки {call.data}: {e}")
        bot.answer_callback_query(
            call.id,
            "😔 Произошла ошибка при изменении настройки. Пожалуйста, попробуйте позже."
        )


@bot.message_handler(func=lambda message: message.text == "⏰ Установить время" or message.text == "/time")
def set_time_menu(message):
    try:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
        times = ["06:00", "07:00", "08:00", "09:00", "10:00", "11:00", "12:00"]
        buttons = [types.KeyboardButton(time) for time in times]
        markup.add(*buttons)

        custom_time = types.KeyboardButton("🕓 Своё время")
        back = types.KeyboardButton("🔙 Назад")
        markup.add(custom_time, back)

        bot.send_message(
            message.chat.id,
            "⏰ *Выберите время для утреннего сообщения*\n\n"
            "В какое время вам удобно получать утреннее сообщение?",
            reply_markup=markup,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка при открытии меню выбора времени: {e}")
        bot.send_message(
            message.chat.id,
            "😔 Произошла ошибка при открытии меню выбора времени. Пожалуйста, попробуйте позже."
        )


@bot.message_handler(func=lambda message: message.text == "🌆 Установить город" or message.text == "/city")
def set_city(message):
    try:
        bot.send_message(
            message.chat.id,
            "🌆 Пожалуйста, введите название города для прогноза погоды:"
        )
        bot.register_next_step_handler(message, process_city_step)
    except Exception as e:
        logger.error(f"Ошибка в обработчике установки города: {e}")
        bot.send_message(
            message.chat.id,
            "😔 Произошла ошибка. Пожалуйста, попробуйте позже."
        )


@bot.callback_query_handler(func=lambda call: call.data.startswith("zodiac_"))
def set_zodiac_sign(call):
    try:
        user_id = call.from_user.id
        zodiac_code = call.data.split("_")[1]

        logger.info(f"Пользователь {user_id} выбрал знак зодиака (код): {zodiac_code}")

        # Преобразование кода знака зодиака в русское название
        zodiac_names = {
            "aries": "овен",
            "taurus": "телец",
            "gemini": "близнецы",
            "cancer": "рак",
            "leo": "лев",
            "virgo": "дева",
            "libra": "весы",
            "scorpio": "скорпион",
            "sagittarius": "стрелец",
            "capricorn": "козерог",
            "aquarius": "водолей",
            "pisces": "рыбы"
        }

        zodiac_sign = zodiac_names.get(zodiac_code, "general")
        logger.info(f"Преобразование кода {zodiac_code} в знак: {zodiac_sign}")

        # Сохраняем знак зодиака в настройках
        success = update_user_setting(user_id, "zodiac_sign", zodiac_sign)

        if not success:
            logger.error(f"Не удалось сохранить знак зодиака {zodiac_sign} для пользователя {user_id}")
            bot.answer_callback_query(call.id, "Ошибка при сохранении знака зодиака")
            return

        # Отображаем тестовый гороскоп
        test_horoscope = get_horoscope(zodiac_sign)

        # Отвечаем пользователю
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"✅ Ваш знак зодиака установлен: *{zodiac_sign.capitalize()}*\n\nВот пример вашего ежедневного гороскопа:\n\n{test_horoscope}",
            parse_mode="Markdown"
        )

        logger.info(f"Пользователь {user_id} успешно установил знак зодиака: {zodiac_sign}")

    except Exception as e:
        logger.error(f"Ошибка при установке знака зодиака: {e}")
        bot.answer_callback_query(
            call.id,
            "😔 Произошла ошибка при установке знака зодиака. Пожалуйста, попробуйте позже."
        )


@bot.message_handler(commands=['zodiac'])
def change_zodiac_sign(message):
    try:
        markup = types.InlineKeyboardMarkup(row_width=3)
        zodiac_signs = [
            ("♈ Овен", "zodiac_aries"),
            ("♉ Телец", "zodiac_taurus"),
            ("♊ Близнецы", "zodiac_gemini"),
            ("♋ Рак", "zodiac_cancer"),
            ("♌ Лев", "zodiac_leo"),
            ("♍ Дева", "zodiac_virgo"),
            ("♎ Весы", "zodiac_libra"),
            ("♏ Скорпион", "zodiac_scorpio"),
            ("♐ Стрелец", "zodiac_sagittarius"),
            ("♑ Козерог", "zodiac_capricorn"),
            ("♒ Водолей", "zodiac_aquarius"),
            ("♓ Рыбы", "zodiac_pisces")
        ]

        buttons = [types.InlineKeyboardButton(text, callback_data=data)
                   for text, data in zodiac_signs]
        markup.add(*buttons)

        bot.send_message(
            message.chat.id,
            "♈ *Выберите ваш знак зодиака для персонализированного гороскопа:*",
            reply_markup=markup,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка при открытии меню выбора знака зодиака: {e}")
        bot.send_message(
            message.chat.id,
            "😔 Произошла ошибка. Пожалуйста, попробуйте позже."
        )


def user_has_set_city(user_id):
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        # Проверяем, была ли настройка города изменена после регистрации
        cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='user_actions' LIMIT 1"
        )
        table_exists = cursor.fetchone()

        if not table_exists:
            # Если таблицы отслеживания действий нет, считаем что город по умолчанию
            conn.close()
            return False

        # Проверяем, есть ли запись об установке города
        cursor.execute(
            "SELECT 1 FROM user_actions WHERE user_id = ? AND action = 'set_city' LIMIT 1",
            (user_id,)
        )
        has_set_city = cursor.fetchone() is not None

        conn.close()
        return has_set_city
    except Exception as e:
        logger.error(f"Ошибка при проверке настройки города пользователя {user_id}: {e}")
        # В случае ошибки предполагаем, что город не был установлен
        return False


def process_city_step(message):
    try:
        city = message.text.strip()
        user_id = message.from_user.id

        # Проверяем, не пустой ли ввод
        if not city:
            bot.send_message(
                message.chat.id,
                "❌ Название города не может быть пустым. Пожалуйста, введите название города."
            )
            bot.register_next_step_handler(message, process_city_step)
            return

        # Проверяем валидность города через API погоды
        test_weather = get_weather(city)
        if "❌" in test_weather:
            bot.send_message(
                message.chat.id,
                f"❌ Не удалось найти погоду для города '{city}'. Пожалуйста, проверьте название и попробуйте снова."
            )
            bot.register_next_step_handler(message, process_city_step)
            return

        # Сохраняем город в базе данных
        success = update_user_setting(user_id, 'city', city)

        if not success:
            bot.send_message(
                message.chat.id,
                "❌ Произошла ошибка при сохранении города. Пожалуйста, попробуйте позже."
            )
            return

        # Отмечаем, что пользователь установил город
        try:
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()

            # Создаем таблицу для отслеживания действий, если её нет
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    action TEXT,
                    value TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
                ''')

            # Удаляем предыдущие записи установки города, если они есть
            cursor.execute(
                "DELETE FROM user_actions WHERE user_id = ? AND action = 'set_city'",
                (user_id,)
            )

            # Добавляем новую запись о действии установки города
            cursor.execute(
                "INSERT INTO user_actions (user_id, action, value) VALUES (?, ?, ?)",
                (user_id, 'set_city', city)
            )

            conn.commit()
            conn.close()
            logger.info(f"Пользователь {user_id} установил город: {city}")
        except Exception as e:
            # Только логируем ошибку, но не прерываем процесс
            logger.error(f"Ошибка при записи действия установки города для пользователя {user_id}: {e}")

        # Подготавливаем клавиатуру для возврата в главное меню
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        item1 = types.KeyboardButton("⚙️ Настройки")
        item2 = types.KeyboardButton("📝 Мои напоминания")
        item3 = types.KeyboardButton("⏰ Установить время")
        item4 = types.KeyboardButton("🌆 Установить город")
        item5 = types.KeyboardButton("🔍 Тестовое сообщение")
        markup.add(item1, item2)
        markup.add(item3, item4)
        markup.add(item5)

        # Получаем актуальную погоду для демонстрации
        current_weather = get_weather(city)

        # Отправляем пользователю подтверждение и текущую погоду
        bot.send_message(
            message.chat.id,
            f"✅ Город успешно установлен: *{city}*\n\n"
            f"Вот текущая погода в вашем городе:\n\n"
            f"{current_weather}",
            parse_mode="Markdown",
            reply_markup=markup
        )
    except Exception as e:
        logger.error(f"Ошибка при обработке ввода города: {e}")
        bot.send_message(
            message.chat.id,
            "😔 Произошла ошибка при установке города. Пожалуйста, попробуйте позже."
        )

        # Возвращаем пользователя в главное меню в случае ошибки
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        item1 = types.KeyboardButton("⚙️ Настройки")
        item2 = types.KeyboardButton("📝 Мои напоминания")
        item3 = types.KeyboardButton("⏰ Установить время")
        item4 = types.KeyboardButton("🌆 Установить город")
        item5 = types.KeyboardButton("🔍 Тестовое сообщение")
        markup.add(item1, item2)
        markup.add(item3, item4)
        markup.add(item5)

        bot.send_message(
            message.chat.id,
            "Вернуться в главное меню?",
            reply_markup=markup
        )


@bot.message_handler(
    func=lambda message: message.text in ["06:00", "07:00", "08:00", "09:00", "10:00", "11:00", "12:00"])
def set_predefined_time(message):
    try:
        time_str = message.text
        user_id = message.from_user.id

        update_user_setting(user_id, 'notification_time', time_str)

        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        item1 = types.KeyboardButton("⚙️ Настройки")
        item2 = types.KeyboardButton("📝 Мои напоминания")
        item3 = types.KeyboardButton("⏰ Установить время")
        item4 = types.KeyboardButton("🌆 Установить город")
        item5 = types.KeyboardButton("🔍 Тестовое сообщение")
        markup.add(item1, item2)
        markup.add(item3, item4)
        markup.add(item5)

        bot.send_message(
            message.chat.id,
            f"✅ Время установлено на {time_str}. Ваше утреннее сообщение будет приходить в это время.",
            reply_markup=markup
        )
    except Exception as e:
        logger.error(f"Ошибка при установке предопределенного времени: {e}")
        bot.send_message(
            message.chat.id,
            "😔 Произошла ошибка при установке времени. Пожалуйста, попробуйте позже."
        )


@bot.message_handler(func=lambda message: message.text == "🕓 Своё время")
def set_custom_time(message):
    try:
        bot.send_message(
            message.chat.id,
            "⏰ Пожалуйста, введите удобное для вас время в формате ЧЧ:ММ (например, 07:30)"
        )
        bot.register_next_step_handler(message, process_custom_time)
    except Exception as e:
        logger.error(f"Ошибка при запросе пользовательского времени: {e}")
        bot.send_message(
            message.chat.id,
            "😔 Произошла ошибка. Пожалуйста, попробуйте позже."
        )


def process_custom_time(message):
    try:
        time_str = message.text.strip()
        # Проверка формата времени
        datetime.strptime(time_str, "%H:%M")

        user_id = message.from_user.id
        update_user_setting(user_id, 'notification_time', time_str)

        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        item1 = types.KeyboardButton("⚙️ Настройки")
        item2 = types.KeyboardButton("📝 Мои напоминания")
        item3 = types.KeyboardButton("⏰ Установить время")
        item4 = types.KeyboardButton("🌆 Установить город")
        item5 = types.KeyboardButton("🔍 Тестовое сообщение")
        markup.add(item1, item2)
        markup.add(item3, item4)
        markup.add(item5)

        bot.send_message(
            message.chat.id,
            f"✅ Время установлено на {time_str}. Ваше утреннее сообщение будет приходить в это время.",
            reply_markup=markup
        )
    except ValueError:
        bot.send_message(
            message.chat.id,
            "❌ Некорректный формат времени. Пожалуйста, используйте формат ЧЧ:ММ (например, 07:30)"
        )
    except Exception as e:
        logger.error(f"Ошибка при обработке пользовательского времени: {e}")
        bot.send_message(
            message.chat.id,
            "😔 Произошла ошибка при установке времени. Пожалуйста, попробуйте позже."
        )


@bot.message_handler(func=lambda message: message.text == "🔙 Назад")
def return_to_main_menu(message):
    try:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        item1 = types.KeyboardButton("⚙️ Настройки")
        item2 = types.KeyboardButton("📝 Мои напоминания")
        item3 = types.KeyboardButton("⏰ Установить время")
        item4 = types.KeyboardButton("🌆 Установить город")
        item5 = types.KeyboardButton("🔍 Тестовое сообщение")
        markup.add(item1, item2)
        markup.add(item3, item4)
        markup.add(item5)

        bot.send_message(
            message.chat.id,
            "Вы вернулись в главное меню.",
            reply_markup=markup
        )
    except Exception as e:
        logger.error(f"Ошибка при возврате в главное меню: {e}")
        bot.send_message(
            message.chat.id,
            "😔 Произошла ошибка. Пожалуйста, попробуйте позже."
        )


@bot.message_handler(func=lambda message: message.text == "📝 Мои напоминания" or message.text == "/reminders")
def show_reminders(message):
    try:
        user_id = message.from_user.id
        reminders = get_reminders_for_today(user_id)

        markup = types.InlineKeyboardMarkup(row_width=1)
        add_reminder_btn = types.InlineKeyboardButton("➕ Добавить напоминание", callback_data="add_reminder")
        markup.add(add_reminder_btn)

        if not reminders:
            bot.send_message(
                message.chat.id,
                "📝 *Ваши напоминания на сегодня*\n\n"
                "У вас нет активных напоминаний на сегодня. Нажмите кнопку ниже, чтобы добавить новое.",
                reply_markup=markup,
                parse_mode="Markdown"
            )
        else:
            message_text = "📝 *Ваши напоминания на сегодня:*\n\n"
            for reminder_id, text in reminders:
                complete_btn = types.InlineKeyboardButton(
                    f"✅ Выполнено: {text[:20]}...",
                    callback_data=f"complete_reminder_{reminder_id}"
                )
                markup.add(complete_btn)

                message_text += f"• {text}\n"

            bot.send_message(
                message.chat.id,
                message_text,
                reply_markup=markup,
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Ошибка при отображении напоминаний: {e}")
        bot.send_message(
            message.chat.id,
            "😔 Произошла ошибка при получении напоминаний. Пожалуйста, попробуйте позже."
        )


@bot.callback_query_handler(func=lambda call: call.data == "add_reminder")
def add_reminder_callback(call):
    try:
        bot.send_message(
            call.message.chat.id,
            "📝 Введите текст напоминания:"
        )
        bot.register_next_step_handler(call.message, process_reminder_text)
    except Exception as e:
        logger.error(f"Ошибка при добавлении напоминания: {e}")
        bot.answer_callback_query(call.id, "Произошла ошибка. Попробуйте позже.")


def process_reminder_text(message):
    try:
        user_id = message.from_user.id
        reminder_text = message.text.strip()

        if not reminder_text:
            bot.send_message(
                message.chat.id,
                "❌ Текст напоминания не может быть пустым. Пожалуйста, попробуйте снова."
            )
            return

        # Добавляем напоминание на сегодня
        today = datetime.now().strftime("%Y-%m-%d")
        reminder_id = add_reminder(user_id, reminder_text, today)

        if reminder_id:
            bot.send_message(
                message.chat.id,
                f"✅ Напоминание успешно добавлено на сегодня: {reminder_text}"
            )
        else:
            bot.send_message(
                message.chat.id,
                "❌ Не удалось добавить напоминание. Пожалуйста, попробуйте позже."
            )
    except Exception as e:
        logger.error(f"Ошибка при обработке текста напоминания: {e}")
        bot.send_message(
            message.chat.id,
            "😔 Произошла ошибка при добавлении напоминания. Пожалуйста, попробуйте позже."
        )


@bot.callback_query_handler(func=lambda call: call.data.startswith("complete_reminder_"))
def complete_reminder_callback(call):
    try:
        reminder_id = int(call.data.split('_')[2])

        # Отмечаем напоминание как выполненное
        if mark_reminder_completed(reminder_id):
            bot.answer_callback_query(call.id, "Напоминание отмечено как выполненное! ✅")

            # Обновляем сообщение с напоминаниями
            user_id = call.from_user.id
            reminders = get_reminders_for_today(user_id)

            markup = types.InlineKeyboardMarkup(row_width=1)
            add_reminder_btn = types.InlineKeyboardButton("➕ Добавить напоминание", callback_data="add_reminder")
            markup.add(add_reminder_btn)

            if not reminders:
                bot.edit_message_text(
                    "📝 *Ваши напоминания на сегодня*\n\n"
                    "У вас нет активных напоминаний на сегодня. Нажмите кнопку ниже, чтобы добавить новое.",
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=markup,
                    parse_mode="Markdown"
                )
            else:
                message_text = "📝 *Ваши напоминания на сегодня:*\n\n"
                for r_id, text in reminders:
                    complete_btn = types.InlineKeyboardButton(
                        f"✅ Выполнено: {text[:20]}...",
                        callback_data=f"complete_reminder_{r_id}"
                    )
                    markup.add(complete_btn)

                    message_text += f"• {text}\n"

                bot.edit_message_text(
                    message_text,
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=markup,
                    parse_mode="Markdown"
                )
        else:
            bot.answer_callback_query(call.id, "Не удалось отметить напоминание. Попробуйте позже.")
    except Exception as e:
        logger.error(f"Ошибка при выполнении напоминания: {e}")
        bot.answer_callback_query(call.id, "Произошла ошибка. Попробуйте позже.")


@bot.message_handler(func=lambda message: message.text == "🔍 Тестовое сообщение" or message.text == "/test")
def send_test_message(message):
    try:
        user_id = message.from_user.id
        settings = get_user_settings(user_id)

        message_text = generate_morning_message(user_id, settings)

        bot.send_message(
            message.chat.id,
            message_text,
            parse_mode="Markdown"
        )
        logger.info(f"Отправлено тестовое сообщение пользователю {user_id}")
    except Exception as e:
        logger.error(f"Ошибка при отправке тестового сообщения: {e}")
        bot.send_message(
            message.chat.id,
            "😔 Произошла ошибка при отправке тестового сообщения. Пожалуйста, попробуйте позже."
        )


# Обработчик неизвестных команд
@bot.message_handler(func=lambda message: message.text and message.text.startswith('/'))
def unknown_command(message):
    try:
        bot.send_message(
            message.chat.id,
            "🤔 Неизвестная команда. Используйте /help для получения списка доступных команд."
        )
    except Exception as e:
        logger.error(f"Ошибка при обработке неизвестной команды: {e}")


# Обработчик для прочих сообщений
@bot.message_handler(func=lambda message: True)
def echo_message(message):
    try:
        bot.send_message(
            message.chat.id,
            "👋 Я вас понимаю, но не знаю, как ответить. Используйте кнопки меню или команды для взаимодействия со мной."
        )
    except Exception as e:
        logger.error(f"Ошибка при обработке эхо-сообщения: {e}")


# Функция отправки утренних сообщений
def send_scheduled_messages():
    try:
        current_time = datetime.now().strftime("%H:%M")
        users = get_all_users_for_notification(current_time)

        if not users:
            logger.info(f"Нет пользователей для отправки уведомлений в {current_time}")
            return

        for user_id, chat_id in users:
            try:
                settings = get_user_settings(user_id)
                message_text = generate_morning_message(user_id, settings)

                bot.send_message(
                    chat_id,
                    message_text,
                    parse_mode="Markdown"
                )
                logger.info(f"Отправлено утреннее сообщение пользователю {user_id}")
            except Exception as e:
                logger.error(f"Ошибка при отправке утреннего сообщения пользователю {user_id}: {e}")
    except Exception as e:
        logger.error(f"Ошибка при выполнении запланированных отправок: {e}")


# Функция для планировщика
def schedule_checker():
    while True:
        try:
            schedule.run_pending()
            time.sleep(30)  # Проверка каждые 30 секунд
        except Exception as e:
            logger.error(f"Ошибка в планировщике: {e}")
            time.sleep(60)  # При ошибке подождем дольше


# Инициализация планировщика
def run_scheduler():
    try:
        # Проверка каждую минуту для отправки сообщений
        schedule.every().minute.at(":00").do(send_scheduled_messages)

        schedule_thread = threading.Thread(target=schedule_checker)
        schedule_thread.daemon = True  # Позволяет программе завершиться, когда основной поток завершается
        schedule_thread.start()

        logger.info("Планировщик успешно запущен")
    except Exception as e:
        logger.error(f"Ошибка при запуске планировщика: {e}")


# Webhook endpoint — сюда Telegram будет присылать обновления
@app.route('/' + BOT_TOKEN, methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return 'OK', 200
    else:
        from flask import abort
        abort(403)

# Эндпоинт для установки webhook (вызывается один раз при деплое)
@app.route("/set_webhook")
def set_webhook():
    render_url = os.environ.get("RENDER_EXTERNAL_URL", "https://localhost:10000")
    webhook_url = f"{render_url}/{BOT_TOKEN}"
    result = bot.set_webhook(url=webhook_url)
    return f"Webhook set: {result}, URL: {webhook_url}"

# Убедитесь, что run_scheduler() НЕ содержит бесконечный цикл в основном потоке
# А использует отдельный поток, как в исходном коде:

def run_scheduler():
    try:
        schedule.every().minute.at(":00").do(send_scheduled_messages)
        schedule_thread = threading.Thread(target=schedule_checker, daemon=True)
        schedule_thread.start()
        logger.info("Планировщик успешно запущен")
    except Exception as e:
        logger.error(f"Ошибка при запуске планировщика: {e}")

# Запуск Flask-сервера
if __name__ == "__main__":
    # Инициализация базы данных и планировщика (если нужно)
    init_database()
    add_missing_columns()
    run_scheduler()  # ⚠️ Осторожно: этот цикл может мешать Flask

    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)


if __name__ == "__main__":
    main()