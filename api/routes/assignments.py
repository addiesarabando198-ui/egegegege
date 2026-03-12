"""
Routes для создания и управления заданиями.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
import aiosqlite
import logging
import random

from api.middleware.telegram_auth import get_current_teacher
from api.schemas.assignment import (
    CreateAssignmentRequest,
    CreateAssignmentResponse,
    AssignmentsListResponse,
    Assignment
)
from teacher_mode.models import TeacherProfile, AssignmentType, TargetType
from teacher_mode.services.assignment_service import create_homework_assignment
from teacher_mode.services.topics_loader import load_topics_for_module
from teacher_mode.utils.datetime_utils import parse_datetime_safe, utc_now
from core.config import DATABASE_FILE

router = APIRouter()
logger = logging.getLogger(__name__)


def select_questions_for_module(module_data: dict, selection_mode: str,
                                question_count: Optional[int] = None,
                                question_ids: Optional[List[str]] = None) -> List:
    """
    Выбирает вопросы для модуля согласно режиму выбора.

    Args:
        module_data: Данные модуля из load_topics_for_module
        selection_mode: Режим выбора (all, random, specific)
        question_count: Количество вопросов для random
        question_ids: ID вопросов для specific

    Returns:
        Список ID выбранных вопросов
    """
    topics_by_id = module_data.get('topics_by_id', {})

    if selection_mode == 'all':
        return list(topics_by_id.keys())

    elif selection_mode == 'random':
        all_ids = list(topics_by_id.keys())
        count = min(question_count or len(all_ids), len(all_ids))
        return random.sample(all_ids, count)

    elif selection_mode == 'specific':
        # Валидируем что все ID существуют
        valid_ids = []
        logger.debug(f"Processing specific selection for {len(question_ids or [])} question IDs")

        for qid in (question_ids or []):
            original_qid = qid
            # Убираем префикс модуля если есть (test_part_123 -> 123)
            if '_' in str(qid):
                qid = qid.split('_')[-1]
                logger.debug(f"Removed prefix from {original_qid} -> {qid}")

            # Конвертируем в int если возможно
            try:
                qid = int(qid)
                logger.debug(f"Converted {original_qid} to int: {qid}")
            except (ValueError, TypeError):
                logger.debug(f"Could not convert {qid} to int, keeping as string")
                pass

            if qid in topics_by_id:
                valid_ids.append(qid)
                logger.debug(f"Question ID {qid} found in topics_by_id")
            else:
                logger.warning(f"Question ID {qid} (original: {original_qid}) not found in topics_by_id. Available keys: {list(topics_by_id.keys())[:10]}")

        logger.info(f"Selected {len(valid_ids)} valid questions out of {len(question_ids or [])} requested")
        return valid_ids

    return []


@router.post(
    "/assignments",
    response_model=CreateAssignmentResponse,
    summary="Создать новое задание",
    description="Создает новое домашнее задание и назначает его выбранным ученикам"
)
async def create_assignment(
    request: CreateAssignmentRequest,
    teacher: TeacherProfile = Depends(get_current_teacher)
) -> CreateAssignmentResponse:
    """
    Создает новое домашнее задание.

    Процесс:
    1. Валидация учеников
    2. Выбор вопросов из модулей
    3. Создание задания в БД
    4. Отправка уведомлений ученикам
    """
    try:
        # Валидируем что все ученики принадлежат учителю
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            placeholders = ','.join('?' * len(request.student_ids))
            query = f"""
                SELECT student_id
                FROM teacher_student_relationships
                WHERE teacher_id = ? AND status = 'active'
                AND student_id IN ({placeholders})
            """
            params = [teacher.user_id] + request.student_ids

            cursor = await db.execute(query, params)
            valid_students = [row['student_id'] for row in await cursor.fetchall()]

            if len(valid_students) != len(request.student_ids):
                invalid_count = len(request.student_ids) - len(valid_students)
                raise HTTPException(
                    status_code=400,
                    detail=f"{invalid_count} students are not connected to this teacher"
                )

        # Собираем вопросы из модулей
        all_selected_questions = []
        modules_data = {}

        logger.info(f"Processing {len(request.modules)} module(s) for assignment creation")

        for module_selection in request.modules:
            module_code = module_selection.module_code
            logger.info(f"Processing module: {module_code}, selection_mode: {module_selection.selection_mode}, question_ids: {module_selection.question_ids}")

            # Загружаем данные модуля
            module_data = load_topics_for_module(module_code)

            if not module_data or not module_data.get('topics_by_id'):
                logger.error(f"Module {module_code} not found or has no topics")
                raise HTTPException(
                    status_code=400,
                    detail=f"Module {module_code} not found or empty"
                )

            logger.info(f"Module {module_code} loaded: {len(module_data.get('topics_by_id', {}))} topics available")

            # Выбираем вопросы
            selected_ids = select_questions_for_module(
                module_data,
                module_selection.selection_mode,
                module_selection.question_count,
                module_selection.question_ids
            )

            logger.info(f"Module {module_code}: selected {len(selected_ids)} question(s) using {module_selection.selection_mode} mode")

            if not selected_ids:
                logger.error(f"No questions selected for module {module_code}. Mode: {module_selection.selection_mode}, IDs: {module_selection.question_ids}")
                raise HTTPException(
                    status_code=400,
                    detail=f"No questions selected for module {module_code}"
                )

            # Сохраняем выбранные вопросы
            for qid in selected_ids:
                all_selected_questions.append({
                    'module': module_code,
                    'question_id': qid
                })

            modules_data[module_code] = {
                'selection_mode': module_selection.selection_mode,
                'selected_ids': selected_ids
            }

        if not all_selected_questions:
            raise HTTPException(
                status_code=400,
                detail="No questions selected for assignment"
            )

        # Определяем тип задания
        assignment_type = AssignmentType.EXISTING_TOPICS

        # Формируем данные задания
        assignment_data = {
            'modules': modules_data,
            'questions': all_selected_questions,
            'total_questions': len(all_selected_questions)
        }

        # Создаем задание через существующий сервис
        homework = await create_homework_assignment(
            teacher_id=teacher.user_id,
            title=request.title,
            assignment_type=assignment_type,
            assignment_data=assignment_data,
            target_type=TargetType.SPECIFIC_STUDENTS,
            student_ids=valid_students,
            description=request.description,
            deadline=request.deadline
        )

        if not homework:
            raise HTTPException(
                status_code=500,
                detail="Failed to create assignment"
            )

        # Уведомления будут отправлены через основного бота
        # (API не имеет прямого доступа к Bot instance)
        notified_count = 0
        logger.info(f"Задание создано. Уведомления будут отправлены ботом.")

        logger.info(f"Создано задание {homework.id} учителем {teacher.user_id} для {len(valid_students)} учеников")

        return CreateAssignmentResponse(
            success=True,
            assignment_id=homework.id,
            created_at=homework.created_at,
            message=f"Задание успешно создано и отправлено {len(valid_students)} ученикам",
            students_notified=notified_count
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при создании задания: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create assignment: {str(e)}"
        )


@router.get(
    "/assignments",
    response_model=AssignmentsListResponse,
    summary="Получить список заданий",
    description="Возвращает список заданий учителя"
)
async def get_assignments(
    teacher: TeacherProfile = Depends(get_current_teacher),
    status: Optional[str] = Query(None, description="Фильтр по статусу (active, archived)"),
    limit: int = Query(50, ge=1, le=100, description="Количество записей"),
    offset: int = Query(0, ge=0, description="Смещение для пагинации")
) -> AssignmentsListResponse:
    """
    Получает список заданий учителя.

    Поддерживает:
    - Фильтрацию по статусу
    - Пагинацию
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            # Базовый запрос для подсчета
            count_query = """
                SELECT COUNT(*) as count
                FROM homework_assignments
                WHERE teacher_id = ?
            """
            count_params = [teacher.user_id]

            # Базовый запрос для данных
            data_query = """
                SELECT
                    ha.id,
                    ha.teacher_id,
                    ha.created_at,
                    ha.title,
                    ha.description,
                    ha.deadline,
                    ha.assignment_type,
                    ha.status,
                    COUNT(DISTINCT hsa.student_id) as total_students,
                    COUNT(DISTINCT CASE WHEN hsa.status = 'completed' THEN hsa.student_id END) as completed_count
                FROM homework_assignments ha
                LEFT JOIN homework_student_assignments hsa ON ha.id = hsa.homework_id
                WHERE ha.teacher_id = ?
            """
            data_params = [teacher.user_id]

            # Добавляем фильтр по статусу если указан
            if status:
                count_query += " AND status = ?"
                data_query += " AND ha.status = ?"
                count_params.append(status)
                data_params.append(status)

            # Получаем общее количество
            cursor = await db.execute(count_query, count_params)
            row = await cursor.fetchone()
            total = row['count'] if row else 0

            # Добавляем группировку, сортировку и пагинацию
            data_query += """
                GROUP BY ha.id
                ORDER BY ha.created_at DESC
                LIMIT ? OFFSET ?
            """
            data_params.extend([limit, offset])

            # Получаем данные заданий
            cursor = await db.execute(data_query, data_params)
            rows = await cursor.fetchall()

            # Формируем список заданий
            assignments = []
            for row in rows:
                assignment = Assignment(
                    id=row['id'],
                    teacher_id=row['teacher_id'],
                    title=row['title'],
                    description=row['description'],
                    deadline=parse_datetime_safe(row['deadline']),
                    assignment_type=row['assignment_type'],
                    created_at=parse_datetime_safe(row['created_at']) or utc_now(),
                    status=row['status'],
                    total_students=row['total_students'] or 0,
                    completed_count=row['completed_count'] or 0
                )
                assignments.append(assignment)

            logger.info(f"Получен список заданий для учителя {teacher.user_id}: {len(assignments)} из {total}")

            return AssignmentsListResponse(
                total=total,
                assignments=assignments
            )

    except Exception as e:
        logger.error(f"Ошибка при получении списка заданий: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve assignments"
        )
