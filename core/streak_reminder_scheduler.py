"""
Streak Reminder Scheduler - система напоминаний о стриках

Phase 2: Notifications
- At Risk warnings (за 6 часов до сброса)
- Critical warnings (за 2 часа до сброса)
- Smart timing на основе истории активности
- Сбалансированный подход (не спамим)
- Учёт часовых поясов пользователей
"""

import logging
import aiosqlite
from datetime import datetime, date, time, timedelta, timezone
from typing import List, Tuple, Optional
from telegram import Bot
from telegram.ext import ContextTypes
from telegram.error import Forbidden, BadRequest

from core.db import DATABASE_FILE
from core.streak_manager import get_streak_manager, StreakState
from core.streak_ui import get_streak_ui
from core.timezone_manager import get_timezone_manager

logger = logging.getLogger(__name__)


class StreakReminderScheduler:
    """Планировщик напоминаний о стриках"""

    def __init__(self, database_file: str = DATABASE_FILE):
        self.database_file = database_file
        self.streak_manager = get_streak_manager()
        self.streak_ui = get_streak_ui()
        self.timezone_manager = get_timezone_manager()

    # ============================================================
    # MAIN SCHEDULER FUNCTION
    # ============================================================

    async def check_and_send_reminders(self, context: ContextTypes.DEFAULT_TYPE):
        """
        Основная функция для проверки и отправки напоминаний.
        Запускается каждый час.
        """
        bot = context.bot
        logger.info("=== Starting streak reminder check ===")

        try:
            # Обновляем состояния стриков для всех пользователей
            users_to_notify = await self.streak_manager.check_and_update_streak_states()

            sent_count = 0

            for user_id, new_state in users_to_notify:
                # Проверяем, можно ли отправить уведомление
                if not await self._can_send_notification(user_id):
                    logger.debug(f"Skipping notification for user {user_id}: notifications disabled or limit reached")
                    continue

                # Определяем тип уведомления
                if new_state == StreakState.AT_RISK:
                    success = await self._send_at_risk_notification(bot, user_id)
                elif new_state == StreakState.CRITICAL:
                    success = await self._send_critical_notification(bot, user_id)
                else:
                    continue

                if success:
                    sent_count += 1

            logger.info(f"=== Streak reminder check complete: {sent_count} notifications sent ===")

        except Exception as e:
            logger.error(f"Error in streak reminder scheduler: {e}", exc_info=True)

    # ============================================================
    # NOTIFICATION SENDING
    # ============================================================

    async def _send_at_risk_notification(self, bot: Bot, user_id: int) -> bool:
        """
        Отправляет предупреждение 'At Risk' (за ~6 часов до сброса).
        Учитывает часовой пояс пользователя.
        """
        try:
            # Получаем информацию о стрике
            streak_info = await self.streak_manager.get_daily_streak_info(user_id)
            current_streak = streak_info['current']

            if current_streak == 0:
                return False

            # Проверяем, не ночь ли у пользователя (тихие часы)
            if await self.timezone_manager.is_quiet_hours(user_id):
                logger.debug(f"Skipping notification for user {user_id}: quiet hours")
                return False

            # Вычисляем оставшееся время до полуночи в часовом поясе пользователя
            hours_left, minutes_left = await self.timezone_manager.calculate_time_until_midnight_user(user_id)

            # Проверяем, оптимальное ли время для уведомления (±2 часа от 18:00 локального)
            if not await self.timezone_manager.is_optimal_notification_time(user_id, preferred_hour=18, tolerance=2):
                logger.debug(f"Skipping at_risk notification for user {user_id}: not optimal time in their timezone")
                return False

            # Формируем сообщение
            text = f"""
⚠️ <b>Не забудь о стрике!</b>

У тебя <b>{current_streak}-дневный стрик</b> 🔥
Осталось примерно <b>{hours_left} часов</b> до сброса

Реши всего <b>1 задание</b> чтобы продолжить!

💪 Ты уже зашел так далеко - не останавливайся!
"""

            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✍️ Решить задание", callback_data="start_practice")],
                [InlineKeyboardButton("❄️ Узнать про заморозку", callback_data="about_freeze")]
            ])

            await bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=keyboard,
                parse_mode='HTML'
            )

            # Логируем отправку
            await self._log_notification(user_id, 'at_risk', current_streak)

            logger.info(f"Sent at_risk notification to user {user_id}")
            return True

        except Forbidden:
            logger.warning(f"User {user_id} blocked the bot")
            await self._disable_notifications(user_id, 'bot_blocked')
            return False
        except BadRequest as e:
            logger.error(f"BadRequest sending notification to {user_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Error sending at_risk notification to {user_id}: {e}")
            return False

    async def _send_critical_notification(self, bot: Bot, user_id: int) -> bool:
        """
        Отправляет критическое предупреждение (за ~2 часа до сброса).
        Учитывает часовой пояс пользователя.
        """
        try:
            # Получаем информацию о стрике
            streak_info = await self.streak_manager.get_daily_streak_info(user_id)
            current_streak = streak_info['current']

            if current_streak == 0:
                return False

            # Для критических уведомлений НЕ проверяем тихие часы -
            # это последний шанс сохранить стрик

            # Вычисляем оставшееся время до полуночи в часовом поясе пользователя
            hours_left, minutes_left = await self.timezone_manager.calculate_time_until_midnight_user(user_id)

            # Формируем сообщение
            message_data = self.streak_ui.get_at_risk_warning_message(
                current_streak,
                hours_left,
                minutes_left
            )

            await bot.send_message(
                chat_id=user_id,
                text=message_data['text'],
                reply_markup=message_data['keyboard'],
                parse_mode=message_data['parse_mode']
            )

            # Логируем отправку
            await self._log_notification(user_id, 'critical', current_streak)

            logger.info(f"Sent critical notification to user {user_id}")
            return True

        except Forbidden:
            logger.warning(f"User {user_id} blocked the bot")
            await self._disable_notifications(user_id, 'bot_blocked')
            return False
        except BadRequest as e:
            logger.error(f"BadRequest sending notification to {user_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Error sending critical notification to {user_id}: {e}")
            return False

    # ============================================================
    # SMART TIMING
    # ============================================================

    async def _get_optimal_notification_time(self, user_id: int) -> Optional[int]:
        """
        Определяет оптимальное время для отправки уведомлений.

        DEPRECATED: Используйте timezone_manager.is_optimal_notification_time()

        Returns:
            Час дня (0-23) или None
        """
        try:
            async with aiosqlite.connect(self.database_file) as db:
                # Проверяем, есть ли у пользователя сохранённый preferred_hour
                cursor = await db.execute("""
                    SELECT optimal_notification_hour FROM user_timezone_info
                    WHERE user_id = ?
                """, (user_id,))
                row = await cursor.fetchone()

                if row and row[0]:
                    return row[0]

                # Анализируем последние 30 дней активности
                cursor = await db.execute("""
                    SELECT activity_date, time_spent_minutes
                    FROM daily_activity_calendar
                    WHERE user_id = ?
                      AND activity_date > date('now', '-30 days')
                    ORDER BY activity_date DESC
                    LIMIT 30
                """, (user_id,))

                activities = await cursor.fetchall()

                if not activities:
                    return 18  # Дефолтное время (после школы)

                # Возвращаем 18:00 как оптимальное время
                # TODO: Реализовать ML модель для персонализации
                return 18

        except Exception as e:
            logger.error(f"Error getting optimal time for user {user_id}: {e}")
            return 18

    # ============================================================
    # HELPER METHODS
    # ============================================================

    def _calculate_time_left(self) -> Tuple[int, int]:
        """
        Вычисляет оставшееся время до полуночи UTC (сброса стрика).

        DEPRECATED: Используйте timezone_manager.calculate_time_until_midnight_user()

        Returns:
            (hours_left, minutes_left)
        """
        # Используем UTC для консистентности
        now = datetime.now(timezone.utc)
        midnight = datetime.combine(
            date.today() + timedelta(days=1),
            time.min,
            tzinfo=timezone.utc
        )
        time_left = midnight - now

        hours_left = int(time_left.total_seconds() // 3600)
        minutes_left = int((time_left.total_seconds() % 3600) // 60)

        return hours_left, minutes_left

    async def _can_send_notification(self, user_id: int) -> bool:
        """
        Проверяет, можно ли отправить уведомление пользователю.
        """
        try:
            async with aiosqlite.connect(self.database_file) as db:
                # Проверка 1: Пользователь не отключил уведомления
                cursor = await db.execute("""
                    SELECT enabled FROM notification_preferences
                    WHERE user_id = ?
                """, (user_id,))
                pref = await cursor.fetchone()

                if pref and not pref[0]:
                    return False

                # Проверка 2: Дневной лимит (максимум 2 напоминания о стрике в день)
                cursor = await db.execute("""
                    SELECT COUNT(*) FROM streak_notifications_log
                    WHERE user_id = ?
                      AND notification_type IN ('at_risk', 'critical')
                      AND date(sent_at) = date('now')
                """, (user_id,))

                count = (await cursor.fetchone())[0]

                if count >= 2:
                    return False

                return True

        except Exception as e:
            logger.error(f"Error checking notification permission for user {user_id}: {e}")
            return False

    async def _log_notification(self, user_id: int, notification_type: str, streak_value: int):
        """Логирует отправленное уведомление"""
        try:
            async with aiosqlite.connect(self.database_file) as db:
                await db.execute("""
                    INSERT INTO streak_notifications_log (
                        user_id,
                        notification_type,
                        streak_value,
                        sent_at,
                        delivered
                    ) VALUES (?, ?, ?, ?, 1)
                """, (
                    user_id,
                    notification_type,
                    streak_value,
                    datetime.now(timezone.utc).isoformat()
                ))

                await db.commit()

        except Exception as e:
            logger.error(f"Error logging notification: {e}")

    async def _disable_notifications(self, user_id: int, reason: str):
        """Отключает уведомления для пользователя"""
        try:
            async with aiosqlite.connect(self.database_file) as db:
                await db.execute("""
                    INSERT OR REPLACE INTO notification_preferences (
                        user_id,
                        enabled,
                        disabled_at,
                        disabled_reason
                    ) VALUES (?, 0, ?, ?)
                """, (user_id, datetime.now(timezone.utc).isoformat(), reason))

                await db.commit()

        except Exception as e:
            logger.error(f"Error disabling notifications for user {user_id}: {e}")


# Глобальный экземпляр
_reminder_scheduler_instance: Optional[StreakReminderScheduler] = None


def get_streak_reminder_scheduler() -> StreakReminderScheduler:
    """Возвращает глобальный экземпляр scheduler"""
    global _reminder_scheduler_instance
    if _reminder_scheduler_instance is None:
        _reminder_scheduler_instance = StreakReminderScheduler()
    return _reminder_scheduler_instance
