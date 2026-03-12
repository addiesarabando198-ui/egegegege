"""
Система подсчёта баллов для полного варианта ЕГЭ по обществознанию.

Первичные баллы:
  Часть 1 (задания 1-16):
    - Задания 1, 3, 9, 12 = 1 балл
    - Остальные (2,4,5,6,7,8,10,11,13,14,15,16) = 2 балла
    - Максимум: 4×1 + 12×2 = 28 баллов

  Часть 2 (задания 17-25):
    - Задание 17 = 2 балла
    - Задание 18 = 2 балла
    - Задание 19 = 3 балла
    - Задание 20 = 3 балла
    - Задание 21 = 3 балла
    - Задание 22 = 4 балла
    - Задание 23 = 3 балла
    - Задание 24 = 4 балла
    - Задание 25 = 6 балла
    - Максимум: 30 баллов

  Итого: 58 первичных баллов
"""

import logging
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Задания тестовой части, за которые ставится 1 балл
ONE_POINT_TASKS = {1, 3, 9, 12}

# Максимальные баллы за задания второй части
PART2_MAX_SCORES: Dict[int, int] = {
    17: 2,
    18: 2,
    19: 3,
    20: 3,
    21: 3,
    22: 4,
    23: 3,
    24: 4,
    25: 6,
}

MAX_PART1_SCORE = 28
MAX_PART2_SCORE = 30
MAX_TOTAL_SCORE = MAX_PART1_SCORE + MAX_PART2_SCORE  # 58

# Шкала перевода первичных баллов во вторичные (2025)
# Источник: шкала ФИПИ для ЕГЭ по обществознанию (58 первичных баллов)
PRIMARY_TO_SECONDARY: Dict[int, int] = {
    0: 0, 1: 2, 2: 4, 3: 6, 4: 8, 5: 10,
    6: 12, 7: 14, 8: 16, 9: 18, 10: 20,
    11: 22, 12: 24, 13: 26, 14: 28, 15: 30,
    16: 32, 17: 34, 18: 36, 19: 38, 20: 40,
    21: 42, 22: 43, 23: 44, 24: 45, 25: 46,
    26: 47, 27: 48, 28: 49, 29: 50, 30: 51,
    31: 52, 32: 53, 33: 54, 34: 55, 35: 56,
    36: 57, 37: 58, 38: 59, 39: 60, 40: 61,
    41: 62, 42: 64, 43: 66, 44: 68, 45: 70,
    46: 72, 47: 74, 48: 76, 49: 78, 50: 80,
    51: 82, 52: 84, 53: 86, 54: 88, 55: 91,
    56: 94, 57: 97, 58: 100,
}

# Пороговый балл для сдачи (минимальный вторичный)
MIN_PASSING_SECONDARY = 42
MIN_PASSING_PRIMARY = 21


def get_max_score_for_task(exam_number: int) -> int:
    """Максимальный первичный балл за задание."""
    if 1 <= exam_number <= 16:
        return 1 if exam_number in ONE_POINT_TASKS else 2
    return PART2_MAX_SCORES.get(exam_number, 0)


def calculate_part1_score(answers: Dict[int, bool]) -> Tuple[int, int]:
    """
    Подсчёт баллов тестовой части.

    Args:
        answers: {exam_number: is_correct} для заданий 1-16

    Returns:
        (набранные баллы, максимум)
    """
    score = 0
    for exam_num in range(1, 17):
        if answers.get(exam_num, False):
            score += get_max_score_for_task(exam_num)
    return score, MAX_PART1_SCORE


def calculate_part2_score(scores: Dict[int, int]) -> Tuple[int, int]:
    """
    Подсчёт баллов второй части.

    Args:
        scores: {task_number: набранные_баллы} для заданий 17-25

    Returns:
        (набранные баллы, максимум)
    """
    total = 0
    for task_num, max_score in PART2_MAX_SCORES.items():
        earned = scores.get(task_num, 0)
        total += min(earned, max_score)
    return total, MAX_PART2_SCORE


def primary_to_secondary(primary: int) -> int:
    """Перевод первичных баллов во вторичные по шкале ФИПИ."""
    primary = max(0, min(primary, MAX_TOTAL_SCORE))
    return PRIMARY_TO_SECONDARY.get(primary, 0)


def get_grade_description(secondary: int) -> Tuple[str, str]:
    """
    Оценка результата по вторичным баллам.

    Returns:
        (emoji, текст описания)
    """
    if secondary >= 80:
        return "\U0001f3c6", "Отличный результат! Вы отлично подготовлены к экзамену!"
    elif secondary >= 60:
        return "\U0001f44d", "Хороший результат! Продолжайте в том же духе."
    elif secondary >= MIN_PASSING_SECONDARY:
        return "\U0001f4da", "Неплохо, но есть над чем поработать."
    else:
        return "\U0001f4aa", "Требуется дополнительная подготовка. Не сдавайтесь!"


def format_results_summary(
    part1_answers: Dict[int, bool],
    part2_scores: Dict[int, int],
) -> str:
    """Формирует текстовую сводку результатов варианта."""
    p1_score, p1_max = calculate_part1_score(part1_answers)
    p2_score, p2_max = calculate_part2_score(part2_scores)
    total_primary = p1_score + p2_score
    secondary = primary_to_secondary(total_primary)
    emoji, description = get_grade_description(secondary)

    lines = [
        f"{emoji} <b>РЕЗУЛЬТАТЫ ВАРИАНТА ЕГЭ</b>\n",
        f"<b>Часть 1 (тестовая):</b> {p1_score}/{p1_max}",
    ]

    # Детализация по заданиям части 1
    part1_details = []
    for num in range(1, 17):
        max_s = get_max_score_for_task(num)
        if num in part1_answers:
            earned = max_s if part1_answers[num] else 0
            icon = "\u2705" if part1_answers[num] else "\u274c"
        else:
            earned = 0
            icon = "\u23ed\ufe0f"
        part1_details.append(f"  \u2116{num}: {icon} {earned}/{max_s}")
    lines.append("\n".join(part1_details))

    lines.append(f"\n<b>Часть 2 (развёрнутая):</b> {p2_score}/{p2_max}")

    # Детализация по заданиям части 2
    task_names = {
        17: "Анализ текста", 18: "Понятие из текста",
        19: "Примеры", 20: "Суждения", 21: "Графики",
        22: "Анализ ситуаций", 23: "Конституция",
        24: "Сложный план", 25: "Обоснование",
    }
    for num in sorted(PART2_MAX_SCORES):
        max_s = PART2_MAX_SCORES[num]
        earned = part2_scores.get(num, 0)
        name = task_names.get(num, f"Задание {num}")
        bar = "\u2588" * earned + "\u2591" * (max_s - earned)
        lines.append(f"  \u2116{num} ({name}): {bar} {earned}/{max_s}")

    lines.append("")
    lines.append(
        f"<b>Первичный балл:</b> {total_primary}/{MAX_TOTAL_SCORE}\n"
        f"<b>Вторичный балл:</b> {secondary}/100\n"
    )
    lines.append(description)

    passed = secondary >= MIN_PASSING_SECONDARY
    if passed:
        lines.append(f"\n\u2705 Порог сдачи ({MIN_PASSING_SECONDARY} баллов) пройден")
    else:
        lines.append(
            f"\n\u26a0\ufe0f Порог сдачи ({MIN_PASSING_SECONDARY} баллов) не пройден "
            f"(не хватает {MIN_PASSING_SECONDARY - secondary} б.)"
        )

    return "\n".join(lines)
