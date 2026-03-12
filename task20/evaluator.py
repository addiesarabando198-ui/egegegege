"""AI-проверка для задания 20."""

import logging
import os
import json
from typing import Dict, List, Any, Optional
from core.types import (
    UserID,
    TaskType,
    EvaluationResult,
    CallbackData,
    TaskRequirements,
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
    from core.ai_evaluator import (
        BaseAIEvaluator,
    )
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


class Task20AIEvaluator(BaseAIEvaluator if AI_EVALUATOR_AVAILABLE else object):
    """AI-проверщик для задания 20."""

    def __init__(self):
        if AI_EVALUATOR_AVAILABLE:
            requirements = TaskRequirements(
                task_number=20,
                task_name="Формулирование суждений",
                max_score=3,
                criteria=[
                    {
                        "name": "К1",
                        "max_score": 3,
                        "description": "Корректность суждений (по 1 баллу за каждое)"
                    }
                ],
                description="Сформулируйте три суждения..."
            )
            super().__init__(requirements)
        else:
            self.requirements = TaskRequirements(
                task_number=20,
                task_name="Формулирование суждений",
                max_score=3,
                criteria=[{"name": "К1", "max_score": 3, "description": "Корректность суждений"}],
                description="Сформулируйте три суждения..."
            )

        # Инициализируем сервис если доступен
        self.ai_service = None
        if AI_EVALUATOR_AVAILABLE:
            try:
                config = AIServiceConfig.from_env()
                config.model = AIModel.LITE
                config.temperature = 0.2
                self.config = config
                logger.info("Task20 AI evaluator configured")
            except Exception as e:
                logger.error(f"Failed to configure AI service: {e}")
                self.config = None
    
    def get_system_prompt(self) -> str:
        """Системный промпт для AI."""
        base_prompt = """Ты - опытный эксперт ЕГЭ по обществознанию, специализирующийся на проверке задания 20.

ВАЖНЫЕ ПРАВИЛА ДЛЯ ЗАДАНИЯ 20:
1. В отличие от задания 19, здесь НЕ нужны конкретные примеры
2. Требуются суждения АБСТРАКТНОГО характера с элементами обобщения
3. Суждения должны быть более широкого объёма и менее конкретного содержания
4. Каждое суждение должно быть сформулировано как распространённое предложение
5. Суждения должны содержать элементы обобщения

КРИТЕРИИ ОЦЕНИВАНИЯ:
- 3 балла: приведены все требуемые суждения правильного типа
- 2 балла: приведено на одно суждение меньше требуемого
- 1 балл: приведено на два суждения меньше требуемого  
- 0 баллов: приведен только один аргумент ИЛИ рассуждения общего характера

ШТРАФЫ:
- Если наряду с требуемыми суждениями есть 2+ дополнительных с ошибками → 0 баллов
- Если есть 1 дополнительное с ошибкой → минус 1 балл от фактического

ЧТО СЧИТАЕТСЯ ПРАВИЛЬНЫМ СУЖДЕНИЕМ ДЛЯ ЗАДАНИЯ 20:
- Содержит элементы обобщения (способствует, приводит к, влияет на, обеспечивает, позволяет, создает, формирует, развивает, препятствует, ограничивает, снижает, повышает, улучшает, ухудшает, определяет, зависит от)
- НЕ содержит конкретных примеров (дат, имён, названий конкретных стран/организаций/компаний)
- Является распространённым предложением (не менее 5 слов)
- Соответствует требованию задания
- Содержит причинно-следственные связи

ЧТО НЕ ЗАСЧИТЫВАЕТСЯ:
- Конкретные примеры (например: "В 2020 году в России...", "Компания Apple...", "Во Франции...")
- Упоминание конкретных личностей, дат, событий
- Слишком конкретное содержание без обобщения
- Отдельные слова и словосочетания
- Общие рассуждения без чёткой аргументации
- Суждения, не соответствующие типу (например, негативный вместо позитивного)

ПРАВИЛО ДУБЛИРУЮЩИХ СУЖДЕНИЙ:
Если два или более суждения по сути ДУБЛИРУЮТ или ДОПОЛНЯЮТ друг друга
(раскрывают один и тот же аспект темы с разных сторон), они считаются
как ОДИН элемент ответа, а не два.

Алгоритм проверки на дубли:
1. После оценки каждого суждения по отдельности, сравни ВСЕ пары суждений
2. Если два суждения объясняют одно и то же явление — это дубль
3. Если одно суждение является частным случаем другого — это дубль
4. Засчитай дублирующие суждения как ОДНО

Пример дубля:
- «Налоги позволяют финансировать социальные программы» и
  «Благодаря налогам государство обеспечивает выплату пенсий и пособий»
→ Оба суждения об одном (финансирование социальной сферы) → считаются как 1 элемент

Пример НЕ дубля:
- «Налоги позволяют финансировать социальные программы» и
  «Налоги выполняют регулирующую функцию, сдерживая потребление вредных товаров»
→ Разные аспекты (финансирование vs регулирование) → 2 отдельных элемента

В комментарии ОБЯЗАТЕЛЬНО укажи, если обнаружены дубли:
"Суждения [N] и [M] дублируют друг друга (оба о [тема]) → засчитаны как 1 элемент"

СВЯЗЬ С ТЕЗИСОМ — ОБЯЗАТЕЛЬНА!

Суждение должно быть ЛОГИЧЕСКИ СВЯЗАНО с тезисом, который нужно объяснить/аргументировать.

❌ НЕ засчитывается:
"Налоги важны для государства"
→ Это истинное суждение, но оно НЕ связано с конкретным тезисом задания

✅ Засчитывается:
"Чрезмерное перераспределение средств может снизить мотивацию к труду,
поскольку работники видят, что значительная часть их дохода изымается"
→ Суждение прямо связано с тезисом о рисках перераспределения

ПРОВЕРЯЙ: Отвечает ли суждение на вопрос задания или это просто
"правильная мысль на тему"?

ПРИНЦИП ТОЛКОВАНИЯ В ПОЛЬЗУ УЧЕНИКА:
В спорных и пограничных случаях, когда суждение можно трактовать и как верное,
и как неверное — трактуй В ПОЛЬЗУ ученика.
Снижай балл ТОЛЬКО при наличии явной, бесспорной ошибки.

НЕЗНАКОМЫЕ КЛАССИФИКАЦИИ И ТЕОРИИ:
Если ученик приводит классификацию, теорию или концепцию, которая тебе незнакома —
НЕ отвергай её автоматически. Она может существовать в учебниках ФПУ или научной литературе.
Снижай балл ТОЛЬКО если УВЕРЕН, что информация фактически ошибочна.

""" + get_full_calibration_prompt(20) + """

ВАЖНО: Будь строг в оценке, но справедлив. Учитывай российский контекст.

ВЧИТЫВАЙСЯ В ЛОГИКУ РАССУЖДЕНИЙ:

❌ НЕ проверяй по "ключевым фразам" или наличию терминов
❌ НЕ останавливайся на середине рассуждения

✅ Дочитывай каждое суждение до конца
✅ Оценивай логическую цепочку: посылка → аргумент → вывод
✅ Проверяй, есть ли причинно-следственная связь

При проверке:
- Будь лаконичен в комментариях
- Давай конкретные, практические советы
- Не используй общие фразы типа "нужно больше стараться"
- Для каждого неудачного суждения предложи, как его переформулировать"""

        return base_prompt
    
    async def evaluate(self, answer: str, topic: str, **kwargs) -> EvaluationResult:
        """Оценка ответа через AI."""
        task_text = kwargs.get('task_text', '')
        
        # Если AI недоступен, используем базовую оценку
        if not AI_EVALUATOR_AVAILABLE or not self.config:
            return self._basic_evaluation(answer, topic)
        
        # Формируем промпт для проверки
        evaluation_prompt = f"""Проверь ответ на задание 20 ЕГЭ.

ЗАДАНИЕ: {task_text}

ТЕМА: {topic}

ОТВЕТ УЧЕНИКА:
{answer}

ПОШАГОВЫЙ АЛГОРИТМ:
1. Определи, сколько всего суждений привёл ученик
2. Если больше 3 - проверь ВСЕ на ошибки (любая серьёзная ошибка = 0 баллов за всё)
3. Для каждого суждения оцени:
   - Абстрактность (нет конкретных примеров)
   - Наличие обобщения
   - Соответствие заданию
   - Логичность и корректность
   - Распространённость (не менее 5 слов)

УЧИТЫВАЙ:
- Суждения должны быть теоретическими
- НЕ должно быть конкретных дат, имён, названий
- Должны использоваться обобщающие конструкции

Ответь в формате JSON:
```json
{{
    "score": число от 0 до 3,
    "valid_arguments_count": количество засчитанных суждений,
    "total_arguments": общее количество суждений в ответе,
    "penalty_applied": true/false,
    "penalty_reason": "причина штрафа" или null,
    "valid_arguments": [
        {{
            "number": номер суждения,
            "text": "краткое описание сути суждения (до 50 слов)",
            "has_generalization": true/false,
            "comment": "почему засчитано"
        }}
    ],
    "invalid_arguments": [
        {{
            "number": номер суждения,
            "text": "краткое описание сути суждения (до 50 слов)",
            "reason": "конкретная причина, почему не засчитано",
            "is_concrete_example": true/false,
            "improvement": "конкретный совет, как исправить именно это суждение"
        }}
    ],
    "feedback": "краткий общий комментарий (2-3 предложения)",
    "suggestions": ["конкретная рекомендация по улучшению ответа", "ещё одна конкретная рекомендация"],
    "factual_errors": ["ошибка 1", "ошибка 2"] или []
}}
```

ВАЖНЫЕ ТРЕБОВАНИЯ К ОТВЕТУ:
1. В "feedback" пиши кратко, только самое важное
2. В "suggestions" давай КОНКРЕТНЫЕ советы, а не общие фразы
3. Для каждого незасчитанного суждения в "improvement" напиши, КАК ИМЕННО его улучшить
4. Не повторяй одни и те же фразы

ВАЖНО: Верни ТОЛЬКО валидный JSON в блоке кода, без дополнительного текста."""

        try:
            # Используем сервис AI
            async with create_ai_service(self.config) as service:
                result = await service.get_json_completion(
                    prompt=evaluation_prompt,
                    system_prompt=self.get_system_prompt(),
                    temperature=self.config.temperature
                )
                
                if result:
                    return self._parse_response(result, answer, topic)
                else:
                    logger.error("Failed to get JSON response from AI")
                    return self._basic_evaluation(answer, topic)
                    
        except Exception as e:
            logger.error(f"Error in Task20 evaluation: {e}")
            return self._basic_evaluation(answer, topic)
    
    def _basic_evaluation(self, answer: str, topic: str) -> EvaluationResult:
        """Базовая оценка без AI."""
        arguments = [arg.strip() for arg in answer.split('\n') if arg.strip()]
        score = min(len(arguments), 3) if len(arguments) <= 3 else 2
        
        # Проверяем на наличие конкретных примеров
        concrete_indicators = [
            'например', 'в 20', 'году', 'компания', 'страна',
            'россия', 'сша', 'китай', 'франция', 'германия'
        ]
        
        has_concrete = any(indicator in answer.lower() for indicator in concrete_indicators)
        if has_concrete and score > 0:
            score = max(0, score - 1)
        
        return EvaluationResult(
            criteria_scores={"К1": score},
            total_score=score,
            max_score=3,
            feedback=f"Обнаружено суждений: {len(arguments)}",
            detailed_feedback={  # Изменено: detailed_analysis -> detailed_feedback
                "arguments_count": len(arguments),
                "score": score,
                "has_concrete_examples": has_concrete
            },
            suggestions=[
                "Используйте больше обобщающих конструкций",
                "Избегайте конкретных примеров",
                "Формулируйте развёрнутые предложения"
            ],
            factual_errors=[]
        )
    
    def _parse_response(self, response: Dict[str, Any], answer: str, topic: str) -> EvaluationResult:
            """Парсинг ответа от AI."""
            try:
                score = response.get("score", 0)
                
                # Формируем краткую обратную связь
                feedback = response.get("feedback", "")
                
                # Добавляем информацию о засчитанных суждениях (кратко)
                if response.get("valid_arguments"):
                    feedback += f"\n\n✅ <b>Засчитанные суждения:</b>\n"
                    for i, arg in enumerate(response["valid_arguments"], 1):
                        feedback += f"{i}. {arg.get('comment', 'Суждение корректно')}\n"
                
                # Добавляем информацию о незасчитанных суждениях с конкретными советами
                if response.get("invalid_arguments"):
                    feedback += f"\n\n❌ <b>Не засчитанные суждения:</b>\n"
                    for arg in response["invalid_arguments"]:
                        feedback += f"{arg['number']}. {arg.get('reason', 'Не соответствует критериям')}\n"
                        if arg.get('improvement'):
                            feedback += f"   💡 <i>Совет: {arg['improvement']}</i>\n"
                
                # Добавляем информацию о штрафах (если есть)
                if response.get("penalty_applied"):
                    feedback += f"\n⚠️ <b>Применён штраф:</b> {response.get('penalty_reason', '')}"
                
                return EvaluationResult(
                    criteria_scores={"К1": score},
                    total_score=score,
                    max_score=3,
                    feedback=feedback,
                    detailed_feedback=response,  # Изменено: detailed_analysis -> detailed_feedback
                    suggestions=response.get("suggestions", []),
                    factual_errors=response.get("factual_errors", [])
                )
                
            except Exception as e:
                logger.error(f"Error parsing AI response: {e}")
                return self._basic_evaluation(answer, topic)