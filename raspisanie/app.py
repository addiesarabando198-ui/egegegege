"""
Веб-приложение для составления расписания
Flask + SQLite + Bootstrap

Запуск: python app.py
"""

import os
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from models import db, init_db, Teacher, Classroom, Subject, SchoolClass, Student, Workload, Schedule, Lesson, ScheduleHistory

# Создание приложения
app = Flask(__name__)
app.config['SECRET_KEY'] = 'school-schedule-secret-key-2024'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///school_data.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Инициализация БД
init_db(app)

# Названия дней недели
DAY_NAMES = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница']
DAY_SHORT = ['ПН', 'ВТ', 'СР', 'ЧТ', 'ПТ']


# ============== ГЛАВНАЯ СТРАНИЦА ==============

@app.route('/')
def index():
    """Главная страница - дашборд"""
    stats = {
        'teachers': Teacher.query.count(),
        'classrooms': Classroom.query.count(),
        'classes': SchoolClass.query.count(),
        'students': Student.query.count(),
        'subjects': Subject.query.count(),
        'workloads': Workload.query.count(),
        'schedules': Schedule.query.count(),
    }

    active_schedule = Schedule.query.filter_by(is_active=True).first()

    return render_template('index.html',
                         stats=stats,
                         active_schedule=active_schedule)


# ============== УЧИТЕЛЯ ==============

@app.route('/teachers')
def teachers_list():
    """Список учителей"""
    teachers = Teacher.query.order_by(Teacher.name).all()
    classrooms = Classroom.query.order_by(Classroom.number).all()
    subjects = Subject.query.order_by(Subject.name).all()
    return render_template('teachers.html',
                         teachers=teachers,
                         classrooms=classrooms,
                         subjects=subjects,
                         day_names=DAY_NAMES)


@app.route('/api/teachers', methods=['GET'])
def api_teachers_list():
    """API: Список учителей"""
    teachers = Teacher.query.order_by(Teacher.name).all()
    return jsonify([t.to_dict() for t in teachers])


@app.route('/api/teachers', methods=['POST'])
def api_teacher_create():
    """API: Создать учителя"""
    data = request.json

    teacher = Teacher(
        name=data['name'],
        short_name=data.get('short_name'),
        email=data.get('email'),
        phone=data.get('phone'),
        home_classroom_id=data.get('home_classroom_id') or None
    )

    db.session.add(teacher)
    db.session.commit()

    # Добавляем предметы
    if 'subject_ids' in data:
        for sid in data['subject_ids']:
            subject = Subject.query.get(sid)
            if subject:
                teacher.subjects.append(subject)

    # Добавляем недоступные дни
    if 'unavailable_days' in data:
        teacher.set_unavailable_days(data['unavailable_days'])

    db.session.commit()

    return jsonify(teacher.to_dict()), 201


@app.route('/api/teachers/<int:id>', methods=['GET'])
def api_teacher_get(id):
    """API: Получить учителя"""
    teacher = Teacher.query.get_or_404(id)
    return jsonify(teacher.to_dict())


@app.route('/api/teachers/<int:id>', methods=['PUT'])
def api_teacher_update(id):
    """API: Обновить учителя"""
    teacher = Teacher.query.get_or_404(id)
    data = request.json

    teacher.name = data.get('name', teacher.name)
    teacher.short_name = data.get('short_name', teacher.short_name)
    teacher.email = data.get('email', teacher.email)
    teacher.phone = data.get('phone', teacher.phone)
    teacher.home_classroom_id = data.get('home_classroom_id') or None

    # Обновляем предметы
    if 'subject_ids' in data:
        teacher.subjects = []
        for sid in data['subject_ids']:
            subject = Subject.query.get(sid)
            if subject:
                teacher.subjects.append(subject)

    # Обновляем недоступные дни
    if 'unavailable_days' in data:
        teacher.set_unavailable_days(data['unavailable_days'])

    db.session.commit()

    return jsonify(teacher.to_dict())


