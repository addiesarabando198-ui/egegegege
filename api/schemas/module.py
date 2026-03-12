"""
Pydantic schemas для модулей (разделов заданий).
"""

from pydantic import BaseModel, Field
from typing import List


class Module(BaseModel):
    """Информация о модуле"""
    code: str = Field(..., description="Код модуля (test_part, task19, task20, task24, task25)")
    name: str = Field(..., description="Название модуля")
    total_questions: int = Field(..., description="Всего вопросов в модуле", ge=0)
    description: str = Field(..., description="Описание модуля")

    class Config:
        json_schema_extra = {
            "example": {
                "code": "test_part",
                "name": "📝 Тестовая часть (1-16)",
                "total_questions": 450,
                "description": "Вопросы из тестовой части ЕГЭ"
            }
        }


class ModulesListResponse(BaseModel):
    """Ответ со списком модулей"""
    modules: List[Module] = Field(..., description="Список доступных модулей")

    class Config:
        json_schema_extra = {
            "example": {
                "modules": [
                    {
                        "code": "test_part",
                        "name": "📝 Тестовая часть (1-16)",
                        "total_questions": 450,
                        "description": "Вопросы из тестовой части ЕГЭ"
                    },
                    {
                        "code": "task19",
                        "name": "💡 Задание 19",
                        "total_questions": 120,
                        "description": "Анализ ситуации"
                    }
                ]
            }
        }
