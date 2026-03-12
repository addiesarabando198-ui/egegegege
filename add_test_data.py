#!/usr/bin/env python3
"""
Добавляет тестовые данные в базу для проверки WebApp
"""
import sqlite3

def add_test_data():
    conn = sqlite3.connect('quiz_async.db')
    cursor = conn.cursor()

    # Добавляем тестового учителя (user_id из скриншота Telegram - 149841646)
    teacher_id = 149841646

    # Добавляем запись в users если нет
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (teacher_id,))

    # Добавляем запись в user_roles если нет
    cursor.execute("INSERT OR IGNORE INTO user_roles (user_id, role) VALUES (?, ?)",
                  (teacher_id, "teacher"))

    # Добавляем запись в teacher_profiles если нет
    cursor.execute("""
        INSERT OR IGNORE INTO teacher_profiles
        (user_id, teacher_code, created_at)
        VALUES (?, ?, datetime('now'))
    """, (teacher_id, "TEACH-TC1RUF"))

    # Добавляем тестовых учеников (используем реальные ID из скриншота)
    # ID 1 - это relationship_id, нужны реальные user_id
    # Попробуем добавить самого учителя как ученика для теста
    students = [teacher_id]  # Используем того же пользователя как ученика для теста

    for student_id in students:
        # Добавляем ученика в users
        cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (student_id,))

        # Создаем связь учитель-ученик
        cursor.execute("""
            INSERT OR IGNORE INTO teacher_student_relationships
            (teacher_id, student_id, status, invited_at)
            VALUES (?, ?, 'active', datetime('now'))
        """, (teacher_id, student_id))

    conn.commit()

    # Проверяем что добавлено
    cursor.execute("SELECT COUNT(*) FROM teacher_student_relationships WHERE teacher_id = ?", (teacher_id,))
    count = cursor.fetchone()[0]
    print(f"✅ Добавлено {count} связей учитель-ученик для teacher_id={teacher_id}")

    cursor.execute("""
        SELECT teacher_id, student_id, status
        FROM teacher_student_relationships
        WHERE teacher_id = ?
    """, (teacher_id,))

    print("=== Связи ===")
    for row in cursor.fetchall():
        print(f"   Teacher: {row[0]}, Student: {row[1]}, Status: {row[2]}")

    conn.close()

if __name__ == "__main__":
    add_test_data()
    print("✅ Тестовые данные добавлены!")