@app.route('/api/teachers/<int:id>', methods=['DELETE'])
def api_teacher_delete(id):
    """API: Удалить учителя"""
    teacher = Teacher.query.get_or_404(id)

    # Проверяем, есть ли уроки у учителя
    if teacher.lessons.count() > 0:
        return jsonify({'error': 'Нельзя удалить учителя с уроками в расписании'}), 400

    db.session.delete(teacher)
    db.session.commit()

    return jsonify({'success': True})


# ============== КАБИНЕТЫ ==============

@app.route('/classrooms')
def classrooms_list():
    """Список кабинетов"""
    classrooms = Classroom.query.order_by(Classroom.number).all()
    return render_template('classrooms.html', classrooms=classrooms)


@app.route('/api/classrooms', methods=['GET'])
def api_classrooms_list():
    """API: Список кабинетов"""
    classrooms = Classroom.query.order_by(Classroom.number).all()
    return jsonify([c.to_dict() for c in classrooms])


@app.route('/api/classrooms', methods=['POST'])
def api_classroom_create():
    """API: Создать кабинет"""
    data = request.json

    classroom = Classroom(
        number=data['number'],
        name=data.get('name'),
        capacity=data.get('capacity', 30),
        floor=data.get('floor', 1),
        building=data.get('building'),
        equipment=data.get('equipment')
    )

    db.session.add(classroom)
    db.session.commit()

    return jsonify(classroom.to_dict()), 201


@app.route('/api/classrooms/<int:id>', methods=['GET'])
def api_classroom_get(id):
    """API: Получить кабинет"""
    classroom = Classroom.query.get_or_404(id)
    return jsonify(classroom.to_dict())


@app.route('/api/classrooms/<int:id>', methods=['PUT'])
def api_classroom_update(id):
    """API: Обновить кабинет"""
    classroom = Classroom.query.get_or_404(id)
    data = request.json

    classroom.number = data.get('number', classroom.number)
    classroom.name = data.get('name', classroom.name)
    classroom.capacity = data.get('capacity', classroom.capacity)
    classroom.floor = data.get('floor', classroom.floor)
    classroom.building = data.get('building', classroom.building)
    classroom.equipment = data.get('equipment', classroom.equipment)

    db.session.commit()

    return jsonify(classroom.to_dict())


@app.route('/api/classrooms/<int:id>', methods=['DELETE'])
def api_classroom_delete(id):
    """API: Удалить кабинет"""
    classroom = Classroom.query.get_or_404(id)

    if classroom.lessons.count() > 0:
        return jsonify({'error': 'Нельзя удалить кабинет с уроками'}), 400

    db.session.delete(classroom)
    db.session.commit()

    return jsonify({'success': True})


# ============== КЛАССЫ ==============

@app.route('/classes')
def classes_list():
    """Список классов"""
    classes = SchoolClass.query.order_by(SchoolClass.grade.desc(), SchoolClass.letter).all()
    classrooms = Classroom.query.order_by(Classroom.number).all()
    return render_template('classes.html', classes=classes, classrooms=classrooms)


@app.route('/api/classes', methods=['GET'])
def api_classes_list():
    """API: Список классов"""
    classes = SchoolClass.query.order_by(SchoolClass.name).all()
    return jsonify([c.to_dict() for c in classes])


@app.route('/api/classes', methods=['POST'])
def api_class_create():
    """API: Создать класс"""
    data = request.json

    school_class = SchoolClass(
        name=data['name'],
        grade=data.get('grade'),
        letter=data.get('letter'),
        profile=data.get('profile'),
        student_count=data.get('student_count', 0),
        classroom_id=data.get('classroom_id') or None
    )

    db.session.add(school_class)
    db.session.commit()

    return jsonify(school_class.to_dict()), 201


@app.route('/api/classes/<int:id>', methods=['GET'])
def api_class_get(id):
    """API: Получить класс"""
    school_class = SchoolClass.query.get_or_404(id)
    return jsonify(school_class.to_dict())


