"""AI-проверка для задания 18 ЕГЭ по обществознанию.

Задание 18 — признаки понятия + объяснение связи фрагмента текста
с явлением социальной реальности. Максимальный балл — 2.

Ответ оценивается по ДВУМ элементам:
  Элемент 1: Признаки/характеристики ключевого понятия из УСЛОВИЯ ЗАДАНИЯ.
             Требуемое количество определяется заданием (обычно ≥3, реже ≥2).
             Минимум 2 (или 1 при ≥2) должны быть из каталога/эталона.
             Наличие хотя бы одной неверной позиции обнуляет элемент 1.
  Элемент 2: Объяснение связи конкретной характеристики/функции,
             указанной АВТОРОМ В ТЕКСТЕ-ИСТОЧНИКЕ, с явлением из условия.
             Требуется причинно-следственная/функциональная связь.
             Объяснение связи не указанной автором функции НЕ засчитывается.

Критерии оценивания (ФИПИ, методические рекомендации для экспертов):
  2 балла — оба элемента верны.
  1 балл  — верен только один из двух элементов.
  0 баллов — оба элемента неверны / рассуждения общего характера /
             неверный ответ.
"""

import json
import logging
import os
from typing import Dict, List, Any, Optional

from core.types import TaskRequirements, EvaluationResult

logger = logging.getLogger(__name__)

# Импорт калибровочных few-shot примеров
try:
    from core.fewshot_calibration import get_full_calibration_prompt
except ImportError:
    def get_full_calibration_prompt(task_number: int) -> str:
        return ""

try:
    from core.ai_service import create_ai_service, AIServiceConfig, AIModel
    AI_AVAILABLE = True
except ImportError as e:
    logger.warning(f"AI service not available: {e}")
    AI_AVAILABLE = False


# ------------------------------------------------------------------
# Загрузка каталога признаков
# ------------------------------------------------------------------

_katalog_data: Optional[Dict[str, Any]] = None


def _load_katalog() -> Dict[str, Any]:
    """Загрузить каталог признаков из JSON."""
    global _katalog_data
    if _katalog_data is not None:
        return _katalog_data

    try:
        base_dir = os.path.dirname(os.path.dirname(__file__))
        path = os.path.join(base_dir, "data", "katalog_priznakov.json")
        with open(path, "r", encoding="utf-8") as f:
            _katalog_data = json.load(f)
            count = len(_katalog_data.get("terms", []))
            logger.info(f"Loaded katalog_priznakov.json: {count} terms")
    except Exception as e:
        logger.error(f"Failed to load katalog_priznakov.json: {e}")
        _katalog_data = {"terms": []}

    return _katalog_data


def extract_concept_from_text(text: str) -> str:
    """Извлечь ключевое понятие из текста задания 18.

    Поддерживаемые паттерны условия задания 18 ЕГЭ:
      - понятие «государственный бюджет»
      - смысл понятия «инфляция»
      - характеристик государственного бюджета как финансового плана
      - признаки понятия «правовое государство»
      - что такое «социальная мобильность»
    """
    import re

    # Паттерны с кавычками (приоритетные — наиболее точные)
    quoted_patterns = [
        r'понятие\s*[«"„]([^»""]+)[»"""]',
        r"понятие\s*'([^']+)'",
        r'термин\s*[«"„]([^»""]+)[»"""]',
        r'объясните\s+(?:смысл\s+)?(?:понятия\s+)?[«"„]([^»""]+)[»"""]',
        r'что\s+(?:такое|означает)\s+[«"„]([^»""]+)[»"""]',
    ]
    for pattern in quoted_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()

    # Паттерны без кавычек (типичные формулировки задания 18 ЕГЭ)
    unquoted_patterns = [
        # "характеристик государственного бюджета как финансового плана"
        r'характеристик[иу]?\s+(.+?)\s+как\s',
        # "признаки правового государства; объясните..."
        # "признаков социальной мобильности и объясните..."
        r'признак(?:и|ов|а)\s+(?:понятия\s+)?([А-Яа-яёЁ][А-Яа-яёЁ\s-]+?)(?:\s*[;.,]|\s+как\s|\s+и\s)',
        # "функции понятия X" / "свойства понятия X"
        r'(?:функци[июй]|свойства?)\s+(?:понятия\s+)?([А-Яа-яёЁ][А-Яа-яёЁ\s-]+?)(?:\s*[;.,]|\s+и\s)',
    ]
    for pattern in unquoted_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            # Очистка: убираем лишние слова в конце
            concept = match.group(1).strip().rstrip(";.,")
            # Убираем «основных» и другие прилагательные-модификаторы в начале
            concept = re.sub(r'^(?:основных|главных|ключевых|важнейших)\s+', '', concept)
            if concept and len(concept) > 2:
                return concept

    return ""


