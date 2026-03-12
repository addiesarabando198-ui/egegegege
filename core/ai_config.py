"""
Конфигурация и оптимизация AI-сервиса для проверки заданий ЕГЭ.

Поддерживаемые провайдеры: Claude (Anthropic), YandexGPT.
Выбор через переменную окружения AI_PROVIDER.
"""

import os
import logging
from dataclasses import dataclass
from typing import Dict, Any, Optional
from core.types import TaskType
from core.ai_service import _get_provider, AIProvider

logger = logging.getLogger(__name__)


@dataclass
class OptimalSettings:
    """Оптимальные настройки для разных типов заданий"""
    temperature: float
    max_tokens: int
    model: str  # "pro" или "lite"

    @classmethod
    def for_task(cls, task_type: TaskType) -> 'OptimalSettings':
        """Возвращает оптимальные настройки для типа задания"""

        # Температуры снижены для борьбы с галлюцинацией контекста
        # и систематическим завышением оценок (по результатам benchmark).
        # Task18 переведён на pro — галлюцинации при подмене понятий.
        settings_map = {
            TaskType.TASK17: cls(
                temperature=0.1,
                max_tokens=1500,
                model="lite"
            ),
            TaskType.TASK18: cls(
                temperature=0.1,
                max_tokens=2000,
                model="pro"  # pro: критичен для избежания галлюцинации контекста
            ),
            TaskType.TASK19: cls(
                temperature=0.15,
                max_tokens=2500,
                model="lite"
            ),
            TaskType.TASK20: cls(
                temperature=0.15,
                max_tokens=2000,
                model="lite"
            ),
            TaskType.TASK21: cls(
                temperature=0.1,
                max_tokens=2000,
                model="lite"
            ),
            TaskType.TASK22: cls(
                temperature=0.1,
                max_tokens=2000,
                model="lite"
            ),
            TaskType.TASK23: cls(
                temperature=0.1,
                max_tokens=2000,
                model="pro"  # pro: конституционные нормы требуют точности
            ),
            TaskType.TASK25: cls(
                temperature=0.1,
                max_tokens=3500,
                model="pro"
            ),
            TaskType.TASK24: cls(
                temperature=0.1,
                max_tokens=2500,
                model="pro"
            )
        }

        return settings_map.get(task_type, cls(0.15, 2000, "pro"))


class PromptOptimizer:
    """Оптимизация промптов для AI-сервиса"""

    @staticmethod
    def optimize(prompt: str) -> str:
        """Адаптирует промпт для AI-сервиса"""
        prompt = PromptOptimizer._add_clear_structure(prompt)
        prompt = PromptOptimizer._simplify_language(prompt)
        prompt = PromptOptimizer._add_keywords(prompt)
        prompt = PromptOptimizer._optimize_length(prompt)
        return prompt

    @staticmethod
    def _add_clear_structure(prompt: str) -> str:
        if "ФОРМАТ ОТВЕТА" not in prompt:
            prompt += "\n\nФОРМАТ ОТВЕТА: структурированный JSON"
        return prompt

    @staticmethod
    def _simplify_language(prompt: str) -> str:
        replacements = {
            "осуществить комплексный анализ": "проанализировать",
            "продемонстрировать наличие": "показать",
            "реализовать проверку": "проверить"
        }
        for old, new in replacements.items():
            prompt = prompt.replace(old, new)
        return prompt

    @staticmethod
    def _add_keywords(prompt: str) -> str:
        keywords = {
            "ЕГЭ": "единый государственный экзамен",
            "ФИПИ": "Федеральный институт педагогических измерений",
            "балл": "оценка в баллах"
        }
        for abbr, full in keywords.items():
            if abbr in prompt and full not in prompt:
                prompt = f"{abbr} ({full})\n" + prompt
                break
        return prompt

    @staticmethod
    def _optimize_length(prompt: str, max_length: int = 8000) -> str:
        if len(prompt) > max_length:
            logger.warning(f"Промпт слишком длинный ({len(prompt)} символов), сокращаем")
            return prompt[:max_length] + "..."
        return prompt


