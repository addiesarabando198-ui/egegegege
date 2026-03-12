"""
Pydantic schemas для вопросов.
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict


class Question(BaseModel):
    """Информация о вопросе"""
    id: str = Field(..., description="ID вопроса (например, test_part_123)")
    module: str = Field(..., description="Код модуля")
    number: Optional[int] = Field(None, description="Номер вопроса в тесте")
    text: str = Field(..., description="Текст вопроса")
    type: str = Field(..., description="Тип вопроса (multiple_choice, text, etc.)")
    difficulty: Optional[str] = Field(None, description="Сложность (easy, medium, hard)")
    topic: Optional[str] = Field(None, description="Тема вопроса")
    options: Optional[List[str]] = Field(None, description="Варианты ответов для multiple choice")
    correct_answer: Optional[Any] = Field(None, description="Правильный ответ")
    image_url: Optional[str] = Field(None, description="URL изображения, если есть")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "test_part_123",
                "module": "test_part",
                "number": 5,
                "text": "Выберите верные суждения о...",
                "type": "multiple_choice",
                "difficulty": "medium",
                "topic": "Социальная стратификация",
                "options": ["Вариант 1", "Вариант 2", "Вариант 3"],
                "correct_answer": "Вариант 2"
            }
        }


class QuestionsListResponse(BaseModel):
    """Ответ со списком вопросов"""
    total: int = Field(..., description="Общее количество вопросов")
    questions: List[Question] = Field(..., description="Список вопросов")

    class Config:
        json_schema_extra = {
            "example": {
                "total": 450,
                "questions": [
                    {
                        "id": "test_part_123",
                        "module": "test_part",
                        "number": 5,
                        "text": "Выберите верные суждения о...",
                        "type": "multiple_choice",
                        "difficulty": "medium",
                        "topic": "Социальная стратификация"
                    }
                ]
            }
        }
