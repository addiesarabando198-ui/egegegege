"""
White-label конфигурация бренда бота.

Позволяет онлайн-школам настраивать внешний вид бота:
- Название и описание
- Приветственные сообщения
- Контактные данные
- Тексты UI

Настройки загружаются из переменных окружения и могут быть
переопределены для каждой школы через таблицу schools.branding.
"""

import os
import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class BrandingConfig:
    """Конфигурация бренда бота."""

    # Основные
    bot_name: str = "ЕГЭ Супербот"
    bot_short_name: str = "ЕГЭ Бот"
    bot_description: str = "Подготовка к ЕГЭ по обществознанию с AI-проверкой"

    # Приветствие
    welcome_message: str = (
        "Привет! Я помогу тебе подготовиться к ЕГЭ по обществознанию.\n\n"
        "Выбери, с чего начать:"
    )
    welcome_teacher_message: str = (
        "Добро пожаловать в режим учителя!\n\n"
        "Здесь вы можете создавать задания, проверять работы учеников "
        "и отслеживать их прогресс."
    )

    # Контакты
    support_contact: str = ""
    support_url: str = ""
    school_name: str = ""
    school_url: str = ""

    # Тексты
    subscription_promo_text: str = (
        "Оформите подписку для полного доступа ко всем заданиям "
        "и неограниченным AI-проверкам."
    )
    footer_text: str = ""

    # Визуал (для WebApp)
    primary_color: str = "#2196F3"
    logo_url: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict) -> "BrandingConfig":
        """Создание из словаря (игнорирует неизвестные ключи)."""
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)

    @classmethod
    def from_json(cls, json_str: str) -> "BrandingConfig":
        try:
            data = json.loads(json_str)
            return cls.from_dict(data)
        except (json.JSONDecodeError, TypeError):
            return cls()


def _load_from_env() -> BrandingConfig:
    """Загружает конфигурацию бренда из переменных окружения."""
    kwargs = {}

    env_mapping = {
        "BOT_BRAND_NAME": "bot_name",
        "BOT_BRAND_SHORT_NAME": "bot_short_name",
        "BOT_BRAND_DESCRIPTION": "bot_description",
        "BOT_BRAND_WELCOME": "welcome_message",
        "BOT_BRAND_WELCOME_TEACHER": "welcome_teacher_message",
        "BOT_BRAND_SUPPORT_CONTACT": "support_contact",
        "BOT_BRAND_SUPPORT_URL": "support_url",
        "BOT_BRAND_SCHOOL_NAME": "school_name",
        "BOT_BRAND_SCHOOL_URL": "school_url",
        "BOT_BRAND_SUBSCRIPTION_PROMO": "subscription_promo_text",
        "BOT_BRAND_FOOTER": "footer_text",
        "BOT_BRAND_COLOR": "primary_color",
        "BOT_BRAND_LOGO_URL": "logo_url",
    }

    for env_key, field_name in env_mapping.items():
        value = os.getenv(env_key)
        if value:
            kwargs[field_name] = value

    config = BrandingConfig(**kwargs)
    logger.info(f"Branding loaded: bot_name='{config.bot_name}'")
    return config


# Глобальный экземпляр — дефолтный брендинг
_default_branding: Optional[BrandingConfig] = None


def get_branding(school_branding_json: Optional[str] = None) -> BrandingConfig:
    """
    Возвращает конфигурацию бренда.

    Args:
        school_branding_json: JSON из таблицы schools.branding (для white-label).
            Если None — используется дефолтный конфиг из env.

    Returns:
        BrandingConfig
    """
    global _default_branding

    if _default_branding is None:
        _default_branding = _load_from_env()

    if school_branding_json:
        try:
            school_config = BrandingConfig.from_json(school_branding_json)
            # Мержим: school overrides поверх дефолтов
            base = _default_branding.to_dict()
            overrides = {
                k: v for k, v in school_config.to_dict().items()
                if v  # Пропускаем пустые значения
            }
            base.update(overrides)
            return BrandingConfig.from_dict(base)
        except Exception as e:
            logger.warning(f"Failed to parse school branding: {e}")

    return _default_branding