@app.route('/api/classes/<int:id>', methods=['PUT'])
def api_class_update(id):
    """API: Обновить класс"""
    school_class = SchoolClass.query.get_or_404(id)
    data = request.json

    school_class.name = data.get('name', school_class.name)
    school_class.grade = data.get('grade', school_class.grade)
    school_class.letter = data.get('letter', school_class.letter)
    school_class.profile = data.get('profile', school_class.profile)
    school_class.student_count = data.get('student_count', school_class.student_count)
    school_class.classroom_id = data.get('classroom_id') or None

    db.session.commit()

    return jsonify(school_class.to_dict())


@app.route('/api/classes/<int:id>', methods=['DELETE'])
def api_class_delete(id):
    """API: Удалить класс"""
    school_class = SchoolClass.query.get_or_404(id)

    db.session.delete(school_class)
    db.session.commit()

    return jsonify({'success': True})


# ============== ПРЕДМЕТЫ ==============

@app.route('/subjects')
def subjects_list():
    """Список предметов"""
    subjects = Subject.query.order_by(Subject.name).all()
    return render_template('subjects.html', subjects=subjects)


@app.route('/api/subjects', methods=['GET'])
def api_subjects_list():
    """API: Список предметов"""
    subjects = Subject.query.order_by(Subject.name).all()
    return jsonify([s.to_dict() for s in subjects])


@app.route('/api/subjects', methods=['POST'])
def api_subject_create():
    """API: Создать предмет"""
    data = request.json

    subject = Subject(
        name=data['name'],
        short_name=data.get('short_name'),
        is_ege=data.get('is_ege', False),
        ege_hours=data.get('ege_hours', 0),
        color=data.get('color')
    )

    db.session.add(subject)
    db.session.commit()

    return jsonify(subject.to_dict()), 201


@app.route('/api/subjects/<int:id>', methods=['GET'])
def api_subject_get(id):
    """API: Получить предмет"""
    subject = Subject.query.get_or_404(id)
    return jsonify(subject.to_dict())


@app.route('/api/subjects/<int:id>', methods=['PUT'])
def api_subject_update(id):
    """API: Обновить предмет"""
    subject = Subject.query.get_or_404(id)
    data = request.json

    subject.name = data.get('name', subject.name)
    subject.short_name = data.get('short_name', subject.short_name)
    subject.is_ege = data.get('is_ege', subject.is_ege)
    subject.ege_hours = data.get('ege_hours', subject.ege_hours)
    subject.color = data.get('color', subject.color)

    db.session.commit()

    return jsonify(subject.to_dict())


@app.route('/api/subjects/<int:id>', methods=['DELETE'])
def api_subject_delete(id):
    """API: Удалить предмет"""
    subject = Subject.query.get_or_404(id)

    db.session.delete(subject)
    db.session.commit()

    return jsonify({'success': True})


# ============== НАГРУЗКА ==============

@app.route('/workload')
def workload_list():
    """Нагрузка"""
    workloads = Workload.query.join(SchoolClass).order_by(SchoolClass.name).all()
    teachers = Teacher.query.order_by(Teacher.name).all()
    subjects = Subject.query.order_by(Subject.name).all()
    classes = SchoolClass.query.order_by(SchoolClass.name).all()
    return render_template('workload.html',
                         workloads=workloads,
                         teachers=teachers,
                         subjects=subjects,
                         classes=classes)


@app.route('/api/workloads', methods=['GET'])
def api_workload_list():
    """API: Список нагрузки"""
    workloads = Workload.query.all()
    return jsonify([w.to_dict() for w in workloads])


@app.route('/api/workloads', methods=['POST'])
def api_workload_create():
    """API: Создать нагрузку"""
    data = request.json

    workload = Workload(
        subject_id=data['subject_id'],
        class_id=data['class_id'],
        teacher_id=data['teacher_id'],
        hours_per_week=data.get('hours_per_week', 1),
        is_group=data.get('is_group', False),
        group_number=data.get('group_number')
    )

    db.session.add(workload)
    db.session.commit()

    return jsonify(workload.to_dict()), 201


