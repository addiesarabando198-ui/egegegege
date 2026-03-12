"""
Pydantic schemas для черновиков заданий.
"""

from pydantic import BaseModel, Field
from typing import Any, Dict, List
from datetime import datetime


class SaveDraftRequest(BaseModel):
    """Запрос на сохранение черновика"""
    draft_data: Dict[str, Any] = Field(
        ...,
        description="Данные черновика (частично заполненное задание)"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "draft_data": {
                    "assignment_type": "existing_topics",
                    "title": "Незаконченное задание...",
                    "modules": [],
                    "student_ids": []
                }
            }
        }


class SaveDraftResponse(BaseModel):
    """Ответ на сохранение черновика"""
    draft_id: str = Field(..., description="ID черновика")
    saved_at: datetime = Field(..., description="Время сохранения")

    class Config:
        json_schema_extra = {
            "example": {
                "draft_id": "draft_789",
                "saved_at": "2025-12-29T15:35:00Z"
            }
        }


class Draft(BaseModel):
    """Информация о черновике"""
    draft_id: str = Field(..., description="ID черновика")
    created_at: datetime = Field(..., description="Время создания")
    updated_at: datetime = Field(..., description="Время последнего обновления")
    data: Dict[str, Any] = Field(..., description="Данные черновика")

    class Config:
        json_schema_extra = {
            "example": {
                "draft_id": "draft_789",
                "created_at": "2025-12-29T15:35:00Z",
                "updated_at": "2025-12-29T15:40:00Z",
                "data": {
                    "assignment_type": "existing_topics",
                    "title": "Незаконченное задание...",
                    "modules": [],
                    "student_ids": []
                }
            }
        }


class DraftsListResponse(BaseModel):
    """Ответ со списком черновиков"""
    drafts: List[Draft] = Field(..., description="Список черновиков")

    class Config:
        json_schema_extra = {
            "example": {
                "drafts": [
                    {
                        "draft_id": "draft_789",
                        "created_at": "2025-12-29T15:35:00Z",
                        "updated_at": "2025-12-29T15:40:00Z",
                        "data": {
                            "assignment_type": "existing_topics",
                            "title": "Незаконченное задание...",
                            "modules": []
                        }
                    }
                ]
            }
        }


class DeleteDraftResponse(BaseModel):
    """Ответ на удаление черновика"""
    success: bool = Field(..., description="Успешно ли удален")
    message: str = Field(..., description="Сообщение о результате")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "Черновик успешно удален"
            }
        }
