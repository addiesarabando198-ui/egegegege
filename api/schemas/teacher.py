"""
Pydantic schemas для профиля учителя и статистики.
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class SubscriptionInfo(BaseModel):
    """Информация о подписке учителя"""
    tier: str = Field(..., description="Уровень подписки (teacher_free, teacher_basic, teacher_standard, teacher_premium)")
    expires_at: Optional[datetime] = Field(None, description="Дата истечения подписки")
    is_active: bool = Field(..., description="Активна ли подписка")

    class Config:
        json_schema_extra = {
            "example": {
                "tier": "teacher_premium",
                "expires_at": "2025-12-31T23:59:59Z",
                "is_active": True
            }
        }


class TeacherStats(BaseModel):
    """Статистика учителя"""
    total_students: int = Field(..., description="Всего учеников", ge=0)
    total_assignments: int = Field(..., description="Всего заданий создано", ge=0)
    active_assignments: int = Field(..., description="Активных заданий", ge=0)

    class Config:
        json_schema_extra = {
            "example": {
                "total_students": 45,
                "total_assignments": 120,
                "active_assignments": 15
            }
        }


class TeacherProfileResponse(BaseModel):
    """Полный профиль учителя"""
    teacher_id: int = Field(..., description="ID учителя")
    user_id: int = Field(..., description="Telegram user ID")
    name: str = Field(..., description="Отображаемое имя учителя")
    teacher_code: str = Field(..., description="Код учителя для подключения учеников")
    subscription: SubscriptionInfo
    stats: TeacherStats

    class Config:
        from_attributes = True  # Для SQLAlchemy моделей
        json_schema_extra = {
            "example": {
                "teacher_id": 123,
                "user_id": 987654321,
                "name": "Иван Иванович",
                "teacher_code": "TEACH-ABC123",
                "subscription": {
                    "tier": "teacher_premium",
                    "expires_at": "2025-12-31T23:59:59Z",
                    "is_active": True
                },
                "stats": {
                    "total_students": 45,
                    "total_assignments": 120,
                    "active_assignments": 15
                }
            }
        }
