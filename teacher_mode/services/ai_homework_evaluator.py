"""
Сервис для AI проверки ответов учеников в домашних заданиях.
"""

import logging
from typing import Optional, Dict, Tuple

logger = logging.getLogger(__name__)


async def evaluate_homework_answer(
    task_module: str,
    question_data: Dict,
    user_answer: str,
    user_id: int
) -> Tuple[bool, str]:
    """
    Проверяет ответ ученика через AI evaluator соответствующего модуля.

    Args:
        task_module: Название модуля ('task17', 'task18', 'task19', 'task20', 'task21',
                     'task22', 'task23', 'task24', 'task25', 'test_part', 'custom')
        question_data: Данные вопроса из question_loader или custom_questions
        user_answer: Ответ ученика
        user_id: ID ученика

    Returns:
        Tuple[bool, str]: (is_correct, feedback_text)
        - is_correct: True если ответ принят (набрано > 50% баллов)
        - feedback_text: Текст обратной связи для ученика
    """
    try:
        # Для кастомных вопросов используем указанный тип
        if task_module == 'custom':
            custom_type = question_data.get('type', 'test_part')
            return await _evaluate_custom_question(custom_type, question_data, user_answer, user_id)

        if task_module == 'test_part':
            return await _evaluate_test_part(question_data, user_answer, user_id)
        elif task_module == 'task17':
            return await _evaluate_task17(question_data, user_answer, user_id)
        elif task_module == 'task18':
            return await _evaluate_task18(question_data, user_answer, user_id)
        elif task_module == 'task19':
            return await _evaluate_task19(question_data, user_answer, user_id)
        elif task_module == 'task20':
            return await _evaluate_task20(question_data, user_answer, user_id)
        elif task_module == 'task21':
            return await _evaluate_task21(question_data, user_answer, user_id)
        elif task_module == 'task22':
            return await _evaluate_task22(question_data, user_answer, user_id)
        elif task_module == 'task23':
            return await _evaluate_task23(question_data, user_answer, user_id)
        elif task_module == 'task24':
            return await _evaluate_task24(question_data, user_answer, user_id)
        elif task_module == 'task25':
            return await _evaluate_task25(question_data, user_answer, user_id)
        else:
            logger.warning(f"Unknown task module: {task_module}")
            return False, f"❌ Неизвестный тип задания: {task_module}"

    except Exception as e:
        logger.error(f"Error evaluating answer for {task_module}: {e}", exc_info=True)
        return False, f"❌ Ошибка при проверке ответа: {str(e)}"


async def _evaluate_task17(question_data: Dict, user_answer: str, user_id: int) -> Tuple[bool, str]:
    """Проверка ответа для task17 (анализ текста: поиск информации)"""
    try:
        from task17.evaluator import Task17AIEvaluator
        from core.types import EvaluationResult

        evaluator = Task17AIEvaluator()

        result: EvaluationResult = await evaluator.evaluate(
            answer=user_answer,
            task_data=question_data
        )

        is_correct = result.total_score >= (result.max_score / 2)

        feedback = f"📊 <b>Результат проверки:</b>\n\n"
        feedback += f"Баллы: {result.total_score}/{result.max_score}\n\n"
        feedback += f"<b>Обратная связь:</b>\n{result.feedback}"

        if result.warnings:
            feedback += f"\n\n⚠️ <b>Предупреждения:</b>\n"
            feedback += "\n".join(f"• {w}" for w in result.warnings)

        if result.suggestions:
            feedback += f"\n\n💡 <b>Рекомендации:</b>\n"
            feedback += "\n".join(f"• {s}" for s in result.suggestions)

        return is_correct, feedback

    except ImportError as e:
        logger.warning(f"Task17 evaluator not available: {e}")
        return True, "✅ Ответ принят (AI проверка недоступна)"
    except Exception as e:
        logger.error(f"Error in task17 evaluation: {e}", exc_info=True)
        return False, f"❌ Ошибка при проверке: {str(e)}"


