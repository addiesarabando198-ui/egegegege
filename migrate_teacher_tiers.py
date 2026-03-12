#!/usr/bin/env python3
"""
Миграция: Добавление teacher_free и teacher_trial_7days в CHECK constraint таблицы teacher_profiles

Проблема:
---------
Таблица teacher_profiles имеет CHECK constraint, который позволяет только:
- teacher_basic
- teacher_standard
- teacher_premium

Но мы хотим добавить:
- teacher_free (бесплатный тариф)
- teacher_trial_7days (пробный период)

Решение:
--------
SQLite не позволяет изменять CHECK constraint напрямую.
Нужно:
1. Создать новую таблицу с обновленным constraint
2. Скопировать данные
3. Удалить старую таблицу
4. Переименовать новую таблицу
"""

import asyncio
import aiosqlite
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DATABASE_FILE = "quiz_async.db"


async def migrate_teacher_profiles():
    """Мигрирует таблицу teacher_profiles с новым CHECK constraint."""

    if not Path(DATABASE_FILE).exists():
        logger.error(f"Database file {DATABASE_FILE} not found!")
        return False

    async with aiosqlite.connect(DATABASE_FILE) as db:
        logger.info("🔍 Checking current schema...")

        # Проверяем, есть ли уже новый constraint
        cursor = await db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='teacher_profiles'")
        schema = await cursor.fetchone()

        if schema and "'teacher_free'" in schema[0]:
            logger.info("✅ Schema already updated - teacher_free is in CHECK constraint")
            return True

        logger.info("📋 Current schema needs update")
        logger.info(f"Current: {schema[0] if schema else 'Table not found'}")

        # Начинаем миграцию
        logger.info("🔄 Starting migration...")

        try:
            # 1. Создаем новую таблицу с правильным constraint
            logger.info("Step 1: Creating new table with updated CHECK constraint...")
            await db.execute("""
                CREATE TABLE teacher_profiles_new (
                    user_id INTEGER PRIMARY KEY,
                    teacher_code TEXT UNIQUE NOT NULL,
                    display_name TEXT NOT NULL,
                    has_active_subscription BOOLEAN DEFAULT FALSE,
                    subscription_expires DATETIME NULL,
                    subscription_tier TEXT DEFAULT 'teacher_free' CHECK(
                        subscription_tier IN (
                            'teacher_free', 'teacher_trial_7days',
                            'teacher_basic', 'teacher_standard', 'teacher_premium'
                        )
                    ),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    feedback_settings TEXT DEFAULT '{}',
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)
            logger.info("✅ New table created")

            # 2. Копируем данные из старой таблицы
            logger.info("Step 2: Copying data from old table...")
            await db.execute("""
                INSERT INTO teacher_profiles_new
                (user_id, teacher_code, display_name, has_active_subscription,
                 subscription_expires, subscription_tier, created_at, feedback_settings)
                SELECT user_id, teacher_code, display_name, has_active_subscription,
                       subscription_expires, subscription_tier, created_at, feedback_settings
                FROM teacher_profiles
            """)

            cursor = await db.execute("SELECT COUNT(*) FROM teacher_profiles_new")
            count = await cursor.fetchone()
            logger.info(f"✅ Copied {count[0]} rows")

            # 3. Удаляем старую таблицу
            logger.info("Step 3: Dropping old table...")
            await db.execute("DROP TABLE teacher_profiles")
            logger.info("✅ Old table dropped")

            # 4. Переименовываем новую таблицу
            logger.info("Step 4: Renaming new table...")
            await db.execute("ALTER TABLE teacher_profiles_new RENAME TO teacher_profiles")
            logger.info("✅ New table renamed")

            # Коммитим изменения
            await db.commit()
            logger.info("✅ Migration committed")

            # Проверяем результат
            cursor = await db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='teacher_profiles'")
            new_schema = await cursor.fetchone()
            logger.info(f"\n📋 New schema:\n{new_schema[0]}")

            logger.info("\n🎉 Migration completed successfully!")
            return True

        except Exception as e:
            logger.error(f"❌ Migration failed: {e}")
            await db.rollback()

            # Пытаемся откатить изменения
            try:
                await db.execute("DROP TABLE IF EXISTS teacher_profiles_new")
                await db.commit()
                logger.info("🔄 Rollback completed")
            except Exception as rollback_error:
                logger.error(f"❌ Rollback failed: {rollback_error}")

            return False


async def verify_migration():
    """Проверяет, что миграция прошла успешно."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        # Проверяем схему
        cursor = await db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='teacher_profiles'")
        schema = await cursor.fetchone()

        if not schema:
            logger.error("❌ Table teacher_profiles not found!")
            return False

        if "'teacher_free'" not in schema[0]:
            logger.error("❌ teacher_free not in CHECK constraint!")
            return False

        if "'teacher_trial_7days'" not in schema[0]:
            logger.error("❌ teacher_trial_7days not in CHECK constraint!")
            return False

        # Проверяем данные
        cursor = await db.execute("SELECT COUNT(*) FROM teacher_profiles")
        count = await cursor.fetchone()

        logger.info(f"✅ Verification passed!")
        logger.info(f"   - Table exists with correct schema")
        logger.info(f"   - {count[0]} rows in table")
        logger.info(f"   - teacher_free and teacher_trial_7days in CHECK constraint")

        return True


async def main():
    """Main migration script."""
    logger.info("=" * 60)
    logger.info("Teacher Profiles Migration Script")
    logger.info("Adding teacher_free and teacher_trial_7days to CHECK constraint")
    logger.info("=" * 60)

    # Запускаем миграцию
    success = await migrate_teacher_profiles()

    if success:
        # Проверяем результат
        await verify_migration()
    else:
        logger.error("Migration failed!")
        return 1

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
