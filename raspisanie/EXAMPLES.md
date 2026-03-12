# 🚀 Примеры использования

## Быстрый старт

### 1. Базовое использование

```python
from data_loader import DataLoader
from schedule_generator import ScheduleGenerator

# Загрузка данных
loader = DataLoader()
loader.load_classrooms('data/Здания__кабинеты__места__школьные_здания_.xlsx')
loader.load_teachers_and_subjects('data/Расстановка_кадров_ФЕВРАЛЬ_2025-2026_учебный_год__2_.xlsx')
loader.load_students_and_ege_choices('data/Список_участников_ГИА-11_ГБОУ_Школа__Покровский_квартал___41_.xlsx')
loader.create_ege_practice_groups()

# Генерация расписания
generator = ScheduleGenerator(loader)
generator.place_ege_practices()  # Фаза 1

# Сохранение
generator.schedule.save_to_json('output/schedule.json')
print(f"Создано {len(generator.schedule.lessons)} уроков")
```

### 2. Проверка загруженных данных

```python
from data_loader import DataLoader

loader = DataLoader()
# ... загрузка данных ...

# Проверка учителей
print(f"Всего учителей: {len(loader.teachers)}")
for name, teacher in list(loader.teachers.items())[:5]:
    print(f"  {name}: {', '.join(teacher.subjects[:3])}")

# Проверка групп ЕГЭ
print(f"\nВсего групп ЕГЭ: {len(loader.ege_groups)}")
for group in loader.ege_groups[:5]:
    print(f"  {group.subject}: {group.student_count} учеников")
```

### 3. Анализ расписания

```python
from schedule_base import DayOfWeek

# Получить расписание учителя
teacher = loader.teachers["Иванов И.И."]
lessons = generator.schedule.get_lessons_by_teacher(teacher.name)
print(f"У учителя {teacher.name} {len(lessons)} уроков")

# Подсчитать окна
gaps = generator.schedule.get_teacher_gaps(teacher)
print(f"Окон: {gaps}")

# Расписание по дням
for day in DayOfWeek:
    day_lessons = [l for l in lessons if l.time_slot.day == day]
    print(f"{day.name}: {len(day_lessons)} уроков")
```

### 4. Поиск конфликтов

```python
def find_conflicts(schedule):
    """Найти конфликты в расписании"""
    conflicts = []
    
    for lesson1 in schedule.lessons:
        for lesson2 in schedule.lessons:
            if lesson1 == lesson2:
                continue
            
            if lesson1.time_slot != lesson2.time_slot:
                continue
            
            # Один учитель в двух местах
            if lesson1.teacher == lesson2.teacher:
                conflicts.append(f"Учитель {lesson1.teacher.name} занят в двух местах: {lesson1.time_slot}")
            
            # Один класс в двух местах
            if lesson1.class_or_group == lesson2.class_or_group:
                conflicts.append(f"Класс {lesson1.class_or_group} занят в двух местах: {lesson1.time_slot}")
            
            # Один кабинет для двух уроков
            if lesson1.classroom and lesson2.classroom and lesson1.classroom == lesson2.classroom:
                conflicts.append(f"Кабинет {lesson1.classroom.number} занят дважды: {lesson1.time_slot}")
    
    return conflicts

conflicts = find_conflicts(generator.schedule)
if conflicts:
    print("Найдены конфликты:")
    for conflict in conflicts[:10]:
        print(f"  ⚠️ {conflict}")
else:
    print("✅ Конфликтов не найдено")
```

### 5. Статистика по расписанию

