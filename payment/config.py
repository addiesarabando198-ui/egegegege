# payment/config.py - Упрощенная конфигурация с двумя тарифами
"""Конфигурация модуля оплаты с пробным периодом и полной подпиской."""
import os
import logging
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ==================== TINKOFF SETTINGS ====================
TINKOFF_TERMINAL_KEY = os.getenv('TINKOFF_TERMINAL_KEY')
TINKOFF_SECRET_KEY = os.getenv('TINKOFF_SECRET_KEY')
TINKOFF_API_URL = 'https://securepay.tinkoff.ru/v2/'

# ==================== WEBHOOK SETTINGS ====================
WEBHOOK_BASE_URL = os.getenv('WEBHOOK_BASE_URL', 'https://your-domain.com')
WEBHOOK_PATH = '/payment/webhook'
WEBHOOK_HOST = '0.0.0.0'
WEBHOOK_PORT = 8080
# Используем WEBHOOK_BASE_URL из окружения вместо хардкода
WEBHOOK_URL = f"{WEBHOOK_BASE_URL}{WEBHOOK_PATH}"

# ==================== ADMIN SETTINGS ====================
PAYMENT_ADMIN_CHAT_ID = int(os.getenv('PAYMENT_ADMIN_CHAT_ID', '0'))

# ИСПРАВЛЕНИЕ: Импортируем централизованный DATABASE_FILE из core.config
# вместо переопределения в каждом модуле
try:
    from core.config import DATABASE_FILE
    DATABASE_PATH = DATABASE_FILE  # Алиас для обратной совместимости
except ImportError:
    # Fallback если core.config недоступен
    DATABASE_PATH = os.getenv('DATABASE_FILE', 'quiz_async.db')
    DATABASE_FILE = DATABASE_PATH
    logger.warning("Could not import DATABASE_FILE from core.config, using fallback")

# ==================== SUBSCRIPTION MODE ====================
SUBSCRIPTION_MODE = 'modular'  # Режим работы
FREE_MODULES = ['test_part', 'personal_cabinet', 'teacher_mode']  # Модули ВСЕГДА бесплатны

# Модули с freemium доступом (3 бесплатных AI-проверки в неделю)
FREEMIUM_MODULES = ['task17', 'task18', 'task19', 'task20', 'task21', 'task22', 'task23', 'task24', 'task25']

# ВСЕ платные модули (используется для планов подписки и проверок доступа)
# ВАЖНО: При добавлении новых модулей добавляйте их ТОЛЬКО сюда!
ALL_PAID_MODULES = ['test_part', 'task17', 'task18', 'task19', 'task20', 'task21', 'task22', 'task23', 'task24', 'task25', 'full_exam']

# ==================== CONFIG VALIDATION ====================

class ConfigValidationError(Exception):
    """Исключение при ошибке валидации конфигурации."""
    pass


def validate_config() -> None:
    """
    Проверяет обязательные переменные окружения при старте.

    Raises:
        ConfigValidationError: Если отсутствуют критические параметры
    """
    errors = []
    warnings = []

    # Проверяем КРИТИЧЕСКИЕ параметры Tinkoff
    if not TINKOFF_TERMINAL_KEY:
        errors.append("TINKOFF_TERMINAL_KEY не установлен")
    elif len(TINKOFF_TERMINAL_KEY) < 10:
        warnings.append("TINKOFF_TERMINAL_KEY выглядит подозрительно коротким")

    if not TINKOFF_SECRET_KEY:
        errors.append("TINKOFF_SECRET_KEY не установлен")
    elif len(TINKOFF_SECRET_KEY) < 10:
        warnings.append("TINKOFF_SECRET_KEY выглядит подозрительно коротким")

    # Проверяем WEBHOOK_BASE_URL
    if WEBHOOK_BASE_URL == 'https://your-domain.com':
        errors.append("WEBHOOK_BASE_URL не настроен (используется дефолтное значение)")
    elif not WEBHOOK_BASE_URL.startswith('https://'):
        errors.append("WEBHOOK_BASE_URL должен использовать HTTPS для безопасности")

    # Проверяем PAYMENT_ADMIN_CHAT_ID
    if PAYMENT_ADMIN_CHAT_ID == 0:
        warnings.append("PAYMENT_ADMIN_CHAT_ID не установлен - админ не будет получать алерты о платежах")

    # Проверяем DATABASE_FILE
    if not DATABASE_FILE:
        errors.append("DATABASE_FILE не установлен")

    # Логируем предупреждения
    for warning in warnings:
        logger.warning(f"⚠️  Config warning: {warning}")

    # Если есть ошибки - выбрасываем исключение
    if errors:
        error_msg = "Ошибки конфигурации payment модуля:\n" + "\n".join(f"  ❌ {e}" for e in errors)
        logger.error(error_msg)
        raise ConfigValidationError(error_msg)

    logger.info("✅ Payment config validation passed")


