"""
Загрузчик конкретных вопросов из модулей для выполнения домашних заданий.
"""

import json
import os
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


def load_question_by_id(task_module: str, question_id) -> Optional[Dict]:
    """
    Загружает конкретный вопрос по ID из указанного модуля.

    Args:
        task_module: Название модуля ('test_part', 'task19', 'task20', 'task21',
                     'task22', 'task23', 'task24', 'task25')
        question_id: ID вопроса (может быть строкой для test_part или числом для остальных)

    Returns:
        Словарь с данными вопроса или None если не найден
    """
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

        # Специальная обработка для test_part
        if task_module == 'test_part':
            return _load_test_part_question(question_id, base_dir)

        # Специальная обработка для task24
        if task_module == 'task24':
            return _load_task24_question(question_id, base_dir)

        # Специальная обработка для task21 (task21_questions.json, формат {"tasks": [...]})
        if task_module == 'task21':
            return _load_task21_question(question_id, base_dir)

        # Специальная обработка для task22 (task22_topics.json, формат {"tasks": [...]})
        if task_module == 'task22':
            return _load_task22_question(question_id, base_dir)

        # Специальная обработка для task23 (data/task23_questions.json)
        if task_module == 'task23':
            return _load_task23_question(question_id, base_dir)

        # Обработка для остальных модулей (task19, task20, task25 — формат [список тем])
        topics_file = os.path.join(base_dir, task_module, f"{task_module}_topics.json")

        if not os.path.exists(topics_file):
            logger.warning(f"Topics file not found: {topics_file}")
            return None

        with open(topics_file, 'r', encoding='utf-8') as f:
            topics = json.load(f)

        # Ищем вопрос по ID
        for topic in topics:
            if topic.get('id') == question_id:
                return topic

        logger.warning(f"Question {question_id} not found in {task_module}")
        return None

    except Exception as e:
        logger.error(f"Error loading question {question_id} from {task_module}: {e}")
        return None


