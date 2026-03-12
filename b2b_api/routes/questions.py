"""
Routes для банка заданий B2B API.

GET /api/v1/questions - список заданий с фильтрацией
GET /api/v1/questions/{id} - конкретное задание
GET /api/v1/questions/stats - статистика по заданиям
"""

import logging
import json
import os
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query

from b2b_api.schemas.questions import (
    B2BQuestion,
    B2BQuestionsListResponse,
    TaskType,
    QuestionStatsResponse
)
from b2b_api.middleware.api_key_auth import verify_api_key, require_scope

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/questions", tags=["questions"])

# Путь к данным
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data')

# Кэш вопросов
_questions_cache = None


def load_questions() -> List[dict]:
    """Загружает все вопросы из JSON файлов."""
    global _questions_cache

    if _questions_cache is not None:
        return _questions_cache

    questions = []

    # Загружаем основной файл вопросов
    questions_file = os.path.join(DATA_DIR, 'questions.json')
    if os.path.exists(questions_file):
        try:
            with open(questions_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for q in data:
                    # Определяем task_number по exam_number
                    exam_num = q.get('exam_number', 1)
                    if exam_num in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]:
                        # Тестовая часть - пропускаем для B2B API
                        continue

                    # Формируем вопрос
                    questions.append({
                        'id': q.get('id', f"q_{len(questions)}"),
                        'task_number': exam_num,
                        'task_type': f"task{exam_num}" if 19 <= exam_num <= 25 else 'test_part',
                        'text': q.get('question', q.get('text', '')),
                        'topic': q.get('topic', ''),
                        'block': q.get('block', ''),
                        'difficulty': q.get('difficulty', 'П'),
                        'max_score': get_max_score(exam_num),
                        'answer': q.get('answer'),
                        'explanation': q.get('explanation')
                    })
        except Exception as e:
            logger.error(f"Error loading questions.json: {e}")

    # Загружаем текстовые отрывки для task17/task18
    passages_file = os.path.join(DATA_DIR, 'text_passages_17_18.json')
    if os.path.exists(passages_file):
        try:
            with open(passages_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for passage in data.get('passages', []):
                    passage_id = passage.get('id', len(questions))
                    block = passage.get('block', 'Разное')
                    source = passage.get('source', '')
                    text_content = passage.get('text', '')

                    # Task 17
                    if 'task17' in passage:
                        t17 = passage['task17']
                        questions.append({
                            'id': f"task17_{passage_id}",
                            'task_number': 17,
                            'task_type': 'task17',
                            'text': f"{t17.get('question', '')}\n\nТекст: {text_content[:200]}...",
                            'topic': source,
                            'block': block,
                            'difficulty': 'П',
                            'max_score': 2,
                        })

                    # Task 18
                    if 'task18' in passage:
                        t18 = passage['task18']
                        questions.append({
                            'id': f"task18_{passage_id}",
                            'task_number': 18,
                            'task_type': 'task18',
                            'text': f"{t18.get('question', '')}\n\nТекст: {text_content[:200]}...",
                            'topic': t18.get('concept', source),
                            'block': block,
                            'difficulty': 'П',
                            'max_score': 2,
                        })
        except Exception as e:
            logger.error(f"Error loading text_passages_17_18.json: {e}")

    # Загружаем вопросы для task23
    task23_file = os.path.join(DATA_DIR, 'task23_questions.json')
    if os.path.exists(task23_file):
        try:
            with open(task23_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for q in data:
                    questions.append({
                        'id': q.get('id', f"task23_{len(questions)}"),
                        'task_number': 23,
                        'task_type': 'task23',
                        'text': q.get('question', q.get('text', '')),
                        'topic': q.get('topic', ''),
                        'block': q.get('block', 'Разное'),
                        'difficulty': q.get('difficulty', 'В'),
                        'max_score': 3
                    })
        except Exception as e:
            logger.error(f"Error loading task23_questions.json: {e}")

    # Загружаем планы для task24/25
    plans_file = os.path.join(DATA_DIR, 'plans_data_with_blocks.json')
    if os.path.exists(plans_file):
        try:
            with open(plans_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for i, q in enumerate(data):
                    # Task 24 - составление плана
                    questions.append({
                        'id': f"task24_{i}",
                        'task_number': 24,
                        'task_type': 'task24',
                        'text': f"Используя обществоведческие знания, составьте сложный план, позволяющий раскрыть по существу тему «{q.get('title', '')}».",
                        'topic': q.get('title', ''),
                        'block': q.get('block', 'Разное'),
                        'difficulty': 'В',
                        'max_score': 4,
                        'sample_answer': q.get('plan')
                    })
        except Exception as e:
            logger.error(f"Error loading plans_data_with_blocks.json: {e}")

    _questions_cache = questions
    logger.info(f"Loaded {len(questions)} questions for B2B API")
    return questions


def get_max_score(task_number: int) -> int:
    """Возвращает максимальный балл для задания."""
    scores = {
        17: 2,
        18: 2,
        19: 3,
        20: 2,
        21: 3,
        22: 4,
        23: 3,
        24: 4,
        25: 6
    }
    return scores.get(task_number, 1)


def get_criteria(task_number: int) -> List[dict]:
    """Возвращает критерии оценивания для задания."""
    criteria_map = {
        17: [
            {"id": "К1", "name": "Поиск информации в тексте", "max_score": 2, "description": "2 балла за 3 правильных ответа, 1 балл за 2 правильных ответа"}
        ],
        18: [
            {"id": "К1", "name": "Объяснение понятия", "max_score": 2, "description": "2 балла за оба элемента (признаки понятия + связь с явлением), 1 балл за один элемент"}
        ],
        19: [
            {"id": "К1", "name": "Корректность примеров", "max_score": 3, "description": "По 1 баллу за каждый корректный конкретный пример"}
        ],
        20: [
            {"id": "К1", "name": "Понимание текста", "max_score": 2, "description": "Понимание и интерпретация текста"}
        ],
        21: [
            {"id": "К1", "name": "Раскрытие темы", "max_score": 2, "description": "Раскрытие темы с опорой на знания"},
            {"id": "К2", "name": "Теоретические положения", "max_score": 1, "description": "Корректность теоретических положений"}
        ],
        22: [
            {"id": "К1", "name": "Раскрытие темы", "max_score": 2, "description": "Раскрытие темы"},
            {"id": "К2", "name": "Примеры", "max_score": 2, "description": "Корректность примеров"}
        ],
        23: [
            {"id": "К1", "name": "Раскрытие задачи", "max_score": 3, "description": "Корректность ответа на вопросы задачи"}
        ],
        24: [
            {"id": "К1", "name": "Раскрытие темы", "max_score": 2, "description": "Раскрытие темы по существу"},
            {"id": "К2", "name": "Структура плана", "max_score": 1, "description": "Корректность структуры"},
            {"id": "К3", "name": "Корректность формулировок", "max_score": 1, "description": "Корректность формулировок пунктов"}
        ],
        25: [
            {"id": "К1", "name": "Раскрытие смысла", "max_score": 2, "description": "Раскрытие смысла высказывания"},
            {"id": "К2", "name": "Теоретическое содержание", "max_score": 2, "description": "Теоретическое содержание мини-сочинения"},
            {"id": "К3", "name": "Связность аргументации", "max_score": 2, "description": "Связность и логичность рассуждений"}
        ]
    }
    return criteria_map.get(task_number, [])


@router.get(
    "",
    response_model=B2BQuestionsListResponse,
    summary="Список заданий",
    description="""
Возвращает список заданий из банка с поддержкой фильтрации и пагинации.

**Фильтры:**
- `task_number` - номер задания (17-25)
- `block` - тематический блок (Экономика, Политика и т.д.)
- `topic` - поиск по теме
- `difficulty` - уровень сложности (Б, П, В)
- `search` - поиск по тексту задания

**Примеры ответов:**
Для premium клиентов доступны примеры правильных ответов (`include_sample_answers=true`).
    """
)
async def list_questions(
    client_data: dict = Depends(verify_api_key),
    page: int = Query(1, ge=1, description="Номер страницы"),
    per_page: int = Query(20, ge=1, le=100, description="Заданий на странице"),
    task_number: Optional[int] = Query(None, ge=17, le=25, description="Номер задания"),
    block: Optional[str] = Query(None, description="Тематический блок"),
    topic: Optional[str] = Query(None, description="Поиск по теме"),
    difficulty: Optional[str] = Query(None, description="Уровень сложности"),
    search: Optional[str] = Query(None, description="Поиск по тексту"),
    include_sample_answers: bool = Query(False, description="Включить примеры ответов")
) -> B2BQuestionsListResponse:
    """
    Получает список заданий с фильтрацией.
    """
    # Проверяем scope для примеров ответов
    if include_sample_answers:
        if 'questions:samples' not in client_data.get('scopes', []) and 'admin' not in client_data.get('scopes', []):
            include_sample_answers = False  # Молча отключаем если нет прав

    questions = load_questions()

    # Применяем фильтры
    filtered = questions

    if task_number:
        filtered = [q for q in filtered if q['task_number'] == task_number]

    if block:
        filtered = [q for q in filtered if q.get('block', '').lower() == block.lower()]

    if topic:
        topic_lower = topic.lower()
        filtered = [q for q in filtered if topic_lower in q.get('topic', '').lower()]

    if difficulty:
        filtered = [q for q in filtered if q.get('difficulty', '') == difficulty]

    if search:
        search_lower = search.lower()
        filtered = [
            q for q in filtered
            if search_lower in q.get('text', '').lower() or
               search_lower in q.get('topic', '').lower()
        ]

    # Пагинация
    total = len(filtered)
    offset = (page - 1) * per_page
    paginated = filtered[offset:offset + per_page]

    # Формируем ответ
    result_questions = []
    for q in paginated:
        question = B2BQuestion(
            id=q['id'],
            task_number=q['task_number'],
            task_type=TaskType(q['task_type']) if q['task_type'] in [t.value for t in TaskType] else TaskType.TASK_19,
            text=q['text'],
            topic=q.get('topic'),
            block=q.get('block'),
            difficulty=q.get('difficulty'),
            max_score=q['max_score'],
            criteria=get_criteria(q['task_number']),
            sample_answer=q.get('sample_answer') if include_sample_answers else None
        )
        result_questions.append(question)

    # Собираем доступные фильтры
    all_blocks = list(set(q.get('block', '') for q in questions if q.get('block')))
    all_topics = list(set(q.get('topic', '') for q in questions if q.get('topic')))[:50]  # Лимит

    return B2BQuestionsListResponse(
        total=total,
        page=page,
        per_page=per_page,
        questions=result_questions,
        available_blocks=sorted(all_blocks),
        available_topics=sorted(all_topics)
    )


@router.get(
    "/stats",
    response_model=QuestionStatsResponse,
    summary="Статистика по заданиям",
    description="Возвращает статистику по банку заданий."
)
async def get_questions_stats(
    client_data: dict = Depends(verify_api_key)
) -> QuestionStatsResponse:
    """
    Получает статистику по банку заданий.
    """
    questions = load_questions()

    # Статистика по номерам заданий
    by_task = {}
    for q in questions:
        tn = q['task_number']
        by_task[str(tn)] = by_task.get(str(tn), 0) + 1

    # Статистика по блокам
    by_block = {}
    for q in questions:
        block = q.get('block', 'Другое')
        by_block[block] = by_block.get(block, 0) + 1

    # Статистика по сложности
    by_difficulty = {}
    for q in questions:
        diff = q.get('difficulty', 'Не указано')
        by_difficulty[diff] = by_difficulty.get(diff, 0) + 1

    return QuestionStatsResponse(
        total_questions=len(questions),
        by_task_number=by_task,
        by_block=by_block,
        by_difficulty=by_difficulty
    )


@router.get(
    "/{question_id}",
    response_model=B2BQuestion,
    summary="Получить задание",
    description="Возвращает конкретное задание по ID."
)
async def get_question(
    question_id: str,
    client_data: dict = Depends(verify_api_key),
    include_sample_answer: bool = Query(False, description="Включить пример ответа")
) -> B2BQuestion:
    """
    Получает задание по ID.
    """
    # Проверяем scope для примеров ответов
    if include_sample_answer:
        if 'questions:samples' not in client_data.get('scopes', []) and 'admin' not in client_data.get('scopes', []):
            include_sample_answer = False

    questions = load_questions()

    # Ищем вопрос
    question = None
    for q in questions:
        if q['id'] == question_id:
            question = q
            break

    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    return B2BQuestion(
        id=question['id'],
        task_number=question['task_number'],
        task_type=TaskType(question['task_type']) if question['task_type'] in [t.value for t in TaskType] else TaskType.TASK_19,
        text=question['text'],
        topic=question.get('topic'),
        block=question.get('block'),
        difficulty=question.get('difficulty'),
        max_score=question['max_score'],
        criteria=get_criteria(question['task_number']),
        sample_answer=question.get('sample_answer') if include_sample_answer else None
    )