def get_config_status() -> Dict[str, Any]:
    """
    Возвращает статус конфигурации для диагностики.

    Returns:
        Словарь с информацией о конфигурации (без чувствительных данных)
    """
    return {
        'tinkoff_configured': bool(TINKOFF_TERMINAL_KEY and TINKOFF_SECRET_KEY),
        'webhook_configured': WEBHOOK_BASE_URL != 'https://your-domain.com',
        'webhook_https': WEBHOOK_BASE_URL.startswith('https://') if WEBHOOK_BASE_URL else False,
        'admin_alerts_enabled': PAYMENT_ADMIN_CHAT_ID != 0,
        'subscription_mode': SUBSCRIPTION_MODE,
        'database_file': DATABASE_FILE,
        'free_modules': FREE_MODULES,
        'freemium_modules': FREEMIUM_MODULES
    }


# Валидируем конфигурацию при импорте модуля (можно отключить для тестов)
if os.getenv('SKIP_PAYMENT_CONFIG_VALIDATION') != '1':
    try:
        validate_config()
    except ConfigValidationError as e:
        logger.error(f"Payment module configuration error: {e}")
        logger.error("Payment features will be DISABLED. Fix config and restart.")
        # НЕ падаем, чтобы бот мог запуститься без платежей для отладки
        # но логируем критическую ошибку

logger.info(f"Payment module loaded with SUBSCRIPTION_MODE = {SUBSCRIPTION_MODE}")
logger.info(f"Free modules: {FREE_MODULES}")
logger.info(f"Freemium modules: {FREEMIUM_MODULES}")

