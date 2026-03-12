import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from core.ai_service import get_ai_service
from core.types import EvaluationResult, TaskRequirements, EvaluationCriteria

logger = logging.getLogger(__name__)


class BaseAIEvaluator(ABC):
    """Базовый класс для AI-оценщиков заданий ЕГЭ"""
    
    def __init__(self, requirements: TaskRequirements):
        self.requirements = requirements
        self.ai_service = get_ai_service()
    
    @abstractmethod
    async def evaluate(self, answer: str, topic: str, **kwargs) -> EvaluationResult:
        """Основной метод проверки ответа"""
        pass
    
    @abstractmethod
    def get_system_prompt(self) -> str:
        """Системный промпт для конкретного задания"""
        pass
    
    async def check_factual_accuracy(self, answer: str, topic: str) -> List[Dict[str, str]]:
        """Универсальная проверка фактических ошибок"""
        system_prompt = f"""Ты - эксперт ЕГЭ по обществознанию, проверяющий задание {self.requirements.task_number}.
Твоя задача - найти фактические ошибки в ответе ученика."""

        prompt = f"""Тема: "{topic}"
Ответ ученика:
{answer}

Найди ВСЕ фактические ошибки. Для каждой ошибки укажи:
- error: неправильная формулировка
- correction: правильный вариант  
- explanation: краткое объяснение

Если ошибок нет, верни пустой список []."""

        result = await self.ai_service.get_json_completion(
            prompt, 
            system_prompt=system_prompt,
            temperature=0.1
        )
        
        return result if isinstance(result, list) else []
    
    async def generate_feedback(
        self, 
        answer: str, 
        scores: Dict[str, int],
        issues: List[str]
    ) -> str:
        """Генерация персонализированной обратной связи"""
        total = sum(scores.values())
        max_total = self.requirements.max_score
        
        system_prompt = """Ты - доброжелательный преподаватель обществознания.
Дай краткую, но полезную обратную связь. Используй эмодзи для наглядности."""

        issues_text = "\n".join([f"- {issue}" for issue in issues]) if issues else "Нет"
        
        prompt = f"""Задание {self.requirements.task_number} ({self.requirements.task_name})
Оценка: {total}/{max_total} баллов

Основные проблемы:
{issues_text}

Напиши обратную связь (2-3 предложения):
1. Что хорошо
2. Главная проблема (если есть)
3. Конкретный совет"""

        result = await self.ai_service.get_completion(
            prompt,
            system_prompt=system_prompt,
            temperature=0.7
        )
        
        return result["text"] if result["success"] else ""
    
    def format_criteria_prompt(self) -> str:
        """Форматирование критериев для промпта"""
        criteria_text = []
        for criterion in self.requirements.criteria:
            # Теперь criterion это EvaluationCriteria (dataclass), обращаемся к атрибутам
            name = criterion.name
            max_score = criterion.max_score
            description = criterion.description
            criteria_text.append(f"{name} (макс. {max_score} балла): {description}")

        return "\n".join(criteria_text)


