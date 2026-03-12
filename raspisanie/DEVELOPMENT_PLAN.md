# 📋 План разработки

## Текущее состояние: Альфа v0.1 (40%)

**Что работает:**
- ✅ Загрузка всех данных из Excel
- ✅ Формирование групп для практикумов ЕГЭ
- ✅ Поиск оптимальных временных слотов
- ✅ Размещение практикумов ЕГЭ

**Что требует доработки:**
- ⚠️ Назначение правильных учителей для практикумов ЕГЭ
- ⚠️ Обработка больших групп (>60 человек)

**Что не реализовано:**
- ❌ Размещение обязательных предметов
- ❌ Оптимизация расписания
- ❌ Экспорт в Excel
- ❌ Веб-интерфейс

---

## Этап 1: Исправление критических ошибок (1-2 дня)

### Задача 1.1: Правильное назначение учителей для практикумов ЕГЭ

**Приоритет:** 🔴 КРИТИЧЕСКИЙ

**Проблема:**  
Все группы практикумов ЕГЭ сейчас назначены одному учителю (Шнайдер О.А.), что неверно.

**Решение:**

1. В `data_loader.py`, метод `load_teachers_and_subjects()`:
   ```python
   # Создаем маппинг: практикум ЕГЭ по предмету → учитель
   self.ege_teachers = {}  # Dict[str, Teacher]
   
   # При обработке строк
   if 'Практикум ЕГЭ по' in subject_name:
       # Извлекаем предмет: "Практикум ЕГЭ по русскому языку" → "русскому языку"
       ege_subject = subject_name.split('по ')[1].strip()
       
       # Нормализуем название (убираем падежи)
       normalized = normalize_subject_name(ege_subject)
       # "русскому языку" → "Русский язык"
       
       self.ege_teachers[normalized] = current_teacher
   ```

2. В методе `create_ege_practice_groups()`:
   ```python
   for ege_subject, students_list in subject_students.items():
       # Находим учителя из маппинга
       teacher = self.ege_teachers.get(ege_subject)
       
       if not teacher:
           print(f"⚠️ Не найден учитель для практикума ЕГЭ: {ege_subject}")
           # Временное решение: взять любого учителя этого предмета
           teacher = self.find_subject_teacher(ege_subject)
       
       group = EGEPracticeGroup(
           subject=ege_subject,
           teacher=teacher,
           students=students_list,
           hours_per_week=hours
       )
   ```

3. Добавить вспомогательные функции:
   ```python
   def normalize_subject_name(name: str) -> str:
       """Нормализация названия предмета"""
       mapping = {
           'русскому языку': 'Русский язык',
           'математике': 'Математика профильная',
           'английскому языку': 'Английский язык',
           # и т.д.
       }
       return mapping.get(name.lower(), name)
   
   def find_subject_teacher(self, subject: str) -> Teacher:
       """Поиск учителя по предмету"""
       for subj in self.subjects:
           if subject.lower() in subj.name.lower():
               return subj.teacher
       return list(self.teachers.values())[0]  # fallback
   ```

**Тестирование:**
```bash
python data_loader.py
# Проверить: у каждой группы ЕГЭ свой учитель
```

**Критерий успеха:**  
После запуска каждая группа практикума ЕГЭ имеет корректного учителя.

---

### Задача 1.2: Обработка больших групп

**Приоритет:** 🟡 ВАЖНЫЙ

**Проблема:**  
Практикум по русскому языку выбрали 255 учеников, но максимальная вместимость кабинета - 60 человек.

**Варианты решения:**

**Вариант А: Разделение на подгруппы**
```python
def split_large_groups(self):
    """Разделение больших групп на подгруппы"""
    max_group_size = 60
    
    new_groups = []
    for group in self.ege_groups:
        if group.student_count > max_group_size:
            # Делим на подгруппы
            num_subgroups = (group.student_count + max_group_size - 1) // max_group_size
            
            for i in range(num_subgroups):
                start = i * max_group_size
                end = min((i + 1) * max_group_size, group.student_count)
                
                subgroup = EGEPracticeGroup(
                    subject=f"{group.subject} (группа {i+1})",
                    teacher=group.teacher,
                    students=group.students[start:end],
                    hours_per_week=group.hours_per_week
                )
                new_groups.append(subgroup)
        else:
            new_groups.append(group)
    
    self.ege_groups = new_groups
```

