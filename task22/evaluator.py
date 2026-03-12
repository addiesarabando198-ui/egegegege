"""AI-проверка для задания 22."""

import logging
import re
from typing import Dict, List, Any, Optional
from core.types import (
    TaskRequirements,
    EvaluationResult,
)

logger = logging.getLogger(__name__)

# Импорт калибровочных few-shot примеров
try:
    from core.fewshot_calibration import get_full_calibration_prompt
except ImportError:
    def get_full_calibration_prompt(task_number: int) -> str:
        return ""

# Безопасный импорт
try:
    from core.ai_evaluator import BaseAIEvaluator
    from core.ai_service import create_ai_service, AIServiceConfig, AIModel
    AI_EVALUATOR_AVAILABLE = True
except ImportError as e:
    logger.warning(f"AI evaluator components not available: {e}")
    AI_EVALUATOR_AVAILABLE = False

    # Заглушки для работы без AI
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


class Task22AIEvaluator(BaseAIEvaluator if AI_EVALUATOR_AVAILABLE else object):
    """AI-проверщик для задания 22."""

    def __init__(self):
        if AI_EVALUATOR_AVAILABLE:
            requirements = TaskRequirements(
                task_number=22,
                task_name="Оценивание ответов на задания-задачи",
                max_score=4,
                criteria=[
                    {
                        "name": "К1",
                        "max_score": 4,
                        "description": "Правильность ответов (по 1 баллу за каждый правильный ответ)"
                    }
                ],
                description="Ответьте на четыре вопроса к описанной ситуации..."
            )
            super().__init__(requirements)
        else:
            self.requirements = TaskRequirements(
                task_number=22,
                task_name="Оценивание ответов на задания-задачи",
                max_score=4,
                criteria=[{"name": "К1", "max_score": 4, "description": "Правильность ответов"}],
                description="Ответьте на четыре вопроса к описанной ситуации..."
            )

        # Инициализируем сервис если доступен
        self.ai_service = None
        if AI_EVALUATOR_AVAILABLE:
            try:
                config = AIServiceConfig.from_env()
                config.model = AIModel.LITE  # Sonnet достаточен для задания 22
                config.temperature = 0.2  # Низкая температура для строгой проверки
                self.config = config
                logger.info("Task22 AI evaluator configured")
            except Exception as e:
                logger.error(f"Failed to configure AI service: {e}")
                self.config = None

    def get_system_prompt(self) -> str:
        """Системный промпт для AI."""
        return """Ты - опытный эксперт ЕГЭ по обществознанию, специализирующийся на проверке задания 22.

ВАЖНЫЕ ПРАВИЛА ДЛЯ ЗАДАНИЯ 22:

1. Задание 22 представляет собой задание-задачу. Оно содержит условие (описание конкретной ситуации) и четыре вопроса (требования).
2. Это задание базового уровня сложности. Оно требует применения усвоенных знаний для комплексного анализа конкретной ситуации.
3. За полное и правильное выполнение задания выставляется 4 балла. При неполном правильном ответе – 3, 2 или 1 балл.

КРИТЕРИИ ОЦЕНИВАНИЯ:
- 4 балла: правильно даны ответы на четыре вопроса
- 3 балла: правильно даны ответы на любые три вопроса
- 2 балла: правильно даны ответы на любые два вопроса
- 1 балл: правильно дан ответ на любой один вопрос
- 0 баллов: приведены рассуждения общего характера, не соответствующие требованию задания, ИЛИ ответ неправильный

ВАЖНЫЕ МОМЕНТЫ:

1. Полный правильный ответ на тот или иной вопрос предполагает указание определённого количества позиций (см. пример 5, второй вопрос) при отсутствии неверных позиций. Действует тот же принцип, что и при оценивании ответов на задания 17.

2. При оценивании ряда вопросов (см. пример 5, первый вопрос; пример 6, первый, третий и четвёртый вопросы) требуется наличие правильного однозначного ответа.

3. Если в задаче один из вопросов предполагает указание какого-то родового понятия, а следующий вопрос содержит требование назвать другие объекты, относящиеся к этому виду, то наличие правильного ответа на предыдущий вопрос является необходимым условием для засчитывания ответа на последующий вопрос (см. Пример 5, второй вопрос).

ПРОВЕРКА ОТВЕТОВ:

- Внимательно читай каждый ответ ученика
- Сравнивай с правильными ответами и требованиями к ответу
- Учитывай допустимые формулировки (ответ не обязан быть дословным)
- Проверяй связанность вопросов (если есть зависимость)
- Не засчитывай ответы с фактическими ошибками
- Не засчитывай общие рассуждения без конкретного ответа

При проверке:
- Будь строг, но справедлив
- Давай конкретные комментарии к каждому ответу
- Для каждого неправильного ответа объясни, почему он не засчитан
- Предложи, как можно улучшить ответ

""" + get_full_calibration_prompt(22) + """
"""

    async def evaluate(
        self,
        answer: str,
        task_data: Dict[str, Any],
        **kwargs
    ) -> EvaluationResult:
        """Оценка ответа через AI."""

        # Если AI недоступен, используем базовую оценку
        if not AI_EVALUATOR_AVAILABLE or not self.config:
            return self._basic_evaluation(answer, task_data)

        # Парсим ответы пользователя (ожидаем нумерованный список)
        user_answers = self._parse_user_answers(answer)

        # Формируем промпт для проверки
        evaluation_prompt = self._build_evaluation_prompt(
            task_data, user_answers, answer
        )

        try:
            # Используем сервис AI
            async with create_ai_service(self.config) as service:
                result = await service.get_json_completion(
                    prompt=evaluation_prompt,
                    system_prompt=self.get_system_prompt(),
                    temperature=self.config.temperature
                )

                if result:
                    return self._parse_response(result, task_data, user_answers)
                else:
                    logger.error("Failed to get JSON response from AI")
                    return self._basic_evaluation(answer, task_data)

        except Exception as e:
            logger.error(f"Error in Task22 evaluation: {e}")
            return self._basic_evaluation(answer, task_data)

    def _parse_user_answers(self, answer: str) -> List[str]:
        """Парсинг ответов пользователя из нумерованного списка."""
        answers = []

        # Ищем нумерованные ответы (1., 2., 3., 4. или 1), 2), 3), 4))
        pattern = r'^\s*(\d+)[.)]\s*(.+?)(?=^\s*\d+[.)]|\Z)'
        matches = re.finditer(pattern, answer, re.MULTILINE | re.DOTALL)

        for match in matches:
            answer_text = match.group(2).strip()
            answers.append(answer_text)

        # Если не нашли нумерацию, пробуем разделить по переносам строк
        if len(answers) == 0:
            lines = [line.strip() for line in answer.split('\n') if line.strip()]
            answers = lines[:4]  # Берем первые 4 строки

        return answers

    def _build_evaluation_prompt(
        self,
        task_data: Dict[str, Any],
        user_answers: List[str],
        full_answer: str
    ) -> str:
        """Формирование промпта для проверки."""

        description = task_data.get('description', '')
        questions = task_data.get('questions', [])
        correct_answers = task_data.get('correct_answers', [])
        answer_requirements = task_data.get('answer_requirements', [])
        connected_questions = task_data.get('connected_questions', [])

        prompt = f"""Проверь ответ на задание 22 ЕГЭ.

ОПИСАНИЕ СИТУАЦИИ:
{description}

ВОПРОСЫ И ПРАВИЛЬНЫЕ ОТВЕТЫ:
"""

        for i, (question, correct_answer, requirement) in enumerate(zip(questions, correct_answers, answer_requirements), 1):
            prompt += f"""
{i}. Вопрос: {question}
   Правильный ответ: {correct_answer}
   Требование: {requirement}
"""

        if connected_questions:
            prompt += "\n\nСВЯЗАННЫЕ ВОПРОСЫ:\n"
            for conn in connected_questions:
                prompt += f"- Вопрос {conn['dependent']} зависит от вопроса {conn['requires']}: {conn['description']}\n"

        prompt += f"""

ОТВЕТЫ УЧЕНИКА:
{full_answer}

РАСПОЗНАННЫЕ ОТВЕТЫ НА ВОПРОСЫ:
"""

        for i, ans in enumerate(user_answers, 1):
            prompt += f"{i}. {ans}\n"

        prompt += """

ПОШАГОВЫЙ АЛГОРИТМ:
1. Проверь каждый ответ ученика на соответствие правильному ответу
2. Учитывай требования к каждому ответу
3. Проверь связанные вопросы (если есть зависимость между вопросами)
4. Посчитай количество правильных ответов
5. Выстав балл: 4 правильных = 4 балла, 3 правильных = 3 балла, и т.д.

Ответь в формате JSON:
```json
{
    "score": число от 0 до 4,
    "correct_answers_count": количество правильных ответов,
    "answers_evaluation": [
        {
            "question_number": номер вопроса,
            "user_answer": "ответ ученика",
            "is_correct": true/false,
            "comment": "почему засчитан или не засчитан",
            "penalty_reason": "причина штрафа" или null
        }
    ],
    "feedback": "общий комментарий (2-3 предложения)",
    "suggestions": ["конкретная рекомендация по улучшению", "ещё одна рекомендация"],
    "factual_errors": ["ошибка 1", "ошибка 2"] или []
}
```

ВАЖНО: Верни ТОЛЬКО валидный JSON в блоке кода, без дополнительного текста."""

        return prompt

    def _basic_evaluation(self, answer: str, task_data: Dict[str, Any]) -> EvaluationResult:
        """Базовая оценка без AI."""
        user_answers = self._parse_user_answers(answer)
        answers_count = len(user_answers)
        score = min(answers_count, 4)

        return EvaluationResult(
            criteria_scores={"К1": score},
            total_score=score,
            max_score=4,
            feedback=f"Обнаружено ответов: {answers_count}. Для точной проверки требуется AI-сервис.",
            detailed_feedback={
                "answers_count": answers_count,
                "score": score,
                "note": "Базовая проверка без AI"
            },
            suggestions=[
                "Убедитесь, что ответили на все 4 вопроса",
                "Используйте нумерованный список для ответов",
                "Давайте конкретные ответы, а не общие рассуждения"
            ],
            factual_errors=[]
        )

    def _parse_response(
        self,
        response: Dict[str, Any],
        task_data: Dict[str, Any],
        user_answers: List[str]
    ) -> EvaluationResult:
        """Парсинг ответа от AI."""
        try:
            score = response.get("score", 0)
            correct_count = response.get("correct_answers_count", 0)

            # Формируем обратную связь
            feedback = response.get("feedback", "")
            feedback += f"\n\n<b>Результат:</b> {correct_count} из 4 ответов правильны. Балл: {score}/4\n"

            # Добавляем оценку каждого ответа
            if response.get("answers_evaluation"):
                feedback += "\n<b>Проверка ответов:</b>\n"
                for eval_item in response["answers_evaluation"]:
                    q_num = eval_item.get("question_number", 0)
                    is_correct = eval_item.get("is_correct", False)
                    comment = eval_item.get("comment", "")

                    icon = "✅" if is_correct else "❌"
                    feedback += f"{icon} <b>Вопрос {q_num}:</b> {comment}\n"

                    if eval_item.get("penalty_reason"):
                        feedback += f"   ⚠️ {eval_item['penalty_reason']}\n"

            return EvaluationResult(
                criteria_scores={"К1": score},
                total_score=score,
                max_score=4,
                feedback=feedback,
                detailed_feedback=response,
                suggestions=response.get("suggestions", []),
                factual_errors=response.get("factual_errors", [])
            )

        except Exception as e:
            logger.error(f"Error parsing AI response: {e}")
            return self._basic_evaluation("", task_data)
