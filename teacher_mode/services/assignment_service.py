"""
Сервис для работы с домашними заданиями.
"""

import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any, Union
import aiosqlite

from core.config import DATABASE_FILE
from ..models import (
    HomeworkAssignment,
    HomeworkStudentAssignment,
    AssignmentType,
    AssignmentStatus,
    StudentAssignmentStatus,
    TargetType
)
from ..utils.datetime_utils import utc_now, parse_datetime_safe, datetime_to_iso

logger = logging.getLogger(__name__)


def _safe_json_loads(json_str: str, default: Any = None) -> Any:
    """
    Безопасно парсит JSON строку с fallback на default значение.

    Args:
        json_str: JSON строка для парсинга
        default: Значение по умолчанию при ошибке парсинга

    Returns:
        Распарсенное значение или default
    """
    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        logger.warning(f"Ошибка парсинга JSON: {e}, используем default значение")
        return default


async def create_homework_assignment(
    teacher_id: int,
    title: str,
    assignment_type: AssignmentType,
    assignment_data: Dict[str, Any],
    target_type: TargetType,
    student_ids: List[int],
    description: Optional[str] = None,
    deadline: Optional[datetime] = None
) -> Optional[HomeworkAssignment]:
    """
    Создает домашнее задание.

    ИСПРАВЛЕНО:
    - Добавлены явные транзакции для атомарности
    - Используется batch INSERT для назначений учеников
    - Добавлен rollback при ошибках

    Args:
        teacher_id: ID учителя
        title: Название задания
        assignment_type: Тип задания
        assignment_data: Данные задания (JSON)
        target_type: Кому назначено
        student_ids: Список ID учеников
        description: Описание (опционально)
        deadline: Дедлайн (опционально)

    Returns:
        HomeworkAssignment или None при ошибке
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # ИСПРАВЛЕНО: Явная транзакция для атомарности
            await db.execute("BEGIN TRANSACTION")

            try:
                now = utc_now()  # ИСПРАВЛЕНО: timezone-aware datetime
                assignment_data_json = json.dumps(assignment_data)

                # ИСПРАВЛЕНО: убеждаемся что deadline тоже timezone-aware
                deadline_iso = datetime_to_iso(deadline) if deadline else None

                cursor = await db.execute("""
                    INSERT INTO homework_assignments
                    (teacher_id, created_at, title, description, deadline,
                     assignment_type, assignment_data, target_type, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')
                """, (
                    teacher_id,
                    now.isoformat(),
                    title,
                    description,
                    deadline_iso,
                    assignment_type.value,
                    assignment_data_json,
                    target_type.value
                ))

                homework_id = cursor.lastrowid

                # ИСПРАВЛЕНО: Batch INSERT для всех назначений за один раз
                student_assignments = [
                    (homework_id, student_id, now.isoformat(), 'assigned')
                    for student_id in student_ids
                ]

                await db.executemany("""
                    INSERT INTO homework_student_assignments
                    (homework_id, student_id, assigned_at, status)
                    VALUES (?, ?, ?, ?)
                """, student_assignments)

                # ИСПРАВЛЕНО: Коммит только если все прошло успешно
                await db.commit()

                homework = HomeworkAssignment(
                    id=homework_id,
                    teacher_id=teacher_id,
                    created_at=now,
                    title=title,
                    description=description,
                    deadline=deadline,
                    assignment_type=assignment_type,
                    assignment_data=assignment_data,
                    target_type=target_type,
                    status=AssignmentStatus.ACTIVE
                )

                logger.info(f"Создано ДЗ id={homework_id} от учителя {teacher_id} для {len(student_ids)} учеников")
                return homework

            except Exception as inner_e:
                # ИСПРАВЛЕНО: Откат транзакции при любой ошибке
                await db.rollback()
                logger.error(f"Ошибка внутри транзакции при создании ДЗ: {inner_e}")
                raise

    except Exception as e:
        logger.error(f"Ошибка при создании домашнего задания: {e}")
        return None


async def assign_homework_to_student(
    homework_id: int,
    student_id: int
) -> Optional[HomeworkStudentAssignment]:
    """
    Назначает задание конкретному ученику.

    Args:
        homework_id: ID задания
        student_id: ID ученика

    Returns:
        HomeworkStudentAssignment или None при ошибке
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            now = utc_now()  # ИСПРАВЛЕНО: timezone-aware datetime

            cursor = await db.execute("""
                INSERT INTO homework_student_assignments
                (homework_id, student_id, assigned_at, status)
                VALUES (?, ?, ?, 'assigned')
            """, (homework_id, student_id, now.isoformat()))

            await db.commit()

            assignment = HomeworkStudentAssignment(
                id=cursor.lastrowid,
                homework_id=homework_id,
                student_id=student_id,
                assigned_at=now,
                status=StudentAssignmentStatus.ASSIGNED
            )

            logger.info(f"Назначено ДЗ {homework_id} ученику {student_id}")
            return assignment

    except aiosqlite.IntegrityError:
        logger.warning(f"Задание {homework_id} уже назначено ученику {student_id}")
        return None
    except Exception as e:
        logger.error(f"Ошибка при назначении задания ученику: {e}")
        return None


async def get_student_homeworks(student_id: int) -> List[HomeworkStudentAssignment]:
    """
    Получает список домашних заданий ученика с их статусами.

    Args:
        student_id: ID ученика

    Returns:
        Список HomeworkStudentAssignment с заполненными данными о заданиях
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT
                    hsa.id as assignment_id,
                    hsa.homework_id,
                    hsa.student_id,
                    hsa.assigned_at,
                    hsa.completed_at,
                    hsa.status as student_status,
                    ha.teacher_id,
                    ha.created_at,
                    ha.title,
                    ha.description,
                    ha.deadline,
                    ha.assignment_type,
                    ha.assignment_data,
                    ha.target_type,
                    ha.status as homework_status
                FROM homework_student_assignments hsa
                JOIN homework_assignments ha ON hsa.homework_id = ha.id
                WHERE hsa.student_id = ?
                ORDER BY ha.deadline ASC, ha.created_at DESC
            """, (student_id,))

            rows = await cursor.fetchall()

            assignments = []
            for row in rows:
                assignment = HomeworkStudentAssignment(
                    id=row['assignment_id'],
                    homework_id=row['homework_id'],
                    student_id=row['student_id'],
                    assigned_at=parse_datetime_safe(row['assigned_at']) or utc_now(),  # ИСПРАВЛЕНО: безопасный парсинг
                    completed_at=parse_datetime_safe(row['completed_at']),  # ИСПРАВЛЕНО: безопасный парсинг
                    status=StudentAssignmentStatus(row['student_status'])
                )

                # Добавляем данные о задании для удобства
                assignment.title = row['title']
                assignment.description = row['description']
                assignment.deadline = parse_datetime_safe(row['deadline'])  # ИСПРАВЛЕНО: безопасный парсинг
                assignment.assignment_type = AssignmentType(row['assignment_type'])

                assignments.append(assignment)

            return assignments

    except Exception as e:
        logger.error(f"Ошибка при получении заданий ученика: {e}")
        return []