async def _evaluate_task18(question_data: Dict, user_answer: str, user_id: int) -> Tuple[bool, str]:
    """Проверка ответа для task18 (объяснение понятия из текста)"""
    try:
        from task18.evaluator import Task18AIEvaluator
        from core.types import EvaluationResult

        evaluator = Task18AIEvaluator()

        result: EvaluationResult = await evaluator.evaluate(
            answer=user_answer,
            task_data=question_data
        )

        is_correct = result.total_score >= (result.max_score / 2)

        feedback = f"📊 <b>Результат проверки:</b>\n\n"
        feedback += f"Баллы: {result.total_score}/{result.max_score}\n\n"
        feedback += f"<b>Обратная связь:</b>\n{result.feedback}"

        if result.warnings:
            feedback += f"\n\n⚠️ <b>Предупреждения:</b>\n"
            feedback += "\n".join(f"• {w}" for w in result.warnings)

        if result.suggestions:
            feedback += f"\n\n💡 <b>Рекомендации:</b>\n"
            feedback += "\n".join(f"• {s}" for s in result.suggestions)

        return is_correct, feedback

    except ImportError as e:
        logger.warning(f"Task18 evaluator not available: {e}")
        return True, "✅ Ответ принят (AI проверка недоступна)"
    except Exception as e:
        logger.error(f"Error in task18 evaluation: {e}", exc_info=True)
        return False, f"❌ Ошибка при проверке: {str(e)}"


async def _evaluate_task19(question_data: Dict, user_answer: str, user_id: int) -> Tuple[bool, str]:
    """Проверка ответа для task19 (примеры с обществознанием)"""
    try:
        from task19.evaluator import Task19AIEvaluator
        from core.types import EvaluationResult

        # Создаем evaluator
        evaluator = Task19AIEvaluator()

        # Вызываем проверку
        topic = question_data.get('title', 'Неизвестная тема')
        task_text = question_data.get('task_text', '')

        result: EvaluationResult = await evaluator.evaluate(
            answer=user_answer,
            topic=topic,
            task_text=task_text
        )

        # Формируем обратную связь
        is_correct = result.total_score >= (result.max_score / 2)  # >= 50% баллов

        feedback = f"📊 <b>Результат проверки:</b>\n\n"
        feedback += f"Баллы: {result.total_score}/{result.max_score}\n\n"
        feedback += f"<b>Обратная связь:</b>\n{result.feedback}"

        if result.warnings:
            feedback += f"\n\n⚠️ <b>Предупреждения:</b>\n"
            feedback += "\n".join(f"• {w}" for w in result.warnings)

        if result.suggestions:
            feedback += f"\n\n💡 <b>Рекомендации:</b>\n"
            feedback += "\n".join(f"• {s}" for s in result.suggestions)

        return is_correct, feedback

    except ImportError as e:
        logger.warning(f"Task19 evaluator not available: {e}")
        return True, "✅ Ответ принят (AI проверка недоступна)"
    except Exception as e:
        logger.error(f"Error in task19 evaluation: {e}", exc_info=True)
        return False, f"❌ Ошибка при проверке: {str(e)}"


async def _evaluate_task20(question_data: Dict, user_answer: str, user_id: int) -> Tuple[bool, str]:
    """Проверка ответа для task20 (логические задачи)"""
    try:
        from task20.evaluator import Task20AIEvaluator
        from core.types import EvaluationResult

        # Создаем evaluator
        evaluator = Task20AIEvaluator()

        # Вызываем проверку
        topic = question_data.get('title', 'Неизвестная тема')
        task_text = question_data.get('task_text', '')

        result: EvaluationResult = await evaluator.evaluate(
            answer=user_answer,
            topic=topic,
            task_text=task_text
        )

        # Формируем обратную связь
        is_correct = result.total_score >= (result.max_score / 2)

        feedback = f"📊 <b>Результат проверки:</b>\n\n"
        feedback += f"Баллы: {result.total_score}/{result.max_score}\n\n"
        feedback += f"<b>Обратная связь:</b>\n{result.feedback}"

        if result.warnings:
            feedback += f"\n\n⚠️ <b>Предупреждения:</b>\n"
            feedback += "\n".join(f"• {w}" for w in result.warnings)

        if result.suggestions:
            feedback += f"\n\n💡 <b>Рекомендации:</b>\n"
            feedback += "\n".join(f"• {s}" for s in result.suggestions)

        return is_correct, feedback

    except ImportError as e:
        logger.warning(f"Task20 evaluator not available: {e}")
        return True, "✅ Ответ принят (AI проверка недоступна)"
    except Exception as e:
        logger.error(f"Error in task20 evaluation: {e}", exc_info=True)
        return False, f"❌ Ошибка при проверке: {str(e)}"


