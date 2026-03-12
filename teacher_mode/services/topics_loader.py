"""
Загрузчик тем из банка заданий для создания домашних заданий.
"""

import json
import os
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def load_topics_for_module(task_module: str) -> Dict:
    """
    Загружает темы для указанного модуля задания.

    Args:
        task_module: Название модуля ('test_part', 'task19', 'task20', 'task21',
                     'task22', 'task23', 'task24', 'task25')

    Returns:
        Словарь с темами в формате:
        {
            'blocks': {
                'Блок 1': [{'id': 1, 'title': 'Тема 1'}, ...],
                'Блок 2': [...],
                ...
            },
            'topics_by_id': {1: {...}, 2: {...}, ...},
            'total_count': 120
        }
    """
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

        # Специальная обработка для test_part
        if task_module == 'test_part':
            return _load_test_part_topics(base_dir)

        # Специальная обработка для task17/task18 (общие текстовые отрывки)
        if task_module in ('task17', 'task18'):
            return _load_task17_18_topics(base_dir, task_module)

        # Специальная обработка для task21
        if task_module == 'task21':
            return _load_task21_topics(base_dir)

        # Специальная обработка для task22
        if task_module == 'task22':
            return _load_task22_topics(base_dir)

        # Специальная обработка для task23
        if task_module == 'task23':
            return _load_task23_topics(base_dir)

        # Специальная обработка для task24
        if task_module == 'task24':
            return _load_task24_plans(base_dir)

        # Обработка для остальных модулей (task19, task20, task25)
        topics_file = os.path.join(base_dir, task_module, f"{task_module}_topics.json")

        if not os.path.exists(topics_file):
            logger.info(f"Topics file not found for {task_module}: {topics_file}")
            return {'blocks': {}, 'topics_by_id': {}, 'total_count': 0}

        with open(topics_file, 'r', encoding='utf-8') as f:
            raw_topics = json.load(f)

        # Обрабатываем темы
        blocks = {}
        topics_by_id = {}

        for topic in raw_topics:
            topic_id = topic.get('id')
            block_name = topic.get('block', 'Без категории')

            # Добавляем в словарь по ID
            topics_by_id[topic_id] = topic

            # Добавляем в блок
            if block_name not in blocks:
                blocks[block_name] = []

            blocks[block_name].append({
                'id': topic_id,
                'title': topic.get('title', f'Тема {topic_id}')
            })

        return {
            'blocks': blocks,
            'topics_by_id': topics_by_id,
            'total_count': len(raw_topics)
        }

    except Exception as e:
        logger.error(f"Error loading topics for {task_module}: {e}")
        return {'blocks': {}, 'topics_by_id': {}, 'total_count': 0}


