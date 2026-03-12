"""
Middleware для автоматического отслеживания кликов по retention уведомлениям.

Этот middleware работает прозрачно для всех существующих callback-кнопок:
- Проверяет, было ли недавно отправлено retention уведомление пользователю
- При первом клике по любой кнопке логирует клик в notification_log
- Не требует изменения существующих кнопок
"""

import logging
import aiosqlite
from datetime import datetime, timezone, timedelta
from telegram import Update
from telegram.ext import ContextTypes

from core.db import DATABASE_FILE

logger = logging.getLogger(__name__)


class RetentionClickTracker:
    """Трекер кликов по retention уведомлениям"""

    def __init__(self, database_file: str = DATABASE_FILE):
        self.database_file = database_file
        # Кэш для избежания повторных запросов в БД
        self._tracked_users = set()  # user_id, которые уже кликнули в текущей сессии

    async def track_click_if_needed(self, user_id: int) -> bool:
        """
        Проверяет и логирует клик по retention уведомлению.

        Args:
            user_id: ID пользователя

        Returns:
            True если клик был залогирован
        """
        # Проверяем кэш - не отслеживаем повторно в той же сессии
        if user_id in self._tracked_users:
            return False

        try:
            async with aiosqlite.connect(self.database_file) as db:
                # Ищем последнее неоткликнутое retention уведомление за последние 7 дней
                cursor = await db.execute("""
                    SELECT id, sent_at
                    FROM notification_log
                    WHERE user_id = ?
                      AND clicked = 0
                      AND sent_at > datetime('now', '-7 days')
                    ORDER BY sent_at DESC
                    LIMIT 1
                """, (user_id,))

                notification = await cursor.fetchone()

                if not notification:
                    return False

                notification_id, sent_at = notification

                # Логируем клик
                await db.execute("""
                    UPDATE notification_log
                    SET clicked = 1, clicked_at = ?
                    WHERE id = ?
                """, (datetime.now(timezone.utc).isoformat(), notification_id))

                await db.commit()

                # Добавляем в кэш
                self._tracked_users.add(user_id)

                logger.info(
                    f"Tracked retention notification click: user_id={user_id}, "
                    f"notification_id={notification_id}, sent_at={sent_at}"
                )

                return True

        except Exception as e:
            logger.error(f"Error tracking retention click for user {user_id}: {e}", exc_info=True)
            return False

    def clear_cache(self):
        """Очищает кэш отслеженных пользователей"""
        self._tracked_users.clear()


# Глобальный экземпляр трекера
_tracker_instance = None


def get_retention_click_tracker() -> RetentionClickTracker:
    """Возвращает глобальный экземпляр трекера"""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = RetentionClickTracker()
    return _tracker_instance


async def retention_click_middleware(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Middleware для автоматического отслеживания кликов.

    Вызывается для КАЖДОГО callback_query и проверяет, нужно ли залогировать клик.
    """
    # Работаем только с callback_query
    if not update.callback_query:
        return

    user_id = update.effective_user.id
    callback_data = update.callback_query.data

    # Игнорируем служебные callback'и
    ignored_patterns = [
        'notifications_disable',
        'notifications_enable',
        'retention:',  # Админские команды
        'notification_clicked:',  # Старый формат (если останется)
    ]

    if any(callback_data.startswith(pattern) for pattern in ignored_patterns):
        return

    # Отслеживаем клик
    tracker = get_retention_click_tracker()
    await tracker.track_click_if_needed(user_id)


async def reset_retention_click_cache(context: ContextTypes.DEFAULT_TYPE):
    """
    Периодическая очистка кэша отслеженных кликов.

    Запускается раз в час через Job Queue.
    """
    tracker = get_retention_click_tracker()
    tracker.clear_cache()
    logger.debug("Retention click tracker cache cleared")


def register_retention_click_middleware(application):
    """
    Регистрирует middleware для автоматического отслеживания кликов.

    Args:
        application: telegram.ext.Application
    """
    from telegram.ext import CallbackQueryHandler

    # Добавляем middleware для всех callback запросов
    # group=-2 означает, что он выполнится раньше большинства других обработчиков
    application.add_handler(
        CallbackQueryHandler(retention_click_middleware),
        group=-2
    )

    # Добавляем периодическую очистку кэша (каждый час)
    application.job_queue.run_repeating(
        reset_retention_click_cache,
        interval=3600,  # 1 час в секундах
        first=3600,  # Первый запуск через 1 час
        name='retention_click_cache_cleanup'
    )

    logger.info("Retention click middleware registered (group=-2) with hourly cache cleanup")