def _stem_words(text: str) -> set:
    """Простое стемминг-подобное извлечение основ слов.

    Берём первые 5 символов каждого слова (или слово целиком, если короче).
    Позволяет сопоставить «государственного бюджета» с «государственный бюджет»:
      «государственного» → «госуд», «бюджета» → «бюдже»
      «государственный» → «госуд»,  «бюджет» → «бюдже»
    """
    words = text.lower().split()
    stems = set()
    for w in words:
        if len(w) <= 3:
            stems.add(w)
        else:
            stems.add(w[:5])
    return stems


def find_catalog_signs(concept: str) -> List[str]:
    """Найти признаки понятия в каталоге по ключевому слову."""
    if not concept or not concept.strip():
        return []

    katalog = _load_katalog()
    concept_lower = concept.lower().strip()

    # 1. Точное совпадение
    for entry in katalog.get("terms", []):
        if entry["term"].lower() == concept_lower:
            return entry["signs"]

    # 2. Поиск по вхождению подстроки
    matches = []
    for entry in katalog.get("terms", []):
        term = entry["term"].lower()
        if concept_lower in term or term in concept_lower:
            matches.append(entry)

    if matches:
        matches.sort(key=lambda e: abs(len(e["term"]) - len(concept)))
        return matches[0]["signs"]

    # 3. Нечёткий поиск по основам слов (для сопоставления падежных форм)
    concept_stems = _stem_words(concept_lower)
    if len(concept_stems) < 1:
        return []

    stem_matches = []
    for entry in katalog.get("terms", []):
        term_stems = _stem_words(entry["term"].lower())
        # Считаем долю совпадающих основ
        if not concept_stems or not term_stems:
            continue
        overlap = concept_stems & term_stems
        # Требуем совпадения большинства значимых слов
        score = len(overlap) / max(len(concept_stems), len(term_stems))
        if score >= 0.5 and len(overlap) >= 1:
            stem_matches.append((score, entry))

    if stem_matches:
        stem_matches.sort(key=lambda x: (-x[0], abs(len(x[1]["term"]) - len(concept))))
        return stem_matches[0][1]["signs"]

    return []


