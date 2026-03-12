#!/usr/bin/env python3
"""
Скрипт для исправления длительности подписок в БД.

Проблема:
- trial_7days давал 30 дней вместо 7
- package_full мог давать двойную длительность

Решение:
- Исправить все trial_7days подписки на 7 дней
- Проверить и скорректировать package_full подписки
"""
import asyncio
import aiosqlite
from datetime import datetime, timedelta, timezone
import sys
import os

# Добавляем путь к проекту для импорта модулей
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def fix_subscription_durations(db_path='quiz_async.db', dry_run=False):
    """
    Исправляет длительность подписок.

    Args:
        db_path: Путь к файлу БД
        dry_run: Если True, только показывает что будет исправлено без изменения БД
    """
    try:
        async with aiosqlite.connect(db_path) as db:
            print("=" * 80)
            print("ИСПРАВЛЕНИЕ ДЛИТЕЛЬНОСТИ ПОДПИСОК")
            print("=" * 80)
            print()

            if dry_run:
                print("🔍 РЕЖИМ ПРОВЕРКИ (изменения НЕ будут сохранены)")
                print()

            # Проверяем, есть ли таблица
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='module_subscriptions'"
            )
            if not await cursor.fetchone():
                print("❌ Таблица module_subscriptions не найдена")
                print("   Миграции еще не применены или БД не инициализирована")
                return

            # ========================================
            # 1. ИСПРАВЛЕНИЕ ПРОБНЫХ ПОДПИСОК
            # ========================================
            print("🔍 Проверка пробных подписок (trial_7days)...")
            print()

            cursor = await db.execute("""
                SELECT user_id, module_code, created_at, expires_at, is_active
                FROM module_subscriptions
                WHERE plan_id = 'trial_7days'
            """)
            trial_subscriptions = await cursor.fetchall()

            if not trial_subscriptions:
                print("   ℹ️  Пробных подписок не найдено")
                print()
            else:
                fixed_count = 0
                for row in trial_subscriptions:
                    user_id, module_code, created_at, expires_at, is_active = row

                    # Парсим даты
                    created_dt = datetime.fromisoformat(created_at)
                    expires_dt = datetime.fromisoformat(expires_at)

                    # Убеждаемся что даты имеют timezone
                    if created_dt.tzinfo is None:
                        created_dt = created_dt.replace(tzinfo=timezone.utc)
                    if expires_dt.tzinfo is None:
                        expires_dt = expires_dt.replace(tzinfo=timezone.utc)

                    # Вычисляем длительность
                    duration = expires_dt - created_dt
                    duration_days = duration.days

                    # Если длительность больше 7 дней - исправляем
                    if duration_days > 7:
                        correct_expires = created_dt + timedelta(days=7)
                        correct_expires_str = correct_expires.isoformat()

                        print(f"   ❌ User {user_id}, модуль {module_code}:")
                        print(f"      Текущая длительность: {duration_days} дней")
                        print(f"      Старый expires_at: {expires_at}")
                        print(f"      Новый expires_at: {correct_expires_str}")
                        print(f"      Активна: {'Да' if is_active else 'Нет'}")
                        print()

                        if not dry_run:
                            # Обновляем запись
                            await db.execute("""
                                UPDATE module_subscriptions
                                SET expires_at = ?
                                WHERE user_id = ? AND module_code = ? AND plan_id = 'trial_7days'
                            """, (correct_expires_str, user_id, module_code))

                        fixed_count += 1

                if fixed_count > 0:
                    print(f"   ✅ Исправлено {fixed_count} пробных подписок")
                else:
                    print(f"   ✅ Все пробные подписки имеют правильную длительность (7 дней)")
                print()

            # ========================================
            # 2. ПРОВЕРКА ПОЛНЫХ ПОДПИСОК
            # ========================================
            print("🔍 Проверка полных подписок (package_full)...")
            print()

            cursor = await db.execute("""
                SELECT
                    ms.user_id,
                    ms.module_code,
                    ms.created_at,
                    ms.expires_at,
                    ms.is_active,
                    p.metadata
                FROM module_subscriptions ms
                LEFT JOIN payments p ON ms.user_id = p.user_id
                    AND p.plan_id = 'package_full'
                    AND p.status = 'completed'
                WHERE ms.plan_id = 'package_full'
                ORDER BY ms.created_at DESC
            """)
            package_subscriptions = await cursor.fetchall()

            if not package_subscriptions:
                print("   ℹ️  Полных подписок не найдено")
                print()
            else:
                import json
                package_fixed = 0

                for row in package_subscriptions:
                    user_id, module_code, created_at, expires_at, is_active, metadata_str = row

                    # Парсим даты
                    created_dt = datetime.fromisoformat(created_at)
                    expires_dt = datetime.fromisoformat(expires_at)

                    if created_dt.tzinfo is None:
                        created_dt = created_dt.replace(tzinfo=timezone.utc)
                    if expires_dt.tzinfo is None:
                        expires_dt = expires_dt.replace(tzinfo=timezone.utc)

                    # Вычисляем длительность
                    duration = expires_dt - created_dt
                    duration_days = duration.days

                    # Пытаемся извлечь duration_months из метаданных
                    duration_months = 1  # По умолчанию
                    if metadata_str:
                        try:
                            metadata = json.loads(metadata_str)
                            duration_months = metadata.get('duration_months', 1)
                        except:
                            pass

                    expected_days = 30 * duration_months

                    # Проверяем корректность (допускаем погрешность ±1 день)
                    if abs(duration_days - expected_days) > 1:
                        correct_expires = created_dt + timedelta(days=expected_days)
                        correct_expires_str = correct_expires.isoformat()

                        print(f"   ⚠️  User {user_id}, модуль {module_code}:")
                        print(f"      Оплачено месяцев: {duration_months}")
                        print(f"      Текущая длительность: {duration_days} дней")
                        print(f"      Ожидаемая: {expected_days} дней")
                        print(f"      Старый expires_at: {expires_at}")
                        print(f"      Новый expires_at: {correct_expires_str}")
                        print(f"      Активна: {'Да' if is_active else 'Нет'}")
                        print()

                        if not dry_run:
                            await db.execute("""
                                UPDATE module_subscriptions
                                SET expires_at = ?
                                WHERE user_id = ? AND module_code = ? AND plan_id = 'package_full'
                            """, (correct_expires_str, user_id, module_code))

                        package_fixed += 1

                if package_fixed > 0:
                    print(f"   ✅ Исправлено {package_fixed} полных подписок")
                else:
                    print(f"   ✅ Все полные подписки имеют правильную длительность")
                print()

            # ========================================
            # СОХРАНЕНИЕ ИЗМЕНЕНИЙ
            # ========================================
            if not dry_run:
                await db.commit()

                # Записываем в историю миграций
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS migration_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        migration_name TEXT NOT NULL UNIQUE,
                        applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        description TEXT
                    )
                """)

                await db.execute("""
                    INSERT OR IGNORE INTO migration_history (migration_name, description)
                    VALUES (?, ?)
                """, (
                    'fix_subscription_durations_2024',
                    f'Исправление длительности подписок. Trial: {fixed_count}, Package: {package_fixed}'
                ))

                await db.commit()

                print("=" * 80)
                print("✅ МИГРАЦИЯ ЗАВЕРШЕНА УСПЕШНО")
                print("=" * 80)
            else:
                print("=" * 80)
                print("ℹ️  ПРОВЕРКА ЗАВЕРШЕНА (изменения НЕ сохранены)")
                print("   Запустите без флага --dry-run для применения исправлений")
                print("=" * 80)

    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

async def main():
    """Точка входа."""
    import argparse

    parser = argparse.ArgumentParser(description='Исправление длительности подписок')
    parser.add_argument('--db', default='quiz_async.db', help='Путь к БД')
    parser.add_argument('--dry-run', action='store_true', help='Режим проверки без изменений')

    args = parser.parse_args()

    await fix_subscription_durations(args.db, args.dry_run)

if __name__ == '__main__':
    asyncio.run(main())