@app.route('/api/workloads/<int:id>', methods=['GET'])
def api_workload_get(id):
    """API: Получить нагрузку"""
    workload = Workload.query.get_or_404(id)
    return jsonify(workload.to_dict())


@app.route('/api/workloads/<int:id>', methods=['PUT'])
def api_workload_update(id):
    """API: Обновить нагрузку"""
    workload = Workload.query.get_or_404(id)
    data = request.json

    workload.subject_id = data.get('subject_id', workload.subject_id)
    workload.class_id = data.get('class_id', workload.class_id)
    workload.teacher_id = data.get('teacher_id', workload.teacher_id)
    workload.hours_per_week = data.get('hours_per_week', workload.hours_per_week)
    workload.is_group = data.get('is_group', workload.is_group)
    workload.group_number = data.get('group_number', workload.group_number)

    db.session.commit()

    return jsonify(workload.to_dict())


@app.route('/api/workloads/<int:id>', methods=['DELETE'])
def api_workload_delete(id):
    """API: Удалить нагрузку"""
    workload = Workload.query.get_or_404(id)

    db.session.delete(workload)
    db.session.commit()

    return jsonify({'success': True})


# ============== РАСПИСАНИЕ ==============

@app.route('/schedule')
def schedule_view():
    """Просмотр расписания"""
    schedules = Schedule.query.order_by(Schedule.created_at.desc()).all()
    active = Schedule.query.filter_by(is_active=True).first()
    classes = SchoolClass.query.order_by(SchoolClass.name).all()
    teachers = Teacher.query.order_by(Teacher.name).all()
    classrooms = Classroom.query.order_by(Classroom.number).all()
    subjects = Subject.query.order_by(Subject.name).all()

    return render_template('schedule.html',
                         schedules=schedules,
                         active_schedule=active,
                         classes=classes,
                         teachers=teachers,
                         classrooms=classrooms,
                         subjects=subjects,
                         day_names=DAY_NAMES,
                         day_short=DAY_SHORT)


@app.route('/api/schedules', methods=['GET'])
def api_schedules_list():
    """API: Список расписаний"""
    schedules = Schedule.query.order_by(Schedule.created_at.desc()).all()
    return jsonify([s.to_dict() for s in schedules])


@app.route('/api/schedules', methods=['POST'])
def api_schedule_create():
    """API: Создать новое расписание"""
    data = request.json

    schedule = Schedule(
        name=data['name'],
        description=data.get('description'),
        is_active=data.get('is_active', False)
    )

    if schedule.is_active:
        # Деактивируем остальные
        Schedule.query.update({'is_active': False})

    db.session.add(schedule)
    db.session.commit()

    return jsonify(schedule.to_dict()), 201


@app.route('/api/schedules/<int:id>', methods=['DELETE'])
def api_schedule_delete(id):
    """API: Удалить расписание"""
    schedule = Schedule.query.get_or_404(id)

    db.session.delete(schedule)
    db.session.commit()

    return jsonify({'success': True})


@app.route('/api/schedules/<int:id>/activate', methods=['POST'])
def api_schedule_activate(id):
    """API: Активировать расписание"""
    schedule = Schedule.query.get_or_404(id)

    Schedule.query.update({'is_active': False})
    schedule.is_active = True
    db.session.commit()

    return jsonify(schedule.to_dict())