async def _evaluate_task21(question_data: Dict, user_answer: str, user_id: int) -> Tuple[bool, str]:
    """Проверка ответа для task21 (графики спроса и предложения)"""
    # Если нет структурированных данных (быстрая проверка без загруженных ответов),
    # используем свободную AI-проверку по условию задания.
    # Структурированные данные — это наличие полей question_1/question_2/question_3
    # с реальным содержимым (acceptable_keywords, correct_answer и т.д.)
    has_structured_data = (
        question_data.get("question_1") or
        question_data.get("question_2") or
        question_data.get("question_3")
    )

    if not has_structured_data:
        return await _evaluate_task21_freeform(question_data, user_answer, user_id,
                                               condition_image=question_data.get("condition_image"))

    try:
        from task21.evaluator import Task21Evaluator
        from core.types import EvaluationResult

        evaluator = Task21Evaluator()

        result: EvaluationResult = await evaluator.evaluate(
            user_answer=user_answer,
            question_data=question_data
        )

        is_correct = result.total_score >= (result.max_score / 2)

        feedback = f"📊 <b>Результат проверки:</b>\n\n"
        feedback += f"Баллы: {result.total_score}/{result.max_score}\n\n"
        feedback += f"<b>Обратная связь:</b>\n{result.feedback}"

        if result.suggestions:
            feedback += f"\n\n💡 <b>Рекомендации:</b>\n"
            feedback += "\n".join(f"• {s}" for s in result.suggestions)

        return is_correct, feedback

    except ImportError as e:
        logger.warning(f"Task21 evaluator not available: {e}")
        return True, "✅ Ответ принят (AI проверка недоступна)"
    except Exception as e:
        logger.error(f"Error in task21 evaluation: {e}", exc_info=True)
        return False, f"❌ Ошибка при проверке: {str(e)}"


async def _evaluate_task22(question_data: Dict, user_answer: str, user_id: int) -> Tuple[bool, str]:
    """Проверка ответа для task22 (анализ ситуаций)"""
    # Если нет структурированных данных (быстрая проверка без загруженных ответов),
    # используем свободную AI-проверку по условию задания.
    # Структурированные данные — это наличие непустых questions И correct_answers.
    # Одно лишь описание (description) без вопросов/ответов не является достаточным.
    has_structured_data = (
        question_data.get("questions") and
        question_data.get("correct_answers")
    )

    if not has_structured_data:
        return await _evaluate_task22_freeform(question_data, user_answer, user_id,
                                               condition_image=question_data.get("condition_image"))

    try:
        from task22.evaluator import Task22AIEvaluator
        from core.types import EvaluationResult

        evaluator = Task22AIEvaluator()

        result: EvaluationResult = await evaluator.evaluate(
            answer=user_answer,
            task_data=question_data
        )

        is_correct = result.total_score >= (result.max_score / 2)

        feedback = f"📊 <b>Результат проверки:</b>\n\n"
        feedback += f"Баллы: {result.total_score}/{result.max_score}\n\n"
        feedback += f"<b>Обратная связь:</b>\n{result.feedback}"

        if result.suggestions:
            feedback += f"\n\n💡 <b>Рекомендации:</b>\n"
            feedback += "\n".join(f"• {s}" for s in result.suggestions)

        return is_correct, feedback

    except ImportError as e:
        logger.warning(f"Task22 evaluator not available: {e}")
        return True, "✅ Ответ принят (AI проверка недоступна)"
    except Exception as e:
        logger.error(f"Error in task22 evaluation: {e}", exc_info=True)
        return False, f"❌ Ошибка при проверке: {str(e)}"


async def _evaluate_task23(question_data: Dict, user_answer: str, user_id: int) -> Tuple[bool, str]:
    """Проверка ответа для task23 (Конституция РФ)"""
    try:
        from task23.evaluator import Task23Evaluator
        from core.types import EvaluationResult

        evaluator = Task23Evaluator()

        result: EvaluationResult = await evaluator.evaluate(
            user_answer=user_answer,
            question_data=question_data
        )

        is_correct = result.total_score >= (result.max_score / 2)

        feedback = f"📊 <b>Результат проверки:</b>\n\n"
        feedback += f"Баллы: {result.total_score}/{result.max_score}\n\n"
        feedback += f"<b>Обратная связь:</b>\n{result.feedback}"

        if result.suggestions:
            feedback += f"\n\n💡 <b>Рекомендации:</b>\n"
            feedback += "\n".join(f"• {s}" for s in result.suggestions)

        return is_correct, feedback

    except ImportError as e:
        logger.warning(f"Task23 evaluator not available: {e}")
        return True, "✅ Ответ принят (AI проверка недоступна)"
    except Exception as e:
        logger.error(f"Error in task23 evaluation: {e}", exc_info=True)
        return False, f"❌ Ошибка при проверке: {str(e)}"


