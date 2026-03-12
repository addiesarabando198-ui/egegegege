"""
Визуальные компоненты для отображения стриков

Phase 1: Foundation
- Отображение стриков в главном меню
- Progress bars до следующего уровня
- Countdown таймеры
- Milestone celebrations
"""

import logging
from datetime import datetime, date, timedelta
from typing import Dict, Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from core.streak_manager import StreakLevel, StreakState, get_streak_manager

logger = logging.getLogger(__name__)


class StreakUI:
    """Класс для генерации UI элементов стриков"""

    def __init__(self):
        self.streak_manager = get_streak_manager()

    # ============================================================
    # MAIN MENU DISPLAY
    # ============================================================

    async def get_streak_display_for_menu(self, user_id: int) -> str:
        """
        Возвращает форматированную строку со стриками для главного меню.

        Формат:
        🔥 23 дня подряд  ⭐ Знаток    🎯 12 правильных
        """
        try:
            # Получаем информацию о стриках
            daily_info = await self.streak_manager.get_daily_streak_info(user_id)

            # Получаем correct streak из БД
            from core.db import get_user_streaks
            streaks = await get_user_streaks(user_id)

            current_daily = daily_info['current']
            current_correct = streaks.get('current_correct', 0)
            level = daily_info['level']

            if current_daily == 0:
                return "💡 <i>Начни свой стрик сегодня - реши первое задание!</i>"

            # Визуализация огоньков
            flames = self._get_flame_emoji(current_daily)
            days_word = self._pluralize_days(current_daily)

            # Базовая строка
            display = f"{flames} <b>{current_daily}</b> {days_word}  {level.emoji} {level.display_name}"

            # Добавляем correct streak если есть
            if current_correct > 0:
                display += f"    🎯 <b>{current_correct}</b> подряд"

            return display

        except Exception as e:
            logger.error(f"Error getting streak display: {e}")
            return ""

    async def get_progress_to_next_level(self, user_id: int) -> Optional[str]:
        """
        Возвращает прогресс до следующего уровня.

        Returns:
            Строка с progress bar или None
        """
        try:
            info = await self.streak_manager.get_daily_streak_info(user_id)
            current = info['current']
            level = info['level']

            # Определяем следующий уровень
            next_levels = {
                StreakLevel.NOVICE: (StreakLevel.STUDENT, 7),
                StreakLevel.STUDENT: (StreakLevel.PRACTITIONER, 14),
                StreakLevel.PRACTITIONER: (StreakLevel.EXPERT, 30),
                StreakLevel.EXPERT: (StreakLevel.MASTER, 60),
                StreakLevel.MASTER: (StreakLevel.LEGEND, 100),
            }

            if level not in next_levels:
                # Максимальный уровень достигнут
                return None

            next_level, days_needed = next_levels[level]
            days_left = days_needed - current
            progress_percent = (current / days_needed) * 100

            # Создаем progress bar
            filled = int(progress_percent / 10)
            bar = "█" * filled + "░" * (10 - filled)

            return f"{bar} {int(progress_percent)}% до <b>{next_level.emoji} {next_level.display_name}</b> (еще {days_left} {self._pluralize_days(days_left)})"

        except Exception as e:
            logger.error(f"Error getting progress: {e}")
            return None

    async def get_countdown_warning(self, user_id: int) -> Optional[str]:
        """
        Возвращает предупреждение с countdown если стрик под угрозой.

        Returns:
            Строка с предупреждением или None
        """
        try:
            info = await self.streak_manager.get_daily_streak_info(user_id)
            state = info['state']
            last_activity = info['last_activity']

            if state not in [StreakState.AT_RISK, StreakState.CRITICAL]:
                return None

            if not last_activity:
                return None

            # Вычисляем оставшееся время
            last_date = date.fromisoformat(last_activity)
            now = datetime.now()
            midnight = datetime.combine(date.today() + timedelta(days=1), datetime.min.time())
            hours_left = int((midnight - now).total_seconds() / 3600)
            minutes_left = int(((midnight - now).total_seconds() % 3600) / 60)

            if state == StreakState.CRITICAL:
                emoji = "🚨"
                urgency = "КРИТИЧНО"
            else:
                emoji = "⚠️"
                urgency = "Внимание"

            return f"{emoji} <b>{urgency}!</b> До сброса стрика: <b>{hours_left}ч {minutes_left}м</b>"

        except Exception as e:
            logger.error(f"Error getting countdown: {e}")
            return None

    # ============================================================
    # MILESTONE CELEBRATIONS
    # ============================================================

    def get_milestone_message(
        self,
        milestone_type: str,
        value: int,
        level: StreakLevel
    ) -> Dict[str, any]:
        """
        Возвращает сообщение для milestone celebration.

        Returns:
            {
                'text': str,
                'keyboard': InlineKeyboardMarkup,
                'parse_mode': str
            }
        """
        milestones = {
            'daily': {
                7: {
                    'title': '🎉 НЕДЕЛЯ!',
                    'subtitle': '7 дней подряд! Отличное начало!',
                    'reward': '🎁 Бонус: 1 бесплатная заморозка',
                    'motivation': 'Продолжай в том же духе! 💪'
                },
                14: {
                    'title': '🏆 2 НЕДЕЛИ!',
                    'subtitle': 'Ты в топ-20% пользователей!',
                    'reward': '🎁 Бонус: +3 AI-проверки',
                    'motivation': 'Привычка формируется! 🚀'
                },
                30: {
                    'title': '👑 МЕСЯЦ!',
                    'subtitle': 'Невероятное достижение! Ты в топ-5%!',
                    'reward': '🎁 Награда: 1 заморозка + 5 AI-проверок',
                    'motivation': 'Ты настоящий мастер подготовки! ⭐'
                },
                60: {
                    'title': '💎 2 МЕСЯЦА!',
                    'subtitle': 'Фантастика! Ты в топ-2%!',
                    'reward': '🎁 Награда: 2 заморозки',
                    'motivation': 'Твоя целеустремленность вдохновляет! 🌟'
                },
                100: {
                    'title': '🌟 100 ДНЕЙ! ЛЕГЕНДА!',
                    'subtitle': 'Невероятное достижение! Ты в топ-1%!',
                    'reward': '🎁 Эксклюзив: Месяц Premium БЕСПЛАТНО',
                    'motivation': 'Ты вдохновляешь тысячи учеников! 👑'
                }
            },
            'correct': {
                5: {
                    'title': '🎯 5 ПРАВИЛЬНЫХ ПОДРЯД!',
                    'subtitle': 'Отличная точность!',
                    'reward': '🎁 Бонус: +1 AI-проверка',
                    'motivation': 'Продолжай так же! 💪'
                },
                10: {
                    'title': '🔥 10 ПРАВИЛЬНЫХ ПОДРЯД!',
                    'subtitle': 'Безупречная серия!',
                    'reward': '🎁 Награда: +2 AI-проверки + 1 щит от ошибок',
                    'motivation': 'Ты на пути к совершенству! ⭐'
                },
                20: {
                    'title': '⚡ 20 ПРАВИЛЬНЫХ ПОДРЯД!',
                    'subtitle': 'Фантастическая точность!',
                    'reward': '🎁 Награда: +3 AI-проверки',
                    'motivation': 'Твои знания впечатляют! 🏆'
                },
                50: {
                    'title': '💎 50 ПРАВИЛЬНЫХ ПОДРЯД!',
                    'subtitle': 'Перфекционист! Ты в топ-1%!',
                    'reward': '🎁 Эксклюзив: Скидка 20% на Premium',
                    'motivation': 'Твой уровень поразительный! 👑'
                }
            }
        }

        milestone_data = milestones.get(milestone_type, {}).get(value)
        if not milestone_data:
            return None

        # Формируем текст
        text = f"""
{milestone_data['title']}

{milestone_data['subtitle']}

{milestone_data['reward']}

{milestone_data['motivation']}

Продолжай занятия и достигни еще больших высот! 🚀
"""

        # Создаем клавиатуру
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎉 Отлично!", callback_data="milestone_acknowledged")],
            [InlineKeyboardButton("📊 Моя статистика", callback_data="my_stats")],
            [InlineKeyboardButton("📚 Продолжить занятия", callback_data="to_main_menu")]
        ])

        return {
            'text': text,
            'keyboard': keyboard,
            'parse_mode': ParseMode.HTML
        }

    # ============================================================
    # AT RISK WARNING UI
    # ============================================================

    def get_at_risk_warning_message(
        self,
        streak_value: int,
        hours_left: int,
        minutes_left: int
    ) -> Dict[str, any]:
        """Возвращает сообщение предупреждения об угрозе потери стрика"""

        if hours_left < 2:
            emoji = "🚨"
            title = "КРИТИЧНО"
            urgency_text = "ПОСЛЕДНИЙ ШАНС!"
        else:
            emoji = "⚠️"
            title = "ВНИМАНИЕ"
            urgency_text = "Твой стрик под угрозой!"

        text = f"""
{emoji} <b>{title}!</b>

{urgency_text}

Твой <b>{streak_value}-дневный стрик</b> сгорит через <b>{hours_left}ч {minutes_left}м</b>!

⏱ Ты потратил много времени на обучение
💪 Ты показал отличные результаты

Неужели сдаёшься?

Реши всего <b>1 задание</b> чтобы продолжить стрик!
"""

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✍️ Решить задание СЕЙЧАС", callback_data="start_practice")],
            [InlineKeyboardButton("🛡️ Магазин защит", callback_data="streak_shop")],
            [InlineKeyboardButton("👑 Premium подписка", callback_data="about_premium")]
        ])

        return {
            'text': text,
            'keyboard': keyboard,
            'parse_mode': ParseMode.HTML
        }

    # ============================================================
    # HELPER METHODS
    # ============================================================

    def _get_flame_emoji(self, days: int) -> str:
        """Возвращает эмодзи огоньков в зависимости от количества дней"""
        if days >= 100:
            return "💎🔥💎"  # Легенда
        elif days >= 60:
            return "🔥🔥🔥"  # Мастер
        elif days >= 30:
            return "🔥🔥🔥"  # Знаток
        elif days >= 14:
            return "🔥🔥"    # Практикант
        elif days >= 7:
            return "🔥"      # Ученик
        else:
            return "🔥"      # Новичок

    def _pluralize_days(self, days: int) -> str:
        """Склонение слова 'день'"""
        if days % 10 == 1 and days % 100 != 11:
            return "день"
        elif days % 10 in [2, 3, 4] and days % 100 not in [12, 13, 14]:
            return "дня"
        else:
            return "дней"


# Глобальный экземпляр
_streak_ui_instance: Optional[StreakUI] = None


def get_streak_ui() -> StreakUI:
    """Возвращает глобальный экземпляр StreakUI"""
    global _streak_ui_instance
    if _streak_ui_instance is None:
        _streak_ui_instance = StreakUI()
    return _streak_ui_instance
