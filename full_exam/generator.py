"""
Генератор полного варианта ЕГЭ по обществознанию.

Создаёт вариант из 25 заданий:
  - Часть 1 (тестовая): задания 1-16
  - Часть 2 (развёрнутая): задания 17-25

Правила подбора заданий второй части:
  1. Темы не должны дублироваться
  2. Желательно использовать разные блоки для разных заданий
  3. Задания 17 и 18 основаны на общем тексте
  4. Задания 24 и 25 должны быть тематически связаны (один подтопик)
  5. Задания 21 и 23 не имеют блоков — выбираются случайно
"""

import json
import os
import random
import logging
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Any, Optional, Tuple, Set
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ALL_BLOCKS = [
    "Человек и общество",
    "Экономика",
    "Социальные отношения",
    "Политика",
    "Право",
]


@dataclass
class ExamTask:
    """Одно задание в варианте."""
    exam_number: int          # Номер задания ЕГЭ (1-16, 17-25)
    source_module: str        # Модуль-источник: test_part, task19, ...
    task_data: Dict[str, Any] # Полные данные задания
    block: Optional[str] = None
    title: Optional[str] = None


@dataclass
class ExamVariant:
    """Полный сгенерированный вариант ЕГЭ."""
    variant_id: str
    tasks: Dict[int, ExamTask] = field(default_factory=dict)  # exam_number -> ExamTask
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_task(self, exam_number: int) -> Optional[ExamTask]:
        return self.tasks.get(exam_number)

    def set_task(self, exam_number: int, task: ExamTask):
        self.tasks[exam_number] = task

    @property
    def part1_tasks(self) -> Dict[int, ExamTask]:
        return {n: t for n, t in self.tasks.items() if 1 <= n <= 16}

    @property
    def part2_tasks(self) -> Dict[int, ExamTask]:
        return {n: t for n, t in self.tasks.items() if 17 <= n <= 25}

    @property
    def total_tasks(self) -> int:
        return len(self.tasks)

    def to_dict(self) -> Dict[str, Any]:
        """Сериализация для хранения в БД / assignment_data."""
        result = {
            "variant_id": self.variant_id,
            "metadata": self.metadata,
            "tasks": {},
        }
        for num, task in self.tasks.items():
            result["tasks"][str(num)] = {
                "exam_number": task.exam_number,
                "source_module": task.source_module,
                "task_data": task.task_data,
                "block": task.block,
                "title": task.title,
            }
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExamVariant":
        """Десериализация из словаря."""
        variant = cls(
            variant_id=data["variant_id"],
            metadata=data.get("metadata", {}),
        )
        for num_str, task_info in data.get("tasks", {}).items():
            variant.tasks[int(num_str)] = ExamTask(
                exam_number=task_info["exam_number"],
                source_module=task_info["source_module"],
                task_data=task_info["task_data"],
                block=task_info.get("block"),
                title=task_info.get("title"),
            )
        return variant


# ──────────────────────────────────────────────────────────────
# Загрузка данных
# ──────────────────────────────────────────────────────────────

def _load_json(path: str) -> Any:
    """Загрузка JSON-файла с обработкой ошибок."""
    full_path = os.path.join(BASE_DIR, path)
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка загрузки {full_path}: {e}")
        return None


def _load_test_part_questions() -> List[Dict[str, Any]]:
    """Загрузка вопросов тестовой части."""
    data = _load_json("data/questions.json")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        all_q = []
        for block_topics in data.values():
            if isinstance(block_topics, dict):
                for topic_questions in block_topics.values():
                    if isinstance(topic_questions, list):
                        all_q.extend(topic_questions)
        return all_q
    return []


def _load_text_passages_17_18() -> List[Dict[str, Any]]:
    """Загрузка текстовых отрывков для заданий 17 и 18."""
    data = _load_json("data/text_passages_17_18.json")
    if isinstance(data, dict):
        return data.get("passages", [])
    return []


def _load_task19_topics() -> List[Dict[str, Any]]:
    """Загрузка тем задания 19."""
    data = _load_json("task19/task19_topics.json")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("topics", [])
    return []


def _load_task20_topics() -> List[Dict[str, Any]]:
    """Загрузка тем задания 20."""
    data = _load_json("task20/task20_topics.json")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("topics", [])
    return []


def _load_task21_questions() -> List[Dict[str, Any]]:
    """Загрузка заданий 21 (графики — без блоков)."""
    data = _load_json("task21/task21_questions.json")
    if isinstance(data, dict):
        return data.get("tasks", data.get("questions", []))
    if isinstance(data, list):
        return data
    return []