# Задание 19: Примеры
class Task19Evaluator(BaseAIEvaluator):
    """Проверка задания 19 - примеры социальных объектов"""
    
    def __init__(self):
        requirements = TaskRequirements(
            task_number=19,
            task_name="Примеры социальных объектов",
            max_score=3,
            criteria=[
                EvaluationCriteria(
                    code="К1",
                    name="К1",
                    max_score=3,
                    description="Правильность примеров (по 1 баллу за каждый корректный пример)"
                )
            ],
            description="Приведите три примера, иллюстрирующих..."
        )
        super().__init__(requirements)
    
    def get_system_prompt(self) -> str:
        return """Ты - эксперт ЕГЭ по обществознанию, специализирующийся на проверке задания 19.
Задание 19 требует привести три примера, иллюстрирующих определенное положение или понятие.
Каждый пример должен быть конкретным, соответствовать теме и раскрывать суть явления."""
    
    async def evaluate(self, answer: str, topic: str, **kwargs) -> EvaluationResult:
        # Основная проверка через AI
        evaluation_prompt = f"""Проверь ответ на задание 19 по теме: "{topic}"

Ответ ученика:
{answer}

Критерии оценки:
{self.format_criteria_prompt()}

Оцени каждый пример:
1. Соответствует ли теме (is_relevant: true/false)
2. Конкретен ли пример (is_specific: true/false)
3. Правильно ли раскрывает суть (is_correct: true/false)
4. Описание проблемы, если есть (issue: строка или null)

Формат ответа:
{{
    "examples_analysis": [
        {{"example_num": 1, "is_relevant": true, "is_specific": true, "is_correct": true, "issue": null}},
        ...
    ],
    "valid_examples_count": число,
    "score": число от 0 до 3,
    "main_issues": ["список основных проблем"],
    "suggestions": ["список рекомендаций"]
}}"""

        async with self.ai_service:
            result = await self.ai_service.get_json_completion(
                evaluation_prompt,
                system_prompt=self.get_system_prompt(),
                temperature=0.2
            )

            if not result:
                # Fallback оценка
                return EvaluationResult(
                    criteria_scores={"К1": 1},
                    total_score=1,
                    max_score=3,
                    feedback="Не удалось полностью проверить ответ. Требуется проверка преподавателем.",
                    detailed_feedback={},
                    suggestions=[],
                    factual_errors=[]
                )

            # Проверка фактических ошибок
            factual_errors = await self.check_factual_accuracy(answer, topic)

            # Генерация обратной связи
            feedback = await self.generate_feedback(
                answer,
                {"К1": result.get("score", 0)},
                result.get("main_issues", [])
            )
            return EvaluationResult(
                criteria_scores={"К1": result.get("score", 0)},
                total_score=result.get("score", 0),
                max_score=3,
                feedback=feedback,
                detailed_feedback=result,
                suggestions=result.get("suggestions", []),
                factual_errors=factual_errors
            )


# Задание 20: Формулирование суждений
class Task20Evaluator(BaseAIEvaluator):
    """Проверка задания 20 - формулирование суждений"""
    
    def __init__(self):
        requirements = TaskRequirements(
            task_number=20,
            task_name="Формулирование суждений",
            max_score=3,
            criteria=[
                EvaluationCriteria(
                    code="К1",
                    name="К1",
                    max_score=3,
                    description="Корректность суждений (по 1 баллу за каждое)"
                )
            ],
            description="Сформулируйте три суждения о..."
        )
        super().__init__(requirements)
    
    def get_system_prompt(self) -> str:
        return """Ты - эксперт ЕГЭ по обществознанию, специализирующийся на проверке задания 20.
Задание 20 требует сформулировать три суждения, раскрывающих различные аспекты темы.
Суждения должны быть корректными с точки зрения обществознания, логичными и содержательными."""
    
    async def evaluate(self, answer: str, topic: str, **kwargs) -> EvaluationResult:
        evaluation_prompt = f"""Проверь ответ на задание 20 по теме: "{topic}"

Ответ ученика:
{answer}

Оцени каждое суждение:
1. Корректность с точки зрения обществознания
2. Логичность и непротиворечивость
3. Содержательность (не банальность)
4. Соответствие теме

Формат ответа:
{{
    "statements_analysis": [
        {{
            "statement_num": 1,
            "is_correct": true,
            "is_logical": true,
            "is_meaningful": true,
            "is_relevant": true,
            "issue": null
        }},
        ...
    ],
    "valid_statements_count": число,
    "score": число от 0 до 3,
    "main_issues": ["список проблем"],
    "suggestions": ["рекомендации"]
}}"""

        async with self.ai_service:
            result = await self.ai_service.get_json_completion(
                evaluation_prompt,
                system_prompt=self.get_system_prompt(),
                temperature=0.2
            )

            if not result:
                return self._get_fallback_result()

            factual_errors = await self.check_factual_accuracy(answer, topic)
            feedback = await self.generate_feedback(
                answer,
                {"К1": result.get("score", 0)},
                result.get("main_issues", [])
            )

            return EvaluationResult(
                criteria_scores={"К1": result.get("score", 0)},
                total_score=result.get("score", 0),
                max_score=3,
                feedback=feedback,
                detailed_feedback=result,
                suggestions=result.get("suggestions", []),
                factual_errors=factual_errors
            )
    
    def _get_fallback_result(self) -> EvaluationResult:
        return EvaluationResult(
            criteria_scores={"К1": 1},
            total_score=1,
            max_score=3,
            feedback="Требуется дополнительная проверка преподавателем.",
            detailed_feedback={},
            suggestions=["Убедитесь, что каждое суждение раскрывает отдельный аспект темы"],
            factual_errors=[]
        )


