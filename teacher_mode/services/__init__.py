"""
Сервисы для режима учителя.
"""

from . import teacher_service
from . import assignment_service
from . import progress_tracker
from . import analytics_service
from . import gift_service
from . import homework_integration

__all__ = [
    'teacher_service',
    'assignment_service',
    'progress_tracker',
    'analytics_service',
    'gift_service',
    'homework_integration',
]