# ==================== УПРОЩЕННАЯ СИСТЕМА ПОДПИСОК ====================
MODULE_PLANS = {
    # Пробный период
    'trial_7days': {
        'name': '🎁 Пробный период',
        'description': 'Полный доступ на 7 дней за 1 рубль',
        'detailed_description': [
            '• Доступ ко всем заданиям второй части',
            '• ИИ-проверка каждого ответа',
            '• Персональные рекомендации',
            '• Без ограничений на 7 дней'
        ],
        'price_rub': 1,
        'duration_days': 7,
        'modules': ['test_part', 'task17', 'task18', 'task19', 'task20', 'task21', 'task22', 'task23', 'task24', 'task25', 'full_exam'],
        'type': 'trial',
        'features': [
            '✅ Все задания второй части',
            '✅ ИИ-проверка ответов',
            '✅ Полный доступ на неделю',
            '💡 Идеально для знакомства'
        ]
    },
    
    # Полная подписка
    'package_full': {
        'name': '👑 Полная подписка',
        'description': 'Полный доступ ко всем заданиям',
        'price_rub': 249,
        'duration_days': 30,
        'modules': ['test_part', 'task17', 'task18', 'task19', 'task20', 'task21', 'task22', 'task23', 'task24', 'task25', 'full_exam'],
        'type': 'package',
        'features': [
            '✅ Все задания второй части с проверкой ИИ',
            '✅ Задания 17-18 — Анализ текста и понятий',
            '✅ Задание 19 — Примеры и иллюстрации',
            '✅ Задание 20 — Работа с текстом',
            '✅ Задание 22 — Анализ ситуаций',
            '✅ Задание 24 — Сложный план',
            '✅ Задание 25 — Обоснование с примерами',
            '💡 Максимальные баллы на ЕГЭ!'
        ],
        'detailed_description': [
            '• Задания 17-18: Анализируй тексты и объясняй понятия',
            '• Задание 19: Научись подбирать идеальные примеры к любой теории',
            '• Задание 20: Пиши аргументы, которые оценят на максимум',
            '• Задание 22: Анализируй ситуации и отвечай на вопросы как профи',
            '• Задание 24: Составляй планы, которые невозможно завалить',
            '• Задание 25: Обосновывай так, чтобы эксперт поставил 6/6',
            '• ИИ проверяет каждое слово как строгий эксперт ФИПИ',
            '• Смотри эталонные ответы и повторяй успех'
        ]
    },

    # ==================== ПОДПИСКИ ДЛЯ УЧИТЕЛЕЙ ====================
    # Режим учителя АКТИВЕН в production!

    # Бесплатный тариф для учителей - 1 ученик
    'teacher_free': {
        'name': '👨‍🏫 Бесплатный тариф учителя',
        'description': 'Попробуйте режим учителя с одним учеником',
        'price_rub': 0,
        'duration_days': 36500,  # ~100 лет - фактически бессрочно
        'modules': ['test_part', 'task17', 'task18', 'task19', 'task20', 'task21', 'task22', 'task23', 'task24', 'task25', 'full_exam'],
        'type': 'teacher',
        'max_students': 1,
        'features': [
            '✅ 1 ученик бесплатно',
            '✅ Создание домашних заданий',
            '✅ Отслеживание прогресса',
            '✅ Базовая статистика',
            '💡 Идеально для начала'
        ],
        'detailed_description': [
            '• Подключите 1 ученика бесплатно',
            '• Создавайте домашние задания из готовых тем',
            '• Отслеживайте прогресс ученика',
            '• Смотрите статистику по выполненным заданиям',
            '• Попробуйте режим учителя перед оформлением подписки'
        ]
    },

    # Подписка ученика со скидкой от учителя
    'student_with_teacher': {
        'name': '🎓 Подписка ученика',
        'description': 'Специальная цена для учеников от учителя',
        'price_rub': 149,
        'duration_days': 30,
        'modules': ['test_part', 'task17', 'task18', 'task19', 'task20', 'task21', 'task22', 'task23', 'task24', 'task25', 'full_exam'],
        'type': 'student',
        'features': [
            '✅ Все задания с проверкой ИИ',
            '✅ Скидка 100₽ от учителя',
            '✅ Домашние задания от учителя',
            '✅ Отслеживание прогресса',
            '💰 Выгодно: 149₽ вместо 249₽'
        ],
        'detailed_description': [
            '• Полный доступ ко всем заданиям второй части',
            '• Выполнение домашних заданий от учителя',
            '• Учитель видит ваш прогресс и слабые места',
            '• Специальная цена — экономия 100 рублей',
            '• ИИ проверяет каждый ответ как эксперт ЕГЭ'
        ]
    },

    # Пробный период для учителей - 7 дней за 1₽
    'teacher_trial_7days': {
        'name': '🎁 Пробный период для учителя',
        'description': 'Протестируйте все функции за 1 рубль',
        'price_rub': 1,
        'duration_days': 7,
        'modules': ['test_part', 'task17', 'task18', 'task19', 'task20', 'task21', 'task22', 'task23', 'task24', 'task25', 'full_exam'],
        'type': 'teacher',
        'max_students': 3,
        'features': [
            '✅ До 3 учеников',
            '✅ Создание домашних заданий',
            '✅ Отслеживание прогресса',
            '✅ Базовая статистика',
            '✅ 7 дней полного доступа',
            '🎁 Всего 1 рубль!'
        ],
        'detailed_description': [
            '• Протестируйте все возможности режима учителя',
            '• Подключите до 3 учеников по вашему коду',
            '• Создавайте домашние задания из готовых тем',
            '• Отслеживайте прогресс учеников в реальном времени',
            '• 7 дней для оценки функционала',
            '• После окончания триала выберите подходящий тариф'
        ]
    },

    # Учитель Basic - до 10 учеников
    'teacher_basic': {
        'name': '👨‍🏫 Учитель Basic',
        'description': 'Для репетиторов до 10 учеников',
        'price_rub': 249,
        'duration_days': 30,
        'modules': ['test_part', 'task17', 'task18', 'task19', 'task20', 'task21', 'task22', 'task23', 'task24', 'task25', 'full_exam'],
        'type': 'teacher',
        'max_students': 10,
        'features': [
            '✅ До 10 учеников',
            '✅ Создание домашних заданий',
            '✅ Отслеживание прогресса учеников',
            '✅ Базовая статистика',
            '✅ Собственный код для учеников',
            '💡 Для начинающих репетиторов'
        ],
        'detailed_description': [
            '• Подключите до 10 учеников по вашему коду',
            '• Создавайте домашние задания из готовых тем',
            '• Отслеживайте прогресс каждого ученика',
            '• Смотрите статистику по выполненным заданиям',
            '• Ваши ученики получают скидку на подписку',
            '• Полный доступ к тренировочным модулям'
        ]
    },

    # Учитель Standard - до 20 учеников
    'teacher_standard': {
        'name': '👨‍🏫 Учитель Standard',
        'description': 'Для опытных репетиторов до 20 учеников',
        'price_rub': 449,
        'duration_days': 30,
        'modules': ['test_part', 'task17', 'task18', 'task19', 'task20', 'task21', 'task22', 'task23', 'task24', 'task25', 'full_exam'],
        'type': 'teacher',
        'max_students': 20,
        'features': [
            '✅ До 20 учеников',
            '✅ Создание домашних заданий',
            '✅ Детальная аналитика по ученикам',
            '✅ Еженедельный дайджест успехов',
            '✅ Собственный код для учеников',
            '✅ Приоритетная поддержка',
            '💎 Для профессионалов'
        ],
        'detailed_description': [
            '• Подключите до 20 учеников по вашему коду',
            '• Создавайте задания из готовых тем',
            '• Детальная аналитика слабых мест учеников',
            '• Еженедельный отчет о прогрессе',
            '• Ваши ученики получают скидку на подписку',
            '• Полный доступ к тренировочным модулям',
            '• Приоритетная техническая поддержка'
        ]
    },

    # Учитель Premium - безлимит учеников
    'teacher_premium': {
        'name': '👨‍🏫 Учитель Premium',
        'description': 'Безлимитный тариф для школ и курсов',
        'price_rub': 699,
        'duration_days': 30,
        'modules': ['test_part', 'task17', 'task18', 'task19', 'task20', 'task21', 'task22', 'task23', 'task24', 'task25', 'full_exam'],
        'type': 'teacher',
        'max_students': -1,  # Безлимит
        'features': [
            '✅ Безлимит учеников',
            '✅ Создание любых заданий',
            '✅ Продвинутая аналитика',
            '✅ Еженедельный дайджест',
            '✅ Дарить подписки ученикам',
            '✅ Создание промокодов',
            '✅ Приоритетная поддержка',
            '🔥 Для школ и курсов'
        ],
        'detailed_description': [
            '• Неограниченное количество учеников',
            '• Создавайте любые домашние задания',
            '• Продвинутая аналитика и рекомендации',
            '• Еженедельный отчет по всем ученикам',
            '• Дарите подписки лучшим ученикам',
            '• Создавайте промокоды для своих учеников',
            '• Полный доступ к тренировочным модулям',
            '• Приоритетная техническая поддержка'
        ]
    },

    # ==================== ТЕСТОВЫЕ ТАРИФЫ ДЛЯ АДМИНА (1₽) ====================
    # Эти тарифы видны только администраторам для тестирования платежной системы

    # Тестовый пробный период (для проверки, хотя оригинал тоже 1₽)
    'test_trial_7days': {
        'name': '[TEST] 🎁 Пробный период',
        'description': 'Полный доступ на 7 дней за 1 рубль',
        'detailed_description': [
            '• Доступ ко всем заданиям второй части',
            '• ИИ-проверка каждого ответа',
            '• Персональные рекомендации',
            '• Без ограничений на 7 дней'
        ],
        'price_rub': 1,
        'duration_days': 7,
        'modules': ['test_part', 'task17', 'task18', 'task19', 'task20', 'task21', 'task22', 'task23', 'task24', 'task25', 'full_exam'],
        'type': 'trial',
        'is_test': True,
        'features': [
            '✅ Все задания второй части',
            '✅ ИИ-проверка ответов',
            '✅ Полный доступ на неделю',
            '💡 Тестовый тариф для админа'
        ]
    },

    # Тестовая полная подписка
    'test_package_full': {
        'name': '[TEST] 👑 Полная подписка',
        'description': 'Полный доступ ко всем заданиям',
        'price_rub': 1,
        'duration_days': 30,
        'modules': ['test_part', 'task17', 'task18', 'task19', 'task20', 'task21', 'task22', 'task23', 'task24', 'task25', 'full_exam'],
        'type': 'package',
        'is_test': True,
        'features': [
            '✅ Все задания второй части с проверкой ИИ',
            '✅ Задание 19 — Примеры и иллюстрации',
            '✅ Задание 20 — Работа с текстом',
            '✅ Задание 22 — Анализ ситуаций',
            '✅ Задание 24 — Сложный план',
            '✅ Задание 25 — Обоснование с примерами',
            '💡 Тестовый тариф для админа'
        ],
        'detailed_description': [
            '• Задание 19: Научись подбирать идеальные примеры к любой теории',
            '• Задание 20: Пиши аргументы, которые оценят на максимум',
            '• Задание 22: Анализируй ситуации и отвечай на вопросы как профи',
            '• Задание 24: Составляй планы, которые невозможно завалить',
            '• Задание 25: Обосновывай так, чтобы эксперт поставил 6/6',
            '• ИИ проверяет каждое слово как строгий эксперт ФИПИ',
            '• Смотри эталонные ответы и повторяй успех'
        ]
    },

    # Тестовая подписка ученика
    'test_student_with_teacher': {
        'name': '[TEST] 🎓 Подписка ученика',
        'description': 'Специальная цена для учеников от учителя',
        'price_rub': 1,
        'duration_days': 30,
        'modules': ['test_part', 'task17', 'task18', 'task19', 'task20', 'task21', 'task22', 'task23', 'task24', 'task25', 'full_exam'],
        'type': 'student',
        'is_test': True,
        'features': [
            '✅ Все задания с проверкой ИИ',
            '✅ Скидка от учителя',
            '✅ Домашние задания от учителя',
            '✅ Отслеживание прогресса',
            '💡 Тестовый тариф для админа'
        ],
        'detailed_description': [
            '• Полный доступ ко всем заданиям второй части',
            '• Выполнение домашних заданий от учителя',
            '• Учитель видит ваш прогресс и слабые места',
            '• Специальная цена для тестирования',
            '• ИИ проверяет каждый ответ как эксперт ЕГЭ'
        ]
    },

    # Тестовый пробный период учителя
    'test_teacher_trial_7days': {
        'name': '[TEST] 🎁 Пробный период для учителя',
        'description': 'Протестируйте все функции за 1 рубль',
        'price_rub': 1,
        'duration_days': 7,
        'modules': ['test_part', 'task17', 'task18', 'task19', 'task20', 'task21', 'task22', 'task23', 'task24', 'task25', 'full_exam'],
        'type': 'teacher',
        'max_students': 3,
        'is_test': True,
        'features': [
            '✅ До 3 учеников',
            '✅ Создание домашних заданий',
            '✅ Отслеживание прогресса',
            '✅ Базовая статистика',
            '✅ 7 дней полного доступа',
            '💡 Тестовый тариф для админа'
        ],
        'detailed_description': [
            '• Протестируйте все возможности режима учителя',
            '• Подключите до 3 учеников по вашему коду',
            '• Создавайте домашние задания из готовых тем',
            '• Отслеживайте прогресс учеников в реальном времени',
            '• 7 дней для оценки функционала',
            '• После окончания триала выберите подходящий тариф'
        ]
    },

    # Тестовый учитель Basic
    'test_teacher_basic': {
        'name': '[TEST] 👨‍🏫 Учитель Basic',
        'description': 'Для репетиторов до 10 учеников',
        'price_rub': 1,
        'duration_days': 30,
        'modules': ['test_part', 'task17', 'task18', 'task19', 'task20', 'task21', 'task22', 'task23', 'task24', 'task25', 'full_exam'],
        'type': 'teacher',
        'max_students': 10,
        'is_test': True,
        'features': [
            '✅ До 10 учеников',
            '✅ Создание домашних заданий',
            '✅ Отслеживание прогресса учеников',
            '✅ Базовая статистика',
            '✅ Собственный код для учеников',
            '💡 Тестовый тариф для админа'
        ],
        'detailed_description': [
            '• Подключите до 10 учеников по вашему коду',
            '• Создавайте домашние задания из готовых тем',
            '• Отслеживайте прогресс каждого ученика',
            '• Смотрите статистику по выполненным заданиям',
            '• Ваши ученики получают скидку на подписку',
            '• Полный доступ к тренировочным модулям'
        ]
    },

    # Тестовый учитель Standard
    'test_teacher_standard': {
        'name': '[TEST] 👨‍🏫 Учитель Standard',
        'description': 'Для опытных репетиторов до 20 учеников',
        'price_rub': 1,
        'duration_days': 30,
        'modules': ['test_part', 'task17', 'task18', 'task19', 'task20', 'task21', 'task22', 'task23', 'task24', 'task25', 'full_exam'],
        'type': 'teacher',
        'max_students': 20,
        'is_test': True,
        'features': [
            '✅ До 20 учеников',
            '✅ Создание домашних заданий',
            '✅ Детальная аналитика по ученикам',
            '✅ Еженедельный дайджест успехов',
            '✅ Собственный код для учеников',
            '✅ Приоритетная поддержка',
            '💡 Тестовый тариф для админа'
        ],
        'detailed_description': [
            '• Подключите до 20 учеников по вашему коду',
            '• Создавайте задания из готовых тем',
            '• Детальная аналитика слабых мест учеников',
            '• Еженедельный отчет о прогрессе',
            '• Ваши ученики получают скидку на подписку',
            '• Полный доступ к тренировочным модулям',
            '• Приоритетная техническая поддержка'
        ]
    },

    # Тестовый учитель Premium
    'test_teacher_premium': {
        'name': '[TEST] 👨‍🏫 Учитель Premium',
        'description': 'Безлимитный тариф для школ и курсов',
        'price_rub': 1,
        'duration_days': 30,
        'modules': ['test_part', 'task17', 'task18', 'task19', 'task20', 'task21', 'task22', 'task23', 'task24', 'task25', 'full_exam'],
        'type': 'teacher',
        'max_students': -1,  # Безлимит
        'is_test': True,
        'features': [
            '✅ Безлимит учеников',
            '✅ Создание любых заданий',
            '✅ Продвинутая аналитика',
            '✅ Еженедельный дайджест',
            '✅ Дарить подписки ученикам',
            '✅ Создание промокодов',
            '✅ Приоритетная поддержка',
            '💡 Тестовый тариф для админа'
        ],
        'detailed_description': [
            '• Неограниченное количество учеников',
            '• Создавайте любые домашние задания',
            '• Продвинутая аналитика и рекомендации',
            '• Еженедельный отчет по всем ученикам',
            '• Дарите подписки лучшим ученикам',
            '• Создавайте промокоды для своих учеников',
            '• Полный доступ к тренировочным модулям',
            '• Приоритетная техническая поддержка'
        ]
    }
}

