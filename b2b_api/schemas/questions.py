"""
Pydantic schemas для банка заданий B2B API.
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Any
from enum import Enum


class TaskType(str, Enum):
    """Тип задания"""
    TASK_17 = "task17"  # Анализ текста: поиск информации
    TASK_18 = "task18"  # Объяснение понятия из текста
    TASK_19 = "task19"  # Примеры социальных объектов
    TASK_20 = "task20"  # Работа с текстом
    TASK_21 = "task21"  # Графики спроса и предложения
    TASK_22 = "task22"  # Анализ ситуаций
    TASK_23 = "task23"  # Конституция РФ
    TASK_24 = "task24"  # Сложный план
    TASK_25 = "task25"  # Обоснование с примерами


class DifficultyLevel(str, Enum):
    """Уровень сложности"""
    BASIC = "basic"        # Базовый (Б)
    ADVANCED = "advanced"  # Повышенный (П)
    HIGH = "high"          # Высокий (В)


class ThematicBlock(str, Enum):
    """Тематический блок"""
    CHELOVEK = "Человек и общество"
    EKONOMIKA = "Экономика"
    SOCIALNAYA = "Социальные отношения"
    POLITIKA = "Политика"
    PRAVO = "Право"


class B2BQuestion(BaseModel):
    """Задание из банка"""
    id: str = Field(..., description="Уникальный ID задания")
    task_number: int = Field(..., ge=17, le=25, description="Номер задания ЕГЭ")
    task_type: TaskType = Field(..., description="Тип задания")

    # Содержание
    text: str = Field(..., description="Текст задания")
    topic: Optional[str] = Field(None, description="Тема задания")
    block: Optional[str] = Field(None, description="Тематический блок")

    # Характеристики
    difficulty: Optional[str] = Field(None, description="Уровень сложности (Б/П/В)")
    max_score: int = Field(..., description="Максимальный балл")

    # Дополнительные материалы
    source_text: Optional[str] = Field(None, description="Исходный текст (для задания 20)")
    image_url: Optional[str] = Field(None, description="URL изображения")

    # Критерии оценивания (для клиентов, чтобы понимать как проверяется)
    criteria: Optional[List[dict]] = Field(None, description="Критерии оценивания")

    # Пример правильного ответа (опционально, для премиум клиентов)
    sample_answer: Optional[str] = Field(None, description="Пример ответа (для премиум)")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "task19_politika_001",
                "task_number": 19,
                "task_type": "task19",
                "text": "Приведите три примера, иллюстрирующие функции политических партий в демократическом государстве.",
                "topic": "Политические партии",
                "block": "Политика",
                "difficulty": "П",
                "max_score": 3,
                "criteria": [
                    {
                        "id": "К1",
                        "name": "Корректность примеров",
                        "max_score": 3,
                        "description": "По 1 баллу за каждый корректный конкретный пример"
                    }
                ]
            }
        }


class QuestionsFilterParams(BaseModel):
    """Параметры фильтрации заданий"""
    task_number: Optional[int] = Field(None, ge=17, le=25, description="Номер задания")
    task_type: Optional[TaskType] = Field(None, description="Тип задания")
    block: Optional[str] = Field(None, description="Тематический блок")
    topic: Optional[str] = Field(None, description="Тема (поиск по подстроке)")
    difficulty: Optional[str] = Field(None, description="Уровень сложности")
    search: Optional[str] = Field(None, description="Поиск по тексту задания")
    include_sample_answers: bool = Field(False, description="Включить примеры ответов")


class B2BQuestionsListResponse(BaseModel):
    """Ответ со списком заданий"""
    total: int = Field(..., description="Общее количество заданий")
    page: int = Field(..., description="Текущая страница")
    per_page: int = Field(..., description="Заданий на странице")
    questions: List[B2BQuestion] = Field(..., description="Список заданий")

    # Статистика по фильтрам (для UI)
    available_blocks: Optional[List[str]] = Field(None, description="Доступные блоки")
    available_topics: Optional[List[str]] = Field(None, description="Доступные темы")

    class Config:
        json_schema_extra = {
            "example": {
                "total": 150,
                "page": 1,
                "per_page": 20,
                "questions": [
                    {
                        "id": "task19_politika_001",
                        "task_number": 19,
                        "task_type": "task19",
                        "text": "Приведите три примера...",
                        "topic": "Политические партии",
                        "block": "Политика",
                        "difficulty": "П",
                        "max_score": 3
                    }
                ],
                "available_blocks": ["Политика", "Экономика", "Право", "Социальные отношения", "Человек и общество"],
                "available_topics": ["Политические партии", "Государство", "Выборы"]
            }
        }


class QuestionStatsResponse(BaseModel):
    """Статистика по заданиям"""
    total_questions: int = Field(..., description="Всего заданий")
    by_task_number: dict = Field(..., description="Количество по номерам заданий")
    by_block: dict = Field(..., description="Количество по блокам")
    by_difficulty: dict = Field(..., description="Количество по сложности")