class Task18AIEvaluator:
    """AI-проверщик для задания 18."""

    def __init__(self):
        self.requirements = TaskRequirements(
            task_number=18,
            task_name="Анализ текста: объяснение понятия",
            max_score=2,
            criteria=[],
            description=(
                "Используя обществоведческие знания, объясните понятие "
                "из текста и/или приведите примеры, признаки, функции."
            ),
        )
        self.config = None
        if AI_AVAILABLE:
            try:
                self.config = AIServiceConfig.from_env()
                self.config.model = AIModel.LITE
                self.config.temperature = 0.2
                logger.info("Task18 AI evaluator configured")
            except Exception as e:
                logger.error(f"Failed to configure AI for task18: {e}")

    # ------------------------------------------------------------------
    # system prompt
    # ------------------------------------------------------------------

    def get_system_prompt(self) -> str:
        return """Ты — опытный эксперт ЕГЭ по обществознанию, проверяющий задание 18.

СТРУКТУРА ЗАДАНИЯ 18:
Задание состоит из вводного предложения и двух элементов.
Ученику дан текст-источник (тот же, что и в задании 17) и УСЛОВИЕ ЗАДАНИЯ.
Условие задания содержит:
  - Первая часть: указание привести признаки/характеристики КЛЮЧЕВОГО
    ПОНЯТИЯ (понятие и уточнение берутся из УСЛОВИЯ ЗАДАНИЯ).
  - Вторая часть: указание объяснить связь конкретной характеристики/
    функции, упомянутой АВТОРОМ В ТЕКСТЕ, с определённым явлением.

═══════════════════════════════════════════════════
ЭЛЕМЕНТ 1 — ПРИЗНАКИ КЛЮЧЕВОГО ПОНЯТИЯ
═══════════════════════════════════════════════════

Ключевое понятие берётся из УСЛОВИЯ ЗАДАНИЯ, а НЕ из текста-источника.
Текст-источник НЕ используется для проверки элемента 1.

Например: если условие просит «характеристики государственного бюджета
как финансового плана», а текст-источник рассказывает о социальной
политике и доходах населения — ключевое понятие = «государственный
бюджет», а не «социальная политика» и не «доходы населения».

ПРАВИЛА ПРОВЕРКИ ЭЛЕМЕНТА 1:

1. КОЛИЧЕСТВО ПРИЗНАКОВ:
   - Обычно требуется ≥3 (в исключительных случаях ≥2).
   - При ≥3: минимум 2 должны быть из каталога/эталона, при отсутствии
     неверных позиций.
   - При ≥2: минимум 1 из каталога/эталона, при отсутствии неверных.

2. НЕ ЗАСЧИТЫВАЙ признаки, повторяющие ФОРМУЛИРОВКУ ЗАДАНИЯ.
   Нельзя повторять родовое слово и признаки из условия.
   Пример: если задание говорит «признаки налога как законно
   установленного платежа физических и юридических лиц», то ответы
   «законно установленный», «платёж физических и юридических лиц»
   НЕ засчитываются — они уже содержатся в формулировке.

3. НЕ ЗАСЧИТЫВАЙ: признаки через отрицание; через этимологию/
   метафору/аллегорию; «пустые» признаки (общие слова без содержания).

4. НЕВЕРНЫЕ ПОЗИЦИИ: если среди указанных признаков есть хотя бы
   ОДИН неверный → весь элемент 1 НЕ засчитывается.

5. ЗАСЧИТЫВАЙ близкие по смыслу формулировки — не требуй дословного
   совпадения. В учебниках за 6–11 класс разные определения одних
   понятий. Кроме определений, в учебниках есть развёрнутые
   характеристики, признаки, связи — учитывай их тоже.

6. Дублирующие признаки считаются как один.

7. Если ученик написал определение без разбивки на признаки — проверь,
   можно ли из него выделить требуемое количество конкретных признаков.

═══════════════════════════════════════════════════
ЭЛЕМЕНТ 2 — ОБЪЯСНЕНИЕ СВЯЗИ С ТЕКСТОМ-ИСТОЧНИКОМ
═══════════════════════════════════════════════════

Ученик должен объяснить связь конкретной функции/характеристики,
УКАЗАННОЙ АВТОРОМ В ТЕКСТЕ-ИСТОЧНИКЕ, с явлением из условия задания.

ПРАВИЛА ПРОВЕРКИ ЭЛЕМЕНТА 2:

1. ОПОРА НА ТЕКСТ ОБЯЗАТЕЛЬНА. Ученик должен взять именно ту функцию/
   характеристику, которую упоминает АВТОР ТЕКСТА. Объяснение связи
   НЕ УКАЗАННОЙ автором функции/характеристики НЕ засчитывается.

2. Требуется ПРИЧИННО-СЛЕДСТВЕННАЯ или ФУНКЦИОНАЛЬНАЯ связь:
   (функция/характеристика из текста) → (механизм) → (явление).
   Простое цитирование текста или констатация факта НЕ засчитывается.

3. НЕ ЗАСЧИТЫВАЙ: рассуждения общего характера без конкретной связи;
   воспроизведение только явной информации из текста без объяснения
   причинно-следственных связей; объяснение, не связанное с текстом.

4. Если в объяснении есть ошибочные суждения → элемент 2 НЕ засчитан.

═══════════════════════════════════════════════════
СИСТЕМА ОЦЕНИВАНИЯ
═══════════════════════════════════════════════════

2 балла — правильно приведены оба элемента (нужное количество
          признаков + корректное объяснение связи).
1 балл  — правильно приведён только один любой элемент.
0 баллов — все иные ситуации, ИЛИ рассуждения общего характера,
          не соответствующие требованию задания, ИЛИ ответ неправильный.

═══════════════════════════════════════════════════
ТИПИЧНЫЕ ОШИБКИ ЭКСПЕРТОВ (ИЗБЕГАЙ ИХ)
═══════════════════════════════════════════════════

- Не обращать внимание на количество обязательных признаков в критериях.
- Оценивать «пустые» признаки, содержащиеся в тексте задания.
- Ждать дословного воспроизведения признаков из каталога.
- Не проверять, выписал ли ученик определение понятия (из которого
  можно выделить признаки).
- Ставить балл за элемент 2, если приведён большой объём текста
  с общими рассуждениями, но без конкретной причинно-следственной связи.

""" + get_full_calibration_prompt(18) + """
- Ставить балл за элемент 2, если объяснение не связано с текстом.

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
                logger.error("AI returned None for task18")
                return self._basic_evaluation(answer, task_data)
        except Exception as e:
            logger.error(f"Error in Task18 evaluation: {e}")
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
        # 1) Из text_passages_17_18.json: text, question, concept, correct_answer
        # 2) Из variant_check (внешний вариант): task_text, correct_answer_criteria
        # 3) Из homework: task_text, criteria
        text = task_data.get("text", "")
        question = task_data.get("question", "")
        concept = task_data.get("concept", "")
        correct_answer = task_data.get("correct_answer", {})

        # Автоизвлечение понятия из текста задания, если не указано явно
        if not concept:
            concept = extract_concept_from_text(question) or extract_concept_from_text(
                task_data.get("task_text", "")
            )
        required_count = correct_answer.get("required_count", 3)
        elements = correct_answer.get("elements", [])
        scoring_notes = task_data.get("scoring_notes", "")

        # Fallback: если стандартные поля пусты, берём из альтернативных
        task_text = task_data.get("task_text", "")
        source_text = task_data.get("source_text", "")
        criteria_text = (
            task_data.get("correct_answer_criteria", "")
            or task_data.get("criteria", "")
        )

        if not text and source_text:
            text = source_text
        elif not text and not question and task_text:
            # Внешний вариант: task_text содержит условие задания
            question = task_text

        if not text and task_text:
            text = task_text

        has_source_text = bool(text and text != task_text)

        if not elements and criteria_text:
            # Парсим критерии из текстовой формы
            elements = [
                line.strip().lstrip("–—-•·0123456789.) ")
                for line in criteria_text.split("\n")
                if line.strip() and len(line.strip()) > 5
            ]
            if not elements:
                elements = [criteria_text]

        if not scoring_notes and criteria_text:
            scoring_notes = criteria_text

        correct_block = "\n".join(
            f"  {i}. {e}" for i, e in enumerate(elements, 1)
        )

        # Получить признаки из каталога
        catalog_signs = find_catalog_signs(concept)
        if catalog_signs:
            catalog_block = "\n".join(
                f"  {i}. {s}" for i, s in enumerate(catalog_signs, 1)
            )
        else:
            catalog_block = "  (признаки не найдены в каталоге — опирайся на эталонные ответы)"

        # Блок инструкций по Элементу 2 зависит от наличия текста-источника
        if has_source_text:
            text_section = f"ТЕКСТ-ИСТОЧНИК (тот же, что и в задании 17):\n{text}"
            element2_instructions = """ШАГ 2: Проверка ЭЛЕМЕНТА 2 (Объяснение связи с текстом):
  a) Определи по УСЛОВИЮ ЗАДАНИЯ, связь КАКОЙ именно функции/
     характеристики из текста нужно объяснить и С ЧЕМ.
  b) Найди в ТЕКСТЕ-ИСТОЧНИКЕ эту конкретную функцию/характеристику,
     указанную автором.
  c) Проверь, ссылается ли ученик именно на функцию/характеристику
     из текста, а не на произвольную/выдуманную. Если ученик объясняет
     связь функции, НЕ указанной автором в тексте → НЕ засчитывать.
  d) Проверь наличие ПРИЧИННО-СЛЕДСТВЕННОЙ связи:
     (характеристика из текста) → (механизм) → (явление из условия).
     Простое цитирование/констатация без объяснения → НЕ засчитывать.
  e) Проверь отсутствие ошибочных суждений. Есть ошибки → НЕ засчитан.
  f) Общие рассуждения без конкретной связи → НЕ засчитывать."""
            step3 = """ШАГ 3: Итоговый балл:
  - Оба элемента засчитаны → 2 балла.
  - Только один элемент засчитан → 1 балл.
  - Ни один не засчитан / рассуждения общего характера /
    ответ неправильный → 0 баллов."""
        else:
            text_section = "ТЕКСТ-ИСТОЧНИК: НЕ ПРЕДОСТАВЛЕН"
            element2_instructions = """ШАГ 2: Элемент 2 (Объяснение связи с текстом):
  ТЕКСТ-ИСТОЧНИК НЕ ПРЕДОСТАВЛЕН — невозможно проверить привязку к тексту.
  Установи element2_accepted = false.
  Если ученик привёл объяснение связи, отметь это в комментарии, но НЕ засчитывай."""
            step3 = """ШАГ 3: Итоговый балл (без текста-источника):
  - Элемент 1 засчитан → 1 балл (максимум без текста).
  - Элемент 1 не засчитан → 0 баллов.
  ВАЖНО: Без текста-источника максимальный балл = 1."""

        return f"""Проверь ответ на задание 18 ЕГЭ по обществознанию.

