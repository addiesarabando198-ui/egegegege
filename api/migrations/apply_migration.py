"""
Скрипт для применения миграций БД для Teacher WebApp API.
"""

import asyncio
import aiosqlite
import os
import sys
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Определяем путь к БД
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
DATABASE_FILE = os.path.join(PROJECT_ROOT, 'quiz_async.db')


async def apply_migrations():
    """Применяет миграции к базе данных"""
    try:
        migrations_dir = os.path.dirname(__file__)
        migration_file = os.path.join(migrations_dir, '001_create_drafts_table.sql')

        if not os.path.exists(migration_file):
            logger.error(f"Файл миграции не найден: {migration_file}")
            return False

        # Читаем SQL миграции
        with open(migration_file, 'r', encoding='utf-8') as f:
            migration_sql = f.read()

        # Применяем миграцию
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Разделяем на отдельные команды
            commands = [cmd.strip() for cmd in migration_sql.split(';') if cmd.strip()]

            for command in commands:
                logger.info(f"Выполнение: {command[:100]}...")
                await db.execute(command)

            await db.commit()

        logger.info("✅ Миграция успешно применена")
        return True

    except Exception as e:
        logger.error(f"❌ Ошибка при применении миграции: {e}")
        return False


if __name__ == "__main__":
    success = asyncio.run(apply_migrations())
    sys.exit(0 if success else 1)
