"""
StreakManager - Управление улучшенной системой стриков

Phase 1: Foundation
- Трекинг daily, correct, weekly стриков
- Управление состояниями (active, at_risk, critical, frozen, lost)
- Начисление milestone наград
- Интеграция с защитами стриков
"""

import logging
import aiosqlite
from datetime import datetime, date, timedelta, timezone
from typing import Dict, Optional, Tuple, List
from enum import Enum

from core.db import DATABASE_FILE

logger = logging.getLogger(__name__)


class StreakState(Enum):
    """Состояния стрика"""
    ACTIVE = "active"              # 🔥 Активен
    AT_RISK = "at_risk"            # ⚠️ Под угрозой (< 6 часов)
    CRITICAL = "critical"          # 🚨 Критично (< 2 часов)
    FROZEN = "frozen"              # ❄️ Заморожен
    LOST = "lost"                  # 💔 Потерян
    RECOVERABLE = "recoverable"    # 🔄 Можно восстановить (48ч)


class StreakLevel(Enum):
    """Уровни стрика"""
    NOVICE = (1, "Новичок", "🌱", 0)
    STUDENT = (2, "Ученик", "📚", 7)
    PRACTITIONER = (3, "Практикант", "🎯", 14)
    EXPERT = (4, "Знаток", "⭐", 30)
    MASTER = (5, "Мастер", "🏆", 60)
    LEGEND = (6, "Легенда", "👑", 100)

    def __init__(self, level: int, display_name: str, emoji: str, days_required: int):
        self.level = level
        self.display_name = display_name
        self.emoji = emoji
        self.days_required = days_required

    @classmethod
    def get_level_for_days(cls, days: int) -> 'StreakLevel':
        """Возвращает уровень для заданного количества дней"""
        if days >= 100:
            return cls.LEGEND
        elif days >= 60:
            return cls.MASTER
        elif days >= 30:
            return cls.EXPERT
        elif days >= 14:
            return cls.PRACTITIONER
        elif days >= 7:
            return cls.STUDENT
        else:
            return cls.NOVICE