async def get_homework_by_id(homework_id: int) -> Optional[HomeworkAssignment]:
    """
    Получает домашнее задание по ID.

    Args:
        homework_id: ID задания

    Returns:
        HomeworkAssignment или None
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT id, teacher_id, created_at, title, description, deadline,
                       assignment_type, assignment_data, target_type, status
                FROM homework_assignments
                WHERE id = ?
            """, (homework_id,))

            row = await cursor.fetchone()
            if not row:
                return None

            return HomeworkAssignment(
                id=row['id'],
                teacher_id=row['teacher_id'],
                created_at=parse_datetime_safe(row['created_at']) or utc_now(),  # ИСПРАВЛЕНО: безопасный парсинг
                title=row['title'],
                description=row['description'],
                deadline=parse_datetime_safe(row['deadline']),  # ИСПРАВЛЕНО: безопасный парсинг
                assignment_type=AssignmentType(row['assignment_type']),
                assignment_data=_safe_json_loads(row['assignment_data'], {}),
                target_type=TargetType(row['target_type']),
                status=AssignmentStatus(row['status'])
            )

    except Exception as e:
        logger.error(f"Ошибка при получении задания по ID: {e}")
        return None


async def get_teacher_homeworks(teacher_id: int) -> List[HomeworkAssignment]:
    """
    Получает все домашние задания учителя.

    Args:
        teacher_id: ID учителя

    Returns:
        Список HomeworkAssignment
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT id, teacher_id, created_at, title, description, deadline,
                       assignment_type, assignment_data, target_type, status
                FROM homework_assignments
                WHERE teacher_id = ?
                ORDER BY created_at DESC
            """, (teacher_id,))

            rows = await cursor.fetchall()

            homeworks = []
            for row in rows:
                homework = HomeworkAssignment(
                    id=row['id'],
                    teacher_id=row['teacher_id'],
                    created_at=parse_datetime_safe(row['created_at']) or utc_now(),  # ИСПРАВЛЕНО: безопасный парсинг
                    title=row['title'],
                    description=row['description'],
                    deadline=parse_datetime_safe(row['deadline']),  # ИСПРАВЛЕНО: безопасный парсинг
                    assignment_type=AssignmentType(row['assignment_type']),
                    assignment_data=_safe_json_loads(row['assignment_data'], {}),
                    target_type=TargetType(row['target_type']),
                    status=AssignmentStatus(row['status'])
                )
                homeworks.append(homework)

            return homeworks

    except Exception as e:
        logger.error(f"Ошибка при получении заданий учителя: {e}")
        return []


