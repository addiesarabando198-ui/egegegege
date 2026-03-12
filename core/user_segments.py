"""
Модуль сегментации пользователей для retention-стратегии.

Определяет 8 сегментов пользователей:
1. Bounced - зарегистрировался но не начал (1-7 дней)
2. Late Bounced - упущенные bounced (7-60 дней) - resurrection кампания
3. Curious - попробовал, но не зацепило
4. Active Free - активные бесплатники
5. Trial Users - пользователи на триале
6. Paying but Inactive - платят, но не используют
7. Churn Risk - риск отмены подписки
8. Cancelled - отменили подписку
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List
from enum import Enum
import aiosqlite

from core.db import DATABASE_FILE

logger = logging.getLogger(__name__)


class UserSegment(Enum):
    """Сегменты пользователей для retention"""
    BOUNCED = "bounced"
    LATE_BOUNCED = "late_bounced"  # Resurrection кампания для упущенных bounced
    CURIOUS = "curious"
    ACTIVE_FREE = "active_free"
    TRIAL_USER = "trial_user"
    PAYING_INACTIVE = "paying_inactive"
    CHURN_RISK = "churn_risk"
    CANCELLED = "cancelled"
    ACTIVE_PAYING = "active_paying"  # Активные платящие (не нуждаются в retention)


class UserSegmentClassifier:
    """Классификатор пользователей по сегментам"""

    def __init__(self, database_file: str = DATABASE_FILE):
        self.database_file = database_file

    async def get_user_activity_stats(self, user_id: int) -> Dict[str, Any]:
        """
        Получает статистику активности пользователя.

        Returns:
            Dict с метриками активности
        """
        try:
            async with aiosqlite.connect(self.database_file) as db:
                # Получаем основную информацию о пользователе
                cursor = await db.execute("""
                    SELECT created_at, last_activity_date, username, first_name
                    FROM users
                    WHERE user_id = ?
                """, (user_id,))
                user_row = await cursor.fetchone()

                if not user_row:
                    return None

                created_at_str, last_activity_str, username, first_name = user_row

                # Парсим даты
                try:
                    created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
                    # Если дата timezone-naive, добавляем UTC
                    if created_at.tzinfo is None:
                        created_at = created_at.replace(tzinfo=timezone.utc)
                except:
                    created_at = datetime.now(timezone.utc) - timedelta(days=1)

                try:
                    if last_activity_str:
                        last_activity = datetime.fromisoformat(last_activity_str.replace('Z', '+00:00'))
                        # Если дата timezone-naive, добавляем UTC
                        if last_activity.tzinfo is None:
                            last_activity = last_activity.replace(tzinfo=timezone.utc)
                    else:
                        last_activity = created_at
                except:
                    last_activity = created_at

                # Количество решённых вопросов
                cursor = await db.execute("""
                    SELECT COUNT(*) FROM answered_questions
                    WHERE user_id = ?
                """, (user_id,))
                answered_count = (await cursor.fetchone())[0]

                # Количество AI-проверок за всё время
                cursor = await db.execute("""
                    SELECT COALESCE(SUM(checks_used), 0) FROM user_ai_limits
                    WHERE user_id = ?
                """, (user_id,))
                ai_checks_total = (await cursor.fetchone())[0]

                # AI-проверки за сегодня
                today = datetime.now(timezone.utc).date()
                cursor = await db.execute("""
                    SELECT COALESCE(checks_used, 0) FROM user_ai_limits
                    WHERE user_id = ? AND check_date = ?
                """, (user_id, today.isoformat()))
                result = await cursor.fetchone()
                ai_checks_today = result[0] if result else 0

                # Активность за последнюю неделю
                week_ago = datetime.now(timezone.utc) - timedelta(days=7)
                cursor = await db.execute("""
                    SELECT COUNT(*) FROM answered_questions
                    WHERE user_id = ? AND timestamp > ?
                """, (user_id, week_ago.isoformat()))
                answered_week = (await cursor.fetchone())[0]

                # Дни с момента регистрации
                days_since_registration = (datetime.now(timezone.utc) - created_at).days

                # Дни неактивности
                days_inactive = (datetime.now(timezone.utc) - last_activity).days

                return {
                    'user_id': user_id,
                    'username': username,
                    'first_name': first_name,
                    'created_at': created_at,
                    'last_activity': last_activity,
                    'days_since_registration': days_since_registration,
                    'days_inactive': days_inactive,
                    'answered_total': answered_count,
                    'answered_week': answered_week,
                    'ai_checks_total': ai_checks_total,
                    'ai_checks_today': ai_checks_today
                }

        except Exception as e:
            logger.error(f"Error getting user activity stats for {user_id}: {e}")
            return None

    async def get_subscription_info(self, user_id: int) -> Dict[str, Any]:
        """
        Получает информацию о подписке пользователя.
        """
        try:
            async with aiosqlite.connect(self.database_file) as db:
                now = datetime.now(timezone.utc)

                cursor = await db.execute("""
                    SELECT
                        us.id, us.user_id, us.plan_id, us.created_at, us.expires_at,
                        COALESCE(ar.enabled, 0) as auto_renew
                    FROM user_subscriptions us
                    LEFT JOIN auto_renewal_settings ar ON us.user_id = ar.user_id
                    WHERE us.user_id = ? AND us.expires_at > ?
                    ORDER BY us.expires_at DESC
                    LIMIT 1
                """, (user_id, now.isoformat()))

                row = await cursor.fetchone()

                if not row:
                    # Проверяем была ли подписка раньше (истекшие)
                    cursor = await db.execute("""
                        SELECT
                            us.id, us.expires_at, us.plan_id
                        FROM user_subscriptions us
                        WHERE us.user_id = ? AND us.expires_at <= ?
                        ORDER BY us.expires_at DESC
                        LIMIT 1
                    """, (user_id, now.isoformat()))

                    expired_row = await cursor.fetchone()

                    if expired_row:
                        try:
                            end_date = datetime.fromisoformat(expired_row[1].replace('Z', '+00:00'))
                        except (ValueError, AttributeError):
                            return {'has_subscription': False, 'had_subscription': False}
                        # Если дата timezone-naive, добавляем UTC
                        if end_date.tzinfo is None:
                            end_date = end_date.replace(tzinfo=timezone.utc)
                        days_since_cancel = (datetime.now(timezone.utc) - end_date).days

                        return {
                            'has_subscription': False,
                            'had_subscription': True,
                            'days_since_cancel': days_since_cancel,
                            'last_plan_id': expired_row[2]
                        }

                    return {'has_subscription': False, 'had_subscription': False}

                # Парсим активную подписку
                sub_id, user_id, plan_id, start_date, end_date, auto_renew = row

                try:
                    start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                except (ValueError, AttributeError):
                    return {'has_subscription': False, 'had_subscription': False}
                # Если дата timezone-naive, добавляем UTC
                if start_dt.tzinfo is None:
                    start_dt = start_dt.replace(tzinfo=timezone.utc)

                try:
                    end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                except (ValueError, AttributeError):
                    return {'has_subscription': False, 'had_subscription': False}
                # Если дата timezone-naive, добавляем UTC
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=timezone.utc)

                days_until_expiry = (end_dt - datetime.now(timezone.utc)).days
                days_since_start = (datetime.now(timezone.utc) - start_dt).days

                # Определяем is_trial
                is_trial = plan_id == 'trial_7days' or (plan_id and 'trial' in plan_id.lower())

                return {
                    'has_subscription': True,
                    'is_trial': is_trial,
                    'plan_id': plan_id,
                    'start_date': start_dt,
                    'end_date': end_dt,
                    'days_until_expiry': days_until_expiry,
                    'days_since_start': days_since_start,
                    'auto_renew': bool(auto_renew)
                }

        except Exception as e:
            logger.error(f"Error getting subscription info for {user_id}: {e}")
            return {'has_subscription': False, 'had_subscription': False}

    async def classify_user(self, user_id: int) -> Optional[UserSegment]:
        """
        Классифицирует пользователя по сегменту.

        Returns:
            UserSegment или None если пользователь не найден
        """
        activity = await self.get_user_activity_stats(user_id)
        if not activity:
            return None

        subscription = await self.get_subscription_info(user_id)

        # Сегмент 1: BOUNCED
        # - Зарегистрировался но не решил ни одного вопроса
        # - Не использовал AI-проверку
        # - Прошло 1-7 дней
        if (activity['answered_total'] == 0 and
            activity['ai_checks_total'] == 0 and
            1 <= activity['days_since_registration'] <= 7):
            return UserSegment.BOUNCED

        # Сегмент 2: LATE_BOUNCED (Resurrection кампания)
        # - Зарегистрировался но не решил ни одного вопроса
        # - Не использовал AI-проверку
        # - Прошло 7-60 дней (упущенные bounced пользователи)
        if (activity['answered_total'] == 0 and
            activity['ai_checks_total'] == 0 and
            7 < activity['days_since_registration'] <= 60):
            return UserSegment.LATE_BOUNCED

        # Сегмент 3: CURIOUS
        # - Решил 1-10 вопросов
        # - Использовал 0-1 AI-проверку
        # - Неактивен 2-14 дней
        if (1 <= activity['answered_total'] <= 10 and
            activity['ai_checks_total'] <= 1 and
            2 <= activity['days_inactive'] <= 14 and
            not subscription['has_subscription']):
            return UserSegment.CURIOUS

        # Сегмент 4: ACTIVE_FREE
        # - Решает 5+ вопросов в неделю
        # - Регулярно использует AI-проверки
        # - Нет подписки
        # - Активен 7+ дней
        if (activity['answered_week'] >= 5 and
            activity['ai_checks_total'] >= 3 and
            not subscription['has_subscription'] and
            activity['days_since_registration'] >= 7):
            return UserSegment.ACTIVE_FREE

        # Сегмент 5: TRIAL_USER
        # - Есть триальная подписка
        if subscription['has_subscription'] and subscription.get('is_trial'):
            return UserSegment.TRIAL_USER

        # Сегмент 6: PAYING_INACTIVE
        # - Есть активная подписка (не trial)
        # - Неактивен 3+ дней
        if (subscription['has_subscription'] and
            not subscription.get('is_trial') and
            activity['days_inactive'] >= 3):
            return UserSegment.PAYING_INACTIVE

        # Сегмент 7: CHURN_RISK
        # - Подписка истекает через 3-7 дней
        # - Автопродление выключено
        # - Активность снизилась (< 5 вопросов за неделю)
        if (subscription['has_subscription'] and
            not subscription.get('is_trial') and
            3 <= subscription['days_until_expiry'] <= 7 and
            not subscription.get('auto_renew') and
            activity['answered_week'] < 5):
            return UserSegment.CHURN_RISK

        # Сегмент 8: CANCELLED
        # - Подписка была, но закончилась
        # - Прошло 1-14 дней после отмены
        if (subscription.get('had_subscription') and
            not subscription['has_subscription'] and
            1 <= subscription.get('days_since_cancel', 999) <= 14):
            return UserSegment.CANCELLED

        # Если ни один сегмент не подошёл - активный платящий (не нуждается в retention)
        if subscription['has_subscription'] and activity['days_inactive'] < 3:
            return UserSegment.ACTIVE_PAYING

        # Не классифицирован (вернём None или можно добавить сегмент "OTHER")
        return None

    async def get_users_by_segment(self, segment: UserSegment, limit: int = 100) -> List[int]:
        """
        Получает список user_id по сегменту.

        Args:
            segment: Сегмент пользователей
            limit: Максимальное количество пользователей

        Returns:
            Список user_id
        """
        try:
            async with aiosqlite.connect(self.database_file) as db:
                cursor = await db.execute("""
                    SELECT user_id FROM users
                    ORDER BY created_at DESC
                    LIMIT 1000
                """)

                all_users = await cursor.fetchall()

                segment_users = []
                for row in all_users:
                    user_id = row[0]
                    user_segment = await self.classify_user(user_id)

                    if user_segment == segment:
                        segment_users.append(user_id)

                        if len(segment_users) >= limit:
                            break

                return segment_users

        except Exception as e:
            logger.error(f"Error getting users by segment {segment}: {e}")
            return []


# Глобальный экземпляр
_classifier_instance: Optional[UserSegmentClassifier] = None


def get_segment_classifier() -> UserSegmentClassifier:
    """Возвращает глобальный экземпляр классификатора"""
    global _classifier_instance
    if _classifier_instance is None:
        _classifier_instance = UserSegmentClassifier()
    return _classifier_instance
