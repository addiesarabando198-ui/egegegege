#!/usr/bin/env python3
"""Скрипт для проверки подписки конкретного пользователя."""
import asyncio
import aiosqlite
from datetime import datetime, timezone
import json
import sys

async def check_user_subscription(user_id: int, db_path='quiz_async.db'):
    """
    Проверяет состояние подписки пользователя.

    Args:
        user_id: ID пользователя в Telegram
        db_path: Путь к БД
    """
    try:
        async with aiosqlite.connect(db_path) as db:
            print("=" * 80)
            print(f"ПРОВЕРКА ПОДПИСКИ ПОЛЬЗОВАТЕЛЯ {user_id}")
            print("=" * 80)
            print()

            # Проверяем наличие таблиц
            cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in await cursor.fetchall()]

            if not tables:
                print("❌ БД пустая или не инициализирована")
                print(f"   Путь: {db_path}")
                return

            print(f"📋 Доступные таблицы: {', '.join(tables)}")
            print()

            # ========================================
            # 1. ИНФОРМАЦИЯ О ПОЛЬЗОВАТЕЛЕ
            # ========================================
            print("👤 ИНФОРМАЦИЯ О ПОЛЬЗОВАТЕЛЕ:")

            if 'users' in tables:
                cursor = await db.execute("""
                    SELECT user_id, username, first_name, last_name, created_at
                    FROM users
                    WHERE user_id = ?
                """, (user_id,))
                user_info = await cursor.fetchone()
            else:
                print("   ⚠️  Таблица 'users' не найдена, пропускаем...")
                user_info = None

            if user_info:
                uid, username, first_name, last_name, created_at = user_info
                print(f"   ID: {uid}")
                print(f"   Username: @{username if username else 'не указан'}")
                print(f"   Имя: {first_name} {last_name or ''}")
                print(f"   Зарегистрирован: {created_at}")
            else:
                print(f"   ❌ Пользователь с ID {user_id} не найден в БД")
                return

            print()

            # ========================================
            # 2. ПЛАТЕЖИ ПОЛЬЗОВАТЕЛЯ
            # ========================================
            print("💳 ПЛАТЕЖИ:")

            if 'payments' not in tables:
                print("   ❌ Таблица 'payments' не найдена")
                payments = []
            else:
                cursor = await db.execute("""
                    SELECT order_id, plan_id, amount_kopecks, status,
                           created_at, completed_at, payment_id, metadata
                    FROM payments
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                """, (user_id,))
                payments = await cursor.fetchall()

            if not payments:
                print("   ℹ️  Платежей не найдено")
            else:
                for payment in payments:
                    order_id, plan_id, amount, status, created, completed, payment_id, metadata_str = payment

                    print(f"\n   📋 Платеж: {order_id}")
                    print(f"      План: {plan_id}")
                    print(f"      Сумма: {amount / 100:.2f}₽")
                    print(f"      Статус: {status}")
                    print(f"      Создан: {created}")
                    print(f"      Завершен: {completed or 'не завершен'}")
                    print(f"      Payment ID: {payment_id or 'нет'}")

                    if metadata_str:
                        try:
                            metadata = json.loads(metadata_str)
                            print(f"      Метаданные:")
                            print(f"         duration_months: {metadata.get('duration_months', 'не указано')}")
                            print(f"         enable_auto_renewal: {metadata.get('enable_auto_renewal', False)}")
                            print(f"         email: {metadata.get('email', 'не указан')}")
                        except:
                            print(f"      Метаданные: {metadata_str}")

            print()

            # ========================================
            # 3. АКТИВНЫЕ ПОДПИСКИ
            # ========================================
            print("📦 ПОДПИСКИ:")

            if 'module_subscriptions' not in tables:
                print("   ❌ Таблица 'module_subscriptions' не найдена")
                subscriptions = []
            else:
                cursor = await db.execute("""
                    SELECT module_code, plan_id, created_at, expires_at, is_active
                    FROM module_subscriptions
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                """, (user_id,))
                subscriptions = await cursor.fetchall()

            if not subscriptions:
                print("   ❌ Активных подписок не найдено")
            else:
                now = datetime.now(timezone.utc)
                for sub in subscriptions:
                    module_code, plan_id, created, expires, is_active = sub

                    # Парсим даты
                    try:
                        created_dt = datetime.fromisoformat(created)
                        expires_dt = datetime.fromisoformat(expires)

                        if created_dt.tzinfo is None:
                            created_dt = created_dt.replace(tzinfo=timezone.utc)
                        if expires_dt.tzinfo is None:
                            expires_dt = expires_dt.replace(tzinfo=timezone.utc)

                        duration = (expires_dt - created_dt).days
                        is_expired = expires_dt < now

                        status_icon = "✅" if (is_active and not is_expired) else "❌"

                        print(f"\n   {status_icon} Модуль: {module_code}")
                        print(f"      План: {plan_id}")
                        print(f"      Создана: {created}")
                        print(f"      Истекает: {expires}")
                        print(f"      Длительность: {duration} дней")
                        print(f"      Активна: {'Да' if is_active else 'Нет'}")
                        print(f"      Истекла: {'Да' if is_expired else 'Нет'}")

                        # Проверка корректности длительности
                        if plan_id == 'trial_7days':
                            expected = 7
                            if duration != expected:
                                print(f"      ⚠️  ОШИБКА: ожидалось {expected} дней, получено {duration}")
                        elif plan_id == 'package_full':
                            # Пытаемся найти duration_months из платежа
                            cursor2 = await db.execute("""
                                SELECT metadata FROM payments
                                WHERE user_id = ? AND plan_id = ? AND status = 'completed'
                                ORDER BY created_at DESC LIMIT 1
                            """, (user_id, plan_id))
                            payment_info = await cursor2.fetchone()
                            if payment_info and payment_info[0]:
                                try:
                                    meta = json.loads(payment_info[0])
                                    expected_months = meta.get('duration_months', 1)
                                    expected_days = 30 * expected_months
                                    if abs(duration - expected_days) > 1:
                                        print(f"      ⚠️  ОШИБКА: ожидалось {expected_days} дней ({expected_months} мес), получено {duration}")
                                except:
                                    pass
                    except Exception as e:
                        print(f"      ⚠️  Ошибка парсинга дат: {e}")

            print()

            # ========================================
            # 4. ИСТОРИЯ ПРОБНОГО ПЕРИОДА
            # ========================================
            print("🎁 ИСТОРИЯ ПРОБНОГО ПЕРИОДА:")

            if 'trial_history' not in tables:
                print("   ⚠️  Таблица 'trial_history' не найдена")
            else:
                cursor = await db.execute("""
                    SELECT trial_activated_at, trial_expires_at
                    FROM trial_history
                    WHERE user_id = ?
                """, (user_id,))
                trial = await cursor.fetchone()

                if trial:
                    activated, expires = trial
                    print(f"   Активирован: {activated}")
                    print(f"   Истекает: {expires}")
                else:
                    print("   ℹ️  Пробный период не активирован")

            print()

            # ========================================
            # 5. WEBHOOK ЛОГИ
            # ========================================
            print("📡 WEBHOOK ЛОГИ:")

            # Проверяем, есть ли таблица webhook_logs
            cursor = await db.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='webhook_logs'
            """)
            if await cursor.fetchone():
                # Получаем order_id из платежей пользователя
                cursor = await db.execute("""
                    SELECT order_id FROM payments WHERE user_id = ?
                """, (user_id,))
                order_ids = [row[0] for row in await cursor.fetchall()]

                if order_ids:
                    placeholders = ','.join('?' * len(order_ids))
                    cursor = await db.execute(f"""
                        SELECT order_id, status, payment_id, created_at
                        FROM webhook_logs
                        WHERE order_id IN ({placeholders})
                        ORDER BY created_at DESC
                    """, order_ids)
                    webhook_logs = await cursor.fetchall()

                    if webhook_logs:
                        for log in webhook_logs:
                            order_id, status, payment_id, created = log
                            print(f"\n   📨 Webhook: {order_id}")
                            print(f"      Статус: {status}")
                            print(f"      Payment ID: {payment_id}")
                            print(f"      Время: {created}")
                    else:
                        print("   ℹ️  Webhook логов не найдено")
                else:
                    print("   ℹ️  Нет платежей для проверки webhook")
            else:
                print("   ℹ️  Таблица webhook_logs не существует")

            print()

            # ========================================
            # 6. ДИАГНОСТИКА
            # ========================================
            print("🔍 ДИАГНОСТИКА:")

            # Проверяем, есть ли незавершенные платежи
            cursor = await db.execute("""
                SELECT COUNT(*) FROM payments
                WHERE user_id = ? AND status = 'pending'
            """, (user_id,))
            pending_count = (await cursor.fetchone())[0]

            if pending_count > 0:
                print(f"   ⚠️  Есть {pending_count} незавершенных платежей")

            # Проверяем, есть ли completed платежи без подписок
            cursor = await db.execute("""
                SELECT p.order_id, p.plan_id
                FROM payments p
                LEFT JOIN module_subscriptions ms ON p.user_id = ms.user_id
                WHERE p.user_id = ? AND p.status = 'completed' AND ms.user_id IS NULL
            """, (user_id,))
            orphan_payments = await cursor.fetchall()

            if orphan_payments:
                print(f"   ❌ КРИТИЧНО: Найдены завершенные платежи БЕЗ подписок:")
                for order_id, plan_id in orphan_payments:
                    print(f"      - {order_id} ({plan_id})")
                print(f"   → Это означает, что платеж прошел, но подписка не активировалась!")

            # Проверяем, есть ли подписки с неправильной длительностью
            cursor = await db.execute("""
                SELECT module_code, plan_id, created_at, expires_at
                FROM module_subscriptions
                WHERE user_id = ? AND plan_id = 'trial_7days'
            """, (user_id,))
            trial_subs = await cursor.fetchall()

            for module_code, plan_id, created, expires in trial_subs:
                try:
                    created_dt = datetime.fromisoformat(created)
                    expires_dt = datetime.fromisoformat(expires)
                    if created_dt.tzinfo is None:
                        created_dt = created_dt.replace(tzinfo=timezone.utc)
                    if expires_dt.tzinfo is None:
                        expires_dt = expires_dt.replace(tzinfo=timezone.utc)

                    duration = (expires_dt - created_dt).days
                    if duration > 7:
                        print(f"   ⚠️  Модуль {module_code}: пробный период имеет {duration} дней вместо 7")
                        print(f"   → Необходимо применить миграцию fix_subscription_durations.py")
                except:
                    pass

            print()
            print("=" * 80)

    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

async def main():
    """Точка входа."""
    if len(sys.argv) < 2:
        print("Использование: python3 check_user_subscription.py <user_id>")
        print("Пример: python3 check_user_subscription.py 5145328370")
        sys.exit(1)

    try:
        user_id = int(sys.argv[1])
    except ValueError:
        print(f"❌ Ошибка: '{sys.argv[1]}' не является корректным ID пользователя")
        sys.exit(1)

    await check_user_subscription(user_id)

if __name__ == '__main__':
    asyncio.run(main())
