"""
Timezone Manager - управление часовыми поясами пользователей

Обеспечивает:
- Автоматическое определение часового пояса
- Персонализированное время отправки уведомлений
- Проверку оптимального времени для каждого пользователя
"""

import logging
import aiosqlite
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Tuple, List
from zoneinfo import ZoneInfo

from core.db import DATABASE_FILE

logger = logging.getLogger(__name__)


# Популярные часовые пояса России с UTC offset
RUSSIA_TIMEZONES = {
    'Europe/Kaliningrad': {'offset': 2, 'name': 'Калининград'},
    'Europe/Moscow': {'offset': 3, 'name': 'Москва'},
    'Europe/Samara': {'offset': 4, 'name': 'Самара'},
    'Asia/Yekaterinburg': {'offset': 5, 'name': 'Екатеринбург'},
    'Asia/Omsk': {'offset': 6, 'name': 'Омск'},
    'Asia/Krasnoyarsk': {'offset': 7, 'name': 'Красноярск'},
    'Asia/Irkutsk': {'offset': 8, 'name': 'Иркутск'},
    'Asia/Yakutsk': {'offset': 9, 'name': 'Якутск'},
    'Asia/Vladivostok': {'offset': 10, 'name': 'Владивосток'},
    'Asia/Magadan': {'offset': 11, 'name': 'Магадан'},
    'Asia/Kamchatka': {'offset': 12, 'name': 'Камчатка'},
}

# Время, когда НЕ нужно отправлять уведомления (ночь)
QUIET_HOURS_START = 22  # 22:00
QUIET_HOURS_END = 8     # 08:00