**Вариант Б: Использование нескольких кабинетов**
```python
def assign_multiple_classrooms(self, lesson: Lesson) -> List[Classroom]:
    """Назначить несколько кабинетов для большой группы"""
    required_capacity = len(lesson.students)
    classrooms = []
    current_capacity = 0
    
    for classroom in sorted(self.classrooms.values(), 
                           key=lambda c: c.capacity, reverse=True):
        if not self.schedule.is_classroom_busy(classroom, lesson.time_slot):
            classrooms.append(classroom)
            current_capacity += classroom.capacity
            
            if current_capacity >= required_capacity:
                break
    
    return classrooms
```

**Рекомендация:** Использовать **Вариант А** (разделение на подгруппы), так как это более реалистично.

**Критерий успеха:**  
Все группы имеют размер ≤ 60 человек и назначены в подходящие кабинеты.

---

## Этап 2: Размещение обязательных предметов (2-3 дня)

### Задача 2.1: Базовый алгоритм размещения

**Приоритет:** 🔴 КРИТИЧЕСКИЙ

**Реализация:**

1. Создать метод `place_mandatory_subjects()` в `schedule_generator.py`:

```python
def place_mandatory_subjects(self):
    """Размещение обязательных предметов"""
    print("\n" + "="*100)
    print(" " * 30 + "ФАЗА 2: РАЗМЕЩЕНИЕ ОБЯЗАТЕЛЬНЫХ ПРЕДМЕТОВ")
    print("="*100)
    
    # Получаем все обязательные предметы
    mandatory = [s for s in self.loader.subjects 
                 if s.subject_type == SubjectType.MANDATORY]
    
    print(f"\nВсего обязательных предметов: {len(mandatory)}")
    
    # Сортируем по приоритету
    # 1. Предметы с большим количеством часов
    # 2. Сложные предметы (математика, русский, физика)
    mandatory.sort(key=lambda s: (
        s.hours_per_week,  # Больше часов = выше приоритет
        1 if any(x in s.name.lower() 
                for x in ['математика', 'русский', 'физика']) else 0
    ), reverse=True)
    
    # Размещаем каждый предмет
    for subject in mandatory:
        self.place_subject(subject)
    
    print(f"\n✅ Размещено {len(self.schedule.lessons)} уроков")
```

2. Создать метод `place_subject()`:

```python
def place_subject(self, subject: Subject):
    """Размещение одного предмета"""
    placed = 0
    required = subject.hours_per_week
    
    # Определяем приоритет времени
    is_hard_subject = any(x in subject.name.lower() 
                         for x in ['математика', 'русский', 'физика', 
                                  'английский', 'химия'])
    
    # Получаем список слотов
    available_slots = self.get_available_slots(subject)
    
    # Сортируем слоты по приоритету
    available_slots.sort(key=lambda s: self.evaluate_slot(s, is_hard_subject), 
                        reverse=True)
    
    # Размещаем уроки
    for slot in available_slots:
        if placed >= required:
            break
        
        if self.can_place_lesson(subject, slot):
            classroom = self.find_best_classroom(subject, slot)
            
            lesson = Lesson(
                subject=subject.name,
                teacher=subject.teacher,
                class_or_group=subject.classes[0],  # упрощение
                classroom=classroom,
                time_slot=slot
            )
            
            self.schedule.add_lesson(lesson)
            placed += 1
    
    if placed < required:
        print(f"⚠️ {subject.name}: размещено {placed}/{required} уроков")
```

3. Создать метод `get_available_slots()`:

```python
def get_available_slots(self, subject: Subject) -> List[TimeSlot]:
    """Получить доступные слоты для предмета"""
    available = []
    
    for slot in self.all_time_slots:
        # Пропускаем слоты, зарезервированные для ЕГЭ
        if slot in self.ege_slots:
            continue
        
        # Проверяем доступность учителя
        if not subject.teacher.is_available(slot.day):
            continue
        
        # Проверяем, что учитель не занят
        if self.schedule.is_teacher_busy(subject.teacher, slot):
            continue
        
        # Проверяем, что класс не занят
        for class_name in subject.classes:
            if self.schedule.is_class_busy(class_name, slot):
                continue
        
        available.append(slot)
    
    return available
```

