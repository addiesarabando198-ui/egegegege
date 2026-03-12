"""
Milestone Notification Handler - обработка достижений и наград

Phase 2: Notifications
- Автоматическое обнаружение milestone (7d, 30d, 100d, etc)
- Отправка celebration messages
- Автоматическая выдача наград
- Tracking engagement для аналитики
"""

import logging
import aiosqlite
from datetime import datetime, timezone
from typing import Optional, Dict, List
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Forbidden, BadRequest

from core.db import DATABASE_FILE
from core.streak_manager import get_streak_manager, StreakLevel
from core.streak_ui import get_streak_ui

logger = logging.getLogger(__name__)


class MilestoneNotificationHandler:
    """Обработчик milestone уведомлений и наград"""

    def __init__(self, database_file: str = DATABASE_FILE):
        self.database_file = database_file
        self.streak_manager = get_streak_manager()
        self.streak_ui = get_streak_ui()

        # Определяем milestone значения для отслеживания
        self.daily_milestones = [7, 14, 30, 60, 100]
        self.correct_milestones = [5, 10, 20, 50]

    # ============================================================
    # MILESTONE DETECTION
    # ============================================================

    async def check_and_notify_milestones(
        self,
        bot: Bot,
        user_id: int,
        streak_type: str,
        current_value: int,
        previous_value: int
    ) -> bool:
        """
        Проверяет, достиг ли пользователь нового milestone.

        Args:
            bot: Telegram bot instance
            user_id: ID пользователя
            streak_type: 'daily' или 'correct'
            current_value: Текущее значение стрика
            previous_value: Предыдущее значение стрика

        Returns:
            True если milestone был достигнут и уведомление отправлено
        """
        try:
            # Определяем список milestone для проверки
            milestones = (
                self.daily_milestones if streak_type == 'daily'
                else self.correct_milestones
            )

            # Проверяем, пересекли ли мы milestone
            for milestone in milestones:
                if previous_value < milestone <= current_value:
                    # Проверяем, не отправляли ли уже это уведомление
                    already_achieved = await self._is_milestone_achieved(
                        user_id,
                        streak_type,
                        milestone
                    )

                    if already_achieved:
                        logger.debug(
                            f"Milestone {streak_type}:{milestone} already achieved for user {user_id}"
                        )
                        continue

                    # Отправляем уведомление
                    success = await self._send_milestone_notification(
                        bot,
                        user_id,
                        streak_type,
                        milestone
                    )

                    if success:
                        # Выдаем награды
                        await self._grant_milestone_rewards(
                            user_id,
                            streak_type,
                            milestone
                        )

                        # Логируем достижение
                        await self._log_milestone_achievement(
                            user_id,
                            streak_type,
                            milestone
                        )

                        return True

            return False

        except Exception as e:
            logger.error(f"Error checking milestones for user {user_id}: {e}", exc_info=True)
            return False

    async def _is_milestone_achieved(
        self,
        user_id: int,
        milestone_type: str,
        milestone_value: int
    ) -> bool:
        """Проверяет, достигнут ли уже этот milestone"""
        try:
            async with aiosqlite.connect(self.database_file) as db:
                cursor = await db.execute("""
                    SELECT id FROM streak_milestones
                    WHERE user_id = ?
                      AND milestone_type = ?
                      AND milestone_value = ?
                """, (user_id, milestone_type, milestone_value))

                result = await cursor.fetchone()
                return result is not None

        except Exception as e:
            logger.error(f"Error checking milestone status: {e}")
            return False

    # ============================================================
    # NOTIFICATION SENDING
    # ============================================================

    async def _send_milestone_notification(
        self,
        bot: Bot,
        user_id: int,
        milestone_type: str,
        milestone_value: int
    ) -> bool:
        """
        Отправляет уведомление о достижении milestone.
        """
        try:
            # Получаем текущий уровень пользователя
            streak_info = await self.streak_manager.get_daily_streak_info(user_id)
            level = streak_info['level']

            # Получаем сообщение из UI
            message_data = self.streak_ui.get_milestone_message(
                milestone_type,
                milestone_value,
                level
            )

            if not message_data:
                logger.warning(
                    f"No milestone message found for {milestone_type}:{milestone_value}"
                )
                return False

            # Отправляем сообщение
            await bot.send_message(
                chat_id=user_id,
                text=message_data['text'],
                reply_markup=message_data['keyboard'],
                parse_mode=message_data['parse_mode']
            )

            logger.info(
                f"Sent milestone notification to user {user_id}: "
                f"{milestone_type}:{milestone_value}"
            )
            return True

        except Forbidden:
            logger.warning(f"User {user_id} blocked the bot")
            return False
        except BadRequest as e:
            logger.error(f"BadRequest sending milestone to {user_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Error sending milestone notification: {e}", exc_info=True)
            return False

    # ============================================================
    # REWARD GRANTING
    # ============================================================

    async def _grant_milestone_rewards(
        self,
        user_id: int,
        milestone_type: str,
        milestone_value: int
    ) -> bool:
        """
        Выдает награды за достижение milestone.

        Награды:
        Daily Streaks:
        - 7d: 1 заморозка
        - 14d: 3 AI-проверки
        - 30d: 1 заморозка + 5 AI-проверок
        - 60d: 2 заморозки
        - 100d: 1 месяц Premium бесплатно

        Correct Streaks:
        - 5: +1 AI-проверка
        - 10: +2 AI-проверки + 1 щит от ошибок
        - 20: +3 AI-проверки
        - 50: Скидка 20% на Premium
        """
        try:
            rewards_map = {
                'daily': {
                    7: {'freezes': 1, 'ai_checks': 0},
                    14: {'freezes': 0, 'ai_checks': 3},
                    30: {'freezes': 1, 'ai_checks': 5},
                    60: {'freezes': 2, 'ai_checks': 0},
                    100: {'premium_days': 30}  # Special: 1 month premium
                },
                'correct': {
                    5: {'ai_checks': 1},
                    10: {'ai_checks': 2, 'error_shields': 1},
                    20: {'ai_checks': 3},
                    50: {'premium_discount': 20}  # Special: 20% discount
                }
            }

            rewards = rewards_map.get(milestone_type, {}).get(milestone_value)

            if not rewards:
                logger.warning(f"No rewards defined for {milestone_type}:{milestone_value}")
                return False

            async with aiosqlite.connect(self.database_file) as db:
                # Выдаем заморозки
                if 'freezes' in rewards and rewards['freezes'] > 0:
                    await db.execute("""
                        UPDATE user_streaks
                        SET freeze_count = freeze_count + ?
                        WHERE user_id = ?
                    """, (rewards['freezes'], user_id))
                    logger.info(f"Granted {rewards['freezes']} freezes to user {user_id}")

                # Выдаем AI-проверки
                if 'ai_checks' in rewards and rewards['ai_checks'] > 0:
                    await db.execute("""
                        UPDATE users
                        SET ai_checks_remaining = ai_checks_remaining + ?
                        WHERE user_id = ?
                    """, (rewards['ai_checks'], user_id))
                    logger.info(f"Granted {rewards['ai_checks']} AI checks to user {user_id}")

                # Выдаем щиты от ошибок
                if 'error_shields' in rewards and rewards['error_shields'] > 0:
                    await db.execute("""
                        UPDATE user_streaks
                        SET error_shield_count = error_shield_count + ?
                        WHERE user_id = ?
                    """, (rewards['error_shields'], user_id))
                    logger.info(f"Granted {rewards['error_shields']} error shields to user {user_id}")

                # Premium на месяц (milestone 100 дней)
                if 'premium_days' in rewards:
                    from datetime import timedelta
                    # TODO: Интеграция с системой подписок
                    # Пока просто логируем
                    logger.info(f"User {user_id} earned {rewards['premium_days']} days of premium!")

                # Скидка на Premium (milestone 50 правильных)
                if 'premium_discount' in rewards:
                    # TODO: Сохранить промокод или купон в БД
                    logger.info(f"User {user_id} earned {rewards['premium_discount']}% discount!")

                await db.commit()

            return True

        except Exception as e:
            logger.error(f"Error granting rewards to user {user_id}: {e}", exc_info=True)
            return False

    # ============================================================
    # LOGGING
    # ============================================================

    async def _log_milestone_achievement(
        self,
        user_id: int,
        milestone_type: str,
        milestone_value: int
    ) -> bool:
        """Логирует достижение milestone в БД"""
        try:
            async with aiosqlite.connect(self.database_file) as db:
                # Определяем название badge
                badge_name = self._get_badge_name(milestone_type, milestone_value)

                # Определяем выданные награды
                rewards_granted = self._get_rewards_description(
                    milestone_type,
                    milestone_value
                )

                await db.execute("""
                    INSERT INTO streak_milestones (
                        user_id,
                        milestone_type,
                        milestone_value,
                        milestone_name,
                        achieved_at,
                        badge_earned,
                        rewards_granted,
                        notification_sent
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """, (
                    user_id,
                    milestone_type,
                    milestone_value,
                    badge_name,
                    datetime.now(timezone.utc).isoformat(),
                    badge_name,
                    rewards_granted
                ))

                await db.commit()

            logger.info(f"Logged milestone achievement for user {user_id}: {badge_name}")
            return True

        except Exception as e:
            logger.error(f"Error logging milestone: {e}", exc_info=True)
            return False

    # ============================================================
    # HELPER METHODS
    # ============================================================

    def _get_badge_name(self, milestone_type: str, milestone_value: int) -> str:
        """Возвращает название badge для milestone"""
        badges = {
            'daily': {
                7: '🎉 Неделя Подряд',
                14: '🏆 2 Недели',
                30: '👑 Месяц',
                60: '💎 2 Месяца',
                100: '🌟 Легенда (100 дней)'
            },
            'correct': {
                5: '🎯 5 Правильных',
                10: '🔥 10 Правильных',
                20: '⚡ 20 Правильных',
                50: '💎 50 Правильных'
            }
        }

        return badges.get(milestone_type, {}).get(
            milestone_value,
            f"{milestone_type} {milestone_value}"
        )

    def _get_rewards_description(
        self,
        milestone_type: str,
        milestone_value: int
    ) -> str:
        """Возвращает текстовое описание наград"""
        rewards = {
            'daily': {
                7: '1 заморозка',
                14: '3 AI-проверки',
                30: '1 заморозка + 5 AI-проверок',
                60: '2 заморозки',
                100: '1 месяц Premium бесплатно'
            },
            'correct': {
                5: '1 AI-проверка',
                10: '2 AI-проверки + 1 щит от ошибок',
                20: '3 AI-проверки',
                50: 'Скидка 20% на Premium'
            }
        }

        return rewards.get(milestone_type, {}).get(
            milestone_value,
            'Неизвестная награда'
        )

    # ============================================================
    # ENGAGEMENT TRACKING
    # ============================================================

    async def track_milestone_engagement(
        self,
        user_id: int,
        milestone_type: str,
        milestone_value: int,
        action: str
    ) -> bool:
        """
        Отслеживает взаимодействие пользователя с milestone уведомлением.

        Args:
            action: 'clicked', 'shared', 'dismissed'
        """
        try:
            async with aiosqlite.connect(self.database_file) as db:
                if action == 'clicked':
                    await db.execute("""
                        UPDATE streak_milestones
                        SET notification_clicked = 1
                        WHERE user_id = ?
                          AND milestone_type = ?
                          AND milestone_value = ?
                    """, (user_id, milestone_type, milestone_value))

                elif action == 'shared':
                    await db.execute("""
                        UPDATE streak_milestones
                        SET user_shared = 1
                        WHERE user_id = ?
                          AND milestone_type = ?
                          AND milestone_value = ?
                    """, (user_id, milestone_type, milestone_value))

                await db.commit()

            logger.info(
                f"Tracked milestone engagement for user {user_id}: "
                f"{milestone_type}:{milestone_value} - {action}"
            )
            return True

        except Exception as e:
            logger.error(f"Error tracking engagement: {e}")
            return False


# Глобальный экземпляр
_milestone_handler_instance: Optional[MilestoneNotificationHandler] = None


def get_milestone_notification_handler() -> MilestoneNotificationHandler:
    """Возвращает глобальный экземпляр handler"""
    global _milestone_handler_instance
    if _milestone_handler_instance is None:
        _milestone_handler_instance = MilestoneNotificationHandler()
    return _milestone_handler_instance