```python
from collections import defaultdict

def print_statistics(schedule, loader):
    """Вывести статистику по расписанию"""
    print("\n" + "="*100)
    print("СТАТИСТИКА РАСПИСАНИЯ")
    print("="*100)
    
    # Общая информация
    print(f"\n📊 Всего уроков: {len(schedule.lessons)}")
    print(f"🎯 Практикумов ЕГЭ: {sum(1 for l in schedule.lessons if l.is_ege_practice)}")
    
    # По дням недели
    print("\n⏰ Распределение по дням:")
    for day in DayOfWeek:
        day_lessons = [l for l in schedule.lessons if l.time_slot.day == day]
        print(f"  {day.name:10s}: {len(day_lessons):3d} уроков")
    
    # Загрузка учителей
    print("\n👨‍🏫 Топ-5 самых загруженных учителей:")
    teacher_loads = defaultdict(int)
    for lesson in schedule.lessons:
        teacher_loads[lesson.teacher.name] += 1
    
    for i, (teacher, count) in enumerate(sorted(teacher_loads.items(), 
                                                key=lambda x: x[1], 
                                                reverse=True)[:5], 1):
        gaps = schedule.get_teacher_gaps(loader.teachers[teacher])
        print(f"  {i}. {teacher:30s}: {count:2d} уроков, {gaps} окон")
    
    # Окна
    print("\n🕳️ Окна в расписании:")
    total_gaps = sum(schedule.get_teacher_gaps(t) for t in loader.teachers.values())
    print(f"  У учителей: {total_gaps}")
    
    total_class_gaps = sum(schedule.get_class_gaps(c) for c in loader.classes.keys())
    print(f"  У классов: {total_class_gaps}")
    
    print("="*100)

print_statistics(generator.schedule, loader)
```

### 6. Экспорт данных

```python
import json

# Экспорт в JSON с дополнительной информацией
def export_detailed_json(schedule, filename):
    """Детальный экспорт в JSON"""
    data = {
        'metadata': {
            'total_lessons': len(schedule.lessons),
            'generated_at': '2026-01-31',
            'version': '0.1.0'
        },
        'lessons': []
    }
    
    for lesson in schedule.lessons:
        data['lessons'].append({
            'subject': lesson.subject,
            'teacher': lesson.teacher.name,
            'class': lesson.class_or_group,
            'classroom': lesson.classroom.number if lesson.classroom else None,
            'day': lesson.time_slot.day.name,
            'lesson_number': lesson.time_slot.lesson_number,
            'is_ege': lesson.is_ege_practice,
            'students_count': len(lesson.students) if lesson.students else 0
        })
    
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

export_detailed_json(generator.schedule, 'output/schedule_detailed.json')
```

## Примеры отладки

### Проверка доступности учителей

```python
def check_teacher_availability():
    """Проверить доступность учителей по дням"""
    from schedule_base import DayOfWeek
    
    loader = DataLoader()
    loader.load_teachers_and_subjects('data/...')
    
    for day in DayOfWeek:
        unavailable = [t.name for t in loader.teachers.values() 
                      if not t.is_available(day)]
        if unavailable:
            print(f"{day.name}: недоступны {len(unavailable)} учителей")
            for teacher in unavailable[:5]:
                print(f"  - {teacher}")
```

### Проверка вместимости кабинетов

```python
def check_classroom_capacity(schedule, loader):
    """Проверить, что в кабинетах достаточно мест"""
    for lesson in schedule.lessons:
        if not lesson.classroom:
            continue
        
        students_count = len(lesson.students) if lesson.students else 0
        capacity = lesson.classroom.capacity
        
        if students_count > capacity:
            print(f"⚠️ {lesson.subject} в {lesson.time_slot}: "
                  f"{students_count} учеников > {capacity} мест (каб. {lesson.classroom.number})")
```

### Визуализация расписания учителя

```python
def visualize_teacher_schedule(schedule, teacher_name):
    """Визуализация расписания учителя"""
    from schedule_base import DayOfWeek
    
    lessons = schedule.get_lessons_by_teacher(teacher_name)
    
    print(f"\n{'='*80}")
    print(f"Расписание: {teacher_name}")
    print('='*80)
    
    # Создаем таблицу
    days = list(DayOfWeek)
    for lesson_num in range(1, 8):
        row = [f"{lesson_num}"]
        
        for day in days:
            slot = TimeSlot(day, lesson_num)
            lesson = next((l for l in lessons if l.time_slot == slot), None)
            
            if lesson:
                row.append(f"{lesson.class_or_group:8s}")
            else:
                row.append("-" * 8)
        
        print("  ".join(row))
    
    print('='*80)
```

## Работа с данными

### Создание тестовых данных

