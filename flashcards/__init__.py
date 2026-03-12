"""
Модуль карточек (Flashcards) для заучивания материала ЕГЭ.

Поддерживает:
- Колоды карточек по Конституции РФ (задание 23)
- Глоссарий терминов по обществознанию
- Алгоритм интервального повторения SM-2
- Интеграция со стриками

Тяжёлые импорты (plugin, handlers) загружаются лениво,
чтобы FastAPI-сервер мог использовать flashcards.db / flashcards.sm2
без загрузки всей Telegram-инфраструктуры.
"""


def __getattr__(name):
    if name == "FlashcardsPlugin":
        from .plugin import FlashcardsPlugin
        return FlashcardsPlugin
    if name == "plugin":
        from .plugin import plugin
        return plugin
    if name == "init_flashcards_data":
        from .handlers import init_flashcards_data
        return init_flashcards_data
    raise AttributeError(f"module 'flashcards' has no attribute {name!r}")


__all__ = [
    'FlashcardsPlugin',
    'plugin',
    'init_flashcards_data',
]
