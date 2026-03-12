"""
Модуль для задания 23 ЕГЭ по обществознанию.

Задание 23 посвящено Конституции Российской Федерации.
Модуль поддерживает два типа вопросов:
- Model Type 1: Дана одна характеристика, нужно дать 3 подтверждения
- Model Type 2: Даны три характеристики, нужно дать по одному подтверждению каждой
"""

from .plugin import Task23Plugin, plugin
from .handlers import register_handlers, init_task23_data
from .evaluator import Task23Evaluator

__all__ = [
    'Task23Plugin',
    'plugin',
    'register_handlers',
    'init_task23_data',
    'Task23Evaluator'
]