async def update_homework_status(
    homework_id: int,
    status: AssignmentStatus
) -> bool:
    """
    Обновляет статус домашнего задания.

    Args:
        homework_id: ID задания
        status: Новый статус

    Returns:
        True если успешно
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute("""
                UPDATE homework_assignments
                SET status = ?
                WHERE id = ?
            """, (status.value, homework_id))

            await db.commit()

            logger.info(f"Обновлён статус задания {homework_id} на {status.value}")
            return True

    except Exception as e:
        logger.error(f"Ошибка при обновлении статуса задания: {e}")
        return False


async def update_student_assignment_status(
    homework_id: int,
    student_id: int,
    status: StudentAssignmentStatus
) -> bool:
    """
    Обновляет статус выполнения задания учеником.

    Args:
        homework_id: ID задания
        student_id: ID ученика
        status: Новый статус

    Returns:
        True если успешно
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Если статус "completed", добавляем время завершения
            if status == StudentAssignmentStatus.COMPLETED:
                await db.execute("""
                    UPDATE homework_student_assignments
                    SET status = ?, completed_at = ?
                    WHERE homework_id = ? AND student_id = ?
                """, (status.value, utc_now().isoformat(), homework_id, student_id))  # ИСПРАВЛЕНО: timezone-aware datetime
            else:
                await db.execute("""
                    UPDATE homework_student_assignments
                    SET status = ?
                    WHERE homework_id = ? AND student_id = ?
                """, (status.value, homework_id, student_id))

            await db.commit()

            logger.info(f"Обновлён статус задания {homework_id} для ученика {student_id} на {status.value}")
            return True

    except Exception as e:
        logger.error(f"Ошибка при обновлении статуса выполнения: {e}")
        return False