# ==================== СКИДКИ ЗА ДЛИТЕЛЬНОСТЬ ====================
# Расчет:
# 1 месяц: 249₽ (без скидки)
# 3 месяца: 672₽ (10% скидка = 224₽/мес, экономия 75₽)
# 6 месяцев: 1270₽ (15% скидка = 212₽/мес, экономия 224₽)

DURATION_DISCOUNTS = {
    1: {
        'multiplier': 1.0,  # Без скидки
        'label': '1 месяц',
        'discount_percent': 0,
        'badge': ''
    },
    3: {
        'multiplier': 2.7,  # 672₽ вместо 747₽ (скидка 10%)
        'label': '3 месяца',
        'discount_percent': 10,
        'badge': '💰 Выгода',
        'savings': 75  # Экономия в рублях
    },
    6: {
        'multiplier': 5.1,  # 1270₽ вместо 1494₽ (скидка 15%)
        'label': '6 месяцев',
        'discount_percent': 15,
        'badge': '🔥 Лучшая цена',
        'savings': 224  # Экономия в рублях
    }
}

# ==================== ВЫБОР АКТИВНОЙ СИСТЕМЫ ====================
SUBSCRIPTION_PLANS = MODULE_PLANS
logger.info(f"Using simplified MODULE_PLANS with {len(MODULE_PLANS)} plans")
logger.info(f"Available plans: {list(SUBSCRIPTION_PLANS.keys())}")

