"""
Модуль работы с базой данных с защитой от SQL injection.
Все SQL запросы используют параметризацию для безопасности.
"""

from __future__ import annotations  # Python 3.8 compatibility

import os
import logging
from datetime import datetime, date, timezone, timedelta
from typing import Dict, Any, List, Tuple, Optional, Set
import aiosqlite
from core.config import DATABASE_FILE
from core.types import UserID, TaskType, EvaluationResult, CallbackData
from core import states
import asyncio
logger = logging.getLogger(__name__)

# Имена таблиц - константы для предотвращения injection через имена таблиц
TABLE_PROGRESS = 'user_progress'
TABLE_MISTAKES = 'user_mistakes'
TABLE_ANSWERED = 'answered_questions'
TABLE_USERS = 'users'

# Глобальная переменная для единственного соединения
_db: Optional[aiosqlite.Connection] = None


async def get_db() -> aiosqlite.Connection:
    """Возвращает единственное соединение с БД."""
    global _db
    if _db is None:
        _db = await aiosqlite.connect(DATABASE_FILE)
        _db.row_factory = aiosqlite.Row
    return _db


# Алиас для совместимости
async def get_connection() -> aiosqlite.Connection:
    """Алиас для get_db() для обратной совместимости."""
    return await get_db()


async def close_db():
    """Закрывает соединение с БД."""
    global _db
    if _db:
        await _db.close()
        _db = None


async def execute_with_retry(query: str, params: tuple = (), max_retries: int = 3):
    """Выполняет запрос с повторными попытками при блокировке БД."""

    for attempt in range(max_retries):
        try:
            db = await get_db()
            cursor = await db.execute(query, params)
            await db.commit()
            return cursor
        except aiosqlite.OperationalError as e:
            if "database is locked" in str(e) and attempt < max_retries - 1:
                logger.warning(f"БД заблокирована, попытка {attempt + 1}/{max_retries}")
                await asyncio.sleep(0.1 * (attempt + 1))  # Экспоненциальная задержка
            else:
                raise


async def check_column_exists(db: aiosqlite.Connection, table_name: str, column_name: str) -> bool:
    """
    Проверяет существование колонки в таблице.

    Args:
        db: Соединение с БД
        table_name: Название таблицы
        column_name: Название колонки

    Returns:
        bool: True если колонка существует
    """
    try:
        cursor = await db.execute(f"PRAGMA table_info({table_name})")
        columns = [row[1] for row in await cursor.fetchall()]
        return column_name in columns
    except Exception:
        return False


