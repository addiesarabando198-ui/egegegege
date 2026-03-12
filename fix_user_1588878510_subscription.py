#!/usr/bin/env python3
"""
Скрипт для исправления подписки пользователя 1588878510.

ПРОБЛЕМА:
Пользователь оплатил package_full на 3 месяца (672₽),
но получил только trial_7days на 7 дней из-за race condition.

РЕШЕНИЕ:
Обновить все подписки на правильный срок (90 дней вместо 7).
"""
import asyncio
import aiosqlite
from datetime import datetime, timedelta, timezone

USER_ID = 1588878510
CORRECT_PLAN_ID = 'package_full'
CORRECT_DURATION_DAYS = 90  # 3 месяца

async def fix_subscription():
    """Исправляет подписку пользователя."""
    try:
        async with aiosqlite.connect('quiz_async.db') as db:
            print("=" * 80)
            print(f"ИСПРАВЛЕНИЕ ПОДПИСКИ ПОЛЬЗОВАТЕЛЯ {USER_ID}")
            print("=" * 80)
            print()

            # Получаем текущие подписки
            cursor = await db.execute("""
                SELECT module_code, plan_id, created_at, expires_at, is_active
                FROM module_subscriptions
                WHERE user_id = ?
            """, (USER_ID,))
            subscriptions = await cursor.fetchall()

            if not subscriptions:
                print("❌ Подписок не найдено")
                return

            print("📦 ТЕКУЩИЕ ПОДПИСКИ:")
            for module_code, plan_id, created_at, expires_at, is_active in subscriptions:
                print(f"   - {module_code}: {plan_id}, истекает {expires_at}")

            print()
            print("🔧 ИСПРАВЛЕНИЕ:")
            print()

            # Определяем правильную дату создания и окончания
            # Используем дату завершения платежа package_full: 2025-11-18 04:41:00
            correct_created_at = datetime(2025, 11, 18, 4, 41, 0, tzinfo=timezone.utc)
            correct_expires_at = correct_created_at + timedelta(days=CORRECT_DURATION_DAYS)

            print(f"   Новая дата создания: {correct_created_at.isoformat()}")
            print(f"   Новая дата окончания: {correct_expires_at.isoformat()}")
            print(f"   Длительность: {CORRECT_DURATION_DAYS} дней (3 месяца)")
            print()

            # Обновляем все подписки
            updated_count = 0
            for module_code, old_plan_id, old_created, old_expires, is_active in subscriptions:
                await db.execute("""
                    UPDATE module_subscriptions
                    SET plan_id = ?,
                        created_at = ?,
                        expires_at = ?,
                        is_active = 1
                    WHERE user_id = ? AND module_code = ?
                """, (CORRECT_PLAN_ID, correct_created_at.isoformat(),
                      correct_expires_at.isoformat(), USER_ID, module_code))

                print(f"   ✅ Обновлен модуль {module_code}")
                print(f"      Было: {old_plan_id}, истекает {old_expires}")
                print(f"      Стало: {CORRECT_PLAN_ID}, истекает {correct_expires_at.isoformat()}")
                print()

                updated_count += 1

            # Обновляем историю пробного периода (она тоже неправильная)
            await db.execute("""
                DELETE FROM trial_history WHERE user_id = ?
            """, (USER_ID,))
            print(f"   🗑️  Удалена неправильная запись trial_history")
            print()

            await db.commit()

            print("=" * 80)
            print(f"✅ ИСПРАВЛЕНИЕ ЗАВЕРШЕНО")
            print(f"   Обновлено модулей: {updated_count}")
            print(f"   Новый срок подписки: до {correct_expires_at.strftime('%d.%m.%Y')}")
            print("=" * 80)

    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        return

if __name__ == '__main__':
    print()
    print("⚠️  ВНИМАНИЕ: Этот скрипт исправит подписку пользователя 1588878510")
    print("   Пользователь оплатил 3 месяца, но получил только 7 дней.")
    print()
    response = input("Продолжить? (yes/no): ")

    if response.lower() in ['yes', 'y', 'да']:
        asyncio.run(fix_subscription())
        print()
        print("🔍 Проверить результат:")
        print(f"   python3 check_user_subscription.py {USER_ID}")
    else:
        print("Отменено")
