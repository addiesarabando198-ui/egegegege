#!/usr/bin/env python3
"""
Главный файл для запуска генератора расписания
ГБОУ "Школа Покровский квартал"

Использование:
    python main.py                    # Запуск с демо-данными
    python main.py --data-dir data    # Запуск с реальными данными
    python main.py --phase 1          # Только Фаза 1
    python main.py --phase 2          # Фазы 1-2
    python main.py --demo             # Принудительно использовать демо-данные
"""

import sys
import argparse
from pathlib import Path


def main():
    """Главная функция"""
    parser = argparse.ArgumentParser(
        description='Генератор расписания для школы "Покровский квартал"'
    )

    parser.add_argument(
        '--data-dir', type=str, default='data',
        help='Папка с исходными данными (Excel файлы)'
    )
    parser.add_argument(
        '--output-dir', type=str, default='output',
        help='Папка для результатов'
    )
    parser.add_argument(
        '--phase', type=str, default='all',
        choices=['all', '1', '2', '3'],
        help='Какую фазу запустить (all=все, 1=только практикумы, 2=+обязательные, 3=+оптимизация)'
    )
    parser.add_argument(
        '--demo', action='store_true',
        help='Использовать демо-данные вместо реальных'
    )
    parser.add_argument(
        '--iterations', type=int, default=1000,
        help='Количество итераций оптимизации (по умолчанию 1000)'
    )
    parser.add_argument(
        '--quiet', action='store_true',
        help='Минимальный вывод'
    )

    args = parser.parse_args()

    print("=" * 100)
    print(" " * 20 + "ГЕНЕРАТОР РАСПИСАНИЯ v1.0")
    print(" " * 15 + "ГБОУ \"Школа Покровский квартал\" (корпус БК)")
    print("=" * 100)

    # Определяем источник данных
    data_dir = Path(args.data_dir)
    use_demo = args.demo

    # Проверка наличия реальных данных
    if not use_demo:
        required_files = [
            'Здания__кабинеты__места__школьные_здания_.xlsx',
            'Расстановка_кадров_ФЕВРАЛЬ_2025-2026_учебный_год__2_.xlsx',
            'Список_участников_ГИА-11_ГБОУ_Школа__Покровский_квартал___41_.xlsx'
        ]

        missing_files = []
        if not data_dir.exists():
            use_demo = True
            print(f"\n⚠️  Папка {data_dir} не найдена. Используем демо-данные.")
        else:
            for filename in required_files:
                if not (data_dir / filename).exists():
                    missing_files.append(filename)

            if missing_files:
                use_demo = True
                print(f"\n⚠️  Отсутствуют файлы данных:")
                for f in missing_files:
                    print(f"   - {f}")
                print("   Используем демо-данные.")

    # Создание папки для результатов
    output_dir = Path(args.output_dir)
    output_dir.mkdir(exist_ok=True)

    # Загрузка данных
    print("\n" + "=" * 100)
    print("ЗАГРУЗКА ДАННЫХ")
    print("=" * 100)

    if use_demo:
        from demo_data import DemoDataLoader
        loader = DemoDataLoader()
        loader.load_all()
    else:
        from data_loader import DataLoader
        loader = DataLoader()

        try:
            loader.load_classrooms(str(data_dir / required_files[0]))
            loader.load_teachers_and_subjects(str(data_dir / required_files[1]))
            loader.load_students_and_ege_choices(str(data_dir / required_files[2]))
            loader.create_ege_practice_groups()
            loader.print_summary()
        except Exception as e:
            print(f"\n❌ Ошибка при загрузке данных: {e}")
            print("   Переключаемся на демо-данные...")
            from demo_data import DemoDataLoader
            loader = DemoDataLoader()
            loader.load_all()

    # Импорт генератора
    from schedule_generator import ScheduleGenerator
    from phase2_mandatory import Phase2MandatoryPlacer
    from phase3_optimization import Phase3Optimizer

    # ===== ФАЗА 1: Практикумы ЕГЭ =====
    print("\n" + "=" * 100)
    print("ФАЗА 1: РАЗМЕЩЕНИЕ ПРАКТИКУМОВ ЕГЭ")
    print("=" * 100)

    generator = ScheduleGenerator(loader)
    generator.place_ege_practices()

    # Сохранение промежуточного результата
    generator.schedule.save_to_json(str(output_dir / 'schedule_phase1.json'))
    print(f"\n💾 Фаза 1 сохранена: {output_dir / 'schedule_phase1.json'}")

    if args.phase == '1':
        _print_final_summary(generator.schedule, loader)
        return 0

    # ===== ФАЗА 2: Обязательные предметы =====
    phase2 = Phase2MandatoryPlacer(
        schedule=generator.schedule,
        loader=loader,
        ege_slots=generator.ege_slots
    )
    phase2.place_all_mandatory_subjects()

    # Сохранение промежуточного результата
    generator.schedule.save_to_json(str(output_dir / 'schedule_phase2.json'))
    print(f"\n💾 Фаза 2 сохранена: {output_dir / 'schedule_phase2.json'}")

    if args.phase == '2':
        _print_final_summary(generator.schedule, loader)
        return 0

    # ===== ФАЗА 3: Оптимизация =====
    optimizer = Phase3Optimizer(
        schedule=generator.schedule,
        loader=loader
    )
    optimized_schedule = optimizer.optimize(
        max_iterations=args.iterations,
        verbose=not args.quiet
    )

    # Сохранение финального результата
    optimized_schedule.save_to_json(str(output_dir / 'schedule_final.json'))
    print(f"\n💾 Финальное расписание: {output_dir / 'schedule_final.json'}")

    _print_final_summary(optimized_schedule, loader)

    return 0


def _print_final_summary(schedule, loader):
    """Вывод итоговой сводки"""
    print("\n" + "=" * 100)
    print(" " * 35 + "ИТОГОВАЯ СВОДКА")
    print("=" * 100)

    total_lessons = len(schedule.lessons)
    ege_lessons = sum(1 for l in schedule.lessons if l.is_ege_practice)
    mandatory_lessons = total_lessons - ege_lessons

    print(f"\n📊 Всего уроков в расписании: {total_lessons}")
    print(f"   - Практикумы ЕГЭ: {ege_lessons}")
    print(f"   - Обязательные предметы: {mandatory_lessons}")

    # Окна у учителей
    total_teacher_gaps = sum(
        schedule.get_teacher_gaps(t)
        for t in loader.teachers.values()
    )
    print(f"\n🕳️  Окон у учителей: {total_teacher_gaps}")

    # Окна у классов
    total_class_gaps = sum(
        schedule.get_class_gaps(c)
        for c in loader.classes.keys()
    )
    print(f"🕳️  Окон у классов: {total_class_gaps}")

    # Нагрузка по дням
    from schedule_base import DayOfWeek
    day_names = {
        DayOfWeek.MONDAY: "ПН",
        DayOfWeek.TUESDAY: "ВТ",
        DayOfWeek.WEDNESDAY: "СР",
        DayOfWeek.THURSDAY: "ЧТ",
        DayOfWeek.FRIDAY: "ПТ"
    }

    print("\n📅 Нагрузка по дням:")
    for day in DayOfWeek:
        count = sum(1 for l in schedule.lessons if l.time_slot.day == day)
        bar = "█" * (count // 10)
        print(f"   {day_names[day]}: {count:3d} {bar}")

    print("\n✅ Генерация расписания завершена!")
    print("=" * 100)


if __name__ == '__main__':
    sys.exit(main())
