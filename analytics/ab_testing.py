"""
A/B тестирование для оптимизации онбординга и конверсий.

Позволяет:
- Рандомно распределять пользователей по вариантам
- Отслеживать конверсии по вариантам
- Сравнивать эффективность разных подходов
"""

import logging
import random
from typing import Optional, Dict, List
from datetime import datetime
import aiosqlite
from core.config import DATABASE_FILE

logger = logging.getLogger(__name__)


# Доступные A/B тесты
ACTIVE_TESTS = {
    'onboarding_flow': {
        'variants': ['control', 'no_question', 'instant_value'],
        'weights': [34, 33, 33],  # Равномерное распределение
        'description': 'Тестирование разных флоу онбординга'
    }
}


async def assign_user_to_variant(
    user_id: int,
    test_name: str
) -> str:
    """
    Назначает пользователя на вариант A/B теста.

    Args:
        user_id: ID пользователя
        test_name: Название теста (например, 'onboarding_flow')

    Returns:
        Название варианта (например, 'control', 'variant_a')
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Проверяем существование таблицы
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='ab_tests'"
            )
            table_exists = await cursor.fetchone()

            if not table_exists:
                # Создаём таблицу
                await db.execute("""
                    CREATE TABLE ab_tests (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        test_name TEXT NOT NULL,
                        variant TEXT NOT NULL,
                        assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(user_id, test_name),
                        FOREIGN KEY (user_id) REFERENCES users(user_id)
                    )
                """)
                await db.execute("CREATE INDEX idx_ab_tests_user ON ab_tests(user_id)")
                await db.execute("CREATE INDEX idx_ab_tests_test ON ab_tests(test_name)")
                await db.execute("CREATE INDEX idx_ab_tests_variant ON ab_tests(variant)")
                await db.commit()
                logger.info("Created ab_tests table")

            # Проверяем, уже ли назначен пользователь на этот тест
            cursor = await db.execute("""
                SELECT variant FROM ab_tests
                WHERE user_id = ? AND test_name = ?
            """, (user_id, test_name))

            existing = await cursor.fetchone()
            if existing:
                return existing[0]

            # Назначаем новый вариант
            test_config = ACTIVE_TESTS.get(test_name)
            if not test_config:
                logger.warning(f"Unknown test: {test_name}")
                return 'control'

            # Weighted random choice
            variant = random.choices(
                test_config['variants'],
                weights=test_config['weights'],
                k=1
            )[0]

            await db.execute("""
                INSERT INTO ab_tests (user_id, test_name, variant)
                VALUES (?, ?, ?)
            """, (user_id, test_name, variant))

            await db.commit()

            logger.info(f"Assigned user {user_id} to test '{test_name}' variant '{variant}'")
            return variant

    except Exception as e:
        logger.error(f"Error assigning A/B test variant for user {user_id}: {e}")
        return 'control'  # Fallback to control


async def get_user_variant(user_id: int, test_name: str) -> Optional[str]:
    """
    Получает вариант A/B теста для пользователя.

    Args:
        user_id: ID пользователя
        test_name: Название теста

    Returns:
        Название варианта или None
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute("""
                SELECT variant FROM ab_tests
                WHERE user_id = ? AND test_name = ?
            """, (user_id, test_name))

            row = await cursor.fetchone()
            return row[0] if row else None

    except Exception as e:
        logger.error(f"Error getting A/B test variant for user {user_id}: {e}")
        return None


async def get_test_stats(test_name: str, days: int = 30) -> Dict:
    """
    Получает статистику по A/B тесту.

    Args:
        test_name: Название теста
        days: За сколько дней

    Returns:
        Dict со статистикой по вариантам
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT
                    ab.variant,
                    COUNT(DISTINCT ab.user_id) as total_users,
                    COUNT(DISTINCT CASE
                        WHEN c.conversion_type = 'trial_purchase' THEN c.user_id
                    END) as trial_conversions,
                    COUNT(DISTINCT CASE
                        WHEN c.conversion_type = 'subscription_purchase' THEN c.user_id
                    END) as paid_conversions,
                    COALESCE(SUM(CASE
                        WHEN c.conversion_type = 'subscription_purchase' THEN c.value_rub
                        ELSE 0
                    END), 0) as total_revenue
                FROM ab_tests ab
                LEFT JOIN conversions c ON ab.user_id = c.user_id
                WHERE ab.test_name = ?
                  AND ab.assigned_at >= datetime('now', ?)
                GROUP BY ab.variant
                ORDER BY ab.variant
            """, (test_name, f'-{days} days'))

            rows = await cursor.fetchall()

            variants = []
            for row in rows:
                total = row['total_users']
                trial_conv = row['trial_conversions']
                paid_conv = row['paid_conversions']

                trial_cr = (trial_conv / total * 100) if total > 0 else 0
                paid_cr = (paid_conv / total * 100) if total > 0 else 0

                variants.append({
                    'variant': row['variant'],
                    'total_users': total,
                    'trial_conversions': trial_conv,
                    'paid_conversions': paid_conv,
                    'trial_cr': round(trial_cr, 2),
                    'paid_cr': round(paid_cr, 2),
                    'revenue': row['total_revenue']
                })

            return {
                'test_name': test_name,
                'variants': variants,
                'period_days': days
            }

    except Exception as e:
        logger.error(f"Error getting A/B test stats for {test_name}: {e}")
        return {'test_name': test_name, 'variants': [], 'period_days': days}


async def track_ab_conversion(
    user_id: int,
    test_name: str,
    conversion_type: str,
    value: float = 0
) -> bool:
    """
    Отслеживает конверсию в рамках A/B теста.

    Использует существующую таблицу conversions + добавляет связь с A/B тестом.

    Args:
        user_id: ID пользователя
        test_name: Название теста
        conversion_type: Тип конверсии
        value: Значение конверсии

    Returns:
        True если успешно
    """
    from analytics.utm_tracker import track_conversion

    # Используем существующую функцию отслеживания конверсий
    # Данные о варианте A/B теста уже есть в таблице ab_tests
    return await track_conversion(user_id, conversion_type, value)


async def get_winning_variant(test_name: str, metric: str = 'trial_cr') -> Optional[str]:
    """
    Определяет лучший вариант A/B теста по метрике.

    Args:
        test_name: Название теста
        metric: Метрика для сравнения ('trial_cr', 'paid_cr', 'revenue')

    Returns:
        Название лучшего варианта или None
    """
    stats = await get_test_stats(test_name)

    if not stats['variants']:
        return None

    # Сортируем по метрике
    sorted_variants = sorted(
        stats['variants'],
        key=lambda x: x.get(metric, 0),
        reverse=True
    )

    winner = sorted_variants[0]

    logger.info(f"Winning variant for {test_name} (by {metric}): {winner['variant']} ({winner[metric]}%)")
    return winner['variant']
