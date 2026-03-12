"""AI-проверка для задания 17 ЕГЭ по обществознанию.

Задание 17 — три вопроса по тексту. Ученик должен ответить на три
вопроса, опираясь на информацию из текстового фрагмента.
Максимальный балл — 2.

Критерии оценивания (ФИПИ, методические рекомендации для экспертов):
  2 балла — верные ответы на ВСЕ ТРИ вопроса.
  1 балл  — верные ответы на ЛЮБЫЕ ДВА вопроса.
  0 баллов — верный ответ только на один / рассуждения общего характера /
             неверный ответ.
"""

import logging
from typing import Dict, List, Any

from core.types import TaskRequirements, EvaluationResult

logger = logging.getLogger(__name__)

try:
    from core.ai_service import create_ai_service, AIServiceConfig, AIModel
    AI_AVAILABLE = True
except ImportError as e:
    logger.warning(f"AI service not available: {e}")
    AI_AVAILABLE = False


class Task17AIEvaluator:
    """AI-проверщик для задания 17."""

    def __init__(self):
        self.requirements = TaskRequirements(
            task_number=17,
            task_name="Анализ текста: поиск информации",
            max_score=2,
            criteria=[],
            description=(
                "Прочитайте текст и найдите указанные в вопросе элементы "
                "(функции, признаки, понятия и т.д.)."
            ),
        )
        self.config = None
        if AI_AVAILABLE:
            try:
                self.config = AIServiceConfig.from_env()
                self.config.model = AIModel.LITE
                self.config.temperature = 0.15
                logger.info("Task17 AI evaluator configured")
            except Exception as e:
                logger.error(f"Failed to configure AI service for task17: {e}")

    # ------------------------------------------------------------------
    # system prompt
    # ------------------------------------------------------------------

    def get_system_prompt(self) -> str:
        return """Ты — опытный эксперт ЕГЭ по обществознанию, проверяющий задание 17.

СУТЬ ЗАДАНИЯ 17:
Ученику дан текстовый фрагмент и ТРИ ВОПРОСА по нему. Нужно ответить
на каждый вопрос, опираясь на информацию из текста.

КРИТЕРИИ ОЦЕНИВАНИЯ (максимум 2 балла):
• 2 балла — верные ответы на ВСЕ ТРИ вопроса.
• 1 балл  — верные ответы на ЛЮБЫЕ ДВА вопроса.
• 0 баллов — верный ответ только на один вопрос / рассуждения общего
  характера / неверный ответ.

ВАЖНЫЕ ПРАВИЛА ОЦЕНИВАНИЯ:

1. ПОРЯДОК ОТВЕТОВ НЕ ВАЖЕН. Если ученик отвечает на вопросы не по
   порядку — идентифицируй все элементы и оценивай их независимо от
   порядка.

2. ПЕРЕСКАЗ СВОИМИ СЛОВАМИ ЗАСЧИТЫВАЕТСЯ. Не требуй дословного
   цитирования. Если смысл ответа верно передан — элемент засчитывается.

3. ПЕРЕПИСЫВАНИЕ БОЛЬШОГО ФРАГМЕНТА ЦЕЛИКОМ НЕ ЗАСЧИТЫВАЕТСЯ, если
   задание требовало найти конкретные термины или характеристики.
   Ответ должен быть конкретным, а не состоять из объёмной цитаты.

4. ПОЗИЦИИ, КОТОРЫХ НЕТ В ТЕКСТЕ, НЕ ЗАСЧИТЫВАЮТСЯ. Задание 17
   проверяет умение работать с текстом, а не общие знания.

5. КОГДА ВОПРОС ТРЕБУЕТ НЕСКОЛЬКО ПОЗИЦИЙ (например, «укажите любые
   три мотива»):
   - Засчитывай только при наличии ≥ требуемого количества верных
     позиций И при отсутствии неверных позиций.
   - Если позиций БОЛЬШЕ, чем требуется, но ВСЕ верные — засчитывать.
   - Если хотя бы одна позиция НЕВЕРНАЯ — ответ на ВЕСЬ этот вопрос НЕ
     засчитывается.
   - Если верных позиций МЕНЬШЕ требуемого — ответ не засчитывается.

6. Если один элемент ответа дублирует другой (по смыслу), засчитывается
   только один.

7. НЕПОЛНОЕ ЦИТИРОВАНИЕ С ИСКАЖЕНИЕМ СМЫСЛА не засчитывается — цитата,
   обрывающаяся в месте, меняющем суть ответа.

Отвечай ВСЕГДА в формате JSON."""

    # ------------------------------------------------------------------
    # evaluation
    # ------------------------------------------------------------------

    async def evaluate(
        self,
        answer: str,
        task_data: Dict[str, Any],
        **kwargs,
    ) -> EvaluationResult:
        if not AI_AVAILABLE or not self.config:
            return self._basic_evaluation(answer, task_data)

        prompt = self._build_evaluation_prompt(answer, task_data)

        try:
            async with create_ai_service(self.config) as service:
                result = await service.get_json_completion(
                    prompt=prompt,
                    system_prompt=self.get_system_prompt(),
                    temperature=self.config.temperature,
                )
                if result:
                    return self._parse_response(result, task_data)
                logger.error("AI returned None for task17")
                return self._basic_evaluation(answer, task_data)
        except Exception as e:
            logger.error(f"Error in Task17 evaluation: {e}")
            return self._basic_evaluation(answer, task_data)

    # ------------------------------------------------------------------
    # prompt builder
    # ------------------------------------------------------------------

    def _build_evaluation_prompt(
        self,
        answer: str,
        task_data: Dict[str, Any],
    ) -> str:
        # Поддержка нескольких форматов данных:
        # 1) Из text_passages_17_18.json: text, question, correct_answers
        # 2) Из variant_check (внешний вариант): task_text, correct_answer_criteria
        # 3) Из homework: task_text, criteria
        text = task_data.get("text", "")
        question = task_data.get("question", "")
        correct_answers = task_data.get("correct_answers", [])
        required_count = task_data.get("required_count", 3)
        scoring_notes = task_data.get("scoring_notes", "")

        # Fallback: если стандартные поля пусты, берём из альтернативных
        task_text = task_data.get("task_text", "")
        criteria_text = (
            task_data.get("correct_answer_criteria", "")
            or task_data.get("criteria", "")
        )

        if not text and not question and task_text:
            question = task_text

        if not text and task_text:
            text = task_text

        if not correct_answers and criteria_text:
            correct_answers = [
                line.strip().lstrip("–—-•·0123456789.) ")
                for line in criteria_text.split("\n")
                if line.strip() and len(line.strip()) > 5
            ]
            if not correct_answers:
                correct_answers = [criteria_text]

        if not scoring_notes and criteria_text:
            scoring_notes = criteria_text

        correct_block = "\n".join(
            f"  {i}. {a}" for i, a in enumerate(correct_answers, 1)
        )

        return f"""Проверь ответ на задание 17 ЕГЭ по обществознанию.

ТЕКСТ:
{text}

ВОПРОС (содержит три подвопроса):
{question}

ПРАВИЛЬНЫЕ ОТВЕТЫ (эталон):
{correct_block}

ТРЕБУЕМОЕ КОЛИЧЕСТВО ЭЛЕМЕНТОВ (суммарно): {required_count}

ДОПОЛНИТЕЛЬНЫЕ КРИТЕРИИ:
{scoring_notes}

ОТВЕТ УЧЕНИКА:
{answer}

ПОШАГОВЫЙ АЛГОРИТМ ПРОВЕРКИ:

ШАГ 1: Разбей ответ ученика на части, соответствующие каждому из 3 вопросов
(независимо от порядка, который выбрал ученик). Ученик мог отвечать не по
порядку или без нумерации — идентифицируй все элементы.

ШАГ 2: Для каждого вопроса оцени ответ:
  a) Если вопрос требует КОНКРЕТНЫЙ ФАКТ/ТЕРМИН из текста:
     - Проверь, что ответ НЕ является «переписыванием большого фрагмента»
       (копирование абзаца целиком = НЕ засчитывается)
     - Засчитай, если СМЫСЛ верно передан (даже без прямого цитирования)
     - НЕ засчитывай позиции, которых НЕТ в тексте
  b) Если вопрос требует НЕСКОЛЬКО ПОЗИЦИЙ (например, «три мотива»):
     - Считай количество верных позиций из текста
     - Если есть хоть одна НЕВЕРНАЯ позиция → ответ на ВЕСЬ этот вопрос = 0
     - Если верных позиций МЕНЬШЕ требуемого → ответ на этот вопрос = 0
     - Если позиций БОЛЬШЕ требуемого, но ВСЕ верные → засчитывать

ШАГ 3: Подсчёт итогового балла:
  - 3 верных вопроса → 2 балла
  - 2 верных вопроса → 1 балл
  - ≤ 1 верного вопроса → 0 баллов

Ответь в формате JSON:
```json
{{
    "score": число от 0 до 2,
    "questions_correct": число верно отвеченных вопросов (0-3),
    "questions_evaluation": [
        {{
            "question_num": 1,
            "question_summary": "краткая суть вопроса",
            "is_correct": true/false,
            "user_answer_summary": "что ответил ученик на этот вопрос",
            "correct_answer_summary": "какой ответ ожидался",
            "positions_required": число требуемых позиций (если >1, иначе 1),
            "positions_valid": число верных позиций ученика,
            "positions_invalid": число неверных позиций ученика,
            "comment": "краткий комментарий эксперта"
        }}
    ],
    "feedback": "общий комментарий (2-3 предложения)",
    "suggestions": ["рекомендация 1", "рекомендация 2"]
}}
```

ВАЖНО: Верни ТОЛЬКО валидный JSON."""

    # ------------------------------------------------------------------
    # response parsing
    # ------------------------------------------------------------------

    def _parse_response(
        self,
        response: Dict[str, Any],
        task_data: Dict[str, Any],
    ) -> EvaluationResult:
        try:
            score = min(max(response.get("score", 0), 0), 2)
            questions_correct = response.get("questions_correct", 0)

            feedback = response.get("feedback", "")
            feedback += (
                f"\n\n<b>Результат:</b> {questions_correct} из 3 вопросов"
                f" отвечены верно. Балл: {score}/2\n"
            )

            questions = response.get("questions_evaluation", [])
            if questions:
                feedback += "\n<b>Проверка по вопросам:</b>\n"
                for q in questions:
                    icon = "\u2705" if q.get("is_correct") else "\u274c"
                    q_num = q.get("question_num", "?")
                    q_summary = q.get("question_summary", "")
                    comment = q.get("comment", "")

                    feedback += f"\n{icon} <b>Вопрос {q_num}</b>"
                    if q_summary:
                        feedback += f" ({q_summary})"
                    feedback += "\n"

                    # Показываем позиции, если вопрос требовал >1
                    pos_req = q.get("positions_required", 1)
                    if pos_req > 1:
                        pos_valid = q.get("positions_valid", 0)
                        pos_invalid = q.get("positions_invalid", 0)
                        feedback += (
                            f"  Позиций: {pos_valid} верных"
                            f" из {pos_req} требуемых"
                        )
                        if pos_invalid:
                            feedback += f", {pos_invalid} неверных"
                        feedback += "\n"

                    if comment:
                        feedback += f"  {comment}\n"

            return EvaluationResult(
                criteria_scores={"K1": score},
                total_score=score,
                max_score=2,
                feedback=feedback,
                detailed_feedback=response,
                suggestions=response.get("suggestions", []),
                factual_errors=[],
            )
        except Exception as e:
            logger.error(f"Error parsing task17 AI response: {e}")
            return self._basic_evaluation("", task_data)

    # ------------------------------------------------------------------
    # fallback
    # ------------------------------------------------------------------

    def _basic_evaluation(
        self,
        answer: str,
        task_data: Dict[str, Any],
    ) -> EvaluationResult:
        return EvaluationResult(
            criteria_scores={"K1": 0},
            total_score=0,
            max_score=2,
            feedback=(
                "AI-сервис временно недоступен. "
                "Обратитесь к преподавателю для проверки."
            ),
            detailed_feedback={},
            suggestions=[
                "Внимательно прочитайте текст перед ответом",
                "Ответ должен содержать конкретные элементы из текста",
            ],
            factual_errors=[],
        )
