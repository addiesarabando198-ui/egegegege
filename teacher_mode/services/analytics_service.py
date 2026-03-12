"""
Сервис для аналитики и рекомендаций.
"""

import logging
import aiosqlite
from typing import Dict, List, Any, Optional
from collections import defaultdict
from datetime import datetime

from core.db import get_db

logger = logging.getLogger(__name__)


def extract_topic_from_question_id(question_id: str) -> Optional[str]:
    """
    Извлекает тему из question_id.
    Примеры: 'task19_001' -> 'task19', 'test_part_12' -> 'test_part_12'
    """
    if '_' in question_id:
        # Для заданий типа task19_001, task20_005
        parts = question_id.split('_')
        if len(parts) >= 1:
            return parts[0]
    return question_id


async def analyze_student_performance(
    student_id: int,
    teacher_id: int
) -> Dict[str, Any]:
    """
    Анализирует успеваемость ученика по всем заданиям от учителя.

    Args:
        student_id: ID ученика
        teacher_id: ID учителя

    Returns:
        Словарь с аналитикой
    """
    try:
        db = await get_db()

        # Получаем все задания от этого учителя для этого ученика
        cursor = await db.execute("""
            SELECT
                hsa.homework_id,
                hsa.status as assignment_status,
                ha.title,
                ha.deadline
            FROM homework_student_assignments hsa
            JOIN homework_assignments ha ON hsa.homework_id = ha.id
            WHERE hsa.student_id = ? AND ha.teacher_id = ?
        """, (student_id, teacher_id))

        assignments = await cursor.fetchall()

        total_homeworks = len(assignments)
        completed_homeworks = sum(1 for a in assignments if a[1] == 'completed')
        in_progress = sum(1 for a in assignments if a[1] == 'in_progress')
        overdue = sum(1 for a in assignments if a[1] == 'overdue')
        assigned = sum(1 for a in assignments if a[1] == 'assigned')

        # Получаем прогресс по всем заданиям этого ученика
        cursor = await db.execute("""
            SELECT
                hp.question_id,
                hp.user_answer,
                hp.is_correct,
                hp.ai_feedback,
                hp.completed_at
            FROM homework_progress hp
            JOIN homework_assignments ha ON hp.homework_id = ha.id
            WHERE hp.student_id = ? AND ha.teacher_id = ?
        """, (student_id, teacher_id))

        progress_rows = await cursor.fetchall()

        if not progress_rows:
            return {
                'total_homeworks': total_homeworks,
                'completed_homeworks': completed_homeworks,
                'in_progress': in_progress,
                'overdue': overdue,
                'assigned': assigned,
                'overall_accuracy': 0.0,
                'total_questions': 0,
                'correct_count': 0,
                'topic_stats': {},
                'weak_topics': [],
                'strong_topics': [],
                'error_examples': [],
                'recommendations': ['Пока нет данных для анализа']
            }

        # Группируем по темам
        topic_data = defaultdict(lambda: {'correct': 0, 'total': 0, 'errors': []})

        total_correct = 0
        total_questions = len(progress_rows)

        for row in progress_rows:
            question_id = row[0]
            user_answer = row[1]
            is_correct = bool(row[2])
            ai_feedback = row[3]
            completed_at = row[4]

            topic = extract_topic_from_question_id(question_id)

            if topic:
                topic_data[topic]['total'] += 1
                if is_correct:
                    topic_data[topic]['correct'] += 1
                    total_correct += 1
                else:
                    # Сохраняем примеры ошибок
                    topic_data[topic]['errors'].append({
                        'question_id': question_id,
                        'user_answer': user_answer,
                        'ai_feedback': ai_feedback,
                        'completed_at': completed_at
                    })

        # Вычисляем процент по темам
        topic_stats = {}
        weak_topics = []
        strong_topics = []

        for topic, data in topic_data.items():
            accuracy = data['correct'] / data['total'] if data['total'] > 0 else 0
            topic_stats[topic] = {
                'correct': data['correct'],
                'total': data['total'],
                'accuracy': round(accuracy * 100, 1),
                'error_count': len(data['errors'])
            }

            if accuracy < 0.6:
                weak_topics.append({
                    'topic': topic,
                    'accuracy': round(accuracy * 100, 1),
                    'errors': data['errors'][:3]  # Берем первые 3 ошибки
                })
            elif accuracy >= 0.8:
                strong_topics.append({
                    'topic': topic,
                    'accuracy': round(accuracy * 100, 1)
                })

        # Формируем рекомендации
        recommendations = []
        if weak_topics:
            for wt in weak_topics[:3]:  # Топ-3 слабых тем
                recommendations.append(
                    f"Проработать тему {wt['topic']} (успеваемость {wt['accuracy']}%)"
                )
        else:
            recommendations.append("Отличная работа! Продолжайте в том же духе")

        overall_accuracy = total_correct / total_questions if total_questions > 0 else 0

        # Собираем примеры ошибок для детального анализа
        error_examples = []
        for topic, data in topic_data.items():
            if data['errors']:
                for error in data['errors'][:2]:  # По 2 примера на тему
                    error_examples.append({
                        'topic': topic,
                        'question_id': error['question_id'],
                        'user_answer': error['user_answer'],
                        'ai_feedback': error['ai_feedback']
                    })

        return {
            'total_homeworks': total_homeworks,
            'completed_homeworks': completed_homeworks,
            'in_progress': in_progress,
            'overdue': overdue,
            'assigned': assigned,
            'overall_accuracy': round(overall_accuracy * 100, 1),
            'total_questions': total_questions,
            'correct_count': total_correct,
            'topic_stats': topic_stats,
            'weak_topics': weak_topics,
            'strong_topics': strong_topics,
            'error_examples': error_examples,
            'recommendations': recommendations
        }

    except Exception as e:
        logger.error(f"Error analyzing student performance: {e}", exc_info=True)
        return {
            'total_homeworks': 0,
            'completed_homeworks': 0,
            'in_progress': 0,
            'overdue': 0,
            'assigned': 0,
            'overall_accuracy': 0.0,
            'total_questions': 0,
            'correct_count': 0,
            'topic_stats': {},
            'weak_topics': [],
            'strong_topics': [],
            'error_examples': [],
            'recommendations': ['Ошибка при получении данных']
        }


