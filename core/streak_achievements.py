"""
Streak Achievements System - система достижений и badges

Phase 4: Gamification
- 20+ различных достижений
- Категории: Streaks, Accuracy, Volume, Special
- Редкость: Common, Rare, Epic, Legendary
- Автоматическая выдача наград
"""

import logging
import aiosqlite
from datetime import datetime, timezone, date
from typing import Dict, List, Optional, Tuple
from enum import Enum
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from core.db import DATABASE_FILE

logger = logging.getLogger(__name__)


class BadgeRarity(Enum):
    """Редкость достижения"""
    COMMON = ("Обычное", "⚪")
    RARE = ("Редкое", "🔵")
    EPIC = ("Эпическое", "🟣")
    LEGENDARY = ("Легендарное", "🟡")

    def __init__(self, display_name: str, emoji: str):
        self.display_name = display_name
        self.emoji = emoji


class Achievement:
    """Класс достижения"""

    def __init__(
        self,
        achievement_id: str,
        title: str,
        description: str,
        emoji: str,
        category: str,
        rarity: BadgeRarity,
        condition_description: str,
        reward_description: Optional[str] = None
    ):
        self.achievement_id = achievement_id
        self.title = title
        self.description = description
        self.emoji = emoji
        self.category = category
        self.rarity = rarity
        self.condition_description = condition_description
        self.reward_description = reward_description


