"""
core/types.py
Общие типы и классы для предотвращения циклических импортов.
"""

from typing import Dict, List, Optional, Any, Tuple, Union, Callable
from dataclasses import dataclass
from enum import Enum
from datetime import datetime


# Общие типы данных
UserID = int
MessageID = int
ChatID = int
QuestionID = str
TopicID = Union[str, int]
Score = int


# Перечисления
class TaskType(Enum):
    """Типы заданий ЕГЭ."""
    TEST_PART = "test_part"
    TASK17 = "task17"
    TASK18 = "task18"
    TASK19 = "task19"
    TASK20 = "task20"
    TASK21 = "task21"
    TASK22 = "task22"
    TASK23 = "task23"
    TASK24 = "task24"
    TASK25 = "task25"


class AnswerMode(Enum):
    """Режимы ответов."""
    TEXT = "text"
    DOCUMENT = "document"
    VOICE = "voice"
    PARTS = "parts"  # Для задания 25


class QuestionType(Enum):
    """Типы вопросов в тестовой части."""
    SINGLE = "single"  # Один правильный ответ
    MULTIPLE = "multiple"  # Несколько правильных ответов
    ORDER = "order"  # Установить порядок
    MATCH = "match"  # Установить соответствие


# Базовые структуры данных
@dataclass
class Question:
    """Структура вопроса."""
    id: QuestionID
    text: str
    type: QuestionType
    answer: Union[str, List[str]]
    topic: str
    block: Optional[str] = None
    exam_number: Optional[int] = None
    difficulty: Optional[int] = None
    explanation: Optional[str] = None
    options: Optional[List[str]] = None


@dataclass
class Topic:
    """Структура темы для развернутых заданий."""
    id: TopicID
    title: str
    task_text: str
    block: Optional[str] = None
    difficulty: Optional[int] = None
    keywords: Optional[List[str]] = None
    example_answer: Optional[Dict[str, Any]] = None
    criteria: Optional[Dict[str, Any]] = None


@dataclass
class UserProgress:
    """Прогресс пользователя."""
    user_id: UserID
    task_type: TaskType
    total_answered: int = 0
    correct_answers: int = 0
    topics_completed: List[TopicID] = None
    last_activity: Optional[datetime] = None
    current_streak: int = 0
    max_streak: int = 0
    
    def __post_init__(self):
        if self.topics_completed is None:
            self.topics_completed = []


@dataclass
class EvaluationCriteria:
    """Критерий оценивания."""
    code: str  # К1, К2, К3 и т.д.
    name: str
    max_score: int
    description: str


@dataclass
class EvaluationResult:
    """Результат проверки ответа."""
    total_score: int
    max_score: int
    criteria_scores: Dict[str, int]
    feedback: str
    detailed_feedback: Optional[Dict[str, Any]] = None  # Изменено с Dict[str, str] на Dict[str, Any]
    warnings: Optional[List[str]] = None
    suggestions: Optional[List[str]] = None
    factual_errors: Optional[List[Dict[str, str]]] = None  # Добавлено новое поле
    
    @property
    def percentage(self) -> float:
        """Процент выполнения."""
        if self.max_score == 0:
            return 0.0
        return (self.total_score / self.max_score) * 100


@dataclass
class TaskRequirements:
    """Требования к заданию."""
    task_number: int
    task_name: str
    max_score: int
    criteria: List[EvaluationCriteria]
    description: str
    time_limit: Optional[int] = None  # в минутах


# Callback data структуры
@dataclass
class CallbackData:
    """Базовая структура для callback_data."""
    action: str
    task: Optional[TaskType] = None
    data: Optional[Dict[str, Any]] = None
    
    def to_string(self) -> str:
        """Преобразование в строку для callback_data."""
        parts = [self.action]
        if self.task:
            parts.append(self.task.value)
        if self.data:
            # Кодируем дополнительные данные
            import json
            import base64
            data_str = base64.b64encode(
                json.dumps(self.data).encode()
            ).decode()
            parts.append(data_str)
        return ":".join(parts)
    
    @classmethod
    def from_string(cls, callback_str: str) -> 'CallbackData':
        """Создание из строки callback_data."""
        parts = callback_str.split(":", 2)
        action = parts[0]
        task = None
        data = None
        
        if len(parts) > 1:
            try:
                task = TaskType(parts[1])
            except ValueError:
                pass
        
        if len(parts) > 2:
            try:
                import json
                import base64
                data = json.loads(
                    base64.b64decode(parts[2].encode()).decode()
                )
            except:
                pass
        
        return cls(action=action, task=task, data=data)


# Типы для обработчиков
HandlerFunc = Callable[[Any, Any], Any]
ErrorHandlerFunc = Callable[[Exception, Any, Any], Any]


# Константы
MAX_MESSAGE_LENGTH = 4096
MAX_CALLBACK_DATA_LENGTH = 64
MAX_INLINE_BUTTONS = 100
MAX_REPLY_BUTTONS = 300

# Лимиты для заданий
TASK_LIMITS = {
    TaskType.TASK17: {"elements": 3, "min_words": 30},
    TaskType.TASK18: {"elements": 3, "min_words": 30},
    TaskType.TASK19: {"examples": 3, "min_words": 50},
    TaskType.TASK20: {"judgments": 3, "min_words": 60},
    TaskType.TASK24: {"points": 10, "sub_points": 3},
    TaskType.TASK25: {"parts": 3, "min_words": 150}
}