def _load_task21_question(question_id, base_dir: str) -> Optional[Dict]:
    """
    Загружает вопрос task21 из task21_questions.json.

    Args:
        question_id: ID задания (строка вида "task21_003" или число)
        base_dir: Базовая директория проекта

    Returns:
        Словарь с данными вопроса или None
    """
    try:
        questions_file = os.path.join(base_dir, 'task21', 'task21_questions.json')

        if not os.path.exists(questions_file):
            logger.warning(f"Task21 questions file not found: {questions_file}")
            return None

        with open(questions_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        tasks = data.get('tasks', [])
        for task in tasks:
            if task.get('id') == question_id:
                return task

        logger.warning(f"Question {question_id} not found in task21")
        return None

    except Exception as e:
        logger.error(f"Error loading task21 question {question_id}: {e}")
        return None


def _load_task22_question(question_id, base_dir: str) -> Optional[Dict]:
    """
    Загружает вопрос task22 из task22_topics.json.

    Args:
        question_id: ID задания (число)
        base_dir: Базовая директория проекта

    Returns:
        Словарь с данными вопроса или None
    """
    try:
        topics_file = os.path.join(base_dir, 'task22', 'task22_topics.json')

        if not os.path.exists(topics_file):
            logger.warning(f"Task22 topics file not found: {topics_file}")
            return None

        with open(topics_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        tasks = data.get('tasks', [])
        for task in tasks:
            if task.get('id') == question_id:
                return task

        logger.warning(f"Question {question_id} not found in task22")
        return None

    except Exception as e:
        logger.error(f"Error loading task22 question {question_id}: {e}")
        return None


def _load_task23_question(question_id, base_dir: str) -> Optional[Dict]:
    """
    Загружает вопрос task23 из data/task23_questions.json.

    Args:
        question_id: ID вопроса (число)
        base_dir: Базовая директория проекта

    Returns:
        Словарь с данными вопроса или None
    """
    try:
        questions_file = os.path.join(base_dir, 'data', 'task23_questions.json')

        if not os.path.exists(questions_file):
            logger.warning(f"Task23 questions file not found: {questions_file}")
            return None

        with open(questions_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        questions = data.get('questions', [])
        for question in questions:
            if question.get('id') == question_id:
                return question

        logger.warning(f"Question {question_id} not found in task23")
        return None

    except Exception as e:
        logger.error(f"Error loading task23 question {question_id}: {e}")
        return None


def _load_task24_question(question_id: int, base_dir: str) -> Optional[Dict]:
    """
    Загружает вопрос task24 из plans_data_with_blocks.json.

    Args:
        question_id: ID темы
        base_dir: Базовая директория проекта

    Returns:
        Словарь с данными плана или None
    """
    try:
        plans_file = os.path.join(base_dir, 'data', 'plans_data_with_blocks.json')

        if not os.path.exists(plans_file):
            logger.warning(f"Plans file not found: {plans_file}")
            return None

        with open(plans_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Создаем маппинг ID -> название темы (как в topics_loader)
        topic_id_to_name = {}
        topic_id_counter = 1

        for block_name, topic_names in data.get('blocks', {}).items():
            for topic_name in topic_names:
                topic_id_to_name[topic_id_counter] = topic_name
                topic_id_counter += 1

        # Получаем название темы по ID
        topic_name = topic_id_to_name.get(question_id)
        if not topic_name:
            logger.warning(f"Topic ID {question_id} not found in task24")
            return None

        # Получаем данные плана
        plan_data = data.get('plans', {}).get(topic_name)
        if not plan_data:
            logger.warning(f"Plan data not found for topic: {topic_name}")
            return None

        # Формируем объект вопроса
        return {
            'id': question_id,
            'title': topic_name,
            'block': plan_data.get('block', 'Без категории'),
            'full_plan': plan_data.get('full_plan'),
            'points_data': plan_data.get('points_data'),
            'min_points': plan_data.get('min_points'),
            'min_detailed_points': plan_data.get('min_detailed_points'),
            'min_subpoints': plan_data.get('min_subpoints')
        }

    except Exception as e:
        logger.error(f"Error loading task24 question {question_id}: {e}")
        return None


def _load_test_part_question(question_id: str, base_dir: str) -> Optional[Dict]:
    """
    Загружает вопрос test_part из questions.json через модуль test_part.loader.

    Args:
        question_id: ID вопроса (строка, например "ekonomika_2_1_q1")
        base_dir: Базовая директория проекта

    Returns:
        Словарь с данными вопроса или None
    """
    try:
        # Импортируем функции из test_part
        try:
            from test_part.loader import get_questions_dict_flat, load_questions
        except ImportError:
            # Добавляем в sys.path если не получилось импортировать
            import sys
            test_part_dir = os.path.join(base_dir, 'test_part')
            if test_part_dir not in sys.path:
                sys.path.insert(0, test_part_dir)
            from test_part.loader import get_questions_dict_flat, load_questions

        # Получаем словарь вопросов
        questions_dict = get_questions_dict_flat()

        # Если вопросы не загружены, пытаемся загрузить
        if not questions_dict:
            logger.warning("test_part questions not initialized, attempting to load...")
            load_questions()
            questions_dict = get_questions_dict_flat()

        if not questions_dict:
            logger.warning("No questions available for test_part after load attempt")
            return None

        # Получаем вопрос по ID
        question = questions_dict.get(question_id)

        if not question:
            logger.warning(f"Question {question_id} not found in test_part")
            return None

        return question

    except Exception as e:
        logger.error(f"Error loading test_part question {question_id}: {e}")
        import traceback
        traceback.print_exc()
        return None


def format_question_for_display(task_module: str, question_data: Dict) -> str:
    """
    Форматирует вопрос для отображения ученику.

    Args:
        task_module: Название модуля
        question_data: Данные вопроса из load_question_by_id

    Returns:
        Отформатированный текст вопроса
    """
    if task_module == 'test_part':
        # Используем функцию форматирования из модуля test_part
        try:
            from test_part.utils import format_question_text
            return format_question_text(question_data)
        except ImportError:
            logger.warning("Could not import format_question_text from test_part")
            # Простое форматирование как fallback
            return f"<b>Вопрос #{question_data.get('exam_number', '?')}</b>\n\n{question_data.get('question', str(question_data))}"

    elif task_module == 'task19':
        return f"<b>{question_data['title']}</b>\n\n{question_data['task_text']}"

    elif task_module == 'task20':
        return f"<b>{question_data['title']}</b>\n\n{question_data['task_text']}"

    elif task_module == 'task21':
        market = question_data.get('market_name', '')
        text = f"<b>📊 Задание 21 — Рынок {market}</b>\n\n"
        text += f"{question_data.get('graph_description', '')}\n"
        notation = question_data.get('graph_notation', '')
        if notation:
            text += f"{notation}\n"
        text += "\n<b>Вопросы:</b>\n\n"
        q1 = question_data.get('question_1', {})
        q2 = question_data.get('question_2', {})
        q3 = question_data.get('question_3', {})
        text += f"<b>1.</b> {q1.get('text', '')}\n\n"
        text += f"<b>2.</b> {q2.get('text', '')}\n\n"
        text += f"<b>3.</b> {q3.get('text', '')}"
        return text

    elif task_module == 'task22':
        text = f"<b>Задание 22</b>\n\n"
        text += f"{question_data.get('description', '')}\n\n"
        questions = question_data.get('questions', [])
        for i, q in enumerate(questions, 1):
            text += f"{i}. {q}\n"
        return text

    elif task_module == 'task23':
        model_type = question_data.get('model_type', 1)
        characteristics = question_data.get('characteristics', [])
        text = f"<b>Задание 23 — Конституция РФ</b>\n\n"
        if model_type == 1 and characteristics:
            text += f"Характеристика: <i>{characteristics[0]}</i>\n\n"
            text += "Приведите три объяснения (подтверждения) данной характеристики."
        elif model_type == 2:
            text += "Приведите по одному подтверждению каждой характеристики:\n\n"
            for i, char in enumerate(characteristics, 1):
                text += f"{i}. {char}\n"
        return text

    elif task_module == 'task24':
        text = f"<b>{question_data['title']}</b>\n\n"
        text += "Составьте детализированный план по данной теме.\n\n"
        text += f"<b>Требования:</b>\n"
        text += f"• Минимум {question_data.get('min_points', 3)} пунктов\n"
        text += f"• Минимум {question_data.get('min_detailed_points', 2)} детализированных пунктов\n"
        text += f"• Минимум {question_data.get('min_subpoints', 3)} подпунктов в детализированных пунктах"
        return text

    elif task_module == 'task25':
        parts = question_data.get('parts', {})
        text = f"<b>{question_data['title']}</b>\n\n"
        text += f"<b>Часть 1:</b>\n{parts.get('part1', '')}\n\n"
        text += f"<b>Часть 2:</b>\n{parts.get('part2', '')}\n\n"
        text += f"<b>Часть 3:</b>\n{parts.get('part3', '')}"
        return text

    return str(question_data)
