"""
Фаза 3: Оптимизация расписания
Алгоритм Simulated Annealing для минимизации окон и улучшения качества
"""

from typing import List, Tuple, Optional, Dict, Set
from collections import defaultdict
from schedule_base import (
    Schedule, Lesson, Teacher, Classroom, TimeSlot, DayOfWeek
)
import random
import math
import copy


class Phase3Optimizer:
    """
    Класс для оптимизации расписания методом Simulated Annealing.

    Цели оптимизации (по приоритету):
    1. Минимизация окон у учителей (вес: 4)
    2. Минимизация окон у классов (вес: 4)
    3. Размещение сложных предметов на 2-4 уроках (вес: 4)
    4. Равномерная нагрузка по дням недели (вес: 3)
    5. Компактное расписание (вес: 2)
    """

    def __init__(self, schedule: Schedule, loader):
        """
        Args:
            schedule: Расписание после Фазы 1 и 2
            loader: Загрузчик данных
        """
        self.schedule = schedule
        self.loader = loader
        self.best_schedule: Optional[Schedule] = None
        self.best_metric = float('inf')

        # Параметры Simulated Annealing
        self.initial_temperature = 100.0
        self.cooling_rate = 0.995
        self.min_temperature = 0.1

        # Статистика
        self.stats = {
            'initial_metric': 0.0,
            'final_metric': 0.0,
            'improvements': 0,
            'iterations': 0,
            'accepted_worse': 0
        }

        # Кэши для быстрого доступа
        self._build_indices()

    def _build_indices(self):
        """Построить индексы для быстрого поиска"""
        self.lessons_by_teacher: Dict[str, List[Lesson]] = defaultdict(list)
        self.lessons_by_class: Dict[str, List[Lesson]] = defaultdict(list)
        self.lessons_by_slot: Dict[TimeSlot, List[Lesson]] = defaultdict(list)

        for lesson in self.schedule.lessons:
            self.lessons_by_teacher[lesson.teacher.name].append(lesson)
            self.lessons_by_class[lesson.class_or_group].append(lesson)
            self.lessons_by_slot[lesson.time_slot].append(lesson)

    def optimize(self, max_iterations: int = 2000, verbose: bool = True) -> Schedule:
        """
        Оптимизировать расписание методом Simulated Annealing.

        Args:
            max_iterations: Максимальное число итераций
            verbose: Выводить прогресс

        Returns:
            Оптимизированное расписание
        """
        if verbose:
            print("\n" + "=" * 100)
            print(" " * 30 + "ФАЗА 3: ОПТИМИЗАЦИЯ РАСПИСАНИЯ")
            print("=" * 100)

        # Начальная метрика
        current_metric = self._calculate_quality_metric()
        self.stats['initial_metric'] = current_metric
        self.best_metric = current_metric
        self.best_schedule = self._copy_schedule()

        if verbose:
            print(f"\n📊 Начальная метрика качества: {current_metric:.2f}")
            self._print_metric_breakdown()

        temperature = self.initial_temperature
        no_improvement_count = 0
        max_no_improvement = 200  # Ранняя остановка

        for iteration in range(max_iterations):
            self.stats['iterations'] = iteration + 1

            # Находим пару уроков для обмена
            swap_result = self._find_and_try_swap()

            if swap_result is None:
                continue

            lesson1, lesson2, new_metric = swap_result

            delta = new_metric - current_metric

            # Решение: принять или откатить
            if delta < 0:
                # Улучшение - принимаем
                current_metric = new_metric
                self.stats['improvements'] += 1
                no_improvement_count = 0

                if new_metric < self.best_metric:
                    self.best_metric = new_metric
                    self.best_schedule = self._copy_schedule()

                    if verbose and iteration % 100 == 0:
                        print(f"  Итерация {iteration}: новый лучший результат = {self.best_metric:.2f}")

            elif random.random() < self._acceptance_probability(delta, temperature):
                # Принимаем ухудшение с некоторой вероятностью
                current_metric = new_metric
                self.stats['accepted_worse'] += 1
                no_improvement_count += 1
            else:
                # Откатываем обмен
                self._swap_lessons(lesson1, lesson2)
                no_improvement_count += 1

            # Охлаждение
            temperature = max(self.min_temperature, temperature * self.cooling_rate)

            # Ранняя остановка
            if no_improvement_count >= max_no_improvement:
                if verbose:
                    print(f"\n  ⏹️  Ранняя остановка на итерации {iteration} (нет улучшений)")
                break

        # Восстанавливаем лучший результат
        self.schedule = self.best_schedule
        self._build_indices()
        self.stats['final_metric'] = self.best_metric

        if verbose:
            self._print_final_statistics()

        return self.schedule

    def _calculate_quality_metric(self) -> float:
        """
        Вычислить метрику качества расписания.

        Меньше = лучше.
        """
        metric = 0.0

        # 1. Окна у учителей (вес: 4)
        teacher_gaps = self._count_teacher_gaps()
        metric += teacher_gaps * 4

        # 2. Окна у классов (вес: 4)
        class_gaps = self._count_class_gaps()
        metric += class_gaps * 4

        # 3. Сложные предметы вне оптимального времени (вес: 4)
        suboptimal = self._count_suboptimal_timing()
        metric += suboptimal * 4

        # 4. Неравномерность нагрузки по дням (вес: 3)
        variance = self._calculate_daily_variance()
        metric += variance * 3

        # 5. Некомпактность расписания (вес: 2)
        spread = self._calculate_schedule_spread()
        metric += spread * 2

        return metric

    def _count_teacher_gaps(self) -> int:
        """Подсчитать общее количество окон у всех учителей"""
        total_gaps = 0

        for teacher_name, lessons in self.lessons_by_teacher.items():
            for day in DayOfWeek:
                day_lessons = [l for l in lessons if l.time_slot.day == day]
                if len(day_lessons) < 2:
                    continue

                lesson_numbers = sorted(l.time_slot.lesson_number for l in day_lessons)
                for i in range(len(lesson_numbers) - 1):
                    gap = lesson_numbers[i + 1] - lesson_numbers[i] - 1
                    total_gaps += gap

        return total_gaps

    def _count_class_gaps(self) -> int:
        """Подсчитать общее количество окон у всех классов"""
        total_gaps = 0

        for class_name, lessons in self.lessons_by_class.items():
            # Пропускаем группы ЕГЭ
            if class_name.startswith('ЕГЭ-'):
                continue

            for day in DayOfWeek:
                day_lessons = [l for l in lessons if l.time_slot.day == day]
                if len(day_lessons) < 2:
                    continue

                lesson_numbers = sorted(l.time_slot.lesson_number for l in day_lessons)
                for i in range(len(lesson_numbers) - 1):
                    gap = lesson_numbers[i + 1] - lesson_numbers[i] - 1
                    total_gaps += gap

        return total_gaps

    def _count_suboptimal_timing(self) -> int:
        """Подсчитать уроки сложных предметов вне оптимального времени (2-4 урок)"""
        hard_keywords = ['математика', 'алгебра', 'геометрия', 'русский',
                        'физика', 'химия', 'английский']
        count = 0

        for lesson in self.schedule.lessons:
            if lesson.is_ege_practice:
                continue

            is_hard = any(kw in lesson.subject.lower() for kw in hard_keywords)
            if is_hard and lesson.time_slot.lesson_number not in [2, 3, 4]:
                count += 1

        return count

    def _calculate_daily_variance(self) -> float:
        """Вычислить дисперсию нагрузки по дням недели"""
        daily_counts = []

        for day in DayOfWeek:
            count = sum(1 for l in self.schedule.lessons if l.time_slot.day == day)
            daily_counts.append(count)

        if not daily_counts:
            return 0.0

        mean = sum(daily_counts) / len(daily_counts)
        variance = sum((c - mean) ** 2 for c in daily_counts) / len(daily_counts)

        return math.sqrt(variance)

    def _calculate_schedule_spread(self) -> float:
        """Вычислить разброс расписания (насколько оно растянуто)"""
        spread = 0

        for class_name, lessons in self.lessons_by_class.items():
            if class_name.startswith('ЕГЭ-'):
                continue

            for day in DayOfWeek:
                day_lessons = [l for l in lessons if l.time_slot.day == day]
                if len(day_lessons) < 2:
                    continue

                lesson_numbers = [l.time_slot.lesson_number for l in day_lessons]
                day_spread = max(lesson_numbers) - min(lesson_numbers) + 1 - len(lesson_numbers)
                spread += day_spread

        return spread

    def _find_and_try_swap(self) -> Optional[Tuple[Lesson, Lesson, float]]:
        """
        Найти пару уроков для обмена и выполнить его.

        Returns:
            (lesson1, lesson2, new_metric) или None если обмен невозможен
        """
        # Выбираем случайный урок
        if len(self.schedule.lessons) < 2:
            return None

        # Стратегия: фокусируемся на уроках, создающих проблемы
        problem_lessons = self._find_problem_lessons()

        if problem_lessons and random.random() < 0.7:
            lesson1 = random.choice(problem_lessons)
        else:
            lesson1 = random.choice(self.schedule.lessons)

        # Ищем подходящего кандидата для обмена
        candidates = self._find_swap_candidates(lesson1)

        if not candidates:
            return None

        lesson2 = random.choice(candidates)

        # Выполняем обмен
        self._swap_lessons(lesson1, lesson2)

        # Пересчитываем метрику
        new_metric = self._calculate_quality_metric()

        return lesson1, lesson2, new_metric

    def _find_problem_lessons(self) -> List[Lesson]:
        """Найти уроки, которые создают проблемы (окна, плохое время)"""
        problem_lessons = []

        hard_keywords = ['математика', 'алгебра', 'геометрия', 'русский',
                        'физика', 'химия', 'английский']

        for lesson in self.schedule.lessons:
            if lesson.is_ege_practice:
                continue

            # Сложный предмет в плохое время
            is_hard = any(kw in lesson.subject.lower() for kw in hard_keywords)
            if is_hard and lesson.time_slot.lesson_number not in [2, 3, 4]:
                problem_lessons.append(lesson)
                continue

            # Урок создает окно
            teacher_lessons = self.lessons_by_teacher[lesson.teacher.name]
            day_lessons = [l for l in teacher_lessons if l.time_slot.day == lesson.time_slot.day]

            if len(day_lessons) >= 2:
                lesson_numbers = sorted(l.time_slot.lesson_number for l in day_lessons)
                idx = lesson_numbers.index(lesson.time_slot.lesson_number)

                # Проверяем, создает ли этот урок окно
                if idx > 0 and lesson_numbers[idx] - lesson_numbers[idx - 1] > 1:
                    problem_lessons.append(lesson)
                elif idx < len(lesson_numbers) - 1 and lesson_numbers[idx + 1] - lesson_numbers[idx] > 1:
                    problem_lessons.append(lesson)

        return problem_lessons

    def _find_swap_candidates(self, lesson: Lesson) -> List[Lesson]:
        """Найти уроки, с которыми можно обменять данный урок"""
        candidates = []

        for other in self.schedule.lessons:
            if other == lesson:
                continue

            # Не меняем практикумы ЕГЭ между собой
            if lesson.is_ege_practice and other.is_ege_practice:
                continue

            # Проверяем, можно ли поменять
            if self._can_swap(lesson, other):
                candidates.append(other)

        return candidates

    def _can_swap(self, lesson1: Lesson, lesson2: Lesson) -> bool:
        """Проверить, можно ли обменять два урока слотами"""
        slot1 = lesson1.time_slot
        slot2 = lesson2.time_slot

        # Те же слоты - не имеет смысла
        if slot1 == slot2:
            return False

        # Проверяем учителя lesson1 в slot2
        if not lesson1.teacher.is_available(slot2.day):
            return False

        for other in self.lessons_by_slot.get(slot2, []):
            if other != lesson2 and other.teacher.name == lesson1.teacher.name:
                return False

        # Проверяем учителя lesson2 в slot1
        if not lesson2.teacher.is_available(slot1.day):
            return False

        for other in self.lessons_by_slot.get(slot1, []):
            if other != lesson1 and other.teacher.name == lesson2.teacher.name:
                return False

        # Проверяем классы
        for other in self.lessons_by_slot.get(slot2, []):
            if other != lesson2 and other.class_or_group == lesson1.class_or_group:
                return False

        for other in self.lessons_by_slot.get(slot1, []):
            if other != lesson1 and other.class_or_group == lesson2.class_or_group:
                return False

        # Проверяем кабинеты
        if lesson1.classroom and lesson2.classroom:
            for other in self.lessons_by_slot.get(slot2, []):
                if other != lesson2 and other.classroom == lesson1.classroom:
                    return False

            for other in self.lessons_by_slot.get(slot1, []):
                if other != lesson1 and other.classroom == lesson2.classroom:
                    return False

        return True

    def _swap_lessons(self, lesson1: Lesson, lesson2: Lesson):
        """Обменять слоты двух уроков"""
        # Обновляем индексы
        slot1 = lesson1.time_slot
        slot2 = lesson2.time_slot

        # Удаляем из старых слотов
        if lesson1 in self.lessons_by_slot[slot1]:
            self.lessons_by_slot[slot1].remove(lesson1)
        if lesson2 in self.lessons_by_slot[slot2]:
            self.lessons_by_slot[slot2].remove(lesson2)

        # Меняем слоты
        lesson1.time_slot = slot2
        lesson2.time_slot = slot1

        # Добавляем в новые слоты
        self.lessons_by_slot[slot2].append(lesson1)
        self.lessons_by_slot[slot1].append(lesson2)

    def _acceptance_probability(self, delta: float, temperature: float) -> float:
        """Вероятность принятия ухудшающего изменения (Simulated Annealing)"""
        if temperature <= 0:
            return 0.0
        return math.exp(-delta / temperature)

    def _copy_schedule(self) -> Schedule:
        """Создать глубокую копию расписания"""
        new_schedule = Schedule()

        for lesson in self.schedule.lessons:
            new_lesson = Lesson(
                subject=lesson.subject,
                teacher=lesson.teacher,
                class_or_group=lesson.class_or_group,
                classroom=lesson.classroom,
                time_slot=TimeSlot(lesson.time_slot.day, lesson.time_slot.lesson_number),
                is_ege_practice=lesson.is_ege_practice,
                students=lesson.students
            )
            new_schedule.add_lesson(new_lesson)

        return new_schedule

    def _print_metric_breakdown(self):
        """Вывести детализацию метрики"""
        teacher_gaps = self._count_teacher_gaps()
        class_gaps = self._count_class_gaps()
        suboptimal = self._count_suboptimal_timing()
        variance = self._calculate_daily_variance()
        spread = self._calculate_schedule_spread()

        print(f"\n   Детализация:")
        print(f"   - Окна у учителей: {teacher_gaps} (вес x4 = {teacher_gaps * 4})")
        print(f"   - Окна у классов: {class_gaps} (вес x4 = {class_gaps * 4})")
        print(f"   - Неоптимальное время: {suboptimal} (вес x4 = {suboptimal * 4})")
        print(f"   - Дисперсия нагрузки: {variance:.1f} (вес x3 = {variance * 3:.1f})")
        print(f"   - Разброс расписания: {spread} (вес x2 = {spread * 2})")

    def _print_final_statistics(self):
        """Вывести финальную статистику"""
        print("\n" + "-" * 80)
        print("📊 РЕЗУЛЬТАТЫ ОПТИМИЗАЦИИ:")
        print("-" * 80)

        improvement = self.stats['initial_metric'] - self.stats['final_metric']
        improvement_pct = (improvement / self.stats['initial_metric'] * 100) if self.stats['initial_metric'] > 0 else 0

        print(f"\n   Начальная метрика: {self.stats['initial_metric']:.2f}")
        print(f"   Финальная метрика: {self.stats['final_metric']:.2f}")
        print(f"   Улучшение: {improvement:.2f} ({improvement_pct:.1f}%)")

        print(f"\n   Итераций: {self.stats['iterations']}")
        print(f"   Улучшений: {self.stats['improvements']}")
        print(f"   Принято ухудшений: {self.stats['accepted_worse']}")

        print("\n📈 Финальная детализация:")
        self._print_metric_breakdown()

        # Топ учителей с окнами
        print("\n👨‍🏫 Топ-5 учителей с наибольшим количеством окон:")
        teacher_gap_list = []
        for teacher in self.loader.teachers.values():
            gaps = self.schedule.get_teacher_gaps(teacher)
            if gaps > 0:
                teacher_gap_list.append((teacher.name, gaps))

        teacher_gap_list.sort(key=lambda x: x[1], reverse=True)
        for i, (name, gaps) in enumerate(teacher_gap_list[:5], 1):
            print(f"   {i}. {name}: {gaps} окон")

        # Нагрузка по дням
        print("\n📅 Нагрузка по дням недели:")
        day_names = {
            DayOfWeek.MONDAY: "Понедельник",
            DayOfWeek.TUESDAY: "Вторник",
            DayOfWeek.WEDNESDAY: "Среда",
            DayOfWeek.THURSDAY: "Четверг",
            DayOfWeek.FRIDAY: "Пятница"
        }

        for day in DayOfWeek:
            count = sum(1 for l in self.schedule.lessons if l.time_slot.day == day)
            bar = "█" * (count // 5)
            print(f"   {day_names[day]:12s}: {count:3d} уроков {bar}")

        print("\n" + "=" * 100)

    def print_statistics(self):
        """Вывести статистику (публичный метод)"""
        self._print_final_statistics()


# Тестирование
if __name__ == '__main__':
    import sys
    sys.path.insert(0, '/home/user/ege-superbot/raspisanie')

    from demo_data import DemoDataLoader
    from schedule_generator import ScheduleGenerator
    from phase2_mandatory import Phase2MandatoryPlacer

    print("=" * 100)
    print(" " * 30 + "ТЕСТ ФАЗЫ 3")
    print("=" * 100)

    # Загружаем демо-данные
    loader = DemoDataLoader()
    loader.load_all()

    # Фаза 1
    generator = ScheduleGenerator(loader)
    generator.place_ege_practices()
    print(f"\nПосле Фазы 1: {len(generator.schedule.lessons)} уроков")

    # Фаза 2
    phase2 = Phase2MandatoryPlacer(
        schedule=generator.schedule,
        loader=loader,
        ege_slots=generator.ege_slots
    )
    phase2.place_all_mandatory_subjects()
    print(f"После Фазы 2: {len(generator.schedule.lessons)} уроков")

    # Фаза 3
    optimizer = Phase3Optimizer(
        schedule=generator.schedule,
        loader=loader
    )
    optimized = optimizer.optimize(max_iterations=1000)

    print(f"\nПосле Фазы 3: {len(optimized.lessons)} уроков")

    # Сохраняем результат
    optimized.save_to_json('output/schedule_optimized.json')
    print(f"\n💾 Расписание сохранено в output/schedule_optimized.json")