4. Создать метод `evaluate_slot()`:

```python
def evaluate_slot(self, slot: TimeSlot, is_hard: bool) -> float:
    """Оценка качества слота для предмета"""
    score = 100.0
    
    # Для сложных предметов предпочитаем 2-4 урок
    if is_hard:
        if 2 <= slot.lesson_number <= 4:
            score += 30
        else:
            score -= 20
    
    # Избегаем первого и последнего уроков
    if slot.lesson_number == 1:
        score -= 10
    if slot.lesson_number == 7:
        score -= 15
    
    # Предпочитаем равномерное распределение по дням
    # (считаем текущую загруженность дня)
    day_load = len([l for l in self.schedule.lessons 
                    if l.time_slot.day == slot.day])
    score -= day_load * 2  # Штраф за перегруженные дни
    
    return score
```

5. Создать метод `can_place_lesson()`:

```python
def can_place_lesson(self, subject: Subject, slot: TimeSlot) -> bool:
    """Проверка, можно ли разместить урок в слот"""
    
    # Проверяем учителя
    if self.schedule.is_teacher_busy(subject.teacher, slot):
        return False
    
    # Проверяем классы
    for class_name in subject.classes:
        if self.schedule.is_class_busy(class_name, slot):
            return False
    
    return True
```

**Тестирование:**
```bash
python schedule_generator.py
# Проверить: все предметы размещены, нет конфликтов
```

**Критерий успеха:**  
Все обязательные предметы размещены без конфликтов (учитель/класс/кабинет).

---

### Задача 2.2: Улучшение алгоритма

**Приоритет:** 🟡 ВАЖНЫЙ

**Оптимизации:**

1. **Backtracking при неудаче:**
   ```python
   def place_subject_with_backtracking(self, subject: Subject):
       """Размещение с возможностью отката"""
       snapshot = copy.deepcopy(self.schedule)
       
       try:
           self.place_subject(subject)
       except CannotPlaceException:
           # Откатываемся
           self.schedule = snapshot
           # Пробуем другую стратегию
           self.place_subject_alternative(subject)
   ```

2. **Учет предпочтений кабинетов:**
   ```python
   def find_best_classroom(self, subject: Subject, slot: TimeSlot) -> Classroom:
       """Найти лучший кабинет для урока"""
       
       # Предпочитаем домашний кабинет учителя
       home = subject.teacher.home_classroom
       if home and not self.schedule.is_classroom_busy(
               self.loader.classrooms[home], slot):
           return self.loader.classrooms[home]
       
       # Ищем свободный кабинет подходящего размера
       # ...
   ```

3. **Балансировка нагрузки по дням:**
   ```python
   def balance_weekly_load(self):
       """Выровнять нагрузку по дням недели"""
       for teacher in self.loader.teachers.values():
           daily_loads = defaultdict(int)
           
           for lesson in self.schedule.get_lessons_by_teacher(teacher.name):
               daily_loads[lesson.time_slot.day] += 1
           
           # Если разброс большой - пытаемся перераспределить
           if max(daily_loads.values()) - min(daily_loads.values()) > 3:
               self.redistribute_teacher_lessons(teacher)
   ```

---

## Этап 3: Оптимизация расписания (2-3 дня)

### Задача 3.1: Минимизация окон

**Приоритет:** 🔴 КРИТИЧЕСКИЙ

**Алгоритм:**

1. Подсчитать текущие метрики:
   ```python
   def calculate_gaps_metric(self) -> int:
       """Подсчитать общее количество окон"""
       total_gaps = 0
       
       for teacher in self.loader.teachers.values():
           total_gaps += self.schedule.get_teacher_gaps(teacher)
       
       for class_name in self.loader.classes.keys():
           total_gaps += self.schedule.get_class_gaps(class_name)
       
       return total_gaps
   ```

2. Найти пары уроков для обмена:
   ```python
   def find_swap_candidates(self) -> List[Tuple[Lesson, Lesson]]:
       """Найти пары уроков, которые можно обменять"""
       candidates = []
       
       lessons = self.schedule.lessons
       for i, lesson1 in enumerate(lessons):
           for lesson2 in lessons[i+1:]:
               if self.can_swap(lesson1, lesson2):
                   candidates.append((lesson1, lesson2))
       
       return candidates
   ```