async def _evaluate_task24(question_data: Dict, user_answer: str, user_id: int) -> Tuple[bool, str]:
    """Проверка ответа для task24 (развернутый план)"""
    try:
        from task24.checker import evaluate_plan_with_ai
        from task24.handlers import plan_bot_data  # Глобальный объект с данными планов

        # Получаем данные эталонного плана
        topic_name = question_data.get('title', 'Неизвестная тема')

        # Формируем ideal_plan_data из question_data
        ideal_plan_data = {
            'full_plan': question_data.get('full_plan', []),
            'points_data': question_data.get('points_data', []),
            'min_points': question_data.get('min_points', 3),
            'min_detailed_points': question_data.get('min_detailed_points', 2),
            'min_subpoints': question_data.get('min_subpoints', 3)
        }

        # Вызываем проверку
        feedback_text = await evaluate_plan_with_ai(
            user_plan_text=user_answer,
            ideal_plan_data=ideal_plan_data,
            bot_data=plan_bot_data,
            topic_name=topic_name,
            use_ai=True,
            user_id=user_id
        )

        # Извлекаем баллы из feedback
        import re
        k1_match = re.search(r'К1.*?(\d+)/3', feedback_text)
        k2_match = re.search(r'К2.*?(\d+)/1', feedback_text)
        k1 = int(k1_match.group(1)) if k1_match else 0
        k2 = int(k2_match.group(1)) if k2_match else 0

        total_score = k1 + k2
        max_score = 4

        is_correct = total_score >= (max_score / 2)  # >= 2 баллов из 4

        feedback = f"📊 <b>Результат проверки плана:</b>\n\n"
        feedback += feedback_text

        return is_correct, feedback

    except ImportError as e:
        logger.warning(f"Task24 checker not available: {e}")
        return True, "✅ Ответ принят (AI проверка недоступна)"
    except Exception as e:
        logger.error(f"Error in task24 evaluation: {e}", exc_info=True)
        return False, f"❌ Ошибка при проверке: {str(e)}"


async def _evaluate_task25(question_data: Dict, user_answer: str, user_id: int) -> Tuple[bool, str]:
    """Проверка ответа для task25 (эссе)"""
    try:
        from task25.evaluator import Task25AIEvaluator

        # Создаем evaluator
        evaluator = Task25AIEvaluator()

        # Вызываем проверку
        result = await evaluator.evaluate(
            answer=user_answer,
            topic=question_data,  # Передаем весь question_data как topic
            user_id=user_id
        )

        is_correct = result.total_score >= (result.max_score / 2)

        # Используем встроенное форматирование Task25EvaluationResult,
        # которое выводит детальные комментарии по каждому критерию (К1, К2, К3),
        # разбор элементов К2 и примеров К3, рекомендации и фактические ошибки
        if hasattr(result, 'format_feedback'):
            feedback = result.format_feedback()
        else:
            # Фолбэк для базового EvaluationResult без format_feedback
            feedback = f"📊 <b>Результат проверки:</b>\n\n"
            feedback += f"Баллы: {result.total_score}/{result.max_score}\n\n"
            feedback += f"<b>Обратная связь:</b>\n{result.feedback}"

        return is_correct, feedback

    except ImportError as e:
        logger.warning(f"Task25 evaluator not available: {e}")
        return True, "✅ Ответ принят (AI проверка недоступна)"
    except Exception as e:
        logger.error(f"Error in task25 evaluation: {e}", exc_info=True)
        return False, f"❌ Ошибка при проверке: {str(e)}"


