"""
Простой тест для проверки OCR функционала.
Этот файл можно удалить после тестирования.
"""
import asyncio
import os
import sys

# Добавляем корневую директорию в путь для импортов
sys.path.insert(0, os.path.dirname(__file__))

from core.vision_service import VisionService, VisionConfig


async def test_vision_service():
    """Тест инициализации VisionService"""

    print("=" * 60)
    print("Тестирование OCR функционала")
    print("=" * 60)

    # Тест 1: Инициализация без credentials (должен быть недоступен)
    print("\n1. Проверка инициализации без credentials...")
    service = VisionService()

    if service.is_available:
        print("❌ Ошибка: Сервис доступен без credentials")
    else:
        print("✅ OK: Сервис корректно определяет отсутствие credentials")

    # Тест 2: Проверка с fake credentials
    print("\n2. Проверка инициализации с credentials...")
    config = VisionConfig(
        api_key="test_key",
        folder_id="test_folder"
    )
    service_with_config = VisionService(config)

    if service_with_config.is_available:
        print("✅ OK: Сервис доступен с credentials")
    else:
        print("❌ Ошибка: Сервис недоступен с credentials")

    print("\n" + "=" * 60)
    print("Тесты завершены!")
    print("=" * 60)
    print("\nДля полного тестирования OCR:")
    print("1. Установите переменные окружения YANDEX_GPT_API_KEY и YANDEX_GPT_FOLDER_ID")
    print("2. Запустите бота и отправьте фотографию с текстом в одном из модулей")
    print("   - Task 19: Примеры")
    print("   - Task 20: Суждения")
    print("   - Task 24: План")
    print("   - Task 25: Развернутый ответ")
    print()


if __name__ == "__main__":
    asyncio.run(test_vision_service())
