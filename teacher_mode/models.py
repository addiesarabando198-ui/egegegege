"""
Модели данных для режима учителя.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum


class UserRole(str, Enum):
    """Роли пользователей"""
    TEACHER = "teacher"
    STUDENT = "student"


class RelationshipStatus(str, Enum):
    """Статус связи учитель-ученик"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    BLOCKED = "blocked"


class AssignmentType(str, Enum):
    """Тип домашнего задания"""
    EXISTING_TOPICS = "existing_topics"  # Из существующих тем (task19, task20, etc.)
    CUSTOM = "custom"  # Кастомное задание (для будущего)
    TEST_PART = "test_part"  # Из тестовой части
    FULL_EXAM = "full_exam"  # Полный вариант ЕГЭ (1-16 + 19-25)


class AssignmentStatus(str, Enum):
    """Статус домашнего задания"""
    ACTIVE = "active"
    ARCHIVED = "archived"


class StudentAssignmentStatus(str, Enum):
    """Статус выполнения задания учеником"""
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    OVERDUE = "overdue"


class TargetType(str, Enum):
    """Кому назначено задание"""
    ALL_STUDENTS = "all_students"
    SPECIFIC_STUDENTS = "specific_students"
    GROUP = "group"  # Для будущего


@dataclass
class TeacherProfile:
    """Профиль учителя"""
    user_id: int
    teacher_code: str
    display_name: str
    has_active_subscription: bool
    subscription_expires: Optional[datetime]
    subscription_tier: str  # 'teacher_basic', 'teacher_standard', 'teacher_premium'
    created_at: datetime
    feedback_settings: Optional[Dict[str, Any]] = None

    @property
    def max_students(self) -> int:
        """Максимальное количество учеников по тарифу"""
        from payment.config import get_teacher_max_students
        return get_teacher_max_students(self.subscription_tier)


@dataclass
class TeacherStudentRelationship:
    """Связь учитель-ученик"""
    id: int
    teacher_id: int
    student_id: int
    invited_at: datetime
    status: RelationshipStatus


@dataclass
class HomeworkAssignment:
    """Домашнее задание"""
    id: int
    teacher_id: int
    created_at: datetime
    title: str
    description: Optional[str]
    deadline: Optional[datetime]
    assignment_type: AssignmentType
    assignment_data: Dict[str, Any]  # JSON с деталями задания
    target_type: TargetType
    status: AssignmentStatus


@dataclass
class HomeworkStudentAssignment:
    """Назначение задания конкретному ученику"""
    id: int
    homework_id: int
    student_id: int
    assigned_at: datetime
    status: StudentAssignmentStatus
    completed_at: Optional[datetime] = None


@dataclass
class HomeworkProgress:
    """Прогресс выполнения домашнего задания"""
    id: int
    homework_id: int
    student_id: int
    question_id: str
    user_answer: str
    is_correct: bool
    ai_feedback: Optional[str]
    completed_at: datetime


@dataclass
class GiftedSubscription:
    """Подаренная подписка"""
    id: int
    gifter_id: int  # Кто подарил (учитель или другой пользователь)
    recipient_id: int  # Кому подарили
    duration_days: int
    activated_at: datetime
    expires_at: datetime
    status: str  # 'active', 'expired', 'cancelled'


@dataclass
class PromoCode:
    """Промокод для подписки"""
    code: str
    creator_id: int  # Кто создал (обычно учитель)
    duration_days: int
    max_uses: int
    used_count: int
    created_at: datetime
    expires_at: Optional[datetime]
    status: str  # 'active', 'expired', 'exhausted'


# ============================================
# Модели для быстрой проверки работ (Quick Check)
# ============================================

class QuickCheckTaskType(str, Enum):
    """Типы заданий для быстрой проверки"""
    TASK17 = "task17"
    TASK18 = "task18"
    TASK19 = "task19"
    TASK20 = "task20"
    TASK21 = "task21"
    TASK22 = "task22"
    TASK23 = "task23"
    TASK24 = "task24"
    TASK25 = "task25"
    CUSTOM = "custom"  # Произвольное задание


@dataclass
class QuickCheck:
    """Быстрая проверка работы ученика"""
    id: int
    teacher_id: int
    task_type: QuickCheckTaskType
    task_condition: str
    student_answer: str
    student_id: Optional[int]
    ai_feedback: Optional[str]
    is_correct: Optional[bool]
    score: Optional[int]
    teacher_comment: Optional[str]
    tags: Optional[List[str]]  # Теги для категоризации
    template_name: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]


@dataclass
class QuickCheckTemplate:
    """Шаблон задания для быстрой проверки"""
    id: int
    teacher_id: int
    template_name: str
    task_type: QuickCheckTaskType
    task_condition: str
    tags: Optional[List[str]]
    usage_count: int
    created_at: datetime
    updated_at: Optional[datetime]


@dataclass
class QuickCheckQuota:
    """Квота на быстрые проверки для учителя"""
    id: int
    teacher_id: int
    monthly_limit: int  # Месячный лимит проверок
    used_this_month: int  # Использовано в текущем месяце
    current_period_start: datetime
    current_period_end: datetime
    bonus_checks: int  # Бонусные проверки (не сгорают)
    last_reset_at: Optional[datetime]
    updated_at: datetime

    @property
    def remaining_checks(self) -> int:
        """Оставшиеся проверки в текущем периоде"""
        return max(0, self.monthly_limit + self.bonus_checks - self.used_this_month)

    @property
    def can_check(self) -> bool:
        """Можно ли выполнить проверку"""
        return self.remaining_checks > 0
