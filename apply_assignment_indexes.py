#!/usr/bin/env python3
"""
Скрипт для применения миграции индексов для homework_assignments.
Запустите этот скрипт один раз для добавления недостающих индексов.

ИСПРАВЛЕНО: Добавлены индексы для оптимизации запросов по assignment_type
"""

import asyncio
import aiosqlite
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


async def apply_indexes():
    """Применяет миграцию индексов"""
    db_path = Path(__file__).parent / "quiz_async.db"
    migration_path = Path(__file__).parent / "teacher_mode" / "migrations" / "add_assignment_type_index.sql"

    if not db_path.exists():
        logger.error(f"Database not found at {db_path}")
        return False

    if not migration_path.exists():
        logger.error(f"Migration file not found at {migration_path}")
        return False

    try:
        logger.info("Reading migration file...")
        with open(migration_path, 'r', encoding='utf-8') as f:
            migration_sql = f.read()

        logger.info("Connecting to database...")
        async with aiosqlite.connect(db_path) as db:
            # Разбиваем на statements (SQLite не поддерживает executescript в aiosqlite)
            statements = [s.strip() for s in migration_sql.split(';') if s.strip() and not s.strip().startswith('--')]

            logger.info(f"Executing {len(statements)} SQL statements...")

            for i, statement in enumerate(statements, 1):
                if statement:
                    logger.info(f"  {i}/{len(statements)}: {statement[:60]}...")
                    await db.execute(statement)

            await db.commit()

        logger.info("✅ Migration applied successfully!")
        logger.info("\nIndexes created:")
        logger.info("  - idx_homework_assignments_type")
        logger.info("  - idx_homework_assignments_teacher_type")

        return True

    except Exception as e:
        logger.error(f"❌ Error applying migration: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    success = asyncio.run(apply_indexes())
    exit(0 if success else 1)