```python
def create_test_data():
    """Создать минимальный набор тестовых данных"""
    from schedule_base import *
    
    # Учителя
    teacher1 = Teacher(name="Иванов И.И.", subjects=["Математика"], home_classroom="42")
    teacher2 = Teacher(name="Петров П.П.", subjects=["Русский язык"], home_classroom="43")
    
    # Кабинеты
    classroom1 = Classroom(number="42", capacity=30, floor=4)
    classroom2 = Classroom(number="43", capacity=25, floor=4)
    
    # Ученики
    student1 = Student(name="Сидоров С.С.", class_name="11В", 
                      ege_subjects=["Математика профильная", "Физика"])
    student2 = Student(name="Иванова И.И.", class_name="11В",
                      ege_subjects=["Русский язык", "Обществознание"])
    
    # Класс
    class11v = Class(name="11В", profile="Технический", students=[student1, student2])
    
    return {
        'teachers': [teacher1, teacher2],
        'classrooms': [classroom1, classroom2],
        'students': [student1, student2],
        'classes': [class11v]
    }
```

### Сравнение двух расписаний

```python
def compare_schedules(schedule1, schedule2):
    """Сравнить два расписания"""
    
    diff = {
        'added': [],
        'removed': [],
        'changed': []
    }
    
    # Находим изменения
    lessons1 = {(l.subject, l.teacher.name, l.time_slot): l 
                for l in schedule1.lessons}
    lessons2 = {(l.subject, l.teacher.name, l.time_slot): l 
                for l in schedule2.lessons}
    
    # Добавленные
    for key in lessons2:
        if key not in lessons1:
            diff['added'].append(lessons2[key])
    
    # Удаленные
    for key in lessons1:
        if key not in lessons2:
            diff['removed'].append(lessons1[key])
    
    # Изменённые
    for key in lessons1:
        if key in lessons2:
            if lessons1[key].classroom != lessons2[key].classroom:
                diff['changed'].append((lessons1[key], lessons2[key]))
    
    # Вывод
    print(f"Добавлено: {len(diff['added'])}")
    print(f"Удалено: {len(diff['removed'])}")
    print(f"Изменено: {len(diff['changed'])}")
    
    return diff
```

## Интеграция с другими системами

### Экспорт в iCal (календарь)

```python
def export_to_ical(schedule, filename):
    """Экспорт расписания в формат iCal"""
    # Требует библиотеку icalendar
    from icalendar import Calendar, Event
    from datetime import datetime, timedelta
    
    cal = Calendar()
    cal.add('prodid', '-//Генератор расписания//NONSGML v1.0//EN')
    cal.add('version', '2.0')
    
    # Начало учебного года
    start_date = datetime(2026, 2, 2)  # 2 февраля 2026
    
    for lesson in schedule.lessons:
        # Определяем день недели
        day_offset = lesson.time_slot.day.value - 1
        lesson_date = start_date + timedelta(days=day_offset)
        
        # Определяем время
        start_time = datetime.combine(lesson_date, 
                                      get_lesson_time(lesson.time_slot.lesson_number))
        end_time = start_time + timedelta(minutes=40)
        
        # Создаем событие
        event = Event()
        event.add('summary', f"{lesson.subject}")
        event.add('dtstart', start_time)
        event.add('dtend', end_time)
        event.add('location', f"Кабинет {lesson.classroom.number if lesson.classroom else '?'}")
        
        cal.add_component(event)
    
    with open(filename, 'wb') as f:
        f.write(cal.to_ical())

def get_lesson_time(lesson_number):
    """Получить время начала урока"""
    from datetime import time
    times = {
        1: time(9, 0),
        2: time(9, 50),
        3: time(10, 50),
        4: time(11, 40),
        5: time(12, 30),
        6: time(13, 30),
        7: time(14, 20)
    }
    return times.get(lesson_number, time(9, 0))
```

---

## Полезные советы

### 1. Отладочный режим

```python
# Добавьте в начало schedule_generator.py
DEBUG = True

def debug_print(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)

# Используйте вместо print()
debug_print("Размещаем урок:", lesson)
```

### 2. Кэширование результатов

```python
import functools

@functools.lru_cache(maxsize=1000)
def is_slot_available(teacher_name, day, lesson_number):
    """Кэшированная проверка доступности слота"""
    # ...
    pass
```

### 3. Профилирование

```python
import time

def profile_function(func):
    """Декоратор для измерения времени выполнения"""
    def wrapper(*args, **kwargs):
        start = time.time()
        result = func(*args, **kwargs)
        end = time.time()
        print(f"{func.__name__} took {end - start:.2f} seconds")
        return result
    return wrapper

@profile_function
def place_ege_practices(self):
    # ...
    pass
```

---

**Примеры обновлены:** 31.01.2026  
**Версия:** 1.0