{text_section}

УСЛОВИЕ ЗАДАНИЯ:
{question}

КЛЮЧЕВОЕ ПОНЯТИЕ (из условия задания): «{concept}»
Признаки проверяй ИМЕННО для этого понятия. НЕ путай его с другими
понятиями, которые могут упоминаться в тексте-источнике.
Текст-источник НЕ используется для проверки элемента 1.

КАТАЛОГ ПРИЗНАКОВ ПОНЯТИЯ «{concept}» (эталонный перечень):
{catalog_block}

ЭТАЛОННЫЕ ОТВЕТЫ (из критериев оценивания):
{correct_block}

ТРЕБУЕМОЕ КОЛИЧЕСТВО ПРИЗНАКОВ: {required_count}

ДОПОЛНИТЕЛЬНЫЕ КРИТЕРИИ:
{scoring_notes}

ОТВЕТ УЧЕНИКА:
{answer}

══════════════════════════════════════
ПОШАГОВЫЙ АЛГОРИТМ ПРОВЕРКИ
══════════════════════════════════════

ШАГ 1: Проверка ЭЛЕМЕНТА 1 (Признаки понятия «{concept}»):
  a) Выдели все заявленные учеником признаки понятия «{concept}».
  b) ИСКЛЮЧИ признаки, которые:
     - повторяют родовое слово или признаки из ФОРМУЛИРОВКИ ЗАДАНИЯ
       (например, если задание говорит «налог как законно установленный
       платёж физических и юридических лиц», то «законность»,
       «платёж физических и юридических лиц» НЕ засчитываются)
     - сформулированы через отрицание
     - определены через этимологию слова, метафору или аллегорию
     - являются «пустыми» (общие слова без содержания)
     - дублируют другой признак по смыслу
  c) Сопоставь каждый оставшийся признак с КАТАЛОГОМ ПРИЗНАКОВ и
     ЭТАЛОННЫМИ ОТВЕТАМИ. Засчитывай близкие по смыслу формулировки —
     не требуй дословного совпадения с каталогом.
  d) Проверь на НЕВЕРНЫЕ ПОЗИЦИИ — признаки, которые фактически
     неверны для данного понятия. ЕСЛИ ЕСТЬ ХОТЯ БЫ ОДНА НЕВЕРНАЯ
     ПОЗИЦИЯ → весь элемент 1 НЕ засчитан.
  e) Определи, засчитан ли элемент 1:
     - Если требуется ≥3: нужно ≥3 верных, из них ≥2 из каталога,
       без неверных позиций.
     - Если требуется ≥2: нужно ≥2 верных, из них ≥1 из каталога,
       без неверных позиций.

