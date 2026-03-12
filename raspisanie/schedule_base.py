"""
Система автоматизации составления расписания
Базовые классы данных
"""

from dataclasses import dataclass, field
from typing import List, Set, Dict, Optional, Tuple
from enum import Enum
import json


class DayOfWeek(Enum):
    """Дни недели"""
    MONDAY = 1
    TUESDAY = 2
    WEDNESDAY = 3
    THURSDAY = 4
    FRIDAY = 5


class SubjectType(Enum):
    """Типы предметов"""
    MANDATORY = "mandatory"  # Обязательный предмет
    EGE_PRACTICE = "ege_practice"  # Практикум ЕГЭ
    ELECTIVE = "elective"  # Факультатив


@dataclass
class TimeSlot:
    """Временной слот (день недели + номер урока)"""
    day: DayOfWeek
    lesson_number: int  # 1-7
    
    def __hash__(self):
        return hash((self.day, self.lesson_number))
    
    def __str__(self):
        day_names = {
            DayOfWeek.MONDAY: "ПН",
            DayOfWeek.TUESDAY: "ВТ",
            DayOfWeek.WEDNESDAY: "СР",
            DayOfWeek.THURSDAY: "ЧТ",
            DayOfWeek.FRIDAY: "ПТ"
        }
        return f"{day_names[self.day]}-{self.lesson_number}"


@dataclass
class Classroom:
    """Кабинет"""
    number: str
    capacity: int
    floor: int
    responsible_teacher: Optional[str] = None
    
    def __hash__(self):
        return hash(self.number)


@dataclass
class Teacher:
    """Учитель"""
    name: str
    subjects: List[str] = field(default_factory=list)
    home_classroom: Optional[str] = None
    unavailable_days: Set[DayOfWeek] = field(default_factory=set)
    
    def __hash__(self):
        return hash(self.name)
    
    def is_available(self, day: DayOfWeek) -> bool:
        """Проверка доступности учителя в определенный день"""
        return day not in self.unavailable_days


@dataclass
class Student:
    """Ученик"""
    name: str
    class_name: str
    ege_subjects: List[str] = field(default_factory=list)
    
    def __hash__(self):
        return hash(self.name)


@dataclass
class Class:
    """Класс"""
    name: str
    profile: str
    students: List[Student] = field(default_factory=list)
    
    def __hash__(self):
        return hash(self.name)
    
    @property
    def student_count(self) -> int:
        return len(self.students)


@dataclass
class Subject:
    """Предмет"""
    name: str
    subject_type: SubjectType
    hours_per_week: int
    teacher: Teacher
    classes: List[str] = field(default_factory=list)  # Список классов
    is_grouped: bool = False  # Деление на группы
    groups: List[str] = field(default_factory=list)  # Список групп
    
    def __hash__(self):
        return hash((self.name, self.teacher.name, tuple(self.classes)))


@dataclass
class EGEPracticeGroup:
    """Группа учеников для практикума ЕГЭ"""
    subject: str  # Предмет ЕГЭ (например, "Математика проф")
    teacher: Teacher
    students: List[Student] = field(default_factory=list)
    hours_per_week: int = 3  # Обычно 3-4 часа
    
    @property
    def student_count(self) -> int:
        return len(self.students)
    
    @property
    def classes_involved(self) -> Set[str]:
        """Из каких классов ученики"""
        return {student.class_name for student in self.students}


@dataclass
class Lesson:
    """Урок в расписании"""
    subject: str
    teacher: Teacher
    class_or_group: str  # Название класса или группы
    classroom: Optional[Classroom]
    time_slot: TimeSlot
    is_ege_practice: bool = False
    students: List[Student] = field(default_factory=list)
    
    def __str__(self):
        classroom_str = self.classroom.number if self.classroom else "???"
        return f"{self.time_slot}: {self.subject} ({self.teacher.name}) [{self.class_or_group}] в каб. {classroom_str}"


@dataclass
class Schedule:
    """Расписание"""
    lessons: List[Lesson] = field(default_factory=list)
    
    def add_lesson(self, lesson: Lesson):
        """Добавить урок в расписание"""
        self.lessons.append(lesson)
    
    def get_lessons_by_class(self, class_name: str) -> List[Lesson]:
        """Получить все уроки для класса"""
        return [l for l in self.lessons if class_name in l.class_or_group]
    
    def get_lessons_by_teacher(self, teacher_name: str) -> List[Lesson]:
        """Получить все уроки учителя"""
        return [l for l in self.lessons if l.teacher.name == teacher_name]
    
    def get_lessons_by_timeslot(self, time_slot: TimeSlot) -> List[Lesson]:
        """Получить все уроки в определенное время"""
        return [l for l in self.lessons if l.time_slot == time_slot]
    
    def is_teacher_busy(self, teacher: Teacher, time_slot: TimeSlot) -> bool:
        """Проверка, занят ли учитель в данное время"""
        return any(l.teacher == teacher and l.time_slot == time_slot for l in self.lessons)
    
    def is_class_busy(self, class_name: str, time_slot: TimeSlot) -> bool:
        """Проверка, занят ли класс в данное время"""
        return any(class_name in l.class_or_group and l.time_slot == time_slot for l in self.lessons)
    
    def is_classroom_busy(self, classroom: Classroom, time_slot: TimeSlot) -> bool:
        """Проверка, занят ли кабинет в данное время"""
        return any(l.classroom == classroom and l.time_slot == time_slot for l in self.lessons)
    
    def get_teacher_gaps(self, teacher: Teacher) -> int:
        """Подсчет "окон" в расписании учителя"""
        teacher_lessons = self.get_lessons_by_teacher(teacher.name)
        
        gaps = 0
        for day in DayOfWeek:
            day_lessons = [l for l in teacher_lessons if l.time_slot.day == day]
            if not day_lessons:
                continue
            
            lesson_numbers = sorted([l.time_slot.lesson_number for l in day_lessons])
            
            # Считаем окна между первым и последним уроком
            for i in range(lesson_numbers[0], lesson_numbers[-1]):
                if i not in lesson_numbers:
                    gaps += 1
        
        return gaps
    
    def get_class_gaps(self, class_name: str) -> int:
        """Подсчет "окон" в расписании класса"""
        class_lessons = self.get_lessons_by_class(class_name)
        
        gaps = 0
        for day in DayOfWeek:
            day_lessons = [l for l in class_lessons if l.time_slot.day == day]
            if not day_lessons:
                continue
            
            lesson_numbers = sorted([l.time_slot.lesson_number for l in day_lessons])
            
            for i in range(lesson_numbers[0], lesson_numbers[-1]):
                if i not in lesson_numbers:
                    gaps += 1
        
        return gaps
    
    def to_dict(self) -> dict:
        """Экспорт в словарь"""
        return {
            'lessons': [
                {
                    'subject': l.subject,
                    'teacher': l.teacher.name,
                    'class': l.class_or_group,
                    'classroom': l.classroom.number if l.classroom else None,
                    'day': l.time_slot.day.name,
                    'lesson_number': l.time_slot.lesson_number,
                    'is_ege': l.is_ege_practice
                }
                for l in self.lessons
            ]
        }
    
    def save_to_json(self, filename: str):
        """Сохранить расписание в JSON"""
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)


# Модуль schedule_base загружен