async def get_teacher_statistics(teacher_id: int) -> Dict[str, Any]:
    """
    Получает общую статистику для учителя.

    Args:
        teacher_id: ID учителя

    Returns:
        Словарь со статистикой
    """
    try:
        db = await get_db()

        # Получаем количество учеников
        cursor = await db.execute("""
            SELECT COUNT(*) FROM teacher_student_relationships
            WHERE teacher_id = ? AND status = 'active'
        """, (teacher_id,))
        row = await cursor.fetchone()
        total_students = row[0] if row else 0

        # Получаем статистику заданий
        cursor = await db.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as active
            FROM homework_assignments
            WHERE teacher_id = ?
        """, (teacher_id,))
        row = await cursor.fetchone()
        total_homeworks = row[0] if row else 0
        active_homeworks = row[1] if row and row[1] else 0

        # Получаем статистику выполнения
        cursor = await db.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN status = 'overdue' THEN 1 ELSE 0 END) as overdue
            FROM homework_student_assignments hsa
            JOIN homework_assignments ha ON hsa.homework_id = ha.id
            WHERE ha.teacher_id = ?
        """, (teacher_id,))
        row = await cursor.fetchone()
        total_assignments = row[0] if row else 0
        completed_assignments = row[1] if row and row[1] else 0
        overdue_assignments = row[2] if row and row[2] else 0

        average_completion_rate = (completed_assignments / total_assignments * 100) if total_assignments > 0 else 0

        # Получаем топ учеников по успеваемости
        cursor = await db.execute("""
            SELECT
                u.user_id,
                u.first_name || ' ' || COALESCE(u.last_name, '') as name,
                COUNT(CASE WHEN hp.is_correct = 1 THEN 1 END) * 100.0 / COUNT(*) as accuracy
            FROM users u
            JOIN teacher_student_relationships tsr ON u.user_id = tsr.student_id
            JOIN homework_progress hp ON u.user_id = hp.student_id
            JOIN homework_assignments ha ON hp.homework_id = ha.id
            WHERE tsr.teacher_id = ? AND ha.teacher_id = ? AND tsr.status = 'active'
            GROUP BY u.user_id, name
            HAVING COUNT(*) >= 5
            ORDER BY accuracy DESC
            LIMIT 5
        """, (teacher_id, teacher_id))

        top_students = []
        rows = await cursor.fetchall()
        for row in rows:
            top_students.append({
                'user_id': row[0],
                'name': row[1].strip(),
                'accuracy': round(row[2], 1)
            })

        return {
            'total_students': total_students,
            'active_homeworks': active_homeworks,
            'total_homeworks': total_homeworks,
            'completed_assignments': completed_assignments,
            'overdue_assignments': overdue_assignments,
            'average_completion_rate': round(average_completion_rate, 1),
            'top_students': top_students
        }

    except Exception as e:
        logger.error(f"Error getting teacher statistics: {e}", exc_info=True)
        return {
            'total_students': 0,
            'active_homeworks': 0,
            'total_homeworks': 0,
            'completed_assignments': 0,
            'overdue_assignments': 0,
            'average_completion_rate': 0.0,
            'top_students': []
        }