async def get_homework_statistics(homework_id: int) -> Dict[str, Any]:
    """
    Получает статистику по домашнему заданию.

    Args:
        homework_id: ID задания

    Returns:
        Словарь со статистикой
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            # Получаем количество учеников по статусам
            cursor = await db.execute("""
                SELECT status, COUNT(*) as count
                FROM homework_student_assignments
                WHERE homework_id = ?
                GROUP BY status
            """, (homework_id,))

            rows = await cursor.fetchall()

            stats = {
                'total': 0,
                'assigned': 0,
                'in_progress': 0,
                'completed': 0,
                'checked': 0
            }

            for row in rows:
                stats[row['status']] = row['count']
                stats['total'] += row['count']

            return stats

    except Exception as e:
        logger.error(f"Ошибка при получении статистики задания: {e}")
        return {'total': 0, 'assigned': 0, 'in_progress': 0, 'completed': 0, 'checked': 0}


async def get_completed_question_ids(homework_id: int, student_id: int) -> List[Union[int, str]]:
    """
    Получает список ID выполненных вопросов для конкретного задания и ученика.

    Args:
        homework_id: ID домашнего задания
        student_id: ID ученика

    Returns:
        Список ID выполненных вопросов (могут быть int или str для test_part)
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT question_id
                FROM homework_progress
                WHERE homework_id = ? AND student_id = ?
            """, (homework_id, student_id))

            rows = await cursor.fetchall()
            # Пытаемся преобразовать в int, если не получается - оставляем строкой
            result = []
            for row in rows:
                q_id = row['question_id']
                try:
                    result.append(int(q_id))
                except (ValueError, TypeError):
                    result.append(q_id)
            return result

    except Exception as e:
        logger.error(f"Ошибка при получении выполненных вопросов: {e}")
        return []


async def save_question_progress(homework_id: int, student_id: int, question_id: Union[int, str],
                                 user_answer: str, is_correct: bool,
                                 ai_feedback: Optional[str] = None) -> bool:
    """
    Сохраняет прогресс выполнения конкретного вопроса.

    Args:
        homework_id: ID домашнего задания
        student_id: ID ученика
        question_id: ID вопроса (int или str для test_part)
        user_answer: Ответ ученика
        is_correct: Правильность ответа
        ai_feedback: Обратная связь от AI (опционально)

    Returns:
        True если успешно сохранено, False иначе
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Сохраняем или обновляем прогресс
            await db.execute("""
                INSERT OR REPLACE INTO homework_progress
                (homework_id, student_id, question_id, user_answer, is_correct, ai_feedback, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (homework_id, student_id, str(question_id), user_answer, is_correct, ai_feedback))

            await db.commit()
            return True

    except Exception as e:
        logger.error(f"Ошибка при сохранении прогресса вопроса: {e}")
        return False


async def get_question_progress(homework_id: int, student_id: int, question_id: Union[int, str]) -> Optional[Dict]:
    """
    Получает прогресс выполнения конкретного вопроса.

    Args:
        homework_id: ID домашнего задания
        student_id: ID ученика
        question_id: ID вопроса (int или str для test_part)

    Returns:
        Словарь с данными прогресса или None если не найдено
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT id, homework_id, student_id, question_id, user_answer,
                       is_correct, ai_feedback, completed_at
                FROM homework_progress
                WHERE homework_id = ? AND student_id = ? AND question_id = ?
            """, (homework_id, student_id, str(question_id)))

            row = await cursor.fetchone()
            if not row:
                return None

            return {
                'id': row['id'],
                'homework_id': row['homework_id'],
                'student_id': row['student_id'],
                'question_id': row['question_id'],
                'user_answer': row['user_answer'],
                'is_correct': bool(row['is_correct']),
                'ai_feedback': row['ai_feedback'],
                'completed_at': row['completed_at']
            }

    except Exception as e:
        logger.error(f"Ошибка при получении прогресса вопроса: {e}")
        return None


async def get_homework_student_progress(homework_id: int, student_id: int) -> List[Dict]:
    """
    Получает полный прогресс ученика по домашнему заданию.

    Args:
        homework_id: ID домашнего задания
        student_id: ID ученика

    Returns:
        Список словарей с прогрессом по каждому вопросу
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

            return [
                {
                    'id': row['id'],
                    'homework_id': row['homework_id'],
                    'student_id': row['student_id'],
                    'question_id': int(row['question_id']),
                    'user_answer': row['user_answer'],
                    'is_correct': bool(row['is_correct']),
                    'ai_feedback': row['ai_feedback'],
                    'completed_at': row['completed_at']
                }
                for row in rows
            ]

    except Exception as e:
        logger.error(f"Ошибка при получении прогресса ученика: {e}")
        return []


async def get_homework_all_progress(homework_id: int) -> Dict[int, List[Dict]]:
    """
    Получает прогресс всех учеников по домашнему заданию.

    Args:
        homework_id: ID домашнего задания

    Returns:
        Словарь {student_id: [список прогресса]}
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT id, homework_id, student_id, question_id, user_answer,
                       is_correct, ai_feedback, completed_at
                FROM homework_progress
                WHERE homework_id = ?
                ORDER BY student_id, completed_at ASC
            """, (homework_id,))

            rows = await cursor.fetchall()

            # Группируем по student_id
            progress_by_student = {}
            for row in rows:
                student_id = row['student_id']
                if student_id not in progress_by_student:
                    progress_by_student[student_id] = []

                progress_by_student[student_id].append({
                    'id': row['id'],
                    'homework_id': row['homework_id'],
                    'student_id': row['student_id'],
                    'question_id': int(row['question_id']),
                    'user_answer': row['user_answer'],
                    'is_correct': bool(row['is_correct']),
                    'ai_feedback': row['ai_feedback'],
                    'completed_at': row['completed_at']
                })

            return progress_by_student

    except Exception as e:
        logger.error(f"Ошибка при получении прогресса всех учеников: {e}")
        return {}


