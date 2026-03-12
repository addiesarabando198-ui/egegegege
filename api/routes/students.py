"""
Routes для работы с учениками учителя.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
import aiosqlite
import logging

from api.middleware.telegram_auth import get_current_teacher
from api.schemas.student import StudentsListResponse, Student, StudentStats
from teacher_mode.models import TeacherProfile
from teacher_mode.services.teacher_service import get_users_display_names
from teacher_mode.utils.datetime_utils import parse_datetime_safe, utc_now
from core.config import DATABASE_FILE

router = APIRouter()
logger = logging.getLogger(__name__)


async def get_student_statistics(student_id: int) -> StudentStats:
    """
    Получает статистику ученика.

    Args:
        student_id: ID ученика (user_id)

    Returns:
        StudentStats с статистикой
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            # Получаем количество завершенных заданий
            cursor = await db.execute("""
                SELECT COUNT(*) as count
                FROM homework_student_assignments
                WHERE student_id = ? AND status = 'completed'
            """, (student_id,))
            row = await cursor.fetchone()
            completed_assignments = row['count'] if row else 0

            # Получаем количество решенных вопросов и правильных ответов
            cursor = await db.execute("""
                SELECT
                    COUNT(*) as total_questions,
                    SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) as correct_answers
                FROM homework_progress
                WHERE student_id = ?
            """, (student_id,))
            row = await cursor.fetchone()
            total_questions_solved = row['total_questions'] if row and row['total_questions'] else 0
            correct_answers = row['correct_answers'] if row and row['correct_answers'] else 0

            # Вычисляем средний балл
            average_score = None
            if total_questions_solved > 0:
                average_score = round((correct_answers / total_questions_solved) * 100, 1)

            return StudentStats(
                completed_assignments=completed_assignments,
                average_score=average_score,
                total_questions_solved=total_questions_solved,
                correct_answers=correct_answers
            )

    except Exception as e:
        logger.error(f"Ошибка при получении статистики ученика: {e}")
        return StudentStats(
            completed_assignments=0,
            average_score=None,
            total_questions_solved=0,
            correct_answers=0
        )


@router.get(
    "/students",
    response_model=StudentsListResponse,
    summary="Получить список учеников",
    description="Возвращает список учеников учителя с их статистикой"
)
async def get_students(
    teacher: TeacherProfile = Depends(get_current_teacher),
    search: Optional[str] = Query(None, description="Поиск по имени или username"),
    limit: int = Query(50, ge=1, le=100, description="Количество записей"),
    offset: int = Query(0, ge=0, description="Смещение для пагинации")
) -> StudentsListResponse:
    """
    Получает список учеников текущего учителя.

    Поддерживает:
    - Поиск по имени или username
    - Пагинацию
    - Статистику по каждому ученику
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            # Базовый запрос для подсчета общего количества
            count_query = """
                SELECT COUNT(*) as count
                FROM teacher_student_relationships tsr
                JOIN users u ON tsr.student_id = u.user_id
                WHERE tsr.teacher_id = ? AND tsr.status = 'active'
            """
            count_params = [teacher.user_id]

            # Базовый запрос для получения данных
            data_query = """
                SELECT
                    tsr.id as relationship_id,
                    tsr.student_id,
                    tsr.invited_at,
                    u.user_id,
                    u.username,
                    u.first_name,
                    u.last_name
                FROM teacher_student_relationships tsr
                JOIN users u ON tsr.student_id = u.user_id
                WHERE tsr.teacher_id = ? AND tsr.status = 'active'
            """
            data_params = [teacher.user_id]

            # Добавляем поиск если указан
            if search:
                search_condition = """
                    AND (
                        u.first_name LIKE ? OR
                        u.last_name LIKE ? OR
                        u.username LIKE ?
                    )
                """
                search_param = f"%{search}%"
                count_query += search_condition
                data_query += search_condition
                count_params.extend([search_param, search_param, search_param])
                data_params.extend([search_param, search_param, search_param])

            # Получаем общее количество
            cursor = await db.execute(count_query, count_params)
            row = await cursor.fetchone()
            total = row['count'] if row else 0

            # Добавляем сортировку и пагинацию
            data_query += " ORDER BY tsr.invited_at DESC LIMIT ? OFFSET ?"
            data_params.extend([limit, offset])

            # Получаем данные учеников
            cursor = await db.execute(data_query, data_params)
            rows = await cursor.fetchall()

            # Формируем список учеников
            students = []
            for row in rows:
                # Формируем имя ученика
                first_name = row['first_name'] or ''
                last_name = row['last_name'] or ''
                full_name = f"{first_name} {last_name}".strip()
                if not full_name:
                    full_name = row['username'] or f"ID: {row['user_id']}"

                # Получаем статистику ученика
                stats = await get_student_statistics(row['student_id'])

                student = Student(
                    id=row['relationship_id'],
                    user_id=row['user_id'],
                    name=full_name,
                    username=row['username'],
                    connected_at=parse_datetime_safe(row['invited_at']) or utc_now(),
                    stats=stats
                )
                students.append(student)

            logger.info(f"Получен список учеников для учителя {teacher.user_id}: {len(students)} из {total}")

            return StudentsListResponse(
                total=total,
                students=students
            )

    except Exception as e:
        logger.error(f"Ошибка при получении списка учеников: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve students list"
        )


@router.get(
    "/students/{student_id}/stats",
    response_model=StudentStats,
    summary="Получить статистику ученика",
    description="Возвращает детальную статистику конкретного ученика"
)
async def get_student_stats(
    student_id: int,
    teacher: TeacherProfile = Depends(get_current_teacher)
) -> StudentStats:
    """
    Получает статистику конкретного ученика.

    Проверяет, что ученик подключен к данному учителю.
    """
    try:
        # Проверяем, что ученик принадлежит этому учителю
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT id
                FROM teacher_student_relationships
                WHERE teacher_id = ? AND student_id = ? AND status = 'active'
            """, (teacher.user_id, student_id))

            row = await cursor.fetchone()
            if not row:
                raise HTTPException(
                    status_code=404,
                    detail="Student not found or not connected to this teacher"
                )

        # Получаем статистику
        stats = await get_student_statistics(student_id)
        logger.info(f"Получена статистика ученика {student_id} для учителя {teacher.user_id}")

        return stats

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при получении статистики ученика: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve student statistics"
        )
