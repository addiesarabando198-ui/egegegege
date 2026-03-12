"""
Интеграция выполнения домашних заданий с существующими evaluators.

Этот модуль связывает систему домашних заданий учителей
с существующими плагинами (task19, task20, task21, task22, task23, task24, task25).
"""

from __future__ import annotations  # Python 3.8 compatibility

import logging
from typing import Optional, Dict, Any
from datetime import datetime

from . import assignment_service, progress_tracker
from ..models import AssignmentType, StudentAssignmentStatus

logger = logging.getLogger(__name__)


async def start_homework_session(
    homework_id: int,
    student_id: int,
    context
) -> Optional[Dict[str, Any]]:
    """
    Начинает сессию выполнения домашнего задания.

    Args:
        homework_id: ID домашнего задания
        student_id: ID ученика
        context: Telegram context для сохранения состояния

    Returns:
        Dict с данными задания или None при ошибке
    """
    # Получаем задание
    homework = await assignment_service.get_homework_by_id(homework_id)
    if not homework:
        logger.error(f"Homework {homework_id} not found")
        return None

    # Проверяем, что задание назначено этому ученику
    student_homeworks = await assignment_service.get_student_homeworks(student_id)
    if not any(hw.homework_id == homework_id for hw in student_homeworks):
        logger.warning(f"Homework {homework_id} not assigned to student {student_id}")
        return None

    # Обновляем статус на "in_progress" если был "assigned"
    await assignment_service.update_student_assignment_status(
        homework_id,
        student_id,
        StudentAssignmentStatus.IN_PROGRESS
    )

    # Извлекаем данные задания
    assignment_data = homework.assignment_data
    task_module = assignment_data.get('task_module')  # 'task19', 'task20', etc.
    questions_count = assignment_data.get('questions_count', 10)

    # Сохраняем в контекст для использования в обработчиках
    context.user_data['current_homework'] = {
        'homework_id': homework_id,
        'task_module': task_module,
        'questions_count': questions_count,
        'current_question': 0,
        'title': homework.title
    }

    logger.info(f"Started homework session {homework_id} for student {student_id}")

    return context.user_data['current_homework']


async def save_homework_answer(
    homework_id: int,
    student_id: int,
    question_id: str,
    answer: str,
    is_correct: bool,
    ai_feedback: Optional[str] = None,
    total_questions: int = None,
    bot=None
) -> bool:
    """
    Сохраняет ответ ученика на вопрос домашнего задания.
    Автоматически проверяет и завершает задание, если все вопросы выполнены.

    Args:
        homework_id: ID задания
        student_id: ID ученика
        question_id: ID вопроса (например, "task19_q1")
        answer: Ответ ученика
        is_correct: Правильный ли ответ
        ai_feedback: Фидбэк от AI
        total_questions: Общее количество вопросов (для проверки завершения)
        bot: Telegram Bot instance для отправки уведомлений

    Returns:
        True при успехе
    """
    progress = await progress_tracker.save_homework_progress(
        homework_id=homework_id,
        student_id=student_id,
        question_id=question_id,
        user_answer=answer,
        is_correct=is_correct,
        ai_feedback=ai_feedback
    )

    if not progress:
        return False

    logger.info(f"Saved answer for homework {homework_id}, student {student_id}, question {question_id}")

    # Проверяем и автоматически завершаем задание, если все вопросы выполнены
    if total_questions is not None:
        await check_and_complete_homework(
            homework_id=homework_id,
            student_id=student_id,
            total_questions=total_questions,
            bot=bot
        )

    return True


async def check_and_complete_homework(
    homework_id: int,
    student_id: int,
    total_questions: int,
    bot=None
) -> bool:
    """
    Проверяет и автоматически завершает задание если все вопросы выполнены.
    Отправляет уведомление учителю при завершении.

    Args:
        homework_id: ID задания
        student_id: ID ученика
        total_questions: Общее количество вопросов
        bot: Telegram Bot instance для отправки уведомлений (опционально)

    Returns:
        True если задание было завершено
    """
    return await progress_tracker.auto_complete_homework(
        homework_id,
        student_id,
        total_questions,
        bot
    )


async def get_homework_progress_summary(
    homework_id: int,
    student_id: int
) -> Dict[str, Any]:
    """
    Получает сводку по прогрессу выполнения задания.

    Args:
        homework_id: ID задания
        student_id: ID ученика

    Returns:
        Dict с прогрессом и статистикой
    """
    homework = await assignment_service.get_homework_by_id(homework_id)
    if not homework:
        return {}

    questions_count = homework.assignment_data.get('questions_count', 10)

    completion = await progress_tracker.calculate_homework_completion(
        homework_id,
        student_id,
        questions_count
    )

    performance = await progress_tracker.get_student_performance_summary(
        student_id,
        homework_id
    )

    return {
        'homework_id': homework_id,
        'title': homework.title,
        'deadline': homework.deadline,
        'completion': completion,
        'performance': performance,
        'is_completed': completion['percentage'] >= 100
    }