async def add_teacher_comment(progress_id: int, teacher_comment: str) -> bool:
    """
    Добавляет комментарий учителя к ответу ученика.

    ИСПРАВЛЕНО: Использует отдельную колонку teacher_comment вместо
    добавления к ai_feedback, что предотвращает неконтролируемый рост текста.

    Args:
        progress_id: ID записи в homework_progress
        teacher_comment: Комментарий учителя

    Returns:
        True если успешно, False иначе
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # ИСПРАВЛЕНО: Записываем комментарий в отдельную колонку
            await db.execute("""
                UPDATE homework_progress
                SET teacher_comment = ?,
                    teacher_comment_at = ?
                WHERE id = ?
            """, (teacher_comment, utc_now().isoformat(), progress_id))

            await db.commit()
            logger.info(f"Комментарий учителя добавлен к progress_id={progress_id}")
            return True

    except Exception as e:
        logger.error(f"Ошибка при добавлении комментария учителя: {e}")
        return False


async def override_answer_score(progress_id: int, is_correct: bool) -> bool:
    """
    Переоценивает ответ ученика (изменяет статус is_correct).

    Args:
        progress_id: ID записи в homework_progress
        is_correct: Новый статус (True - принят, False - отклонен)

    Returns:
        True если успешно, False иначе
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute("""
                UPDATE homework_progress
                SET is_correct = ?
                WHERE id = ?
            """, (1 if is_correct else 0, progress_id))

            await db.commit()
            return True

    except Exception as e:
        logger.error(f"Ошибка при переоценке ответа: {e}")
        return False


async def get_question_progress_by_id(progress_id: int) -> Optional[Dict]:
    """
    Получает прогресс выполнения вопроса по ID записи.

    Args:
        progress_id: ID записи в homework_progress

    Returns:
        Словарь с данными прогресса или None
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT id, homework_id, student_id, question_id, user_answer,
                       is_correct, ai_feedback, completed_at
                FROM homework_progress
                WHERE id = ?
            """, (progress_id,))

            row = await cursor.fetchone()
            if not row:
                return None

            return {
                'id': row['id'],
                'homework_id': row['homework_id'],
                'student_id': row['student_id'],
                'question_id': int(row['question_id']),
                'user_answer': row['user_answer'],
                'is_correct': bool(row['is_correct']),
                'ai_feedback': row['ai_feedback'],
                'completed_at': row['completed_at']
            }

    except Exception as e:
        logger.error(f"Ошибка при получении прогресса по ID: {e}")
        return None


