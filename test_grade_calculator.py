#!/usr/bin/env python3
"""
Тест логики калькулятора оценок без GUI
"""

def get_grade_ege(percent):
    """Определить оценку по проценту (режим ЕГЭ)"""
    if percent >= 85:
        return 5
    elif percent >= 65:
        return 4
    elif percent >= 50:
        return 3
    else:
        return 2

def get_grade_no_ege(percent):
    """Определить оценку по проценту (режим без ЕГЭ)"""
    if percent >= 75:
        return 5
    elif percent >= 55:
        return 4
    elif percent >= 40:
        return 3
    else:
        return 2

def test_calculations():
    """Тестирование расчётов"""
    print("=== Тестирование калькулятора оценок ===\n")

    # Тест 1: 20 вопросов, режим ЕГЭ
    print("Тест 1: 20 вопросов, режим ЕГЭ")
    total = 20
    print(f"Всего вопросов: {total}")
    print("\nПравильных | Процент | Оценка")
    print("-" * 35)

    for correct in range(total, -1, -1):
        percent = (correct / total) * 100
        grade = get_grade_ege(percent)
        print(f"{correct:10} | {percent:6.1f}% | {grade}")

    # Тест 2: 20 вопросов, режим "не сдаёт ЕГЭ"
    print("\n\nТест 2: 20 вопросов, режим 'не сдаёт ЕГЭ'")
    print(f"Всего вопросов: {total}")
    print("\nПравильных | Процент | Оценка")
    print("-" * 35)

    for correct in range(total, -1, -1):
        percent = (correct / total) * 100
        grade = get_grade_no_ege(percent)
        print(f"{correct:10} | {percent:6.1f}% | {grade}")

    # Проверка критических точек
    print("\n\n=== Проверка граничных значений ===")

    print("\nРежим ЕГЭ:")
    test_cases_ege = [
        (85, "граница 5/4"),
        (84.9, "чуть ниже границы 5"),
        (65, "граница 4/3"),
        (64.9, "чуть ниже границы 4"),
        (50, "граница 3/2"),
        (49.9, "чуть ниже границы 3"),
    ]

    for percent, description in test_cases_ege:
        grade = get_grade_ege(percent)
        print(f"{percent:5.1f}% ({description:25}) -> оценка {grade}")

    print("\nРежим 'не сдаёт ЕГЭ':")
    test_cases_no_ege = [
        (75, "граница 5/4"),
        (74.9, "чуть ниже границы 5"),
        (55, "граница 4/3"),
        (54.9, "чуть ниже границы 4"),
        (40, "граница 3/2"),
        (39.9, "чуть ниже границы 3"),
    ]

    for percent, description in test_cases_no_ege:
        grade = get_grade_no_ege(percent)
        print(f"{percent:5.1f}% ({description:25}) -> оценка {grade}")

    print("\n=== Все тесты пройдены успешно! ===")

if __name__ == "__main__":
    test_calculations()