def _load_task22_tasks() -> List[Dict[str, Any]]:
    """Загрузка заданий 22 (анализ ситуаций)."""
    data = _load_json("task22/task22_topics.json")
    if isinstance(data, dict):
        return data.get("tasks", [])
    if isinstance(data, list):
        return data
    return []


def _load_task23_questions() -> List[Dict[str, Any]]:
    """Загрузка заданий 23 (Конституция — без блоков)."""
    data = _load_json("data/task23_questions.json")
    if isinstance(data, dict):
        return data.get("questions", [])
    if isinstance(data, list):
        return data
    return []


def _load_task24_plans() -> Tuple[Dict[str, Any], Dict[str, List[str]]]:
    """
    Загрузка планов задания 24.
    Returns: (plans_data, blocks_data)
    """
    data = _load_json("data/plans_data_with_blocks.json")
    if not isinstance(data, dict):
        return {}, {}
    plans = data.get("plans", {})
    blocks = data.get("blocks", {})
    return plans, blocks


def _load_task25_topics() -> List[Dict[str, Any]]:
    """Загрузка тем задания 25."""
    data = _load_json("task25/task25_topics.json")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("topics", [])
    return []


# ──────────────────────────────────────────────────────────────
# Связывание тем задания 24 и 25
# ──────────────────────────────────────────────────────────────

def _title_similarity(title_a: str, title_b: str) -> float:
    """
    Вычисляет сходство двух названий тем.
    Использует SequenceMatcher + бонус за общие ключевые слова.
    """
    a_lower = title_a.lower().strip()
    b_lower = title_b.lower().strip()

    # Точное совпадение
    if a_lower == b_lower:
        return 1.0

    # Одно содержит другое
    if a_lower in b_lower or b_lower in a_lower:
        return 0.9

    # SequenceMatcher
    seq_ratio = SequenceMatcher(None, a_lower, b_lower).ratio()

    # Бонус за общие значимые слова (> 3 символов)
    stop_words = {"как", "для", "его", "что", "при", "она", "они", "это", "так", "все"}
    words_a = {w for w in a_lower.split() if len(w) > 3 and w not in stop_words}
    words_b = {w for w in b_lower.split() if len(w) > 3 and w not in stop_words}
    common = words_a & words_b
    if words_a and words_b:
        word_overlap = len(common) / min(len(words_a), len(words_b))
    else:
        word_overlap = 0.0

    return 0.5 * seq_ratio + 0.5 * word_overlap


def _find_linked_pair_24_25(
    plans: Dict[str, Any],
    blocks_24: Dict[str, List[str]],
    topics_25: List[Dict[str, Any]],
    preferred_block: Optional[str] = None,
) -> Optional[Tuple[Dict[str, Any], Dict[str, Any], str]]:
    """
    Находит тематически связанную пару задания 24 и 25.

    Returns:
        (task24_data, task25_data, block) или None
    """
    # Группируем task25 по блокам
    t25_by_block: Dict[str, List[Dict[str, Any]]] = {}
    for topic in topics_25:
        block = topic.get("block", "")
        t25_by_block.setdefault(block, []).append(topic)

    # Определяем блоки для поиска
    search_blocks = [preferred_block] if preferred_block else list(blocks_24.keys())
    random.shuffle(search_blocks)

    best_pair = None
    best_score = -1.0

    for block in search_blocks:
        task24_topics = blocks_24.get(block, [])
        task25_in_block = t25_by_block.get(block, [])
        if not task24_topics or not task25_in_block:
            continue

        # Пробуем найти лучшую пару в этом блоке
        sampled_24 = random.sample(task24_topics, min(len(task24_topics), 15))
        for t24_name in sampled_24:
            plan_data = plans.get(t24_name)
            if not plan_data:
                continue

            for t25 in task25_in_block:
                t25_title = t25.get("title", "")
                score = _title_similarity(t24_name, t25_title)
                if score > best_score:
                    best_score = score
                    task24_out = {
                        "topic_name": t24_name,
                        "plan_data": plan_data,
                        "block": block,
                    }
                    best_pair = (task24_out, t25, block)

        # Если нашли хорошую пару (> 0.4), используем её
        if best_score >= 0.4:
            break

    return best_pair


# ──────────────────────────────────────────────────────────────
# Генерация варианта
# ──────────────────────────────────────────────────────────────

