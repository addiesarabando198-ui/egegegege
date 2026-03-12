"""
Миграция для улучшенной системы стриков

Phase 1: Foundation
- Создание новых таблиц для tracking стриков
- Миграция существующих данных
- Добавление индексов для производительности
"""

import logging
import aiosqlite
from datetime import datetime, timezone
from core.db import DATABASE_FILE

logger = logging.getLogger(__name__)


async def apply_streak_system_migration():
    """
    Применяет миграцию для улучшенной системы стриков.

    Создает:
    - user_streaks: Расширенная информация о стриках
    - streak_milestones: История достижений
    - streak_protection_log: Использование защит
    - streak_notifications_log: Эффективность уведомлений
    - daily_activity_calendar: Календарь активности
    """

    logger.info("Starting streak system migration...")

    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # ============================================================
            # ТАБЛИЦА 1: user_streaks
            # ============================================================
            logger.info("Creating user_streaks table...")

            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_streaks (
                    user_id INTEGER PRIMARY KEY,

                    -- Daily Learning Streak
                    current_daily_streak INTEGER DEFAULT 0,
                    max_daily_streak INTEGER DEFAULT 0,
                    daily_streak_started_at TEXT,
                    daily_streak_level INTEGER DEFAULT 1,
                    last_activity_date TEXT,

                    -- Correct Answer Streak
                    current_correct_streak INTEGER DEFAULT 0,
                    max_correct_streak INTEGER DEFAULT 0,
                    correct_streak_started_at TEXT,

                    -- Weekly Goal Streak
                    weekly_goal_streak INTEGER DEFAULT 0,
                    current_week_progress INTEGER DEFAULT 0,
                    weekly_goal_target INTEGER DEFAULT 20,
                    week_reset_date TEXT,

                    -- Protection Items (инвентарь защит)
                    freeze_count INTEGER DEFAULT 0,
                    error_shield_count INTEGER DEFAULT 0,
                    repair_used_this_month BOOLEAN DEFAULT 0,
                    last_repair_date TEXT,

                    -- State Management
                    streak_state TEXT DEFAULT 'active',
                    at_risk_notified BOOLEAN DEFAULT 0,
                    critical_notified BOOLEAN DEFAULT 0,

                    -- Lost Streak Recovery
                    streak_before_loss INTEGER DEFAULT 0,
                    streak_lost_at TEXT,

                    -- Statistics
                    total_days_active INTEGER DEFAULT 0,
                    total_hours_spent REAL DEFAULT 0.0,
                    longest_streak_ever INTEGER DEFAULT 0,

                    -- Timestamps
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,

                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)

            # Индексы для user_streaks
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_streak_state
                ON user_streaks(streak_state)
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_daily_streak
                ON user_streaks(current_daily_streak DESC)
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_last_activity
                ON user_streaks(last_activity_date)
            """)

            logger.info("✓ user_streaks table created with indexes")

            # ============================================================
            # ТАБЛИЦА 2: streak_milestones
            # ============================================================
            logger.info("Creating streak_milestones table...")

            await db.execute("""
                CREATE TABLE IF NOT EXISTS streak_milestones (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,

                    -- Milestone Info
                    milestone_type TEXT NOT NULL,
                    milestone_value INTEGER NOT NULL,
                    milestone_name TEXT,

                    -- Achievement Details
                    achieved_at TEXT NOT NULL,
                    badge_earned TEXT,
                    rewards_granted TEXT,

                    -- Engagement Tracking
                    notification_sent BOOLEAN DEFAULT 0,
                    notification_clicked BOOLEAN DEFAULT 0,
                    user_shared BOOLEAN DEFAULT 0,

                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_milestone_user
                ON streak_milestones(user_id)
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_milestone_type
                ON streak_milestones(milestone_type, milestone_value)
            """)

            logger.info("✓ streak_milestones table created with indexes")

            # ============================================================
            # ТАБЛИЦА 3: streak_protection_log
            # ============================================================
            logger.info("Creating streak_protection_log table...")

            await db.execute("""
                CREATE TABLE IF NOT EXISTS streak_protection_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,

                    -- Protection Details
                    protection_type TEXT NOT NULL,
                    streak_value_saved INTEGER,
                    streak_type TEXT,

                    -- Transaction
                    cost_rub INTEGER DEFAULT 0,
                    is_premium_benefit BOOLEAN DEFAULT 0,
                    payment_id TEXT,

                    -- Context
                    triggered_automatically BOOLEAN DEFAULT 0,
                    reason TEXT,

                    -- Timestamp
                    used_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_protection_user
                ON streak_protection_log(user_id)
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_protection_type
                ON streak_protection_log(protection_type)
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_protection_date
                ON streak_protection_log(used_at)
            """)

            logger.info("✓ streak_protection_log table created with indexes")

            # ============================================================
            # ТАБЛИЦА 4: streak_notifications_log
            # ============================================================
            logger.info("Creating streak_notifications_log table...")

            await db.execute("""
                CREATE TABLE IF NOT EXISTS streak_notifications_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,

                    -- Notification Details
                    notification_type TEXT NOT NULL,
                    streak_value INTEGER,
                    message_template TEXT,

                    -- Engagement
                    sent_at TEXT NOT NULL,
                    delivered BOOLEAN DEFAULT 0,
                    clicked BOOLEAN DEFAULT 0,
                    click_timestamp TEXT,

                    -- Conversion
                    led_to_activity BOOLEAN DEFAULT 0,
                    led_to_purchase BOOLEAN DEFAULT 0,
                    purchase_amount_rub INTEGER,

                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_notif_user
                ON streak_notifications_log(user_id)
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_notif_type
                ON streak_notifications_log(notification_type)
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_notif_sent
                ON streak_notifications_log(sent_at)
            """)

            logger.info("✓ streak_notifications_log table created with indexes")

            # ============================================================
            # ТАБЛИЦА 5: daily_activity_calendar
            # ============================================================
            logger.info("Creating daily_activity_calendar table...")

            await db.execute("""
                CREATE TABLE IF NOT EXISTS daily_activity_calendar (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    activity_date TEXT NOT NULL,

                    -- Activity Metrics
                    questions_answered INTEGER DEFAULT 0,
                    questions_correct INTEGER DEFAULT 0,
                    ai_checks_used INTEGER DEFAULT 0,
                    time_spent_minutes INTEGER DEFAULT 0,

                    -- Streak Status
                    contributed_to_streak BOOLEAN DEFAULT 0,
                    was_frozen BOOLEAN DEFAULT 0,
                    was_repaired BOOLEAN DEFAULT 0,

                    -- Goals
                    daily_goal_met BOOLEAN DEFAULT 0,
                    exceeded_goal BOOLEAN DEFAULT 0,

                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,

                    FOREIGN KEY (user_id) REFERENCES users(user_id),
                    UNIQUE(user_id, activity_date)
                )
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_calendar_user_date
                ON daily_activity_calendar(user_id, activity_date DESC)
            """)

            logger.info("✓ daily_activity_calendar table created with indexes")

            # ============================================================
            # ТАБЛИЦА 6: notification_preferences
            # ============================================================
            logger.info("Creating notification_preferences table...")

            await db.execute("""
                CREATE TABLE IF NOT EXISTS notification_preferences (
                    user_id INTEGER PRIMARY KEY,

                    -- Настройки уведомлений
                    enabled BOOLEAN DEFAULT 1,
                    streak_reminders BOOLEAN DEFAULT 1,
                    milestone_celebrations BOOLEAN DEFAULT 1,

                    -- Время уведомлений
                    preferred_time_hour INTEGER DEFAULT 18,
                    timezone TEXT DEFAULT 'Europe/Moscow',

                    -- Деактивация
                    disabled_at TEXT,
                    disabled_reason TEXT,

                    -- Timestamps
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,

                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_notif_prefs_enabled
                ON notification_preferences(enabled)
            """)

            logger.info("✓ notification_preferences table created with indexes")

            # ============================================================
            # ТАБЛИЦА 7: user_achievements
            # ============================================================
            logger.info("Creating user_achievements table...")

            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_achievements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,

                    -- Achievement Info
                    achievement_id TEXT NOT NULL,
                    achievement_name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    rarity TEXT NOT NULL,

                    -- Tracking
                    earned_at TEXT NOT NULL,
                    notification_sent BOOLEAN DEFAULT 0,

                    -- Timestamps
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,

                    FOREIGN KEY (user_id) REFERENCES users(user_id),
                    UNIQUE(user_id, achievement_id)
                )
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_achievements_user
                ON user_achievements(user_id)
            """)

            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_achievements_category
                ON user_achievements(user_id, category)
            """)

            logger.info("✓ user_achievements table created with indexes")

            # ============================================================
            # МИГРАЦИЯ СУЩЕСТВУЮЩИХ ДАННЫХ
            # ============================================================
            logger.info("Migrating existing streak data...")

            # Проверяем, есть ли данные в старой таблице users
            cursor = await db.execute("""
                SELECT user_id,
                       current_daily_streak,
                       max_daily_streak,
                       current_correct_streak,
                       max_correct_streak,
                       last_activity_date
                FROM users
                WHERE current_daily_streak IS NOT NULL
                   OR current_correct_streak IS NOT NULL
            """)

            existing_users = await cursor.fetchall()
            migrated_count = 0

            for row in existing_users:
                user_id = row[0]
                current_daily = row[1] or 0
                max_daily = row[2] or 0
                current_correct = row[3] or 0
                max_correct = row[4] or 0
                last_activity = row[5]

                # Определяем уровень стрика
                if current_daily >= 100:
                    level = 6  # Легенда
                elif current_daily >= 60:
                    level = 5  # Мастер
                elif current_daily >= 30:
                    level = 4  # Знаток
                elif current_daily >= 14:
                    level = 3  # Практикант
                elif current_daily >= 7:
                    level = 2  # Ученик
                else:
                    level = 1  # Новичок

                # Вставляем или обновляем в новой таблице
                await db.execute("""
                    INSERT OR REPLACE INTO user_streaks (
                        user_id,
                        current_daily_streak,
                        max_daily_streak,
                        current_correct_streak,
                        max_correct_streak,
                        last_activity_date,
                        daily_streak_level,
                        longest_streak_ever,
                        total_days_active,
                        streak_state,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                """, (
                    user_id,
                    current_daily,
                    max_daily,
                    current_correct,
                    max_correct,
                    last_activity,
                    level,
                    max_daily,
                    max_daily,  # Приближенная оценка
                    datetime.now(timezone.utc).isoformat(),
                    datetime.now(timezone.utc).isoformat()
                ))

                migrated_count += 1

            await db.commit()

            logger.info(f"✓ Migrated {migrated_count} existing users to new streak system")

            # ============================================================
            # ЗАВЕРШЕНИЕ
            # ============================================================
            logger.info("Streak system migration completed successfully!")

            return True

    except Exception as e:
        logger.error(f"Error during streak migration: {e}", exc_info=True)
        return False


async def rollback_streak_migration():
    """
    Откатывает миграцию стриков (для тестирования).
    ВНИМАНИЕ: Удаляет все данные из новых таблиц!
    """
    logger.warning("Rolling back streak migration...")

    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute("DROP TABLE IF EXISTS daily_activity_calendar")
            await db.execute("DROP TABLE IF EXISTS streak_notifications_log")
            await db.execute("DROP TABLE IF EXISTS streak_protection_log")
            await db.execute("DROP TABLE IF EXISTS streak_milestones")
            await db.execute("DROP TABLE IF EXISTS user_streaks")

            await db.commit()

            logger.info("Streak migration rolled back successfully")
            return True

    except Exception as e:
        logger.error(f"Error rolling back migration: {e}")
        return False


if __name__ == "__main__":
    # Для тестирования миграции
    import asyncio

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    async def test_migration():
        print("Testing streak migration...")
        success = await apply_streak_system_migration()

        if success:
            print("✓ Migration successful!")
        else:
            print("✗ Migration failed!")

    asyncio.run(test_migration())
