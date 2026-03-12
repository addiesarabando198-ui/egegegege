"""
Routes для получения вопросов из модулей.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
import logging
import json
import os

from api.middleware.telegram_auth import get_current_teacher
from api.schemas.question import QuestionsListResponse, Question
from teacher_mode.models import TeacherProfile
from teacher_mode.services.topics_loader import load_topics_for_module

router = APIRouter()
logger = logging.getLogger(__name__)


def format_question_from_topic(topic_data: dict, module_code: str) -> Question:
    """
    Форматирует данные темы в формат Question.

    Args:
        topic_data: Данные темы из loader
        module_code: Код модуля

    Returns:
        Question object
    """
    question_id = f"{module_code}_{topic_data.get('id', 'unknown')}"

    return Question(
        id=question_id,
        module=module_code,
        number=topic_data.get('exam_number'),
        text=topic_data.get('title', topic_data.get('text', 'Без названия')),
        type='multiple_choice' if module_code == 'test_part' else 'text',
        difficulty=topic_data.get('difficulty', 'medium'),
        topic=topic_data.get('topic', topic_data.get('block')),
        options=None,
        correct_answer=None,
        image_url=None
    )


@router.get(
    "/questions",
    response_model=QuestionsListResponse,
    summary="Получить список вопросов",
    description="Возвращает список вопросов из указанного модуля с поддержкой поиска и пагинации"
)
async def get_questions(
    module: str = Query(..., description="Код модуля (test_part, task19, task20, task24, task25)"),
    teacher: TeacherProfile = Depends(get_current_teacher),
    search: Optional[str] = Query(None, description="Поиск по тексту вопроса"),
    limit: int = Query(20, ge=1, le=100, description="Количество вопросов"),
    offset: int = Query(0, ge=0, description="Смещение для пагинации")
) -> QuestionsListResponse:
    """
    Получает список вопросов из указанного модуля.

    Поддерживает:
    - Поиск по тексту
    - Пагинацию
    - Фильтрацию по модулям
    """
    try:
        # Проверяем валидность модуля
        valid_modules = ['test_part', 'task19', 'task20', 'task24', 'task25']
        if module not in valid_modules:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid module. Must be one of: {', '.join(valid_modules)}"
            )

        # Загружаем темы для модуля
        topics_data = load_topics_for_module(module)

        if not topics_data or not topics_data.get('topics_by_id'):
            logger.warning(f"No topics found for module {module}")
            return QuestionsListResponse(total=0, questions=[])

        # Получаем все темы
        all_topics = list(topics_data['topics_by_id'].values())

        # Фильтруем по поиску если указан
        if search:
            search_lower = search.lower()
            filtered_topics = []
            for topic in all_topics:
                # Ищем в title, text, или block
                title = str(topic.get('title', '')).lower()
                text = str(topic.get('text', '')).lower()
                block = str(topic.get('block', '')).lower()

                if search_lower in title or search_lower in text or search_lower in block:
                    filtered_topics.append(topic)

            all_topics = filtered_topics

        # Общее количество после фильтрации
        total = len(all_topics)

        # Применяем пагинацию
        paginated_topics = all_topics[offset:offset + limit]

        # Форматируем в Question objects
        questions = [
            format_question_from_topic(topic, module)
            for topic in paginated_topics
        ]

        logger.info(f"Получено {len(questions)} вопросов из модуля {module} для учителя {teacher.user_id}")

        return QuestionsListResponse(
            total=total,
            questions=questions
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при получении вопросов: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve questions"
        )


@router.get(
    "/questions/{question_id}",
    response_model=Question,
    summary="Получить конкретный вопрос",
    description="Возвращает детальную информацию о конкретном вопросе"
)
async def get_question_by_id(
    question_id: str,
    teacher: TeacherProfile = Depends(get_current_teacher)
) -> Question:
    """
    Получает детальную информацию о конкретном вопросе.

    Format question_id: {module}_{topic_id}
    Example: test_part_123, task19_45
    """
    try:
        # Парсим question_id
        parts = question_id.split('_', 1)
        if len(parts) != 2:
            raise HTTPException(
                status_code=400,
                detail="Invalid question_id format. Expected: {module}_{id}"
            )

        module_code = parts[0]
        topic_id_str = parts[1]

        # Пытаемся преобразовать в int если возможно
        try:
            topic_id = int(topic_id_str)
        except ValueError:
            topic_id = topic_id_str

        # Загружаем темы для модуля
        topics_data = load_topics_for_module(module_code)

        if not topics_data or not topics_data.get('topics_by_id'):
            raise HTTPException(
                status_code=404,
                detail="Module not found"
            )

        # Ищем тему по ID
        topic = topics_data['topics_by_id'].get(topic_id)

        if not topic:
            raise HTTPException(
                status_code=404,
                detail="Question not found"
            )

        # Форматируем в Question
        question = format_question_from_topic(topic, module_code)

        logger.info(f"Получен вопрос {question_id} для учителя {teacher.user_id}")

        return question

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при получении вопроса: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve question"
        )
