"""
Файл-прокси для совместимости структуры модулей.
Реальная логика оценки находится в checker.py
"""

# Импортируем функции из checker.py
from .checker import evaluate_plan, evaluate_plan_with_ai, PlanBotData

# Флаг для совместимости с другими модулями
AI_EVALUATOR_AVAILABLE = True

# Экспортируем всё необходимое
__all__ = [
    'evaluate_plan',
    'evaluate_plan_with_ai', 
    'PlanBotData',
    'AI_EVALUATOR_AVAILABLE'
]