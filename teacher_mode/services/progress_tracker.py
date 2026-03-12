"""
Сервис для отслеживания прогресса выполнения заданий.
"""

import logging
from datetime import datetime
from typing import List, Optional
import aiosqlite

from core.config import DATABASE_FILE
from ..models import HomeworkProgress
from ..utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)


async def save_homework_progress(
    homework_id: int,
    student_id: int,
    question_id: str,
    user_answer: str,
    is_correct: bool,
    ai_feedback: Optional[str] = None
) -> Optional[HomeworkProgress]:
    """
    Сохраняет прогресс по одному вопросу.

    Args:
        homework_id: ID задания
        student_id: ID ученика
        question_id: ID вопроса
        user_answer: Ответ ученика
        is_correct: Правильный ли ответ
        ai_feedback: Фидбэк от AI (опционально)

    Returns:
        HomeworkProgress или None при ошибке
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            now = utc_now()

            cursor = await db.execute("""
                INSERT INTO homework_progress
                (homework_id, student_id, question_id, user_answer, is_correct, ai_feedback, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (homework_id, student_id, question_id, user_answer, is_correct, ai_feedback, now))

            await db.commit()

            progress = HomeworkProgress(
                id=cursor.lastrowid,
                homework_id=homework_id,
                student_id=student_id,
                question_id=question_id,
                user_answer=user_answer,
                is_correct=is_correct,
                ai_feedback=ai_feedback,
                completed_at=now
            )

            logger.info(f"Saved progress for homework {homework_id}, student {student_id}, question {question_id}")
            return progress

    except Exception as e:
        logger.error(f"Error saving homework progress: {e}")
        return None


async def get_homework_progress(
    homework_id: int,
    student_id: int
) -> List[HomeworkProgress]:
    """
    Получает прогресс ученика по заданию.

    Args:
        homework_id: ID задания
        student_id: ID ученика

    Returns:
        Список HomeworkProgress
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT id, homework_id, student_id, question_id, user_answer,
                       is_correct, ai_feedback, completed_at
                FROM homework_progress
                WHERE homework_id = ? AND student_id = ?
                ORDER BY completed_at ASC
            """, (homework_id, student_id))

            rows = await cursor.fetchall()

            progress_list = []
            for row in rows:
                progress = HomeworkProgress(
                    id=row['id'],
                    homework_id=row['homework_id'],
                    student_id=row['student_id'],
                    question_id=row['question_id'],
                    user_answer=row['user_answer'],
                    is_correct=bool(row['is_correct']),
                    ai_feedback=row['ai_feedback'],
                    completed_at=datetime.fromisoformat(row['completed_at'])
                )
                progress_list.append(progress)

            return progress_list

    except Exception as e:
        logger.error(f"Error getting homework progress: {e}")
        return []


async def calculate_homework_completion(
    homework_id: int,
    student_id: int,
    total_questions: int
) -> dict:
    """
    Вычисляет процент выполнения задания.

    Args:
        homework_id: ID задания
        student_id: ID ученика
        total_questions: Всего вопросов в задании

    Returns:
        Dict с completed, total, percentage, correct, incorrect
    """
    progress = await get_homework_progress(homework_id, student_id)

    completed = len(progress)
    correct = sum(1 for p in progress if p.is_correct)
    incorrect = completed - correct
    percentage = (completed / total_questions * 100) if total_questions > 0 else 0

    return {
        'completed': completed,
        'total': total_questions,
        'percentage': round(percentage, 2),
        'correct': correct,
        'incorrect': incorrect
    }


async def is_homework_completed(
    homework_id: int,
    student_id: int,
    total_questions: int
) -> bool:
    """
    Проверяет, завершено ли задание учеником.

    Args:
        homework_id: ID задания
        student_id: ID ученика
        total_questions: Всего вопросов в задании

    Returns:
        True если все вопросы выполнены
    """
    completion = await calculate_homework_completion(homework_id, student_id, total_questions)
    return completion['completed'] >= total_questions


async def auto_complete_homework(
    homework_id: int,
    student_id: int,
    total_questions: int,
    bot=None
) -> bool:
    """
    Автоматически обновляет статус задания на 'completed', если все вопросы выполнены.
    Опционально отправляет уведомление учителю о завершении.

    Args:
        homework_id: ID задания
        student_id: ID ученика
        total_questions: Всего вопросов в задании
        bot: Telegram Bot instance для отправки уведомлений (опционально)

    Returns:
        True если статус был обновлён
    """
    if await is_homework_completed(homework_id, student_id, total_questions):
        from . import assignment_service
        from ..models import StudentAssignmentStatus

        success = await assignment_service.update_student_assignment_status(
            homework_id,
            student_id,
            StudentAssignmentStatus.COMPLETED
        )

        if success:
            logger.info(f"Auto-completed homework {homework_id} for student {student_id}")

            # Отправляем уведомление учителю
            if bot:
                try:
                    from . import notification_service
                    from ...teacher_mode.services import teacher_service

                    # Получаем информацию о задании
                    homework = await assignment_service.get_homework_by_id(homework_id)
                    if homework:
                        # Получаем статистику выполнения
                        performance = await get_student_performance_summary(student_id, homework_id)
                        correct_count = performance.get('correct', 0)
                        total_count = performance.get('total', 0)

                        # Получаем имя ученика
                        student_names = await teacher_service.get_users_display_names([student_id])
                        student_name = student_names.get(student_id, f"Ученик {student_id}")

                        # Отправляем уведомление учителю
                        await notification_service.notify_teacher_about_completion(
                            bot=bot,
                            teacher_id=homework.teacher_id,
                            student_id=student_id,
                            student_name=student_name,
                            homework_id=homework_id,
                            homework_title=homework.title,
                            correct_count=correct_count,
                            total_count=total_count
                        )
                except Exception as e:
                    logger.error(f"Failed to send teacher notification: {e}")
                    # Не падаем, если уведомление не удалось отправить

        return success

    return False


async def get_student_performance_summary(
    student_id: int,
    homework_id: Optional[int] = None
) -> dict:
    """
    Получает сводку по успеваемости ученика.

    Args:
        student_id: ID ученика
        homework_id: ID конкретного задания (опционально)

    Returns:
        Dict с статистикой (total_questions, correct, incorrect, accuracy)
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            if homework_id:
                cursor = await db.execute("""
                    SELECT COUNT(*) as total,
                           SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) as correct
                    FROM homework_progress
                    WHERE student_id = ? AND homework_id = ?
                """, (student_id, homework_id))
            else:
                cursor = await db.execute("""
                    SELECT COUNT(*) as total,
                           SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) as correct
                    FROM homework_progress
                    WHERE student_id = ?
                """, (student_id,))

            row = await cursor.fetchone()

            total = row[0] if row else 0
            correct = row[1] if row and row[1] else 0
            incorrect = total - correct
            accuracy = (correct / total * 100) if total > 0 else 0

            return {
                'total_questions': total,
                'correct': correct,
                'incorrect': incorrect,
                'accuracy': round(accuracy, 2)
            }

    except Exception as e:
        logger.error(f"Error getting performance summary: {e}")
        return {
            'total_questions': 0,
            'correct': 0,
            'incorrect': 0,
            'accuracy': 0
        }