class AchievementSystem:
    """Система управления достижениями"""

    def __init__(self, database_file: str = DATABASE_FILE):
        self.database_file = database_file
        self.achievements = self._initialize_achievements()

    def _initialize_achievements(self) -> Dict[str, Achievement]:
        """Инициализирует все достижения в системе"""
        achievements = {}

        # ============================================================
        # STREAK ACHIEVEMENTS
        # ============================================================

        achievements['streak_week'] = Achievement(
            achievement_id='streak_week',
            title='Неделя подряд',
            description='Занимайся 7 дней подряд',
            emoji='🔥',
            category='streaks',
            rarity=BadgeRarity.COMMON,
            condition_description='Достигни 7-дневного стрика',
            reward_description='1 бесплатная заморозка'
        )

        achievements['streak_two_weeks'] = Achievement(
            achievement_id='streak_two_weeks',
            title='Две недели',
            description='Занимайся 14 дней подряд',
            emoji='🔥🔥',
            category='streaks',
            rarity=BadgeRarity.RARE,
            condition_description='Достигни 14-дневного стрика',
            reward_description='3 AI-проверки'
        )

        achievements['streak_month'] = Achievement(
            achievement_id='streak_month',
            title='Месяц подряд',
            description='Занимайся 30 дней подряд',
            emoji='👑',
            category='streaks',
            rarity=BadgeRarity.EPIC,
            condition_description='Достигни 30-дневного стрика',
            reward_description='1 заморозка + 5 AI-проверок'
        )

        achievements['streak_two_months'] = Achievement(
            achievement_id='streak_two_months',
            title='Два месяца',
            description='Занимайся 60 дней подряд',
            emoji='💎',
            category='streaks',
            rarity=BadgeRarity.EPIC,
            condition_description='Достигни 60-дневного стрика',
            reward_description='2 заморозки'
        )

        achievements['streak_legend'] = Achievement(
            achievement_id='streak_legend',
            title='Легенда стриков',
            description='Занимайся 100 дней подряд',
            emoji='🌟',
            category='streaks',
            rarity=BadgeRarity.LEGENDARY,
            condition_description='Достигни 100-дневного стрика',
            reward_description='1 месяц Premium бесплатно'
        )

        # ============================================================
        # ACCURACY ACHIEVEMENTS
        # ============================================================

        achievements['correct_5'] = Achievement(
            achievement_id='correct_5',
            title='Меткий стрелок',
            description='5 правильных ответов подряд',
            emoji='🎯',
            category='accuracy',
            rarity=BadgeRarity.COMMON,
            condition_description='Ответь правильно 5 раз подряд',
            reward_description='1 AI-проверка'
        )

        achievements['correct_10'] = Achievement(
            achievement_id='correct_10',
            title='Снайпер',
            description='10 правильных ответов подряд',
            emoji='🔥',
            category='accuracy',
            rarity=BadgeRarity.RARE,
            condition_description='Ответь правильно 10 раз подряд',
            reward_description='2 AI-проверки + 1 щит'
        )

        achievements['correct_20'] = Achievement(
            achievement_id='correct_20',
            title='Безупречный',
            description='20 правильных ответов подряд',
            emoji='⚡',
            category='accuracy',
            rarity=BadgeRarity.EPIC,
            condition_description='Ответь правильно 20 раз подряд',
            reward_description='3 AI-проверки'
        )

        achievements['correct_50'] = Achievement(
            achievement_id='correct_50',
            title='Перфекционист',
            description='50 правильных ответов подряд',
            emoji='💎',
            category='accuracy',
            rarity=BadgeRarity.LEGENDARY,
            condition_description='Ответь правильно 50 раз подряд',
            reward_description='Скидка 20% на Premium'
        )

        # ============================================================
        # VOLUME ACHIEVEMENTS
        # ============================================================

        achievements['questions_100'] = Achievement(
            achievement_id='questions_100',
            title='Практикант',
            description='Реши 100 заданий',
            emoji='📚',
            category='volume',
            rarity=BadgeRarity.COMMON,
            condition_description='Ответь на 100 вопросов',
            reward_description='2 AI-проверки'
        )

        achievements['questions_500'] = Achievement(
            achievement_id='questions_500',
            title='Знаток',
            description='Реши 500 заданий',
            emoji='🎓',
            category='volume',
            rarity=BadgeRarity.RARE,
            condition_description='Ответь на 500 вопросов',
            reward_description='5 AI-проверок'
        )

        achievements['questions_1000'] = Achievement(
            achievement_id='questions_1000',
            title='Мастер',
            description='Реши 1000 заданий',
            emoji='🏆',
            category='volume',
            rarity=BadgeRarity.EPIC,
            condition_description='Ответь на 1000 вопросов',
            reward_description='10 AI-проверок + 1 заморозка'
        )

        achievements['questions_5000'] = Achievement(
            achievement_id='questions_5000',
            title='Гроссмейстер',
            description='Реши 5000 заданий',
            emoji='👑',
            category='volume',
            rarity=BadgeRarity.LEGENDARY,
            condition_description='Ответь на 5000 вопросов',
            reward_description='3 месяца Premium бесплатно'
        )

        # ============================================================
        # SPECIAL ACHIEVEMENTS
        # ============================================================

        achievements['perfect_day'] = Achievement(
            achievement_id='perfect_day',
            title='Идеальный день',
            description='100% правильных за день (мин 10 вопросов)',
            emoji='✨',
            category='special',
            rarity=BadgeRarity.RARE,
            condition_description='Ответь правильно на все вопросы за день (мин 10)',
            reward_description='1 щит от ошибок'
        )

        achievements['early_bird'] = Achievement(
            achievement_id='early_bird',
            title='Ранняя птичка',
            description='Позанимайся до 8:00 утра 5 раз',
            emoji='🌅',
            category='special',
            rarity=BadgeRarity.RARE,
            condition_description='Реши задания до 8:00 утра 5 раз',
            reward_description='1 заморозка'
        )

        achievements['night_owl'] = Achievement(
            achievement_id='night_owl',
            title='Полуночник',
            description='Позанимайся после 23:00 пять раз',
            emoji='🦉',
            category='special',
            rarity=BadgeRarity.RARE,
            condition_description='Реши задания после 23:00 пять раз',
            reward_description='1 заморозка'
        )

        achievements['weekend_warrior'] = Achievement(
            achievement_id='weekend_warrior',
            title='Воин выходного дня',
            description='Занимайся каждые выходные месяц подряд',
            emoji='⚔️',
            category='special',
            rarity=BadgeRarity.EPIC,
            condition_description='Реши задания в субботу и воскресенье 4 недели подряд',
            reward_description='2 заморозки'
        )

        achievements['comeback_king'] = Achievement(
            achievement_id='comeback_king',
            title='Король возвращения',
            description='Восстанови стрик после потери',
            emoji='🔄',
            category='special',
            rarity=BadgeRarity.RARE,
            condition_description='Используй Repair для восстановления стрика',
            reward_description='1 щит от ошибок'
        )

        achievements['protected'] = Achievement(
            achievement_id='protected',
            title='Защищённый',
            description='Используй заморозку чтобы сохранить стрик',
            emoji='❄️',
            category='special',
            rarity=BadgeRarity.COMMON,
            condition_description='Автоматически примени заморозку при пропуске',
            reward_description='Нет'
        )

        achievements['first_steps'] = Achievement(
            achievement_id='first_steps',
            title='Первые шаги',
            description='Реши первое задание',
            emoji='🌱',
            category='special',
            rarity=BadgeRarity.COMMON,
            condition_description='Ответь на первый вопрос',
            reward_description='1 AI-проверка'
        )

        return achievements

    # ============================================================
    # ACHIEVEMENT CHECKING
    # ============================================================

    async def check_and_grant_achievements(
        self,
        user_id: int,
        event_type: str,
        event_data: Dict
    ) -> List[Achievement]:
        """
        Проверяет условия достижений и выдает новые.

        Args:
            user_id: ID пользователя
            event_type: Тип события ('streak_milestone', 'question_answered', etc)
            event_data: Данные события

        Returns:
            Список новых достижений
        """
        try:
            new_achievements = []

            if event_type == 'daily_streak_milestone':
                streak_value = event_data.get('streak_value', 0)
                achievement_id = None

                if streak_value == 7:
                    achievement_id = 'streak_week'
                elif streak_value == 14:
                    achievement_id = 'streak_two_weeks'
                elif streak_value == 30:
                    achievement_id = 'streak_month'
                elif streak_value == 60:
                    achievement_id = 'streak_two_months'
                elif streak_value == 100:
                    achievement_id = 'streak_legend'

                if achievement_id:
                    granted = await self._grant_achievement(user_id, achievement_id)
                    if granted:
                        new_achievements.append(self.achievements[achievement_id])

            elif event_type == 'correct_streak_milestone':
                streak_value = event_data.get('streak_value', 0)
                achievement_id = None

                if streak_value == 5:
                    achievement_id = 'correct_5'
                elif streak_value == 10:
                    achievement_id = 'correct_10'
                elif streak_value == 20:
                    achievement_id = 'correct_20'
                elif streak_value == 50:
                    achievement_id = 'correct_50'

                if achievement_id:
                    granted = await self._grant_achievement(user_id, achievement_id)
                    if granted:
                        new_achievements.append(self.achievements[achievement_id])

            elif event_type == 'total_questions_milestone':
                total = event_data.get('total_questions', 0)
                achievement_id = None

                if total == 100:
                    achievement_id = 'questions_100'
                elif total == 500:
                    achievement_id = 'questions_500'
                elif total == 1000:
                    achievement_id = 'questions_1000'
                elif total == 5000:
                    achievement_id = 'questions_5000'

                if achievement_id:
                    granted = await self._grant_achievement(user_id, achievement_id)
                    if granted:
                        new_achievements.append(self.achievements[achievement_id])

            elif event_type == 'first_question':
                granted = await self._grant_achievement(user_id, 'first_steps')
                if granted:
                    new_achievements.append(self.achievements['first_steps'])

            elif event_type == 'freeze_used':
                granted = await self._grant_achievement(user_id, 'protected')
                if granted:
                    new_achievements.append(self.achievements['protected'])

            elif event_type == 'repair_used':
                granted = await self._grant_achievement(user_id, 'comeback_king')
                if granted:
                    new_achievements.append(self.achievements['comeback_king'])

            elif event_type == 'perfect_day':
                granted = await self._grant_achievement(user_id, 'perfect_day')
                if granted:
                    new_achievements.append(self.achievements['perfect_day'])

            return new_achievements

        except Exception as e:
            logger.error(f"Error checking achievements: {e}", exc_info=True)
            return []

    async def _grant_achievement(self, user_id: int, achievement_id: str) -> bool:
        """Выдает достижение пользователю если он его еще не получал"""
        try:
            async with aiosqlite.connect(self.database_file) as db:
                # Проверяем, есть ли уже это достижение
                cursor = await db.execute("""
                    SELECT id FROM user_achievements
                    WHERE user_id = ? AND achievement_id = ?
                """, (user_id, achievement_id))

                if await cursor.fetchone():
                    return False  # Уже есть

                achievement = self.achievements.get(achievement_id)
                if not achievement:
                    return False

                # Выдаем достижение
                await db.execute("""
                    INSERT INTO user_achievements (
                        user_id,
                        achievement_id,
                        achievement_name,
                        category,
                        rarity,
                        earned_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    user_id,
                    achievement_id,
                    achievement.title,
                    achievement.category,
                    achievement.rarity.name,
                    datetime.now(timezone.utc).isoformat()
                ))

                await db.commit()

                logger.info(f"Granted achievement '{achievement_id}' to user {user_id}")
                return True

        except Exception as e:
            logger.error(f"Error granting achievement: {e}", exc_info=True)
            return False

    # ============================================================
    # ACHIEVEMENT DISPLAY
    # ============================================================

    async def get_user_achievements(self, user_id: int) -> List[Dict]:
        """Получает все достижения пользователя"""
        try:
            async with aiosqlite.connect(self.database_file) as db:
                cursor = await db.execute("""
                    SELECT achievement_id, achievement_name, category, rarity, earned_at
                    FROM user_achievements
                    WHERE user_id = ?
                    ORDER BY earned_at DESC
                """, (user_id,))

                rows = await cursor.fetchall()

                achievements = []
                for row in rows:
                    achievement_id = row[0]
                    achievement_obj = self.achievements.get(achievement_id)

                    if achievement_obj:
                        achievements.append({
                            'id': achievement_id,
                            'title': row[1],
                            'emoji': achievement_obj.emoji,
                            'category': row[2],
                            'rarity': row[3],
                            'earned_at': row[4],
                            'description': achievement_obj.description
                        })

                return achievements

        except Exception as e:
            logger.error(f"Error getting achievements: {e}", exc_info=True)
            return []

    async def get_achievement_stats(self, user_id: int) -> Dict:
        """Получает статистику по достижениям"""
        try:
            async with aiosqlite.connect(self.database_file) as db:
                # Общее количество
                cursor = await db.execute("""
                    SELECT COUNT(*) FROM user_achievements WHERE user_id = ?
                """, (user_id,))
                total_earned = (await cursor.fetchone())[0]

                # По редкости
                cursor = await db.execute("""
                    SELECT rarity, COUNT(*)
                    FROM user_achievements
                    WHERE user_id = ?
                    GROUP BY rarity
                """, (user_id,))

                by_rarity = {}
                for row in await cursor.fetchall():
                    by_rarity[row[0]] = row[1]

                # По категориям
                cursor = await db.execute("""
                    SELECT category, COUNT(*)
                    FROM user_achievements
                    WHERE user_id = ?
                    GROUP BY category
                """, (user_id,))

                by_category = {}
                for row in await cursor.fetchall():
                    by_category[row[0]] = row[1]

                return {
                    'total_earned': total_earned,
                    'total_available': len(self.achievements),
                    'by_rarity': by_rarity,
                    'by_category': by_category,
                    'completion_percent': int(total_earned / len(self.achievements) * 100)
                }

        except Exception as e:
            logger.error(f"Error getting achievement stats: {e}", exc_info=True)
            return {}

    def get_achievement_display_text(self, achievement: Achievement, earned_at: Optional[str] = None) -> str:
        """Форматирует текст для отображения достижения"""
        rarity_emoji = achievement.rarity.emoji
        rarity_text = achievement.rarity.display_name

        text = f"{achievement.emoji} <b>{achievement.title}</b> {rarity_emoji}\n"
        text += f"<i>{achievement.description}</i>\n"
        text += f"🏅 Редкость: {rarity_text}\n"

        if achievement.reward_description:
            text += f"🎁 Награда: {achievement.reward_description}\n"

        if earned_at:
            earned_date = datetime.fromisoformat(earned_at).strftime("%d.%m.%Y")
            text += f"📅 Получено: {earned_date}"

        return text


# Глобальный экземпляр
_achievement_system_instance: Optional[AchievementSystem] = None


def get_achievement_system() -> AchievementSystem:
    """Возвращает глобальный экземпляр системы достижений"""
    global _achievement_system_instance
    if _achievement_system_instance is None:
        _achievement_system_instance = AchievementSystem()
    return _achievement_system_instance
