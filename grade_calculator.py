#!/usr/bin/env python3
"""
Приложение для расчёта градации оценок в тесте
Показывает какую оценку получит ученик при определённом количестве правильных ответов
"""

import tkinter as tk
from tkinter import ttk, messagebox


class GradeCalculatorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Калькулятор оценок")
        self.root.geometry("700x600")
        self.root.resizable(True, True)

        # Критерии оценки (обычный режим - сдаёт ЕГЭ)
        self.criteria_ege = {
            5: 85,  # 85%+
            4: 65,  # 65-84%
            3: 50,  # 50-64%
        }

        # Критерии оценки (режим "не сдаёт ЕГЭ" - мягче на 10%)
        self.criteria_no_ege = {
            5: 75,  # 75%+
            4: 55,  # 55-74%
            3: 40,  # 40-54%
        }

        self.create_widgets()

    def create_widgets(self):
        # Заголовок
        title_label = tk.Label(
            self.root,
            text="Калькулятор градации оценок",
            font=("Arial", 16, "bold"),
            pady=10
        )
        title_label.pack()

        # Фрейм для ввода
        input_frame = tk.Frame(self.root, pady=10)
        input_frame.pack()

        # Поле ввода количества вопросов
        tk.Label(input_frame, text="Количество вопросов в тесте:", font=("Arial", 11)).grid(row=0, column=0, padx=5, sticky="w")
        self.questions_entry = tk.Entry(input_frame, width=10, font=("Arial", 11))
        self.questions_entry.grid(row=0, column=1, padx=5)

        # Чекбокс "Не сдаёт ЕГЭ"
        self.no_ege_var = tk.BooleanVar()
        self.no_ege_check = tk.Checkbutton(
            input_frame,
            text="Не сдаёт ЕГЭ (мягкие критерии)",
            variable=self.no_ege_var,
            font=("Arial", 10),
            command=self.on_mode_change
        )
        self.no_ege_check.grid(row=1, column=0, columnspan=2, pady=5, sticky="w")

        # Показать текущие критерии
        self.criteria_label = tk.Label(
            input_frame,
            text=self.get_criteria_text(),
            font=("Arial", 9),
            fg="gray",
            justify="left"
        )
        self.criteria_label.grid(row=2, column=0, columnspan=2, pady=5, sticky="w")

        # Кнопка расчёта
        calculate_btn = tk.Button(
            input_frame,
            text="Рассчитать",
            command=self.calculate_grades,
            font=("Arial", 11, "bold"),
            bg="#4CAF50",
            fg="white",
            padx=20,
            pady=5
        )
        calculate_btn.grid(row=3, column=0, columnspan=2, pady=10)

        # Фрейм для таблицы результатов
        table_frame = tk.Frame(self.root)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        # Заголовок таблицы
        tk.Label(table_frame, text="Результаты:", font=("Arial", 12, "bold")).pack(anchor="w")

        # Скроллбар
        scrollbar = tk.Scrollbar(table_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Таблица с результатами
        self.results_tree = ttk.Treeview(
            table_frame,
            columns=("correct", "incorrect", "percent", "grade"),
            show="headings",
            yscrollcommand=scrollbar.set,
            height=15
        )

        self.results_tree.heading("correct", text="Правильных")
        self.results_tree.heading("incorrect", text="Неправильных")
        self.results_tree.heading("percent", text="Процент")
        self.results_tree.heading("grade", text="Оценка")

        self.results_tree.column("correct", width=120, anchor="center")
        self.results_tree.column("incorrect", width=120, anchor="center")
        self.results_tree.column("percent", width=120, anchor="center")
        self.results_tree.column("grade", width=120, anchor="center")

        scrollbar.config(command=self.results_tree.yview)
        self.results_tree.pack(fill=tk.BOTH, expand=True)

        # Настройка цветов для оценок
        self.setup_tags()

    def setup_tags(self):
        """Настройка цветовых тегов для оценок"""
        self.results_tree.tag_configure("grade_5", background="#E3F2FD", foreground="#1565C0")  # Синий
        self.results_tree.tag_configure("grade_4", background="#E8F5E9", foreground="#2E7D32")  # Зелёный
        self.results_tree.tag_configure("grade_3", background="#FFF9C4", foreground="#F57F17")  # Жёлтый
        self.results_tree.tag_configure("grade_2", background="#FFEBEE", foreground="#C62828")  # Красный

    def get_criteria_text(self):
        """Получить текст с критериями оценки"""
        if self.no_ege_var.get():
            return "Критерии: 5 (75%+), 4 (55-74%), 3 (40-54%), 2 (<40%)"
        else:
            return "Критерии: 5 (85%+), 4 (65-84%), 3 (50-64%), 2 (<50%)"

    def on_mode_change(self):
        """Обработчик изменения режима"""
        self.criteria_label.config(text=self.get_criteria_text())
        # Если уже есть результаты, пересчитать
        if self.questions_entry.get():
            self.calculate_grades()

    def get_grade(self, percent):
        """Определить оценку по проценту правильных ответов"""
        criteria = self.criteria_no_ege if self.no_ege_var.get() else self.criteria_ege

        if percent >= criteria[5]:
            return 5
        elif percent >= criteria[4]:
            return 4
        elif percent >= criteria[3]:
            return 3
        else:
            return 2

    def calculate_grades(self):
        """Рассчитать и отобразить градацию оценок"""
        try:
            total_questions = int(self.questions_entry.get())

            if total_questions <= 0:
                messagebox.showerror("Ошибка", "Количество вопросов должно быть положительным числом!")
                return

            if total_questions > 1000:
                messagebox.showwarning("Предупреждение", "Слишком большое количество вопросов. Рекомендуется не более 1000.")

            # Очистить предыдущие результаты
            for item in self.results_tree.get_children():
                self.results_tree.delete(item)

            # Рассчитать для каждого количества правильных ответов
            for correct in range(total_questions, -1, -1):
                incorrect = total_questions - correct
                percent = (correct / total_questions) * 100
                grade = self.get_grade(percent)

                # Определить тег для цвета
                tag = f"grade_{grade}"

                # Добавить строку в таблицу
                self.results_tree.insert(
                    "",
                    tk.END,
                    values=(
                        correct,
                        incorrect,
                        f"{percent:.1f}%",
                        grade
                    ),
                    tags=(tag,)
                )

        except ValueError:
            messagebox.showerror("Ошибка", "Пожалуйста, введите корректное число!")


def main():
    root = tk.Tk()
    app = GradeCalculatorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