# ==================== ОПИСАНИЯ МОДУЛЕЙ ДЛЯ UI ====================
MODULE_DESCRIPTIONS = {
    'test_part': {
        'emoji': '📝',
        'short_name': 'Тестовая часть',
        'full_name': 'Задания 1-16 (тестовая часть)',
        'description': 'Все задания первой части ЕГЭ с автопроверкой',
        'features': [
            'Более 1000 заданий',
            'Все темы кодификатора',
            'Мгновенная проверка',
            'Подробные объяснения'
        ],
        'is_free': True
    },
    'task17': {
        'emoji': '📖',
        'short_name': 'Задание 17',
        'full_name': 'Задание 17 — Анализ текста',
        'description': 'Находи информацию в тексте и отвечай на вопросы как эксперт',
        'features': [
            'Анализируй обществоведческие тексты',
            'ИИ проверит точность ответов',
            'Учись выделять главное из текста',
            'Получай до 2 баллов на ЕГЭ'
        ],
        'is_free': False
    },
    'task18': {
        'emoji': '📝',
        'short_name': 'Задание 18',
        'full_name': 'Задание 18 — Понятие из текста',
        'description': 'Объясняй понятия из текста и выделяй их признаки',
        'features': [
            'Работай с понятиями из текста',
            'ИИ оценит полноту ответа',
            'Учись формулировать определения',
            'Получай до 2 баллов на ЕГЭ'
        ],
        'is_free': False
    },
    'task19': {
        'emoji': '🎯',
        'short_name': 'Задание 19',
        'full_name': 'Задание 19 — Примеры и иллюстрации',
        'description': 'Научись подбирать убедительные примеры к любой теории',
        'features': [
            'Учись на лучших примерах',
            'ИИ оценит твои примеры',
            'База готовых решений',
            'Рекомендации по улучшению'
        ],
        'is_free': False
    },
    'task20': {
        'emoji': '📖',
        'short_name': 'Задание 20',
        'full_name': 'Задание 20 — Работа с текстом',
        'description': 'Формулируй аргументы, за которые дают максимум баллов',
        'features': [
            'Разбирай тексты как профи',
            'Пиши убедительные суждения',
            'Используй готовые формулировки',
            'ИИ проверит твою логику'
        ],
        'is_free': False
    },
    'task21': {
        'emoji': '📊',
        'short_name': 'Задание 21',
        'full_name': 'Задание 21 — Графики спроса и предложения',
        'description': 'Анализируй графики и определяй изменения на рынках',
        'features': [
            'Разбирай графики спроса и предложения',
            'Определяй факторы изменений',
            'ИИ проверит твой анализ',
            'Получай до 3 баллов на ЕГЭ'
        ],
        'is_free': False
    },
    'task22': {
        'emoji': '📝',
        'short_name': 'Задание 22',
        'full_name': 'Задание 22 — Анализ ситуаций',
        'description': 'Анализируй конкретные ситуации и отвечай на 4 вопроса',
        'features': [
            'Разбирай реальные кейсы',
            'ИИ проверит каждый ответ',
            'Учись применять теорию на практике',
            'Получай до 4 баллов на ЕГЭ'
        ],
        'is_free': False
    },
    'task23': {
        'emoji': '📜',
        'short_name': 'Задание 23',
        'full_name': 'Задание 23 — Конституция РФ',
        'description': 'Изучай Конституцию и определяй функции органов власти',
        'features': [
            'Разбирай статьи Конституции',
            'Определяй полномочия органов',
            'ИИ проверит твои ответы',
            'Получай до 3 баллов на ЕГЭ'
        ],
        'is_free': False
    },
    'task24': {
        'emoji': '💎',
        'short_name': 'Задание 24',
        'full_name': 'Задание 24 — Сложный план',
        'description': 'Составляй планы, которые эксперт не сможет завалить',
        'features': [
            'Структурируй ответы как профи',
            'ИИ проверит каждый пункт',
            'Смотри эталонные планы',
            'Получай оценку как на ЕГЭ'
        ],
        'is_free': False
    },
    'task25': {
        'emoji': '✍️',
        'short_name': 'Задание 25',
        'full_name': 'Задание 25 — Обоснование',
        'description': 'Обосновывай так убедительно, что эксперт поставит 6/6',
        'features': [
            'Подбирай примеры из разных сфер',
            'ИИ оценит твоё обоснование',
            'Конкретизируй точно и чётко',
            'Получай развёрнутую обратную связь'
        ],
        'is_free': False
    },
    'full_exam': {
        'emoji': '📋',
        'short_name': 'Полный вариант',
        'full_name': 'Полный вариант ЕГЭ',
        'description': 'Пройди полный вариант ЕГЭ из 25 заданий с проверкой ИИ',
        'features': [
            '16 заданий тестовой части',
            '9 заданий с развёрнутым ответом (17-25)',
            'ИИ-проверка второй части',
            'Подсчёт первичных и вторичных баллов',
            'Свободная навигация между заданиями'
        ],
        'is_free': False
    }
}

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def get_plan_price_kopecks(plan_id: str, months: int = 1) -> int:
    """
    Возвращает цену плана в копейках для Tinkoff API.
    
    Args:
        plan_id: ID плана (trial_7days или package_full)
        months: Количество месяцев
    
    Returns:
        Цена в копейках
    """
    plan = SUBSCRIPTION_PLANS.get(plan_id)
    if not plan:
        raise ValueError(f"Unknown plan: {plan_id}")
    
    base_price = plan['price_rub']
    
    # Для пробного периода всегда 1₽
    if plan_id == 'trial_7days':
        return 100  # 1₽ в копейках
    
    # Применяем множитель для длительности
    if months in DURATION_DISCOUNTS:
        multiplier = DURATION_DISCOUNTS[months]['multiplier']
        total_price = int(base_price * multiplier)
    else:
        total_price = base_price * months
    
    return total_price * 100  # Конвертируем в копейки


