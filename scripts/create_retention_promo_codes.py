#!/usr/bin/env python3
"""
Скрипт для создания промокодов для retention-кампаний.

Создаёт все промокоды из notification_templates.py:
- TOP20, TRIAL20, LASTDAY25, COMEBACK30, STAY15, SAVE25, URGENT30, RETURN40, LAST50

Usage:
    python scripts/create_retention_promo_codes.py [database_path]

    database_path - опциональный путь к БД (по умолчанию quiz_async.db)

Examples:
    python scripts/create_retention_promo_codes.py
    python scripts/create_retention_promo_codes.py /opt/ege-bot/quiz_async.db
    python3 scripts/create_retention_promo_codes.py quiz_async.db
"""

import asyncio
import aiosqlite
import sys
import os
from pathlib import Path

# Добавляем путь к корневой директории
ROOT_DIR = Path(__file__).parent.parent

# Определяем путь к БД без импорта core.db (чтобы избежать зависимостей)
if len(sys.argv) > 1:
    DATABASE_FILE = sys.argv[1]
else:
    # По умолчанию ищем quiz_async.db в текущей директории или в корне проекта
    current_dir = Path.cwd()

    if (current_dir / 'quiz_async.db').exists():
        DATABASE_FILE = str(current_dir / 'quiz_async.db')
    elif (ROOT_DIR / 'quiz_async.db').exists():
        DATABASE_FILE = str(ROOT_DIR / 'quiz_async.db')
    else:
        # Если не найдена, используем текущую директорию (будет ошибка позже если не существует)
        DATABASE_FILE = 'quiz_async.db'

# Промокоды из retention-системы
RETENTION_PROMO_CODES = [
    {
        'code': 'TOP20',
        'discount_percent': 20,
        'description': 'Скидка 20% для топ-10% активных бесплатников (Active Free Day 20)',
        'usage_limit': None,  # Безлимит
        'campaign': 'active_free_day20'
    },
    {
        'code': 'TRIAL20',
        'discount_percent': 20,
        'description': 'Скидка 20% для триалистов за 2 дня до окончания',
        'usage_limit': None,
        'campaign': 'trial_expiring_2days'
    },
    {
        'code': 'LASTDAY25',
        'discount_percent': 25,
        'description': 'Скидка 25% для триалистов в последний день',
        'usage_limit': None,
        'campaign': 'trial_expiring_1day'
    },
    {
        'code': 'COMEBACK30',
        'discount_percent': 30,
        'description': 'Скидка 30% для expired trial users',
        'usage_limit': None,
        'campaign': 'trial_expired'
    },
    {
        'code': 'STAY15',
        'discount_percent': 15,
        'description': 'Скидка 15% для churn risk за 7 дней',
        'usage_limit': None,
        'campaign': 'churn_risk_7days'
    },
    {
        'code': 'SAVE25',
        'discount_percent': 25,
        'description': 'Скидка 25% для churn risk за 3 дня',
        'usage_limit': None,
        'campaign': 'churn_risk_3days'
    },
    {
        'code': 'URGENT30',
        'discount_percent': 30,
        'description': 'Скидка 30% для churn risk в последний день',
        'usage_limit': None,
        'campaign': 'churn_risk_1day'
    },
    {
        'code': 'RETURN40',
        'discount_percent': 40,
        'description': 'Скидка 40% для cancelled users (день 3)',
        'usage_limit': None,
        'campaign': 'cancelled_day3'
    },
    {
        'code': 'LAST50',
        'discount_percent': 50,
        'description': 'Скидка 50% для cancelled users (день 7 - последний шанс)',
        'usage_limit': None,
        'campaign': 'cancelled_day7'
    }
]


async def promo_code_exists(db: aiosqlite.Connection, code: str) -> bool:
    """Проверяет существует ли промокод"""
    cursor = await db.execute(
        "SELECT code FROM promo_codes WHERE code = ?",
        (code.upper(),)
    )
    result = await cursor.fetchone()
    return result is not None


async def create_promo_code(db: aiosqlite.Connection, promo_data: dict) -> bool:
    """
    Создаёт промокод в БД.

    Returns:
        True если создан, False если уже существует
    """
    code = promo_data['code'].upper()

    # Проверяем существование
    if await promo_code_exists(db, code):
        print(f"  ⚠️  {code} уже существует, пропускаем")
        return False

    # Создаём промокод (без поля description - его нет в схеме)
    # created_at имеет DEFAULT CURRENT_TIMESTAMP, поэтому не указываем его
    await db.execute("""
        INSERT INTO promo_codes (
            code,
            discount_percent,
            discount_amount,
            usage_limit,
            used_count,
            is_active
        ) VALUES (?, ?, ?, ?, ?, ?)
    """, (
        code,
        promo_data['discount_percent'],
        0,  # discount_amount (используем процент, не фикс. сумму)
        promo_data['usage_limit'],
        0,  # used_count
        1  # is_active
    ))

    print(f"  ✅ {code} создан ({promo_data['discount_percent']}% скидка)")
    return True


async def create_all_promo_codes():
    """Создаёт все retention промокоды"""
    print("=" * 60)
    print("🎁 СОЗДАНИЕ ПРОМОКОДОВ ДЛЯ RETENTION-СИСТЕМЫ")
    print("=" * 60)
    print()

    # Проверяем наличие БД
    if not os.path.exists(DATABASE_FILE):
        print(f"❌ База данных не найдена: {DATABASE_FILE}")
        print(f"   Создайте БД или укажите правильный путь")
        return

    # Проверяем наличие таблицы promo_codes
    async with aiosqlite.connect(DATABASE_FILE) as db:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='promo_codes'"
        )
        table_exists = await cursor.fetchone()

        if not table_exists:
            print("❌ Таблица promo_codes не существует!")
            print("   Сначала примените миграции платёжного модуля")
            return

        print(f"📂 База данных: {DATABASE_FILE}")
        print(f"📊 Промокодов к созданию: {len(RETENTION_PROMO_CODES)}")
        print()

        created = 0
        skipped = 0

        for promo_data in RETENTION_PROMO_CODES:
            if await create_promo_code(db, promo_data):
                created += 1
            else:
                skipped += 1

        await db.commit()

        print()
        print("=" * 60)
        print(f"✅ Готово!")
        print(f"   Создано: {created}")
        print(f"   Пропущено (уже существуют): {skipped}")
        print("=" * 60)
        print()

        # Показываем список всех retention промокодов
        print("📋 ВСЕ RETENTION ПРОМОКОДЫ:")
        print()

        cursor = await db.execute("""
            SELECT code, discount_percent, is_active
            FROM promo_codes
            WHERE code IN ({})
            ORDER BY discount_percent ASC
        """.format(','.join(['?' for _ in RETENTION_PROMO_CODES])),
            [p['code'].upper() for p in RETENTION_PROMO_CODES]
        )

        codes = await cursor.fetchall()

        # Создаём словарь для быстрого поиска описаний
        descriptions = {p['code'].upper(): p['description'] for p in RETENTION_PROMO_CODES}

        for code, discount, is_active in codes:
            status = "✅" if is_active else "❌"
            description = descriptions.get(code, "")
            print(f"  {status} {code:12} - {discount:2}% - {description}")

        print()
        print("💡 Использование:")
        print("   Эти промокоды автоматически включены в notification_templates.py")
        print("   Они будут предлагаться пользователям в retention-уведомлениях")
        print()


async def main():
    """Главная функция"""
    try:
        await create_all_promo_codes()
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    asyncio.run(main())