async def _evaluate_test_part(question_data: Dict, user_answer: str, user_id: int) -> Tuple[bool, str]:
    """Проверка ответа для тестовой части (короткий ответ)"""
    try:
        # Для тестовой части используем точное сравнение
        correct_answer = question_data.get('answer', question_data.get('correct_answer', ''))

        # Нормализуем ответы (убираем пробелы, приводим к нижнему регистру)
        user_answer_normalized = user_answer.strip().lower().replace(' ', '')
        correct_answer_normalized = str(correct_answer).strip().lower().replace(' ', '')

        is_correct = user_answer_normalized == correct_answer_normalized

        if is_correct:
            feedback = (
                "✅ <b>Ответ правильный!</b>\n\n"
                f"Ваш ответ: <code>{user_answer}</code>\n"
                f"Правильный ответ: <code>{correct_answer}</code>"
            )
        else:
            feedback = (
                "❌ <b>Ответ неправильный</b>\n\n"
                f"Ваш ответ: <code>{user_answer}</code>\n"
                f"Правильный ответ: <code>{correct_answer}</code>"
            )

        return is_correct, feedback

    except Exception as e:
        logger.error(f"Error in test_part evaluation: {e}", exc_info=True)
        return False, f"❌ Ошибка при проверке: {str(e)}"


async def _evaluate_custom_question(
    custom_type: str,
    question_data: Dict,
    user_answer: str,
    user_id: int
) -> Tuple[bool, str]:
    """
    Проверка кастомного вопроса с использованием evaluator соответствующего типа.

    Args:
        custom_type: Тип кастомного вопроса ('test_part', 'task19', 'task20', 'task21',
                     'task22', 'task23', 'task24', 'task25')
        question_data: Данные кастомного вопроса (включая text, type, correct_answer)
        user_answer: Ответ ученика
        user_id: ID ученика

    Returns:
        Tuple[bool, str]: (is_correct, feedback_text)
    """
    try:
        # Получаем текст вопроса и правильный ответ/критерии из кастомного вопроса
        question_text = question_data.get('text', '')
        correct_answer = question_data.get('correct_answer')

        # Для test_part используем простую проверку
        if custom_type == 'test_part':
            if correct_answer:
                # Если учитель указал правильный ответ, сравниваем
                user_answer_normalized = user_answer.strip().lower().replace(' ', '')
                correct_answer_normalized = str(correct_answer).strip().lower().replace(' ', '')

                is_correct = user_answer_normalized == correct_answer_normalized

                if is_correct:
                    feedback = (
                        "✅ <b>Ответ правильный!</b>\n\n"
                        f"Ваш ответ: <code>{user_answer}</code>\n"
                        f"Правильный ответ: <code>{correct_answer}</code>"
                    )
                else:
                    feedback = (
                        "❌ <b>Ответ неправильный</b>\n\n"
                        f"Ваш ответ: <code>{user_answer}</code>\n"
                        f"Правильный ответ: <code>{correct_answer}</code>"
                    )

                return is_correct, feedback
            else:
                # Если правильный ответ не указан, принимаем ответ без проверки
                feedback = (
                    "✅ <b>Ответ принят</b>\n\n"
                    f"Ваш ответ: <code>{user_answer}</code>\n\n"
                    "💡 Учитель не указал правильный ответ, поэтому ваш ответ принят автоматически."
                )
                return True, feedback

        # Для заданий 17-25 используем соответствующие AI evaluators
        elif custom_type == 'task17':
            eval_question_data = {
                'text': question_text,
                'question': question_text,
            }
            if correct_answer:
                eval_question_data['correct_answers'] = [correct_answer]
            return await _evaluate_task17(eval_question_data, user_answer, user_id)

        elif custom_type == 'task18':
            from task18.evaluator import extract_concept_from_text
            eval_question_data = {
                'text': question_text,
                'question': question_text,
                'concept': extract_concept_from_text(question_text),
            }
            if correct_answer:
                eval_question_data['elements'] = [correct_answer]
            return await _evaluate_task18(eval_question_data, user_answer, user_id)

        elif custom_type == 'task19':
            # Формируем question_data для evaluator
            eval_question_data = {
                'title': 'Кастомный вопрос',
                'task_text': question_text
            }

            # Если указаны критерии, добавляем их в feedback
            if correct_answer:
                eval_question_data['criteria'] = correct_answer

            return await _evaluate_task19(eval_question_data, user_answer, user_id)

        elif custom_type == 'task20':
            eval_question_data = {
                'title': 'Кастомный вопрос',
                'task_text': question_text
            }

            if correct_answer:
                eval_question_data['criteria'] = correct_answer

            return await _evaluate_task20(eval_question_data, user_answer, user_id)

        elif custom_type == 'task21':
            eval_question_data = {
                'task_text': question_text,
                'market_name': 'Кастомное задание',
            }
            return await _evaluate_task21(eval_question_data, user_answer, user_id)

        elif custom_type == 'task22':
            eval_question_data = {
                'description': question_text,
                'questions': [],
                'correct_answers': [],
                'answer_requirements': [],
                'connected_questions': [],
            }
            return await _evaluate_task22(eval_question_data, user_answer, user_id)

        elif custom_type == 'task23':
            eval_question_data = {
                'model_type': 1,
                'characteristics': [question_text],
                'model_answers': [],
            }
            return await _evaluate_task23(eval_question_data, user_answer, user_id)

        elif custom_type == 'task24':
            eval_question_data = {
                'topic': 'Кастомный план',
                'full_plan': [],
                'points_data': [],
                'min_points': 3,
                'min_detailed_points': 2,
                'min_subpoints': 3
            }

            if correct_answer:
                # Если учитель указал критерии, можем использовать их
                eval_question_data['description'] = f"Критерии: {correct_answer}"

            return await _evaluate_task24(eval_question_data, user_answer, user_id)

        elif custom_type == 'task25':
            eval_question_data = {
                'title': 'Кастомное эссе',
                'task_text': question_text
            }

            if correct_answer:
                eval_question_data['criteria'] = correct_answer

            return await _evaluate_task25(eval_question_data, user_answer, user_id)

        else:
            logger.warning(f"Unknown custom question type: {custom_type}")
            return True, f"✅ Ответ принят (неизвестный тип задания: {custom_type})"

    except Exception as e:
        logger.error(f"Error evaluating custom question: {e}", exc_info=True)
        return False, f"❌ Ошибка при проверке кастомного вопроса: {str(e)}"