class TimezoneManager:
    """Менеджер часовых поясов пользователей"""

    def __init__(self, database_file: str = DATABASE_FILE):
        self.database_file = database_file

    async def get_user_timezone(self, user_id: int) -> str:
        """
        Получает часовой пояс пользователя.

        Returns:
            Строка с часовым поясом (например, 'Europe/Moscow')
        """
        try:
            async with aiosqlite.connect(self.database_file) as db:
                cursor = await db.execute("""
                    SELECT timezone FROM user_timezone_info
                    WHERE user_id = ?
                """, (user_id,))
                row = await cursor.fetchone()

                if row and row[0]:
                    return row[0]

                return 'Europe/Moscow'  # Default

        except Exception as e:
            logger.error(f"Error getting timezone for user {user_id}: {e}")
            return 'Europe/Moscow'

    async def get_user_utc_offset(self, user_id: int) -> int:
        """
        Получает UTC offset пользователя в часах.

        Returns:
            Смещение от UTC в часах (например, 3 для Москвы)
        """
        try:
            async with aiosqlite.connect(self.database_file) as db:
                cursor = await db.execute("""
                    SELECT utc_offset_hours FROM user_timezone_info
                    WHERE user_id = ?
                """, (user_id,))
                row = await cursor.fetchone()

                if row and row[0] is not None:
                    return row[0]

                return 3  # Default (Moscow)

        except Exception as e:
            logger.error(f"Error getting UTC offset for user {user_id}: {e}")
            return 3

    async def set_user_timezone(
        self,
        user_id: int,
        timezone_id: str,
        detection_method: str = 'user_selected'
    ) -> bool:
        """
        Устанавливает часовой пояс пользователя.

        Args:
            user_id: ID пользователя
            timezone_id: ID часового пояса (например, 'Europe/Moscow')
            detection_method: Как определён ('user_selected', 'auto_detected', 'default')

        Returns:
            True если успешно
        """
        try:
            # Получаем UTC offset из справочника
            tz_info = RUSSIA_TIMEZONES.get(timezone_id)
            utc_offset = tz_info['offset'] if tz_info else 3

            async with aiosqlite.connect(self.database_file) as db:
                await db.execute("""
                    INSERT INTO user_timezone_info (
                        user_id, timezone, utc_offset_hours, detection_method, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(user_id) DO UPDATE SET
                        timezone = excluded.timezone,
                        utc_offset_hours = excluded.utc_offset_hours,
                        detection_method = excluded.detection_method,
                        updated_at = excluded.updated_at
                """, (
                    user_id,
                    timezone_id,
                    utc_offset,
                    detection_method,
                    datetime.now(timezone.utc).isoformat()
                ))
                await db.commit()

            logger.info(f"Set timezone {timezone_id} (UTC+{utc_offset}) for user {user_id}")
            return True

        except Exception as e:
            logger.error(f"Error setting timezone for user {user_id}: {e}")
            return False

    async def get_user_local_time(self, user_id: int) -> datetime:
        """
        Получает текущее локальное время пользователя.

        Returns:
            datetime в локальном часовом поясе пользователя
        """
        utc_offset = await self.get_user_utc_offset(user_id)
        now_utc = datetime.now(timezone.utc)
        user_time = now_utc + timedelta(hours=utc_offset)
        return user_time

    async def get_user_local_hour(self, user_id: int) -> int:
        """
        Получает текущий час в локальном времени пользователя.

        Returns:
            Час дня (0-23)
        """
        user_time = await self.get_user_local_time(user_id)
        return user_time.hour

    async def is_quiet_hours(self, user_id: int) -> bool:
        """
        Проверяет, сейчас ли "тихие часы" у пользователя (ночь).

        Returns:
            True если сейчас ночь (22:00 - 08:00 локального времени)
        """
        local_hour = await self.get_user_local_hour(user_id)

        # Тихие часы: 22:00 - 08:00
        if QUIET_HOURS_START <= local_hour or local_hour < QUIET_HOURS_END:
            return True

        return False

    async def is_optimal_notification_time(
        self,
        user_id: int,
        preferred_hour: int = 18,
        tolerance: int = 2
    ) -> bool:
        """
        Проверяет, оптимальное ли сейчас время для отправки уведомления.

        Args:
            user_id: ID пользователя
            preferred_hour: Предпочитаемый час (по умолчанию 18:00)
            tolerance: Допустимое отклонение в часах

        Returns:
            True если сейчас оптимальное время (±tolerance от preferred_hour)
        """
        # Проверяем тихие часы
        if await self.is_quiet_hours(user_id):
            return False

        local_hour = await self.get_user_local_hour(user_id)

        # Проверяем близость к предпочитаемому часу
        diff = abs(local_hour - preferred_hour)
        # Учитываем переход через полночь
        diff = min(diff, 24 - diff)

        return diff <= tolerance

    async def get_users_for_notification_now(
        self,
        preferred_hour: int = 18,
        tolerance: int = 2
    ) -> List[int]:
        """
        Получает список пользователей, для которых сейчас оптимальное время уведомления.

        Args:
            preferred_hour: Предпочитаемый час (18:00)
            tolerance: Допустимое отклонение (±2 часа)

        Returns:
            Список user_id
        """
        try:
            async with aiosqlite.connect(self.database_file) as db:
                now_utc = datetime.now(timezone.utc)
                current_utc_hour = now_utc.hour

                # Собираем пользователей, у которых сейчас оптимальное время
                users = []

                cursor = await db.execute("""
                    SELECT user_id, utc_offset_hours,
                           COALESCE(optimal_notification_hour, 18) as pref_hour
                    FROM user_timezone_info
                """)
                rows = await cursor.fetchall()

                for row in rows:
                    user_id, utc_offset, pref_hour = row
                    utc_offset = utc_offset or 3

                    # Вычисляем локальный час
                    local_hour = (current_utc_hour + utc_offset) % 24

                    # Проверяем тихие часы
                    if QUIET_HOURS_START <= local_hour or local_hour < QUIET_HOURS_END:
                        continue

                    # Проверяем близость к предпочитаемому часу
                    diff = abs(local_hour - (pref_hour or preferred_hour))
                    diff = min(diff, 24 - diff)

                    if diff <= tolerance:
                        users.append(user_id)

                return users

        except Exception as e:
            logger.error(f"Error getting users for notification: {e}")
            return []

    async def calculate_time_until_midnight_user(self, user_id: int) -> Tuple[int, int]:
        """
        Вычисляет время до полуночи в локальном времени пользователя.

        Returns:
            (hours_left, minutes_left)
        """
        user_time = await self.get_user_local_time(user_id)

        # Полночь следующего дня
        midnight = user_time.replace(
            hour=0, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)

        time_left = midnight - user_time

        hours_left = int(time_left.total_seconds() // 3600)
        minutes_left = int((time_left.total_seconds() % 3600) // 60)

        return hours_left, minutes_left

    async def ensure_user_timezone_record(self, user_id: int) -> None:
        """
        Создаёт запись о часовом поясе для нового пользователя (если не существует).
        """
        try:
            async with aiosqlite.connect(self.database_file) as db:
                await db.execute("""
                    INSERT OR IGNORE INTO user_timezone_info (
                        user_id, timezone, utc_offset_hours, detection_method
                    ) VALUES (?, 'Europe/Moscow', 3, 'default')
                """, (user_id,))
                await db.commit()

        except Exception as e:
            logger.error(f"Error ensuring timezone record for user {user_id}: {e}")

    async def reset_daily_notification_counters(self) -> int:
        """
        Сбрасывает ежедневные счётчики уведомлений.
        Должна вызываться каждый день в полночь UTC.

        Returns:
            Количество сброшенных записей
        """
        try:
            async with aiosqlite.connect(self.database_file) as db:
                cursor = await db.execute("""
                    UPDATE notification_preferences
                    SET notification_count_today = 0,
                        last_count_reset_date = ?
                    WHERE notification_count_today > 0
                """, (datetime.now(timezone.utc).date().isoformat(),))

                reset_count = cursor.rowcount

                # Логируем сброс
                await db.execute("""
                    INSERT INTO notification_reset_log (reset_type, users_reset)
                    VALUES ('daily', ?)
                """, (reset_count,))

                await db.commit()

                logger.info(f"Reset daily notification counters for {reset_count} users")
                return reset_count

        except Exception as e:
            logger.error(f"Error resetting daily counters: {e}")
            return 0

    async def reset_weekly_notification_counters(self) -> int:
        """
        Сбрасывает еженедельные счётчики уведомлений.
        Должна вызываться каждый понедельник.

        Returns:
            Количество сброшенных записей
        """
        try:
            async with aiosqlite.connect(self.database_file) as db:
                cursor = await db.execute("""
                    UPDATE notification_preferences
                    SET notification_count_week = 0
                    WHERE notification_count_week > 0
                """)

                reset_count = cursor.rowcount

                # Логируем сброс
                await db.execute("""
                    INSERT INTO notification_reset_log (reset_type, users_reset)
                    VALUES ('weekly', ?)
                """, (reset_count,))

                await db.commit()

                logger.info(f"Reset weekly notification counters for {reset_count} users")
                return reset_count

        except Exception as e:
            logger.error(f"Error resetting weekly counters: {e}")
            return 0

    def get_timezone_options(self) -> List[Dict]:
        """
        Возвращает список доступных часовых поясов для выбора пользователем.

        Returns:
            Список словарей с информацией о часовых поясах
        """
        options = []
        for tz_id, info in RUSSIA_TIMEZONES.items():
            options.append({
                'id': tz_id,
                'name': info['name'],
                'offset': info['offset'],
                'display': f"UTC+{info['offset']} ({info['name']})"
            })
        return sorted(options, key=lambda x: x['offset'])


# Глобальный экземпляр
_timezone_manager_instance: Optional[TimezoneManager] = None


def get_timezone_manager() -> TimezoneManager:
    """Возвращает глобальный экземпляр менеджера часовых поясов"""
    global _timezone_manager_instance
    if _timezone_manager_instance is None:
        _timezone_manager_instance = TimezoneManager()
    return _timezone_manager_instance