{element2_instructions}

{step3}

Ответь в формате JSON:
```json
{{
    "score": число от 0 до 2,
    "element1_accepted": true/false,
    "element2_accepted": true/false,
    "element1_evaluation": {{
        "traits_found": ["признак 1", "признак 2", ...],
        "traits_excluded": [
            {{"trait": "текст", "reason": "причина исключения"}}
        ],
        "traits_valid_count": число верных признаков,
        "traits_from_catalog": число из каталога/эталона,
        "has_invalid_traits": true/false,
        "invalid_traits": ["неверный признак 1"],
        "comment": "комментарий по элементу 1"
    }},
    "element2_evaluation": {{
        "required_connection": "какую связь требует условие задания",
        "author_reference": "какая функция/характеристика указана автором в тексте",
        "student_reference": "на какую функцию/характеристику ссылается ученик",
        "matches_text": true/false,
        "has_causal_link": true/false,
        "has_errors": true/false,
        "errors_found": ["ошибка 1"],
        "comment": "комментарий по элементу 2"
    }},
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
            el1_ok = response.get("element1_accepted", False)
            el2_ok = response.get("element2_accepted", False)

            feedback = response.get("feedback", "")

            # Сводка
            el1_icon = "\u2705" if el1_ok else "\u274c"
            el2_icon = "\u2705" if el2_ok else "\u274c"
            feedback += (
                f"\n\n<b>Результат:</b> Балл: {score}/2\n"
                f"{el1_icon} Элемент 1 (признаки понятия): "
                f"{'засчитан' if el1_ok else 'не засчитан'}\n"
                f"{el2_icon} Элемент 2 (объяснение связи): "
                f"{'засчитано' if el2_ok else 'не засчитано'}\n"
            )

            # Детали по элементу 1
            el1_eval = response.get("element1_evaluation", {})
            if el1_eval:
                feedback += "\n<b>Элемент 1 — Признаки понятия:</b>\n"

                traits = el1_eval.get("traits_found", [])
                valid_count = el1_eval.get("traits_valid_count", 0)
                from_std = el1_eval.get("traits_from_catalog", 0) or el1_eval.get("traits_from_standard", 0)

                if traits:
                    for trait in traits:
                        feedback += f"  \u2022 {trait}\n"

                # Исключённые признаки
                excluded = el1_eval.get("traits_excluded", [])
                if excluded:
                    feedback += "  <i>Исключены:</i>\n"
                    for ex in excluded:
                        t = ex.get("trait", "")
                        r = ex.get("reason", "")
                        feedback += f"  \u2796 {t}"
                        if r:
                            feedback += f" ({r})"
                        feedback += "\n"

                # Неверные
                invalid = el1_eval.get("invalid_traits", [])
                if invalid:
                    feedback += "  <i>Неверные:</i>\n"
                    for inv in invalid:
                        feedback += f"  \u274c {inv}\n"
                    feedback += (
                        "  \u26a0\ufe0f Наличие неверной позиции — "
                        "весь элемент 1 не засчитан.\n"
                    )

                feedback += (
                    f"  Верных: {valid_count}, из каталога признаков: {from_std}\n"
                )

                el1_comment = el1_eval.get("comment", "")
                if el1_comment:
                    feedback += f"  {el1_comment}\n"

            # Детали по элементу 2
            el2_eval = response.get("element2_evaluation", {})
            if el2_eval:
                feedback += "\n<b>Элемент 2 — Объяснение связи:</b>\n"

                author_ref = el2_eval.get("author_reference", "") or el2_eval.get("text_reference", "")
                student_ref = el2_eval.get("student_reference", "")
                if author_ref:
                    feedback += f"  Характеристика из текста: {author_ref}\n"
                if student_ref:
                    feedback += f"  Ученик ссылается на: {student_ref}\n"

                matches_text = el2_eval.get("matches_text", None)
                has_causal = el2_eval.get("has_causal_link", False)
                has_errors = el2_eval.get("has_errors", False)

                if matches_text is False:
                    feedback += "  \u274c Объяснение не привязано к характеристике из текста\n"

                if has_causal:
                    feedback += "  \u2705 Причинно-следственная связь: есть\n"
                else:
                    feedback += "  \u274c Причинно-следственная связь: нет\n"

                if has_errors:
                    errors = el2_eval.get("errors_found", [])
                    for err in errors:
                        feedback += f"  \u274c Ошибка: {err}\n"

                el2_comment = el2_eval.get("comment", "")
                if el2_comment:
                    feedback += f"  {el2_comment}\n"

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
            logger.error(f"Error parsing task18 AI response: {e}")
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
                "Опирайтесь на обществоведческие знания, а не только на текст",
                "Приводите конкретные примеры, а не общие фразы",
            ],
            factual_errors=[],
        )