async def apply_complaint_hints_migration(db: aiosqlite.Connection):
    """
    Применяет миграцию для системы жалоб и подсказок AI.

    Создаёт/обновляет:
    - Таблицу user_feedback (если не существует)
    - Дополнительные поля в user_feedback для контекста проверки
    - Таблицу task_specific_hints
    - Таблицу hint_application_log
    - Представления для аналитики
    - Триггеры

    Args:
        db: Соединение с БД
    """
    try:
        logger.info("Применение миграции системы жалоб и подсказок...")

        # 1. Создаём таблицу user_feedback если не существует
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                feedback_type TEXT CHECK(feedback_type IN ('cancellation', 'support', 'general', 'complaint')),
                category TEXT,
                message TEXT,
                status TEXT DEFAULT 'new' CHECK(status IN ('new', 'in_progress', 'resolved', 'closed')),
                admin_response TEXT,
                admin_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        logger.info("✓ Таблица user_feedback готова")

        # 2. Добавляем новые колонки в user_feedback для жалоб на AI
        new_columns = {
            'task_type': 'TEXT',
            'topic_name': 'TEXT',
            'user_answer': 'TEXT',
            'ai_feedback': 'TEXT',
            'k1_score': 'INTEGER',
            'k2_score': 'INTEGER',
            'complaint_reason': 'TEXT',
            'resolution_type': "TEXT CHECK(resolution_type IN ('approved', 'rejected', 'partial'))"
        }

        for col_name, col_def in new_columns.items():
            if not await check_column_exists(db, 'user_feedback', col_name):
                try:
                    await db.execute(f"ALTER TABLE user_feedback ADD COLUMN {col_name} {col_def}")
                    logger.info(f"✓ Добавлена колонка user_feedback.{col_name}")
                except aiosqlite.OperationalError as e:
                    if "duplicate column" not in str(e).lower():
                        logger.warning(f"Предупреждение при добавлении {col_name}: {e}")

        # 3. Создаём таблицу task_specific_hints
        await db.execute("""
            CREATE TABLE IF NOT EXISTS task_specific_hints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_type TEXT NOT NULL,
                topic_name TEXT,
                hint_text TEXT NOT NULL,
                hint_category TEXT CHECK(hint_category IN ('factual', 'structural', 'terminology', 'criteria', 'general')),
                priority INTEGER DEFAULT 1 CHECK(priority >= 1 AND priority <= 5),
                is_active BOOLEAN DEFAULT 1,
                created_from_complaint_id INTEGER,
                created_by_admin_id INTEGER,
                usage_count INTEGER DEFAULT 0,
                success_rate FLOAT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                FOREIGN KEY (created_from_complaint_id) REFERENCES user_feedback(id)
            )
        """)
        logger.info("✓ Таблица task_specific_hints создана")

        # 4. Создаём таблицу hint_application_log
        await db.execute("""
            CREATE TABLE IF NOT EXISTS hint_application_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hint_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                topic_name TEXT,
                task_type TEXT,
                was_helpful BOOLEAN,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (hint_id) REFERENCES task_specific_hints(id),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        logger.info("✓ Таблица hint_application_log создана")

        # 5. Создаём индексы
        indices = [
            ('idx_hints_task_topic', 'task_specific_hints', 'task_type, topic_name, is_active'),
            ('idx_hints_priority', 'task_specific_hints', 'priority DESC, created_at DESC'),
            ('idx_hints_active', 'task_specific_hints', 'is_active, expires_at'),
            ('idx_hint_log_hint', 'hint_application_log', 'hint_id, applied_at'),
            ('idx_hint_log_user', 'hint_application_log', 'user_id, applied_at'),
            ('idx_feedback_status', 'user_feedback', 'status, created_at'),
            ('idx_feedback_type', 'user_feedback', 'feedback_type, status'),
            ('idx_feedback_user', 'user_feedback', 'user_id, created_at'),
            ('idx_feedback_task_topic', 'user_feedback', 'task_type, topic_name, status'),
        ]

        for idx_name, table_name, columns in indices:
            try:
                await db.execute(f'CREATE INDEX IF NOT EXISTS {idx_name} ON {table_name} ({columns})')
            except Exception as e:
                logger.debug(f"Индекс {idx_name} уже существует или ошибка: {e}")

        logger.info("✓ Индексы созданы")

        # 6. Создаём триггеры
        # Триггер для обновления updated_at
        await db.execute("""
            CREATE TRIGGER IF NOT EXISTS update_feedback_timestamp
            AFTER UPDATE ON user_feedback
            BEGIN
                UPDATE user_feedback
                SET updated_at = CURRENT_TIMESTAMP
                WHERE id = NEW.id;
            END
        """)

        # Триггер для автоматического увеличения usage_count
        await db.execute("""
            CREATE TRIGGER IF NOT EXISTS increment_hint_usage
            AFTER INSERT ON hint_application_log
            BEGIN
                UPDATE task_specific_hints
                SET usage_count = usage_count + 1
                WHERE id = NEW.hint_id;
            END
        """)

        logger.info("✓ Триггеры созданы")

        # 7. Создаём представления для аналитики
        # Представление: Активные подсказки с статистикой
        await db.execute("""
            CREATE VIEW IF NOT EXISTS active_hints_with_stats AS
            SELECT
                tsh.id,
                tsh.task_type,
                tsh.topic_name,
                tsh.hint_text,
                tsh.hint_category,
                tsh.priority,
                tsh.usage_count,
                tsh.created_at,
                tsh.expires_at,
                COUNT(DISTINCT hal.user_id) as unique_users_count
            FROM task_specific_hints tsh
            LEFT JOIN hint_application_log hal ON tsh.id = hal.hint_id
            WHERE tsh.is_active = 1
              AND (tsh.expires_at IS NULL OR tsh.expires_at > datetime('now'))
            GROUP BY tsh.id
            ORDER BY tsh.priority DESC, tsh.usage_count DESC
        """)

        # Представление: Жалобы, ожидающие обработки
        await db.execute("""
            CREATE VIEW IF NOT EXISTS pending_complaints AS
            SELECT
                uf.id,
                uf.user_id,
                uf.task_type,
                uf.topic_name,
                uf.complaint_reason,
                uf.message,
                uf.k1_score,
                uf.k2_score,
                uf.created_at
            FROM user_feedback uf
            WHERE uf.feedback_type = 'complaint'
              AND uf.status = 'new'
            ORDER BY uf.created_at ASC
        """)

        logger.info("✓ Представления созданы")

        await db.commit()
        logger.info("✅ Миграция системы жалоб и подсказок успешно применена!")

    except Exception as e:
        logger.error(f"Ошибка при применении миграции системы жалоб: {e}", exc_info=True)
        # Не прерываем работу бота, если миграция не удалась
        # raise


async def init_db():
    """
    Инициализирует базу данных: создает таблицы, добавляет/проверяет столбцы и создает индексы.
    Использует параметризованные запросы где возможно.
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # --- 1. Создание таблиц (IF NOT EXISTS) ---
            # Для CREATE TABLE параметризация не требуется, т.к. имена таблиц - константы
            await db.execute(f'''
                CREATE TABLE IF NOT EXISTS {TABLE_PROGRESS} (
                    user_id INTEGER NOT NULL, 
                    topic TEXT NOT NULL,
                    correct_count INTEGER DEFAULT 0, 
                    total_answered INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, topic)
                )
            ''')
            
            await db.execute(f'''
                CREATE TABLE IF NOT EXISTS {TABLE_MISTAKES} (
                    user_id INTEGER NOT NULL, 
                    question_id TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, question_id)
                )
            ''')
            
            await db.execute(f'''
                CREATE TABLE IF NOT EXISTS {TABLE_ANSWERED} (
                    user_id INTEGER NOT NULL, 
                    question_id TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, question_id)
                )
            ''')
            
            await db.execute(f'''
                CREATE TABLE IF NOT EXISTS {TABLE_USERS} (
                    user_id INTEGER PRIMARY KEY,
                    first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                    is_subscribed BOOLEAN DEFAULT FALSE,
                    subscription_expires DATETIME NULL,
                    monthly_usage_count INTEGER DEFAULT 0,
                    current_month_start DATETIME NULL,
                    current_daily_streak INTEGER DEFAULT 0,
                    max_daily_streak INTEGER DEFAULT 0,
                    current_correct_streak INTEGER DEFAULT 0,
                    max_correct_streak INTEGER DEFAULT 0,
                    last_activity_date DATE NULL,
                    reminders_enabled BOOLEAN DEFAULT TRUE
                )
            ''')

            # Таблица для отслеживания дневных лимитов AI-проверок
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_ai_limits (
                    user_id INTEGER NOT NULL,
                    check_date DATE NOT NULL,
                    checks_used INTEGER DEFAULT 0,
                    last_check_time DATETIME,
                    PRIMARY KEY (user_id, check_date),
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            ''')
            
            logger.info("Проверка/создание таблиц завершено.")

            # --- 2. Проверка и добавление недостающих столбцов ---
            cursor = await db.execute(f"PRAGMA table_info({TABLE_USERS})")
            rows = await cursor.fetchall()
            existing_columns = {row[1] for row in rows}

            # Столбцы для добавления если отсутствуют
            columns_to_add = {
                'first_seen': 'DATETIME DEFAULT CURRENT_TIMESTAMP',
                'is_subscribed': 'BOOLEAN DEFAULT FALSE',
                'subscription_expires': 'DATETIME NULL',
                'monthly_usage_count': 'INTEGER DEFAULT 0',
                'current_month_start': 'DATETIME NULL',
                'current_daily_streak': 'INTEGER DEFAULT 0',
                'max_daily_streak': 'INTEGER DEFAULT 0',
                'current_correct_streak': 'INTEGER DEFAULT 0',
                'max_correct_streak': 'INTEGER DEFAULT 0',
                'last_activity_date': 'DATE NULL',
                'reminders_enabled': 'BOOLEAN DEFAULT TRUE',
                'username': 'TEXT NULL',
                'first_name': 'TEXT NULL',
                'last_name': 'TEXT NULL',
                'created_at': 'DATETIME DEFAULT CURRENT_TIMESTAMP'
            }

            for col_name, col_def in columns_to_add.items():
                if col_name not in existing_columns:
                    try:
                        # ALTER TABLE безопасен с константными именами таблиц
                        await db.execute(f"ALTER TABLE {TABLE_USERS} ADD COLUMN {col_name} {col_def}")
                        logger.info(f"Добавлен столбец '{col_name}' в таблицу '{TABLE_USERS}'.")
                    except aiosqlite.Error as e:
                        if "duplicate column name" in str(e).lower():
                            logger.debug(f"Столбец '{col_name}' уже существует.")
                        else:
                            logger.error(f"Ошибка при добавлении столбца '{col_name}': {e}")

            # --- 3. Создание индексов ---
            indices = [
                (f'idx_{TABLE_PROGRESS}_user_id', TABLE_PROGRESS, 'user_id'),
                (f'idx_{TABLE_MISTAKES}_user_id', TABLE_MISTAKES, 'user_id'),
                (f'idx_{TABLE_ANSWERED}_user_id', TABLE_ANSWERED, 'user_id'),
                (f'idx_{TABLE_MISTAKES}_question_id', TABLE_MISTAKES, 'question_id'),
                (f'idx_{TABLE_ANSWERED}_question_id', TABLE_ANSWERED, 'question_id'),
                (f'idx_{TABLE_USERS}_last_activity_date', TABLE_USERS, 'last_activity_date'),
                ('idx_user_ai_limits_date', 'user_ai_limits', 'check_date')
            ]
            
            for idx_name, table_name, column_name in indices:
                await db.execute(f'CREATE INDEX IF NOT EXISTS {idx_name} ON {table_name} ({column_name})')
            
            logger.info("Создание индексов завершено.")

            await db.commit()
            logger.info(f"База данных успешно инициализирована.")

            # --- 4. Применение миграций для системы жалоб и подсказок ---
            await apply_complaint_hints_migration(db)

            # --- 5. Применение миграций для режима учителя ---
            await apply_teacher_mode_migration(db)

    except Exception as e:
        logger.exception(f"Ошибка при инициализации БД: {e}")
        raise


async def get_or_create_user_status(user_id: int) -> Dict[str, Any]:
    """
    Получает статус пользователя. Создает запись если не существует.
    Использует параметризованные запросы для безопасности.
    """
    if not isinstance(user_id, int) or user_id <= 0:
        logger.error(f"Некорректный user_id: {user_id}")
        return {"is_subscribed": False, "monthly_usage_count": 0}
    
    try:
        now = datetime.now(timezone.utc)
        today = now.date()
        
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # ВАЖНО: Устанавливаем row_factory для получения словарей
            db.row_factory = aiosqlite.Row
            
            # Создаем пользователя если не существует
            await db.execute(
                f"INSERT OR IGNORE INTO {TABLE_USERS} (user_id) VALUES (?)",
                (user_id,)
            )
            
            # Получаем данные пользователя
            cursor = await db.execute(
                f"""SELECT is_subscribed, subscription_expires, monthly_usage_count, 
                    current_month_start, last_activity_date 
                    FROM {TABLE_USERS} WHERE user_id = ?""",
                (user_id,)
            )
            row = await cursor.fetchone()
            
            if not row:
                await db.commit()
                return {"is_subscribed": False, "monthly_usage_count": 0}
            
            # Преобразуем Row в словарь
            row_dict = dict(row)

            # Обновляем last_activity_date
            if row_dict.get('last_activity_date') != str(today):
                await db.execute(
                    f"UPDATE {TABLE_USERS} SET last_activity_date = ? WHERE user_id = ?",
                    (today, user_id)
                )

            # Сброс месячного счетчика если новый месяц
            month_start = row_dict.get('current_month_start')
            if month_start:
                month_start_dt = datetime.fromisoformat(month_start)
                if month_start_dt.month != now.month or month_start_dt.year != now.year:
                    await db.execute(
                        f"""UPDATE {TABLE_USERS} 
                            SET monthly_usage_count = 0, current_month_start = ? 
                            WHERE user_id = ?""",
                        (now.isoformat(), user_id)
                    )
                    await db.commit()
                    return {"is_subscribed": row_dict.get('is_subscribed', False), "monthly_usage_count": 0}
            else:
                await db.execute(
                    f"UPDATE {TABLE_USERS} SET current_month_start = ? WHERE user_id = ?",
                    (now.isoformat(), user_id)
                )
            
            await db.commit()
            
            # Проверяем срок подписки
            is_subscribed = row_dict.get('is_subscribed', False)
            expires = row_dict.get('subscription_expires')
            
            if is_subscribed and expires:
                expires_dt = datetime.fromisoformat(expires).replace(tzinfo=timezone.utc)
                if expires_dt < now:
                    # Подписка истекла
                    is_subscribed = False
                    await execute_with_retry(
                        f"UPDATE {TABLE_USERS} SET is_subscribed = FALSE WHERE user_id = ?",
                        (user_id,)
                    )
            
            return {
                "is_subscribed": is_subscribed,
                "monthly_usage_count": row_dict.get('monthly_usage_count', 0),
                "subscription_expires": expires
            }
            
    except Exception as e:
        logger.exception(f"Ошибка получения статуса user {user_id}: {e}")
        return {"is_subscribed": False, "monthly_usage_count": 0}

async def increment_usage(user_id: int):
    """Увеличивает счетчик использования. Безопасно от SQL injection."""
    if not isinstance(user_id, int) or user_id <= 0:
        logger.error(f"Некорректный user_id для increment_usage: {user_id}")
        return
        
    try:
        await execute_with_retry(
            f"UPDATE {TABLE_USERS} SET monthly_usage_count = monthly_usage_count + 1 WHERE user_id = ?",
            (user_id,)
        )
    except Exception as e:
        logger.exception(f"Ошибка инкремента использования user {user_id}: {e}")


async def update_progress(user_id: int, topic: str, is_correct: bool):
    """Обновляет прогресс пользователя. Защищено от SQL injection."""
    if not isinstance(user_id, int) or user_id <= 0:
        logger.error(f"Некорректный user_id: {user_id}")
        return
        
    if not topic or not isinstance(topic, str) or topic == "N/A":
        logger.debug(f"Пропуск записи прогресса для user {user_id} без темы.")
        return
    
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Вставляем запись если не существует
            await db.execute(
                f"INSERT OR IGNORE INTO {TABLE_PROGRESS} (user_id, topic) VALUES (?, ?)",
                (user_id, topic)
            )
            
            # Обновляем счетчики
            if is_correct:
                await db.execute(
                    f"""UPDATE {TABLE_PROGRESS} 
                        SET correct_count = correct_count + 1, 
                            total_answered = total_answered + 1 
                        WHERE user_id = ? AND topic = ?""",
                    (user_id, topic)
                )
            else:
                await db.execute(
                    f"""UPDATE {TABLE_PROGRESS} 
                        SET total_answered = total_answered + 1 
                        WHERE user_id = ? AND topic = ?""",
                    (user_id, topic)
                )
            
            await db.commit()
    except Exception as e:
        logger.exception(f"Ошибка обновления прогресса user {user_id}, topic {topic}: {e}")


async def record_mistake(user_id: int, question_id: str):
    """Записывает ошибку. Защищено от SQL injection."""
    if not isinstance(user_id, int) or user_id <= 0:
        logger.error(f"Некорректный user_id: {user_id}")
        return
        
    if not question_id or not isinstance(question_id, str):
        logger.debug(f"Пропуск записи ошибки для user {user_id} без question_id.")
        return
    
    try:
        await execute_with_retry(
            f"""INSERT INTO {TABLE_MISTAKES} (user_id, question_id, timestamp) 
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id, question_id) 
                DO UPDATE SET timestamp = CURRENT_TIMESTAMP""",
            (user_id, question_id)
        )
    except Exception as e:
        logger.exception(f"Ошибка записи ошибки user {user_id}, question {question_id}: {e}")

async def get_mistake_ids(user_id: int) -> List[str]:
    """Возвращает список ID вопросов с ошибками. Защищено от SQL injection."""
    if not isinstance(user_id, int) or user_id <= 0:
        logger.error(f"Некорректный user_id: {user_id}")
        return []
        
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute(
                f"SELECT question_id FROM {TABLE_MISTAKES} WHERE user_id = ? ORDER BY timestamp ASC",
                (user_id,)
            )
            rows = await cursor.fetchall()
            return [row[0] for row in rows]
    except Exception as e:
        logger.exception(f"Ошибка получения ошибок user {user_id}: {e}")
        return []

async def get_correct_answers_count(user_id: int) -> int:
    """Возвращает общее количество правильных ответов. Защищено от SQL injection."""
    if not isinstance(user_id, int) or user_id <= 0:
        return 0
        
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute(
                f"""SELECT SUM(correct_count) 
                    FROM {TABLE_PROGRESS}
                    WHERE user_id = ?""",
                (user_id,)
            )
            result = await cursor.fetchone()
            return result[0] if result and result[0] else 0
            
    except Exception as e:
        logger.exception(f"Ошибка получения количества правильных ответов: {e}")
        return 0


async def get_total_questions_count() -> int:
    """Возвращает общее количество вопросов в базе."""
    # Это заглушка - нужно реализовать подсчет из данных вопросов
    # Временно возвращаем примерное значение
    return 500

async def delete_mistake(user_id: int, question_id: str):
    """Удаляет ошибку из списка. Защищено от SQL injection."""
    if not isinstance(user_id, int) or user_id <= 0:
        return
        
    if not question_id or not isinstance(question_id, str):
        return
        
    try:
        await execute_with_retry(
            f"DELETE FROM {TABLE_MISTAKES} WHERE user_id = ? AND question_id = ?",
            (user_id, question_id)
        )
        logger.debug(f"Удалена ошибка {question_id} для user {user_id}")
        
    except Exception as e:
        logger.exception(f"Ошибка удаления ошибки: {e}")


async def record_answered(user_id: int, question_id: str):
    """Записывает отвеченный вопрос. Защищено от SQL injection."""
    if not isinstance(user_id, int) or user_id <= 0 or not question_id:
        return
        
    try:
        await execute_with_retry(
            f"INSERT OR IGNORE INTO {TABLE_ANSWERED} (user_id, question_id) VALUES (?, ?)",
            (user_id, question_id)
        )
    except Exception as e:
        logger.exception(f"Ошибка записи отвеченного вопроса: {e}")


async def get_answered_question_ids(user_id: int) -> Set[str]:
    """Возвращает множество отвеченных вопросов. Защищено от SQL injection."""
    if not isinstance(user_id, int) or user_id <= 0:
        return set()
        
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute(
                f"SELECT question_id FROM {TABLE_ANSWERED} WHERE user_id = ?",
                (user_id,)
            )
            rows = await cursor.fetchall()
            return {row[0] for row in rows}
    except Exception as e:
        logger.exception(f"Ошибка получения отвеченных вопросов: {e}")
        return set()


async def reset_answered_questions(user_id: int):
    """Очищает историю отвеченных вопросов. Защищено от SQL injection."""
    if not isinstance(user_id, int) or user_id <= 0:
        return
        
    try:
        await execute_with_retry(
            f"DELETE FROM {TABLE_ANSWERED} WHERE user_id = ?",
            (user_id,)
        )
        logger.info(f"История ответов для user {user_id} сброшена.")
    except Exception as e:
        logger.exception(f"Ошибка сброса истории: {e}")


async def get_user_stats(user_id: int) -> List[Tuple[str, int, int]]:
    """Возвращает статистику по темам. Защищено от SQL injection."""
    if not isinstance(user_id, int) or user_id <= 0:
        return []
        
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute(
                f"""SELECT topic, correct_count, total_answered 
                    FROM {TABLE_PROGRESS}
                    WHERE user_id = ? AND total_answered > 0 
                    ORDER BY topic ASC""",
                (user_id,)
            )
            return await cursor.fetchall()
    except Exception as e:
        logger.exception(f"Ошибка получения статистики: {e}")
        return []


async def set_subscription_status(user_id: int, subscribed: bool, expires_at: Optional[datetime] = None):
    """Устанавливает статус подписки. Защищено от SQL injection."""
    if not isinstance(user_id, int) or user_id <= 0:
        return
        
    expires_iso = expires_at.isoformat() if expires_at else None
    
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute(
                f"INSERT OR IGNORE INTO {TABLE_USERS} (user_id) VALUES (?)",
                (user_id,)
            )
            await db.execute(
                f"""UPDATE {TABLE_USERS} 
                    SET is_subscribed = ?, subscription_expires = ? 
                    WHERE user_id = ?""",
                (subscribed, expires_iso, user_id)
            )
            await db.commit()
            logger.info(f"Статус подписки для user {user_id} обновлен")
    except Exception as e:
        logger.exception(f"Ошибка установки подписки: {e}")


async def set_reminders_status(user_id: int, enabled: bool):
    """Включает/выключает напоминания. Защищено от SQL injection."""
    if not isinstance(user_id, int) or user_id <= 0:
        return
        
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute(
                f"INSERT OR IGNORE INTO {TABLE_USERS} (user_id) VALUES (?)",
                (user_id,)
            )
            await db.execute(
                f"UPDATE {TABLE_USERS} SET reminders_enabled = ? WHERE user_id = ?",
                (enabled, user_id)
            )
            await db.commit()
            logger.info(f"Статус напоминаний для user {user_id}: {enabled}")
    except Exception as e:
        logger.exception(f"Ошибка установки напоминаний: {e}")


async def get_users_for_reminders(inactive_days: int) -> List[int]:
    """Возвращает пользователей для напоминаний. Защищено от SQL injection."""
    if not isinstance(inactive_days, int) or inactive_days < 0:
        inactive_days = 3  # Значение по умолчанию
        
    try:
        threshold_date = (date.today() - timedelta(days=inactive_days)).isoformat()
        
        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute(
                f"""SELECT user_id FROM {TABLE_USERS} 
                    WHERE reminders_enabled = 1 
                    AND last_activity_date <= ?""",
                (threshold_date,)
            )
            rows = await cursor.fetchall()
            return [row[0] for row in rows]
    except Exception as e:
        logger.exception(f"Ошибка получения пользователей для напоминаний: {e}")
        return []


async def update_streak(user_id: int, streak_type: str, value: int):
    """Обновляет значение стрика. Защищено от SQL injection."""
    if not isinstance(user_id, int) or user_id <= 0:
        return
        
    if streak_type not in ['daily', 'correct']:
        return
        
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute(
                f"INSERT OR IGNORE INTO {TABLE_USERS} (user_id) VALUES (?)",
                (user_id,)
            )
            
            if streak_type == 'daily':
                await db.execute(
                    f"""UPDATE {TABLE_USERS}
                        SET current_daily_streak = ?,
                            max_daily_streak = MAX(max_daily_streak, ?)
                        WHERE user_id = ?""",
                    (value, value, user_id)
                )
            else:  # correct
                await db.execute(
                    f"""UPDATE {TABLE_USERS}
                        SET current_correct_streak = ?,
                            max_correct_streak = MAX(max_correct_streak, ?)
                        WHERE user_id = ?""",
                    (value, value, user_id)
                )
            
            await db.commit()
            
    except Exception as e:
        logger.exception(f"Ошибка обновления стрика {streak_type} для user {user_id}: {e}")


async def get_user_streaks(user_id: int) -> Dict[str, int]:
    """Получает стрики пользователя. Защищено от SQL injection."""
    streaks = {
        'current_daily': 0, 'max_daily': 0,
        'current_correct': 0, 'max_correct': 0
    }
    
    if not isinstance(user_id, int) or user_id <= 0:
        return streaks
        
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute(
                f"""SELECT current_daily_streak, max_daily_streak,
                           current_correct_streak, max_correct_streak
                    FROM {TABLE_USERS} WHERE user_id = ?""",
                (user_id,)
            )
            row = await cursor.fetchone()
            if row:
                streaks['current_daily'] = row[0] or 0
                streaks['max_daily'] = row[1] or 0
                streaks['current_correct'] = row[2] or 0
                streaks['max_correct'] = row[3] or 0
    except Exception as e:
        logger.exception(f"Ошибка получения стриков: {e}")
    
    return streaks


# Добавляем импорт для совместимости


async def update_daily_streak(user_id: int) -> tuple[int, int]:
    """
    Обновляет дневной стрик пользователя.
    Возвращает (текущий_стрик, максимальный_стрик).
    """
    if not isinstance(user_id, int) or user_id <= 0:
        logger.warning(f"Invalid user_id for update_daily_streak: {user_id}")
        return (0, 0)
    
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # ========== СОЗДАНИЕ ТАБЛИЦЫ ЕСЛИ НЕТ ==========
            await db.execute(f"""
                CREATE TABLE IF NOT EXISTS {TABLE_USERS} (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    current_daily_streak INTEGER DEFAULT 0,
                    max_daily_streak INTEGER DEFAULT 0,
                    current_correct_streak INTEGER DEFAULT 0,
                    max_correct_streak INTEGER DEFAULT 0,
                    last_activity_date TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # ========== ВСТАВКА ЗАПИСИ ЕСЛИ НЕ СУЩЕСТВУЕТ ==========
            await db.execute(
                f"""INSERT OR IGNORE INTO {TABLE_USERS} 
                    (user_id, current_daily_streak, max_daily_streak, last_activity_date) 
                    VALUES (?, 0, 0, NULL)""",
                (user_id,)
            )
            await db.commit()
            
            # ========== ПОЛУЧЕНИЕ ТЕКУЩИХ ДАННЫХ ==========
            today = date.today()
            cursor = await db.execute(
                f"""SELECT last_activity_date, current_daily_streak, max_daily_streak 
                    FROM {TABLE_USERS} WHERE user_id = ?""",
                (user_id,)
            )
            row = await cursor.fetchone()
            
            if not row:
                logger.error(f"No row found for user {user_id} after INSERT OR IGNORE")
                return (0, 0)
            
            # Разбираем данные из БД
            last_activity_str = row[0]
            current_streak = row[1] if row[1] is not None else 0
            max_streak = row[2] if row[2] is not None else 0
            
            logger.info(f"Daily streak check for user {user_id}: "
                       f"last_activity={last_activity_str}, "
                       f"current={current_streak}, max={max_streak}")
            
            # ========== ЛОГИКА ОБНОВЛЕНИЯ СТРИКА ==========
            if last_activity_str:
                try:
                    # Парсим дату последней активности
                    last_activity = date.fromisoformat(last_activity_str)
                    days_diff = (today - last_activity).days
                    
                    logger.debug(f"User {user_id}: last activity was {days_diff} days ago")
                    
                    if days_diff == 0:
                        # Уже были сегодня
                        # ИСПРАВЛЕНИЕ: Если streak == 0, значит это первая активность
                        # (например, пользователь открыл бота, обновился last_activity_date,
                        # но не отвечал на вопросы). Устанавливаем streak = 1.
                        if current_streak == 0:
                            logger.info(f"User {user_id} first question today, initializing streak to 1")
                            current_streak = 1
                            max_streak = max(max_streak, 1)
                        else:
                            logger.debug(f"User {user_id} already active today, keeping streak at {current_streak}")
                            return (current_streak, max_streak)
                        
                    elif days_diff == 1:
                        # Вчера были - увеличиваем стрик
                        current_streak += 1
                        max_streak = max(max_streak, current_streak)
                        logger.info(f"User {user_id} streak continues: {current_streak} days")
                        
                    elif days_diff > 1:
                        # Пропустили день или больше - сбрасываем
                        logger.info(f"User {user_id} missed {days_diff-1} days, resetting streak from {current_streak} to 1")
                        current_streak = 1
                        # max_streak остается прежним
                        
                    else:
                        # days_diff < 0 - дата в будущем? Ошибка данных
                        logger.error(f"User {user_id} has future date: {last_activity_str}")
                        current_streak = 1
                        
                except ValueError as e:
                    # Не удалось распарсить дату
                    logger.error(f"Invalid date format for user {user_id}: {last_activity_str}, error: {e}")
                    current_streak = 1
                    max_streak = max(max_streak, 1)
            else:
                # Первая активность пользователя
                logger.info(f"First activity for user {user_id}, setting streak to 1")
                current_streak = 1
                max_streak = max(max_streak, 1)
            
            # ========== ОБНОВЛЕНИЕ БД ==========
            await db.execute(
                f"""UPDATE {TABLE_USERS} 
                    SET current_daily_streak = ?, 
                        max_daily_streak = ?,
                        last_activity_date = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = ?""",
                (current_streak, max_streak, today.isoformat(), user_id)
            )
            await db.commit()
            
            logger.info(f"Updated daily streak for user {user_id}: current={current_streak}, max={max_streak}")
            
            # ========== ПРОВЕРКА ОБНОВЛЕНИЯ ==========
            # Дополнительная проверка что данные действительно обновились
            cursor = await db.execute(
                f"SELECT current_daily_streak, max_daily_streak FROM {TABLE_USERS} WHERE user_id = ?",
                (user_id,)
            )
            check_row = await cursor.fetchone()
            if check_row:
                actual_current = check_row[0]
                actual_max = check_row[1]
                if actual_current != current_streak or actual_max != max_streak:
                    logger.error(f"Streak mismatch after update for user {user_id}: "
                               f"expected ({current_streak}, {max_streak}), "
                               f"got ({actual_current}, {actual_max})")
            
            return (current_streak, max_streak)
            
    except aiosqlite.Error as e:
        logger.error(f"Database error updating daily streak for user {user_id}: {e}", exc_info=True)
        return (0, 0)
    except Exception as e:
        logger.error(f"Unexpected error updating daily streak for user {user_id}: {e}", exc_info=True)
        return (0, 0)


async def reset_correct_streak(user_id: int) -> None:
    """
    Сбрасывает стрик правильных ответов до 0.
    """
    if not isinstance(user_id, int) or user_id <= 0:
        logger.warning(f"Invalid user_id for reset_correct_streak: {user_id}")
        return
    
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Убеждаемся что запись существует
            await db.execute(
                f"INSERT OR IGNORE INTO {TABLE_USERS} (user_id) VALUES (?)",
                (user_id,)
            )
            
            # Сбрасываем стрик правильных ответов
            await db.execute(
                f"""UPDATE {TABLE_USERS} 
                    SET current_correct_streak = 0,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = ?""",
                (user_id,)
            )
            await db.commit()
            
            logger.info(f"Reset correct streak for user {user_id}")
            
    except Exception as e:
        logger.error(f"Error resetting correct streak for user {user_id}: {e}")


async def update_correct_streak(user_id: int) -> tuple[int, int]:
    """
    Увеличивает стрик правильных ответов на 1.
    Возвращает (текущий_стрик, максимальный_стрик).
    """
    if not isinstance(user_id, int) or user_id <= 0:
        logger.warning(f"Invalid user_id for update_correct_streak: {user_id}")
        return (0, 0)
    
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Создаём таблицу если не существует
            await db.execute(f"""
                CREATE TABLE IF NOT EXISTS {TABLE_USERS} (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    current_daily_streak INTEGER DEFAULT 0,
                    max_daily_streak INTEGER DEFAULT 0,
                    current_correct_streak INTEGER DEFAULT 0,
                    max_correct_streak INTEGER DEFAULT 0,
                    last_activity_date TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Вставляем запись если не существует
            await db.execute(
                f"""INSERT OR IGNORE INTO {TABLE_USERS} 
                    (user_id, current_correct_streak, max_correct_streak) 
                    VALUES (?, 0, 0)""",
                (user_id,)
            )
            
            # Получаем текущие значения
            cursor = await db.execute(
                f"""SELECT current_correct_streak, max_correct_streak 
                    FROM {TABLE_USERS} WHERE user_id = ?""",
                (user_id,)
            )
            row = await cursor.fetchone()
            
            if row:
                current_streak = (row[0] or 0) + 1
                max_streak = max(row[1] or 0, current_streak)
            else:
                current_streak = 1
                max_streak = 1
            
            # Обновляем БД
            await db.execute(
                f"""UPDATE {TABLE_USERS} 
                    SET current_correct_streak = ?, 
                        max_correct_streak = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = ?""",
                (current_streak, max_streak, user_id)
            )
            await db.commit()
            
            logger.info(f"Updated correct streak for user {user_id}: current={current_streak}, max={max_streak}")
            
            return (current_streak, max_streak)
            
    except Exception as e:
        logger.error(f"Error updating correct streak for user {user_id}: {e}", exc_info=True)
        return (0, 0)


async def reset_user_progress(user_id: int):
    """Полностью сбрасывает прогресс пользователя. Защищено от SQL injection."""
    if not isinstance(user_id, int) or user_id <= 0:
        logger.error(f"Некорректный user_id: {user_id}")
        return
        
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Удаляем прогресс
            await db.execute(
                f"DELETE FROM {TABLE_PROGRESS} WHERE user_id = ?",
                (user_id,)
            )
            
            # Удаляем ошибки
            await db.execute(
                f"DELETE FROM {TABLE_MISTAKES} WHERE user_id = ?",
                (user_id,)
            )
            
            # Удаляем историю ответов
            await db.execute(
                f"DELETE FROM {TABLE_ANSWERED} WHERE user_id = ?",
                (user_id,)
            )
            
            # Сбрасываем стрики
            await db.execute(
                f"""UPDATE {TABLE_USERS} 
                    SET current_daily_streak = 0,
                        current_correct_streak = 0,
                        monthly_usage_count = 0
                    WHERE user_id = ?""",
                (user_id,)
            )
            
            await db.commit()
            logger.info(f"Прогресс пользователя {user_id} полностью сброшен")
            
    except Exception as e:
        logger.exception(f"Ошибка сброса прогресса для user {user_id}: {e}")

async def ensure_user(user_id: int) -> None:
    """Создает пользователя в БД если он не существует."""
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute(
                f"INSERT OR IGNORE INTO {TABLE_USERS} (user_id) VALUES (?)",
                (user_id,)
            )
            await db.commit()
    except Exception as e:
        logger.exception(f"Ошибка при создании пользователя: {e}")
        
# Методы для обратной совместимости с payment модулем
async def execute_query(query: str, params: tuple = ()) -> Any:
    """Обертка для execute_with_retry."""
    return await execute_with_retry(query, params)

async def fetch_one(query: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
    """Выполняет SELECT и возвращает одну строку."""
    try:
        async with aiosqlite.connect(DATABASE_FILE) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(query, params)
            row = await cursor.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"Error in fetch_one: {e}")
        return None

async def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    """Получает данные пользователя."""
    return await get_or_create_user_status(user_id)

async def update_user_info(user_id: int, username: str = None, first_name: str = None, last_name: str = None):
    """Обновляет информацию о пользователе из Telegram."""
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Проверяем, существует ли пользователь
            cursor = await db.execute(
                f"SELECT user_id FROM {TABLE_USERS} WHERE user_id = ?",
                (user_id,)
            )
            user_exists = await cursor.fetchone()
            
            if user_exists:
                # Обновляем существующего пользователя
                await db.execute(f"""
                    UPDATE {TABLE_USERS} 
                    SET username = COALESCE(?, username),
                        first_name = COALESCE(?, first_name),
                        last_name = COALESCE(?, last_name),
                        last_activity_date = date('now'),
                        created_at = COALESCE(created_at, CURRENT_TIMESTAMP)
                    WHERE user_id = ?
                """, (username, first_name, last_name, user_id))
            else:
                # Создаём нового пользователя со всеми данными
                await db.execute(f"""
                    INSERT INTO {TABLE_USERS} (
                        user_id, username, first_name, last_name, 
                        created_at, first_seen, last_activity_date
                    ) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, date('now'))
                """, (user_id, username, first_name, last_name))
            
            await db.commit()
            logger.info(f"Updated user info for {user_id}: {first_name} (@{username})")

    except Exception as e:
        logger.error(f"Error updating user info for {user_id}: {e}")


# ==================== Функции для работы с лимитами AI-проверок ====================

async def get_daily_ai_checks_used(user_id: int) -> int:
    """
    Получает количество использованных AI-проверок за сегодня.

    Args:
        user_id: ID пользователя

    Returns:
        Количество использованных проверок сегодня
    """
    try:
        today = date.today()
        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute(
                "SELECT checks_used FROM user_ai_limits WHERE user_id = ? AND check_date = ?",
                (user_id, today)
            )
            row = await cursor.fetchone()
            return row[0] if row else 0
    except Exception as e:
        logger.error(f"Error getting daily AI checks for user {user_id}: {e}")
        return 0


async def increment_ai_check_usage(user_id: int) -> bool:
    """
    Увеличивает счетчик использованных AI-проверок на 1.
    Использует атомарный UPSERT для предотвращения race conditions.

    Args:
        user_id: ID пользователя

    Returns:
        True если успешно, False в случае ошибки
    """
    try:
        today = date.today()
        now = datetime.now(timezone.utc)

        async with aiosqlite.connect(DATABASE_FILE) as db:
            # ИСПРАВЛЕНО: Используем атомарный UPSERT вместо SELECT + UPDATE/INSERT
            # Это предотвращает race conditions при параллельных запросах
            await db.execute(
                """INSERT INTO user_ai_limits (user_id, check_date, checks_used, last_check_time)
                   VALUES (?, ?, 1, ?)
                   ON CONFLICT(user_id, check_date) DO UPDATE
                   SET checks_used = checks_used + 1,
                       last_check_time = excluded.last_check_time""",
                (user_id, today, now)
            )

            await db.commit()
            logger.debug(f"Incremented AI check usage for user {user_id}")
            return True

    except Exception as e:
        logger.error(f"Error incrementing AI check usage for user {user_id}: {e}")
        return False


async def reset_daily_ai_limits() -> int:
    """
    Удаляет старые записи лимитов (старше 30 дней) для очистки БД.
    Актуальные лимиты автоматически сбрасываются при проверке по дате.

    Returns:
        Количество удаленных записей
    """
    try:
        cutoff_date = date.today() - timedelta(days=30)

        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute(
                "DELETE FROM user_ai_limits WHERE check_date < ?",
                (cutoff_date,)
            )
            await db.commit()
            deleted_count = cursor.rowcount

            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} old AI limit records")

            return deleted_count

    except Exception as e:
        logger.error(f"Error resetting daily AI limits: {e}")
        return 0


async def get_ai_limit_stats(user_id: int, days: int = 7) -> Dict[str, Any]:
    """
    Получает статистику использования AI-проверок за последние N дней.

    Args:
        user_id: ID пользователя
        days: Количество дней для анализа (по умолчанию 7)

    Returns:
        Словарь со статистикой
    """
    try:
        start_date = date.today() - timedelta(days=days)

        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute(
                """SELECT check_date, checks_used
                   FROM user_ai_limits
                   WHERE user_id = ? AND check_date >= ?
                   ORDER BY check_date DESC""",
                (user_id, start_date)
            )
            rows = await cursor.fetchall()

            total_checks = sum(row['checks_used'] for row in rows)
            avg_checks = total_checks / days if days > 0 else 0

            return {
                'total_checks': total_checks,
                'average_per_day': round(avg_checks, 1),
                'days_active': len(rows),
                'last_7_days': [
                    {'date': str(row['check_date']), 'checks': row['checks_used']}
                    for row in rows
                ]
            }

    except Exception as e:
        logger.error(f"Error getting AI limit stats for user {user_id}: {e}")
        return {
            'total_checks': 0,
            'average_per_day': 0,
            'days_active': 0,
            'last_7_days': []
        }


# ==================== Функции для недельных лимитов AI-проверок ====================

async def get_weekly_ai_checks_used(user_id: int) -> int:
    """
    Получает количество использованных AI-проверок с начала текущей недели (понедельника).

    Args:
        user_id: ID пользователя

    Returns:
        Количество использованных проверок с понедельника этой недели
    """
    try:
        today = date.today()

        # Вычисляем понедельник текущей недели
        # weekday(): 0=Monday, 1=Tuesday, ..., 6=Sunday
        days_since_monday = today.weekday()
        week_start = today - timedelta(days=days_since_monday)

        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute(
                """SELECT SUM(checks_used) as total
                   FROM user_ai_limits
                   WHERE user_id = ? AND check_date >= ?""",
                (user_id, week_start)
            )
            row = await cursor.fetchone()
            total = row[0] if row and row[0] else 0

            logger.debug(f"User {user_id} used {total} AI checks this week (since {week_start})")
            return total

    except Exception as e:
        logger.error(f"Error getting weekly AI checks for user {user_id}: {e}")
        return 0


async def reset_weekly_ai_limits() -> int:
    """
    Удаляет старые записи лимитов (старше 4 недель) для очистки БД.
    Актуальные недельные лимиты автоматически считаются при проверке.

    Returns:
        Количество удаленных записей
    """
    try:
        # Удаляем записи старше 4 недель (28 дней)
        cutoff_date = date.today() - timedelta(days=28)

        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute(
                "DELETE FROM user_ai_limits WHERE check_date < ?",
                (cutoff_date,)
            )
            await db.commit()
            deleted_count = cursor.rowcount

            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} old weekly AI limit records (older than {cutoff_date})")

            return deleted_count

    except Exception as e:
        logger.error(f"Error resetting weekly AI limits: {e}")
        return 0


async def apply_teacher_mode_migration(db: aiosqlite.Connection):
    """
    Применяет миграцию для режима учителя.

    Создаёт таблицы:
    - user_roles (роли пользователей: teacher, student)
    - teacher_profiles (профили учителей с кодами)
    - teacher_student_relationships (связи учитель-ученик)
    - homework_assignments (домашние задания)
    - homework_student_assignments (назначения заданий ученикам)
    - homework_progress (прогресс выполнения заданий)
    - gifted_subscriptions (подаренные подписки)
    - gift_promo_codes (промокоды для подписок)
    - promo_code_usage (использование промокодов)
    - deadline_reminders (напоминания о дедлайнах)

    Args:
        db: Соединение с БД
    """
    try:
        logger.info("Применение миграции режима учителя...")

        # 1. Таблица ролей пользователей
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_roles (
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('teacher', 'student')),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, role),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        logger.info("✓ Таблица user_roles готова")

        # 2. Таблица профилей учителей
        await db.execute("""
            CREATE TABLE IF NOT EXISTS teacher_profiles (
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
        logger.info("✓ Таблица teacher_profiles готова")

        # 3. Таблица связей учитель-ученик
        await db.execute("""
            CREATE TABLE IF NOT EXISTS teacher_student_relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                teacher_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,
                invited_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'active' CHECK(status IN ('active', 'inactive', 'blocked')),
                UNIQUE(teacher_id, student_id),
                FOREIGN KEY (teacher_id) REFERENCES teacher_profiles(user_id),
                FOREIGN KEY (student_id) REFERENCES users(user_id)
            )
        """)
        logger.info("✓ Таблица teacher_student_relationships готова")

        # 4. Таблица домашних заданий
        await db.execute("""
            CREATE TABLE IF NOT EXISTS homework_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                teacher_id INTEGER NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                title TEXT NOT NULL,
                description TEXT,
                deadline DATETIME NULL,
                assignment_type TEXT NOT NULL CHECK(
                    assignment_type IN ('existing_topics', 'custom', 'test_part')
                ),
                assignment_data TEXT NOT NULL,
                target_type TEXT DEFAULT 'all_students' CHECK(
                    target_type IN ('all_students', 'specific_students', 'group')
                ),
                status TEXT DEFAULT 'active' CHECK(status IN ('active', 'archived')),
                FOREIGN KEY (teacher_id) REFERENCES teacher_profiles(user_id)
            )
        """)
        logger.info("✓ Таблица homework_assignments готова")

        # 5. Таблица назначений заданий ученикам
        await db.execute("""
            CREATE TABLE IF NOT EXISTS homework_student_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                homework_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,
                assigned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                completed_at DATETIME,
                status TEXT DEFAULT 'assigned' CHECK(
                    status IN ('assigned', 'in_progress', 'completed', 'overdue')
                ),
                UNIQUE(homework_id, student_id),
                FOREIGN KEY (homework_id) REFERENCES homework_assignments(id) ON DELETE CASCADE,
                FOREIGN KEY (student_id) REFERENCES users(user_id)
            )
        """)
        logger.info("✓ Таблица homework_student_assignments готова")

        # 6. Таблица прогресса выполнения заданий
        await db.execute("""
            CREATE TABLE IF NOT EXISTS homework_progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                homework_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,
                question_id TEXT NOT NULL,
                user_answer TEXT NOT NULL,
                is_correct BOOLEAN NOT NULL,
                ai_feedback TEXT,
                completed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(homework_id, student_id, question_id),
                FOREIGN KEY (homework_id) REFERENCES homework_assignments(id) ON DELETE CASCADE,
                FOREIGN KEY (student_id) REFERENCES users(user_id)
            )
        """)
        logger.info("✓ Таблица homework_progress готова")

        # 7. Таблица подаренных подписок
        await db.execute("""
            CREATE TABLE IF NOT EXISTS gifted_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                gifter_id INTEGER NOT NULL,
                recipient_id INTEGER NOT NULL,
                duration_days INTEGER NOT NULL,
                activated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME NOT NULL,
                status TEXT DEFAULT 'active' CHECK(status IN ('active', 'expired', 'cancelled')),
                FOREIGN KEY (gifter_id) REFERENCES users(user_id),
                FOREIGN KEY (recipient_id) REFERENCES users(user_id)
            )
        """)
        logger.info("✓ Таблица gifted_subscriptions готова")

        # 8. Таблица промокодов
        await db.execute("""
            CREATE TABLE IF NOT EXISTS gift_promo_codes (
                code TEXT PRIMARY KEY,
                creator_id INTEGER NOT NULL,
                duration_days INTEGER NOT NULL,
                max_uses INTEGER NOT NULL,
                used_count INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME NULL,
                status TEXT DEFAULT 'active' CHECK(status IN ('active', 'expired', 'exhausted')),
                FOREIGN KEY (creator_id) REFERENCES users(user_id)
            )
        """)
        logger.info("✓ Таблица gift_promo_codes готова")

        # 9. Таблица использования промокодов
        await db.execute("""
            CREATE TABLE IF NOT EXISTS promo_code_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                promo_code TEXT NOT NULL,
                student_id INTEGER NOT NULL,
                used_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(promo_code, student_id),
                FOREIGN KEY (promo_code) REFERENCES gift_promo_codes(code),
                FOREIGN KEY (student_id) REFERENCES users(user_id)
            )
        """)
        logger.info("✓ Таблица promo_code_usage готова")

        # 10. Таблица напоминаний о дедлайнах
        await db.execute("""
            CREATE TABLE IF NOT EXISTS deadline_reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                homework_id INTEGER NOT NULL,
                hours_before INTEGER NOT NULL,
                sent_at TEXT NOT NULL,
                UNIQUE(student_id, homework_id, hours_before),
                FOREIGN KEY (student_id) REFERENCES users(user_id),
                FOREIGN KEY (homework_id) REFERENCES homework_assignments(id) ON DELETE CASCADE
            )
        """)
        logger.info("✓ Таблица deadline_reminders готова")

        # 11. Таблица истории изменений подписок учителей
        await db.execute("""
            CREATE TABLE IF NOT EXISTS teacher_subscription_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                plan_id TEXT NOT NULL,
                action TEXT NOT NULL CHECK(
                    action IN ('activated', 'renewed', 'upgraded', 'downgraded', 'expired', 'cancelled')
                ),
                previous_tier TEXT,
                new_tier TEXT,
                expires_at DATETIME,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        logger.info("✓ Таблица teacher_subscription_history готова")

        # Создание индексов для оптимизации запросов
        indices = [
            ('idx_teacher_code', 'teacher_profiles', 'teacher_code'),
            ('idx_teacher_student_teacher', 'teacher_student_relationships', 'teacher_id'),
            ('idx_teacher_student_student', 'teacher_student_relationships', 'student_id'),
            ('idx_homework_teacher', 'homework_assignments', 'teacher_id'),
            ('idx_homework_deadline', 'homework_assignments', 'deadline'),
            ('idx_homework_student_homework', 'homework_student_assignments', 'homework_id'),
            ('idx_homework_student_student', 'homework_student_assignments', 'student_id'),
            ('idx_homework_progress_homework', 'homework_progress', 'homework_id'),
            ('idx_homework_progress_student', 'homework_progress', 'student_id'),
            ('idx_gifted_gifter', 'gifted_subscriptions', 'gifter_id'),
            ('idx_gifted_recipient', 'gifted_subscriptions', 'recipient_id'),
            ('idx_promo_creator', 'gift_promo_codes', 'creator_id'),
            ('idx_promo_usage_student', 'promo_code_usage', 'student_id'),
            ('idx_deadline_reminders_student', 'deadline_reminders', 'student_id'),
            ('idx_deadline_reminders_homework', 'deadline_reminders', 'homework_id'),
            ('idx_deadline_reminders_sent', 'deadline_reminders', 'sent_at'),
            ('idx_teacher_subscription_history_user', 'teacher_subscription_history', 'user_id'),
            ('idx_teacher_subscription_history_created', 'teacher_subscription_history', 'created_at'),
        ]

        for idx_name, table_name, column_name in indices:
            await db.execute(f'CREATE INDEX IF NOT EXISTS {idx_name} ON {table_name} ({column_name})')

        logger.info("✓ Индексы для режима учителя созданы")

        await db.commit()
        logger.info("Миграция режима учителя успешно применена")

    except Exception as e:
        logger.exception(f"Ошибка при применении миграции режима учителя: {e}")
        raise


# ==================== ONBOARDING И АНАЛИТИКА ВОРОНКИ ====================

async def get_user_data(user_id: int) -> Optional[Dict[str, Any]]:
    """
    Получает данные пользователя включая onboarding статус.

    Args:
        user_id: ID пользователя

    Returns:
        Словарь с данными пользователя или None
    """
    try:
        db = await get_db()

        # Проверяем наличие колонок onboarding
        has_onboarding = await check_column_exists(db, 'users', 'onboarding_completed')

        if has_onboarding:
            cursor = await db.execute(
                """SELECT user_id, onboarding_completed, onboarding_skipped,
                          onboarding_completed_at, first_seen, last_activity_date
                   FROM users WHERE user_id = ?""",
                (user_id,)
            )
        else:
            cursor = await db.execute(
                """SELECT user_id, first_seen, last_activity_date
                   FROM users WHERE user_id = ?""",
                (user_id,)
            )

        row = await cursor.fetchone()

        if row:
            return dict(row)
        return None

    except Exception as e:
        logger.error(f"Error getting user data for {user_id}: {e}")
        return None


async def track_funnel_event(user_id: int, event_type: str, event_data: Optional[Dict] = None):
    """
    Трекинг событий воронки для аналитики.

    Args:
        user_id: ID пользователя
        event_type: Тип события (onboarding_started, onboarding_completed, etc.)
        event_data: Дополнительные данные в формате словаря
    """
    try:
        import json
        db = await get_db()

        # Проверяем существование таблицы
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='funnel_events'"
        )
        table_exists = await cursor.fetchone()

        if not table_exists:
            # Создаем таблицу если её нет
            await db.execute("""
                CREATE TABLE funnel_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    event_data TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)
            await db.execute("CREATE INDEX idx_funnel_events_user ON funnel_events(user_id)")
            await db.execute("CREATE INDEX idx_funnel_events_type ON funnel_events(event_type)")
            await db.commit()

        # Сохраняем событие
        event_data_json = json.dumps(event_data) if event_data else None

        await db.execute(
            """INSERT INTO funnel_events (user_id, event_type, event_data)
               VALUES (?, ?, ?)""",
            (user_id, event_type, event_data_json)
        )
        await db.commit()

        logger.info(f"Funnel event tracked: {event_type} for user {user_id}")

    except Exception as e:
        logger.error(f"Error tracking funnel event {event_type} for user {user_id}: {e}")


async def get_funnel_stats() -> Dict[str, Any]:
    """
    Получает статистику по воронке.

    Returns:
        Словарь со статистикой конверсий
    """
    try:
        db = await get_db()

        # Проверяем существование view
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='view' AND name='funnel_analysis'"
        )
        view_exists = await cursor.fetchone()

        if view_exists:
            cursor = await db.execute("SELECT * FROM funnel_analysis")
            row = await cursor.fetchone()
            if row:
                return dict(row)

        # Если view нет - считаем вручную
        cursor = await db.execute("""
            SELECT
                COUNT(DISTINCT u.user_id) as total_users,
                COUNT(DISTINCT CASE WHEN aq.user_id IS NOT NULL THEN u.user_id END) as answered_questions,
                COUNT(DISTINCT CASE WHEN al.user_id IS NOT NULL THEN u.user_id END) as used_ai_check,
                COUNT(DISTINCT CASE WHEN s.user_id IS NOT NULL AND s.is_active = 1 THEN u.user_id END) as active_subscribers
            FROM users u
            LEFT JOIN answered_questions aq ON u.user_id = aq.user_id
            LEFT JOIN user_ai_limits al ON u.user_id = al.user_id
            LEFT JOIN subscriptions s ON u.user_id = s.user_id
        """)

        row = await cursor.fetchone()
        if row:
            data = dict(row)
            total = data['total_users']
            if total > 0:
                data['activation_rate'] = round(data['answered_questions'] / total * 100, 2)
                data['ai_usage_rate'] = round(data['used_ai_check'] / total * 100, 2)
                data['paid_conversion_rate'] = round(data['active_subscribers'] / total * 100, 2)
            return data

        return {}

    except Exception as e:
        logger.error(f"Error getting funnel stats: {e}")
        return {}


async def get_cohort_stats(weeks: int = 8) -> List[Dict[str, Any]]:
    """
    Получает когортную статистику.

    Args:
        weeks: Количество недель для анализа

    Returns:
        Список когорт с метриками
    """
    try:
        db = await get_db()

        cursor = await db.execute("""
            SELECT
                strftime('%Y-W%W', u.first_seen) as cohort_week,
                COUNT(DISTINCT u.user_id) as users,
                COUNT(DISTINCT CASE WHEN aq.user_id IS NOT NULL THEN u.user_id END) as answered_questions,
                COUNT(DISTINCT CASE WHEN s.user_id IS NOT NULL AND s.is_active = 1 THEN u.user_id END) as paying_now,
                ROUND(COUNT(DISTINCT CASE WHEN aq.user_id IS NOT NULL THEN u.user_id END) * 100.0 / COUNT(DISTINCT u.user_id), 1) as activation_rate,
                ROUND(COUNT(DISTINCT CASE WHEN s.user_id IS NOT NULL AND s.is_active = 1 THEN u.user_id END) * 100.0 / COUNT(DISTINCT u.user_id), 1) as conversion_rate
            FROM users u
            LEFT JOIN answered_questions aq ON u.user_id = aq.user_id
            LEFT JOIN subscriptions s ON u.user_id = s.user_id
            WHERE u.first_seen IS NOT NULL
            GROUP BY cohort_week
            ORDER BY cohort_week DESC
            LIMIT ?
        """, (weeks,))

        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    except Exception as e:
        logger.error(f"Error getting cohort stats: {e}")
        return []


async def apply_onboarding_migration(db: aiosqlite.Connection):
    """
    Применяет миграцию для onboarding и аналитики воронки.
    """
    try:
        logger.info("Применение миграции onboarding...")

        # Добавляем поля onboarding если их нет
        has_onboarding = await check_column_exists(db, 'users', 'onboarding_completed')

        if not has_onboarding:
            await db.execute("ALTER TABLE users ADD COLUMN onboarding_completed BOOLEAN DEFAULT 0")
            await db.execute("ALTER TABLE users ADD COLUMN onboarding_skipped BOOLEAN DEFAULT 0")
            await db.execute("ALTER TABLE users ADD COLUMN onboarding_completed_at TIMESTAMP")
            logger.info("✓ Поля onboarding добавлены в users")

        # Создаем таблицу для funnel events
        await db.execute("""
            CREATE TABLE IF NOT EXISTS funnel_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                event_data TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        logger.info("✓ Таблица funnel_events создана")

        # Индексы
        await db.execute("CREATE INDEX IF NOT EXISTS idx_funnel_events_user ON funnel_events(user_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_funnel_events_type ON funnel_events(event_type)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_funnel_events_created ON funnel_events(created_at)")
        logger.info("✓ Индексы funnel_events созданы")

        await db.commit()
        logger.info("Миграция onboarding успешно применена")

    except Exception as e:
        logger.exception(f"Ошибка при применении миграции onboarding: {e}")
        raise