def generate_variant(variant_id: Optional[str] = None) -> ExamVariant:
    """
    Генерирует полный вариант ЕГЭ.

    Args:
        variant_id: ID варианта (генерируется автоматически если не указан)

    Returns:
        ExamVariant со всеми 23 заданиями
    """
    if not variant_id:
        variant_id = f"var_{random.randint(100000, 999999)}"

    variant = ExamVariant(variant_id=variant_id)

    # === Часть 1: тестовые задания 1-16 ===
    _generate_part1(variant)

    # === Часть 2: развёрнутые задания 17-25 ===
    _generate_part2(variant)

    variant.metadata["total_generated"] = variant.total_tasks
    variant.metadata["part1_count"] = len(variant.part1_tasks)
    variant.metadata["part2_count"] = len(variant.part2_tasks)

    logger.info(
        f"Вариант {variant_id} сгенерирован: "
        f"{len(variant.part1_tasks)} тестовых + {len(variant.part2_tasks)} развёрнутых"
    )
    return variant


def _generate_part1(variant: ExamVariant):
    """Генерация тестовой части (задания 1-16)."""
    questions = _load_test_part_questions()
    if not questions:
        logger.error("Не удалось загрузить вопросы тестовой части")
        return

    # Группируем по exam_number
    by_exam_num: Dict[int, List[Dict[str, Any]]] = {}
    for q in questions:
        num = q.get("exam_number")
        if num and 1 <= num <= 16:
            by_exam_num.setdefault(num, []).append(q)

    for exam_num in range(1, 17):
        pool = by_exam_num.get(exam_num, [])
        if pool:
            chosen = random.choice(pool)
            variant.set_task(exam_num, ExamTask(
                exam_number=exam_num,
                source_module="test_part",
                task_data=chosen,
                block=chosen.get("block"),
                title=chosen.get("topic"),
            ))
        else:
            logger.warning(f"Нет вопросов для задания №{exam_num}")


def _generate_part2(variant: ExamVariant):
    """
    Генерация второй части (задания 17-25).

    Алгоритм:
    1. Загружаем все данные
    2. Выбираем текстовый отрывок для заданий 17 и 18 (общий текст)
    3. Выбираем связанную пару 24+25
    4. Распределяем оставшиеся блоки для 19, 20, 22
    5. Задания 21 и 23 — случайно (без блоков)
    """
    # Загрузка данных
    passages_17_18 = _load_text_passages_17_18()
    topics_19 = _load_task19_topics()
    topics_20 = _load_task20_topics()
    questions_21 = _load_task21_questions()
    tasks_22 = _load_task22_tasks()
    questions_23 = _load_task23_questions()
    plans_24, blocks_24 = _load_task24_plans()
    topics_25 = _load_task25_topics()

    used_titles: Set[str] = set()
    used_blocks: Set[str] = set()

    # ── Шаг 0: Задания 17 + 18 (общий текст) ──
    if passages_17_18:
        passage = random.choice(passages_17_18)
        passage_block = passage.get("block")

        # Задание 17
        if "task17" in passage:
            t17_data = {
                "text": passage["text"],
                "source": passage.get("source", ""),
                "passage_id": passage.get("id"),
                **passage["task17"],
            }
            variant.set_task(17, ExamTask(
                exam_number=17,
                source_module="task17",
                task_data=t17_data,
                block=passage_block,
                title=f"Текст: {passage.get('source', '')}",
            ))

        # Задание 18
        if "task18" in passage:
            t18_data = {
                "text": passage["text"],
                "source": passage.get("source", ""),
                "passage_id": passage.get("id"),
                **passage["task18"],
            }
            variant.set_task(18, ExamTask(
                exam_number=18,
                source_module="task18",
                task_data=t18_data,
                block=passage_block,
                title=f"Понятие: {passage['task18'].get('concept', '')}",
            ))

        if passage_block:
            used_blocks.add(passage_block)
    else:
        logger.warning("Нет текстовых отрывков для заданий 17-18")

    # ── Шаг 1: Связанная пара 24 + 25 ──
    pair = _find_linked_pair_24_25(plans_24, blocks_24, topics_25)
    if pair:
        t24_data, t25_data, pair_block = pair

        variant.set_task(24, ExamTask(
            exam_number=24,
            source_module="task24",
            task_data=t24_data,
            block=pair_block,
            title=t24_data.get("topic_name"),
        ))
        used_titles.add(t24_data.get("topic_name", "").lower())
        used_blocks.add(pair_block)

        variant.set_task(25, ExamTask(
            exam_number=25,
            source_module="task25",
            task_data=t25_data,
            block=pair_block,
            title=t25_data.get("title"),
        ))
        used_titles.add(t25_data.get("title", "").lower())
        # Не добавляем pair_block повторно — пара 24+25 делит один блок
    else:
        logger.warning("Не удалось найти связанную пару 24+25, выбираем случайно")
        _pick_random_task24(variant, plans_24, blocks_24, used_titles, used_blocks)
        _pick_random_task25(variant, topics_25, used_titles, used_blocks)

    # ── Шаг 2: Задания 19, 20, 22 — из разных блоков ──
    available_blocks = [b for b in ALL_BLOCKS if b not in used_blocks]
    random.shuffle(available_blocks)

    # Задания с блоками, которые нужно распределить
    block_tasks = [
        (19, topics_19, "task19"),
        (20, topics_20, "task20"),
        (22, tasks_22, "task22"),
    ]

    for i, (task_num, topics, module) in enumerate(block_tasks):
        chosen = _pick_topic_from_pool(
            topics, available_blocks, used_titles, preferred_index=i
        )
        if chosen:
            block = chosen.get("block", "")
            title = chosen.get("title", chosen.get("topic_name", ""))
            variant.set_task(task_num, ExamTask(
                exam_number=task_num,
                source_module=module,
                task_data=chosen,
                block=block,
                title=title,
            ))
            used_titles.add(title.lower())
            if block:
                used_blocks.add(block)
                if block in available_blocks:
                    available_blocks.remove(block)
        else:
            # Фолбэк: случайный выбор без ограничений по блоку
            if topics:
                chosen = random.choice(topics)
                variant.set_task(task_num, ExamTask(
                    exam_number=task_num,
                    source_module=module,
                    task_data=chosen,
                    block=chosen.get("block"),
                    title=chosen.get("title", ""),
                ))

    # ── Шаг 3: Задание 21 (графики) — без блоков ──
    if questions_21:
        chosen_21 = random.choice(questions_21)
        variant.set_task(21, ExamTask(
            exam_number=21,
            source_module="task21",
            task_data=chosen_21,
            block=None,
            title=chosen_21.get("market_name", ""),
        ))

    # ── Шаг 4: Задание 23 (Конституция) — без блоков ──
    if questions_23:
        chosen_23 = random.choice(questions_23)
        variant.set_task(23, ExamTask(
            exam_number=23,
            source_module="task23",
            task_data=chosen_23,
            block=None,
            title=chosen_23.get("id", ""),
        ))


