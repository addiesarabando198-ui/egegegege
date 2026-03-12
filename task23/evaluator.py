"""
AI-проверка для задания 23 (Конституция РФ).

Поддерживает два типа моделей вопросов:
- Model Type 1: Одна характеристика, три подтверждения
- Model Type 2: Три характеристики, по одному подтверждению каждой
"""

import logging
import json
import re
from typing import Dict, List, Any, Optional, Union
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
class AnswerEvaluation:
    """Результат оценки одного ответа."""
    is_correct: bool
    score: float
    feedback: str
    matched_model_answer: Optional[str] = None


class Task23Evaluator(BaseAIEvaluator if AI_EVALUATOR_AVAILABLE else object):
    """AI-проверщик для задания 23 (Конституция РФ)."""

    def __init__(self):
        if AI_EVALUATOR_AVAILABLE:
            requirements = TaskRequirements(
                task_number=23,
                task_name="Конституция Российской Федерации",
                max_score=3,
                criteria=[
                    {
                        "name": "К1",
                        "max_score": 3,
                        "description": "Правильность подтверждений (по 1 баллу за каждое)"
                    }
                ],
                description="Сформулируйте подтверждения характеристик на основе Конституции РФ"
            )
            super().__init__(requirements)
        else:
            self.requirements = TaskRequirements(
                task_number=23,
                task_name="Конституция Российской Федерации",
                max_score=3,
                criteria=[{"name": "К1", "max_score": 3, "description": "Правильность подтверждений"}],
                description="Сформулируйте подтверждения характеристик на основе Конституции РФ"
            )

        self.ai_service = None
        self.config = None

        if AI_EVALUATOR_AVAILABLE:
            try:
                config = AIServiceConfig.from_env()
                config.model = AIModel.PRO
                config.temperature = 0.2
                self.config = config
                logger.info("Task23 AI evaluator configured")
            except Exception as e:
                logger.error(f"Failed to configure AI service: {e}")
                self.config = None

    def get_system_prompt(self) -> str:
        """Системный промпт для AI."""
        return """Ты - опытный эксперт ЕГЭ по обществознанию, специализирующийся на проверке задания 23 (Конституция РФ).

ДВЕ МОДЕЛИ ЗАДАНИЯ 23:

МОДЕЛЬ 1: Дана одна характеристика государства → ученик должен привести три объяснения (подтверждения) этой характеристики.

МОДЕЛЬ 2: Даны три характеристики государства → ученик должен привести по одному подтверждению каждой характеристики.

ОФИЦИАЛЬНЫЕ КРИТЕРИИ ОЦЕНИВАНИЯ:

3 балла:
- На основе Конституции РФ приведены три объяснения
- БЕЗ дополнительных (сверх требуемых трёх) позиций, содержащих неточности/ошибки

2 балла:
- На основе Конституции РФ приведены только два объяснения
- БЕЗ дополнительных позиций, содержащих неточности/ошибки

1 балл:
- На основе Конституции РФ приведено только одно объяснение БЕЗ дополнительных позиций с неточностями/ошибками
- ИЛИ приведены два-три объяснения ПРИ НАЛИЧИИ дополнительных позиций, содержащих неточности/ошибки

0 баллов:
- Ни одно объяснение не приведено на основе Конституции РФ
- ИЛИ приведены рассуждения общего характера, не соответствующие требованию задания
- ИЛИ ответ неправильный

ТРЕБОВАНИЯ К ФОРМЕ ОТВЕТА:

✅ ЗАСЧИТЫВАЮТСЯ только объяснения/подтверждения:
- Сформулированные как РАСПРОСТРАНЁННЫЕ ПРЕДЛОЖЕНИЯ (не отдельные слова или словосочетания!)
- С опорой на КОНКРЕТНОЕ положение Конституции РФ

❌ НЕ ЗАСЧИТЫВАЮТСЯ:
- Отдельные слова и словосочетания (например, просто "идеологическое многообразие")
- Теоретически верные характеристики БЕЗ опоры на Конституцию РФ
- Характеристики с опорой на ИНЫЕ нормативные акты РФ (федеральные законы и т.д.), но НЕ на Конституцию
- Просто название характеристик из статьи 1 Конституции без пояснений учащегося
- Общие рассуждения без конкретики

✅ НЕ ТРЕБУЕТСЯ:
- Указание номеров соответствующих статей Конституции РФ
- Дословное воспроизведение содержания статей

✅ ВАЖНО:
- Засчитывай объяснения, которые соответствуют требованию задания, даже если они НЕ указаны в эталонных ответах
- Принимай синонимичные и перефразированные формулировки, если они передают смысл конституционного положения

При проверке:
- Будь строг к форме (требуй распространённые предложения)
- Проверяй опору именно на Конституцию РФ
- Учитывай наличие дополнительных позиций с ошибками при выставлении балла
- Давай конкретные комментарии к каждому подтверждению

""" + get_full_calibration_prompt(23) + """
"""

    async def evaluate(
        self,
        user_answer: str,
        question_data: Dict[str, Any],
        **kwargs
    ) -> EvaluationResult:
        """
        Оценка ответа пользователя.

        Args:
            user_answer: Ответ пользователя (текст)
            question_data: Данные вопроса из JSON

        Returns:
            EvaluationResult с оценкой и обратной связью
        """
        model_type = question_data.get('model_type', 1)

        if model_type == 1:
            return await self._evaluate_model1(user_answer, question_data)
        elif model_type == 2:
            return await self._evaluate_model2(user_answer, question_data)
        else:
            logger.error(f"Unknown model_type: {model_type}")
            return self._create_error_result("Неизвестный тип вопроса")

    async def _evaluate_model1(
        self,
        user_answer: str,
        question_data: Dict[str, Any]
    ) -> EvaluationResult:
        """
        Оценка ответа для Model Type 1.

        Дана ОДНА характеристика, нужно дать 3 подтверждения.
        Каждое правильное подтверждение = 1 балл.
        """
        characteristic = question_data.get('characteristics', [''])[0]
        model_answers = question_data.get('model_answers', [])

        # Парсим ответы пользователя
        user_answers = self._parse_user_answers(user_answer)

        if not AI_EVALUATOR_AVAILABLE or not self.config:
            return self._basic_evaluation_model1(user_answers, model_answers, characteristic)

        # Формируем промпт для AI оценки
        prompt = self._build_model1_prompt(
            characteristic, model_answers, user_answers, user_answer
        )

        try:
            async with create_ai_service(self.config) as service:
                result = await service.get_json_completion(
                    prompt=prompt,
                    system_prompt=self.get_system_prompt(),
                    temperature=self.config.temperature
                )

                if result:
                    return self._parse_model1_response(result, model_answers)
                else:
                    return self._basic_evaluation_model1(user_answers, model_answers, characteristic)

        except Exception as e:
            logger.error(f"Error in Task23 Model1 evaluation: {e}")
            return self._basic_evaluation_model1(user_answers, model_answers, characteristic)

    async def _evaluate_model2(
        self,
        user_answer: str,
        question_data: Dict[str, Any]
    ) -> EvaluationResult:
        """
        Оценка ответа для Model Type 2.

        Даны ТРИ характеристики, нужно дать по одному подтверждению каждой.
        Каждое правильное подтверждение = 1 балл.
        """
        characteristics = question_data.get('characteristics', [])
        model_answers = question_data.get('model_answers', {})

        # Парсим ответы пользователя
        user_answers = self._parse_user_answers(user_answer)

        if not AI_EVALUATOR_AVAILABLE or not self.config:
            return self._basic_evaluation_model2(
                user_answers, characteristics, model_answers
            )

        # Формируем промпт для AI оценки
        prompt = self._build_model2_prompt(
            characteristics, model_answers, user_answers, user_answer
        )

        try:
            async with create_ai_service(self.config) as service:
                result = await service.get_json_completion(
                    prompt=prompt,
                    system_prompt=self.get_system_prompt(),
                    temperature=self.config.temperature
                )

                if result:
                    return self._parse_model2_response(result, characteristics)
                else:
                    return self._basic_evaluation_model2(
                        user_answers, characteristics, model_answers
                    )

        except Exception as e:
            logger.error(f"Error in Task23 Model2 evaluation: {e}")
            return self._basic_evaluation_model2(
                user_answers, characteristics, model_answers
            )

    def _parse_user_answers(self, answer: str) -> List[str]:
        """Парсинг ответов пользователя из текста."""
        answers = []

        # Пробуем найти нумерованные ответы
        pattern = r'^\s*(\d+)[.)]\s*(.+?)(?=^\s*\d+[.)]|\Z)'
        matches = re.finditer(pattern, answer, re.MULTILINE | re.DOTALL)

        for match in matches:
            answer_text = match.group(2).strip()
            if answer_text:
                answers.append(answer_text)

        # Если не нашли нумерацию, разделяем по переносам строк
        if len(answers) == 0:
            lines = [line.strip() for line in answer.split('\n') if line.strip()]
            # Убираем возможные маркеры в начале строк
            for line in lines:
                clean_line = re.sub(r'^[-–—•]\s*', '', line).strip()
                if clean_line:
                    answers.append(clean_line)

        return answers[:3]  # Максимум 3 ответа

    def _build_model1_prompt(
        self,
        characteristic: str,
        model_answers: List[str],
        user_answers: List[str],
        full_answer: str
    ) -> str:
        """Формирование промпта для Model Type 1."""
        model_answers_text = "\n".join([f"  {i}. {ans}" for i, ans in enumerate(model_answers, 1)])
        user_answers_text = "\n".join([f"  {i}. {ans}" for i, ans in enumerate(user_answers, 1)])

        return f"""Проверь ответ на задание 23 ЕГЭ (Конституция РФ) - МОДЕЛЬ 1.

ТИП ЗАДАНИЯ: Дана ОДНА характеристика государства, ученик должен привести ТРИ объяснения (подтверждения) этой характеристики.

ХАРАКТЕРИСТИКА:
{characteristic}

ПРИМЕРЫ ЭТАЛОННЫХ ПОДТВЕРЖДЕНИЙ (это лишь ПРИМЕРЫ, а НЕ исчерпывающий список!):
{model_answers_text}

ОТВЕТ УЧЕНИКА (полный текст):
{full_answer}

РАСПОЗНАННЫЕ ПОДТВЕРЖДЕНИЯ:
{user_answers_text}

⚠️ ВАЖНЕЙШЕЕ ПРАВИЛО:
Ученик может привести подтверждения, которых НЕТ в эталонных примерах выше!
Такие подтверждения ДОЛЖНЫ быть засчитаны, если они:
- Опираются на положения Конституции РФ
- Раскрывают данную характеристику государства
- Фактически верны

НЕ сравнивай ответ ученика только с эталонными примерами - оценивай его по существу!

КРИТЕРИИ ПРОВЕРКИ КАЖДОГО ПОДТВЕРЖДЕНИЯ:

✅ ЗАСЧИТЫВАЕТСЯ подтверждение, если:
1. Сформулировано как РАСПРОСТРАНЁННОЕ ПРЕДЛОЖЕНИЕ (не отдельные слова/словосочетания!)
2. Опирается на КОНКРЕТНОЕ положение КОНСТИТУЦИИ РФ (не других законов!)
3. Раскрывает данную характеристику государства
4. Фактически верное
5. ДАЖЕ ЕСЛИ его нет в эталонных примерах!

❌ НЕ ЗАСЧИТЫВАЕТСЯ подтверждение, если:
1. Это просто слово или словосочетание (например, "идеологическое многообразие" без пояснения)
2. Опирается на федеральные законы или другие акты, а не на Конституцию РФ
3. Содержит фактическую ошибку
4. Это общее рассуждение без конкретики
5. Просто называет характеристику из ст.1 без пояснения

ПРАВИЛА ВЫСТАВЛЕНИЯ БАЛЛОВ:
- 3 балла: 3 верных подтверждения БЕЗ дополнительных позиций с ошибками
- 2 балла: 2 верных подтверждения БЕЗ дополнительных позиций с ошибками
- 1 балл: 1 верное подтверждение БЕЗ дополнительных ошибок ИЛИ 2-3 верных подтверждения ПРИ НАЛИЧИИ дополнительных позиций с ошибками
- 0 баллов: нет верных подтверждений / общие рассуждения / неправильный ответ

Ответь в формате JSON:
```json
{{
    "correct_count": количество засчитанных подтверждений (0-3),
    "has_additional_errors": true/false (есть ли дополнительные позиции с неточностями/ошибками),
    "score": итоговый балл с учётом правил (0-3),
    "answers_evaluation": [
        {{
            "number": номер подтверждения,
            "user_answer": "ответ ученика",
            "is_expanded_sentence": true/false (это распространённое предложение?),
            "is_based_on_constitution": true/false (опора на Конституцию РФ?),
            "is_correct": true/false (итоговое решение),
            "matched_model": "какому эталонному ответу соответствует (если есть совпадение)" или null,
            "comment": "почему засчитано/не засчитано - с обоснованием по Конституции РФ"
        }}
    ],
    "feedback": "общий комментарий (2-3 предложения)",
    "suggestions": ["рекомендация по улучшению"]
}}
```

ВАЖНО: Верни ТОЛЬКО валидный JSON."""

    def _build_model2_prompt(
        self,
        characteristics: List[str],
        model_answers: Dict[str, List[str]],
        user_answers: List[str],
        full_answer: str
    ) -> str:
        """Формирование промпта для Model Type 2."""
        chars_with_answers = ""
        for i, char in enumerate(characteristics, 1):
            char_answers = model_answers.get(char, [])
            answers_text = "; ".join(char_answers) if char_answers else "примеры отсутствуют"
            chars_with_answers += f"\n{i}. Характеристика: {char}\n   Примеры подтверждений: {answers_text}\n"

        user_answers_text = "\n".join([f"  {i}. {ans}" for i, ans in enumerate(user_answers, 1)])

        return f"""Проверь ответ на задание 23 ЕГЭ (Конституция РФ) - МОДЕЛЬ 2.

ТИП ЗАДАНИЯ: Даны ТРИ характеристики государства, ученик должен привести по ОДНОМУ подтверждению для КАЖДОЙ характеристики.

ХАРАКТЕРИСТИКИ И ПРИМЕРЫ ПОДТВЕРЖДЕНИЙ (примеры - это лишь ОРИЕНТИРЫ, а НЕ исчерпывающий список!):
{chars_with_answers}

ОТВЕТ УЧЕНИКА (полный текст):
{full_answer}

РАСПОЗНАННЫЕ ПОДТВЕРЖДЕНИЯ (по порядку характеристик):
{user_answers_text}

⚠️ ВАЖНЕЙШЕЕ ПРАВИЛО:
Ученик может привести подтверждения, которых НЕТ в примерах выше!
Такие подтверждения ДОЛЖНЫ быть засчитаны, если они:
- Опираются на положения Конституции РФ
- Раскрывают соответствующую характеристику государства
- Фактически верны

НЕ сравнивай ответ ученика только с примерами - оценивай его по существу!

КРИТЕРИИ ПРОВЕРКИ КАЖДОГО ПОДТВЕРЖДЕНИЯ:

✅ ЗАСЧИТЫВАЕТСЯ подтверждение, если:
1. Сформулировано как РАСПРОСТРАНЁННОЕ ПРЕДЛОЖЕНИЕ (не отдельные слова/словосочетания!)
2. Опирается на КОНКРЕТНОЕ положение КОНСТИТУЦИИ РФ (не других законов!)
3. Раскрывает ИМЕННО ТУ характеристику, к которой относится (по порядку)
4. Фактически верное
5. ДАЖЕ ЕСЛИ его нет в примерах!

❌ НЕ ЗАСЧИТЫВАЕТСЯ подтверждение, если:
1. Это просто слово или словосочетание без развёрнутого пояснения
2. Опирается на федеральные законы или другие акты, а не на Конституцию РФ
3. Содержит фактическую ошибку
4. Не соответствует той характеристике, к которой относится
5. Это общее рассуждение без конкретики

ПРАВИЛА ВЫСТАВЛЕНИЯ БАЛЛОВ:
- 3 балла: 3 верных подтверждения (по одному для каждой характеристики) БЕЗ дополнительных позиций с ошибками
- 2 балла: 2 верных подтверждения БЕЗ дополнительных позиций с ошибками
- 1 балл: 1 верное подтверждение БЕЗ дополнительных ошибок ИЛИ 2-3 верных подтверждения ПРИ НАЛИЧИИ дополнительных позиций с ошибками
- 0 баллов: нет верных подтверждений / общие рассуждения / неправильный ответ

Ответь в формате JSON:
```json
{{
    "correct_count": количество засчитанных подтверждений (0-3),
    "has_additional_errors": true/false (есть ли дополнительные позиции с неточностями/ошибками),
    "score": итоговый балл с учётом правил (0-3),
    "answers_evaluation": [
        {{
            "characteristic_number": номер характеристики (1-3),
            "characteristic": "текст характеристики",
            "user_answer": "ответ ученика",
            "is_expanded_sentence": true/false (это распространённое предложение?),
            "is_based_on_constitution": true/false (опора на Конституцию РФ?),
            "matches_characteristic": true/false (соответствует ли своей характеристике?),
            "is_correct": true/false (итоговое решение),
            "matched_model": "какому примеру соответствует (если есть совпадение)" или null,
            "comment": "почему засчитано/не засчитано - с обоснованием по Конституции РФ"
        }}
    ],
    "feedback": "общий комментарий (2-3 предложения)",
    "suggestions": ["рекомендация по улучшению"]
}}
```

ВАЖНО: Верни ТОЛЬКО валидный JSON."""

    def _parse_model1_response(
        self,
        response: Dict[str, Any],
        model_answers: List[str]
    ) -> EvaluationResult:
        """Парсинг ответа AI для Model Type 1."""
        try:
            score = min(response.get("score", 0), 3)
            correct_count = response.get("correct_count", 0)
            has_errors = response.get("has_additional_errors", False)

            feedback = f"<b>Результат:</b> {correct_count} из 3 подтверждений засчитано.\n"
            feedback += f"<b>Балл:</b> {score}/3\n"

            # Пояснение по баллу если есть дополнительные ошибки
            if has_errors and correct_count >= 2:
                feedback += "<i>(Балл снижен из-за дополнительных позиций с ошибками)</i>\n"

            feedback += "\n"

            # Добавляем оценку каждого подтверждения
            if response.get("answers_evaluation"):
                feedback += "<b>Проверка подтверждений:</b>\n"
                for eval_item in response["answers_evaluation"]:
                    num = eval_item.get("number", "?")
                    is_correct = eval_item.get("is_correct", False)
                    comment = eval_item.get("comment", "")

                    icon = "✅" if is_correct else "❌"
                    feedback += f"{icon} <b>Подтверждение {num}:</b>\n"

                    # Показываем детали проверки
                    if not eval_item.get("is_expanded_sentence", True):
                        feedback += "   ⚠️ <i>Не является распространённым предложением</i>\n"
                    if not eval_item.get("is_based_on_constitution", True) and not is_correct:
                        feedback += "   ⚠️ <i>Нет опоры на Конституцию РФ</i>\n"

                    feedback += f"   {comment}\n"

                    if is_correct and eval_item.get("matched_model"):
                        matched = eval_item['matched_model']
                        if len(matched) > 80:
                            matched = matched[:80] + "..."
                        feedback += f"   <i>Соответствует: {matched}</i>\n"

            # Общий комментарий
            if response.get("feedback"):
                feedback += f"\n<b>Комментарий:</b> {response['feedback']}"

            return EvaluationResult(
                criteria_scores={"К1": score},
                total_score=score,
                max_score=3,
                feedback=feedback,
                detailed_feedback=response,
                suggestions=response.get("suggestions", []),
                factual_errors=[]
            )

        except Exception as e:
            logger.error(f"Error parsing Model1 response: {e}")
            return self._create_error_result("Ошибка обработки ответа AI")

    def _parse_model2_response(
        self,
        response: Dict[str, Any],
        characteristics: List[str]
    ) -> EvaluationResult:
        """Парсинг ответа AI для Model Type 2."""
        try:
            score = min(response.get("score", 0), 3)
            correct_count = response.get("correct_count", 0)
            has_errors = response.get("has_additional_errors", False)

            feedback = f"<b>Результат:</b> {correct_count} из 3 подтверждений засчитано.\n"
            feedback += f"<b>Балл:</b> {score}/3\n"

            # Пояснение по баллу если есть дополнительные ошибки
            if has_errors and correct_count >= 2:
                feedback += "<i>(Балл снижен из-за дополнительных позиций с ошибками)</i>\n"

            feedback += "\n"

            # Добавляем оценку каждого подтверждения
            if response.get("answers_evaluation"):
                feedback += "<b>Проверка по характеристикам:</b>\n"
                for eval_item in response["answers_evaluation"]:
                    char_num = eval_item.get("characteristic_number", "?")
                    char_text = eval_item.get("characteristic", "")[:50]
                    is_correct = eval_item.get("is_correct", False)
                    comment = eval_item.get("comment", "")

                    icon = "✅" if is_correct else "❌"
                    feedback += f"\n{icon} <b>{char_num}. {char_text}...</b>\n"

                    # Показываем детали проверки
                    if not eval_item.get("is_expanded_sentence", True):
                        feedback += "   ⚠️ <i>Не является распространённым предложением</i>\n"
                    if not eval_item.get("is_based_on_constitution", True) and not is_correct:
                        feedback += "   ⚠️ <i>Нет опоры на Конституцию РФ</i>\n"
                    if not eval_item.get("matches_characteristic", True) and not is_correct:
                        feedback += "   ⚠️ <i>Не соответствует данной характеристике</i>\n"

                    feedback += f"   {comment}\n"

            # Общий комментарий
            if response.get("feedback"):
                feedback += f"\n<b>Комментарий:</b> {response['feedback']}"

            return EvaluationResult(
                criteria_scores={"К1": score},
                total_score=score,
                max_score=3,
                feedback=feedback,
                detailed_feedback=response,
                suggestions=response.get("suggestions", []),
                factual_errors=[]
            )

        except Exception as e:
            logger.error(f"Error parsing Model2 response: {e}")
            return self._create_error_result("Ошибка обработки ответа AI")

    def _basic_evaluation_model1(
        self,
        user_answers: List[str],
        model_answers: List[str],
        characteristic: str
    ) -> EvaluationResult:
        """Базовая оценка Model Type 1 без AI."""
        score = min(len(user_answers), 3)

        feedback = f"<b>Обнаружено подтверждений:</b> {len(user_answers)}\n"
        feedback += f"<b>Базовый балл:</b> {score}/3\n\n"
        feedback += "<i>Для точной проверки требуется AI-сервис.</i>\n\n"
        feedback += "<b>Эталонные ответы:</b>\n"
        for i, ans in enumerate(model_answers[:3], 1):
            feedback += f"{i}. {ans}\n"

        return EvaluationResult(
            criteria_scores={"К1": score},
            total_score=score,
            max_score=3,
            feedback=feedback,
            detailed_feedback={
                "answers_count": len(user_answers),
                "note": "Базовая проверка без AI",
                "user_answers": user_answers
            },
            suggestions=[
                "Убедитесь, что каждое подтверждение опирается на Конституцию РФ",
                "Формулируйте ответы развёрнутыми предложениями"
            ],
            factual_errors=[]
        )

    def _basic_evaluation_model2(
        self,
        user_answers: List[str],
        characteristics: List[str],
        model_answers: Dict[str, List[str]]
    ) -> EvaluationResult:
        """Базовая оценка Model Type 2 без AI."""
        score = min(len(user_answers), 3)

        feedback = f"<b>Обнаружено подтверждений:</b> {len(user_answers)}\n"
        feedback += f"<b>Базовый балл:</b> {score}/3\n\n"
        feedback += "<i>Для точной проверки требуется AI-сервис.</i>\n\n"
        feedback += "<b>Характеристики и эталонные ответы:</b>\n"

        for i, char in enumerate(characteristics, 1):
            char_answers = model_answers.get(char, [])
            if char_answers:
                example = char_answers[0][:100] + "..." if len(char_answers[0]) > 100 else char_answers[0]
                feedback += f"\n{i}. <b>{char[:50]}...</b>\n   <i>{example}</i>\n"

        return EvaluationResult(
            criteria_scores={"К1": score},
            total_score=score,
            max_score=3,
            feedback=feedback,
            detailed_feedback={
                "answers_count": len(user_answers),
                "note": "Базовая проверка без AI",
                "user_answers": user_answers
            },
            suggestions=[
                "Давайте подтверждения в том же порядке, что и характеристики",
                "Каждое подтверждение должно раскрывать конкретную характеристику"
            ],
            factual_errors=[]
        )

    def _create_error_result(self, message: str) -> EvaluationResult:
        """Создание результата с ошибкой."""
        return EvaluationResult(
            criteria_scores={"К1": 0},
            total_score=0,
            max_score=3,
            feedback=f"❌ {message}",
            detailed_feedback={"error": message},
            suggestions=[],
            factual_errors=[]
        )

    def get_model_answers_text(self, question_data: Dict[str, Any]) -> str:
        """Получить текст эталонных ответов для отображения."""
        model_type = question_data.get('model_type', 1)

        if model_type == 1:
            answers = question_data.get('model_answers', [])
            text = "<b>Эталонные подтверждения (любые 3 из них):</b>\n\n"
            for i, ans in enumerate(answers, 1):
                text += f"{i}. {ans}\n\n"
            return text
        else:
            characteristics = question_data.get('characteristics', [])
            model_answers = question_data.get('model_answers', {})

            text = "<b>Эталонные подтверждения:</b>\n\n"
            for i, char in enumerate(characteristics, 1):
                text += f"<b>{i}. {char}</b>\n"
                char_answers = model_answers.get(char, [])
                if char_answers:
                    for ans in char_answers:
                        text += f"   • {ans}\n"
                text += "\n"
            return text
