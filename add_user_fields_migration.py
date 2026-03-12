#!/usr/bin/env python3
"""
Миграция: добавление полей username, first_name, last_name в таблицу users
"""
import sqlite3
import sys

def migrate(db_path='quiz_async.db'):
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        print(f"🔄 Применение миграции к {db_path}...")

        # Проверяем, есть ли уже поле username
        cursor.execute("PRAGMA table_info(users)")
        columns = [row[1] for row in cursor.fetchall()]

        if 'username' not in columns:
            print("  Добавление поля username...")
            cursor.execute("ALTER TABLE users ADD COLUMN username TEXT")
        else:
            print("  Поле username уже существует")

        if 'first_name' not in columns:
            print("  Добавление поля first_name...")
            cursor.execute("ALTER TABLE users ADD COLUMN first_name TEXT")
        else:
            print("  Поле first_name уже существует")

        if 'last_name' not in columns:
            print("  Добавление поля last_name...")
            cursor.execute("ALTER TABLE users ADD COLUMN last_name TEXT")
        else:
            print("  Поле last_name уже существует")

        conn.commit()
        conn.close()

        print("✅ Миграция успешно применена!")
        return True

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False

if __name__ == "__main__":
    db_path = sys.argv[1] if len(sys.argv) > 1 else 'quiz_async.db'
    success = migrate(db_path)
    sys.exit(0 if success else 1)
