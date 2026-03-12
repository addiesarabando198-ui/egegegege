"""
AI-проверка для задания 21 (Анализ графиков спроса и предложения).

Комбинированный подход:
- Вопрос 1 и 3: простая проверка по ключевым словам
- Вопрос 2: AI-проверка с анализом фактора, объяснения и характера изменения
"""

import logging
import re
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass

from core.types import TaskRequirements, EvaluationResult

logger = logging.getLogger(__name__)

# Импорт калибровочных few-shot примеров
try:
    from core.fewshot_calibration import get_full_calibration_prompt
except ImportError:
    def get_full_calibration_prompt(task_number: int) -> str:
        return ""

# Безопасный импорт AI сервисов
try:
    from core.ai_evaluator import BaseAIEvaluator
    from core.ai_service import create_ai_service, AIServiceConfig, AIModel
    AI_EVALUATOR_AVAILABLE = True
except ImportError as e:
    logger.warning(f"AI evaluator components not available: {e}")
    AI_EVALUATOR_AVAILABLE = False

    class BaseAIEvaluator:
        def __init__(self, requirements: TaskRequirements):
            self.requirements = requirements

    def create_ai_service(config):
        return None

    class AIServiceConfig:
        pass

    class AIModel:
        LITE = "lite"
        PRO = "pro"


@dataclass
class QuestionEvaluation:
    """Результат оценки одного вопроса."""
    question_number: int
    is_correct: bool
    comment: str
    user_answer: str
    details: Optional[Dict[str, Any]] = None


