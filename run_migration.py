#!/usr/bin/env python3
"""
Скрипт для запуска миграции добавления колонки completed_at
"""
import sqlite3
import sys
from pathlib import Path

def run_migration():
    db_path = Path(__file__).parent / 'quiz_async.db'
    migration_path = Path(__file__).parent / 'teacher_mode' / 'migrations' / 'add_completed_at_column.sql'

    if not db_path.exists():
        print(f"❌ База данных не найдена: {db_path}")
        return False

    if not migration_path.exists():
        print(f"❌ Файл миграции не найден: {migration_path}")
        return False

    try:
        # Читаем SQL миграцию
        with open(migration_path, 'r', encoding='utf-8') as f:
            migration_sql = f.read()

        # Подключаемся к базе данных
        conn = sqlite3.connect(str(db_path))

        # Выполняем миграцию
        print(f"🔄 Применение миграции к {db_path}...")
        conn.executescript(migration_sql)
        conn.commit()
        conn.close()

        print("✅ Миграция успешно применена!")
        print("✅ Колонка 'completed_at' добавлена в таблицу 'homework_student_assignments'")
        return True

    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            print("ℹ️  Колонка 'completed_at' уже существует в таблице")
            return True
        else:
            print(f"❌ Ошибка при выполнении миграции: {e}")
            return False
    except Exception as e:
        print(f"❌ Неожиданная ошибка: {e}")
        return False

if __name__ == "__main__":
    success = run_migration()
    sys.exit(0 if success else 1)