async def get_homework_statistics(homework_id: int) -> Dict[str, Any]:
    """
    Получает статистику по конкретному заданию.

    Args:
        homework_id: ID задания

    Returns:
        Словарь со статистикой
    """
    try:
        db = await get_db()

        # Получаем информацию о задании
        cursor = await db.execute("""
            SELECT title, description, deadline, assignment_type
            FROM homework_assignments
            WHERE id = ?
        """, (homework_id,))
        row = await cursor.fetchone()

        if not row:
            return {'error': 'Задание не найдено'}

        homework_title = row[0]

        # Статистика назначений
        cursor = await db.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END) as in_progress,
                SUM(CASE WHEN status = 'assigned' THEN 1 ELSE 0 END) as not_started,
                SUM(CASE WHEN status = 'overdue' THEN 1 ELSE 0 END) as overdue
            FROM homework_student_assignments
            WHERE homework_id = ?
        """, (homework_id,))
        row = await cursor.fetchone()

        total_assigned = row[0] if row else 0
        completed = row[1] if row and row[1] else 0
        in_progress = row[2] if row and row[2] else 0
        not_started = row[3] if row and row[3] else 0
        overdue = row[4] if row and row[4] else 0

        # Средний балл
        cursor = await db.execute("""
            SELECT
                hsa.student_id,
                u.first_name || ' ' || COALESCE(u.last_name, '') as name,
                COUNT(hp.id) as total_questions,
                SUM(CASE WHEN hp.is_correct = 1 THEN 1 ELSE 0 END) as correct_answers
            FROM homework_student_assignments hsa
            JOIN users u ON hsa.student_id = u.user_id
            LEFT JOIN homework_progress hp ON hsa.homework_id = hp.homework_id AND hsa.student_id = hp.student_id
            WHERE hsa.homework_id = ?
            GROUP BY hsa.student_id, name
        """, (homework_id,))

        student_results = []
        total_accuracy = 0
        students_with_results = 0

        rows = await cursor.fetchall()
        for row in rows:
            student_id = row[0]
            name = row[1].strip()
            total_questions = row[2]
            correct_answers = row[3] if row[3] else 0

            accuracy = (correct_answers / total_questions * 100) if total_questions > 0 else 0

            student_results.append({
                'student_id': student_id,
                'name': name,
                'correct_answers': correct_answers,
                'total_questions': total_questions,
                'accuracy': round(accuracy, 1)
            })

            if total_questions > 0:
                total_accuracy += accuracy
                students_with_results += 1

        average_score = (total_accuracy / students_with_results) if students_with_results > 0 else 0

        return {
            'homework_title': homework_title,
            'total_assigned': total_assigned,
            'completed': completed,
            'in_progress': in_progress,
            'not_started': not_started,
            'overdue': overdue,
            'average_score': round(average_score, 1),
            'student_results': student_results
        }

    except Exception as e:
        logger.error(f"Error getting homework statistics: {e}", exc_info=True)
        return {
            'total_assigned': 0,
            'completed': 0,
            'in_progress': 0,
            'not_started': 0,
            'overdue': 0,
            'average_score': 0.0,
            'student_results': []
        }


async def identify_weak_topics(student_id: int, teacher_id: int = None) -> List[Dict[str, Any]]:
    """
    Определяет слабые места ученика (темы с accuracy < 60%).

    Args:
        student_id: ID ученика
        teacher_id: ID учителя (опционально, для фильтрации по учителю)

    Returns:
        Список тем с низкой успеваемостью
    """
    try:
        db = await get_db()

        # Формируем запрос с учетом teacher_id
        if teacher_id:
            query = """
                SELECT
                    hp.question_id,
                    hp.is_correct
                FROM homework_progress hp
                JOIN homework_assignments ha ON hp.homework_id = ha.id
                WHERE hp.student_id = ? AND ha.teacher_id = ?
            """
            params = (student_id, teacher_id)
        else:
            query = """
                SELECT
                    question_id,
                    is_correct
                FROM homework_progress
                WHERE student_id = ?
            """
            params = (student_id,)

        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()

        if not rows:
            return []

        # Группируем по темам
        topic_data = defaultdict(lambda: {'correct': 0, 'total': 0})

        for row in rows:
            question_id = row[0]
            is_correct = bool(row[1])

            topic = extract_topic_from_question_id(question_id)

            if topic:
                topic_data[topic]['total'] += 1
                if is_correct:
                    topic_data[topic]['correct'] += 1

        # Определяем слабые темы (< 60%)
        weak_topics = []
        for topic, data in topic_data.items():
            accuracy = data['correct'] / data['total'] if data['total'] > 0 else 0

            if accuracy < 0.6:
                weak_topics.append({
                    'topic': topic,
                    'correct': data['correct'],
                    'total': data['total'],
                    'accuracy': round(accuracy * 100, 1)
                })

        # Сортируем по accuracy (самые слабые первые)
        weak_topics.sort(key=lambda x: x['accuracy'])

        return weak_topics

    except Exception as e:
        logger.error(f"Error identifying weak topics: {e}", exc_info=True)
        return []


async def analyze_group_performance(teacher_id: int) -> Dict[str, Any]:
    """
    Анализирует успеваемость всей группы учеников учителя.

    Args:
        teacher_id: ID учителя

    Returns:
        Словарь с групповой аналитикой
    """
    try:
        db = await get_db()

        # Получаем всех активных учеников
        cursor = await db.execute("""
            SELECT student_id
            FROM teacher_student_relationships
            WHERE teacher_id = ? AND status = 'active'
        """, (teacher_id,))

        student_ids = [row[0] for row in await cursor.fetchall()]

        if not student_ids:
            return {
                'total_students': 0,
                'group_accuracy': 0.0,
                'common_weak_topics': [],
                'topic_distribution': {},
                'students_summary': []
            }

        # Получаем прогресс по всем ученикам
        placeholders = ','.join('?' * len(student_ids))
        cursor = await db.execute(f"""
            SELECT
                hp.student_id,
                hp.question_id,
                hp.is_correct,
                u.first_name || ' ' || COALESCE(u.last_name, '') as name
            FROM homework_progress hp
            JOIN homework_assignments ha ON hp.homework_id = ha.id
            JOIN users u ON hp.student_id = u.user_id
            WHERE ha.teacher_id = ? AND hp.student_id IN ({placeholders})
        """, (teacher_id, *student_ids))

        rows = await cursor.fetchall()

        # Группируем по темам (для всей группы)
        topic_data = defaultdict(lambda: {'correct': 0, 'total': 0, 'students': set()})

        # Для каждого ученика
        student_data = defaultdict(lambda: {'correct': 0, 'total': 0, 'name': ''})

        for row in rows:
            student_id = row[0]
            question_id = row[1]
            is_correct = bool(row[2])
            name = row[3].strip()

            topic = extract_topic_from_question_id(question_id)

            # Обновляем данные по теме
            if topic:
                topic_data[topic]['total'] += 1
                topic_data[topic]['students'].add(student_id)
                if is_correct:
                    topic_data[topic]['correct'] += 1

            # Обновляем данные по ученику
            student_data[student_id]['name'] = name
            student_data[student_id]['total'] += 1
            if is_correct:
                student_data[student_id]['correct'] += 1

        # Вычисляем общие слабые темы (< 60% по всей группе)
        common_weak_topics = []
        topic_distribution = {}

        for topic, data in topic_data.items():
            accuracy = data['correct'] / data['total'] if data['total'] > 0 else 0

            topic_distribution[topic] = {
                'correct': data['correct'],
                'total': data['total'],
                'accuracy': round(accuracy * 100, 1),
                'students_count': len(data['students'])
            }

            if accuracy < 0.6:
                common_weak_topics.append({
                    'topic': topic,
                    'accuracy': round(accuracy * 100, 1),
                    'total_attempts': data['total'],
                    'students_affected': len(data['students'])
                })

        # Сортируем слабые темы по количеству затронутых учеников
        common_weak_topics.sort(key=lambda x: x['students_affected'], reverse=True)

        # Формируем краткую сводку по ученикам
        students_summary = []
        for student_id, data in student_data.items():
            accuracy = data['correct'] / data['total'] if data['total'] > 0 else 0
            students_summary.append({
                'student_id': student_id,
                'name': data['name'],
                'accuracy': round(accuracy * 100, 1),
                'total_questions': data['total']
            })

        # Сортируем учеников по успеваемости
        students_summary.sort(key=lambda x: x['accuracy'], reverse=True)

        # Общая успеваемость группы
        total_correct = sum(d['correct'] for d in student_data.values())
        total_questions = sum(d['total'] for d in student_data.values())
        group_accuracy = (total_correct / total_questions * 100) if total_questions > 0 else 0

        return {
            'total_students': len(student_ids),
            'group_accuracy': round(group_accuracy, 1),
            'total_questions': total_questions,
            'total_correct': total_correct,
            'common_weak_topics': common_weak_topics,
            'topic_distribution': topic_distribution,
            'students_summary': students_summary
        }

    except Exception as e:
        logger.error(f"Error analyzing group performance: {e}", exc_info=True)
        return {
            'total_students': 0,
            'group_accuracy': 0.0,
            'common_weak_topics': [],
            'topic_distribution': {},
            'students_summary': []
        }