async def get_student_statistics(teacher_id: int, student_id: int) -> Optional[Dict]:
    """
    Получает детальную статистику ученика по всем заданиям учителя.

    ИСПРАВЛЕНО: Оптимизирован N+1 запрос - теперь используется один JOIN вместо
    N отдельных запросов для каждого задания.

    Args:
        teacher_id: ID учителя
        student_id: ID ученика

    Returns:
        Словарь со статистикой или None при ошибке
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            # ИСПРАВЛЕНО: Получаем все задания И их прогресс одним запросом с LEFT JOIN
            # Это устраняет N+1 проблему (было: 1 + N запросов, стало: 2 запроса)
            cursor = await db.execute("""
                SELECT
                    ha.id,
                    ha.title,
                    ha.assignment_type,
                    ha.assignment_data,
                    ha.created_at,
                    hp.question_id,
                    hp.is_correct
                FROM homework_assignments ha
                JOIN homework_student_assignments hsa ON ha.id = hsa.homework_id
                LEFT JOIN homework_progress hp ON hp.homework_id = ha.id AND hp.student_id = ?
                WHERE ha.teacher_id = ? AND hsa.student_id = ?
                ORDER BY ha.created_at DESC, hp.question_id
            """, (student_id, teacher_id, student_id))

            rows = await cursor.fetchall()

            if not rows:
                return {
                    'total_assignments': 0,
                    'completed_assignments': 0,
                    'total_questions': 0,
                    'total_answered': 0,
                    'correct_answers': 0,
                    'incorrect_answers': 0,
                    'accuracy_rate': 0,
                    'assignments_by_module': {},
                    'weak_modules': [],
                    'strong_modules': []
                }

            # Группируем результаты по заданиям
            assignments_dict = {}
            for row in rows:
                assignment_id = row['id']

                if assignment_id not in assignments_dict:
                    assignments_dict[assignment_id] = {
                        'id': assignment_id,
                        'title': row['title'],
                        'assignment_type': row['assignment_type'],
                        'assignment_data': _safe_json_loads(row['assignment_data'], {}),
                        'created_at': row['created_at'],
                        'progress': []
                    }

                # Добавляем прогресс (если есть)
                if row['question_id'] is not None:
                    assignments_dict[assignment_id]['progress'].append({
                        'question_id': row['question_id'],
                        'is_correct': bool(row['is_correct'])
                    })

            # Статистика по модулям
            module_stats = {}  # module_name -> {correct: int, incorrect: int, total: int}

            total_assignments = len(assignments_dict)
            completed_assignments = 0
            total_questions = 0
            correct_answers = 0
            incorrect_answers = 0

            for assignment_data in assignments_dict.values():
                assignment_json = assignment_data['assignment_data']
                progress_rows = assignment_data['progress']

                # Определяем модуль задания
                if assignment_json.get('is_custom'):
                    task_module = 'custom'
                elif assignment_json.get('is_mixed'):
                    # Для смешанных заданий учитываем все модули
                    modules_list = [m['task_module'] for m in assignment_json.get('modules', [])]
                else:
                    task_module = assignment_json.get('task_module', 'unknown')
                    modules_list = [task_module]

                # Подсчитываем вопросы
                if assignment_json.get('is_mixed'):
                    assignment_questions = assignment_json.get('total_questions_count', 0)
                elif assignment_json.get('is_custom'):
                    assignment_questions = len(assignment_json.get('custom_questions', []))
                else:
                    assignment_questions = assignment_json.get('questions_count', 0)

                total_questions += assignment_questions

                # Если ученик ответил на все вопросы, считаем задание завершенным
                if len(progress_rows) >= assignment_questions:
                    completed_assignments += 1

                # Подсчитываем правильные/неправильные ответы
                for progress_row in progress_rows:
                    is_correct = bool(progress_row['is_correct'])

                    if is_correct:
                        correct_answers += 1
                    else:
                        incorrect_answers += 1

                    # Обновляем статистику по модулям
                    for module in modules_list:
                        if module not in module_stats:
                            module_stats[module] = {'correct': 0, 'incorrect': 0, 'total': 0}

                        module_stats[module]['total'] += 1
                        if is_correct:
                            module_stats[module]['correct'] += 1
                        else:
                            module_stats[module]['incorrect'] += 1

            # Вычисляем процент правильных ответов
            total_answered = correct_answers + incorrect_answers
            accuracy_rate = (correct_answers / total_answered * 100) if total_answered > 0 else 0

            # Определяем слабые и сильные модули
            weak_modules = []
            strong_modules = []

            for module, stats in module_stats.items():
                if stats['total'] < 3:  # Слишком мало данных для анализа
                    continue

                module_accuracy = (stats['correct'] / stats['total'] * 100) if stats['total'] > 0 else 0

                if module_accuracy < 50:
                    weak_modules.append({
                        'module': module,
                        'accuracy': module_accuracy,
                        'correct': stats['correct'],
                        'total': stats['total']
                    })
                elif module_accuracy >= 80:
                    strong_modules.append({
                        'module': module,
                        'accuracy': module_accuracy,
                        'correct': stats['correct'],
                        'total': stats['total']
                    })

            # Сортируем по точности
            weak_modules.sort(key=lambda x: x['accuracy'])
            strong_modules.sort(key=lambda x: x['accuracy'], reverse=True)

            return {
                'total_assignments': total_assignments,
                'completed_assignments': completed_assignments,
                'total_questions': total_questions,
                'correct_answers': correct_answers,
                'incorrect_answers': incorrect_answers,
                'accuracy_rate': round(accuracy_rate, 1),
                'total_answered': total_answered,
                'assignments_by_module': module_stats,
                'weak_modules': weak_modules[:3],  # Топ-3 слабых
                'strong_modules': strong_modules[:3]  # Топ-3 сильных
            }

    except Exception as e:
        logger.error(f"Ошибка при получении статистики ученика: {e}")
        return None


async def count_new_homeworks(student_id: int) -> int:
    """
    Подсчитывает количество новых (непросмотренных) домашних заданий ученика.

    Args:
        student_id: ID ученика

    Returns:
        Количество заданий со статусом ASSIGNED
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute("""
                SELECT COUNT(*)
                FROM homework_student_assignments
                WHERE student_id = ? AND status = ?
            """, (student_id, StudentAssignmentStatus.ASSIGNED.value))

            count = (await cursor.fetchone())[0]
            return count

    except Exception as e:
        logger.error(f"Ошибка при подсчете новых домашних заданий: {e}")
        return 0
