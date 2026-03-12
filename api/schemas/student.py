"""
Pydantic schemas для учеников.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class StudentStats(BaseModel):
    """Статистика ученика"""
    completed_assignments: int = Field(..., description="Завершенных заданий", ge=0)
    average_score: Optional[float] = Field(None, description="Средний балл", ge=0, le=100)
    total_questions_solved: int = Field(0, description="Всего вопросов решено", ge=0)
    correct_answers: int = Field(0, description="Правильных ответов", ge=0)

    class Config:
        json_schema_extra = {
            "example": {
                "completed_assignments": 12,
                "average_score": 85.5,
                "total_questions_solved": 250,
                "correct_answers": 214
            }
        }


class Student(BaseModel):
    """Информация об ученике"""
    id: int = Field(..., description="ID ученика в БД")
    user_id: int = Field(..., description="Telegram user ID")
    name: str = Field(..., description="Имя ученика")
    username: Optional[str] = Field(None, description="Telegram username")
    connected_at: datetime = Field(..., description="Дата подключения к учителю")
    stats: Optional[StudentStats] = None

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": 1,
                "user_id": 111222333,
                "name": "Мария Петрова",
                "username": "maria_p",
                "connected_at": "2024-09-01T10:00:00Z",
                "stats": {
                    "completed_assignments": 12,
                    "average_score": 85.5,
                    "total_questions_solved": 250,
                    "correct_answers": 214
                }
            }
        }


class StudentsListResponse(BaseModel):
    """Ответ со списком учеников"""
    total: int = Field(..., description="Общее количество учеников")
    students: List[Student] = Field(..., description="Список учеников")

    class Config:
        json_schema_extra = {
            "example": {
                "total": 45,
                "students": [
                    {
                        "id": 1,
                        "user_id": 111222333,
                        "name": "Мария Петрова",
                        "username": "maria_p",
                        "connected_at": "2024-09-01T10:00:00Z",
                        "stats": {
                            "completed_assignments": 12,
                            "average_score": 85.5,
                            "total_questions_solved": 250,
                            "correct_answers": 214
                        }
                    }
                ]
            }
        }
