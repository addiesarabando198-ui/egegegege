"""
Scheduler для автоматической отправки retention уведомлений.

Запускается ежедневно через Telegram Job Queue.
Классифицирует пользователей и отправляет персонализированные уведомления.
"""

import logging
import aiosqlite
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Tuple
from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.error import Forbidden, BadRequest

from core.db import DATABASE_FILE
from core.user_segments import get_segment_classifier, UserSegment
from core.user_segments_optimized import get_users_by_segment_optimized
from core.notification_templates import (
    get_template,
    NotificationTrigger,
    NotificationTemplate
)

logger = logging.getLogger(__name__)


class RetentionScheduler:
    """Планировщик retention уведомлений"""

    def __init__(self, database_file: str = DATABASE_FILE):
        self.database_file = database_file
        self.classifier = get_segment_classifier()

    def _pluralize_days(self, days: int) -> str:
        """Склонение слова 'день'"""
        if days % 10 == 1 and days % 100 != 11:
            return "день"
        elif days % 10 in [2, 3, 4] and days % 100 not in [12, 13, 14]:
            return "дня"
        else:
            return "дней"

    def _enrich_variables(
        self,
        activity: Dict[str, Any],
        subscription: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Обогащает переменные для шаблонов всеми необходимыми данными.

        Args:
            activity: Статистика активности пользователя
            subscription: Информация о подписке (опционально)

        Returns:
            Полный набор переменных для шаблонов
        """
        # Копируем базовые данные
        variables = dict(activity)

        # Дата ЕГЭ 2025 (предполагаем 1 июня 2025)
        ege_date = datetime(2025, 6, 1, tzinfo=timezone.utc)
        days_to_ege = (ege_date - datetime.now(timezone.utc)).days
        variables['days_to_ege'] = max(0, days_to_ege)
        variables['days_word'] = self._pluralize_days(variables['days_to_ege'])

        # Вопросов до milestone (10 вопросов)
        answered_total = activity.get('answered_total', 0)
        variables['questions_to_milestone'] = max(0, 10 - answered_total)

        # Оставшиеся бесплатные проверки (3 в неделю для free users)
        ai_checks_today = activity.get('ai_checks_today', 0)
        variables['checks_remaining'] = max(0, 3 - ai_checks_today)

        # Streak (пока не реализовано, ставим 0)
        variables['current_streak'] = 0

        # Данные о подписке
        if subscription:
            # Дата окончания подписки (форматированная)
            if subscription.get('end_date'):
                end_date = subscription['end_date']
                if isinstance(end_date, str):
                    try:
                        end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                        variables['subscription_end'] = end_dt.strftime('%d.%m.%Y')
                    except:
                        variables['subscription_end'] = end_date[:10]
                else:
                    variables['subscription_end'] = end_date.strftime('%d.%m.%Y')
            else:
                variables['subscription_end'] = 'неизвестно'

            # Дней до окончания
            days_until_expiry = subscription.get('days_until_expiry', 0)
            variables['days_until_expiry'] = days_until_expiry
            variables['days_word'] = self._pluralize_days(days_until_expiry)

        return variables

    async def can_send_notification(
        self,
        user_id: int,
        trigger: NotificationTrigger
    ) -> Tuple[bool, str]:
        """
        Проверяет можно ли отправить уведомление пользователю.

        Returns:
            (can_send, reason)
        """
        async with aiosqlite.connect(self.database_file) as db:
            # Проверка 1: Пользователь отписался?
            cursor = await db.execute("""
                SELECT enabled FROM notification_preferences
                WHERE user_id = ?
            """, (user_id,))
            pref = await cursor.fetchone()

            if pref and not pref[0]:
                return False, "user_disabled"

            # Проверка 2: Лимит уведомлений в день
            # СМЯГЧЕНО: Увеличили лимиты для всех сегментов
            cursor = await db.execute("""
                SELECT notification_count_today FROM notification_preferences
                WHERE user_id = ?
            """, (user_id,))
            count_row = await cursor.fetchone()

            # Bounced и Curious - агрессивный retention (3 в день)
            # Остальные сегменты - 2 в день (было 1)
            is_critical = trigger.value.startswith(('bounced', 'curious', 'late_bounced'))
            daily_limit = 3 if is_critical else 2

            if count_row and count_row[0] >= daily_limit:
                return False, "daily_limit_exceeded"

            # Проверка 3: Cooldown для этого триггера
            # УЛУЧШЕНО: Cooldown зависит от типа триггера
            cursor = await db.execute("""
                SELECT cooldown_until FROM notification_cooldown
                WHERE user_id = ? AND trigger = ?
                AND cooldown_until > datetime('now')
            """, (user_id, trigger.value))
            cooldown = await cursor.fetchone()

            if cooldown:
                return False, "trigger_cooldown"

            # Проверка 4: Уже отправляли это уведомление?
            # СМЯГЧЕНО: Уменьшили периоды проверки для повторных отправок
            days_check = 2 if is_critical else 5  # Было: 3 и 7

            cursor = await db.execute("""
                SELECT id FROM notification_log
                WHERE user_id = ? AND trigger = ?
                AND sent_at > datetime('now', ? || ' days')
            """, (user_id, trigger.value, f'-{days_check}'))
            recent = await cursor.fetchone()

            if recent:
                return False, "already_sent_recently"

            return True, "ok"

    async def log_notification(
        self,
        user_id: int,
        segment: UserSegment,
        trigger: NotificationTrigger,
        promo_code: Optional[str] = None
    ):
        """Логирует отправленное уведомление"""
        async with aiosqlite.connect(self.database_file) as db:
            await db.execute("""
                INSERT INTO notification_log (
                    user_id, segment, trigger, promo_code, sent_at
                ) VALUES (?, ?, ?, ?, ?)
            """, (
                user_id,
                segment.value,
                trigger.value,
                promo_code,
                datetime.now(timezone.utc)
            ))

            # СМЯГЧЕНО: Уменьшили cooldown периоды для более частых отправок
            # Bounced/Curious/Late_bounced - 8 часов, остальные - 16 часов (было 12 и 24)
            is_critical = trigger.value.startswith(('bounced', 'curious', 'late_bounced'))
            cooldown_hours = 8 if is_critical else 16

            await db.execute("""
                INSERT OR REPLACE INTO notification_cooldown (
                    user_id, trigger, cooldown_until
                ) VALUES (?, ?, ?)
            """, (
                user_id,
                trigger.value,
                (datetime.now(timezone.utc) + timedelta(hours=cooldown_hours)).isoformat()
            ))

            await db.commit()

    def extract_promo_code(self, text: str) -> Optional[str]:
        """Извлекает промокод из текста уведомления"""
        import re
        # Ищем паттерны типа "Промокод: TOP20" или "LASTDAY25"
        patterns = [
            r'Промокод:\s*(\w+)',
            r'промокод[:\s]+(\w+)',
            r'\b([A-Z]{3,}\d{2})\b'  # TOP20, SAVE25, etc.
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)

        return None

    async def send_notification(
        self,
        bot: Bot,
        user_id: int,
        segment: UserSegment,
        trigger: NotificationTrigger,
        variables: Dict[str, Any]
    ) -> bool:
        """
        Отправляет уведомление пользователю.

        Returns:
            True если успешно отправлено
        """
        # Проверяем можно ли отправить
        can_send, reason = await self.can_send_notification(user_id, trigger)
        if not can_send:
            logger.debug(f"Cannot send {trigger.value} to {user_id}: {reason}")
            return False

        # Получаем шаблон
        template = get_template(trigger)
        if not template:
            logger.error(f"Template not found for trigger: {trigger.value}")
            return False

        # Рендерим текст
        text = template.render(variables)

        # Создаём кнопки
        buttons = []
        for btn in template.buttons:
            if 'url' in btn:
                buttons.append([InlineKeyboardButton(btn['text'], url=btn['url'])])
            else:
                buttons.append([InlineKeyboardButton(btn['text'], callback_data=btn['callback_data'])])

        keyboard = InlineKeyboardMarkup(buttons) if buttons else None

        # Пытаемся отправить
        try:
            await bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=keyboard,
                parse_mode='HTML'
            )

            # Извлекаем промокод из текста
            promo_code = self.extract_promo_code(text)

            # Логируем отправку
            await self.log_notification(user_id, segment, trigger, promo_code)

            logger.info(f"Sent {trigger.value} notification to user {user_id}")
            return True

        except Forbidden:
            logger.warning(f"User {user_id} blocked the bot")
            # Отключаем уведомления для этого пользователя
            async with aiosqlite.connect(self.database_file) as db:
                await db.execute("""
                    INSERT OR REPLACE INTO notification_preferences (
                        user_id, enabled, disabled_at, disabled_reason
                    ) VALUES (?, 0, ?, 'bot_blocked')
                """, (user_id, datetime.now(timezone.utc)))
                await db.commit()
            return False

        except BadRequest as e:
            logger.error(f"BadRequest sending to {user_id}: {e}")
            # Если чат не найден - отключаем уведомления
            if "chat not found" in str(e).lower():
                async with aiosqlite.connect(self.database_file) as db:
                    await db.execute("""
                        INSERT OR REPLACE INTO notification_preferences (
                            user_id, enabled, disabled_at, disabled_reason
                        ) VALUES (?, 0, ?, 'chat_not_found')
                    """, (user_id, datetime.now(timezone.utc)))
                    await db.commit()
                logger.warning(f"Disabled notifications for user {user_id}: chat not found")
            return False

        except Exception as e:
            logger.error(f"Error sending notification to {user_id}: {e}")
            return False

    async def process_bounced_users(self, bot: Bot) -> int:
        """Обрабатывает BOUNCED пользователей"""
        sent_count = 0

        # ОПТИМИЗИРОВАНО: Используем прямые SQL-запросы вместо N+1 проблемы
        # УВЕЛИЧЕНО: Больше пользователей для обработки (было 100)
        bounced_users = await get_users_by_segment_optimized(
            UserSegment.BOUNCED,
            limit=200
        )

        for user_id in bounced_users:
            activity = await self.classifier.get_user_activity_stats(user_id)
            if not activity:
                continue

            days_since_reg = activity['days_since_registration']

            # УЛУЧШЕНО: Добавили день 7 для финального напоминания
            if 1 <= days_since_reg <= 2:
                trigger = NotificationTrigger.BOUNCED_DAY1
            elif 3 <= days_since_reg <= 4:
                trigger = NotificationTrigger.BOUNCED_DAY3
            elif 6 <= days_since_reg <= 7:
                trigger = NotificationTrigger.BOUNCED_DAY7
            else:
                continue

            # Обогащаем переменные
            variables = self._enrich_variables(activity)

            # Отправляем
            success = await self.send_notification(
                bot=bot,
                user_id=user_id,
                segment=UserSegment.BOUNCED,
                trigger=trigger,
                variables=variables
            )

            if success:
                sent_count += 1

        return sent_count

    async def process_late_bounced_users(self, bot: Bot) -> int:
        """
        Обрабатывает LATE_BOUNCED пользователей (Resurrection кампания).

        Отправляет единственное "последний шанс" уведомление пользователям,
        которые зарегистрировались 7-60 дней назад, но так и не начали пользоваться ботом.
        """
        sent_count = 0

        # ОПТИМИЗИРОВАНО: Прямой SQL-запрос для late bounced пользователей
        # УВЕЛИЧЕНО: Больше пользователей для resurrection кампании (было 50)
        late_bounced_users = await get_users_by_segment_optimized(
            UserSegment.LATE_BOUNCED,
            limit=100  # Увеличили для охвата большего количества упущенных пользователей
        )

        for user_id in late_bounced_users:
            activity = await self.classifier.get_user_activity_stats(user_id)
            if not activity:
                continue

            # Для late bounced отправляем только один тип уведомления - resurrection
            trigger = NotificationTrigger.LATE_BOUNCED_RESURRECTION

            # Обогащаем переменные
            variables = self._enrich_variables(activity)

            # Отправляем
            success = await self.send_notification(
                bot=bot,
                user_id=user_id,
                segment=UserSegment.LATE_BOUNCED,
                trigger=trigger,
                variables=variables
            )

            if success:
                sent_count += 1

        return sent_count

    async def process_trial_users(self, bot: Bot) -> int:
        """Обрабатывает TRIAL пользователей"""
        sent_count = 0

        # ОПТИМИЗИРОВАНО: Прямой SQL-запрос
        trial_users = await get_users_by_segment_optimized(
            UserSegment.TRIAL_USER,
            limit=50
        )

        for user_id in trial_users:
            activity = await self.classifier.get_user_activity_stats(user_id)
            subscription = await self.classifier.get_subscription_info(user_id)

            if not activity or not subscription.get('has_subscription'):
                continue

            days_until_expiry = subscription.get('days_until_expiry', 999)
            days_since_start = subscription.get('days_since_start', 0)

            # Определяем триггер (используем диапазоны, приоритет - более срочным)
            if days_until_expiry <= 0:
                trigger = NotificationTrigger.TRIAL_EXPIRED
            elif 0 < days_until_expiry <= 1:
                trigger = NotificationTrigger.TRIAL_EXPIRING_1DAY
            elif 1 < days_until_expiry <= 2:
                trigger = NotificationTrigger.TRIAL_EXPIRING_2DAYS
            elif 3 <= days_since_start <= 4:
                trigger = NotificationTrigger.TRIAL_DAY3
            else:
                continue

            # Обогащаем переменные
            variables = self._enrich_variables(activity, subscription)

            # Отправляем
            success = await self.send_notification(
                bot=bot,
                user_id=user_id,
                segment=UserSegment.TRIAL_USER,
                trigger=trigger,
                variables=variables
            )

            if success:
                sent_count += 1

        return sent_count

    async def process_churn_risk_users(self, bot: Bot) -> int:
        """Обрабатывает CHURN_RISK пользователей"""
        sent_count = 0

        # ОПТИМИЗИРОВАНО: Прямой SQL-запрос
        churn_users = await get_users_by_segment_optimized(
            UserSegment.CHURN_RISK,
            limit=50
        )

        for user_id in churn_users:
            activity = await self.classifier.get_user_activity_stats(user_id)
            subscription = await self.classifier.get_subscription_info(user_id)

            if not activity or not subscription.get('has_subscription'):
                continue

            days_until_expiry = subscription.get('days_until_expiry', 999)

            # Определяем триггер (используем диапазоны, приоритет - более срочным)
            if 0 < days_until_expiry <= 1:
                trigger = NotificationTrigger.CHURN_RISK_1DAY
            elif 1 < days_until_expiry <= 3:
                trigger = NotificationTrigger.CHURN_RISK_3DAYS
            elif 3 < days_until_expiry <= 7:
                trigger = NotificationTrigger.CHURN_RISK_7DAYS
            else:
                continue

            # Обогащаем переменные
            variables = self._enrich_variables(activity, subscription)

            # Отправляем
            success = await self.send_notification(
                bot=bot,
                user_id=user_id,
                segment=UserSegment.CHURN_RISK,
                trigger=trigger,
                variables=variables
            )

            if success:
                sent_count += 1

        return sent_count

    async def process_curious_users(self, bot: Bot) -> int:
        """Обрабатывает CURIOUS пользователей"""
        sent_count = 0

        # ОПТИМИЗИРОВАНО: Прямой SQL-запрос
        # УВЕЛИЧЕНО: Больше curious пользователей (было 50)
        curious_users = await get_users_by_segment_optimized(
            UserSegment.CURIOUS,
            limit=100
        )

        for user_id in curious_users:
            activity = await self.classifier.get_user_activity_stats(user_id)
            if not activity:
                continue

            days_inactive = activity['days_inactive']

            # Определяем триггер (используем диапазоны)
            if 3 <= days_inactive <= 6:
                trigger = NotificationTrigger.CURIOUS_DAY3
            elif 7 <= days_inactive <= 14:
                trigger = NotificationTrigger.CURIOUS_DAY7
            else:
                continue

            # Обогащаем переменные
            variables = self._enrich_variables(activity)

            # Отправляем
            success = await self.send_notification(
                bot=bot,
                user_id=user_id,
                segment=UserSegment.CURIOUS,
                trigger=trigger,
                variables=variables
            )

            if success:
                sent_count += 1

        return sent_count

    async def process_active_free_users(self, bot: Bot) -> int:
        """Обрабатывает ACTIVE_FREE пользователей"""
        sent_count = 0

        # ОПТИМИЗИРОВАНО: Прямой SQL-запрос
        active_free_users = await get_users_by_segment_optimized(
            UserSegment.ACTIVE_FREE,
            limit=50
        )

        for user_id in active_free_users:
            activity = await self.classifier.get_user_activity_stats(user_id)
            if not activity:
                continue

            days_since_reg = activity['days_since_registration']
            ai_checks_today = activity['ai_checks_today']

            # Определяем триггер (используем диапазоны)
            if ai_checks_today >= 3:  # Приоритет - использовал лимит прямо сейчас
                trigger = NotificationTrigger.ACTIVE_FREE_LIMIT_WARNING
            elif 10 <= days_since_reg <= 11:
                trigger = NotificationTrigger.ACTIVE_FREE_DAY10
            elif 20 <= days_since_reg <= 21:
                trigger = NotificationTrigger.ACTIVE_FREE_DAY20
            else:
                continue

            # Обогащаем переменные
            variables = self._enrich_variables(activity)

            # Отправляем
            success = await self.send_notification(
                bot=bot,
                user_id=user_id,
                segment=UserSegment.ACTIVE_FREE,
                trigger=trigger,
                variables=variables
            )

            if success:
                sent_count += 1

        return sent_count

    async def process_paying_inactive_users(self, bot: Bot) -> int:
        """Обрабатывает PAYING_INACTIVE пользователей"""
        sent_count = 0

        # ОПТИМИЗИРОВАНО: Прямой SQL-запрос
        paying_inactive_users = await get_users_by_segment_optimized(
            UserSegment.PAYING_INACTIVE,
            limit=50
        )

        for user_id in paying_inactive_users:
            activity = await self.classifier.get_user_activity_stats(user_id)
            subscription = await self.classifier.get_subscription_info(user_id)

            if not activity or not subscription.get('has_subscription'):
                continue

            days_inactive = activity['days_inactive']

            # Определяем триггер (используем диапазоны)
            if 3 <= days_inactive <= 6:
                trigger = NotificationTrigger.PAYING_INACTIVE_DAY3
            elif 7 <= days_inactive <= 13:
                trigger = NotificationTrigger.PAYING_INACTIVE_DAY7
            elif 14 <= days_inactive <= 20:
                trigger = NotificationTrigger.PAYING_INACTIVE_DAY14
            else:
                continue

            # Обогащаем переменные
            variables = self._enrich_variables(activity, subscription)

            # Отправляем
            success = await self.send_notification(
                bot=bot,
                user_id=user_id,
                segment=UserSegment.PAYING_INACTIVE,
                trigger=trigger,
                variables=variables
            )

            if success:
                sent_count += 1

        return sent_count

    async def process_cancelled_users(self, bot: Bot) -> int:
        """Обрабатывает CANCELLED пользователей"""
        sent_count = 0

        # ОПТИМИЗИРОВАНО: Прямой SQL-запрос
        cancelled_users = await get_users_by_segment_optimized(
            UserSegment.CANCELLED,
            limit=50
        )

        for user_id in cancelled_users:
            activity = await self.classifier.get_user_activity_stats(user_id)
            subscription = await self.classifier.get_subscription_info(user_id)

            if not activity or not subscription.get('had_subscription'):
                continue

            days_since_cancel = subscription.get('days_since_cancel', 999)

            # Определяем триггер (используем диапазоны)
            if 1 <= days_since_cancel <= 2:
                trigger = NotificationTrigger.CANCELLED_DAY1
            elif 3 <= days_since_cancel <= 6:
                trigger = NotificationTrigger.CANCELLED_DAY3
            elif 7 <= days_since_cancel <= 14:
                trigger = NotificationTrigger.CANCELLED_DAY7
            else:
                continue

            # Обогащаем переменные
            variables = self._enrich_variables(activity, subscription)

            # Отправляем
            success = await self.send_notification(
                bot=bot,
                user_id=user_id,
                segment=UserSegment.CANCELLED,
                trigger=trigger,
                variables=variables
            )

            if success:
                sent_count += 1

        return sent_count

    async def send_daily_notifications(self, context: ContextTypes.DEFAULT_TYPE):
        """
        Главная функция для ежедневной отправки уведомлений.
        Вызывается Job Queue.
        """
        bot = context.bot

        logger.info("=== Starting daily retention notifications ===")

        total_sent = 0

        # Обрабатываем каждый сегмент по приоритету
        try:
            # CHURN_RISK (критичный приоритет - первыми)
            churn_sent = await self.process_churn_risk_users(bot)
            total_sent += churn_sent
            logger.info(f"CHURN_RISK: sent {churn_sent} notifications")

            # TRIAL (высокий приоритет)
            trial_sent = await self.process_trial_users(bot)
            total_sent += trial_sent
            logger.info(f"TRIAL: sent {trial_sent} notifications")

            # BOUNCED (высокий приоритет)
            bounced_sent = await self.process_bounced_users(bot)
            total_sent += bounced_sent
            logger.info(f"BOUNCED: sent {bounced_sent} notifications")

            # LATE_BOUNCED (высокий приоритет - resurrection кампания)
            late_bounced_sent = await self.process_late_bounced_users(bot)
            total_sent += late_bounced_sent
            logger.info(f"LATE_BOUNCED: sent {late_bounced_sent} notifications")

            # CANCELLED (высокий приоритет - win-back)
            cancelled_sent = await self.process_cancelled_users(bot)
            total_sent += cancelled_sent
            logger.info(f"CANCELLED: sent {cancelled_sent} notifications")

            # CURIOUS (средний приоритет)
            curious_sent = await self.process_curious_users(bot)
            total_sent += curious_sent
            logger.info(f"CURIOUS: sent {curious_sent} notifications")

            # PAYING_INACTIVE (средний приоритет)
            paying_inactive_sent = await self.process_paying_inactive_users(bot)
            total_sent += paying_inactive_sent
            logger.info(f"PAYING_INACTIVE: sent {paying_inactive_sent} notifications")

            # ACTIVE_FREE (низкий приоритет - конверсионные)
            active_free_sent = await self.process_active_free_users(bot)
            total_sent += active_free_sent
            logger.info(f"ACTIVE_FREE: sent {active_free_sent} notifications")

        except Exception as e:
            logger.error(f"Error in daily retention notifications: {e}", exc_info=True)

        logger.info(f"=== Daily notifications complete: {total_sent} sent ===")


# Глобальный экземпляр
_scheduler_instance: Optional[RetentionScheduler] = None


def get_retention_scheduler() -> RetentionScheduler:
    """Возвращает глобальный экземпляр scheduler"""
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = RetentionScheduler()
    return _scheduler_instance