class StreakManager:
    """Менеджер для управления стриками пользователей"""

    def __init__(self, database_file: str = DATABASE_FILE):
        self.database_file = database_file

    # ============================================================
    # DAILY STREAK MANAGEMENT
    # ============================================================

    async def update_daily_streak(self, user_id: int) -> Tuple[int, int, StreakLevel]:
        """
        Обновляет дневной стрик пользователя.

        Returns:
            (current_streak, max_streak, streak_level)
        """
        try:
            async with aiosqlite.connect(self.database_file) as db:
                today = datetime.now(timezone.utc).date().isoformat()

                # Получаем текущие данные
                cursor = await db.execute("""
                    SELECT last_activity_date,
                           current_daily_streak,
                           max_daily_streak,
                           daily_streak_level
                    FROM user_streaks
                    WHERE user_id = ?
                """, (user_id,))

                row = await cursor.fetchone()

                if not row:
                    # Первая активность пользователя
                    await self._create_user_streak_record(db, user_id)
                    current_streak = 1
                    max_streak = 1
                    level = StreakLevel.NOVICE
                else:
                    last_activity_str = row[0]
                    current_streak = row[1] or 0
                    max_streak = row[2] or 0
                    current_level = row[3] or 1

                    # Логика обновления стрика
                    if last_activity_str == today:
                        # Уже были сегодня
                        level = StreakLevel.get_level_for_days(current_streak)
                        return (current_streak, max_streak, level)

                    if last_activity_str:
                        last_activity = date.fromisoformat(last_activity_str)
                        days_diff = (datetime.now(timezone.utc).date() - last_activity).days

                        if days_diff == 1:
                            # Вчера были - продолжаем стрик
                            current_streak += 1
                            max_streak = max(max_streak, current_streak)
                            logger.info(f"User {user_id} streak continues: {current_streak} days")
                        elif days_diff > 1:
                            # Пропустили дни - пробуем применить заморозки (Phase 3)
                            days_missed = days_diff - 1
                            freeze_count = await self._get_freeze_count(db, user_id)

                            if freeze_count >= days_missed:
                                # Применяем заморозки автоматически
                                await self._apply_freeze(db, user_id, days_missed, current_streak)
                                logger.info(
                                    f"User {user_id} missed {days_missed} days, "
                                    f"applied {days_missed} freeze(s), streak saved: {current_streak}"
                                )
                                # Стрик не сбрасывается, но заморозки потрачены
                            else:
                                # Заморозок недостаточно - сбрасываем стрик
                                logger.info(
                                    f"User {user_id} missed {days_missed} days, "
                                    f"only {freeze_count} freeze(s) available, resetting streak from {current_streak}"
                                )

                                # Сохраняем информацию для возможного восстановления
                                await self._mark_streak_lost(db, user_id, current_streak)

                                current_streak = 1
                    else:
                        # Первая активность
                        current_streak = 1
                        max_streak = max(max_streak, 1)

                    level = StreakLevel.get_level_for_days(current_streak)

                # Обновляем в БД
                await db.execute("""
                    UPDATE user_streaks
                    SET current_daily_streak = ?,
                        max_daily_streak = ?,
                        last_activity_date = ?,
                        daily_streak_level = ?,
                        longest_streak_ever = MAX(longest_streak_ever, ?),
                        total_days_active = total_days_active + 1,
                        streak_state = 'active',
                        updated_at = ?
                    WHERE user_id = ?
                """, (
                    current_streak,
                    max_streak,
                    today,
                    level.level,
                    max_streak,
                    datetime.now(timezone.utc).isoformat(),
                    user_id
                ))

                await db.commit()

                # Проверяем milestone
                await self._check_and_grant_milestone(db, user_id, 'daily', current_streak)

                logger.info(f"Updated daily streak for user {user_id}: {current_streak}/{max_streak}, level {level.display_name}")

                return (current_streak, max_streak, level)

        except Exception as e:
            logger.error(f"Error updating daily streak for user {user_id}: {e}", exc_info=True)
            return (0, 0, StreakLevel.NOVICE)

    async def get_daily_streak_info(self, user_id: int) -> Dict:
        """Получает информацию о дневном стрике пользователя"""
        try:
            async with aiosqlite.connect(self.database_file) as db:
                cursor = await db.execute("""
                    SELECT current_daily_streak,
                           max_daily_streak,
                           daily_streak_level,
                           last_activity_date,
                           streak_state,
                           freeze_count
                    FROM user_streaks
                    WHERE user_id = ?
                """, (user_id,))

                row = await cursor.fetchone()

                if not row:
                    return {
                        'current': 0,
                        'max': 0,
                        'level': StreakLevel.NOVICE,
                        'last_activity': None,
                        'state': StreakState.ACTIVE,
                        'freezes_available': 0
                    }

                current_streak = row[0] or 0
                level = StreakLevel.get_level_for_days(current_streak)

                return {
                    'current': current_streak,
                    'max': row[1] or 0,
                    'level': level,
                    'last_activity': row[3],
                    'state': StreakState(row[4]) if row[4] else StreakState.ACTIVE,
                    'freezes_available': row[5] or 0
                }

        except Exception as e:
            logger.error(f"Error getting daily streak info: {e}")
            return {'current': 0, 'max': 0, 'level': StreakLevel.NOVICE}

    # ============================================================
    # CORRECT ANSWER STREAK MANAGEMENT
    # ============================================================

    async def update_correct_streak(self, user_id: int, is_correct: bool) -> Tuple[int, int]:
        """
        Обновляет стрик правильных ответов.

        Args:
            user_id: ID пользователя
            is_correct: Правильный ли ответ

        Returns:
            (current_correct_streak, max_correct_streak)
        """
        try:
            async with aiosqlite.connect(self.database_file) as db:
                # Получаем текущие данные
                cursor = await db.execute("""
                    SELECT current_correct_streak,
                           max_correct_streak,
                           error_shield_count
                    FROM user_streaks
                    WHERE user_id = ?
                """, (user_id,))

                row = await cursor.fetchone()

                if not row:
                    await self._create_user_streak_record(db, user_id)
                    current_streak = 1 if is_correct else 0
                    max_streak = current_streak
                else:
                    current_streak = row[0] or 0
                    max_streak = row[1] or 0
                    shields = row[2] or 0

                    if is_correct:
                        # Правильный ответ - увеличиваем стрик
                        current_streak += 1
                        max_streak = max(max_streak, current_streak)
                        logger.info(f"User {user_id} correct streak: {current_streak}")
                    else:
                        # Неправильный ответ
                        if shields > 0:
                            # Есть щит - используем его
                            logger.info(f"User {user_id} used error shield, streak saved: {current_streak}")
                            await self._use_error_shield(db, user_id, current_streak)
                            # Стрик НЕ сбрасывается
                        else:
                            # Нет щита - сбрасываем стрик
                            logger.info(f"User {user_id} correct streak reset from {current_streak}")
                            current_streak = 0

                # Обновляем в БД
                await db.execute("""
                    UPDATE user_streaks
                    SET current_correct_streak = ?,
                        max_correct_streak = ?,
                        updated_at = ?
                    WHERE user_id = ?
                """, (
                    current_streak,
                    max_streak,
                    datetime.now(timezone.utc).isoformat(),
                    user_id
                ))

                await db.commit()

                # Проверяем milestone для correct streak
                if is_correct:
                    await self._check_and_grant_milestone(db, user_id, 'correct', current_streak)

                return (current_streak, max_streak)

        except Exception as e:
            logger.error(f"Error updating correct streak: {e}", exc_info=True)
            return (0, 0)

    # ============================================================
    # STREAK STATE MANAGEMENT
    # ============================================================

    async def check_and_update_streak_states(self) -> List[Tuple[int, StreakState]]:
        """
        Проверяет и обновляет состояния стриков для всех пользователей.
        Возвращает список (user_id, new_state) для уведомлений.
        """
        users_to_notify = []

        try:
            async with aiosqlite.connect(self.database_file) as db:
                # Получаем всех пользователей с активными стриками
                cursor = await db.execute("""
                    SELECT user_id,
                           current_daily_streak,
                           last_activity_date,
                           streak_state,
                           at_risk_notified,
                           critical_notified
                    FROM user_streaks
                    WHERE current_daily_streak > 0
                      AND streak_state IN ('active', 'at_risk', 'critical')
                """)

                users = await cursor.fetchall()
                now = datetime.now(timezone.utc)

                for row in users:
                    user_id = row[0]
                    streak = row[1]
                    last_activity = row[2]
                    current_state = row[3]
                    at_risk_notified = row[4]
                    critical_notified = row[5]

                    if not last_activity:
                        continue

                    last_activity_date = date.fromisoformat(last_activity)
                    hours_since_activity = (now.date() - last_activity_date).days * 24

                    # Определяем новое состояние
                    new_state = None

                    if hours_since_activity >= 24:
                        # Стрик потерян
                        new_state = StreakState.LOST
                    elif hours_since_activity >= 22:
                        # Критично (< 2 часов)
                        if current_state != 'critical' and not critical_notified:
                            new_state = StreakState.CRITICAL
                    elif hours_since_activity >= 18:
                        # Под угрозой (< 6 часов)
                        if current_state != 'at_risk' and not at_risk_notified:
                            new_state = StreakState.AT_RISK

                    # Обновляем состояние
                    if new_state:
                        await db.execute("""
                            UPDATE user_streaks
                            SET streak_state = ?,
                                at_risk_notified = ?,
                                critical_notified = ?,
                                updated_at = ?
                            WHERE user_id = ?
                        """, (
                            new_state.value,
                            1 if new_state == StreakState.AT_RISK else at_risk_notified,
                            1 if new_state == StreakState.CRITICAL else critical_notified,
                            datetime.now(timezone.utc).isoformat(),
                            user_id
                        ))

                        users_to_notify.append((user_id, new_state))
                        logger.info(f"User {user_id} streak state changed to {new_state.value}")

                await db.commit()

        except Exception as e:
            logger.error(f"Error checking streak states: {e}", exc_info=True)

        return users_to_notify

    # ============================================================
    # MILESTONE & REWARDS
    # ============================================================

    async def _check_and_grant_milestone(
        self,
        db: aiosqlite.Connection,
        user_id: int,
        milestone_type: str,
        value: int
    ):
        """Проверяет и выдает награды за milestone"""

        # Определяем milestone точки
        milestones = {
            'daily': {
                7: ('First Week', '🎁 1 заморозка'),
                14: ('Two Weeks', None),
                30: ('Month Master', '🎁 1 заморозка + 5 AI-проверок'),
                60: ('Two Months', '🎁 2 заморозки'),
                100: ('Legend', '🎁 Месяц Premium')
            },
            'correct': {
                5: ('Perfect 5', '🎁 1 AI-проверка'),
                10: ('Perfect 10', '🎁 2 AI-проверки + 1 щит'),
                20: ('Perfect 20', '🎁 3 AI-проверки'),
                50: ('Perfectionist', '🎁 Скидка 20%'),
                100: ('Perfect 100', '🎁 Неделя Premium')
            }
        }

        if value not in milestones.get(milestone_type, {}):
            return

        milestone_name, rewards = milestones[milestone_type][value]

        # Проверяем, не выдавали ли уже
        cursor = await db.execute("""
            SELECT id FROM streak_milestones
            WHERE user_id = ?
              AND milestone_type = ?
              AND milestone_value = ?
        """, (user_id, milestone_type, value))

        if await cursor.fetchone():
            return  # Уже выдавали

        # Записываем milestone
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
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0)
        """, (
            user_id,
            milestone_type,
            value,
            milestone_name,
            datetime.now(timezone.utc).isoformat(),
            f"{milestone_type}_{value}",
            rewards
        ))

        # Выдаем награды
        if milestone_type == 'daily':
            if value == 7 or value == 30:
                # Выдаем заморозку
                await db.execute("""
                    UPDATE user_streaks
                    SET freeze_count = freeze_count + 1
                    WHERE user_id = ?
                """, (user_id,))

        elif milestone_type == 'correct':
            if value == 10:
                # Выдаем щит от ошибок
                await db.execute("""
                    UPDATE user_streaks
                    SET error_shield_count = error_shield_count + 1
                    WHERE user_id = ?
                """, (user_id,))

        logger.info(f"User {user_id} achieved milestone: {milestone_name}")

    # ============================================================
    # PROTECTION MECHANICS
    # ============================================================

    async def _use_error_shield(self, db: aiosqlite.Connection, user_id: int, streak_saved: int):
        """Использует щит от ошибок"""
        await db.execute("""
            UPDATE user_streaks
            SET error_shield_count = error_shield_count - 1
            WHERE user_id = ?
        """, (user_id,))

        # Логируем использование
        await db.execute("""
            INSERT INTO streak_protection_log (
                user_id,
                protection_type,
                streak_value_saved,
                streak_type,
                cost_rub,
                triggered_automatically,
                reason,
                used_at
            ) VALUES (?, 'error_shield', ?, 'correct', 0, 1, 'wrong_answer', ?)
        """, (user_id, streak_saved, datetime.now(timezone.utc).isoformat()))

    async def _get_freeze_count(self, db: aiosqlite.Connection, user_id: int) -> int:
        """Получает количество доступных заморозок"""
        cursor = await db.execute("""
            SELECT freeze_count FROM user_streaks WHERE user_id = ?
        """, (user_id,))
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def _apply_freeze(
        self,
        db: aiosqlite.Connection,
        user_id: int,
        days_count: int,
        streak_saved: int
    ):
        """Применяет заморозки для сохранения стрика"""
        # Списываем заморозки
        await db.execute("""
            UPDATE user_streaks
            SET freeze_count = freeze_count - ?
            WHERE user_id = ?
        """, (days_count, user_id))

        # Логируем использование
        await db.execute("""
            INSERT INTO streak_protection_log (
                user_id,
                protection_type,
                action,
                quantity,
                streak_days_affected,
                created_at
            ) VALUES (?, 'freeze', 'applied', ?, ?, ?)
        """, (user_id, days_count, streak_saved, datetime.now(timezone.utc).isoformat()))

        logger.info(f"Applied {days_count} freeze(s) for user {user_id}, saved streak: {streak_saved}")

    async def _mark_streak_lost(
        self,
        db: aiosqlite.Connection,
        user_id: int,
        lost_streak_value: int
    ):
        """Помечает стрик как потерянный для возможного восстановления"""
        await db.execute("""
            UPDATE user_streaks
            SET streak_state = 'lost',
                streak_before_loss = ?,
                streak_lost_at = ?
            WHERE user_id = ?
        """, (lost_streak_value, datetime.now(timezone.utc).isoformat(), user_id))

        logger.info(f"Marked streak as lost for user {user_id}: {lost_streak_value} days")

    # ============================================================
    # HELPER METHODS
    # ============================================================

    async def _create_user_streak_record(self, db: aiosqlite.Connection, user_id: int):
        """Создает запись для нового пользователя"""
        await db.execute("""
            INSERT OR IGNORE INTO user_streaks (
                user_id,
                current_daily_streak,
                max_daily_streak,
                daily_streak_level,
                streak_state,
                created_at,
                updated_at
            ) VALUES (?, 1, 1, 1, 'active', ?, ?)
        """, (
            user_id,
            datetime.now(timezone.utc).isoformat(),
            datetime.now(timezone.utc).isoformat()
        ))

    async def get_streak_visualization(self, user_id: int) -> str:
        """
        Возвращает визуализацию стрика для отображения в меню.

        Returns:
            Строка с эмодзи и информацией о стрике
        """
        info = await self.get_daily_streak_info(user_id)
        current = info['current']
        level = info['level']

        if current == 0:
            return "🔥 Начни свой стрик сегодня!"

        # Визуализация огоньков по уровням
        if current >= 100:
            flames = "💎🔥💎"  # Легенда
        elif current >= 60:
            flames = "🔥🔥🔥"  # Мастер (синий)
        elif current >= 30:
            flames = "🔥🔥🔥"  # Знаток (фиолетовый)
        elif current >= 14:
            flames = "🔥🔥"    # Практикант (красный)
        elif current >= 7:
            flames = "🔥"      # Ученик (оранжевый)
        else:
            flames = "🔥"      # Новичок (желтый)

        return f"{flames} {current} {self._pluralize_days(current)} подряд  {level.emoji} {level.display_name}"

    def _pluralize_days(self, days: int) -> str:
        """Склонение слова 'день'"""
        if days % 10 == 1 and days % 100 != 11:
            return "день"
        elif days % 10 in [2, 3, 4] and days % 100 not in [12, 13, 14]:
            return "дня"
        else:
            return "дней"


# Глобальный экземпляр
_streak_manager_instance: Optional[StreakManager] = None


def get_streak_manager() -> StreakManager:
    """Возвращает глобальный экземпляр StreakManager"""
    global _streak_manager_instance
    if _streak_manager_instance is None:
        _streak_manager_instance = StreakManager()
    return _streak_manager_instance
