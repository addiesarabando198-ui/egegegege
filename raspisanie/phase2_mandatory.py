"""
Фаза 2: Размещение обязательных предметов
Алгоритм жадного размещения с учетом приоритетов
"""

from typing import List, Optional, Dict, Tuple, Set
from collections import defaultdict
from schedule_base import (
    Schedule, Subject, Teacher, Classroom, Lesson,
    TimeSlot, DayOfWeek, SubjectType
)


class Phase2MandatoryPlacer:
    """
    Класс для размещения обязательных предметов в расписании.

    Алгоритм:
    1. Сортирует предметы по приоритету (сложные, с большим кол-вом часов)
    2. Для каждого предмета ищет лучшие доступные слоты
    3. Размещает уроки с учетом всех ограничений
    4. Ведет учет размещенных и неразмещенных уроков
    """

    def __init__(self, schedule: Schedule, loader, ege_slots: List[TimeSlot]):
        """
        Args:
            schedule: Текущее расписание (после Фазы 1)
            loader: Загрузчик данных (DataLoader или DemoDataLoader)
            ege_slots: Слоты, занятые практикумами ЕГЭ
        """
        self.schedule = schedule
        self.loader = loader
        self.ege_slots = set(ege_slots)

        # Все возможные слоты (исключая занятые ЕГЭ)
        self.all_slots = [
            TimeSlot(day, lesson)
            for day in DayOfWeek
            for lesson in range(1, 8)
        ]

        # Статистика размещения
        self.stats = {
            'total_required': 0,
            'placed': 0,
            'failed': 0,
            'conflicts': []
        }

        # Кэш занятости для ускорения
        self._teacher_schedule: Dict[str, Dict[TimeSlot, Lesson]] = defaultdict(dict)
        self._class_schedule: Dict[str, Dict[TimeSlot, Lesson]] = defaultdict(dict)
        self._classroom_schedule: Dict[str, Dict[TimeSlot, Lesson]] = defaultdict(dict)

        self._build_cache()

    def _build_cache(self):
        """Построить кэш занятости из текущего расписания"""
        for lesson in self.schedule.lessons:
            # Учитель
            self._teacher_schedule[lesson.teacher.name][lesson.time_slot] = lesson

            # Класс
            self._class_schedule[lesson.class_or_group][lesson.time_slot] = lesson

            # Кабинет
            if lesson.classroom:
                self._classroom_schedule[lesson.classroom.number][lesson.time_slot] = lesson

    def _update_cache(self, lesson: Lesson):
        """Обновить кэш после добавления урока"""
        self._teacher_schedule[lesson.teacher.name][lesson.time_slot] = lesson
        self._class_schedule[lesson.class_or_group][lesson.time_slot] = lesson
        if lesson.classroom:
            self._classroom_schedule[lesson.classroom.number][lesson.time_slot] = lesson

    def place_all_mandatory_subjects(self) -> Dict:
        """
        Разместить все обязательные предметы.

        Returns:
            Статистика размещения
        """
        print("\n" + "=" * 100)
        print(" " * 25 + "ФАЗА 2: РАЗМЕЩЕНИЕ ОБЯЗАТЕЛЬНЫХ ПРЕДМЕТОВ")
        print("=" * 100)

        # Получаем обязательные предметы
        mandatory_subjects = [
            s for s in self.loader.subjects
            if s.subject_type == SubjectType.MANDATORY
        ]

        print(f"\n📚 Всего обязательных предметов: {len(mandatory_subjects)}")

        # Подсчитываем общее количество часов
        total_hours = sum(s.hours_per_week for s in mandatory_subjects)
        self.stats['total_required'] = total_hours
        print(f"📊 Всего часов для размещения: {total_hours}")

        # Сортируем по приоритету
        sorted_subjects = self._sort_by_priority(mandatory_subjects)

        # Группируем по классам для лучшего распределения
        subjects_by_class = self._group_by_class(sorted_subjects)

        print(f"\n🔧 Размещение уроков...")
        print("-" * 80)

        # Размещаем для каждого класса
        for class_name, subjects in subjects_by_class.items():
            placed_for_class = 0
            failed_for_class = 0

            for subject in subjects:
                placed = self._place_subject(subject)
                placed_for_class += placed
                failed_for_class += (subject.hours_per_week - placed)

            print(f"  {class_name}: размещено {placed_for_class} уроков"
                  f"{f', не размещено {failed_for_class}' if failed_for_class > 0 else ''}")

        print("-" * 80)
        self._print_statistics()

        return self.stats

    def _sort_by_priority(self, subjects: List[Subject]) -> List[Subject]:
        """
        Сортировка предметов по приоритету размещения.

        Приоритет:
        1. Сложные предметы (математика, русский, физика) - размещаются первыми
        2. Предметы с большим количеством часов
        3. Предметы с ограниченной доступностью учителя
        """
        def priority_score(subject: Subject) -> Tuple:
            # Сложность предмета
            is_hard = 1 if self._is_hard_subject(subject) else 0

            # Количество часов
            hours = subject.hours_per_week

            # Ограниченность учителя (больше недоступных дней = выше приоритет)
            teacher_restriction = len(subject.teacher.unavailable_days)

            return (-is_hard, -hours, -teacher_restriction, subject.name)

        return sorted(subjects, key=priority_score)

    def _group_by_class(self, subjects: List[Subject]) -> Dict[str, List[Subject]]:
        """Группировка предметов по классам"""
        by_class = defaultdict(list)

        for subject in subjects:
            for class_name in subject.classes:
                by_class[class_name].append(subject)

        return dict(by_class)

    def _place_subject(self, subject: Subject) -> int:
        """
        Разместить один предмет в расписании.

        Args:
            subject: Предмет для размещения

        Returns:
            Количество успешно размещенных уроков
        """
        placed = 0
        is_hard = self._is_hard_subject(subject)
        class_name = subject.classes[0] if subject.classes else "unknown"

        # Находим все доступные слоты с оценками
        scored_slots = self._evaluate_all_slots(subject, is_hard)

        # Для каждого часа находим лучший слот
        days_used: Set[DayOfWeek] = set()

        for _ in range(subject.hours_per_week):
            best_slot = self._find_best_slot(scored_slots, subject, days_used)

            if not best_slot:
                self.stats['failed'] += 1
                self.stats['conflicts'].append({
                    'subject': subject.name,
                    'class': class_name,
                    'teacher': subject.teacher.name,
                    'reason': 'no_available_slot'
                })
                continue

            # Находим кабинет
            classroom = self._find_classroom(subject, best_slot)

            # Создаем урок
            lesson = Lesson(
                subject=subject.name,
                teacher=subject.teacher,
                class_or_group=class_name,
                classroom=classroom,
                time_slot=best_slot,
                is_ege_practice=False
            )

            # Добавляем в расписание
            self.schedule.add_lesson(lesson)
            self._update_cache(lesson)

            # Обновляем статистику
            placed += 1
            self.stats['placed'] += 1
            days_used.add(best_slot.day)

            # Удаляем использованный слот из оценок
            scored_slots = [(score, slot) for score, slot in scored_slots if slot != best_slot]

        return placed

    def _evaluate_all_slots(self, subject: Subject, is_hard: bool) -> List[Tuple[float, TimeSlot]]:
        """
        Оценить все доступные слоты для предмета.

        Returns:
            Список (оценка, слот), отсортированный по убыванию оценки
        """
        scored = []

        for slot in self.all_slots:
            score = self._evaluate_slot(slot, subject, is_hard)
            if score > 0:
                scored.append((score, slot))

        # Сортируем по убыванию оценки
        scored.sort(reverse=True, key=lambda x: x[0])

        return scored

    def _evaluate_slot(self, slot: TimeSlot, subject: Subject, is_hard: bool) -> float:
        """
        Оценить качество слота для размещения урока.

        Returns:
            Оценка > 0 если слот доступен, 0 если недоступен
        """
        # Проверка жестких ограничений
        if not self._is_slot_available(slot, subject):
            return 0.0

        score = 100.0

        # 1. Оптимальное время для сложных предметов (2-4 урок)
        if is_hard:
            if 2 <= slot.lesson_number <= 4:
                score += 30  # Бонус за оптимальное время
            elif slot.lesson_number == 1:
                score -= 15  # Небольшой штраф за первый урок
            elif slot.lesson_number >= 6:
                score -= 25  # Штраф за поздние уроки
        else:
            # Легкие предметы лучше после обеда
            if slot.lesson_number >= 5:
                score += 10
            elif slot.lesson_number == 1:
                score -= 5

        # 2. Первый и последний уроки менее желательны
        if slot.lesson_number == 1:
            score -= 10
        if slot.lesson_number == 7:
            score -= 20

        # 3. Учитываем текущую загруженность дня для класса
        class_name = subject.classes[0] if subject.classes else None
        if class_name:
            day_load = sum(1 for ts, _ in self._class_schedule[class_name].items()
                          if ts.day == slot.day)
            score -= day_load * 3  # Штраф за перегруженные дни

        # 4. Учитываем окна у учителя
        teacher_name = subject.teacher.name
        teacher_slots = [ts for ts in self._teacher_schedule[teacher_name].keys()
                        if ts.day == slot.day]

        if teacher_slots:
            # Проверяем, создаст ли этот слот окно
            all_lessons = sorted([ts.lesson_number for ts in teacher_slots] + [slot.lesson_number])
            gaps = 0
            for i in range(len(all_lessons) - 1):
                gaps += all_lessons[i + 1] - all_lessons[i] - 1
            score -= gaps * 5  # Штраф за создание окон

        # 5. Предпочитаем равномерное распределение по дням недели
        teacher_days = set(ts.day for ts in self._teacher_schedule[teacher_name].keys())
        if slot.day not in teacher_days:
            score += 5  # Бонус за новый день

        # 6. Слот уже занят практикумом ЕГЭ
        if slot in self.ege_slots:
            return 0.0

        return score

    def _is_slot_available(self, slot: TimeSlot, subject: Subject) -> bool:
        """Проверить доступность слота для предмета"""
        # 1. Проверяем доступность учителя в этот день
        if not subject.teacher.is_available(slot.day):
            return False

        # 2. Проверяем, не занят ли учитель
        if slot in self._teacher_schedule[subject.teacher.name]:
            return False

        # 3. Проверяем, не занят ли класс
        for class_name in subject.classes:
            if slot in self._class_schedule[class_name]:
                return False

        # 4. Слот занят практикумом ЕГЭ
        if slot in self.ege_slots:
            return False

        return True

    def _find_best_slot(
        self,
        scored_slots: List[Tuple[float, TimeSlot]],
        subject: Subject,
        days_used: Set[DayOfWeek]
    ) -> Optional[TimeSlot]:
        """
        Найти лучший слот с учетом уже использованных дней.

        Предпочитаем распределять уроки по разным дням.
        """
        # Сначала ищем слот в неиспользованный день
        for score, slot in scored_slots:
            if slot.day not in days_used and self._is_slot_available(slot, subject):
                return slot

        # Если не нашли, берем любой доступный
        for score, slot in scored_slots:
            if self._is_slot_available(slot, subject):
                return slot

        return None

    def _find_classroom(self, subject: Subject, slot: TimeSlot) -> Optional[Classroom]:
        """Найти подходящий свободный кабинет"""
        # 1. Предпочитаем домашний кабинет учителя
        if subject.teacher.home_classroom:
            home_room = self.loader.classrooms.get(subject.teacher.home_classroom)
            if home_room and slot not in self._classroom_schedule.get(home_room.number, {}):
                return home_room

        # 2. Ищем любой свободный кабинет
        for classroom in self.loader.classrooms.values():
            if slot not in self._classroom_schedule.get(classroom.number, {}):
                return classroom

        return None

    def _is_hard_subject(self, subject: Subject) -> bool:
        """Проверить, является ли предмет сложным"""
        hard_keywords = [
            'математика', 'алгебра', 'геометрия',
            'русский', 'физика', 'химия',
            'английский', 'немецкий', 'французский'
        ]
        name_lower = subject.name.lower()
        return any(keyword in name_lower for keyword in hard_keywords)

    def _print_statistics(self):
        """Вывести статистику размещения"""
        print(f"\n📊 СТАТИСТИКА ФАЗЫ 2:")
        print(f"   Всего требовалось: {self.stats['total_required']} уроков")
        print(f"   ✅ Размещено: {self.stats['placed']} уроков")
        print(f"   ❌ Не размещено: {self.stats['failed']} уроков")

        if self.stats['placed'] > 0:
            success_rate = self.stats['placed'] / self.stats['total_required'] * 100
            print(f"   📈 Успешность: {success_rate:.1f}%")

        if self.stats['conflicts']:
            print(f"\n⚠️  Конфликты ({len(self.stats['conflicts'])}):")
            # Показываем первые 5 конфликтов
            for conflict in self.stats['conflicts'][:5]:
                print(f"      - {conflict['subject']} ({conflict['class']}): {conflict['reason']}")
            if len(self.stats['conflicts']) > 5:
                print(f"      ... и еще {len(self.stats['conflicts']) - 5}")

        # Статистика по учителям с окнами
        print(f"\n👨‍🏫 Окна у учителей после Фазы 2:")
        teacher_gaps = []
        for teacher in self.loader.teachers.values():
            gaps = self.schedule.get_teacher_gaps(teacher)
            if gaps > 0:
                teacher_gaps.append((teacher.name, gaps))

        teacher_gaps.sort(key=lambda x: x[1], reverse=True)
        for name, gaps in teacher_gaps[:5]:
            print(f"      {name}: {gaps} окон")

        print("=" * 100)


# Тестирование
if __name__ == '__main__':
    import sys
    sys.path.insert(0, '/home/user/ege-superbot/raspisanie')

    from demo_data import DemoDataLoader
    from schedule_generator import ScheduleGenerator

    print("=" * 100)
    print(" " * 30 + "ТЕСТ ФАЗЫ 2")
    print("=" * 100)

    # Загружаем демо-данные
    loader = DemoDataLoader()
    loader.load_all()

    # Фаза 1: Практикумы ЕГЭ
    generator = ScheduleGenerator(loader)
    generator.place_ege_practices()

    print(f"\nПосле Фазы 1: {len(generator.schedule.lessons)} уроков")

    # Фаза 2: Обязательные предметы
    phase2 = Phase2MandatoryPlacer(
        schedule=generator.schedule,
        loader=loader,
        ege_slots=generator.ege_slots
    )
    stats = phase2.place_all_mandatory_subjects()

    print(f"\nПосле Фазы 2: {len(generator.schedule.lessons)} уроков")

    # Сохраняем результат
    generator.schedule.save_to_json('output/schedule_phase2.json')
    print(f"\n💾 Расписание сохранено в output/schedule_phase2.json")
