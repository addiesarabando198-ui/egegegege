"""
Реализация алгоритма SM-2 (SuperMemo 2) для интервального повторения.

Алгоритм SM-2 определяет оптимальные интервалы повторения карточек
на основе самооценки пользователя. Карточки, которые пользователь
помнит хуже, показываются чаще.

Оценки пользователя:
- 0 (again): Не помню совсем → интервал сбрасывается
- 1 (hard): Сложно, вспомнил с трудом → короткий интервал
- 2 (good): Помню → нормальный интервал
- 3 (easy): Легко → увеличенный интервал
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Tuple


# Маппинг пользовательских оценок (0-3) в SM-2 quality (0-5)
QUALITY_MAP = {
    0: 0,  # again → полный провал
    1: 2,  # hard → правильный, но с серьёзными затруднениями
    2: 4,  # good → правильный, с небольшими затруднениями
    3: 5,  # easy → идеальный ответ
}

# Минимальный easiness factor
MIN_EF = 1.3

# Начальный easiness factor
DEFAULT_EF = 2.5


@dataclass
class ReviewResult:
    """Результат пересчёта параметров карточки после повторения."""
    interval_days: int
    easiness_factor: float
    repetition_number: int
    next_review: datetime


def calculate_sm2(
    quality: int,
    repetition_number: int,
    easiness_factor: float,
    interval_days: int,
) -> Tuple[int, float, int]:
    """
    Пересчитывает параметры SM-2 после оценки.

    Args:
        quality: Оценка пользователя (0-3), маппится в SM-2 quality (0-5)
        repetition_number: Текущий номер повторения
        easiness_factor: Текущий EF (easiness factor)
        interval_days: Текущий интервал в днях

    Returns:
        (new_interval, new_ef, new_repetition_number)
    """
    # Маппим оценку пользователя в SM-2 quality
    q = QUALITY_MAP.get(quality, 0)

    # Обновляем EF (easiness factor)
    new_ef = easiness_factor + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    new_ef = max(MIN_EF, new_ef)

    if q < 3:
        # Ответ неудовлетворительный — сбрасываем повторения
        new_repetition = 0
        new_interval = 1
    else:
        # Ответ удовлетворительный — рассчитываем новый интервал
        new_repetition = repetition_number + 1

        if new_repetition == 1:
            new_interval = 1
        elif new_repetition == 2:
            new_interval = 6
        else:
            new_interval = round(interval_days * new_ef)

    # Корректируем интервал по оценке
    if quality == 3:  # easy — бонус к интервалу
        new_interval = round(new_interval * 1.3)
    elif quality == 1:  # hard — штраф к интервалу
        new_interval = max(1, round(new_interval * 0.6))

    # Ограничиваем максимальный интервал 180 днями
    new_interval = min(new_interval, 180)

    return new_interval, new_ef, new_repetition


def review_card(
    quality: int,
    repetition_number: int,
    easiness_factor: float,
    interval_days: int,
) -> ReviewResult:
    """
    Обёртка над calculate_sm2 с расчётом даты следующего повторения.

    Args:
        quality: Оценка пользователя (0-3)
        repetition_number: Текущий номер повторения
        easiness_factor: Текущий EF
        interval_days: Текущий интервал в днях

    Returns:
        ReviewResult с новыми параметрами и датой следующего повторения
    """
    new_interval, new_ef, new_rep = calculate_sm2(
        quality, repetition_number, easiness_factor, interval_days
    )

    next_review = datetime.now(timezone.utc) + timedelta(days=new_interval)

    return ReviewResult(
        interval_days=new_interval,
        easiness_factor=new_ef,
        repetition_number=new_rep,
        next_review=next_review,
    )
