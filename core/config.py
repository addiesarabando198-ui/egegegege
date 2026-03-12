import os
from dotenv import load_dotenv
from typing import Optional, List

load_dotenv()

# Поддержка обоих вариантов переменных токена
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TG_TOKEN")
if not BOT_TOKEN:
    print("!!! ВНИМАНИЕ: Не найден токен бота TELEGRAM_BOT_TOKEN или TG_TOKEN в .env файле или переменной окружения.")
    raise ValueError("Ошибка: Необходим TELEGRAM_BOT_TOKEN или TG_TOKEN в .env файле или переменных окружения")

# ID канала для проверки подписки
# Для публичных каналов используйте @username
# Для приватных каналов используйте числовой ID (например, -1001234567890)
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "@obshestvonapalcah")  # Убедитесь, что канал существует

# Пути к файлам
QUESTIONS_FILE = os.getenv("QUESTIONS_FILE", "data/questions.json")
DATABASE_FILE = os.getenv("DATABASE_FILE", "quiz_async.db")
STORAGE_DATABASE_FILE = os.getenv("STORAGE_DATABASE_FILE", "fsm_storage.db")
REMINDER_INACTIVITY_DAYS = int(os.getenv("REMINDER_INACTIVITY_DAYS", 3))

# Дополнительные пути к БД (для совместимости)
DATABASE_PATH = os.getenv('DATABASE_PATH', DATABASE_FILE)

# Настройки платежей Tinkoff
TINKOFF_TERMINAL_KEY = os.getenv('TINKOFF_TERMINAL_KEY')
TINKOFF_SECRET_KEY = os.getenv('TINKOFF_SECRET_KEY')

# URL для webhook
WEBHOOK_BASE_URL = os.getenv('WEBHOOK_BASE_URL')  # например: https://yourdomain.com
WEBHOOK_PATH = '/payment/webhook'
WEBHOOK_URL = f"{WEBHOOK_BASE_URL}{WEBHOOK_PATH}" if WEBHOOK_BASE_URL else None

# ID чата для уведомлений админу о платежах
PAYMENT_ADMIN_CHAT_ID = os.getenv('PAYMENT_ADMIN_CHAT_ID')

# Список ID администраторов бота (для админских команд)
ADMIN_IDS = [int(id) for id in os.getenv('ADMIN_IDS', '').split(',') if id]

# Режим разработки
DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'

# Настройки для WebApp
WEBAPP_URL = os.getenv('WEBAPP_URL', 'https://yourdomain.com/webapp')

# Предупреждение о настройках платежей
if not all([TINKOFF_TERMINAL_KEY, TINKOFF_SECRET_KEY, WEBHOOK_BASE_URL]):
    print("⚠️  Внимание: Переменные для платежей не настроены. Модуль платежей будет работать в ограниченном режиме.")

# Экспорт всех настроек
__all__ = [
    'BOT_TOKEN',
    'REQUIRED_CHANNEL',
    'QUESTIONS_FILE',
    'DATABASE_FILE',
    'DATABASE_PATH',
    'STORAGE_DATABASE_FILE',
    'REMINDER_INACTIVITY_DAYS',
    'TINKOFF_TERMINAL_KEY',
    'TINKOFF_SECRET_KEY',
    'WEBHOOK_BASE_URL',
    'WEBHOOK_PATH',
    'WEBHOOK_URL',
    'PAYMENT_ADMIN_CHAT_ID',
    'ADMIN_IDS',
    'DEBUG',
    'WEBAPP_URL'
]