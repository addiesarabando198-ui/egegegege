"""
Конфигурация pytest для тестов teacher_mode.

Настраивает окружение для запуска тестов без реального бота.
"""

import os
import sys
from pathlib import Path

# Добавляем корневую директорию проекта в PYTHONPATH
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Устанавливаем фейковый токен для тестов
os.environ['TELEGRAM_BOT_TOKEN'] = 'TEST_TOKEN_FOR_PYTEST'
os.environ['DATABASE_FILE'] = ':memory:'  # Используем in-memory БД для тестов
