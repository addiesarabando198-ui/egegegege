"""
Pydantic schemas для B2B клиентов.
"""

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
from datetime import datetime
from enum import Enum


class ClientTier(str, Enum):
    """Тарифный план клиента"""
    FREE = "free"          # Бесплатный (ограниченный)
    TRIAL = "trial"        # Пробный период
    BASIC = "basic"        # Базовый
    STANDARD = "standard"  # Стандартный
    PREMIUM = "premium"    # Премиум
    ENTERPRISE = "enterprise"  # Корпоративный


class ClientStatus(str, Enum):
    """Статус клиента"""
    ACTIVE = "active"
    SUSPENDED = "suspended"
    TRIAL = "trial"


class B2BClientCreate(BaseModel):
    """Создание нового B2B клиента"""
    company_name: str = Field(..., min_length=2, max_length=200, description="Название компании")
    contact_email: EmailStr = Field(..., description="Email для связи")
    contact_name: str = Field(..., min_length=2, max_length=100, description="Контактное лицо")
    contact_phone: Optional[str] = Field(None, max_length=20, description="Телефон")
    website: Optional[str] = Field(None, max_length=200, description="Веб-сайт компании")
    tier: ClientTier = Field(ClientTier.TRIAL, description="Тарифный план")
    notes: Optional[str] = Field(None, max_length=1000, description="Примечания")

    class Config:
        json_schema_extra = {
            "example": {
                "company_name": "Онлайн Школа \"Знание\"",
                "contact_email": "api@znanie-school.ru",
                "contact_name": "Иванов Иван",
                "contact_phone": "+7 (999) 123-45-67",
                "website": "https://znanie-school.ru",
                "tier": "standard"
            }
        }


class B2BClient(BaseModel):
    """Информация о B2B клиенте"""
    client_id: str = Field(..., description="Уникальный ID клиента")
    company_name: str = Field(..., description="Название компании")
    contact_email: str = Field(..., description="Email для связи")
    contact_name: str = Field(..., description="Контактное лицо")

    # Статус и тариф
    status: ClientStatus = Field(..., description="Статус клиента")
    tier: ClientTier = Field(..., description="Тарифный план")

    # Лимиты
    rate_limit_per_minute: int = Field(..., description="Лимит запросов в минуту")
    rate_limit_per_day: int = Field(..., description="Лимит запросов в день")
    monthly_quota: Optional[int] = Field(None, description="Месячная квота проверок")

    # Использование
    checks_today: int = Field(0, description="Проверок сегодня")
    checks_this_month: int = Field(0, description="Проверок в этом месяце")
    total_checks: int = Field(0, description="Всего проверок")

    # Даты
    created_at: datetime = Field(..., description="Дата регистрации")
    last_activity_at: Optional[datetime] = Field(None, description="Последняя активность")
    trial_expires_at: Optional[datetime] = Field(None, description="Окончание триала")

    class Config:
        json_schema_extra = {
            "example": {
                "client_id": "cli_abc123",
                "company_name": "Онлайн Школа \"Знание\"",
                "contact_email": "api@znanie-school.ru",
                "contact_name": "Иванов Иван",
                "status": "active",
                "tier": "standard",
                "rate_limit_per_minute": 30,
                "rate_limit_per_day": 1000,
                "monthly_quota": 10000,
                "checks_today": 150,
                "checks_this_month": 3500,
                "total_checks": 45000,
                "created_at": "2024-01-15T10:00:00Z",
                "last_activity_at": "2024-02-12T10:30:00Z"
            }
        }


class APIKeyResponse(BaseModel):
    """Ответ с API ключом"""
    api_key: str = Field(..., description="API ключ (показывается только при создании!)")
    key_id: str = Field(..., description="ID ключа (для управления)")
    client_id: str = Field(..., description="ID клиента")
    name: str = Field(..., description="Название ключа")
    created_at: datetime = Field(..., description="Дата создания")
    expires_at: Optional[datetime] = Field(None, description="Дата истечения")
    scopes: List[str] = Field(..., description="Разрешённые действия")

    class Config:
        json_schema_extra = {
            "example": {
                "api_key": "b2b_live_sk_abc123xyz789...",
                "key_id": "key_001",
                "client_id": "cli_abc123",
                "name": "Production API Key",
                "created_at": "2024-02-12T10:00:00Z",
                "expires_at": None,
                "scopes": ["check:create", "check:read", "questions:read"]
            }
        }


class APIKeyInfo(BaseModel):
    """Информация об API ключе (без самого ключа)"""
    key_id: str
    name: str
    created_at: datetime
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    scopes: List[str]
    is_active: bool


class UsageStatsResponse(BaseModel):
    """Статистика использования API"""
    client_id: str
    period_start: datetime
    period_end: datetime

    # Общие метрики
    total_requests: int
    total_checks: int
    successful_checks: int
    failed_checks: int

    # По заданиям
    checks_by_task: dict = Field(..., description="Проверок по номерам заданий")

    # По дням
    daily_breakdown: List[dict] = Field(..., description="Статистика по дням")

    # Производительность
    avg_processing_time_ms: float
    p95_processing_time_ms: float

    class Config:
        json_schema_extra = {
            "example": {
                "client_id": "cli_abc123",
                "period_start": "2024-02-01T00:00:00Z",
                "period_end": "2024-02-12T23:59:59Z",
                "total_requests": 5000,
                "total_checks": 4800,
                "successful_checks": 4750,
                "failed_checks": 50,
                "checks_by_task": {
                    "19": 1500,
                    "20": 800,
                    "21": 600,
                    "22": 500,
                    "23": 400,
                    "24": 500,
                    "25": 500
                },
                "daily_breakdown": [
                    {"date": "2024-02-01", "checks": 400},
                    {"date": "2024-02-02", "checks": 450}
                ],
                "avg_processing_time_ms": 3500,
                "p95_processing_time_ms": 8000
            }
        }
