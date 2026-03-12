"""
core/base_evaluator.py
Базовый класс для унификации AI evaluator'ов заданий 19, 20, 25.
"""

import os
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from enum import Enum

from core.ai_service import create_ai_service, AIServiceConfig, AIModel
from core.types import EvaluationResult, EvaluationCriteria, TaskRequirements

logger = logging.getLogger(__name__)


class StrictnessLevel(Enum):
    """Уровни строгости проверки."""
    LENIENT = "Мягкий"
    STANDARD = "Стандартный"
    STRICT = "Строгий"
    EXPERT = "Экспертный"


class BaseAIEvaluator(ABC):
    """Базовый класс для AI проверщиков заданий."""
    
    def __init__(self, requirements: TaskRequirements, strictness: StrictnessLevel = StrictnessLevel.STANDARD):
        self.requirements = requirements
        self.strictness = strictness
        self.ai_service = None
        self._init_ai_service()

    def _init_ai_service(self):
        """Инициализация AI сервиса."""
        try:
            config = AIServiceConfig.from_env()
            config.model = AIModel.PRO
            config.temperature = self._get_temperature()
            config.max_tokens = 3000

            self.ai_service = create_ai_service(config)
            logger.info(
                f"{self.requirements.task_name} AI service initialized "
                f"with {self.strictness.value} strictness"
            )
            
        except Exception as e:
            logger.error(f"Failed to initialize AI service: {e}")
            self.ai_service = None
    
    def _get_temperature(self) -> float:
        """Возвращает температуру для AI в зависимости от строгости."""
        temperature_map = {
            StrictnessLevel.LENIENT: 0.4,
            StrictnessLevel.STANDARD: 0.3,
            StrictnessLevel.STRICT: 0.2,
            StrictnessLevel.EXPERT: 0.1
        }
        return temperature_map.get(self.strictness, 0.3)
    
    def get_system_prompt(self) -> str:
        """Формирует системный промпт с учетом строгости."""
        base_prompt = f"""Ты опытный эксперт ЕГЭ по обществознанию, проверяющий задание {self.requirements.task_number}.

КРИТЕРИИ ОЦЕНИВАНИЯ:
"""
        # Добавляем критерии
        for criterion in self.requirements.criteria:
            base_prompt += f"\n{criterion.code}. {criterion.name} (макс. {criterion.max_score} балла)"
            base_prompt += f"\n   {criterion.description}\n"
        
        # Добавляем инструкции по строгости
        if self.strictness == StrictnessLevel.LENIENT:
            base_prompt += "\nПрименяй МЯГКИЕ критерии. Засчитывай частично правильные ответы."
        elif self.strictness == StrictnessLevel.STANDARD:
            base_prompt += "\nПрименяй СТАНДАРТНЫЕ критерии ФИПИ."
        elif self.strictness == StrictnessLevel.STRICT:
            base_prompt += "\nПрименяй СТРОГИЕ критерии. Требуй полного соответствия."
        elif self.strictness == StrictnessLevel.EXPERT:
            base_prompt += "\nМАКСИМАЛЬНАЯ строгость. Любые неточности снижают балл."
        
        # Общие инструкции
        base_prompt += """

ВАЖНЫЕ ПРАВИЛА:
1. Оценивай ТОЛЬКО по критериям ЕГЭ
2. Указывай конкретные ошибки и недочеты
3. Давай развернутую обратную связь
4. Будь объективным и справедливым

Отвечай ВСЕГДА в формате JSON:
{
    "criteria_scores": {"К1": X, "К2": Y, ...},
    "total_score": Z,
    "feedback": "общий комментарий",
    "detailed_feedback": {
        "К1": "детальный разбор по критерию",
        "К2": "детальный разбор по критерию"
    },
    "errors": ["список конкретных ошибок"],
    "suggestions": ["рекомендации по улучшению"]
}"""
        
        return base_prompt
    
    @abstractmethod
    def _build_evaluation_prompt(self, answer: str, task_data: Dict[str, Any]) -> str:
        """Строит промпт для оценки конкретного задания."""
        pass
    
    async def evaluate(
        self, 
        answer: str, 
        task_data: Dict[str, Any],
        user_id: Optional[int] = None
    ) -> EvaluationResult:
        """Оценивает ответ ученика."""
        if not self.ai_service:
            return self._get_fallback_result()
        
        try:
            # Формируем промпт для оценки
            eval_prompt = self._build_evaluation_prompt(answer, task_data)
            
            # Используем AI сервис
            async with self.ai_service as service:
                result = await service.get_json_completion(
                    prompt=eval_prompt,
                    system_prompt=self.get_system_prompt()
                )
            
            if not result:
                logger.error("AI service returned None")
                return self._get_fallback_result()
            
            # Валидируем и формируем результат
            return self._create_evaluation_result(result, task_data)
            
        except Exception as e:
            logger.error(f"Error during AI evaluation: {e}", exc_info=True)
            return self._get_fallback_result()
    
    def _create_evaluation_result(self, ai_response: Dict[str, Any], task_data: Dict[str, Any]) -> EvaluationResult:
        """Создает результат оценки из ответа AI."""
        criteria_scores = ai_response.get('criteria_scores', {})
        
        # Валидируем баллы по критериям
        validated_scores = {}
        for criterion in self.requirements.criteria:
            score = criteria_scores.get(criterion.code, 0)
            # Ограничиваем максимальным баллом
            validated_scores[criterion.code] = min(max(0, int(score)), criterion.max_score)
        
        total_score = sum(validated_scores.values())
        
        return EvaluationResult(
            total_score=total_score,
            max_score=self.requirements.max_score,
            criteria_scores=validated_scores,
            feedback=ai_response.get('feedback', 'Оценка выполнена'),
            detailed_feedback=ai_response.get('detailed_feedback', {}),
            warnings=ai_response.get('errors', []),
            suggestions=ai_response.get('suggestions', [])
        )
    
    def _get_fallback_result(self) -> EvaluationResult:
        """Возвращает результат когда AI недоступен."""
        return EvaluationResult(
            total_score=0,
            max_score=self.requirements.max_score,
            criteria_scores={c.code: 0 for c in self.requirements.criteria},
            feedback="AI сервис временно недоступен. Обратитесь к преподавателю для проверки.",
            warnings=["Автоматическая проверка недоступна"]
        )
    
    def validate_answer_structure(self, answer: str, requirements: Dict[str, Any]) -> Dict[str, bool]:
        """Базовая валидация структуры ответа."""
        validations = {}
        
        # Проверка минимальной длины
        min_length = requirements.get('min_length', 50)
        validations['has_min_length'] = len(answer.split()) >= min_length
        
        # Проверка на наличие абзацев
        validations['has_paragraphs'] = '\n' in answer.strip()
        
        # Проверка на нумерацию (если требуется)
        if requirements.get('requires_numbering', False):
            validations['has_numbering'] = any(
                line.strip().startswith(('1', '2', '3', 'а)', 'б)', 'в)', '-'))
                for line in answer.split('\n')
            )
        
        return validations