class CostCalculator:
    """Калькулятор стоимости использования AI-сервиса"""

    # Тарифы по провайдерам (руб. за 1000 токенов)
    PRICES = {
        AIProvider.YANDEX: {
            "lite": {"input": 0.2, "output": 0.4},
            "pro": {"input": 2.0, "output": 4.0},
        },
        AIProvider.CLAUDE: {
            # Claude Sonnet 4.6: $3.00/$15.00 per 1M tokens ≈ ~0.27/1.35 руб за 1000
            "lite": {"input": 0.27, "output": 1.35},
            # Claude Opus 4.6: $5.00/$25.00 per 1M tokens ≈ ~0.45/2.25 руб за 1000
            "pro": {"input": 0.45, "output": 2.25},
        },
    }

    @classmethod
    def estimate_cost(
        cls,
        task_type: TaskType,
        answers_count: int,
        avg_answer_length: int = 500
    ) -> Dict[str, float]:
        """Оценка стоимости проверки"""
        provider = _get_provider()
        settings = OptimalSettings.for_task(task_type)
        model = settings.model

        prices = cls.PRICES.get(provider, cls.PRICES[AIProvider.CLAUDE])
        model_prices = prices.get(model, prices["pro"])

        avg_prompt_tokens = 1500
        avg_response_tokens = 800

        input_tokens = avg_prompt_tokens + (avg_answer_length // 4)
        output_tokens = avg_response_tokens

        cost_per_answer = (
            (input_tokens / 1000) * model_prices["input"] +
            (output_tokens / 1000) * model_prices["output"]
        )

        total_cost = cost_per_answer * answers_count

        return {
            "cost_per_answer": round(cost_per_answer, 2),
            "total_cost": round(total_cost, 2),
            "model": model,
            "provider": provider.value,
            "answers_count": answers_count
        }


class RateLimiter:
    """Управление лимитами запросов"""

    def __init__(self, requests_per_minute: int = 100):
        self.rpm_limit = requests_per_minute
        self.request_times = []

    async def wait_if_needed(self):
        import asyncio
        from datetime import datetime, timedelta

        now = datetime.now()
        minute_ago = now - timedelta(minutes=1)

        self.request_times = [t for t in self.request_times if t > minute_ago]

        if len(self.request_times) >= self.rpm_limit:
            wait_time = (self.request_times[0] + timedelta(minutes=1) - now).total_seconds()
            if wait_time > 0:
                logger.info(f"Достигнут лимит запросов, ожидание {wait_time:.1f} сек")
                await asyncio.sleep(wait_time)

        self.request_times.append(now)


# Глобальные настройки (провайдер-агностичные)
AI_CONFIG = {
    "timeout": 60,
    "retry_attempts": 3,
    "retry_delay": 2,

    "rate_limit": {
        "requests_per_minute": 100,
        "tokens_per_minute": 120000
    },

    "default_settings": {
        "temperature": 0.3,
        "max_tokens": 2000,
        "stream": False
    },

    "social_studies_context": {
        "knowledge_cutoff": "2025",
        "russian_focus": True,
        "use_academic_style": True
    }
}

# Backward-compatible alias
YANDEX_GPT_CONFIG = AI_CONFIG


def get_optimal_config(task_type: TaskType) -> Dict[str, Any]:
    """Получает оптимальную конфигурацию для задания"""
    settings = OptimalSettings.for_task(task_type)

    return {
        "model": settings.model,
        "completionOptions": {
            "temperature": settings.temperature,
            "maxTokens": str(settings.max_tokens),
            "stream": False
        }
    }


def estimate_monthly_cost(
    daily_users: int,
    tasks_per_user: int = 5,
    task_distribution: Dict[TaskType, float] = None
) -> Dict[str, Any]:
    """Оценка месячной стоимости сервиса"""
    if task_distribution is None:
        task_distribution = {
            TaskType.TASK19: 0.4,
            TaskType.TASK20: 0.3,
            TaskType.TASK25: 0.3
        }

    monthly_answers = daily_users * tasks_per_user * 30
    total_cost = 0

    breakdown = {}
    for task_type, percentage in task_distribution.items():
        task_answers = int(monthly_answers * percentage)
        task_cost = CostCalculator.estimate_cost(task_type, task_answers)
        breakdown[task_type.value] = task_cost
        total_cost += task_cost["total_cost"]

    return {
        "monthly_cost": round(total_cost, 2),
        "daily_cost": round(total_cost / 30, 2),
        "cost_per_user": round(total_cost / (daily_users * 30), 2),
        "breakdown": breakdown,
        "total_answers": monthly_answers
    }
