"""
Алгоритм составления расписания
Фаза 1: Размещение практикумов ЕГЭ
"""

from typing import List, Set, Dict, Tuple, Optional, TYPE_CHECKING
from dataclasses import dataclass
import random
from schedule_base import *

if TYPE_CHECKING:
    from data_loader import DataLoader


class ScheduleGenerator:
    """Генератор расписания"""

    def __init__(self, loader):
        self.loader = loader
        self.schedule = Schedule()
        
        # Все возможные временные слоты
        self.all_time_slots = [
            TimeSlot(day, lesson)
            for day in DayOfWeek
            for lesson in range(1, 8)  # 7 уроков
        ]
        
        # Слоты, зарезервированные для практикумов ЕГЭ
        self.ege_slots: List[TimeSlot] = []
        
    def find_ege_practice_slots(self, num_slots_needed: int) -> List[TimeSlot]:
        """
        Находит оптимальные слоты для практикумов ЕГЭ
        
        Принципы:
        - Все 11 классы должны иметь практикумы одновременно
        - Слоты должны быть распределены по неделе
        - Избегаем первого и последнего уроков
        - Учитываем доступность учителей
        """
        print(f"\n🔍 Поиск {num_slots_needed} оптимальных слотов для практикумов ЕГЭ...")
        
        # Оцениваем каждый слот
        slot_scores = {}
        
        for slot in self.all_time_slots:
            score = self.evaluate_ege_slot(slot)
            slot_scores[slot] = score
        
        # Сортируем слоты по оценке (лучшие первыми)
        sorted_slots = sorted(slot_scores.items(), key=lambda x: x[1], reverse=True)
        
        # Выбираем лучшие слоты, распределенные по дням
        selected_slots = []
        days_used = set()
        
        for slot, score in sorted_slots:
            if len(selected_slots) >= num_slots_needed:
                break
            
            # Стараемся не брать более 2 слотов в один день
            day_count = sum(1 for s in selected_slots if s.day == slot.day)
            if day_count >= 2:
                continue
            
            selected_slots.append(slot)
            days_used.add(slot.day)
        
        # Если не хватает, добавляем оставшиеся
        if len(selected_slots) < num_slots_needed:
            for slot, score in sorted_slots:
                if slot not in selected_slots:
                    selected_slots.append(slot)
                    if len(selected_slots) >= num_slots_needed:
                        break
        
        print(f"✓ Выбраны слоты:")
        for slot in selected_slots:
            print(f"  - {slot} (оценка: {slot_scores[slot]:.2f})")
        
        return selected_slots
    
    def evaluate_ege_slot(self, slot: TimeSlot) -> float:
        """
        Оценивает качество слота для практикума ЕГЭ
        
        Критерии:
        - Предпочтительны уроки 2-5 (центр дня)
        - Учитывается доступность учителей
        - Равномерное распределение по дням
        """
        score = 100.0
        
        # 1. Оценка по номеру урока
        if slot.lesson_number == 1:
            score -= 30  # Первый урок не желателен
        elif slot.lesson_number == 7:
            score -= 20  # Последний урок не желателен
        elif 2 <= slot.lesson_number <= 4:
            score += 20  # Оптимальное время
        
        # 2. Проверка доступности учителей
        available_teachers = sum(
            1 for teacher in self.loader.teachers.values()
            if teacher.is_available(slot.day)
        )
        
        availability_ratio = available_teachers / len(self.loader.teachers)
        score += availability_ratio * 50
        
        # 3. Небольшой случайный фактор для разнообразия
        score += random.uniform(-5, 5)
        
        return score
    
    def place_ege_practices(self):
        """
        Размещение практикумов ЕГЭ в расписании
        
        Алгоритм:
        1. Находим оптимальные общие слоты
        2. Для каждого слота размещаем все практикумы параллельно
        3. Назначаем кабинеты
        """
        print("\n" + "="*100)
        print(" " * 30 + "ФАЗА 1: РАЗМЕЩЕНИЕ ПРАКТИКУМОВ ЕГЭ")
        print("="*100)
        
        ege_groups = self.loader.ege_groups
        
        if not ege_groups:
            print("⚠️  Нет групп для практикумов ЕГЭ")
            return
        
        print(f"\nВсего групп: {len(ege_groups)}")
        
        # Определяем максимальное количество часов среди всех групп
        max_hours = max(group.hours_per_week for group in ege_groups)
        print(f"Максимум часов в неделю для практикумов: {max_hours}")
        
        # Находим оптимальные слоты
        self.ege_slots = self.find_ege_practice_slots(max_hours)
        
        # Для каждого слота размещаем все группы параллельно
        print(f"\n📍 Размещение групп в слоты...")
        
        for slot_idx, time_slot in enumerate(self.ege_slots):
            print(f"\n  Слот {slot_idx + 1}: {time_slot}")
            
            for group in ege_groups:
                # Проверяем, нужно ли этой группе использовать этот слот
                if slot_idx >= group.hours_per_week:
                    continue  # У этой группы меньше часов
                
                # Проверяем доступность учителя
                if not group.teacher.is_available(time_slot.day):
                    print(f"    ⚠️  {group.subject}: учитель {group.teacher.name} недоступен в {time_slot.day.name}")
                    # Нужно найти замену или перенести
                    continue
                
                # Подбираем кабинет
                classroom = self.find_available_classroom(time_slot, group.student_count)
                
                # Создаем урок
                lesson = Lesson(
                    subject=f"Практикум ЕГЭ: {group.subject}",
                    teacher=group.teacher,
                    class_or_group=f"ЕГЭ-{group.subject}",
                    classroom=classroom,
                    time_slot=time_slot,
                    is_ege_practice=True,
                    students=group.students
                )
                
                self.schedule.add_lesson(lesson)
                
                print(f"    ✓ {group.subject}: {len(group.students)} учеников, "
                      f"учитель {group.teacher.name}, каб. {classroom.number if classroom else '???'}")
        
        print(f"\n✅ Размещено {len([l for l in self.schedule.lessons if l.is_ege_practice])} уроков практикумов ЕГЭ")
    
    def find_available_classroom(self, time_slot: TimeSlot, required_capacity: int) -> Optional[Classroom]:
        """Находит свободный подходящий кабинет"""
        
        # Ищем свободные кабинеты с подходящей вместимостью
        available_classrooms = [
            classroom for classroom in self.loader.classrooms.values()
            if classroom.capacity >= required_capacity
            and not self.schedule.is_classroom_busy(classroom, time_slot)
        ]
        
        if not available_classrooms:
            return None
        
        # Предпочитаем кабинеты с наименьшей избыточной вместимостью
        available_classrooms.sort(key=lambda c: c.capacity)
        return available_classrooms[0]
    
    def generate_statistics(self):
        """Генерация статистики по расписанию"""
        print("\n" + "="*100)
        print(" " * 35 + "СТАТИСТИКА РАСПИСАНИЯ")
        print("="*100)
        
        print(f"\n📊 Всего уроков: {len(self.schedule.lessons)}")
        print(f"🎯 Практикумов ЕГЭ: {len([l for l in self.schedule.lessons if l.is_ege_practice])}")
        
        # Статистика по слотам
        print(f"\n⏰ Использование временных слотов:")
        slots_used = defaultdict(int)
        for lesson in self.schedule.lessons:
            slots_used[lesson.time_slot] += 1
        
        for day in DayOfWeek:
            day_slots = [slot for slot in self.all_time_slots if slot.day == day]
            day_lessons = sum(slots_used.get(slot, 0) for slot in day_slots)
            print(f"  {day.name:10s}: {day_lessons} уроков")
        
        # Статистика по учителям
        print(f"\n👨‍🏫 Загрузка учителей (топ-5):")
        teacher_loads = defaultdict(int)
        for lesson in self.schedule.lessons:
            teacher_loads[lesson.teacher.name] += 1
        
        for i, (teacher, count) in enumerate(sorted(teacher_loads.items(), key=lambda x: x[1], reverse=True)[:5], 1):
            print(f"  {i}. {teacher:30s}: {count} уроков")
    
    def export_to_excel(self, filename: str):
        """Экспорт расписания в Excel (будет реализовано позже)"""
        pass


# Тестирование
if __name__ == "__main__":
    import sys
    sys.path.insert(0, '/home/user/ege-superbot/raspisanie')

    from demo_data import DemoDataLoader

    print("=" * 100)
    print(" " * 25 + "ГЕНЕРАТОР РАСПИСАНИЯ - ПРОТОТИП v0.1")
    print("=" * 100)

    # Загружаем демо-данные
    loader = DemoDataLoader()
    loader.load_all()

    # Создаем генератор
    generator = ScheduleGenerator(loader)

    # Размещаем практикумы ЕГЭ
    generator.place_ege_practices()

    # Статистика
    generator.generate_statistics()

    # Сохраняем
    generator.schedule.save_to_json('output/schedule_phase1.json')
    print("\n💾 Расписание (Фаза 1) сохранено в output/schedule_phase1.json")
