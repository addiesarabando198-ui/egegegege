"""
Модели базы данных для системы расписания
SQLAlchemy ORM
"""

from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


# Связующая таблица: учитель <-> предметы
teacher_subjects = db.Table('teacher_subjects',
    db.Column('teacher_id', db.Integer, db.ForeignKey('teachers.id'), primary_key=True),
    db.Column('subject_id', db.Integer, db.ForeignKey('subjects.id'), primary_key=True)
)

# Связующая таблица: учитель <-> недоступные дни
teacher_unavailable_days = db.Table('teacher_unavailable_days',
    db.Column('teacher_id', db.Integer, db.ForeignKey('teachers.id'), primary_key=True),
    db.Column('day', db.Integer, primary_key=True)  # 0=ПН, 1=ВТ, 2=СР, 3=ЧТ, 4=ПТ
)

# Связующая таблица: ученик <-> предметы ЕГЭ
student_ege_subjects = db.Table('student_ege_subjects',
    db.Column('student_id', db.Integer, db.ForeignKey('students.id'), primary_key=True),
    db.Column('subject_id', db.Integer, db.ForeignKey('subjects.id'), primary_key=True)
)


class Teacher(db.Model):
    """Учитель"""
    __tablename__ = 'teachers'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    short_name = db.Column(db.String(50))  # Сокращённое имя для расписания
    email = db.Column(db.String(200))
    phone = db.Column(db.String(20))
    home_classroom_id = db.Column(db.Integer, db.ForeignKey('classrooms.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Связи
    home_classroom = db.relationship('Classroom', backref='responsible_teachers')
    subjects = db.relationship('Subject', secondary=teacher_subjects, backref='teachers')
    workloads = db.relationship('Workload', backref='teacher', lazy='dynamic')
    lessons = db.relationship('Lesson', backref='teacher', lazy='dynamic')

    # Недоступные дни (хранятся отдельно)

    def get_unavailable_days(self):
        """Получить список недоступных дней"""
        result = db.session.execute(
            teacher_unavailable_days.select().where(
                teacher_unavailable_days.c.teacher_id == self.id
            )
        ).fetchall()
        return [row.day for row in result]

    def set_unavailable_days(self, days):
        """Установить недоступные дни (список: 0=ПН, 1=ВТ...)"""
        # Удаляем старые
        db.session.execute(
            teacher_unavailable_days.delete().where(
                teacher_unavailable_days.c.teacher_id == self.id
            )
        )
        # Добавляем новые
        for day in days:
            db.session.execute(
                teacher_unavailable_days.insert().values(teacher_id=self.id, day=day)
            )

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'short_name': self.short_name,
            'email': self.email,
            'phone': self.phone,
            'home_classroom_id': self.home_classroom_id,
            'home_classroom': self.home_classroom.number if self.home_classroom else None,
            'subjects': [s.name for s in self.subjects],
            'unavailable_days': self.get_unavailable_days()
        }


class Classroom(db.Model):
    """Кабинет"""
    __tablename__ = 'classrooms'

    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(20), nullable=False, unique=True)
    name = db.Column(db.String(100))  # Название (например, "Актовый зал")
    capacity = db.Column(db.Integer, default=30)
    floor = db.Column(db.Integer, default=1)
    building = db.Column(db.String(100))  # Корпус
    equipment = db.Column(db.Text)  # Оборудование (компьютеры, проектор и т.д.)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Связи
    lessons = db.relationship('Lesson', backref='classroom', lazy='dynamic')

    def to_dict(self):
        return {
            'id': self.id,
            'number': self.number,
            'name': self.name,
            'capacity': self.capacity,
            'floor': self.floor,
            'building': self.building,
            'equipment': self.equipment
        }


class Subject(db.Model):
    """Предмет"""
    __tablename__ = 'subjects'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    short_name = db.Column(db.String(20))  # Сокращение для расписания
    is_ege = db.Column(db.Boolean, default=False)  # Есть ли практикум ЕГЭ
    ege_hours = db.Column(db.Integer, default=0)  # Часов практикума ЕГЭ в неделю
    color = db.Column(db.String(7))  # Цвет для отображения (#RRGGBB)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'short_name': self.short_name,
            'is_ege': self.is_ege,
            'ege_hours': self.ege_hours,
            'color': self.color
        }


class SchoolClass(db.Model):
    """Класс (11-А, 11-Б и т.д.)"""
    __tablename__ = 'school_classes'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(20), nullable=False, unique=True)
    grade = db.Column(db.Integer)  # Параллель (11, 10, 9...)
    letter = db.Column(db.String(5))  # Буква (А, Б, В...)
    profile = db.Column(db.String(100))  # Профиль класса
    student_count = db.Column(db.Integer, default=0)
    classroom_id = db.Column(db.Integer, db.ForeignKey('classrooms.id'))  # Домашний кабинет
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Связи
    classroom = db.relationship('Classroom', backref='home_classes')
    students = db.relationship('Student', backref='school_class', lazy='dynamic')
    workloads = db.relationship('Workload', backref='school_class', lazy='dynamic')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'grade': self.grade,
            'letter': self.letter,
            'profile': self.profile,
            'student_count': self.student_count,
            'classroom_id': self.classroom_id
        }


class Student(db.Model):
    """Ученик"""
    __tablename__ = 'students'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('school_classes.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Связи
    ege_subjects = db.relationship('Subject', secondary=student_ege_subjects, backref='ege_students')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'class_id': self.class_id,
            'class_name': self.school_class.name if self.school_class else None,
            'ege_subjects': [s.name for s in self.ege_subjects]
        }