@app.route('/api/schedules/<int:id>/export', methods=['GET'])
def api_schedule_export(id):
    """API: Экспорт расписания в CSV"""
    from flask import Response
    import csv
    import io

    schedule = Schedule.query.get_or_404(id)
    lessons = schedule.lessons.order_by(Lesson.day, Lesson.lesson_number).all()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')

    # Заголовок
    writer.writerow(['День', 'Урок', 'Предмет', 'Учитель', 'Класс', 'Кабинет'])

    day_names = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница']

    for lesson in lessons:
        writer.writerow([
            day_names[lesson.day] if lesson.day < 5 else str(lesson.day),
            lesson.lesson_number,
            lesson.subject.name if lesson.subject else '',
            lesson.teacher.name if lesson.teacher else '',
            lesson.school_class.name if lesson.school_class else '',
            lesson.classroom.number if lesson.classroom else ''
        ])

    output.seek(0)
    return Response(
        '\ufeff' + output.read(),  # BOM for Excel
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=schedule_{id}.csv'}
    )


@app.route('/api/schedules/<int:id>/lessons', methods=['GET'])
def api_schedule_lessons(id):
    """API: Уроки расписания с фильтрацией"""
    schedule = Schedule.query.get_or_404(id)

    view_mode = request.args.get('view', 'class')
    filter_id = request.args.get('filter_id')

    query = Lesson.query.filter_by(schedule_id=id)

    if filter_id:
        if view_mode == 'class':
            query = query.filter_by(class_id=int(filter_id))
        elif view_mode == 'teacher':
            query = query.filter_by(teacher_id=int(filter_id))
        elif view_mode == 'classroom':
            query = query.filter_by(classroom_id=int(filter_id))

    lessons = query.all()
    return jsonify([l.to_dict() for l in lessons])


@app.route('/api/schedules/<int:id>/lessons/class/<int:class_id>', methods=['GET'])
def api_schedule_lessons_by_class(id, class_id):
    """API: Уроки расписания для класса"""
    lessons = Lesson.query.filter_by(schedule_id=id, class_id=class_id).all()
    return jsonify([l.to_dict() for l in lessons])


@app.route('/api/schedules/<int:id>/lessons/teacher/<int:teacher_id>', methods=['GET'])
def api_schedule_lessons_by_teacher(id, teacher_id):
    """API: Уроки расписания для учителя"""
    lessons = Lesson.query.filter_by(schedule_id=id, teacher_id=teacher_id).all()
    return jsonify([l.to_dict() for l in lessons])


# ============== УРОКИ (CRUD + Drag-and-Drop) ==============

@app.route('/api/lessons', methods=['POST'])
def api_lesson_create():
    """API: Создать урок"""
    data = request.json

    # Проверка конфликтов
    conflicts = check_lesson_conflicts(data)
    if conflicts:
        return jsonify({'error': 'Конфликт', 'conflicts': conflicts}), 400

    lesson = Lesson(
        schedule_id=data['schedule_id'],
        subject_id=data['subject_id'],
        teacher_id=data['teacher_id'],
        class_id=data.get('class_id'),
        classroom_id=data.get('classroom_id'),
        day=data['day'],
        lesson_number=data['lesson_number'],
        is_ege_practice=data.get('is_ege_practice', False),
        group_name=data.get('group_name')
    )

    db.session.add(lesson)
    db.session.commit()

    # Записываем в историю
    log_history(lesson.schedule_id, 'create', lesson.id, None, lesson.to_dict())

    return jsonify(lesson.to_dict()), 201


@app.route('/api/lessons/<int:id>', methods=['PUT'])
def api_lesson_update(id):
    """API: Обновить урок (перетаскивание)"""
    lesson = Lesson.query.get_or_404(id)
    data = request.json

    old_data = lesson.to_dict()

    # Проверка конфликтов (исключая текущий урок)
    conflicts = check_lesson_conflicts(data, exclude_id=id)
    if conflicts:
        return jsonify({'error': 'Конфликт', 'conflicts': conflicts}), 400

    lesson.day = data.get('day', lesson.day)
    lesson.lesson_number = data.get('lesson_number', lesson.lesson_number)
    lesson.classroom_id = data.get('classroom_id', lesson.classroom_id)
    lesson.teacher_id = data.get('teacher_id', lesson.teacher_id)

    db.session.commit()

    # Записываем в историю
    log_history(lesson.schedule_id, 'move', lesson.id, old_data, lesson.to_dict())

    return jsonify(lesson.to_dict())


