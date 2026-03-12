"""
Менеджер задаче-специфичных подсказок для AI-проверки.

Этот модуль отвечает за:
- Загрузку активных подсказок для конкретных задач/тем
- Форматирование подсказок для добавления в промпты AI
- Логирование использования подсказок
- Создание новых подсказок на основе одобренных жалоб
- Управление жизненным циклом подсказок (активация/деактивация)
"""

import logging
import aiosqlite
from typing import List, Dict, Any, Optional
from datetime import datetime
from core.config import DATABASE_FILE

logger = logging.getLogger(__name__)


class HintManager:
    """Менеджер задаче-специфичных подсказок для AI"""

    def __init__(self, db_path: str = DATABASE_FILE):
        """
        Инициализация HintManager.

        Args:
            db_path: Путь к файлу базы данных SQLite
        """
        self.db_path = db_path

    async def get_active_hints(
        self,
        task_type: str,
        topic_name: Optional[str] = None,
        max_hints: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Получить активные подсказки для конкретной задачи/темы.

        Args:
            task_type: Тип задачи ('task24', 'task19', 'task20', 'task25')
            topic_name: Название темы (опционально, для Task24)
            max_hints: Максимальное количество подсказок (по умолчанию 10)

        Returns:
            List[Dict]: Список подсказок с полями:
                - hint_id: int
                - hint_text: str
                - priority: int
                - hint_category: str
                - usage_count: int
                - topic_name: Optional[str]

        Example:
            >>> hints = await hint_manager.get_active_hints('task24', 'Политические партии')
            >>> print(hints[0]['hint_text'])
            'Учитывай, что в России разрешены многопартийность...'
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row

                # Получаем подсказки двух типов:
                # 1. Специфичные для данной темы (если указана)
                # 2. Общие для данного типа задачи (topic_name IS NULL)
                if topic_name:
                    query = """
                        SELECT id, hint_text, priority, hint_category, usage_count, topic_name
                        FROM task_specific_hints
                        WHERE task_type = ?
                          AND (topic_name = ? OR topic_name IS NULL)
                          AND is_active = 1
                          AND (expires_at IS NULL OR expires_at > datetime('now'))
                        ORDER BY priority DESC, created_at DESC
                        LIMIT ?
                    """
                    cursor = await db.execute(query, (task_type, topic_name, max_hints))
                else:
                    query = """
                        SELECT id, hint_text, priority, hint_category, usage_count, topic_name
                        FROM task_specific_hints
                        WHERE task_type = ?
                          AND topic_name IS NULL
                          AND is_active = 1
                          AND (expires_at IS NULL OR expires_at > datetime('now'))
                        ORDER BY priority DESC, created_at DESC
                        LIMIT ?
                    """
                    cursor = await db.execute(query, (task_type, max_hints))

                rows = await cursor.fetchall()

                hints = []
                for row in rows:
                    hints.append({
                        "hint_id": row["id"],
                        "hint_text": row["hint_text"],
                        "priority": row["priority"],
                        "hint_category": row["hint_category"],
                        "usage_count": row["usage_count"],
                        "topic_name": row["topic_name"]
                    })

                logger.info(
                    f"Loaded {len(hints)} active hints for task_type={task_type}, "
                    f"topic_name={topic_name}"
                )
                return hints

        except Exception as e:
            logger.error(f"Error loading hints: {e}", exc_info=True)
            return []

    async def log_hint_usage(
        self,
        hint_id: int,
        user_id: int,
        topic_name: Optional[str] = None,
        task_type: Optional[str] = None,
        was_helpful: Optional[bool] = None
    ):
        """
        Логировать применение подсказки.

        Args:
            hint_id: ID подсказки
            user_id: ID пользователя
            topic_name: Название темы (опционально)
            task_type: Тип задачи (опционально)
            was_helpful: Была ли подсказка полезной (опционально, для аналитики)

        Note:
            Счетчик usage_count обновляется автоматически через триггер БД.
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    """
                    INSERT INTO hint_application_log
                    (hint_id, user_id, topic_name, task_type, was_helpful)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (hint_id, user_id, topic_name, task_type, was_helpful)
                )
                await db.commit()

                logger.debug(
                    f"Logged hint usage: hint_id={hint_id}, user_id={user_id}, "
                    f"topic={topic_name}"
                )

        except Exception as e:
            logger.error(f"Error logging hint usage: {e}", exc_info=True)

    async def create_hint_from_complaint(
        self,
        complaint_id: int,
        task_type: str,
        topic_name: Optional[str],
        hint_text: str,
        hint_category: str,
        priority: int,
        admin_id: int,
        expires_at: Optional[datetime] = None
    ) -> int:
        """
        Создать новую подсказку на основе одобренной жалобы.

        Args:
            complaint_id: ID жалобы из таблицы user_feedback
            task_type: Тип задачи ('task24', 'task19', etc.)
            topic_name: Название темы (None = применяется ко всем темам)
            hint_text: Текст подсказки для AI
            hint_category: Категория ('factual', 'structural', 'terminology', 'criteria', 'general')
            priority: Приоритет 1-5 (5 = высший)
            admin_id: ID администратора, создавшего подсказку
            expires_at: Опционально: дата истечения подсказки

        Returns:
            int: ID созданной подсказки

        Raises:
            ValueError: Если параметры невалидны
            Exception: При ошибке БД

        Example:
            >>> hint_id = await hint_manager.create_hint_from_complaint(
            ...     complaint_id=123,
            ...     task_type='task24',
            ...     topic_name='Политические партии',
            ...     hint_text='Учитывай, что...',
            ...     hint_category='factual',
            ...     priority=5,
            ...     admin_id=456
            ... )
        """
        # Валидация параметров
        if priority < 1 or priority > 5:
            raise ValueError("Priority must be between 1 and 5")

        valid_categories = ['factual', 'structural', 'terminology', 'criteria', 'general']
        if hint_category not in valid_categories:
            raise ValueError(f"Invalid hint_category. Must be one of: {valid_categories}")

        if not hint_text or len(hint_text.strip()) < 10:
            raise ValueError("Hint text must be at least 10 characters")

        try:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(
                    """
                    INSERT INTO task_specific_hints
                    (task_type, topic_name, hint_text, hint_category, priority,
                     created_from_complaint_id, created_by_admin_id, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_type,
                        topic_name,
                        hint_text,
                        hint_category,
                        priority,
                        complaint_id,
                        admin_id,
                        expires_at
                    )
                )
                await db.commit()

                hint_id = cursor.lastrowid
                logger.info(
                    f"Created hint #{hint_id} from complaint #{complaint_id} "
                    f"for {task_type}/{topic_name}"
                )
                return hint_id

        except Exception as e:
            logger.error(f"Error creating hint: {e}", exc_info=True)
            raise

    async def deactivate_hint(self, hint_id: int, admin_id: int) -> bool:
        """
        Деактивировать подсказку (не удаляя её).

        Args:
            hint_id: ID подсказки
            admin_id: ID администратора

        Returns:
            bool: True если успешно, False если подсказка не найдена
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(
                    "UPDATE task_specific_hints SET is_active = 0 WHERE id = ?",
                    (hint_id,)
                )
                await db.commit()

                if cursor.rowcount > 0:
                    logger.info(f"Deactivated hint #{hint_id} by admin {admin_id}")
                    return True
                else:
                    logger.warning(f"Hint #{hint_id} not found")
                    return False

        except Exception as e:
            logger.error(f"Error deactivating hint: {e}", exc_info=True)
            return False

    async def activate_hint(self, hint_id: int, admin_id: int) -> bool:
        """
        Активировать подсказку.

        Args:
            hint_id: ID подсказки
            admin_id: ID администратора

        Returns:
            bool: True если успешно, False если подсказка не найдена
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(
                    "UPDATE task_specific_hints SET is_active = 1 WHERE id = ?",
                    (hint_id,)
                )
                await db.commit()

                if cursor.rowcount > 0:
                    logger.info(f"Activated hint #{hint_id} by admin {admin_id}")
                    return True
                else:
                    logger.warning(f"Hint #{hint_id} not found")
                    return False

        except Exception as e:
            logger.error(f"Error activating hint: {e}", exc_info=True)
            return False

    async def update_hint(
        self,
        hint_id: int,
        hint_text: Optional[str] = None,
        priority: Optional[int] = None,
        hint_category: Optional[str] = None,
        expires_at: Optional[datetime] = None
    ) -> bool:
        """
        Обновить подсказку.

        Args:
            hint_id: ID подсказки
            hint_text: Новый текст (опционально)
            priority: Новый приоритет (опционально)
            hint_category: Новая категория (опционально)
            expires_at: Новая дата истечения (опционально)

        Returns:
            bool: True если успешно
        """
        updates = []
        params = []

        if hint_text is not None:
            updates.append("hint_text = ?")
            params.append(hint_text)

        if priority is not None:
            if priority < 1 or priority > 5:
                raise ValueError("Priority must be between 1 and 5")
            updates.append("priority = ?")
            params.append(priority)

        if hint_category is not None:
            valid_categories = ['factual', 'structural', 'terminology', 'criteria', 'general']
            if hint_category not in valid_categories:
                raise ValueError(f"Invalid hint_category: {hint_category}")
            updates.append("hint_category = ?")
            params.append(hint_category)

        if expires_at is not None:
            updates.append("expires_at = ?")
            params.append(expires_at)

        if not updates:
            logger.warning("No fields to update")
            return False

        params.append(hint_id)

        try:
            async with aiosqlite.connect(self.db_path) as db:
                query = f"UPDATE task_specific_hints SET {', '.join(updates)} WHERE id = ?"
                cursor = await db.execute(query, params)
                await db.commit()

                if cursor.rowcount > 0:
                    logger.info(f"Updated hint #{hint_id}")
                    return True
                else:
                    logger.warning(f"Hint #{hint_id} not found")
                    return False

        except Exception as e:
            logger.error(f"Error updating hint: {e}", exc_info=True)
            return False

    def format_hints_for_prompt(self, hints: List[Dict[str, Any]]) -> str:
        """
        Форматировать подсказки для добавления в промпт AI.

        Args:
            hints: Список подсказок из get_active_hints()

        Returns:
            str: Отформатированный текст для добавления в system_prompt

        Example:
            >>> hints = await hint_manager.get_active_hints('task24', 'Политические партии')
            >>> formatted = hint_manager.format_hints_for_prompt(hints)
            >>> print(formatted)

            🔍 ВАЖНЫЕ УТОЧНЕНИЯ ДЛЯ ЭТОЙ ЗАДАЧИ:

            Фактические аспекты:
            • Учитывай, что в России разрешены многопартийность...
        """
        if not hints:
            return ""

        formatted = "\n\n🔍 ВАЖНЫЕ УТОЧНЕНИЯ ДЛЯ ЭТОЙ ЗАДАЧИ:\n"

        # Группировка по категориям
        by_category: Dict[str, List[Dict[str, Any]]] = {}
        for hint in hints:
            category = hint.get("hint_category", "general")
            if category not in by_category:
                by_category[category] = []
            by_category[category].append(hint)

        # Заголовки категорий на русском
        category_titles = {
            "factual": "Фактические аспекты",
            "structural": "Структура плана/ответа",
            "terminology": "Терминология",
            "criteria": "Критерии оценки",
            "general": "Общие рекомендации"
        }

        # Порядок вывода категорий по важности
        category_order = ['criteria', 'factual', 'structural', 'terminology', 'general']

        for category in category_order:
            if category not in by_category:
                continue

            category_hints = by_category[category]
            title = category_titles.get(category, "Общие рекомендации")
            formatted += f"\n{title}:\n"

            # Сортировка по приоритету внутри категории
            category_hints.sort(key=lambda h: h.get('priority', 1), reverse=True)

            for hint in category_hints:
                hint_text = hint['hint_text']
                # Добавляем маркер для каждой подсказки
                formatted += f"• {hint_text}\n"

        return formatted

    async def get_hint_stats(self, hint_id: int) -> Optional[Dict[str, Any]]:
        """
        Получить статистику по подсказке.

        Args:
            hint_id: ID подсказки

        Returns:
            Dict или None если подсказка не найдена:
                - hint_id: int
                - hint_text: str
                - usage_count: int
                - unique_users_count: int
                - last_used: datetime или None
                - created_at: datetime
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row

                query = """
                    SELECT
                        tsh.id,
                        tsh.hint_text,
                        tsh.usage_count,
                        tsh.created_at,
                        COUNT(DISTINCT hal.user_id) as unique_users_count,
                        MAX(hal.applied_at) as last_used
                    FROM task_specific_hints tsh
                    LEFT JOIN hint_application_log hal ON tsh.id = hal.hint_id
                    WHERE tsh.id = ?
                    GROUP BY tsh.id
                """
                cursor = await db.execute(query, (hint_id,))
                row = await cursor.fetchone()

                if row:
                    return {
                        "hint_id": row["id"],
                        "hint_text": row["hint_text"],
                        "usage_count": row["usage_count"],
                        "unique_users_count": row["unique_users_count"],
                        "last_used": row["last_used"],
                        "created_at": row["created_at"]
                    }
                else:
                    return None

        except Exception as e:
            logger.error(f"Error getting hint stats: {e}", exc_info=True)
            return None

    async def get_hints_by_topic(self, task_type: str, topic_name: str) -> List[Dict[str, Any]]:
        """
        Получить все подсказки (включая неактивные) для конкретной темы.

        Args:
            task_type: Тип задачи
            topic_name: Название темы

        Returns:
            List[Dict]: Список всех подсказок для темы
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row

                query = """
                    SELECT id, hint_text, hint_category, priority, is_active,
                           usage_count, created_at, expires_at
                    FROM task_specific_hints
                    WHERE task_type = ? AND topic_name = ?
                    ORDER BY priority DESC, created_at DESC
                """
                cursor = await db.execute(query, (task_type, topic_name))
                rows = await cursor.fetchall()

                hints = []
                for row in rows:
                    hints.append({
                        "hint_id": row["id"],
                        "hint_text": row["hint_text"],
                        "hint_category": row["hint_category"],
                        "priority": row["priority"],
                        "is_active": bool(row["is_active"]),
                        "usage_count": row["usage_count"],
                        "created_at": row["created_at"],
                        "expires_at": row["expires_at"]
                    })

                return hints

        except Exception as e:
            logger.error(f"Error getting hints by topic: {e}", exc_info=True)
            return []