class Workload(db.Model):
    """Нагрузка (связь: предмет-класс-учитель-часы)"""
    __tablename__ = 'workloads'

    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('school_classes.id'), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), nullable=False)
    hours_per_week = db.Column(db.Integer, default=1)
    is_group = db.Column(db.Boolean, default=False)  # Деление на группы
    group_number = db.Column(db.Integer)  # Номер группы (1 или 2)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Связи
    subject = db.relationship('Subject', backref='workloads')

    def to_dict(self):
        return {
            'id': self.id,
            'subject_id': self.subject_id,
            'subject_name': self.subject.name if self.subject else None,
            'class_id': self.class_id,
            'class_name': self.school_class.name if self.school_class else None,
            'teacher_id': self.teacher_id,
            'teacher_name': self.teacher.name if self.teacher else None,
            'hours_per_week': self.hours_per_week,
            'is_group': self.is_group,
            'group_number': self.group_number
        }


class Schedule(db.Model):
    """Версия расписания"""
    __tablename__ = 'schedules'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=False)  # Текущее активное расписание
    valid_from = db.Column(db.Date)  # Действует с
    valid_to = db.Column(db.Date)  # Действует до
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Связи
    lessons = db.relationship('Lesson', backref='schedule', lazy='dynamic', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'is_active': self.is_active,
            'valid_from': self.valid_from.isoformat() if self.valid_from else None,
            'valid_to': self.valid_to.isoformat() if self.valid_to else None,
            'lessons_count': self.lessons.count(),
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }


class Lesson(db.Model):
    """Урок в расписании"""
    __tablename__ = 'lessons'

    id = db.Column(db.Integer, primary_key=True)
    schedule_id = db.Column(db.Integer, db.ForeignKey('schedules.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('school_classes.id'))
    classroom_id = db.Column(db.Integer, db.ForeignKey('classrooms.id'))

    day = db.Column(db.Integer, nullable=False)  # 0=ПН, 1=ВТ, 2=СР, 3=ЧТ, 4=ПТ
    lesson_number = db.Column(db.Integer, nullable=False)  # 1-7

    is_ege_practice = db.Column(db.Boolean, default=False)  # Практикум ЕГЭ
    group_name = db.Column(db.String(100))  # Название группы (для практикумов)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Связи
    subject = db.relationship('Subject', backref='lessons')
    school_class = db.relationship('SchoolClass', backref='lessons')

    def to_dict(self):
        return {
            'id': self.id,
            'schedule_id': self.schedule_id,
            'subject_id': self.subject_id,
            'subject_name': self.subject.name if self.subject else None,
            'subject_short': self.subject.short_name if self.subject else None,
            'subject_color': self.subject.color if self.subject else None,
            'teacher_id': self.teacher_id,
            'teacher_name': self.teacher.name if self.teacher else None,
            'class_id': self.class_id,
            'class_name': self.school_class.name if self.school_class else None,
            'classroom_id': self.classroom_id,
            'classroom_number': self.classroom.number if self.classroom else None,
            'day': self.day,
            'lesson_number': self.lesson_number,
            'is_ege_practice': self.is_ege_practice,
            'group_name': self.group_name
        }


class ScheduleHistory(db.Model):
    """История изменений расписания"""
    __tablename__ = 'schedule_history'

    id = db.Column(db.Integer, primary_key=True)
    schedule_id = db.Column(db.Integer, db.ForeignKey('schedules.id'), nullable=False)
    action = db.Column(db.String(50))  # create, update, delete, move
    lesson_id = db.Column(db.Integer)
    old_data = db.Column(db.JSON)
    new_data = db.Column(db.JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Связи
    schedule = db.relationship('Schedule', backref='history')

    def to_dict(self):
        return {
            'id': self.id,
            'schedule_id': self.schedule_id,
            'action': self.action,
            'lesson_id': self.lesson_id,
            'old_data': self.old_data,
            'new_data': self.new_data,
            'created_at': self.created_at.isoformat()
        }


def init_db(app):
    """Инициализация базы данных"""
    db.init_app(app)
    with app.app_context():
        db.create_all()

        # Создаём базовые предметы, если их нет
        if Subject.query.count() == 0:
            default_subjects = [
                ('Русский язык', 'Рус', True, 3, '#e74c3c'),
                ('Литература', 'Лит', True, 3, '#9b59b6'),
                ('Математика', 'Мат', False, 0, '#3498db'),
                ('Алгебра', 'Алг', False, 0, '#2980b9'),
                ('Геометрия', 'Геом', False, 0, '#1abc9c'),
                ('Математика базовая', 'Мат(б)', True, 3, '#3498db'),
                ('Математика профильная', 'Мат(п)', True, 3, '#2980b9'),
                ('История', 'Ист', True, 4, '#e67e22'),
                ('Обществознание', 'Общ', True, 4, '#f39c12'),
                ('Физика', 'Физ', True, 4, '#1abc9c'),
                ('Химия', 'Хим', True, 4, '#16a085'),
                ('Биология', 'Био', True, 4, '#27ae60'),
                ('География', 'Гео', True, 3, '#2ecc71'),
                ('Английский язык', 'Англ', True, 4, '#3498db'),
                ('Немецкий язык', 'Нем', True, 4, '#9b59b6'),
                ('Французский язык', 'Фр', True, 4, '#e91e63'),
                ('Информатика', 'Инф', True, 4, '#607d8b'),
                ('Физкультура', 'Физ-ра', False, 0, '#95a5a6'),
                ('ОБЖ', 'ОБЖ', False, 0, '#7f8c8d'),
            ]

            for name, short, is_ege, hours, color in default_subjects:
                subject = Subject(
                    name=name,
                    short_name=short,
                    is_ege=is_ege,
                    ege_hours=hours,
                    color=color
                )
                db.session.add(subject)

            db.session.commit()