# ============================================
# Свободная AI-проверка (без структурированных данных)
# ============================================

async def _evaluate_task21_freeform(
    question_data: Dict,
    user_answer: str,
    user_id: int,
    condition_image: Optional[Dict] = None
) -> Tuple[bool, str]:
    """
    AI-проверка задания 21 по свободному условию (без предзагруженных ответов).

    Используется когда учитель ввёл условие задания вручную и нет
    структурированных данных вопросов (question_1, question_2, question_3).

    Args:
        condition_image: Опциональное изображение условия (график) в формате
                        {'base64': str, 'media_type': str}
    """
    try:
        from core.ai_service import create_ai_service, AIServiceConfig, AIModel

        config = AIServiceConfig.from_env()
        config.model = AIModel.LITE
        config.temperature = 0.2

        task_text = question_data.get('task_text', '')

        has_image = condition_image is not None
        system_prompt = (
            "Ты - опытный эксперт ЕГЭ по обществознанию, специализирующийся на проверке "
            "задания 21 (анализ графиков спроса и предложения).\n\n"
            "ЗАДАНИЕ 21 предполагает анализ графического изображения, иллюстрирующего "
            "изменения спроса/предложения на конкретном рынке, и ответ на три вопроса.\n\n"
            + ("К условию задания прикреплено изображение графика. Внимательно проанализируй его "
               "для определения правильных ответов на вопросы (направление сдвига кривых, "
               "изменение равновесной цены и количества).\n\n" if has_image else "")
            + "Максимальный балл: 3 (по 1 баллу за каждый правильный ответ на вопрос).\n\n"
            "КРИТЕРИИ:\n"
            "- Вопрос 1: Как изменилась равновесная цена? (ответ должен быть однозначным)\n"
            "- Вопрос 2: Фактор + объяснение его влияния применительно к конкретному рынку "
            "+ характер изменения\n"
            "- Вопрос 3: Прогноз изменения двух переменных\n\n"
            "Проверяй строго, но справедливо. Учитывай допустимые формулировки."
        )

        prompt = (
            f"Проверь ответ ученика на задание 21 ЕГЭ по обществознанию.\n\n"
            f"УСЛОВИЕ ЗАДАНИЯ:\n{task_text}\n\n"
            f"ОТВЕТ УЧЕНИКА:\n{user_answer}\n\n"
            f"Проверь ответ и оцени по критериям задания 21 (максимум 3 балла).\n"
            f"Определи, на какие из трёх вопросов ученик ответил правильно.\n\n"
            f"Ответь в формате JSON:\n"
            f"```json\n"
            f"{{\n"
            f'    "score": "число от 0 до 3",\n'
            f'    "max_score": 3,\n'
            f'    "answers_evaluation": [\n'
            f'        {{\n'
            f'            "question_number": 1,\n'
            f'            "is_correct": true,\n'
            f'            "comment": "комментарий к ответу на вопрос 1"\n'
            f"        }},\n"
            f'        {{\n'
            f'            "question_number": 2,\n'
            f'            "is_correct": false,\n'
            f'            "comment": "комментарий к ответу на вопрос 2"\n'
            f"        }},\n"
            f'        {{\n'
            f'            "question_number": 3,\n'
            f'            "is_correct": true,\n'
            f'            "comment": "комментарий к ответу на вопрос 3"\n'
            f"        }}\n"
            f"    ],\n"
            f'    "feedback": "общая обратная связь (2-3 предложения)",\n'
            f'    "suggestions": ["рекомендация 1", "рекомендация 2"]\n'
            f"}}\n"
            f"```\n\n"
            f"ВАЖНО: Верни ТОЛЬКО валидный JSON."
        )

        # Подготавливаем изображения для multimodal вызова
        images = [condition_image] if condition_image else None

        async with create_ai_service(config) as service:
            result = await service.get_json_completion(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=config.temperature,
                images=images
            )

            if result:
                score = int(result.get("score", 0))
                max_score = int(result.get("max_score", 3))
                feedback_text = result.get("feedback", "")
                suggestions = result.get("suggestions", [])
                answers_eval = result.get("answers_evaluation", [])

                is_correct = score >= (max_score / 2)

                feedback = f"📊 <b>Результат проверки:</b>\n\n"
                feedback += f"Баллы: {score}/{max_score}\n\n"

                if answers_eval:
                    feedback += "<b>Проверка ответов:</b>\n"
                    for item in answers_eval:
                        q_num = item.get("question_number", "?")
                        q_ok = item.get("is_correct", False)
                        q_comment = item.get("comment", "")
                        icon = "✅" if q_ok else "❌"
                        feedback += f"\n{icon} <b>Вопрос {q_num}:</b> {q_comment}\n"

                feedback += f"\n<b>Обратная связь:</b>\n{feedback_text}"

                if suggestions:
                    feedback += f"\n\n💡 <b>Рекомендации:</b>\n"
                    feedback += "\n".join(f"• {s}" for s in suggestions)

                return is_correct, feedback

        return True, "✅ Ответ принят (AI проверка не вернула результат)"

    except ImportError as e:
        logger.warning(f"AI service not available for task21 freeform: {e}")
        return True, "✅ Ответ принят (AI сервис недоступен)"
    except Exception as e:
        logger.error(f"Error in task21 freeform evaluation: {e}", exc_info=True)
        return False, f"❌ Ошибка при проверке: {str(e)}"