@app.route('/api/lessons/<int:id>', methods=['DELETE'])
def api_lesson_delete(id):
    """API: Удалить урок"""
    lesson = Lesson.query.get_or_404(id)

    old_data = lesson.to_dict()
    schedule_id = lesson.schedule_id

    db.session.delete(lesson)
    db.session.commit()

    # Записываем в историю
    log_history(schedule_id, 'delete', id, old_data, None)

    return jsonify({'success': True})


@app.route('/api/lessons/<int:id>/move', methods=['PUT'])
def api_lesson_move(id):
    """API: Переместить урок (drag-and-drop)"""
    lesson = Lesson.query.get_or_404(id)
    data = request.json

    old_data = lesson.to_dict()
    new_day = data.get('day', lesson.day)
    new_lesson_number = data.get('lesson_number', lesson.lesson_number)

    # Проверка конфликтов
    check_data = {
        'schedule_id': lesson.schedule_id,
        'day': new_day,
        'lesson_number': new_lesson_number,
        'teacher_id': lesson.teacher_id,
        'class_id': lesson.class_id,
        'classroom_id': lesson.classroom_id
    }
    conflicts = check_lesson_conflicts(check_data, exclude_id=id)
    if conflicts:
        return jsonify({'success': False, 'error': '; '.join([c['message'] for c in conflicts])}), 400

    lesson.day = new_day
    lesson.lesson_number = new_lesson_number
    db.session.commit()

    # Записываем в историю
    log_history(lesson.schedule_id, 'move', lesson.id, old_data, lesson.to_dict())

    return jsonify({'success': True, 'lesson': lesson.to_dict()})


def check_lesson_conflicts(data, exclude_id=None):
    """Проверка конфликтов при размещении урока"""
    conflicts = []

    schedule_id = data.get('schedule_id')
    day = data.get('day')
    lesson_number = data.get('lesson_number')
    teacher_id = data.get('teacher_id')
    class_id = data.get('class_id')
    classroom_id = data.get('classroom_id')

    # Базовый запрос
    query = Lesson.query.filter_by(
        schedule_id=schedule_id,
        day=day,
        lesson_number=lesson_number
    )

    if exclude_id:
        query = query.filter(Lesson.id != exclude_id)

    existing = query.all()

    for lesson in existing:
        # Учитель занят
        if lesson.teacher_id == teacher_id:
            conflicts.append({
                'type': 'teacher',
                'message': f'Учитель уже ведёт урок: {lesson.subject.name} ({lesson.school_class.name if lesson.school_class else lesson.group_name})'
            })

        # Класс занят
        if class_id and lesson.class_id == class_id:
            conflicts.append({
                'type': 'class',
                'message': f'Класс уже занят: {lesson.subject.name}'
            })

        # Кабинет занят
        if classroom_id and lesson.classroom_id == classroom_id:
            conflicts.append({
                'type': 'classroom',
                'message': f'Кабинет занят: {lesson.subject.name}'
            })

    return conflicts


def log_history(schedule_id, action, lesson_id, old_data, new_data):
    """Записать изменение в историю"""
    history = ScheduleHistory(
        schedule_id=schedule_id,
        action=action,
        lesson_id=lesson_id,
        old_data=old_data,
        new_data=new_data
    )
    db.session.add(history)
    db.session.commit()


# ============== ГЕНЕРАЦИЯ РАСПИСАНИЯ ==============

@app.route('/generate')
def generate_page():
    """Страница генерации расписания"""
    from datetime import datetime
    stats = {
        'teachers': Teacher.query.count(),
        'classrooms': Classroom.query.count(),
        'classes': SchoolClass.query.count(),
        'subjects': Subject.query.count(),
        'workloads': Workload.query.count(),
    }
    schedules = Schedule.query.order_by(Schedule.created_at.desc()).all()
    return render_template('generate.html', stats=stats, schedules=schedules, now=datetime.now())


