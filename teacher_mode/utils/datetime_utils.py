"""
Утилиты для безопасной работы с датами и временем.

Все функции гарантируют использование timezone-aware datetime объектов
для предотвращения ошибок сравнения и хранения дат.
"""

from datetime import datetime, timezone
from typing import Optional


def utc_now() -> datetime:
    """
    Возвращает текущее время в UTC с timezone информацией.

    Использовать вместо datetime.now() для обеспечения
    консистентности временных зон во всем приложении.

    Returns:
        datetime: Timezone-aware datetime объект в UTC

    Examples:
        >>> now = utc_now()
        >>> now.tzinfo is not None
        True
    """
    return datetime.now(timezone.utc)


def ensure_timezone_aware(dt: Optional[datetime], default_tz: timezone = timezone.utc) -> Optional[datetime]:
    """
    Гарантирует, что datetime объект имеет информацию о временной зоне.

    Если объект naive (без timezone), добавляет указанную временную зону.
    Если объект уже timezone-aware, возвращает без изменений.

    Args:
        dt: datetime объект для проверки
        default_tz: Временная зона по умолчанию (UTC)

    Returns:
        datetime: Timezone-aware datetime или None если входной параметр None

    Examples:
        >>> naive_dt = datetime(2024, 1, 1, 12, 0, 0)
        >>> aware_dt = ensure_timezone_aware(naive_dt)
        >>> aware_dt.tzinfo is not None
        True
    """
    if dt is None:
        return None

    if dt.tzinfo is None:
        return dt.replace(tzinfo=default_tz)

    return dt


def parse_datetime_safe(dt_string: Optional[str]) -> Optional[datetime]:
    """
    Безопасно парсит строку в timezone-aware datetime.

    Поддерживает форматы:
    - ISO 8601 с timezone (2024-01-01T12:00:00+00:00)
    - ISO 8601 без timezone (2024-01-01T12:00:00) - добавляется UTC
    - ISO 8601 с Z суффиксом (2024-01-01T12:00:00Z)

    Args:
        dt_string: Строка с датой для парсинга

    Returns:
        datetime: Timezone-aware datetime или None если парсинг не удался

    Examples:
        >>> dt = parse_datetime_safe("2024-01-01T12:00:00")
        >>> dt.tzinfo is not None
        True
    """
    if not dt_string:
        return None

    try:
        # Заменяем Z на +00:00 для корректного парсинга
        dt_string = dt_string.replace('Z', '+00:00')
        dt = datetime.fromisoformat(dt_string)
        return ensure_timezone_aware(dt)
    except (ValueError, AttributeError):
        return None


def datetime_to_iso(dt: Optional[datetime]) -> Optional[str]:
    """
    Конвертирует datetime в ISO формат строки.

    Автоматически гарантирует timezone-aware формат.

    Args:
        dt: datetime объект для конвертации

    Returns:
        str: ISO формат строки или None если dt is None

    Examples:
        >>> dt = utc_now()
        >>> iso_str = datetime_to_iso(dt)
        >>> '+' in iso_str or 'Z' in iso_str
        True
    """
    if dt is None:
        return None

    # Убеждаемся что datetime timezone-aware
    dt = ensure_timezone_aware(dt)
    return dt.isoformat()
