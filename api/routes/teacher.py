"""
Routes для профиля учителя и его статистики.
"""

from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
import aiosqlite
import logging

from api.middleware.telegram_auth import get_current_teacher
from api.schemas.teacher import TeacherProfileResponse, SubscriptionInfo, TeacherStats
from teacher_mode.models import TeacherProfile
from teacher_mode.services.teacher_service import get_teacher_students
from core.config import DATABASE_FILE

router = APIRouter()
logger = logging.getLogger(__name__)


async def get_teacher_statistics(teacher_id: int) -> TeacherStats:
    """
    Получает статистику учителя.

    Args:
        teacher_id: ID учителя (user_id)

    Returns:
        TeacherStats с статистикой
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            # Получаем количество учеников
            cursor = await db.execute("""
                SELECT COUNT(*) as count
                FROM teacher_student_relationships
                WHERE teacher_id = ? AND status = 'active'
            """, (teacher_id,))
            row = await cursor.fetchone()
            total_students = row['count'] if row else 0

            # Получаем количество всех заданий
            cursor = await db.execute("""
                SELECT COUNT(*) as count
                FROM homework_assignments
                WHERE teacher_id = ?
            """, (teacher_id,))
            row = await cursor.fetchone()
            total_assignments = row['count'] if row else 0

            # Получаем количество активных заданий
            cursor = await db.execute("""
                SELECT COUNT(*) as count
                FROM homework_assignments
                WHERE teacher_id = ? AND status = 'active'
            """, (teacher_id,))
            row = await cursor.fetchone()
            active_assignments = row['count'] if row else 0

            return TeacherStats(
                total_students=total_students,
                total_assignments=total_assignments,
                active_assignments=active_assignments
            )

    except Exception as e:
        logger.error(f"Ошибка при получении статистики учителя: {e}")
        return TeacherStats(
            total_students=0,
            total_assignments=0,
            active_assignments=0
        )


@router.get(
    "/profile",
    response_model=TeacherProfileResponse,
    summary="Получить профиль учителя",
    description="Возвращает информацию о профиле учителя, подписке и статистику"
)
async def get_profile(
    teacher: TeacherProfile = Depends(get_current_teacher)
) -> TeacherProfileResponse:
    """
    Получает профиль текущего учителя.

    Требует аутентификации через Telegram WebApp initData.
    """
    try:
        # Получаем статистику
        stats = await get_teacher_statistics(teacher.user_id)

        # Формируем информацию о подписке
        subscription = SubscriptionInfo(
            tier=teacher.subscription_tier,
            expires_at=teacher.subscription_expires,
            is_active=teacher.has_active_subscription
        )

        # Формируем ответ
        profile = TeacherProfileResponse(
            teacher_id=teacher.user_id,
            user_id=teacher.user_id,
            name=teacher.display_name,
            teacher_code=teacher.teacher_code,
            subscription=subscription,
            stats=stats
        )

        logger.info(f"Профиль учителя {teacher.user_id} успешно получен")
        return profile

    except Exception as e:
        logger.error(f"Ошибка при получении профиля учителя: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve teacher profile"
        )


@router.get(
    "/stats",
    response_model=TeacherStats,
    summary="Получить статистику учителя",
    description="Возвращает только статистику учителя"
)
async def get_stats(
    teacher: TeacherProfile = Depends(get_current_teacher)
) -> TeacherStats:
    """
    Получает статистику текущего учителя.

    Требует аутентификации через Telegram WebApp initData.
    """
    try:
        stats = await get_teacher_statistics(teacher.user_id)
        logger.info(f"Статистика учителя {teacher.user_id} успешно получена")
        return stats

    except Exception as e:
        logger.error(f"Ошибка при получении статистики учителя: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve teacher statistics"
        )
