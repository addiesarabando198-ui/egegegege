#!/usr/bin/env python3
"""
Упрощённая ручная активация подписки без зависимостей от telegram бота.
Использует только aiosqlite и стандартную библиотеку.

Usage: python3 simple_activate.py <order_id>
"""

import sys
import asyncio
import aiosqlite
import json
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_PATH = 'quiz_async.db'


async def activate_subscription_simple(order_id: str):
    """Упрощённая активация подписки."""

    async with aiosqlite.connect(DATABASE_PATH, timeout=30.0) as conn:
        # Получаем информацию о платеже
        cursor = await conn.execute(
            """
            SELECT user_id, plan_id, metadata, status
            FROM payments
            WHERE order_id = ?
            """,
            (order_id,)
        )
        payment_info = await cursor.fetchone()

        if not payment_info:
            logger.error(f"❌ Платеж не найден для order_id: {order_id}")
            return False

        user_id, plan_id, metadata_str, current_status = payment_info

        logger.info(f"Найден платеж: user_id={user_id}, plan_id={plan_id}, status={current_status}")

        # Проверяем, есть ли уже активные подписки
        cursor = await conn.execute(
            """
            SELECT COUNT(*) FROM module_subscriptions
            WHERE user_id = ? AND is_active = 1
            """,
            (user_id,)
        )
        count = await cursor.fetchone()

        if count and count[0] > 0:
            logger.info(f"✅ У пользователя уже есть {count[0]} активных подписок")
            response = input("Продолжить активацию? (yes/no): ")
            if response.lower() != 'yes':
                return False

        # Парсим metadata
        try:
            metadata = json.loads(metadata_str) if metadata_str else {}
        except:
            metadata = {}

        duration_months = metadata.get('duration_months', 1)

        # Получаем информацию о плане
        plan_config = get_plan_config(plan_id)

        if not plan_config:
            logger.error(f"❌ План {plan_id} не найден в конфигурации")
            return False

        logger.info(f"План: {plan_config['name']}")
        logger.info(f"Модули: {plan_config['modules']}")
        logger.info(f"Длительность: {duration_months} мес.")

        # Вычисляем дату истечения
        if plan_id == 'trial_7days':
            expires_at = datetime.now() + timedelta(days=7)
        else:
            expires_at = datetime.now() + timedelta(days=duration_months * 30)

        expires_at_str = expires_at.strftime('%Y-%m-%d %H:%M:%S')

        # Создаём подписки для каждого модуля
        for module_code in plan_config['modules']:
            try:
                # Проверяем, есть ли уже подписка на этот модуль
                cursor = await conn.execute(
                    """
                    SELECT id, is_active, expires_at FROM module_subscriptions
                    WHERE user_id = ? AND module_code = ?
                    """,
                    (user_id, module_code)
                )
                existing = await cursor.fetchone()

                if existing:
                    # Обновляем существующую подписку
                    logger.info(f"  Обновляю подписку на модуль {module_code}")
                    await conn.execute(
                        """
                        UPDATE module_subscriptions
                        SET expires_at = ?, is_active = 1, plan_id = ?
                        WHERE user_id = ? AND module_code = ?
                        """,
                        (expires_at_str, plan_id, user_id, module_code)
                    )
                else:
                    # Создаём новую подписку
                    logger.info(f"  Создаю подписку на модуль {module_code}")
                    await conn.execute(
                        """
                        INSERT INTO module_subscriptions
                        (user_id, module_code, plan_id, expires_at, is_active)
                        VALUES (?, ?, ?, ?, 1)
                        """,
                        (user_id, module_code, plan_id, expires_at_str)
                    )
            except Exception as e:
                logger.error(f"  ❌ Ошибка при создании подписки на {module_code}: {e}")
                return False

        # Обновляем статус платежа
        await conn.execute(
            """
            UPDATE payments
            SET status = 'completed',
                completed_at = CURRENT_TIMESTAMP
            WHERE order_id = ?
            """,
            (order_id,)
        )

        # Если это триал, добавляем в историю триала
        if plan_id == 'trial_7days':
            await conn.execute(
                """
                INSERT OR REPLACE INTO trial_history
                (user_id, trial_activated_at, trial_expires_at)
                VALUES (?, CURRENT_TIMESTAMP, ?)
                """,
                (user_id, expires_at_str)
            )

        await conn.commit()

        logger.info(f"✅ Подписка успешно активирована!")
        logger.info(f"   User ID: {user_id}")
        logger.info(f"   План: {plan_id}")
        logger.info(f"   Модулей: {len(plan_config['modules'])}")
        logger.info(f"   Истекает: {expires_at_str}")

        return True


def get_plan_config(plan_id: str):
    """Возвращает конфигурацию плана."""
    plans = {
        'trial_7days': {
            'name': '🎁 Пробный период',
            'modules': ['test_part', 'task19', 'task20', 'task24', 'task25'],
            'duration_days': 7
        },
        'month_1': {
            'name': '📅 1 месяц',
            'modules': ['test_part', 'task19', 'task20', 'task24', 'task25'],
            'duration_days': 30
        },
        'month_3': {
            'name': '📅 3 месяца',
            'modules': ['test_part', 'task19', 'task20', 'task24', 'task25'],
            'duration_days': 90
        },
        'year_1': {
            'name': '📅 1 год',
            'modules': ['test_part', 'task19', 'task20', 'task24', 'task25'],
            'duration_days': 365
        }
    }

    # Поддержка кастомных планов
    if plan_id.startswith('custom_'):
        return {
            'name': 'Кастомный план',
            'modules': ['test_part', 'task19', 'task20', 'task24', 'task25'],
            'duration_days': 30
        }

    return plans.get(plan_id)


async def main():
    if len(sys.argv) < 2:
        print("Usage: python3 simple_activate.py <order_id>")
        print()
        print("Example:")
        print("  python3 simple_activate.py order_6258384661_1761646304_2017e6a6")
        sys.exit(1)

    order_id = sys.argv[1]

    print()
    print("="*80)
    print("РУЧНАЯ АКТИВАЦИЯ ПОДПИСКИ")
    print("="*80)
    print()
    print(f"Order ID: {order_id}")
    print()
    print("ВНИМАНИЕ! Используйте только если платеж был подтвержден в Tinkoff!")
    print()

    response = input("Продолжить? (yes/no): ")
    if response.lower() != 'yes':
        print("Отменено.")
        sys.exit(0)

    print()
    success = await activate_subscription_simple(order_id)

    if success:
        print()
        print("="*80)
        print("✅ ГОТОВО!")
        print("="*80)
        print()
        print("Проверьте результат:")
        print(f"  python3 check_payment_details.py {order_id}")
        print()
        sys.exit(0)
    else:
        print()
        print("="*80)
        print("❌ ОШИБКА!")
        print("="*80)
        print()
        print("Активация не удалась. Проверьте логи выше.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