def _pick_topic_from_pool(
    topics: List[Dict[str, Any]],
    preferred_blocks: List[str],
    used_titles: Set[str],
    preferred_index: int = 0,
) -> Optional[Dict[str, Any]]:
    """
    Выбирает тему из пула, предпочитая указанный блок и избегая дубликатов.
    """
    # Пробуем предпочтительный блок
    if preferred_index < len(preferred_blocks):
        target_block = preferred_blocks[preferred_index]
        candidates = [
            t for t in topics
            if t.get("block") == target_block
            and t.get("title", "").lower() not in used_titles
        ]
        if candidates:
            return random.choice(candidates)

    # Пробуем любой неиспользованный блок
    for block in preferred_blocks:
        candidates = [
            t for t in topics
            if t.get("block") == block
            and t.get("title", "").lower() not in used_titles
        ]
        if candidates:
            return random.choice(candidates)

    # Фолбэк: любая тема с неиспользованным заголовком
    candidates = [
        t for t in topics
        if t.get("title", "").lower() not in used_titles
    ]
    if candidates:
        return random.choice(candidates)

    return None


def _pick_random_task24(
    variant: ExamVariant,
    plans: Dict[str, Any],
    blocks: Dict[str, List[str]],
    used_titles: Set[str],
    used_blocks: Set[str],
):
    """Случайный выбор задания 24."""
    all_topics = []
    for block, topic_names in blocks.items():
        for name in topic_names:
            if name.lower() not in used_titles:
                all_topics.append((name, block))
    if all_topics:
        name, block = random.choice(all_topics)
        plan_data = plans.get(name, {})
        variant.set_task(24, ExamTask(
            exam_number=24,
            source_module="task24",
            task_data={"topic_name": name, "plan_data": plan_data, "block": block},
            block=block,
            title=name,
        ))
        used_titles.add(name.lower())
        used_blocks.add(block)


def _pick_random_task25(
    variant: ExamVariant,
    topics: List[Dict[str, Any]],
    used_titles: Set[str],
    used_blocks: Set[str],
):
    """Случайный выбор задания 25."""
    candidates = [t for t in topics if t.get("title", "").lower() not in used_titles]
    if candidates:
        chosen = random.choice(candidates)
        variant.set_task(25, ExamTask(
            exam_number=25,
            source_module="task25",
            task_data=chosen,
            block=chosen.get("block"),
            title=chosen.get("title"),
        ))
        used_titles.add(chosen.get("title", "").lower())
        if chosen.get("block"):
            used_blocks.add(chosen["block"])


