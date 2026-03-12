"""
Обработчики для режима учителя.
"""

from . import teacher_handlers
from . import student_handlers
from . import analytics_handlers
from . import quick_check_handlers
from . import variant_check_handlers

__all__ = [
    'teacher_handlers',
    'student_handlers',
    'analytics_handlers',
    'quick_check_handlers',
    'variant_check_handlers',
]