def _load_test_part_topics(base_dir: str) -> Dict:
    """
    Загружает темы для тестовой части (задания 1-16) из questions.json.

    Структура:
    - Блоки: Политика, Право, Экономика, Человек и общество, Социология
    - Темы: 2.1, 4.1 и т.д. (темы кодификатора)
    - Можно фильтровать по exam_number (1-16)

    Args:
        base_dir: Базовая директория проекта

    Returns:
        Словарь в формате:
        {
            'blocks': {
                'Политика': [
                    {'id': 1, 'title': '4.1 Политическая власть', 'topic': '4.1', 'exam_numbers': [5, 10], 'questions_count': 25},
                    {'id': 2, 'title': '4.2 Политическая система', 'topic': '4.2', 'exam_numbers': [5], 'questions_count': 15},
                    ...
                ],
                'Право': [...]
            },
            'topics_by_id': {
                1: {'id': 1, 'block': 'Политика', 'topic': '4.1', 'title': '4.1 Политическая власть',
                    'exam_numbers': [5, 10], 'question_ids': ['q1', 'q2'], 'questions_count': 25},
                ...
            },
            'total_count': 1500
        }
    """
    try:
        # Пытаемся импортировать напрямую
        try:
            from test_part.loader import get_questions_data, load_questions
            from test_part.topic_data import TOPIC_NAMES
        except ImportError:
            # Если не получилось - добавляем в sys.path
            import sys
            test_part_dir = os.path.join(base_dir, 'test_part')
            if test_part_dir not in sys.path:
                sys.path.insert(0, test_part_dir)
                logger.info(f"Added {test_part_dir} to sys.path for test_part import")

            from test_part.loader import get_questions_data, load_questions
            from test_part.topic_data import TOPIC_NAMES

        # Получаем данные вопросов (структурированные по блокам и темам)
        questions_data = get_questions_data()

        # Если вопросы не загружены, пытаемся загрузить
        if not questions_data:
            logger.warning("test_part questions not initialized, attempting to load...")
            try:
                load_questions()
                questions_data = get_questions_data()
            except Exception as load_error:
                logger.error(f"Failed to load test_part questions: {load_error}")

        if not questions_data:
            logger.warning("No questions available for test_part after load attempt")
            return {'blocks': {}, 'topics_by_id': {}, 'total_count': 0}

        # Структуры для хранения результата
        blocks = {}
        topics_by_id = {}
        topic_id_counter = 1
        total_count = 0

        # Обрабатываем каждый блок (Политика, Право, Экономика и т.д.)
        for block_name, topics_dict in questions_data.items():
            blocks[block_name] = []

            # Обрабатываем каждую тему в блоке (4.1, 4.2 и т.д.)
            for topic_code, topic_questions in topics_dict.items():
                # Фильтруем только вопросы тестовой части (exam_number 1-16)
                test_part_questions = [
                    q for q in topic_questions
                    if q.get('exam_number') and 1 <= q.get('exam_number') <= 16
                ]

                # Пропускаем темы без вопросов тестовой части
                if not test_part_questions:
                    continue

                # Собираем уникальные номера заданий ЕГЭ для этой темы
                exam_numbers = sorted(list(set(
                    q.get('exam_number') for q in test_part_questions
                    if q.get('exam_number')
                )))

                # Получаем читаемое название темы
                topic_title = TOPIC_NAMES.get(topic_code, topic_code)
                full_title = f"{topic_code} {topic_title}"

                # Создаем объект темы
                topic_obj = {
                    'id': topic_id_counter,
                    'block': block_name,
                    'topic': topic_code,
                    'title': full_title,
                    'exam_numbers': exam_numbers,
                    'question_ids': [q['id'] for q in test_part_questions],
                    'questions_count': len(test_part_questions)
                }

                topics_by_id[topic_id_counter] = topic_obj

                # Добавляем в блок
                blocks[block_name].append({
                    'id': topic_id_counter,
                    'title': f"{full_title} ({len(test_part_questions)} вопр.)",
                    'topic': topic_code,
                    'exam_numbers': exam_numbers,
                    'questions_count': len(test_part_questions)
                })

                total_count += len(test_part_questions)
                topic_id_counter += 1

        logger.info(f"Loaded test_part topics: {len(blocks)} blocks, {len(topics_by_id)} topics, {total_count} questions")

        return {
            'blocks': blocks,
            'topics_by_id': topics_by_id,
            'total_count': total_count
        }

    except Exception as e:
        logger.error(f"Error loading test_part topics: {e}")
        import traceback
        traceback.print_exc()
        return {'blocks': {}, 'topics_by_id': {}, 'total_count': 0}