# Задание 25: Обоснование и примеры
class Task25Evaluator(BaseAIEvaluator):
    """Проверка задания 25 - обоснование и примеры"""
    
    def __init__(self):
        requirements = TaskRequirements(
            task_number=25,
            task_name="Обоснование и примеры",
            max_score=6,
            criteria=[
                EvaluationCriteria(
                    code="К1",
                    name="К1",
                    max_score=2,
                    description="Обоснование (объяснение, аргументация)"
                ),
                EvaluationCriteria(
                    code="К2",
                    name="К2",
                    max_score=4,
                    description="Примеры из различных источников (до 2 баллов за каждый)"
                )
            ],
            description="Обоснуйте необходимость... Приведите три примера..."
        )
        super().__init__(requirements)
    
    def get_system_prompt(self) -> str:
        return """Ты - эксперт ЕГЭ по обществознанию, специализирующийся на проверке задания 25.
Это самое сложное задание ЕГЭ. Оно требует:
1. Обоснование (теоретическое объяснение)
2. Три примера из РАЗНЫХ источников (история, литература, СМИ, личный опыт и т.д.)
Каждый пример должен четко иллюстрировать обоснование."""
    
    async def evaluate(self, answer: str, topic: str, **kwargs) -> EvaluationResult:
        evaluation_prompt = f"""Проверь ответ на задание 25 по теме: "{topic}"

Ответ ученика:
{answer}

Критерии оценки:
{self.format_criteria_prompt()}

Проверь:
1. ОБОСНОВАНИЕ:
   - Есть ли теоретическое объяснение (has_theory: true/false)
   - Корректно ли оно (is_correct: true/false)
   - Полнота раскрытия (completeness: 0.0-1.0)

2. ПРИМЕРЫ (для каждого):
   - Источник примера (source: "история"/"литература"/"СМИ"/"личный опыт"/"другое")
   - Соответствует ли обоснованию (matches_theory: true/false)
   - Конкретность (is_specific: true/false)
   - Корректность (is_correct: true/false)

Формат ответа:
{{
    "justification_analysis": {{
        "has_theory": true,
        "is_correct": true,
        "completeness": 0.8,
        "issues": []
    }},
    "examples_analysis": [
        {{
            "example_num": 1,
            "source": "история",
            "matches_theory": true,
            "is_specific": true,
            "is_correct": true,
            "issue": null
        }},
        ...
    ],
    "unique_sources_count": число,
    "k1_score": число от 0 до 2,
    "k2_score": число от 0 до 4,
    "total_score": число от 0 до 6,
    "main_issues": ["список проблем"],
    "suggestions": ["рекомендации"]
}}"""

        async with self.ai_service:
            result = await self.ai_service.get_json_completion(
                evaluation_prompt,
                system_prompt=self.get_system_prompt(),
                temperature=0.2
            )

            if not result:
                return self._get_fallback_result()

            scores = {
                "К1": result.get("k1_score", 0),
                "К2": result.get("k2_score", 0)
            }

            factual_errors = await self.check_factual_accuracy(answer, topic)
            feedback = await self.generate_feedback(answer, scores, result.get("main_issues", []))

            return EvaluationResult(
                criteria_scores=scores,
                total_score=result.get("total_score", 0),
                max_score=6,
                feedback=feedback,
                detailed_feedback=result,
                suggestions=result.get("suggestions", []),
                factual_errors=factual_errors
            )

    def _get_fallback_result(self) -> EvaluationResult:
        return EvaluationResult(
            criteria_scores={"К1": 1, "К2": 2},
            total_score=3,
            max_score=6,
            feedback="Требуется дополнительная проверка.",
            detailed_feedback={},
            suggestions=["Убедитесь, что примеры из разных источников"],
            factual_errors=[]
        )