3. Проверить возможность обмена:
   ```python
   def can_swap(self, lesson1: Lesson, lesson2: Lesson) -> bool:
       """Можно ли обменять два урока местами"""
       
       # Проверяем учителей
       if self.schedule.is_teacher_busy_excluding(
               lesson1.teacher, lesson2.time_slot, lesson1):
           return False
       
       if self.schedule.is_teacher_busy_excluding(
               lesson2.teacher, lesson1.time_slot, lesson2):
           return False
       
       # Аналогично для классов
       # ...
       
       return True
   ```

4. Применить обмен, если он улучшает метрики:
   ```python
   def optimize_by_swapping(self, max_iterations: int = 1000):
       """Оптимизация путем обмена уроков"""
       current_gaps = self.calculate_gaps_metric()
       
       for iteration in range(max_iterations):
           candidates = self.find_swap_candidates()
           
           if not candidates:
               break
           
           # Пробуем случайный обмен
           lesson1, lesson2 = random.choice(candidates)
           
           # Обмениваем
           lesson1.time_slot, lesson2.time_slot = \
               lesson2.time_slot, lesson1.time_slot
           
           # Проверяем, стало ли лучше
           new_gaps = self.calculate_gaps_metric()
           
           if new_gaps < current_gaps:
               current_gaps = new_gaps
               print(f"Итерация {iteration}: окон {new_gaps}")
           else:
               # Откатываем
               lesson1.time_slot, lesson2.time_slot = \
                   lesson2.time_slot, lesson1.time_slot
       
       print(f"\n✅ Оптимизация завершена. Окон: {current_gaps}")
   ```

---

## Этап 4: Экспорт в Excel (1 день)

### Задача 4.1: Базовый экспорт

**Приоритет:** 🟡 ВАЖНЫЙ

**Реализация:**

Создать файл `export_excel.py`:

```python
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill
from schedule_base import *

class ExcelExporter:
    def __init__(self, schedule: Schedule, classes: List[str], teachers: List[str]):
        self.schedule = schedule
        self.classes = classes
        self.teachers = teachers
    
    def export_by_classes(self, filename: str):
        """Экспорт расписания по классам"""
        wb = Workbook()
        
        for class_name in self.classes:
            ws = wb.create_sheet(title=class_name)
            self._fill_class_sheet(ws, class_name)
        
        # Удаляем дефолтный лист
        wb.remove(wb['Sheet'])
        wb.save(filename)
    
    def _fill_class_sheet(self, ws, class_name: str):
        """Заполнить лист для класса"""
        # Заголовки
        ws['A1'] = 'Урок'
        days = ['ПН', 'ВТ', 'СР', 'ЧТ', 'ПТ']
        for col, day in enumerate(days, start=2):
            ws.cell(1, col, day)
        
        # Уроки
        for lesson_num in range(1, 8):
            ws.cell(lesson_num + 1, 1, lesson_num)
            
            for day_idx, day in enumerate(DayOfWeek):
                slot = TimeSlot(day, lesson_num)
                lessons = [l for l in self.schedule.get_lessons_by_class(class_name)
                          if l.time_slot == slot]
                
                if lessons:
                    lesson = lessons[0]
                    cell_text = f"{lesson.subject}\n{lesson.teacher.name}\nкаб. {lesson.classroom.number if lesson.classroom else '?'}"
                    ws.cell(lesson_num + 1, day_idx + 2, cell_text)
    
    def export_by_teachers(self, filename: str):
        """Экспорт расписания по учителям"""
        # Аналогично export_by_classes
        pass
```

**Использование:**
```python
exporter = ExcelExporter(schedule, list(loader.classes.keys()), 
                        list(loader.teachers.keys()))
exporter.export_by_classes('output/расписание_по_классам.xlsx')
exporter.export_by_teachers('output/расписание_по_учителям.xlsx')
```

---

## Этап 5: Веб-интерфейс (2-3 дня)

### Задача 5.1: Базовый интерфейс

**Приоритет:** 🟢 ЖЕЛАТЕЛЬНЫЙ

**Реализация:**

Создать файл `streamlit_app.py`:

```python
import streamlit as st
from data_loader import DataLoader
from schedule_generator import ScheduleGenerator
from export_excel import ExcelExporter

st.set_page_config(page_title="Генератор расписания", layout="wide")

st.title("📚 Генератор расписания")
st.markdown("Автоматическое составление расписания для 11 классов")

# Боковая панель
with st.sidebar:
    st.header("⚙️ Настройки")
    
    st.subheader("Загрузка данных")
    file_classrooms = st.file_uploader("Кабинеты", type=['xlsx'])
    file_staff = st.file_uploader("Расстановка кадров", type=['xlsx'])
    file_students = st.file_uploader("Ученики и ЕГЭ", type=['xlsx'])
    
    if all([file_classrooms, file_staff, file_students]):
        if st.button("🚀 Сгенерировать расписание", type="primary"):
            with st.spinner("Генерация..."):
                # Запуск генератора
                # ...
                st.success("✅ Расписание готово!")
                st.balloons()

# Основная область
tab1, tab2, tab3, tab4 = st.tabs(["Расписание по классам", 
                                   "Расписание по учителям",
                                   "Статистика",
                                   "Экспорт"])

with tab1:
    st.header("Расписание по классам")
    selected_class = st.selectbox("Выберите класс", ["11В", "11Д", "11Ж"])
    # Показать расписание
    
with tab2:
    st.header("Расписание по учителям")
    # ...
    
with tab3:
    st.header("Статистика")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Всего уроков", 350)
    with col2:
        st.metric("Окон у учителей", 42)
    with col3:
        st.metric("Средняя нагрузка", "28 ч/нед")
    
with tab4:
    st.header("Экспорт")
    if st.button("📥 Скачать Excel"):
        # Экспорт
        pass
```

**Запуск:**
```bash
streamlit run streamlit_app.py
```

---

## Этап 6: Тестирование и отладка (1-2 дня)

### Задачи

1. **Модульное тестирование:**
   - Тесты для базовых классов
   - Тесты для загрузчика данных
   - Тесты для алгоритмов

2. **Интеграционное тестирование:**
   - Полный цикл генерации
   - Проверка валидности результата

3. **Нагрузочное тестирование:**
   - Время работы на реальных данных
   - Использование памяти

---

## Примерный график

| Этап | Задачи | Время | Дедлайн |
|------|--------|-------|---------|
| 1 | Исправление ошибок | 1-2 дня | День 2 |
| 2 | Размещение предметов | 2-3 дня | День 5 |
| 3 | Оптимизация | 2-3 дня | День 8 |
| 4 | Экспорт Excel | 1 день | День 9 |
| 5 | Веб-интерфейс | 2-3 дня | День 12 |
| 6 | Тестирование | 1-2 дня | День 14 |

**Итого:** 9-14 дней работы

---

## Приоритизация

### Must Have (обязательно для v1.0)
- ✅ Загрузка данных
- ✅ Размещение практикумов ЕГЭ (80%)
- ⏳ Исправление назначения учителей
- ⏳ Размещение обязательных предметов
- ⏳ Экспорт в Excel

### Should Have (желательно для v1.0)
- ⏳ Оптимизация расписания
- ⏳ Базовая валидация
- ⏳ Статистика и метрики

### Could Have (можно отложить на v1.1)
- ⏳ Веб-интерфейс
- ⏳ Продвинутая оптимизация
- ⏳ Ручная корректировка
- ⏳ История изменений

---

## Рекомендации по работе в Claude Code

1. **Начните с Этапа 1** - это критически важно
2. **Тестируйте после каждого изменения** - запускайте `schedule_generator.py`
3. **Коммитьте часто** - сохраняйте прогресс
4. **Используйте логирование** - добавьте подробные `print()` для отладки
5. **Не бойтесь экспериментировать** - код уже структурирован, легко менять

## Полезные команды

```bash
# Быстрое тестирование
python schedule_generator.py | tail -50

# Проверка данных
python data_loader.py

# Запуск веб-интерфейса
streamlit run streamlit_app.py

# Форматирование
black *.py

# Проверка типов
mypy schedule_base.py
```

---

**Документ обновлен:** 31.01.2026  
**Версия плана:** 1.0  
**Следующее обновление:** После завершения Этапа 1