def get_subscription_end_date(plan_id: str, months: int = 1) -> datetime:
    """
    Вычисляет дату окончания подписки для плана.
    
    Args:
        plan_id: ID плана
        months: Количество месяцев
        
    Returns:
        Дата окончания подписки
    """
    plan = SUBSCRIPTION_PLANS.get(plan_id)
    if not plan:
        raise ValueError(f"Unknown plan: {plan_id}")
    
    if plan_id == 'trial_7days':
        return datetime.now(timezone.utc) + timedelta(days=7)
    else:
        days = 30 * months
        return datetime.now(timezone.utc) + timedelta(days=days)


def calculate_subscription_price(plan_id: str, months: int = 1) -> int:
    """
    Рассчитывает цену подписки с учетом срока и скидок.
    
    Args:
        plan_id: ID плана
        months: Количество месяцев
        
    Returns:
        Цена в РУБЛЯХ (не в копейках!)
    """
    plan = SUBSCRIPTION_PLANS.get(plan_id)
    if not plan:
        raise ValueError(f"Unknown plan: {plan_id}")
    
    base_price = plan['price_rub']
    
    # Для пробного периода всегда 1₽
    if plan_id == 'trial_7days':
        return 1
    
    # Применяем скидки для многомесячных подписок
    if months in DURATION_DISCOUNTS:
        multiplier = DURATION_DISCOUNTS[months]['multiplier']
        total_price = int(base_price * multiplier)
    else:
        total_price = base_price * months
    
    return total_price