@app.route('/api/generate', methods=['POST'])
def api_generate_schedule():
    """API: Сгенерировать расписание"""
    data = request.json

    # Создаём новое расписание
    schedule = Schedule(
        name=data.get('name', f'Расписание {Schedule.query.count() + 1}'),
        description=data.get('description', 'Автоматически сгенерировано')
    )
    db.session.add(schedule)
    db.session.commit()

    # TODO: Интеграция с алгоритмом генерации
    # Пока просто возвращаем созданное расписание

    return jsonify({
        'success': True,
        'schedule': schedule.to_dict(),
        'message': 'Расписание создано. Алгоритм генерации будет добавлен позже.'
    })


# ============== ИМПОРТ EXCEL ==============

@app.route('/import')
def import_page():
    """Страница импорта"""
    return render_template('import.html')


@app.route('/api/import', methods=['POST'])
def api_import_data():
    """API: Импорт данных из Excel"""
    if 'file' not in request.files:
        return jsonify({'error': 'Файл не загружен'}), 400

    file = request.files['file']
    import_type = request.form.get('type', 'teachers')
    skip_existing = request.form.get('skip_existing') == 'true'

    try:
        import pandas as pd
        df = pd.read_excel(file)
    except Exception as e:
        return jsonify({'error': f'Ошибка чтения файла: {str(e)}'}), 400

    added = 0
    skipped = 0
    errors = []

    if import_type == 'teachers':
        for idx, row in df.iterrows():
            try:
                name = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else None
                if not name:
                    continue

                existing = Teacher.query.filter_by(name=name).first()
                if existing:
                    if skip_existing:
                        skipped += 1
                        continue
                    teacher = existing
                else:
                    teacher = Teacher(name=name)
                    db.session.add(teacher)

                if len(row) > 1 and pd.notna(row.iloc[1]):
                    teacher.short_name = str(row.iloc[1]).strip()
                if len(row) > 2 and pd.notna(row.iloc[2]):
                    teacher.email = str(row.iloc[2]).strip()
                if len(row) > 3 and pd.notna(row.iloc[3]):
                    teacher.phone = str(row.iloc[3]).strip()

                added += 1
            except Exception as e:
                errors.append(f'Строка {idx + 2}: {str(e)}')

    elif import_type == 'classrooms':
        for idx, row in df.iterrows():
            try:
                number = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else None
                if not number:
                    continue

                existing = Classroom.query.filter_by(number=number).first()
                if existing:
                    if skip_existing:
                        skipped += 1
                        continue
                    classroom = existing
                else:
                    classroom = Classroom(number=number)
                    db.session.add(classroom)

                if len(row) > 1 and pd.notna(row.iloc[1]):
                    classroom.name = str(row.iloc[1]).strip()
                if len(row) > 2 and pd.notna(row.iloc[2]):
                    classroom.capacity = int(row.iloc[2])
                if len(row) > 3 and pd.notna(row.iloc[3]):
                    classroom.floor = int(row.iloc[3])
                if len(row) > 4 and pd.notna(row.iloc[4]):
                    classroom.building = str(row.iloc[4]).strip()

                added += 1
            except Exception as e:
                errors.append(f'Строка {idx + 2}: {str(e)}')

    elif import_type == 'classes':
        for idx, row in df.iterrows():
            try:
                name = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else None
                if not name:
                    continue

                existing = SchoolClass.query.filter_by(name=name).first()
                if existing:
                    if skip_existing:
                        skipped += 1
                        continue
                    school_class = existing
                else:
                    school_class = SchoolClass(name=name)
                    db.session.add(school_class)

                # Парсим параллель и букву из названия (например, "11-А")
                import re
                match = re.match(r'(\d+)[- ]?([А-Яа-яA-Za-z]*)', name)
                if match:
                    school_class.grade = int(match.group(1))
                    school_class.letter = match.group(2).upper() if match.group(2) else None

                if len(row) > 1 and pd.notna(row.iloc[1]):
                    school_class.profile = str(row.iloc[1]).strip()
                if len(row) > 2 and pd.notna(row.iloc[2]):
                    school_class.student_count = int(row.iloc[2])

                added += 1
            except Exception as e:
                errors.append(f'Строка {idx + 2}: {str(e)}')

    elif import_type == 'subjects':
        for idx, row in df.iterrows():
            try:
                name = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else None
                if not name:
                    continue

                existing = Subject.query.filter_by(name=name).first()
                if existing:
                    if skip_existing:
                        skipped += 1
                        continue
                    subject = existing
                else:
                    subject = Subject(name=name)
                    db.session.add(subject)

                if len(row) > 1 and pd.notna(row.iloc[1]):
                    subject.short_name = str(row.iloc[1]).strip()
                if len(row) > 2 and pd.notna(row.iloc[2]):
                    subject.is_ege = str(row.iloc[2]).lower() in ['да', 'yes', '1', 'true']
                if len(row) > 3 and pd.notna(row.iloc[3]):
                    subject.ege_hours = int(row.iloc[3])

                added += 1
            except Exception as e:
                errors.append(f'Строка {idx + 2}: {str(e)}')

    elif import_type == 'workload':
        for idx, row in df.iterrows():
            try:
                # Ищем учителя по имени
                teacher_name = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else None
                if not teacher_name:
                    continue

                teacher = Teacher.query.filter(Teacher.name.ilike(f'%{teacher_name}%')).first()
                if not teacher:
                    errors.append(f'Строка {idx + 2}: Учитель "{teacher_name}" не найден')
                    continue

                # Ищем предмет
                subject_name = str(row.iloc[1]).strip() if len(row) > 1 and pd.notna(row.iloc[1]) else None
                if not subject_name:
                    continue

                subject = Subject.query.filter(Subject.name.ilike(f'%{subject_name}%')).first()
                if not subject:
                    errors.append(f'Строка {idx + 2}: Предмет "{subject_name}" не найден')
                    continue

                # Ищем класс
                class_name = str(row.iloc[2]).strip() if len(row) > 2 and pd.notna(row.iloc[2]) else None
                if not class_name:
                    continue

                school_class = SchoolClass.query.filter_by(name=class_name).first()
                if not school_class:
                    errors.append(f'Строка {idx + 2}: Класс "{class_name}" не найден')
                    continue

                # Часы в неделю
                hours = 1
                if len(row) > 3 and pd.notna(row.iloc[3]):
                    hours = int(row.iloc[3])

                # Группа
                is_group = False
                group_number = None
                if len(row) > 4 and pd.notna(row.iloc[4]):
                    group_val = str(row.iloc[4]).strip()
                    if group_val in ['1', '2']:
                        is_group = True
                        group_number = int(group_val)

                # Проверяем дубликаты
                existing = Workload.query.filter_by(
                    teacher_id=teacher.id,
                    subject_id=subject.id,
                    class_id=school_class.id,
                    group_number=group_number
                ).first()

                if existing:
                    if skip_existing:
                        skipped += 1
                        continue
                    existing.hours_per_week = hours
                else:
                    workload = Workload(
                        teacher_id=teacher.id,
                        subject_id=subject.id,
                        class_id=school_class.id,
                        hours_per_week=hours,
                        is_group=is_group,
                        group_number=group_number
                    )
                    db.session.add(workload)

                added += 1
            except Exception as e:
                errors.append(f'Строка {idx + 2}: {str(e)}')

    db.session.commit()

    return jsonify({
        'success': True,
        'added': added,
        'skipped': skipped,
        'errors': errors
    })


# ============== ЗАПУСК ==============

if __name__ == '__main__':
    print("=" * 60)
    print("  Генератор расписания - Школа Покровский квартал")
    print("=" * 60)
    print("\n  Откройте в браузере: http://localhost:5000\n")
    print("=" * 60)

    app.run(debug=True, host='localhost', port=5000)