def _load_task17_18_topics(base_dir: str, task_module: str) -> Dict:
    """
    Загружает текстовые отрывки для task17/task18 из text_passages_17_18.json.

    Args:
        base_dir: Базовая директория проекта
        task_module: 'task17' или 'task18'

    Returns:
        Словарь в формате, совместимом с load_topics_for_module
    """
    try:
        passages_file = os.path.join(base_dir, 'data', 'text_passages_17_18.json')

        if not os.path.exists(passages_file):
            logger.info(f"Passages file not found for {task_module}: {passages_file}")
            return {'blocks': {}, 'topics_by_id': {}, 'total_count': 0}

        with open(passages_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        passages = data.get('passages', [])
        blocks = {}
        topics_by_id = {}

        # Определяем ключ задания ('task17' или 'task18')
        task_key = task_module

        for passage in passages:
            passage_id = passage.get('id')
            if not passage_id or task_key not in passage:
                continue

            block_name = passage.get('block', 'Без категории')
            source = passage.get('source', f'Текст {passage_id}')
            task_data = passage[task_key]

            if task_module == 'task17':
                title = f"Текст: {source}"
            else:
                concept = task_data.get('concept', source)
                title = f"Понятие: {concept}"

            topic_obj = {
                'id': passage_id,
                'title': title,
                'block': block_name,
                'text': passage.get('text', ''),
                'source': source,
                'passage_id': passage_id,
                **task_data,
            }

            topics_by_id[passage_id] = topic_obj

            if block_name not in blocks:
                blocks[block_name] = []
            blocks[block_name].append({
                'id': passage_id,
                'title': title
            })

        logger.info(f"Loaded {task_module} topics: {len(topics_by_id)} passages")

        return {
            'blocks': blocks,
            'topics_by_id': topics_by_id,
            'total_count': len(topics_by_id)
        }

    except Exception as e:
        logger.error(f"Error loading {task_module} topics: {e}")
        return {'blocks': {}, 'topics_by_id': {}, 'total_count': 0}


def _load_task21_topics(base_dir: str) -> Dict:
    """
    Загружает задания для task21 (Графики спроса и предложения).

    Args:
        base_dir: Базовая директория проекта

    Returns:
        Словарь в формате, совместимом с load_topics_for_module
    """
    try:
        questions_file = os.path.join(base_dir, 'task21', 'task21_questions.json')

        if not os.path.exists(questions_file):
            logger.info(f"Questions file not found for task21: {questions_file}")
            return {'blocks': {}, 'topics_by_id': {}, 'total_count': 0}

        with open(questions_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        tasks = data.get('tasks', [])
        blocks = {'Графики': []}
        topics_by_id = {}

        for task in tasks:
            task_id = task.get('id')
            market_name = task.get('market_name', f'Рынок {task_id}')

            topic_obj = {
                'id': task_id,
                'title': f"Рынок {market_name}",
                'block': 'Графики',
                'market_name': market_name,
                'question_1': task.get('question_1', {}),
                'question_2': task.get('question_2', {}),
                'question_3': task.get('question_3', {}),
            }

            topics_by_id[task_id] = topic_obj
            blocks['Графики'].append({
                'id': task_id,
                'title': f"Рынок {market_name}"
            })

        logger.info(f"Loaded task21 topics: {len(topics_by_id)} tasks")

        return {
            'blocks': blocks,
            'topics_by_id': topics_by_id,
            'total_count': len(topics_by_id)
        }

    except Exception as e:
        logger.error(f"Error loading task21 topics: {e}")
        return {'blocks': {}, 'topics_by_id': {}, 'total_count': 0}


def _load_task22_topics(base_dir: str) -> Dict:
    """
    Загружает задания для task22 (Анализ ситуаций).

    Args:
        base_dir: Базовая директория проекта

    Returns:
        Словарь в формате, совместимом с load_topics_for_module
    """
    try:
        topics_file = os.path.join(base_dir, 'task22', 'task22_topics.json')

        if not os.path.exists(topics_file):
            logger.info(f"Topics file not found for task22: {topics_file}")
            return {'blocks': {}, 'topics_by_id': {}, 'total_count': 0}

        with open(topics_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        tasks = data.get('tasks', [])
        blocks = {'Анализ ситуаций': []}
        topics_by_id = {}

        for task in tasks:
            task_id = task.get('id')
            description = task.get('description', '')
            # Берем первые 60 символов для названия
            title = description[:60] + '...' if len(description) > 60 else description

            topic_obj = {
                'id': task_id,
                'title': title,
                'block': 'Анализ ситуаций',
                'description': description,
                'questions': task.get('questions', []),
                'correct_answers': task.get('correct_answers', []),
                'answer_requirements': task.get('answer_requirements', []),
                'connected_questions': task.get('connected_questions', []),
            }

            topics_by_id[task_id] = topic_obj
            blocks['Анализ ситуаций'].append({
                'id': task_id,
                'title': f"Задание {task_id}: {title}"
            })

        logger.info(f"Loaded task22 topics: {len(topics_by_id)} tasks")

        return {
            'blocks': blocks,
            'topics_by_id': topics_by_id,
            'total_count': len(topics_by_id)
        }

    except Exception as e:
        logger.error(f"Error loading task22 topics: {e}")
        return {'blocks': {}, 'topics_by_id': {}, 'total_count': 0}


def _load_task23_topics(base_dir: str) -> Dict:
    """
    Загружает задания для task23 (Конституция РФ).

    Args:
        base_dir: Базовая директория проекта

    Returns:
        Словарь в формате, совместимом с load_topics_for_module
    """
    try:
        questions_file = os.path.join(base_dir, 'data', 'task23_questions.json')

        if not os.path.exists(questions_file):
            logger.info(f"Questions file not found for task23: {questions_file}")
            return {'blocks': {}, 'topics_by_id': {}, 'total_count': 0}

        with open(questions_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        questions = data.get('questions', [])
        blocks = {'Конституция РФ': []}
        topics_by_id = {}

        for question in questions:
            q_id = question.get('id')
            model_type = question.get('model_type', 1)
            characteristics = question.get('characteristics', [])

            # Формируем название из первой характеристики
            if characteristics:
                first_char = characteristics[0]
                title = first_char[:50] + '...' if len(first_char) > 50 else first_char
            else:
                title = f"Вопрос {q_id}"

            topic_obj = {
                'id': q_id,
                'title': title,
                'block': 'Конституция РФ',
                'model_type': model_type,
                'characteristics': characteristics,
                'model_answers': question.get('model_answers', {}),
            }

            topics_by_id[q_id] = topic_obj
            blocks['Конституция РФ'].append({
                'id': q_id,
                'title': f"Вопрос {q_id}: {title}"
            })

        logger.info(f"Loaded task23 topics: {len(topics_by_id)} questions")

        return {
            'blocks': blocks,
            'topics_by_id': topics_by_id,
            'total_count': len(topics_by_id)
        }

    except Exception as e:
        logger.error(f"Error loading task23 topics: {e}")
        return {'blocks': {}, 'topics_by_id': {}, 'total_count': 0}


def _load_task24_plans(base_dir: str) -> Dict:
    """
    Загружает планы для task24 из plans_data_with_blocks.json.

    Args:
        base_dir: Базовая директория проекта

    Returns:
        Словарь в формате, совместимом с load_topics_for_module
    """
    try:
        plans_file = os.path.join(base_dir, 'data', 'plans_data_with_blocks.json')

        if not os.path.exists(plans_file):
            logger.info(f"Plans file not found for task24: {plans_file}")
            return {'blocks': {}, 'topics_by_id': {}, 'total_count': 0}

        with open(plans_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        blocks = {}
        topics_by_id = {}
        topic_id_counter = 1

        # Создаем маппинг названия темы -> ID
        topic_name_to_id = {}

        # Обрабатываем блоки
        for block_name, topic_names in data.get('blocks', {}).items():
            blocks[block_name] = []

            for topic_name in topic_names:
                # Присваиваем ID теме
                if topic_name not in topic_name_to_id:
                    topic_name_to_id[topic_name] = topic_id_counter
                    topic_id_counter += 1

                topic_id = topic_name_to_id[topic_name]

                # Получаем данные плана из раздела plans
                plan_data = data.get('plans', {}).get(topic_name, {})

                # Создаем объект темы
                topic_obj = {
                    'id': topic_id,
                    'title': topic_name,
                    'block': block_name,
                    'plan_data': plan_data  # Сохраняем полные данные плана
                }

                topics_by_id[topic_id] = topic_obj

                blocks[block_name].append({
                    'id': topic_id,
                    'title': topic_name
                })

        return {
            'blocks': blocks,
            'topics_by_id': topics_by_id,
            'total_count': len(topics_by_id)
        }

    except Exception as e:
        logger.error(f"Error loading task24 plans: {e}")
        return {'blocks': {}, 'topics_by_id': {}, 'total_count': 0}


def get_blocks_list(task_module: str) -> List[str]:
    """
    Получает список названий блоков для модуля.

    Args:
        task_module: Название модуля ('task19', 'task20', 'task24', 'task25')

    Returns:
        Список названий блоков
    """
    data = load_topics_for_module(task_module)
    return list(data['blocks'].keys())


def get_topics_in_block(task_module: str, block_name: str) -> List[Dict]:
    """
    Получает список тем в указанном блоке.

    Args:
        task_module: Название модуля
        block_name: Название блока

    Returns:
        Список тем в формате [{'id': 1, 'title': 'Тема'}, ...]
    """
    data = load_topics_for_module(task_module)
    return data['blocks'].get(block_name, [])


def get_topic_by_id(task_module: str, topic_id: int) -> Optional[Dict]:
    """
    Получает тему по её ID.

    Args:
        task_module: Название модуля
        topic_id: ID темы

    Returns:
        Словарь с данными темы или None
    """
    data = load_topics_for_module(task_module)
    return data['topics_by_id'].get(topic_id)


def get_topic_ids_by_blocks(task_module: str, block_names: List[str]) -> List[int]:
    """
    Получает список ID тем для указанных блоков.

    Args:
        task_module: Название модуля
        block_names: Список названий блоков

    Returns:
        Список ID тем
    """
    data = load_topics_for_module(task_module)
    topic_ids = []

    for block_name in block_names:
        topics = data['blocks'].get(block_name, [])
        topic_ids.extend([t['id'] for t in topics])

    return topic_ids


def module_supports_topics(task_module: str) -> bool:
    """
    Проверяет, поддерживает ли модуль систему тем.

    Args:
        task_module: Название модуля ('test_part', 'task19', 'task20', 'task21',
                     'task22', 'task23', 'task24', 'task25')

    Returns:
        True если модуль имеет файл с темами
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

    # test_part поддерживает темы через questions.json
    if task_module == 'test_part':
        questions_file = os.path.join(base_dir, 'data', 'questions.json')
        return os.path.exists(questions_file)

    # Специальная проверка для task17/task18 (общий файл)
    if task_module in ('task17', 'task18'):
        passages_file = os.path.join(base_dir, 'data', 'text_passages_17_18.json')
        return os.path.exists(passages_file)

    # Специальная проверка для task21
    if task_module == 'task21':
        questions_file = os.path.join(base_dir, 'task21', 'task21_questions.json')
        return os.path.exists(questions_file)

    # Специальная проверка для task22
    if task_module == 'task22':
        topics_file = os.path.join(base_dir, 'task22', 'task22_topics.json')
        return os.path.exists(topics_file)

    # Специальная проверка для task23
    if task_module == 'task23':
        questions_file = os.path.join(base_dir, 'data', 'task23_questions.json')
        return os.path.exists(questions_file)

    # Специальная проверка для task24
    if task_module == 'task24':
        plans_file = os.path.join(base_dir, 'data', 'plans_data_with_blocks.json')
        return os.path.exists(plans_file)

    # Проверка для остальных модулей
    topics_file = os.path.join(base_dir, task_module, f"{task_module}_topics.json")
    return os.path.exists(topics_file)