def get_plan_modules(plan_id: str) -> List[str]:
    """
    Возвращает список модулей для плана.
    
    Args:
        plan_id: ID плана
        
    Returns:
        Список кодов модулей
    """
    plan = SUBSCRIPTION_PLANS.get(plan_id)
    if not plan:
        return []
    
    modules = plan.get('modules', [])
    
    # Добавляем бесплатные модули если их нет
    for free_module in FREE_MODULES:
        if free_module not in modules:
            modules.append(free_module)
    
    return modules


def format_price(price_rub: int) -> str:
    """Форматирует цену для отображения."""
    return f"{price_rub}₽"


def is_module_free(module_code: str) -> bool:
    """Проверяет, является ли модуль бесплатным."""
    return module_code in FREE_MODULES


def get_module_info(module_code: str) -> Dict[str, Any]:
    """
    Возвращает полную информацию о модуле для UI.
    
    Args:
        module_code: Код модуля
        
    Returns:
        Словарь с информацией о модуле
    """
    if module_code in MODULE_DESCRIPTIONS:
        info = MODULE_DESCRIPTIONS[module_code].copy()
        info['price'] = 0 if module_code in FREE_MODULES else None
        return info
    
    # Дефолтная информация
    return {
        'emoji': '📚',
        'short_name': module_code,
        'full_name': module_code,
        'description': 'Модуль',
        'features': [],
        'is_free': module_code in FREE_MODULES,
        'price': 0 if module_code in FREE_MODULES else None
    }


def get_plan_info(plan_id: str) -> Optional[Dict[str, Any]]:
    """
    Возвращает информацию о плане подписки.

    Args:
        plan_id: ID плана

    Returns:
        Словарь с информацией о плане или None
    """
    return SUBSCRIPTION_PLANS.get(plan_id)


def is_teacher_plan(plan_id: str) -> bool:
    """
    Проверяет, является ли план подпиской учителя.

    Args:
        plan_id: ID плана

    Returns:
        True если план для учителя
    """
    plan = SUBSCRIPTION_PLANS.get(plan_id)
    if not plan:
        return False
    return plan.get('type') == 'teacher'


def is_student_plan(plan_id: str) -> bool:
    """
    Проверяет, является ли план подпиской ученика.

    Args:
        plan_id: ID плана

    Returns:
        True если план для ученика
    """
    plan = SUBSCRIPTION_PLANS.get(plan_id)
    if not plan:
        return False
    return plan.get('type') == 'student'


