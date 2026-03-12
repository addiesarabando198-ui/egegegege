"""
Утилиты для валидации пользовательских вводов.

Защищает от:
- Чрезмерно длинных строк (DoS)
- Инъекций специальных символов
- Некорректных форматов данных
"""

import re
from typing import Optional, Tuple


# Константы для валидации
MAX_TEXT_LENGTH = 10000  # Максимальная длина текстового ввода (10KB)
MAX_TITLE_LENGTH = 200  # Максимальная длина названия задания
MAX_DESCRIPTION_LENGTH = 2000  # Максимальная длина описания
MAX_TEACHER_CODE_LENGTH = 15  # TEACH-XXXXXX = 12 символов + запас
MAX_PROMO_CODE_LENGTH = 20  # GIFT-XXXXXXXX + запас
MAX_COMMENT_LENGTH = 5000  # Максимальная длина комментария учителя
MAX_ANSWER_LENGTH = 50000  # Максимальная длина ответа ученика (50KB)


def validate_teacher_code(code: str) -> Tuple[bool, Optional[str]]:
    """
    Валидирует код учителя.

    Формат: TEACH-XXXXXX (6 символов A-Z0-9)

    Args:
        code: Код для проверки

    Returns:
        Tuple[bool, Optional[str]]: (валиден, сообщение об ошибке)

    Examples:
        >>> validate_teacher_code("TEACH-ABC123")
        (True, None)
        >>> validate_teacher_code("invalid")
        (False, "Неверный формат кода...")
    """
    if not code or not isinstance(code, str):
        return False, "Код не может быть пустым"

    # Проверка длины
    if len(code) > MAX_TEACHER_CODE_LENGTH:
        return False, f"Код слишком длинный (макс. {MAX_TEACHER_CODE_LENGTH} символов)"

    # Приводим к upper case для проверки
    code = code.strip().upper()

    # Проверка формата TEACH-XXXXXX
    pattern = r'^TEACH-[A-Z0-9]{6}$'
    if not re.match(pattern, code):
        return False, "Неверный формат кода. Должно быть: TEACH-XXXXXX (6 символов A-Z, 0-9)"

    return True, None


def validate_text_input(
    text: str,
    field_name: str = "Текст",
    min_length: int = 1,
    max_length: int = MAX_TEXT_LENGTH,
    allow_empty: bool = False
) -> Tuple[bool, Optional[str]]:
    """
    Валидирует текстовый ввод пользователя.

    Args:
        text: Текст для проверки
        field_name: Название поля (для сообщения об ошибке)
        min_length: Минимальная длина
        max_length: Максимальная длина
        allow_empty: Разрешить пустые строки

    Returns:
        Tuple[bool, Optional[str]]: (валиден, сообщение об ошибке)
    """
    if not isinstance(text, str):
        return False, f"{field_name} должен быть строкой"

    # Проверка на пустоту
    if not text.strip() and not allow_empty:
        return False, f"{field_name} не может быть пустым"

    # Проверка длины
    text_length = len(text)

    if text_length < min_length:
        return False, f"{field_name} слишком короткий (мин. {min_length} символов)"

    if text_length > max_length:
        return False, f"{field_name} слишком длинный (макс. {max_length} символов)"

    return True, None


def validate_assignment_title(title: str) -> Tuple[bool, Optional[str]]:
    """
    Валидирует название домашнего задания.

    Args:
        title: Название задания

    Returns:
        Tuple[bool, Optional[str]]: (валидно, сообщение об ошибке)
    """
    return validate_text_input(
        title,
        field_name="Название задания",
        min_length=3,
        max_length=MAX_TITLE_LENGTH
    )


def validate_assignment_description(description: str) -> Tuple[bool, Optional[str]]:
    """
    Валидирует описание домашнего задания.

    Args:
        description: Описание задания

    Returns:
        Tuple[bool, Optional[str]]: (валидно, сообщение об ошибке)
    """
    return validate_text_input(
        description,
        field_name="Описание",
        min_length=0,
        max_length=MAX_DESCRIPTION_LENGTH,
        allow_empty=True
    )


def validate_teacher_comment(comment: str) -> Tuple[bool, Optional[str]]:
    """
    Валидирует комментарий учителя к ответу ученика.

    Args:
        comment: Комментарий

    Returns:
        Tuple[bool, Optional[str]]: (валиден, сообщение об ошибке)
    """
    return validate_text_input(
        comment,
        field_name="Комментарий",
        min_length=1,
        max_length=MAX_COMMENT_LENGTH
    )


def validate_student_answer(answer: str) -> Tuple[bool, Optional[str]]:
    """
    Валидирует ответ ученика на вопрос.

    Args:
        answer: Ответ ученика

    Returns:
        Tuple[bool, Optional[str]]: (валиден, сообщение об ошибке)
    """
    return validate_text_input(
        answer,
        field_name="Ответ",
        min_length=1,
        max_length=MAX_ANSWER_LENGTH
    )


def validate_promo_code(code: str) -> Tuple[bool, Optional[str]]:
    """
    Валидирует промокод.

    Формат: GIFT-XXXXXXXX (8 символов A-Z0-9)

    Args:
        code: Промокод для проверки

    Returns:
        Tuple[bool, Optional[str]]: (валиден, сообщение об ошибке)
    """
    if not code or not isinstance(code, str):
        return False, "Промокод не может быть пустым"

    # Проверка длины
    if len(code) > MAX_PROMO_CODE_LENGTH:
        return False, f"Промокод слишком длинный (макс. {MAX_PROMO_CODE_LENGTH} символов)"

    # Приводим к upper case для проверки
    code = code.strip().upper()

    # Проверка формата GIFT-XXXXXXXX
    pattern = r'^GIFT-[A-Z0-9]{8}$'
    if not re.match(pattern, code):
        return False, "Неверный формат промокода. Должно быть: GIFT-XXXXXXXX (8 символов A-Z, 0-9)"

    return True, None


def sanitize_html(text: str) -> str:
    """
    Удаляет потенциально опасные HTML теги из текста.

    Оставляет только безопасные теги: <b>, <i>, <code>, <pre>

    Args:
        text: Текст для очистки

    Returns:
        str: Очищенный текст
    """
    if not text:
        return ""

    # Разрешенные теги Telegram HTML
    allowed_tags = ['b', 'strong', 'i', 'em', 'code', 'pre', 'u', 's']

    # Убираем все теги кроме разрешенных
    # Это упрощенная версия - для production лучше использовать библиотеку типа bleach
    import html
    text = html.escape(text)

    # Возвращаем разрешенные теги
    for tag in allowed_tags:
        text = text.replace(f'&lt;{tag}&gt;', f'<{tag}>')
        text = text.replace(f'&lt;/{tag}&gt;', f'</{tag}>')

    return text


def validate_positive_integer(
    value: str,
    field_name: str = "Число",
    min_value: int = 1,
    max_value: int = 1000000
) -> Tuple[bool, Optional[str], Optional[int]]:
    """
    Валидирует положительное целое число.

    Args:
        value: Строка с числом
        field_name: Название поля
        min_value: Минимальное значение
        max_value: Максимальное значение

    Returns:
        Tuple[bool, Optional[str], Optional[int]]: (валидно, сообщение об ошибке, parsed число)
    """
    try:
        num = int(value)
    except (ValueError, TypeError):
        return False, f"{field_name} должно быть целым числом", None

    if num < min_value:
        return False, f"{field_name} должно быть не менее {min_value}", None

    if num > max_value:
        return False, f"{field_name} должно быть не более {max_value}", None

    return True, None, num
