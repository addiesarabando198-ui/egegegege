#!/usr/bin/env python3
"""Скрипт для аудита длительности подписок в БД."""
import asyncio
import aiosqlite
from datetime import datetime, timedelta, timezone
import sys

async def audit_subscriptions():
    """Проверяет и выводит статистику по подпискам с неправильной длительностью."""
    try:
        async with aiosqlite.connect('quiz_async.db') as db:
            # Сначала проверим, какие таблицы есть
            cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = await cursor.fetchall()

            print("Доступные таблицы в БД:")
            for table in tables:
                print(f"  - {table[0]}")
            print()

            # Проверяем, есть ли таблица module_subscriptions
            table_names = [t[0] for t in tables]
            if 'module_subscriptions' not in table_names:
                print("❌ Таблица 'module_subscriptions' не найдена!")
                print("   Возможно, миграции не были применены или БД не инициализирована.")
                return None

            # Получаем все подписки trial_7days и package_full
            cursor = await db.execute("""
                SELECT user_id, plan_id, module_code, created_at, expires_at, is_active
                FROM module_subscriptions
                WHERE plan_id IN ('trial_7days', 'package_full')
                ORDER BY created_at DESC
            """)
            rows = await cursor.fetchall()

            print("=" * 80)
            print("АУДИТ ДЛИТЕЛЬНОСТИ ПОДПИСОК")
            print("=" * 80)
            print()

            if not rows:
                print("❌ Подписок не найдено")
                return

            # Статистика
            total_count = len(rows)
            trial_wrong = 0
            trial_correct = 0
            package_wrong = 0
            package_correct = 0

            wrong_subscriptions = []

            for row in rows:
                user_id, plan_id, module_code, created_at, expires_at, is_active = row

                try:
                    # Парсим даты
                    created_dt = datetime.fromisoformat(created_at)
                    expires_dt = datetime.fromisoformat(expires_at)

                    # Убеждаемся, что даты имеют timezone
                    if created_dt.tzinfo is None:
                        created_dt = created_dt.replace(tzinfo=timezone.utc)
                    if expires_dt.tzinfo is None:
                        expires_dt = expires_dt.replace(tzinfo=timezone.utc)

                    # Вычисляем длительность
                    duration = expires_dt - created_dt
                    duration_days = duration.days

                    # Определяем ожидаемую длительность
                    if plan_id == 'trial_7days':
                        expected_days = 7
                    elif plan_id == 'package_full':
                        # Для package_full проверяем metadata из payments
                        cursor2 = await db.execute("""
                            SELECT metadata FROM payments
                            WHERE user_id = ? AND plan_id = ? AND status = 'completed'
                            ORDER BY created_at DESC LIMIT 1
                        """, (user_id, plan_id))
                        payment = await cursor2.fetchone()

                        if payment and payment[0]:
                            import json
                            try:
                                metadata = json.loads(payment[0])
                                duration_months = metadata.get('duration_months', 1)
                                expected_days = 30 * duration_months
                            except:
                                expected_days = 30
                        else:
                            expected_days = 30
                    else:
                        expected_days = None

                    # Проверяем корректность
                    is_correct = duration_days == expected_days if expected_days else True

                    if plan_id == 'trial_7days':
                        if is_correct:
                            trial_correct += 1
                        else:
                            trial_wrong += 1
                            wrong_subscriptions.append({
                                'user_id': user_id,
                                'plan_id': plan_id,
                                'module_code': module_code,
                                'created_at': created_at,
                                'expires_at': expires_at,
                                'duration_days': duration_days,
                                'expected_days': expected_days,
                                'is_active': is_active
                            })
                    elif plan_id == 'package_full':
                        if is_correct:
                            package_correct += 1
                        else:
                            package_wrong += 1
                            wrong_subscriptions.append({
                                'user_id': user_id,
                                'plan_id': plan_id,
                                'module_code': module_code,
                                'created_at': created_at,
                                'expires_at': expires_at,
                                'duration_days': duration_days,
                                'expected_days': expected_days,
                                'is_active': is_active
                            })

                except Exception as e:
                    print(f"⚠️  Ошибка при обработке подписки: {e}")
                    print(f"   User: {user_id}, Plan: {plan_id}")

            # Выводим статистику
            print("📊 СТАТИСТИКА:")
            print(f"   Всего подписок: {total_count}")
            print()
            print(f"   trial_7days:")
            print(f"      ✅ Правильные: {trial_correct}")
            print(f"      ❌ Неправильные: {trial_wrong}")
            print()
            print(f"   package_full:")
            print(f"      ✅ Правильные: {package_correct}")
            print(f"      ❌ Неправильные: {package_wrong}")
            print()

            if wrong_subscriptions:
                print("=" * 80)
                print("❌ ПОДПИСКИ С НЕПРАВИЛЬНОЙ ДЛИТЕЛЬНОСТЬЮ:")
                print("=" * 80)

                for sub in wrong_subscriptions:
                    print(f"\n👤 User ID: {sub['user_id']}")
                    print(f"   План: {sub['plan_id']}")
                    print(f"   Модуль: {sub['module_code']}")
                    print(f"   Создана: {sub['created_at']}")
                    print(f"   Истекает: {sub['expires_at']}")
                    print(f"   Фактическая длительность: {sub['duration_days']} дней")
                    print(f"   Ожидаемая длительность: {sub['expected_days']} дней")
                    print(f"   Разница: +{sub['duration_days'] - sub['expected_days']} дней")
                    print(f"   Активна: {'Да' if sub['is_active'] else 'Нет'}")

            print()
            print("=" * 80)

            return {
                'total': total_count,
                'trial_wrong': trial_wrong,
                'package_wrong': package_wrong,
                'wrong_subscriptions': wrong_subscriptions
            }

    except Exception as e:
        print(f"❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    result = asyncio.run(audit_subscriptions())

    if result and (result['trial_wrong'] > 0 or result['package_wrong'] > 0):
        print("\n⚠️  ТРЕБУЕТСЯ ИСПРАВЛЕНИЕ!")
        print(f"   Найдено {result['trial_wrong'] + result['package_wrong']} подписок с неправильной длительностью")
        sys.exit(0)
    else:
        print("\n✅ Все подписки имеют правильную длительность")
        sys.exit(0)
