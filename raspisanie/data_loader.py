"""
Загрузчик данных из Excel файлов
Объединяет все данные в единую структуру
"""

import pandas as pd
import json
from collections import defaultdict
from schedule_base import *


class DataLoader:
    """Класс для загрузки данных из Excel файлов"""
    
    def __init__(self):
        self.teachers: Dict[str, Teacher] = {}
        self.classrooms: Dict[str, Classroom] = {}
        self.classes: Dict[str, Class] = {}
        self.students: Dict[str, Student] = {}
        self.subjects: List[Subject] = []
        self.ege_groups: List[EGEPracticeGroup] = []
        
    def load_classrooms(self, filename: str):
        """Загрузка кабинетов"""
        print("Загрузка кабинетов...")
        df = pd.read_excel(filename, sheet_name='БК', header=0)
        
        for idx, row in df.iterrows():
            number = str(row['Номер кабинета'])
            capacity = int(row['Вместимость']) if pd.notna(row['Вместимость']) else 30
            floor = int(row['Этаж']) if pd.notna(row['Этаж']) else 1
            responsible = str(row['Ответственный']) if pd.notna(row['Ответственный']) else None
            
            classroom = Classroom(
                number=number,
                capacity=capacity,
                floor=floor,
                responsible_teacher=responsible
            )
            self.classrooms[number] = classroom
        
        print(f"✓ Загружено {len(self.classrooms)} кабинетов")
    
    def load_teachers_and_subjects(self, filename: str):
        """Загрузка учителей и предметов из расстановки кадров"""
        print("Загрузка учителей и расстановки кадров...")
        df = pd.read_excel(filename, sheet_name='БК (февраль)', header=0)
        
        current_teacher = None
        teacher_subjects = defaultdict(list)
        
        # Находим столбцы с классами
        class_columns = [col for col in df.columns if col.startswith('1')]  # 10-Д, 11-В и т.д.
        
        for idx, row in df.iterrows():
            # Ищем ФИО учителя
            teacher_name = row['ФИО учителя']
            
            if pd.notna(teacher_name) and isinstance(teacher_name, str):
                # Проверяем, что это реально ФИО
                if len(teacher_name.split()) >= 2:
                    current_teacher = teacher_name.strip()
                    if current_teacher not in self.teachers:
                        # Проверяем, есть ли кабинет учителя
                        home_classroom = None
                        for classroom_num, classroom in self.classrooms.items():
                            if classroom.responsible_teacher == current_teacher:
                                home_classroom = classroom_num
                                break
                        
                        self.teachers[current_teacher] = Teacher(
                            name=current_teacher,
                            home_classroom=home_classroom
                        )
            
            # Если есть текущий учитель, собираем его предметы
            if current_teacher:
                subject_name = row['Класс']
                
                if pd.notna(subject_name) and isinstance(subject_name, str):
                    subject_name = subject_name.strip()
                    
                    # Проверяем, что это не служебные строки
                    if subject_name and subject_name not in ['Направление/ профиль', 'Количество учащихся класса', 
                                                               'Классный руководитель', 'Разрешено деление на группы']:
                        # Проверяем, есть ли часы в классах
                        has_hours = False
                        classes_with_hours = []
                        
                        for class_col in class_columns:
                            hours = row[class_col]
                            if pd.notna(hours) and str(hours).isdigit():
                                has_hours = True
                                classes_with_hours.append((class_col, int(hours)))
                        
                        if has_hours:
                            # Добавляем предмет учителю
                            if subject_name not in self.teachers[current_teacher].subjects:
                                self.teachers[current_teacher].subjects.append(subject_name)
                            
                            # Определяем тип предмета
                            subject_type = SubjectType.MANDATORY
                            if 'Практикум ЕГЭ' in subject_name:
                                subject_type = SubjectType.EGE_PRACTICE
                            
                            # Сохраняем информацию о предмете
                            for class_name, hours in classes_with_hours:
                                teacher_subjects[current_teacher].append({
                                    'name': subject_name,
                                    'type': subject_type,
                                    'class': class_name,
                                    'hours': hours
                                })
        
        # Определяем учителей, не работающих по понедельникам
        # (по данным из текущего расписания мы знаем, что 12 учителей не работают по ПН)
        teachers_not_on_monday = [
            'Егорова Н.В.', 'Закревская Е.А.', 'Затопляева О.В.', 'Каретникова А.В.',
            'Новорадовская П.А.', 'Северин А.А.', 'Терехов М.Р.', 'Цуканова М.Л.',
            'Чёрная Е.А.', 'Шах М.В.', 'Шехурдина А.А.', 'Кудряшова А.М.'
        ]
        
        for teacher_name in teachers_not_on_monday:
            if teacher_name in self.teachers:
                self.teachers[teacher_name].unavailable_days.add(DayOfWeek.MONDAY)
        
        # Создаем объекты Subject
        for teacher_name, subjects_list in teacher_subjects.items():
            teacher = self.teachers[teacher_name]
            
            for subj_info in subjects_list:
                subject = Subject(
                    name=subj_info['name'],
                    subject_type=subj_info['type'],
                    hours_per_week=subj_info['hours'],
                    teacher=teacher,
                    classes=[subj_info['class']]
                )
                self.subjects.append(subject)
        
        print(f"✓ Загружено {len(self.teachers)} учителей")
        print(f"✓ Загружено {len(self.subjects)} предметов")
    
    def load_students_and_ege_choices(self, filename: str):
        """Загрузка учеников и их выбора ЕГЭ"""
        print("Загрузка учеников и выбора ЕГЭ...")
        df = pd.read_excel(filename, sheet_name='Результат', header=0)
        
        # Маппинг аббревиатур на полные названия предметов ЕГЭ
        subject_mapping = {
            'РУ': 'Русский язык',
            'МА': 'Математика базовая',
            'МА проф': 'Математика профильная',
            'АЯ': 'Английский язык',
            'ОБ': 'Обществознание',
            'ИС': 'История',
            'ЛИ': 'Литература',
            'ИНФ': 'Информатика',
            'БИ': 'Биология',
            'ФИ': 'Физика',
            'ХИ': 'Химия',
            'ГГ': 'География',
            'ФЯ': 'Французский язык',
            'НЯ': 'Немецкий язык',
            'ИЯ': 'Испанский язык'
        }
        
        # Находим столбцы для каждого предмета
        subject_columns = defaultdict(list)
        for col in df.columns:
            for abbr in subject_mapping.keys():
                if col.startswith(abbr):
                    subject_columns[abbr].append(col)
        
        # Обрабатываем каждого ученика
        for idx, row in df.iterrows():
            student_name = row['ФИО']
            class_name = row['класс']
            
            if pd.notna(student_name) and pd.notna(class_name):
                ege_subjects = []
                
                # Проверяем выбор каждого предмета
                for abbr, full_name in subject_mapping.items():
                    has_subject = False
                    
                    for col in subject_columns[abbr]:
                        val = row[col]
                        if pd.notna(val) and str(val).lower() not in ['отказ', 'н', 'nan', '']:
                            has_subject = True
                            break
                    
                    if has_subject:
                        ege_subjects.append(full_name)
                
                student = Student(
                    name=student_name,
                    class_name=class_name,
                    ege_subjects=ege_subjects
                )
                
                self.students[student_name] = student
                
                # Добавляем ученика в класс
                if class_name not in self.classes:
                    self.classes[class_name] = Class(
                        name=class_name,
                        profile="РЛ ВШЭ"  # Упрощение, можно загружать из другого файла
                    )
                
                self.classes[class_name].students.append(student)
        
        print(f"✓ Загружено {len(self.students)} учеников")
        print(f"✓ Загружено {len(self.classes)} классов")
    
    def create_ege_practice_groups(self):
        """Создание групп для практикумов ЕГЭ"""
        print("Формирование групп для практикумов ЕГЭ...")
        
        # Группируем учеников по предметам ЕГЭ
        subject_students = defaultdict(list)
        
        for student in self.students.values():
            for ege_subject in student.ege_subjects:
                subject_students[ege_subject].append(student)
        
        # Находим учителей для каждого практикума
        # Используем данные из расстановки кадров
        ege_teachers = {}
        for subject in self.subjects:
            if subject.subject_type == SubjectType.EGE_PRACTICE:
                # Извлекаем предмет из названия "Практикум ЕГЭ по X"
                if 'по ' in subject.name:
                    ege_subject_name = subject.name.split('по ')[1].strip()
                    ege_teachers[ege_subject_name] = subject.teacher
        
        # Создаем группы
        for ege_subject, students_list in subject_students.items():
            if len(students_list) == 0:
                continue
            
            # Находим учителя
            teacher = ege_teachers.get(ege_subject)
            if not teacher:
                # Если не нашли, берем первого подходящего
                # (это временное решение, в реальности нужно указать всех учителей)
                teacher = list(self.teachers.values())[0]
            
            # Определяем количество часов (обычно 3-4)
            hours = 3
            if ege_subject in ['Математика профильная', 'Английский язык', 'История', 
                               'Обществознание', 'Физика', 'Информатика', 'Биология', 'Химия']:
                hours = 4
            
            group = EGEPracticeGroup(
                subject=ege_subject,
                teacher=teacher,
                students=students_list,
                hours_per_week=hours
            )
            
            self.ege_groups.append(group)
        
        print(f"✓ Создано {len(self.ege_groups)} групп для практикумов ЕГЭ")
    
    def print_summary(self):
        """Вывод сводной информации"""
        print("\n" + "="*100)
        print(" " * 35 + "СВОДКА ПО ДАННЫМ")
        print("="*100)
        
        print(f"\n📚 Учителей: {len(self.teachers)}")
        print(f"🏫 Кабинетов: {len(self.classrooms)}")
        print(f"👥 Классов: {len(self.classes)}")
        print(f"🎓 Учеников: {len(self.students)}")
        print(f"📖 Предметов (всего связок): {len(self.subjects)}")
        print(f"🎯 Групп для практикумов ЕГЭ: {len(self.ege_groups)}")
        
        print("\n📊 ТОП-5 популярных предметов ЕГЭ:")
        ege_counts = defaultdict(int)
        for student in self.students.values():
            for ege_subj in student.ege_subjects:
                ege_counts[ege_subj] += 1
        
        for i, (subj, count) in enumerate(sorted(ege_counts.items(), key=lambda x: x[1], reverse=True)[:5], 1):
            print(f"  {i}. {subj}: {count} учеников")
        
        print("\n✅ Все данные загружены успешно!")
        print("="*100)


# Пример использования
if __name__ == "__main__":
    loader = DataLoader()
    
    # Загружаем данные
    loader.load_classrooms('/mnt/user-data/uploads/Здания__кабинеты__места__школьные_здания_.xlsx')
    loader.load_teachers_and_subjects('/mnt/user-data/uploads/Расстановка_кадров_ФЕВРАЛЬ_2025-2026_учебный_год__2_.xlsx')
    loader.load_students_and_ege_choices('/mnt/user-data/uploads/Список_участников_ГИА-11_ГБОУ_Школа__Покровский_квартал___41_.xlsx')
    loader.create_ege_practice_groups()
    
    # Выводим сводку
    loader.print_summary()
    
    # Сохраняем данные
    with open('/home/claude/loaded_data.json', 'w', encoding='utf-8') as f:
        json.dump({
            'teachers_count': len(loader.teachers),
            'classrooms_count': len(loader.classrooms),
            'students_count': len(loader.students),
            'ege_groups_count': len(loader.ege_groups)
        }, f, ensure_ascii=False, indent=2)
    
    print("\n💾 Данные сохранены в loaded_data.json")