async def _evaluate_task22_freeform(
    question_data: Dict,
    user_answer: str,
    user_id: int,
    condition_image: Optional[Dict] = None
) -> Tuple[bool, str]:
    """
    AI-проверка задания 22 по свободному условию (без предзагруженных ответов).

    Используется когда учитель ввёл условие задания вручную и нет
    структурированных данных (questions, correct_answers и т.д.).

    Args:
        condition_image: Опциональное изображение условия в формате
                        {'base64': str, 'media_type': str}
    """
    try:
        from core.ai_service import create_ai_service, AIServiceConfig, AIModel

        config = AIServiceConfig.from_env()
        config.model = AIModel.LITE
        config.temperature = 0.2

        task_text = question_data.get('task_text', '') or question_data.get('description', '')

        system_prompt = (
            "Ты - опытный эксперт ЕГЭ по обществознанию, специализирующийся на проверке "
            "задания 22 (задание-задача).\n\n"
            "ЗАДАНИЕ 22 содержит условие (описание конкретной ситуации) и четыре вопроса.\n"
            "Максимальный балл: 4 (по 1 баллу за каждый правильный ответ).\n\n"
            "КРИТЕРИИ ОЦЕНИВАНИЯ:\n"
            "- 4 балла: правильно даны ответы на четыре вопроса\n"
            "- 3 балла: правильно даны ответы на любые три вопроса\n"
            "- 2 балла: правильно даны ответы на любые два вопроса\n"
            "- 1 балл: правильно дан ответ на любой один вопрос\n"
            "- 0 баллов: ответ неправильный или рассуждения общего характера\n\n"
            "ВАЖНЫЕ МОМЕНТЫ:\n"
            "- Полный правильный ответ предполагает указание определённого количества позиций\n"
            "- Если вопрос предполагает родовое понятие, а следующий — виды, "
            "правильный ответ на первый необходим для засчитывания второго\n"
            "- Не засчитывай ответы с фактическими ошибками\n"
            "- Не засчитывай общие рассуждения без конкретного ответа\n"
            "- Учитывай допустимые формулировки (ответ не обязан быть дословным)"
        )

        prompt = (
            f"Проверь ответ ученика на задание 22 ЕГЭ по обществознанию.\n\n"
            f"УСЛОВИЕ ЗАДАНИЯ:\n{task_text}\n\n"
            f"ОТВЕТ УЧЕНИКА:\n{user_answer}\n\n"
            f"Проверь ответ и оцени по критериям задания 22 (максимум 4 балла).\n"
            f"Определи, на какие из четырёх вопросов ученик ответил правильно.\n\n"
            f"Ответь в формате JSON:\n"
            f"```json\n"
            f"{{\n"
            f'    "score": "число от 0 до 4",\n'
            f'    "max_score": 4,\n'
            f'    "correct_answers_count": "количество правильных ответов",\n'
            f'    "answers_evaluation": [\n'
            f'        {{\n'
            f'            "question_number": 1,\n'
            f'            "is_correct": true,\n'
            f'            "comment": "комментарий к ответу на вопрос 1"\n'
            f"        }}\n"
            f"    ],\n"
            f'    "feedback": "общий комментарий (2-3 предложения)",\n'
            f'    "suggestions": ["рекомендация 1", "рекомендация 2"],\n'
            f'    "factual_errors": []\n'
            f"}}\n"
            f"```\n\n"
            f"ВАЖНО: Верни ТОЛЬКО валидный JSON."
        )

        # Подготавливаем изображения для multimodal вызова
        images = [condition_image] if condition_image else None

        async with create_ai_service(config) as service:
            result = await service.get_json_completion(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=config.temperature,
                images=images
            )

            if result:
                score = int(result.get("score", 0))
                max_score = int(result.get("max_score", 4))
                correct_count = int(result.get("correct_answers_count", 0))
                feedback_text = result.get("feedback", "")
                suggestions = result.get("suggestions", [])
                answers_eval = result.get("answers_evaluation", [])
                factual_errors = result.get("factual_errors", [])

                is_correct = score >= (max_score / 2)

                feedback = f"📊 <b>Результат проверки:</b>\n\n"
                feedback += f"Баллы: {score}/{max_score}\n\n"

                if answers_eval:
                    feedback += f"<b>Результат:</b> {correct_count} из 4 ответов правильны.\n\n"
                    feedback += "<b>Проверка ответов:</b>\n"
                    for item in answers_eval:
                        q_num = item.get("question_number", "?")
                        q_ok = item.get("is_correct", False)
                        q_comment = item.get("comment", "")
                        icon = "✅" if q_ok else "❌"
                        feedback += f"{icon} <b>Вопрос {q_num}:</b> {q_comment}\n"

                feedback += f"\n<b>Обратная связь:</b>\n{feedback_text}"

                if factual_errors:
                    feedback += f"\n\n⚠️ <b>Фактические ошибки:</b>\n"
                    feedback += "\n".join(f"• {e}" for e in factual_errors)

                if suggestions:
                    feedback += f"\n\n💡 <b>Рекомендации:</b>\n"
                    feedback += "\n".join(f"• {s}" for s in suggestions)

                return is_correct, feedback

        return True, "✅ Ответ принят (AI проверка не вернула результат)"

    except ImportError as e:
        logger.warning(f"AI service not available for task22 freeform: {e}")
        return True, "✅ Ответ принят (AI сервис недоступен)"
    except Exception as e:
        logger.error(f"Error in task22 freeform evaluation: {e}", exc_info=True)
        return False, f"❌ Ошибка при проверке: {str(e)}"