class Task21Evaluator(BaseAIEvaluator if AI_EVALUATOR_AVAILABLE else object):
    """AI-проверщик для задания 21 (Графики спроса и предложения)."""

    def __init__(self):
        if AI_EVALUATOR_AVAILABLE:
            requirements = TaskRequirements(
                task_number=21,
                task_name="Анализ графиков спроса и предложения",
                max_score=3,
                criteria=[
                    {
                        "name": "К1",
                        "max_score": 3,
                        "description": "Правильность ответов на три вопроса (по 1 баллу за каждый)"
                    }
                ],
                description="Анализ графика изменения спроса/предложения на конкретном рынке"
            )
            super().__init__(requirements)
        else:
            self.requirements = TaskRequirements(
                task_number=21,
                task_name="Анализ графиков спроса и предложения",
                max_score=3,
                criteria=[{"name": "К1", "max_score": 3, "description": "Правильность ответов"}],
                description="Анализ графика изменения спроса/предложения"
            )

        self.ai_service = None
        self.config = None

        if AI_EVALUATOR_AVAILABLE:
            try:
                config = AIServiceConfig.from_env()
                config.model = AIModel.LITE  # Sonnet достаточен для задания 21
                config.temperature = 0.2
                self.config = config
                logger.info("Task21 AI evaluator configured")
            except Exception as e:
                logger.error(f"Failed to configure AI service: {e}")
                self.config = None

    def get_system_prompt(self) -> str:
        """Системный промпт для проверки вопроса 2."""
        return """Ты - опытный эксперт ЕГЭ по обществознанию, специализирующийся на проверке задания 21 (анализ графиков спроса и предложения).

ЗАДАНИЕ 21 - БАЗОВЫЙ УРОВЕНЬ СЛОЖНОСТИ:
Задание предполагает анализ графического изображения, иллюстрирующего изменения спроса/предложения на конкретном рынке, и ответ на три вопроса.

КРИТЕРИИ ОЦЕНИВАНИЯ ВОПРОСА 2 (фактор + объяснение):

✅ ОТВЕТ ЗАСЧИТЫВАЕТСЯ, если:
1. Указан конкретный ФАКТОР (обстоятельство), который мог вызвать изменение
2. Дано ОБЪЯСНЕНИЕ влияния этого фактора на спрос/предложение
3. Указан ХАРАКТЕР изменения (увеличилось/уменьшилось, выросло/сократилось)
4. Объяснение дано ПРИМЕНИТЕЛЬНО К КОНКРЕТНОМУ РЫНКУ из задания
5. Нет дополнительных неверных факторов/объяснений

❌ ОТВЕТ НЕ ЗАСЧИТЫВАЕТСЯ, если:
1. Указан только фактор БЕЗ объяснения
2. НЕ указан характер изменения (увеличилось/уменьшилось)
3. Объяснение дано в абстрактно-теоретической форме, не применительно к конкретному рынку
4. Указано несколько факторов, и хотя бы один из них неверный
5. Содержится фактическая ошибка

ВАЖНО: Обстоятельство (фактор) следует выделить как самостоятельный элемент ответа.

При проверке:
- Будь строг к наличию всех элементов (фактор + объяснение + характер изменения)
- Проверяй применимость к конкретному рынку
- Учитывай допустимые синонимы (увеличилось = выросло = возросло)

""" + get_full_calibration_prompt(21) + """
"""

    async def evaluate(
        self,
        user_answer: str,
        question_data: Dict[str, Any],
        **kwargs
    ) -> EvaluationResult:
        """
        Оценка ответа пользователя на задание 21.

        Args:
            user_answer: Ответ пользователя (текст)
            question_data: Данные вопроса из JSON

        Returns:
            EvaluationResult с оценкой и обратной связью
        """
        # Парсим ответы пользователя
        user_answers = self._parse_user_answers(user_answer)

        evaluations: List[QuestionEvaluation] = []

        # Оцениваем вопрос 1 (изменение цены) - простая проверка
        q1_eval = self._evaluate_question1(
            user_answers.get(1, ""),
            question_data.get("question_1", {})
        )
        evaluations.append(q1_eval)

        # Оцениваем вопрос 2 (фактор + объяснение) - AI-проверка
        q2_eval = await self._evaluate_question2(
            user_answers.get(2, ""),
            question_data
        )
        evaluations.append(q2_eval)

        # Оцениваем вопрос 3 (прогноз) - простая проверка
        q3_eval = self._evaluate_question3(
            user_answers.get(3, ""),
            question_data.get("question_3", {})
        )
        evaluations.append(q3_eval)

        # Подсчитываем итоговый балл
        correct_count = sum(1 for e in evaluations if e.is_correct)
        score = correct_count

        # Формируем обратную связь
        feedback = self._build_feedback(evaluations, score, question_data)

        return EvaluationResult(
            criteria_scores={"К1": score},
            total_score=score,
            max_score=3,
            feedback=feedback,
            detailed_feedback={
                "correct_count": correct_count,
                "evaluations": [
                    {
                        "question": e.question_number,
                        "is_correct": e.is_correct,
                        "comment": e.comment,
                        "user_answer": e.user_answer
                    }
                    for e in evaluations
                ]
            },
            suggestions=self._get_suggestions(evaluations),
            factual_errors=[]
        )

    def _parse_user_answers(self, answer: str) -> Dict[int, str]:
        """
        Парсинг ответов пользователя.

        Поддерживает форматы:
        - Нумерованный список (1. ..., 2. ..., 3. ...) - в одну строку или с переносами
        - Цельный текст с разделением по строкам
        """
        answers = {}

        # Сначала пробуем найти нумерованные ответы (работает и в одну строку)
        # Паттерн ищет "1." или "1)" и текст до следующего номера или конца
        pattern = r'(?:^|\s)(\d)[.)]\s*(.+?)(?=(?:\s\d[.)])|$)'
        matches = list(re.finditer(pattern, answer, re.DOTALL))

        if matches:
            for match in matches:
                num = int(match.group(1))
                text = match.group(2).strip()
                if 1 <= num <= 3 and text:
                    answers[num] = text

        # Если не нашли все 3 ответа, пробуем альтернативный паттерн для многострочного
        if len(answers) < 3:
            pattern2 = r'^\s*(\d+)[.)]\s*(.+?)(?=^\s*\d+[.)]|\Z)'
            matches2 = list(re.finditer(pattern2, answer, re.MULTILINE | re.DOTALL))
            for match in matches2:
                num = int(match.group(1))
                text = match.group(2).strip()
                if 1 <= num <= 3 and num not in answers and text:
                    answers[num] = text

        # Если всё ещё не нашли нумерацию, разделяем по переносам строк
        if not answers:
            lines = [line.strip() for line in answer.split('\n') if line.strip()]
            for i, line in enumerate(lines[:3], 1):
                # Убираем возможные маркеры
                clean_line = re.sub(r'^[-–—•]\s*', '', line).strip()
                if clean_line:
                    answers[i] = clean_line

        return answers

    def _evaluate_question1(
        self,
        user_answer: str,
        q1_data: Dict[str, Any]
    ) -> QuestionEvaluation:
        """
        Оценка вопроса 1: Как изменилась равновесная цена?

        Простая проверка по ключевым словам.
        """
        if not user_answer:
            return QuestionEvaluation(
                question_number=1,
                is_correct=False,
                comment="Ответ не предоставлен",
                user_answer=""
            )

        acceptable = q1_data.get("acceptable_keywords", [])
        correct_answer = q1_data.get("correct_answer", "")

        user_lower = user_answer.lower()

        # Проверяем наличие правильного ключевого слова
        is_correct = False
        for keyword in acceptable:
            if keyword.lower() in user_lower:
                is_correct = True
                break

        # Проверяем, нет ли противоречия (оба варианта одновременно)
        increase_keywords = ["увеличил", "вырос", "возрос", "повысил", "стала больше"]
        decrease_keywords = ["уменьшил", "снизил", "упал", "сократил", "понизил", "стала меньше"]

        has_increase = any(kw in user_lower for kw in increase_keywords)
        has_decrease = any(kw in user_lower for kw in decrease_keywords)

        if has_increase and has_decrease:
            return QuestionEvaluation(
                question_number=1,
                is_correct=False,
                comment="Ответ неоднозначен: указаны противоречивые изменения цены",
                user_answer=user_answer
            )

        if is_correct:
            comment = f"Правильно указано изменение цены"
        else:
            comment = f"Неверно. Правильный ответ: равновесная цена {correct_answer}"

        return QuestionEvaluation(
            question_number=1,
            is_correct=is_correct,
            comment=comment,
            user_answer=user_answer
        )

    async def _evaluate_question2(
        self,
        user_answer: str,
        question_data: Dict[str, Any]
    ) -> QuestionEvaluation:
        """
        Оценка вопроса 2: Что могло вызвать изменение?

        AI-проверка с анализом:
        - Наличия фактора
        - Наличия объяснения
        - Указания характера изменения
        - Применимости к конкретному рынку
        """
        if not user_answer:
            return QuestionEvaluation(
                question_number=2,
                is_correct=False,
                comment="Ответ не предоставлен",
                user_answer=""
            )

        q2_data = question_data.get("question_2", {})

        # Если AI недоступен, используем базовую проверку
        if not AI_EVALUATOR_AVAILABLE or not self.config:
            return self._basic_evaluate_question2(user_answer, q2_data, question_data)

        # Формируем промпт для AI
        prompt = self._build_q2_prompt(user_answer, q2_data, question_data)

        try:
            async with create_ai_service(self.config) as service:
                result = await service.get_json_completion(
                    prompt=prompt,
                    system_prompt=self.get_system_prompt(),
                    temperature=self.config.temperature
                )

                if result:
                    return self._parse_q2_response(result, user_answer)
                else:
                    return self._basic_evaluate_question2(user_answer, q2_data, question_data)

        except Exception as e:
            logger.error(f"Error in Task21 Q2 evaluation: {e}")
            return self._basic_evaluate_question2(user_answer, q2_data, question_data)

    def _build_q2_prompt(
        self,
        user_answer: str,
        q2_data: Dict[str, Any],
        question_data: Dict[str, Any]
    ) -> str:
        """Формирование промпта для проверки вопроса 2."""
        market_name = question_data.get("market_name", "")
        variable_changed = q2_data.get("variable_changed", "предложение")
        change_direction = q2_data.get("change_direction", "")
        example_answers = q2_data.get("example_answers", [])
        evaluation_note = q2_data.get("evaluation_note", "")

        examples_text = "\n".join([f"  - {ans}" for ans in example_answers])

        return f"""Проверь ответ на ВТОРОЙ ВОПРОС задания 21 ЕГЭ.

КОНТЕКСТ ЗАДАНИЯ:
- Рынок: {market_name}
- Что изменилось на графике: {variable_changed}
- Направление изменения: {change_direction}

ВОПРОС: Что могло вызвать изменение {variable_changed}? Укажите любое одно обстоятельство (фактор) и объясните его влияние на {variable_changed}. (Объяснение должно быть дано применительно к рынку {market_name}.)

ПРИМЕРЫ ПРАВИЛЬНЫХ ОТВЕТОВ (не исчерпывающий список!):
{examples_text}

ОСОБЫЕ УКАЗАНИЯ:
{evaluation_note}

ОТВЕТ УЧЕНИКА:
{user_answer}

ПРОВЕРЬ ПО КРИТЕРИЯМ:
1. ФАКТОР: Указан ли конкретный фактор (обстоятельство)?
2. ОБЪЯСНЕНИЕ: Дано ли объяснение влияния фактора?
3. ХАРАКТЕР ИЗМЕНЕНИЯ: Указано ли, что {variable_changed} {change_direction}?
4. ПРИМЕНИМОСТЬ К РЫНКУ: Объяснение дано применительно к рынку {market_name}?
5. ОТСУТСТВИЕ ОШИБОК: Нет ли неверных факторов или фактических ошибок?

Ответь в формате JSON:
```json
{{
    "has_factor": true/false,
    "factor_identified": "какой фактор указан",
    "has_explanation": true/false,
    "has_change_character": true/false,
    "change_character_correct": true/false,
    "is_market_specific": true/false,
    "has_errors": true/false,
    "error_description": "описание ошибки" или null,
    "is_correct": true/false,
    "comment": "развёрнутый комментарий почему засчитано/не засчитано"
}}
```

ВАЖНО: Верни ТОЛЬКО валидный JSON."""

    def _parse_q2_response(
        self,
        response: Dict[str, Any],
        user_answer: str
    ) -> QuestionEvaluation:
        """Парсинг ответа AI для вопроса 2."""
        try:
            is_correct = response.get("is_correct", False)
            comment = response.get("comment", "")

            # Добавляем детали к комментарию
            details = []
            if not response.get("has_factor", True):
                details.append("не указан фактор")
            if not response.get("has_explanation", True):
                details.append("нет объяснения")
            if not response.get("has_change_character", True):
                details.append("не указан характер изменения")
            if not response.get("is_market_specific", True):
                details.append("объяснение не применимо к конкретному рынку")
            if response.get("has_errors", False):
                error = response.get("error_description", "")
                if error:
                    details.append(f"ошибка: {error}")

            if details and not is_correct:
                comment += f"\nПроблемы: {'; '.join(details)}"

            return QuestionEvaluation(
                question_number=2,
                is_correct=is_correct,
                comment=comment,
                user_answer=user_answer,
                details=response
            )

        except Exception as e:
            logger.error(f"Error parsing Q2 response: {e}")
            return QuestionEvaluation(
                question_number=2,
                is_correct=False,
                comment="Ошибка обработки ответа",
                user_answer=user_answer
            )

    def _basic_evaluate_question2(
        self,
        user_answer: str,
        q2_data: Dict[str, Any],
        question_data: Dict[str, Any]
    ) -> QuestionEvaluation:
        """Базовая оценка вопроса 2 без AI."""
        variable_changed = q2_data.get("variable_changed", "предложение")
        change_direction = q2_data.get("change_direction", "")

        user_lower = user_answer.lower()

        # Проверяем наличие ключевых элементов
        has_change_word = False
        if change_direction in ["увеличилось", "увеличился"]:
            change_keywords = ["увеличил", "вырос", "возрос", "повысил"]
        else:
            change_keywords = ["уменьшил", "снизил", "упал", "сократил"]

        for kw in change_keywords:
            if kw in user_lower:
                has_change_word = True
                break

        # Базовая проверка - есть ли слово "предложение" или "спрос" и изменение
        has_variable = variable_changed.lower() in user_lower

        # Считаем ответ частично правильным если есть оба элемента
        is_correct = has_change_word and has_variable and len(user_answer) > 30

        comment = "Базовая проверка (AI недоступен). "
        if is_correct:
            comment += "Ответ содержит необходимые элементы."
        else:
            missing = []
            if not has_variable:
                missing.append(f"не найдено упоминание '{variable_changed}'")
            if not has_change_word:
                missing.append("не указан характер изменения")
            if len(user_answer) <= 30:
                missing.append("ответ слишком короткий")
            comment += f"Недостатки: {'; '.join(missing)}"

        return QuestionEvaluation(
            question_number=2,
            is_correct=is_correct,
            comment=comment,
            user_answer=user_answer
        )

    def _evaluate_question3(
        self,
        user_answer: str,
        q3_data: Dict[str, Any]
    ) -> QuestionEvaluation:
        """
        Оценка вопроса 3: Как изменятся спрос/предложение и равновесная цена?

        Простая проверка по ключевым словам для двух переменных.
        """
        if not user_answer:
            return QuestionEvaluation(
                question_number=3,
                is_correct=False,
                comment="Ответ не предоставлен",
                user_answer=""
            )

        variables = q3_data.get("variables_to_predict", [])
        if not variables:
            return QuestionEvaluation(
                question_number=3,
                is_correct=False,
                comment="Ошибка в данных задания",
                user_answer=user_answer
            )

        user_lower = user_answer.lower()

        # Проверяем каждую переменную
        correct_vars = []
        incorrect_vars = []

        for var in variables:
            var_name = var.get("name", "")
            correct_answer = var.get("correct_answer", "")
            acceptable = var.get("acceptable_keywords", [])

            # Ищем упоминание переменной и её изменения
            var_found = False
            correct_change = False

            # Определяем ключевые слова для проверки
            if correct_answer in ["увеличится", "вырастет", "возрастёт"]:
                correct_keywords = ["увеличит", "вырастет", "возрастёт", "повысит", "станет больше"]
                wrong_keywords = ["уменьшит", "снизит", "упадёт", "сократит"]
            else:
                correct_keywords = ["уменьшит", "снизит", "упадёт", "сократит", "понизит", "станет меньше"]
                wrong_keywords = ["увеличит", "вырастет", "возрастёт", "повысит"]

            # Проверяем правильность
            for kw in correct_keywords:
                if kw in user_lower:
                    correct_change = True
                    break

            # Проверяем на противоречие
            has_wrong = any(kw in user_lower for kw in wrong_keywords)

            if correct_change and not has_wrong:
                correct_vars.append(var_name)
            else:
                incorrect_vars.append((var_name, correct_answer))

        # Оба ответа должны быть правильными
        is_correct = len(correct_vars) == len(variables) and len(incorrect_vars) == 0

        if is_correct:
            comment = "Правильно указаны изменения обеих переменных"
        else:
            wrong_list = [f"{name} (правильно: {ans})" for name, ans in incorrect_vars]
            comment = f"Неверно для: {', '.join(wrong_list)}"

        return QuestionEvaluation(
            question_number=3,
            is_correct=is_correct,
            comment=comment,
            user_answer=user_answer
        )

    def _build_feedback(
        self,
        evaluations: List[QuestionEvaluation],
        score: int,
        question_data: Dict[str, Any]
    ) -> str:
        """Формирование обратной связи."""
        correct_count = sum(1 for e in evaluations if e.is_correct)

        feedback = f"<b>Результат:</b> {correct_count} из 3 ответов правильны.\n"
        feedback += f"<b>Балл:</b> {score}/3\n\n"

        feedback += "<b>Проверка ответов:</b>\n"

        for eval_item in evaluations:
            icon = "✅" if eval_item.is_correct else "❌"
            feedback += f"\n{icon} <b>Вопрос {eval_item.question_number}:</b>\n"

            if eval_item.user_answer:
                # Обрезаем длинные ответы
                answer_preview = eval_item.user_answer
                if len(answer_preview) > 100:
                    answer_preview = answer_preview[:100] + "..."
                feedback += f"   <i>Ваш ответ: {answer_preview}</i>\n"

            feedback += f"   {eval_item.comment}\n"

        return feedback

    def _get_suggestions(self, evaluations: List[QuestionEvaluation]) -> List[str]:
        """Получение рекомендаций по улучшению ответа."""
        suggestions = []

        for eval_item in evaluations:
            if not eval_item.is_correct:
                if eval_item.question_number == 1:
                    suggestions.append(
                        "Вопрос 1: Внимательно смотрите на график - при сдвиге кривой "
                        "предложения вправо цена уменьшается, влево - увеличивается"
                    )
                elif eval_item.question_number == 2:
                    suggestions.append(
                        "Вопрос 2: Обязательно укажите: 1) конкретный фактор, "
                        "2) объяснение его влияния, 3) характер изменения (увеличилось/уменьшилось), "
                        "4) применительно к конкретному рынку из задания"
                    )
                elif eval_item.question_number == 3:
                    suggestions.append(
                        "Вопрос 3: Нужно однозначно указать изменение ОБЕИХ переменных "
                        "(спрос/предложение И равновесная цена)"
                    )

        return suggestions

    def get_model_answers_text(self, question_data: Dict[str, Any]) -> str:
        """Получить текст эталонных ответов для отображения."""
        text = "<b>Эталонные ответы:</b>\n\n"

        # Вопрос 1
        q1 = question_data.get("question_1", {})
        text += f"<b>1. {q1.get('text', 'Как изменилась равновесная цена?')}</b>\n"
        text += f"   Ответ: {q1.get('correct_answer', '')}\n\n"

        # Вопрос 2
        q2 = question_data.get("question_2", {})
        text += f"<b>2. {q2.get('text', '')}</b>\n"
        text += f"   Примеры ответов:\n"
        for example in q2.get("example_answers", []):
            text += f"   • {example}\n"
        text += "\n"

        # Вопрос 3
        q3 = question_data.get("question_3", {})
        text += f"<b>3. {q3.get('text', '')}</b>\n"
        for var in q3.get("variables_to_predict", []):
            text += f"   • {var.get('name', '')}: {var.get('correct_answer', '')}\n"

        return text
