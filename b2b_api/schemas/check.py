"""
Pydantic schemas для проверки ответов B2B API.
"""

from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Dict, Any
from enum import Enum
from datetime import datetime

from b2b_api.utils.url_validator import validate_callback_url


class CheckStatus(str, Enum):
    """Статус проверки"""
    PENDING = "pending"      # В очереди
    PROCESSING = "processing"  # В процессе проверки
    COMPLETED = "completed"   # Завершена
    FAILED = "failed"        # Ошибка


class CriteriaScore(BaseModel):
    """Оценка по критерию"""
    criteria_id: str = Field(..., description="ID критерия (например, К1, К2)")
    criteria_name: str = Field(..., description="Название критерия")
    score: int = Field(..., ge=0, description="Баллы по критерию")
    max_score: int = Field(..., ge=0, description="Максимальный балл по критерию")
    comment: Optional[str] = Field(None, description="Комментарий эксперта по критерию")

    class Config:
        json_schema_extra = {
            "example": {
                "criteria_id": "К1",
                "criteria_name": "Раскрытие смысла понятия",
                "score": 2,
                "max_score": 2,
                "comment": "Смысл понятия раскрыт корректно."
            }
        }


class CheckRequest(BaseModel):
    """Запрос на проверку ответа"""
    task_number: int = Field(
        ...,
        ge=17,
        le=25,
        description="Номер задания ЕГЭ (17-25)"
    )
    task_text: str = Field(
        ...,
        min_length=10,
        max_length=5000,
        description="Текст задания"
    )
    answer_text: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="Текст ответа ученика"
    )
    topic: Optional[str] = Field(
        None,
        max_length=200,
        description="Тема задания (опционально, улучшает точность)"
    )
    strictness: Optional[str] = Field(
        "standard",
        description="Уровень строгости: lenient, standard, strict, expert"
    )
    callback_url: Optional[str] = Field(
        None,
        max_length=2048,
        description="URL для webhook уведомления о завершении проверки (только HTTPS)"
    )
    external_id: Optional[str] = Field(
        None,
        max_length=100,
        description="Внешний ID для связи с системой клиента"
    )
    idempotency_key: Optional[str] = Field(
        None,
        max_length=128,
        description="Ключ идемпотентности для предотвращения дублей"
    )
    metadata: Optional[Dict[str, str]] = Field(
        None,
        description="Дополнительные метаданные клиента (ключ-значение, строки)"
    )

    @field_validator("callback_url")
    @classmethod
    def validate_callback(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        error = validate_callback_url(v)
        if error:
            raise ValueError(error)
        return v

    @field_validator("strictness")
    @classmethod
    def validate_strictness(cls, v: Optional[str]) -> Optional[str]:
        allowed = {"lenient", "standard", "strict", "expert"}
        if v is not None and v not in allowed:
            raise ValueError(f"strictness must be one of: {', '.join(sorted(allowed))}")
        return v

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, v: Optional[Dict[str, str]]) -> Optional[Dict[str, str]]:
        if v is None:
            return v
        if len(v) > 20:
            raise ValueError("metadata must not contain more than 20 keys")
        for key, val in v.items():
            if len(key) > 64:
                raise ValueError(f"metadata key '{key[:20]}...' exceeds 64 characters")
            if len(str(val)) > 256:
                raise ValueError(f"metadata value for '{key}' exceeds 256 characters")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "task_number": 19,
                "task_text": "Приведите три примера, иллюстрирующие функции политических партий в демократическом государстве. (Каждый пример должен быть сформулирован развёрнуто.)",
                "answer_text": "1) Партия «Единая Россия» выдвинула кандидата на выборы Президента РФ - это пример электоральной функции.\n2) Партия КПРФ организовала митинг в поддержку повышения пенсий - это пример функции политической социализации.\n3) Партия «Яблоко» разработала программу экологической политики - это пример программной функции.",
                "topic": "Политические партии",
                "strictness": "standard",
                "external_id": "student_123_task_456"
            }
        }


class CheckResponse(BaseModel):
    """Ответ на запрос проверки (создание)"""
    check_id: str = Field(..., description="Уникальный ID проверки")
    status: CheckStatus = Field(..., description="Статус проверки")
    created_at: datetime = Field(..., description="Время создания запроса")
    estimated_time_seconds: Optional[int] = Field(
        None,
        description="Ожидаемое время обработки в секундах"
    )
    external_id: Optional[str] = Field(None, description="Внешний ID клиента")

    class Config:
        json_schema_extra = {
            "example": {
                "check_id": "chk_abc123def456",
                "status": "pending",
                "created_at": "2024-02-12T10:30:00Z",
                "estimated_time_seconds": 30,
                "external_id": "student_123_task_456"
            }
        }


class CheckResultResponse(BaseModel):
    """Полный результат проверки"""
    check_id: str = Field(..., description="Уникальный ID проверки")
    status: CheckStatus = Field(..., description="Статус проверки")

    # Информация о задании
    task_number: int = Field(..., description="Номер задания")
    task_text: str = Field(..., description="Текст задания")
    answer_text: str = Field(..., description="Ответ ученика")

    # Результаты оценки
    total_score: Optional[int] = Field(None, ge=0, description="Общий балл")
    max_score: Optional[int] = Field(None, ge=0, description="Максимальный балл")
    criteria_scores: Optional[List[CriteriaScore]] = Field(
        None,
        description="Оценки по критериям"
    )

    # Обратная связь
    feedback: Optional[str] = Field(None, description="Общий комментарий эксперта")
    suggestions: Optional[List[str]] = Field(None, description="Рекомендации по улучшению")
    factual_errors: Optional[List[str]] = Field(None, description="Фактические ошибки")

    # Метаданные
    created_at: datetime = Field(..., description="Время создания запроса")
    completed_at: Optional[datetime] = Field(None, description="Время завершения проверки")
    processing_time_ms: Optional[int] = Field(None, description="Время обработки в мс")
    external_id: Optional[str] = Field(None, description="Внешний ID клиента")

    # Ошибка (если status == failed)
    error_message: Optional[str] = Field(None, description="Сообщение об ошибке")

    class Config:
        json_schema_extra = {
            "example": {
                "check_id": "chk_abc123def456",
                "status": "completed",
                "task_number": 19,
                "task_text": "Приведите три примера...",
                "answer_text": "1) Партия «Единая Россия»...",
                "total_score": 3,
                "max_score": 3,
                "criteria_scores": [
                    {
                        "criteria_id": "К1",
                        "criteria_name": "Корректность примеров",
                        "score": 3,
                        "max_score": 3,
                        "comment": "Все три примера корректны и конкретны."
                    }
                ],
                "feedback": "Отличный ответ! Все примеры конкретны и правильно иллюстрируют функции политических партий.",
                "suggestions": [],
                "factual_errors": [],
                "created_at": "2024-02-12T10:30:00Z",
                "completed_at": "2024-02-12T10:30:25Z",
                "processing_time_ms": 25000,
                "external_id": "student_123_task_456"
            }
        }


class CheckListItem(BaseModel):
    """Элемент списка проверок"""
    check_id: str
    status: CheckStatus
    task_number: int
    total_score: Optional[int] = None
    max_score: Optional[int] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    external_id: Optional[str] = None


class CheckListResponse(BaseModel):
    """Список проверок"""
    total: int = Field(..., description="Общее количество проверок")
    items: List[CheckListItem] = Field(..., description="Список проверок")
    page: int = Field(..., description="Текущая страница")
    per_page: int = Field(..., description="Элементов на странице")