def replace_task_in_variant(
    variant: ExamVariant,
    exam_number: int,
) -> bool:
    """
    Заменяет задание в варианте на другое (для учителя).
    Сохраняет ограничения по блокам и дубликатам.

    Returns:
        True если замена прошла успешно
    """
    old_task = variant.get_task(exam_number)
    if not old_task:
        return False

    # Собираем использованные заголовки (исключая текущее задание)
    used_titles = set()
    used_blocks = set()
    for num, task in variant.tasks.items():
        if num != exam_number:
            if task.title:
                used_titles.add(task.title.lower())
            if task.block and num not in (21, 23):
                used_blocks.add(task.block)

    # Для заданий части 1
    if 1 <= exam_number <= 16:
        questions = _load_test_part_questions()
        candidates = [
            q for q in questions
            if q.get("exam_number") == exam_number
            and q.get("id") != old_task.task_data.get("id")
        ]
        if candidates:
            chosen = random.choice(candidates)
            variant.set_task(exam_number, ExamTask(
                exam_number=exam_number,
                source_module="test_part",
                task_data=chosen,
                block=chosen.get("block"),
                title=chosen.get("topic"),
            ))
            return True

    # Замена заданий 17 и 18 (общий текст — заменяем оба)
    if exam_number in (17, 18):
        passages = _load_text_passages_17_18()
        old_passage_id = old_task.task_data.get("passage_id")
        candidates = [p for p in passages if p.get("id") != old_passage_id]
        if candidates:
            passage = random.choice(candidates)
            passage_block = passage.get("block")
            if "task17" in passage:
                t17_data = {
                    "text": passage["text"],
                    "source": passage.get("source", ""),
                    "passage_id": passage.get("id"),
                    **passage["task17"],
                }
                variant.set_task(17, ExamTask(
                    exam_number=17,
                    source_module="task17",
                    task_data=t17_data,
                    block=passage_block,
                    title=f"Текст: {passage.get('source', '')}",
                ))
            if "task18" in passage:
                t18_data = {
                    "text": passage["text"],
                    "source": passage.get("source", ""),
                    "passage_id": passage.get("id"),
                    **passage["task18"],
                }
                variant.set_task(18, ExamTask(
                    exam_number=18,
                    source_module="task18",
                    task_data=t18_data,
                    block=passage_block,
                    title=f"Понятие: {passage['task18'].get('concept', '')}",
                ))
            return True
        return False

    # Для заданий второй части
    loaders = {
        19: (_load_task19_topics, "task19"),
        20: (_load_task20_topics, "task20"),
        21: (_load_task21_questions, "task21"),
        22: (_load_task22_tasks, "task22"),
        23: (_load_task23_questions, "task23"),
    }

    if exam_number in loaders:
        loader_fn, module = loaders[exam_number]
        pool = loader_fn()
        old_id = old_task.task_data.get("id")
        candidates = [
            t for t in pool
            if t.get("id") != old_id
            and t.get("title", "").lower() not in used_titles
        ]
        if candidates:
            chosen = random.choice(candidates)
            variant.set_task(exam_number, ExamTask(
                exam_number=exam_number,
                source_module=module,
                task_data=chosen,
                block=chosen.get("block"),
                title=chosen.get("title", chosen.get("market_name", "")),
            ))
            return True

    if exam_number == 24:
        plans, blocks = _load_task24_plans()
        all_topics = []
        for block, names in blocks.items():
            for name in names:
                if name.lower() not in used_titles:
                    all_topics.append((name, block))
        if all_topics:
            name, block = random.choice(all_topics)
            variant.set_task(24, ExamTask(
                exam_number=24,
                source_module="task24",
                task_data={"topic_name": name, "plan_data": plans.get(name, {}), "block": block},
                block=block,
                title=name,
            ))
            return True

    if exam_number == 25:
        topics = _load_task25_topics()
        candidates = [
            t for t in topics
            if t.get("title", "").lower() not in used_titles
            and t.get("id") != old_task.task_data.get("id")
        ]
        if candidates:
            chosen = random.choice(candidates)
            variant.set_task(25, ExamTask(
                exam_number=25,
                source_module="task25",
                task_data=chosen,
                block=chosen.get("block"),
                title=chosen.get("title"),
            ))
            return True

    return False