def get_task_module_callback(task_module: str, is_homework: bool = False) -> str:
    """
    Генерирует callback_data для перехода в модуль задания.

    Args:
        task_module: Код модуля ('task19', 'task20', etc.)
        is_homework: Режим домашнего задания

    Returns:
        Строка callback_data
    """
    if is_homework:
        return f"homework_{task_module}"
    else:
        return f"choose_{task_module}"


# Интеграция с конкретными evaluators


async def evaluate_task19_answer(
    answer: str,
    topic: str,
    **kwargs
) -> tuple[bool, Optional[str]]:
    """
    Проверяет ответ через evaluator task19.

    Args:
        answer: Ответ ученика
        topic: Тема вопроса
        **kwargs: Дополнительные параметры

    Returns:
        Tuple (is_correct, feedback)
    """
    try:
        from task19.evaluator import Task19AIEvaluator

        evaluator = Task19AIEvaluator()
        result = await evaluator.evaluate(answer, topic, **kwargs)

        # Считаем корректным если набрано >= 50% баллов
        is_correct = result.total_score >= (result.max_score / 2)
        return is_correct, result.feedback

    except Exception as e:
        logger.error(f"Error evaluating task19 answer: {e}")
        return False, "Ошибка при проверке ответа"


async def evaluate_task20_answer(
    answer: str,
    topic: str,
    **kwargs
) -> tuple[bool, Optional[str]]:
    """
    Проверяет ответ через evaluator task20.

    Args:
        answer: Ответ ученика
        topic: Тема вопроса
        **kwargs: Дополнительные параметры

    Returns:
        Tuple (is_correct, feedback)
    """
    try:
        from task20.evaluator import Task20AIEvaluator

        evaluator = Task20AIEvaluator()
        result = await evaluator.evaluate(answer, topic, **kwargs)

        # Считаем корректным если набрано >= 50% баллов
        is_correct = result.total_score >= (result.max_score / 2)
        return is_correct, result.feedback

    except Exception as e:
        logger.error(f"Error evaluating task20 answer: {e}")
        return False, "Ошибка при проверке ответа"


async def evaluate_task21_answer(
    answer: str,
    question_data: dict,
) -> tuple[bool, Optional[str]]:
    """
    Проверяет ответ через evaluator task21 (Графики спроса и предложения).

    Args:
        answer: Ответ ученика
        question_data: Данные вопроса из JSON

    Returns:
        Tuple (is_correct, feedback)
    """
    try:
        from task21.evaluator import Task21Evaluator

        evaluator = Task21Evaluator()
        result = await evaluator.evaluate(user_answer=answer, question_data=question_data)

        is_correct = result.total_score >= (result.max_score / 2)
        return is_correct, result.feedback

    except Exception as e:
        logger.error(f"Error evaluating task21 answer: {e}")
        return False, "Ошибка при проверке ответа"


async def evaluate_task22_answer(
    answer: str,
    question_data: dict,
) -> tuple[bool, Optional[str]]:
    """
    Проверяет ответ через evaluator task22 (Анализ ситуаций).

    Args:
        answer: Ответ ученика
        question_data: Данные вопроса (description, questions, correct_answers, etc.)

    Returns:
        Tuple (is_correct, feedback)
    """
    try:
        from task22.evaluator import Task22AIEvaluator

        evaluator = Task22AIEvaluator()
        result = await evaluator.evaluate(answer=answer, task_data=question_data)

        is_correct = result.total_score >= (result.max_score / 2)
        return is_correct, result.feedback

    except Exception as e:
        logger.error(f"Error evaluating task22 answer: {e}")
        return False, "Ошибка при проверке ответа"


async def evaluate_task23_answer(
    answer: str,
    question_data: dict,
) -> tuple[bool, Optional[str]]:
    """
    Проверяет ответ через evaluator task23 (Конституция РФ).

    Args:
        answer: Ответ ученика
        question_data: Данные вопроса (model_type, characteristics, model_answers, etc.)

    Returns:
        Tuple (is_correct, feedback)
    """
    try:
        from task23.evaluator import Task23Evaluator

        evaluator = Task23Evaluator()
        result = await evaluator.evaluate(user_answer=answer, question_data=question_data)

        is_correct = result.total_score >= (result.max_score / 2)
        return is_correct, result.feedback

    except Exception as e:
        logger.error(f"Error evaluating task23 answer: {e}")
        return False, "Ошибка при проверке ответа"


