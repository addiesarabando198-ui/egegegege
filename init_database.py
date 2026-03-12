#!/usr/bin/env python3
"""
Скрипт для инициализации базы данных
"""
import asyncio
import sys
from pathlib import Path

# Добавляем корневую директорию в PATH
sys.path.insert(0, str(Path(__file__).parent))

# Импортируем напрямую, минуя core/__init__.py
import importlib.util

# Загрузка config
config_spec = importlib.util.spec_from_file_location("config", Path(__file__).parent / "core" / "config.py")
config_module = importlib.util.module_from_spec(config_spec)
config_spec.loader.exec_module(config_module)
DATABASE_FILE = config_module.DATABASE_FILE

# Загрузка db
db_spec = importlib.util.spec_from_file_location("db", Path(__file__).parent / "core" / "db.py")
db_module = importlib.util.module_from_spec(db_spec)
sys.modules['core.config'] = config_module  # Чтобы db.py мог импортировать config
db_spec.loader.exec_module(db_module)
init_db = db_module.init_db

async def main():
    print(f"🔄 Инициализация базы данных: {DATABASE_FILE}")
    try:
        await init_db()
        print("✅ База данных успешно инициализирована!")
    except Exception as e:
        print(f"❌ Ошибка инициализации: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
