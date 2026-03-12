"""
Веб-приложение для автоматического составления расписания
ГБОУ "Школа Покровский квартал"

Запуск: streamlit run streamlit_app.py
"""

import streamlit as st
import pandas as pd
import json
from pathlib import Path
from io import BytesIO
from typing import Optional

# Настройка страницы
st.set_page_config(
    page_title="Генератор расписания",
    page_icon="📅",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS стили
st.markdown("""
<style>
    .main-header {
        font-size: 2rem;
        font-weight: bold;
        margin-bottom: 0.5rem;
    }
    .sub-header {
        font-size: 1rem;
        color: #666;
        margin-bottom: 2rem;
    }
    .metric-card {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 0.5rem 0;
    }
    .success-box {
        background-color: #d4edda;
        padding: 1rem;
        border-radius: 0.5rem;
        border: 1px solid #c3e6cb;
    }
    .warning-box {
        background-color: #fff3cd;
        padding: 1rem;
        border-radius: 0.5rem;
        border: 1px solid #ffeeba;
    }
</style>
""", unsafe_allow_html=True)


def main():
    # Заголовок
    st.markdown('<p class="main-header">📅 Генератор расписания</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">ГБОУ "Школа Покровский квартал" — автоматическое составление расписания для 11 классов</p>', unsafe_allow_html=True)

    # Инициализация состояния
    if 'step' not in st.session_state:
        st.session_state.step = 1
    if 'loader' not in st.session_state:
        st.session_state.loader = None
    if 'schedule' not in st.session_state:
        st.session_state.schedule = None

    # Боковая панель - навигация
    with st.sidebar:
        st.header("📋 Этапы работы")

        steps = [
            ("1️⃣", "Загрузка данных", 1),
            ("2️⃣", "Проверка данных", 2),
            ("3️⃣", "Генерация расписания", 3),
            ("4️⃣", "Просмотр и экспорт", 4),
        ]

        for icon, name, step_num in steps:
            if st.session_state.step >= step_num:
                st.success(f"{icon} {name}")
            else:
                st.info(f"{icon} {name}")

        st.markdown("---")

        # Кнопка сброса
        if st.button("🔄 Начать заново"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

    # Основной контент в зависимости от шага
    if st.session_state.step == 1:
        show_step1_upload()
    elif st.session_state.step == 2:
        show_step2_review()
    elif st.session_state.step == 3:
        show_step3_generate()
    elif st.session_state.step == 4:
        show_step4_export()


def show_step1_upload():
    """Шаг 1: Загрузка данных"""
    st.header("1️⃣ Загрузка данных")

    st.markdown("""
    Загрузите Excel-файлы с данными школы или используйте демо-данные для тестирования.
    """)

    # Выбор источника данных
    data_source = st.radio(
        "Выберите источник данных:",
        ["📁 Загрузить Excel-файлы", "🎮 Использовать демо-данные"],
        horizontal=True
    )

    if data_source == "🎮 Использовать демо-данные":
        st.info("Демо-данные содержат 43 учителя, 29 кабинетов, 10 классов и ~200 учеников с выбором ЕГЭ.")

        if st.button("📥 Загрузить демо-данные", type="primary"):
            with st.spinner("Создание демо-данных..."):
                from demo_data import DemoDataLoader
                loader = DemoDataLoader()
                loader.load_all()
                st.session_state.loader = loader
                st.session_state.step = 2
                st.rerun()

    else:
        st.markdown("### Необходимые файлы:")

        col1, col2, col3 = st.columns(3)

        with col1:
            st.markdown("**🏫 Кабинеты**")
            classrooms_file = st.file_uploader(
                "Здания и кабинеты",
                type=['xlsx', 'xls'],
                key='classrooms_file',
                help="Файл с информацией о кабинетах (номер, вместимость, этаж)"
            )

        with col2:
            st.markdown("**👨‍🏫 Учителя и предметы**")
            teachers_file = st.file_uploader(
                "Расстановка кадров",
                type=['xlsx', 'xls'],
                key='teachers_file',
                help="Файл с распределением учителей по предметам и классам"
            )

        with col3:
            st.markdown("**🎓 Ученики и ЕГЭ**")
            students_file = st.file_uploader(
                "Список участников ГИА",
                type=['xlsx', 'xls'],
                key='students_file',
                help="Файл с выбором предметов ЕГЭ учениками"
            )

        # Проверка загруженных файлов
        if classrooms_file and teachers_file and students_file:
            if st.button("📤 Загрузить данные", type="primary"):
                try:
                    with st.spinner("Загрузка и обработка файлов..."):
                        loader = load_real_data(classrooms_file, teachers_file, students_file)
                        st.session_state.loader = loader
                        st.session_state.step = 2
                        st.rerun()
                except Exception as e:
                    st.error(f"Ошибка при загрузке: {e}")
                    st.exception(e)
        else:
            st.warning("Загрузите все три файла для продолжения")


def load_real_data(classrooms_file, teachers_file, students_file):
    """Загрузка реальных данных из Excel"""
    import tempfile
    import os
    from data_loader import DataLoader

    loader = DataLoader()

    # Сохраняем файлы во временную директорию
    with tempfile.TemporaryDirectory() as tmpdir:
        # Кабинеты
        classrooms_path = os.path.join(tmpdir, "classrooms.xlsx")
        with open(classrooms_path, 'wb') as f:
            f.write(classrooms_file.getvalue())
        loader.load_classrooms(classrooms_path)

        # Учителя
        teachers_path = os.path.join(tmpdir, "teachers.xlsx")
        with open(teachers_path, 'wb') as f:
            f.write(teachers_file.getvalue())
        loader.load_teachers_and_subjects(teachers_path)

        # Ученики
        students_path = os.path.join(tmpdir, "students.xlsx")
        with open(students_path, 'wb') as f:
            f.write(students_file.getvalue())
        loader.load_students_and_ege_choices(students_path)

        # Создаем группы ЕГЭ
        loader.create_ege_practice_groups()

    return loader


def show_step2_review():
    """Шаг 2: Проверка данных"""
    st.header("2️⃣ Проверка загруженных данных")

    loader = st.session_state.loader

    if not loader:
        st.error("Данные не загружены")
        st.session_state.step = 1
        st.rerun()
        return

    # Общая статистика
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("👨‍🏫 Учителей", len(loader.teachers))
    with col2:
        st.metric("🏫 Кабинетов", len(loader.classrooms))
    with col3:
        st.metric("👥 Классов", len(loader.classes))
    with col4:
        st.metric("🎓 Учеников", len(loader.students))

    st.markdown("---")

    # Детальная информация по вкладкам
    tab1, tab2, tab3, tab4 = st.tabs(["👨‍🏫 Учителя", "🏫 Кабинеты", "👥 Классы", "🎯 Практикумы ЕГЭ"])

    with tab1:
        show_teachers_table(loader)

    with tab2:
        show_classrooms_table(loader)

    with tab3:
        show_classes_table(loader)

    with tab4:
        show_ege_groups_table(loader)

    st.markdown("---")

    # Кнопки навигации
    col1, col2 = st.columns([1, 1])

    with col1:
        if st.button("⬅️ Назад к загрузке"):
            st.session_state.step = 1
            st.rerun()

    with col2:
        if st.button("➡️ Перейти к генерации", type="primary"):
            st.session_state.step = 3
            st.rerun()


def show_teachers_table(loader):
    """Таблица учителей"""
    from schedule_base import DayOfWeek

    data = []
    for name, teacher in loader.teachers.items():
        unavailable = ", ".join([
            {"MONDAY": "ПН", "TUESDAY": "ВТ", "WEDNESDAY": "СР",
             "THURSDAY": "ЧТ", "FRIDAY": "ПТ"}.get(d.name, d.name)
            for d in teacher.unavailable_days
        ]) or "—"

        data.append({
            "ФИО": name,
            "Предметы": ", ".join(teacher.subjects[:3]) + ("..." if len(teacher.subjects) > 3 else ""),
            "Кабинет": teacher.home_classroom or "—",
            "Недоступен": unavailable
        })

    df = pd.DataFrame(data)
    st.dataframe(df, use_container_width=True, height=400)


def show_classrooms_table(loader):
    """Таблица кабинетов"""
    data = []
    for num, room in loader.classrooms.items():
        data.append({
            "Номер": num,
            "Вместимость": room.capacity,
            "Этаж": room.floor,
            "Ответственный": room.responsible_teacher or "—"
        })

    df = pd.DataFrame(data)
    st.dataframe(df, use_container_width=True, height=400)


def show_classes_table(loader):
    """Таблица классов"""
    data = []
    for name, cls in loader.classes.items():
        data.append({
            "Класс": name,
            "Профиль": cls.profile,
            "Учеников": cls.student_count
        })

    df = pd.DataFrame(data)
    st.dataframe(df, use_container_width=True)

    # Статистика по ЕГЭ
    st.subheader("📊 Популярность предметов ЕГЭ")
    from collections import Counter
    ege_counts = Counter()
    for student in loader.students.values():
        ege_counts.update(student.ege_subjects)

    ege_data = [{"Предмет": subj, "Учеников": count}
                for subj, count in ege_counts.most_common(10)]
    df_ege = pd.DataFrame(ege_data)
    st.bar_chart(df_ege.set_index("Предмет"))


def show_ege_groups_table(loader):
    """Таблица групп ЕГЭ"""
    data = []
    for group in loader.ege_groups:
        data.append({
            "Предмет": group.subject,
            "Учитель": group.teacher.name,
            "Учеников": group.student_count,
            "Часов/нед": group.hours_per_week,
            "Классы": ", ".join(sorted(group.classes_involved))
        })

    df = pd.DataFrame(data)
    df = df.sort_values("Учеников", ascending=False)
    st.dataframe(df, use_container_width=True, height=400)


def show_step3_generate():
    """Шаг 3: Генерация расписания"""
    st.header("3️⃣ Генерация расписания")

    loader = st.session_state.loader

    # Параметры генерации
    st.subheader("⚙️ Параметры")

    col1, col2 = st.columns(2)

    with col1:
        iterations = st.slider(
            "Количество итераций оптимизации",
            min_value=100,
            max_value=3000,
            value=1000,
            step=100,
            help="Больше итераций = лучше результат, но дольше"
        )

    with col2:
        run_optimization = st.checkbox(
            "Запустить оптимизацию (Фаза 3)",
            value=True,
            help="Оптимизация уменьшает количество окон у учителей и классов"
        )

    st.markdown("---")

    # Описание этапов
    st.markdown("""
    ### Этапы генерации:

    1. **Фаза 1:** Размещение практикумов ЕГЭ в оптимальные слоты
       - Все 11 классы имеют практикумы одновременно
       - Ученики из разных классов объединяются по предметам

    2. **Фаза 2:** Размещение обязательных предметов
       - Сложные предметы (математика, русский) на 2-4 уроках
       - Учет доступности учителей

    3. **Фаза 3:** Оптимизация (Simulated Annealing)
       - Минимизация окон у учителей
       - Минимизация окон у классов
       - Равномерная нагрузка по дням
    """)

    st.markdown("---")

    # Кнопка генерации
    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        if st.button("🚀 Сгенерировать расписание", type="primary", use_container_width=True):
            generate_schedule(loader, iterations, run_optimization)


def generate_schedule(loader, iterations, run_optimization):
    """Генерация расписания с прогресс-баром"""
    from schedule_generator import ScheduleGenerator
    from phase2_mandatory import Phase2MandatoryPlacer
    from phase3_optimization import Phase3Optimizer

    progress = st.progress(0)
    status = st.empty()

    # Фаза 1
    status.info("🎯 Фаза 1: Размещение практикумов ЕГЭ...")
    generator = ScheduleGenerator(loader)
    generator.place_ege_practices()
    progress.progress(33)

    phase1_count = len(generator.schedule.lessons)

    # Фаза 2
    status.info("📚 Фаза 2: Размещение обязательных предметов...")
    phase2 = Phase2MandatoryPlacer(
        schedule=generator.schedule,
        loader=loader,
        ege_slots=generator.ege_slots
    )
    phase2_stats = phase2.place_all_mandatory_subjects()
    progress.progress(66)

    phase2_count = len(generator.schedule.lessons) - phase1_count

    # Фаза 3
    if run_optimization:
        status.info("🔧 Фаза 3: Оптимизация расписания...")
        optimizer = Phase3Optimizer(
            schedule=generator.schedule,
            loader=loader
        )
        schedule = optimizer.optimize(max_iterations=iterations, verbose=False)
        phase3_stats = optimizer.stats
    else:
        schedule = generator.schedule
        phase3_stats = None

    progress.progress(100)
    status.empty()

    # Сохраняем результат
    st.session_state.schedule = schedule
    st.session_state.stats = {
        'phase1_count': phase1_count,
        'phase2_stats': phase2_stats,
        'phase3_stats': phase3_stats
    }
    st.session_state.step = 4

    st.success("✅ Расписание успешно сгенерировано!")
    st.balloons()

    # Автопереход
    import time
    time.sleep(1)
    st.rerun()


def show_step4_export():
    """Шаг 4: Просмотр и экспорт"""
    st.header("4️⃣ Просмотр и экспорт расписания")

    schedule = st.session_state.schedule
    loader = st.session_state.loader
    stats = st.session_state.stats

    if not schedule:
        st.error("Расписание не сгенерировано")
        st.session_state.step = 3
        st.rerun()
        return

    # Статистика
    show_generation_stats(schedule, loader, stats)

    st.markdown("---")

    # Просмотр расписания
    st.subheader("📋 Просмотр расписания")

    view_mode = st.radio(
        "Режим просмотра:",
        ["По классам", "По учителям", "По кабинетам"],
        horizontal=True
    )

    if view_mode == "По классам":
        show_schedule_by_class(schedule, loader)
    elif view_mode == "По учителям":
        show_schedule_by_teacher(schedule, loader)
    else:
        show_schedule_by_classroom(schedule, loader)

    st.markdown("---")

    # Экспорт
    st.subheader("📥 Экспорт")

    col1, col2, col3 = st.columns(3)

    with col1:
        # JSON
        json_data = json.dumps(schedule.to_dict(), ensure_ascii=False, indent=2)
        st.download_button(
            "⬇️ Скачать JSON",
            data=json_data,
            file_name="raspisanie.json",
            mime="application/json",
            use_container_width=True
        )

    with col2:
        # Excel
        excel_data = export_to_excel(schedule, loader)
        st.download_button(
            "⬇️ Скачать Excel",
            data=excel_data,
            file_name="raspisanie.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

    with col3:
        # Новая генерация
        if st.button("🔄 Сгенерировать заново", use_container_width=True):
            st.session_state.step = 3
            st.rerun()


def show_generation_stats(schedule, loader, stats):
    """Показать статистику генерации"""
    from schedule_base import DayOfWeek

    # Основные метрики
    col1, col2, col3, col4 = st.columns(4)

    total = len(schedule.lessons)
    ege = sum(1 for l in schedule.lessons if l.is_ege_practice)

    with col1:
        st.metric("📊 Всего уроков", total)

    with col2:
        st.metric("🎯 Практикумы ЕГЭ", ege)

    with col3:
        success_rate = stats['phase2_stats']['placed'] / stats['phase2_stats']['total_required'] * 100
        st.metric("✅ Успешность", f"{success_rate:.1f}%")

    with col4:
        if stats['phase3_stats']:
            improvement = stats['phase3_stats']['initial_metric'] - stats['phase3_stats']['final_metric']
            pct = improvement / stats['phase3_stats']['initial_metric'] * 100
            st.metric("📈 Оптимизация", f"+{pct:.1f}%")
        else:
            st.metric("📈 Оптимизация", "—")

    # Окна
    col1, col2 = st.columns(2)

    with col1:
        teacher_gaps = sum(schedule.get_teacher_gaps(t) for t in loader.teachers.values())
        st.metric("🕳️ Окон у учителей", teacher_gaps)

    with col2:
        class_gaps = sum(schedule.get_class_gaps(c) for c in loader.classes.keys())
        st.metric("🕳️ Окон у классов", class_gaps)


def show_schedule_by_class(schedule, loader):
    """Расписание по классам"""
    from schedule_base import DayOfWeek

    class_names = sorted(loader.classes.keys())
    selected = st.selectbox("Выберите класс:", class_names)

    if selected:
        lessons = [l for l in schedule.lessons if selected in l.class_or_group]
        df = build_schedule_table(lessons)
        st.dataframe(df, use_container_width=True, height=350)

        # Статистика
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Уроков", len(lessons))
        with col2:
            st.metric("Окон", schedule.get_class_gaps(selected))
        with col3:
            ege = sum(1 for l in lessons if l.is_ege_practice)
            st.metric("Практикумов ЕГЭ", ege)


def show_schedule_by_teacher(schedule, loader):
    """Расписание по учителям"""
    teacher_names = sorted(loader.teachers.keys())
    selected = st.selectbox("Выберите учителя:", teacher_names)

    if selected:
        lessons = schedule.get_lessons_by_teacher(selected)
        df = build_schedule_table(lessons, show_class=True)
        st.dataframe(df, use_container_width=True, height=350)

        teacher = loader.teachers[selected]
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Уроков", len(lessons))
        with col2:
            st.metric("Окон", schedule.get_teacher_gaps(teacher))
        with col3:
            unavailable = len(teacher.unavailable_days)
            st.metric("Недоступных дней", unavailable)


def show_schedule_by_classroom(schedule, loader):
    """Загрузка кабинетов"""
    data = []
    for room_num, classroom in sorted(loader.classrooms.items()):
        lessons = [l for l in schedule.lessons
                  if l.classroom and l.classroom.number == room_num]
        load_pct = len(lessons) / 35 * 100

        data.append({
            "Кабинет": room_num,
            "Вместимость": classroom.capacity,
            "Уроков": len(lessons),
            "Загрузка": f"{load_pct:.0f}%"
        })

    df = pd.DataFrame(data)
    st.dataframe(df, use_container_width=True, height=400)


def build_schedule_table(lessons, show_class=False):
    """Построить таблицу расписания"""
    from schedule_base import DayOfWeek

    day_names = {
        DayOfWeek.MONDAY: "ПН",
        DayOfWeek.TUESDAY: "ВТ",
        DayOfWeek.WEDNESDAY: "СР",
        DayOfWeek.THURSDAY: "ЧТ",
        DayOfWeek.FRIDAY: "ПТ"
    }

    data = {day_names[day]: [""] * 7 for day in DayOfWeek}
    data["Урок"] = list(range(1, 8))

    for lesson in lessons:
        day_col = day_names[lesson.time_slot.day]
        row = lesson.time_slot.lesson_number - 1

        if show_class:
            cell = f"{lesson.subject} ({lesson.class_or_group})"
        else:
            cell = f"{lesson.subject}"

        if lesson.classroom:
            cell += f" [каб.{lesson.classroom.number}]"

        if data[day_col][row]:
            data[day_col][row] += " | " + cell
        else:
            data[day_col][row] = cell

    df = pd.DataFrame(data)
    return df[["Урок", "ПН", "ВТ", "СР", "ЧТ", "ПТ"]]


def export_to_excel(schedule, loader) -> bytes:
    """Экспорт в Excel"""
    from schedule_base import DayOfWeek

    output = BytesIO()

    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # Лист со всеми уроками
        all_data = []
        for lesson in schedule.lessons:
            all_data.append({
                "День": lesson.time_slot.day.name,
                "Урок": lesson.time_slot.lesson_number,
                "Предмет": lesson.subject,
                "Учитель": lesson.teacher.name,
                "Класс": lesson.class_or_group,
                "Кабинет": lesson.classroom.number if lesson.classroom else "",
                "Тип": "Практикум ЕГЭ" if lesson.is_ege_practice else "Обязательный"
            })

        pd.DataFrame(all_data).to_excel(writer, sheet_name="Все уроки", index=False)

        # Листы по классам
        for class_name in sorted(loader.classes.keys()):
            lessons = [l for l in schedule.lessons if class_name in l.class_or_group]
            df = build_schedule_table(lessons)
            # Имя листа не более 31 символа
            sheet_name = class_name[:31]
            df.to_excel(writer, sheet_name=sheet_name, index=False)

    return output.getvalue()


if __name__ == "__main__":
    main()
