"""
Activity Calendar - GitHub-style календарь активности

Phase 4: Gamification
- Визуализация активности пользователя
- GitHub-style heat map
- Статистика за неделю/месяц/год
- Tracking goals и достижений
"""

import logging
import aiosqlite
from datetime import datetime, date, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from core.db import DATABASE_FILE

logger = logging.getLogger(__name__)


class ActivityCalendar:
    """Календарь активности пользователя"""

    def __init__(self, database_file: str = DATABASE_FILE):
        self.database_file = database_file

    # ============================================================
    # ACTIVITY TRACKING
    # ============================================================

    async def record_activity(
        self,
        user_id: int,
        questions_answered: int = 0,
        questions_correct: int = 0,
        ai_checks_used: int = 0,
        time_spent_minutes: int = 0
    ) -> bool:
        """Записывает активность пользователя за день"""
        try:
            today = date.today().isoformat()

            async with aiosqlite.connect(self.database_file) as db:
                # Проверяем, есть ли уже запись на сегодня
                cursor = await db.execute("""
                    SELECT id, questions_answered, questions_correct, time_spent_minutes
                    FROM daily_activity_calendar
                    WHERE user_id = ? AND activity_date = ?
                """, (user_id, today))

                row = await cursor.fetchone()

                if row:
                    # Обновляем существующую запись
                    await db.execute("""
                        UPDATE daily_activity_calendar
                        SET questions_answered = questions_answered + ?,
                            questions_correct = questions_correct + ?,
                            ai_checks_used = ai_checks_used + ?,
                            time_spent_minutes = time_spent_minutes + ?
                        WHERE user_id = ? AND activity_date = ?
                    """, (
                        questions_answered,
                        questions_correct,
                        ai_checks_used,
                        time_spent_minutes,
                        user_id,
                        today
                    ))
                else:
                    # Создаем новую запись
                    await db.execute("""
                        INSERT INTO daily_activity_calendar (
                            user_id,
                            activity_date,
                            questions_answered,
                            questions_correct,
                            ai_checks_used,
                            time_spent_minutes,
                            contributed_to_streak,
                            created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                    """, (
                        user_id,
                        today,
                        questions_answered,
                        questions_correct,
                        ai_checks_used,
                        time_spent_minutes,
                        datetime.now(timezone.utc).isoformat()
                    ))

                await db.commit()

            return True

        except Exception as e:
            logger.error(f"Error recording activity: {e}", exc_info=True)
            return False

    # ============================================================
    # CALENDAR VISUALIZATION
    # ============================================================

    async def get_calendar_heatmap(
        self,
        user_id: int,
        weeks: int = 12
    ) -> Tuple[str, Dict]:
        """
        Возвращает GitHub-style heat map активности.

        Args:
            user_id: ID пользователя
            weeks: Количество недель для отображения (по умолчанию 12 = ~3 месяца)

        Returns:
            (calendar_text, stats_dict)
        """
        try:
            # Получаем данные за период
            end_date = date.today()
            start_date = end_date - timedelta(weeks=weeks)

            async with aiosqlite.connect(self.database_file) as db:
                cursor = await db.execute("""
                    SELECT
                        activity_date,
                        questions_answered,
                        contributed_to_streak
                    FROM daily_activity_calendar
                    WHERE user_id = ?
                      AND activity_date >= ?
                      AND activity_date <= ?
                    ORDER BY activity_date ASC
                """, (user_id, start_date.isoformat(), end_date.isoformat()))

                rows = await cursor.fetchall()

            # Создаем словарь активности
            activity_map = {}
            for row in rows:
                activity_map[row[0]] = {
                    'questions': row[1],
                    'contributed': row[2]
                }

            # Строим календарь
            calendar_text = self._build_calendar_text(activity_map, start_date, end_date)

            # Считаем статистику
            stats = self._calculate_period_stats(activity_map)

            return calendar_text, stats

        except Exception as e:
            logger.error(f"Error getting calendar: {e}", exc_info=True)
            return "", {}

    def _build_calendar_text(
        self,
        activity_map: Dict,
        start_date: date,
        end_date: date
    ) -> str:
        """Строит текстовый календарь активности"""

        # Emoji для разных уровней активности
        def get_intensity_emoji(questions: int) -> str:
            if questions == 0:
                return "⬜"  # Нет активности
            elif questions < 5:
                return "🟩"  # Низкая активность
            elif questions < 15:
                return "🟦"  # Средняя активность
            elif questions < 30:
                return "🟪"  # Высокая активность
            else:
                return "🟨"  # Очень высокая активность

        calendar = "📅 <b>Твоя активность</b>\n\n"

        # Заголовок с месяцами
        calendar += "     "  # Отступ для дней недели

        current_month = start_date.month
        month_names = ['', 'Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн',
                      'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек']

        # Простая версия: показываем последние N недель по 7 дней
        weeks_to_show = []
        current_week = []

        # Начинаем с понедельника перед start_date
        current = start_date - timedelta(days=start_date.weekday())

        while current <= end_date:
            current_week.append(current)

            if len(current_week) == 7:
                weeks_to_show.append(current_week)
                current_week = []

            current += timedelta(days=1)

        # Добавляем последнюю неделю если она не полная
        if current_week:
            weeks_to_show.append(current_week)

        # Строим календарь по неделям
        weekday_labels = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

        # Показываем календарь
        for i, weekday in enumerate(weekday_labels):
            calendar += f"\n{weekday} "

            for week in weeks_to_show[-8:]:  # Показываем последние 8 недель
                if i < len(week):
                    day = week[i]
                    day_str = day.isoformat()

                    if day > end_date or day < start_date:
                        calendar += "  "  # Вне диапазона
                    else:
                        activity = activity_map.get(day_str, {'questions': 0})
                        emoji = get_intensity_emoji(activity['questions'])
                        calendar += emoji
                else:
                    calendar += "  "

        calendar += "\n\n"
        calendar += "🟩 1-4  🟦 5-14  🟪 15-29  🟨 30+  ⬜ 0\n"

        return calendar

    def _calculate_period_stats(self, activity_map: Dict) -> Dict:
        """Считает статистику за период"""
        total_days = len(activity_map)
        total_questions = sum(day['questions'] for day in activity_map.values())
        active_days = sum(1 for day in activity_map.values() if day['questions'] > 0)

        avg_per_day = total_questions / active_days if active_days > 0 else 0

        return {
            'total_days_tracked': total_days,
            'active_days': active_days,
            'total_questions': total_questions,
            'avg_per_active_day': round(avg_per_day, 1),
            'activity_rate': round(active_days / total_days * 100, 1) if total_days > 0 else 0
        }

    # ============================================================
    # WEEKLY/MONTHLY STATS
    # ============================================================

    async def get_week_stats(self, user_id: int) -> Dict:
        """Получает статистику за текущую неделю"""
        try:
            # Понедельник текущей недели
            today = date.today()
            week_start = today - timedelta(days=today.weekday())
            week_end = week_start + timedelta(days=6)

            async with aiosqlite.connect(self.database_file) as db:
                cursor = await db.execute("""
                    SELECT
                        COUNT(*) as days_active,
                        SUM(questions_answered) as total_questions,
                        SUM(questions_correct) as total_correct,
                        SUM(time_spent_minutes) as total_time
                    FROM daily_activity_calendar
                    WHERE user_id = ?
                      AND activity_date >= ?
                      AND activity_date <= ?
                """, (user_id, week_start.isoformat(), week_end.isoformat()))

                row = await cursor.fetchone()

                return {
                    'week_start': week_start.isoformat(),
                    'week_end': week_end.isoformat(),
                    'days_active': row[0] or 0,
                    'total_questions': row[1] or 0,
                    'total_correct': row[2] or 0,
                    'total_time_minutes': row[3] or 0,
                    'accuracy_percent': round((row[2] / row[1] * 100) if row[1] else 0, 1)
                }

        except Exception as e:
            logger.error(f"Error getting week stats: {e}", exc_info=True)
            return {}

    async def get_month_stats(self, user_id: int) -> Dict:
        """Получает статистику за текущий месяц"""
        try:
            today = date.today()
            month_start = today.replace(day=1)
            # Последний день месяца
            if today.month == 12:
                month_end = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                month_end = today.replace(month=today.month + 1, day=1) - timedelta(days=1)

            async with aiosqlite.connect(self.database_file) as db:
                cursor = await db.execute("""
                    SELECT
                        COUNT(*) as days_active,
                        SUM(questions_answered) as total_questions,
                        SUM(questions_correct) as total_correct,
                        SUM(time_spent_minutes) as total_time
                    FROM daily_activity_calendar
                    WHERE user_id = ?
                      AND activity_date >= ?
                      AND activity_date <= ?
                """, (user_id, month_start.isoformat(), month_end.isoformat()))

                row = await cursor.fetchone()

                return {
                    'month_start': month_start.isoformat(),
                    'month_end': month_end.isoformat(),
                    'days_in_month': (month_end - month_start).days + 1,
                    'days_active': row[0] or 0,
                    'total_questions': row[1] or 0,
                    'total_correct': row[2] or 0,
                    'total_time_minutes': row[3] or 0,
                    'accuracy_percent': round((row[2] / row[1] * 100) if row[1] else 0, 1)
                }

        except Exception as e:
            logger.error(f"Error getting month stats: {e}", exc_info=True)
            return {}

    # ============================================================
    # BEST DAY TRACKING
    # ============================================================

    async def get_best_day(self, user_id: int) -> Optional[Dict]:
        """Возвращает лучший день по количеству вопросов"""
        try:
            async with aiosqlite.connect(self.database_file) as db:
                cursor = await db.execute("""
                    SELECT
                        activity_date,
                        questions_answered,
                        questions_correct,
                        time_spent_minutes
                    FROM daily_activity_calendar
                    WHERE user_id = ?
                    ORDER BY questions_answered DESC
                    LIMIT 1
                """, (user_id,))

                row = await cursor.fetchone()

                if row:
                    return {
                        'date': row[0],
                        'questions_answered': row[1],
                        'questions_correct': row[2],
                        'time_spent_minutes': row[3],
                        'accuracy': round((row[2] / row[1] * 100) if row[1] else 0, 1)
                    }

                return None

        except Exception as e:
            logger.error(f"Error getting best day: {e}", exc_info=True)
            return None


# Глобальный экземпляр
_activity_calendar_instance: Optional[ActivityCalendar] = None


def get_activity_calendar() -> ActivityCalendar:
    """Возвращает глобальный экземпляр календаря активности"""
    global _activity_calendar_instance
    if _activity_calendar_instance is None:
        _activity_calendar_instance = ActivityCalendar()
    return _activity_calendar_instance