def get_teacher_max_students(plan_id: str) -> int:
    """
    Возвращает максимальное количество учеников для плана учителя.

    Args:
        plan_id: ID плана учителя

    Returns:
        Максимальное количество учеников (-1 для безлимита, 0 если не план учителя)
    """
    plan = SUBSCRIPTION_PLANS.get(plan_id)
    if not plan or plan.get('type') != 'teacher':
        return 0
    return plan.get('max_students', 0)


def get_all_teacher_plans(user_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Возвращает список всех планов подписок для учителей.
    Тестовые планы (is_test=True) показываются только администраторам.

    Args:
        user_id: ID пользователя для проверки прав доступа к тестовым планам.
                 Если None, тестовые планы не показываются.

    Returns:
        Список словарей с информацией о планах учителей
    """
    # Проверяем, является ли пользователь админом
    is_admin = False
    if user_id is not None:
        try:
            from core.config import ADMIN_IDS
            is_admin = user_id in ADMIN_IDS
        except ImportError:
            logger.warning("Could not import ADMIN_IDS from core.config")

    teacher_plans = []
    for plan_id, plan_info in SUBSCRIPTION_PLANS.items():
        if plan_info.get('type') == 'teacher':
            # Пропускаем тестовые планы для обычных пользователей
            if plan_info.get('is_test', False) and not is_admin:
                continue

            plan_copy = plan_info.copy()
            plan_copy['plan_id'] = plan_id
            teacher_plans.append(plan_copy)

    # Сортируем по цене
    teacher_plans.sort(key=lambda x: x['price_rub'])
    return teacher_plans


def get_student_discount_plan() -> Optional[str]:
    """
    Возвращает ID плана со скидкой для учеников от учителя.

    Returns:
        ID плана или None
    """
    for plan_id, plan_info in SUBSCRIPTION_PLANS.items():
        if plan_info.get('type') == 'student':
            return plan_id
    return None


def is_test_plan(plan_id: str) -> bool:
    """
    Проверяет, является ли план тестовым.

    Args:
        plan_id: ID плана

    Returns:
        True если план тестовый
    """
    plan = SUBSCRIPTION_PLANS.get(plan_id)
    if not plan:
        return False
    return plan.get('is_test', False)


def get_available_plans(user_id: int) -> Dict[str, Dict[str, Any]]:
    """
    Возвращает список доступных тарифов для пользователя.
    Тестовые тарифы (is_test=True) видны только администраторам.

    Args:
        user_id: ID пользователя Telegram

    Returns:
        Словарь с доступными тарифами
    """
    try:
        from core.config import ADMIN_IDS
        is_admin = user_id in ADMIN_IDS
    except ImportError:
        logger.warning("Could not import ADMIN_IDS from core.config, test plans will be hidden")
        is_admin = False

    available_plans = {}
    for plan_id, plan_info in SUBSCRIPTION_PLANS.items():
        # Если план тестовый и пользователь не админ - скрываем
        if plan_info.get('is_test', False) and not is_admin:
            continue

        available_plans[plan_id] = plan_info

    return available_plans


def get_regular_plans() -> Dict[str, Dict[str, Any]]:
    """
    Возвращает список ТОЛЬКО не-тестовых тарифов.
    Полезно для отображения обычным пользователям.

    Returns:
        Словарь с обычными тарифами (без is_test=True)
    """
    regular_plans = {}
    for plan_id, plan_info in SUBSCRIPTION_PLANS.items():
        if not plan_info.get('is_test', False):
            regular_plans[plan_id] = plan_info

    return regular_plans


# ==================== LEGACY SUPPORT ====================
# Для обратной совместимости со старым кодом
LEGACY_SUBSCRIPTION_PLANS = {}

# Экспортируем для обратной совместимости
__all__ = [
    'TINKOFF_TERMINAL_KEY',
    'TINKOFF_SECRET_KEY',
    'TINKOFF_API_URL',
    'WEBHOOK_URL',
    'PAYMENT_ADMIN_CHAT_ID',
    'DATABASE_FILE',  # ИСПРАВЛЕНИЕ: Добавлен централизованный DATABASE_FILE
    'DATABASE_PATH',  # Алиас для обратной совместимости
    'SUBSCRIPTION_MODE',
    'FREE_MODULES',
    'FREEMIUM_MODULES',
    'MODULE_PLANS',
    'SUBSCRIPTION_PLANS',
    'DURATION_DISCOUNTS',
    'MODULE_DESCRIPTIONS',
    'ConfigValidationError',  # НОВОЕ: Класс исключения
    'validate_config',  # НОВОЕ: Функция валидации
    'get_config_status',  # НОВОЕ: Функция диагностики
    'get_plan_price_kopecks',
    'get_subscription_end_date',
    'calculate_subscription_price',
    'get_plan_modules',
    'format_price',
    'is_module_free',
    'get_module_info',
    'get_plan_info',
    'is_teacher_plan',
    'is_student_plan',
    'get_teacher_max_students',
    'get_all_teacher_plans',
    'get_student_discount_plan',
    'is_test_plan',  # НОВОЕ: Проверка тестового тарифа
    'get_available_plans',  # НОВОЕ: Фильтрация тарифов для пользователя
    'get_regular_plans'  # НОВОЕ: Только обычные тарифы
]