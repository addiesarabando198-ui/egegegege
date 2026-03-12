#!/usr/bin/env python3
"""
Применяет исправление для таблицы webhook_logs.

ПРОБЛЕМА:
Отсутствие UNIQUE constraint на (order_id, status) приводило к тому,
что один webhook обрабатывался множество раз (до 79 раз для одного платежа).

РЕШЕНИЕ:
Добавляет UNIQUE constraint для предотвращения дублирования.
"""
import sqlite3
import sys

def apply_webhook_fix(db_path='quiz_async.db'):
    """Применяет исправление для webhook_logs."""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        print("=" * 80)
        print("ПРИМЕНЕНИЕ ИСПРАВЛЕНИЯ WEBHOOK_LOGS")
        print("=" * 80)
        print()

        # Проверяем текущее количество записей
        cursor.execute("SELECT COUNT(*) FROM webhook_logs")
        total_before = cursor.fetchone()[0]
        print(f"📊 Записей в webhook_logs до миграции: {total_before}")

        # Проверяем количество дубликатов
        cursor.execute("""
            SELECT order_id, status, COUNT(*) as cnt
            FROM webhook_logs
            GROUP BY order_id, status
            HAVING cnt > 1
            ORDER BY cnt DESC
            LIMIT 10
        """)
        duplicates = cursor.fetchall()

        if duplicates:
            print(f"\n⚠️  Найдено дубликатов:")
            for order_id, status, count in duplicates:
                print(f"   - {order_id} ({status}): {count} записей")
        else:
            print("\n✅ Дубликатов не найдено")

        print("\n🔧 Применение миграции...")
        print()

        # Создаем новую таблицу
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS webhook_logs_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL,
                status TEXT NOT NULL,
                payment_id TEXT,
                data TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(order_id, status)
            )
        """)
        print("   ✓ Создана новая таблица webhook_logs_new")

        # Копируем уникальные данные
        cursor.execute("""
            INSERT OR IGNORE INTO webhook_logs_new (order_id, status, payment_id, data, created_at)
            SELECT order_id, status, payment_id, data, MIN(created_at)
            FROM webhook_logs
            GROUP BY order_id, status
        """)
        unique_count = cursor.rowcount
        print(f"   ✓ Скопировано {unique_count} уникальных записей")

        # Удаляем старую таблицу
        cursor.execute("DROP TABLE webhook_logs")
        print("   ✓ Удалена старая таблица webhook_logs")

        # Переименовываем новую
        cursor.execute("ALTER TABLE webhook_logs_new RENAME TO webhook_logs")
        print("   ✓ Новая таблица переименована в webhook_logs")

        # Создаем индексы
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_webhook_logs_order_id ON webhook_logs(order_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_webhook_logs_created_at ON webhook_logs(created_at)")
        print("   ✓ Созданы индексы")

        # Записываем в историю миграций
        cursor.execute("""
            INSERT OR IGNORE INTO migration_history (migration_name, description)
            VALUES (?, ?)
        """, (
            'add_webhook_unique_constraint_2024',
            f'Добавлен UNIQUE constraint. Удалено {total_before - unique_count} дубликатов'
        ))
        print("   ✓ Записано в migration_history")

        conn.commit()

        # Финальная статистика
        cursor.execute("SELECT COUNT(*) FROM webhook_logs")
        total_after = cursor.fetchone()[0]

        print()
        print("=" * 80)
        print("✅ МИГРАЦИЯ ЗАВЕРШЕНА УСПЕШНО")
        print("=" * 80)
        print(f"   Было записей: {total_before}")
        print(f"   Стало записей: {total_after}")
        print(f"   Удалено дубликатов: {total_before - total_after}")
        print()

        conn.close()

    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Исправление таблицы webhook_logs')
    parser.add_argument('--db', default='quiz_async.db', help='Путь к БД')

    args = parser.parse_args()

    print()
    print("⚠️  ВНИМАНИЕ: Эта миграция добавит UNIQUE constraint в webhook_logs")
    print("   Дублирующиеся webhook будут удалены (оставлены только первые)")
    print()
    response = input("Продолжить? (yes/no): ")

    if response.lower() in ['yes', 'y', 'да']:
        apply_webhook_fix(args.db)
    else:
        print("Отменено")