async def evaluate_task24_answer(
    answer: str,
    topic: str,
    **kwargs
) -> tuple[bool, Optional[str]]:
    """
    Проверяет ответ (план) через evaluator task24.

    Args:
        answer: План ученика
        topic: Название темы плана
        **kwargs: Дополнительные параметры (должны содержать ideal_plan_data, bot_data)

    Returns:
        Tuple (is_correct, feedback)
    """
    try:
        from task24.checker import evaluate_plan_with_ai, PlanBotData

        # Для task24 нужны дополнительные параметры
        ideal_plan_data = kwargs.get('ideal_plan_data')
        bot_data = kwargs.get('bot_data')
        user_id = kwargs.get('user_id')

        if not ideal_plan_data or not bot_data:
            logger.error("Task24 requires ideal_plan_data and bot_data parameters")
            return False, "Недостаточно данных для проверки плана"

        # Вызываем проверку плана с AI
        feedback = await evaluate_plan_with_ai(
            user_plan_text=answer,
            ideal_plan_data=ideal_plan_data,
            bot_data=bot_data,
            topic_name=topic,
            use_ai=True,
            user_id=user_id
        )

        # Парсим баллы из feedback (формат: "К1: X/3, К2: Y/1")
        import re
        k1_match = re.search(r'К1.*?(\d+)/3', feedback)
        k2_match = re.search(r'К2.*?(\d+)/1', feedback)

        k1_score = int(k1_match.group(1)) if k1_match else 0
        k2_score = int(k2_match.group(1)) if k2_match else 0
        total_score = k1_score + k2_score

        # Считаем корректным если набрано >= 50% баллов (минимум 2 из 4)
        is_correct = total_score >= 2
        return is_correct, feedback

    except Exception as e:
        logger.error(f"Error evaluating task24 answer: {e}")
        return False, "Ошибка при проверке плана"


async def evaluate_task25_answer(
    answer: str,
    topic: dict,
    **kwargs
) -> tuple[bool, Optional[str]]:
    """
    Проверяет ответ через evaluator task25.

    Args:
        answer: Ответ ученика (развернутый ответ с обоснованием, ответом на вопрос и примерами)
        topic: Данные о задании (dict с полями task_text, parts и т.д.)
        **kwargs: Дополнительные параметры (user_id)

    Returns:
        Tuple (is_correct, feedback)
    """
    try:
        from task25.evaluator import Task25AIEvaluator, StrictnessLevel

        evaluator = Task25AIEvaluator(strictness=StrictnessLevel.STRICT)

        user_id = kwargs.get('user_id')
        result = await evaluator.evaluate(answer, topic, user_id=user_id)

        # Считаем корректным если набрано >= 50% баллов (минимум 3 из 6)
        is_correct = result.total_score >= (result.max_score / 2)

        # Для task25 можно использовать format_feedback() если доступно
        if hasattr(result, 'format_feedback'):
            feedback = result.format_feedback()
        else:
            feedback = result.feedback

        return is_correct, feedback

    except Exception as e:
        logger.error(f"Error evaluating task25 answer: {e}")
        return False, "Ошибка при проверке ответа"


async def evaluate_homework_answer(
    task_module: str,
    answer: str,
    question_data: Dict[str, Any]
) -> tuple[bool, Optional[str]]:
    """
    Универсальная функция для проверки ответа на вопрос домашнего задания.

    Args:
        task_module: Модуль задания ('task19', 'task20', 'task21', 'task22', 'task23',
                     'task24', 'task25')
        answer: Ответ ученика
        question_data: Данные вопроса (topic, question_text, и т.д.)

    Returns:
        Tuple (is_correct, feedback)
    """
    if task_module == 'task19':
        return await evaluate_task19_answer(
            answer,
            question_data.get('topic', ''),
            **question_data
        )

    elif task_module == 'task20':
        return await evaluate_task20_answer(
            answer,
            question_data.get('topic', ''),
            **question_data
        )

    elif task_module == 'task21':
        return await evaluate_task21_answer(
            answer,
            question_data,
        )

    elif task_module == 'task22':
        return await evaluate_task22_answer(
            answer,
            question_data,
        )

    elif task_module == 'task23':
        return await evaluate_task23_answer(
            answer,
            question_data,
        )

    elif task_module == 'task24':
        # Для task24 topic это название темы плана
        return await evaluate_task24_answer(
            answer,
            question_data.get('topic', ''),
            **question_data
        )

    elif task_module == 'task25':
        # Для task25 topic это dict с данными задания
        topic_dict = question_data.get('topic_data', question_data)
        return await evaluate_task25_answer(
            answer,
            topic_dict,
            **question_data
        )

    else:
        logger.warning(f"Evaluator for {task_module} not implemented")
        return False, f"Проверка для модуля {task_module} пока не реализована"
