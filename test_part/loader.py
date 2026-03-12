import json
import logging
import os
from typing import Dict, List, Optional, Any, Tuple
# Импортируем кеш из того же пакета
try:
    from .cache import questions_cache
except ImportError:
    logging.warning("Модуль cache не найден, работаем без кеширования")
    questions_cache = None

# --- Логирование ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Константы ---
QUESTIONS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), 
    "data", 
    "questions.json"
)
# --- Глобальные переменные ---
QUESTIONS_DATA: Optional[Dict[str, Dict[str, List[Dict[str, Any]]]]] = None
QUESTIONS_LIST_FLAT: Optional[List[Dict[str, Any]]] = None
QUESTIONS_DICT_FLAT: Optional[Dict[str, Dict[str, Any]]] = None
AVAILABLE_BLOCKS: Optional[List[str]] = None

def validate_question(question: dict) -> Tuple[bool, str]:
    """
    Валидация структуры вопроса.
    
    Returns:
        Tuple[bool, str]: (is_valid, error_message)
    """
    if not isinstance(question, dict):
        return False, "Question is not a dictionary"
    
    # Проверяем базовые поля
    required_fields = ['id', 'block', 'topic', 'answer', 'type']
    missing_fields = [field for field in required_fields if not question.get(field)]
    
    if missing_fields:
        return False, f"Missing required fields: {missing_fields}"
    
    # Проверяем ID на уникальность (будет проверено в load_questions)
    question_id = question.get('id')
    if not isinstance(question_id, str) or not question_id.strip():
        return False, "ID must be a non-empty string"
    
    # Проверяем тип вопроса
    question_type = question.get('type')
    valid_types = ['single_choice', 'multiple_choice', 'matching', 'sequence', 'text_input']
    
    if question_type not in valid_types:
        return False, f"Invalid question type: {question_type}. Must be one of {valid_types}"
    
    # Валидация по типу вопроса
    if question_type == 'matching':
        required_matching_fields = ['instruction', 'column1_options', 'column2_options']
        missing_matching = [field for field in required_matching_fields if not question.get(field)]
        
        if missing_matching:
            return False, f"Matching question missing fields: {missing_matching}"
        
        # Проверяем, что опции - это словари
        col1_options = question.get('column1_options')
        col2_options = question.get('column2_options')
        
        if not isinstance(col1_options, dict) or not isinstance(col2_options, dict):
            return False, "Column options must be dictionaries"
        
        if not col1_options or not col2_options:
            return False, "Column options cannot be empty"
        
        # Проверяем согласованность ответа с опциями
        answer = str(question.get('answer', ''))
        if len(answer) != len(col1_options):
            return False, f"Answer length ({len(answer)}) doesn't match column1 options count ({len(col1_options)})"
    
    elif question_type in ['single_choice', 'multiple_choice', 'sequence']:
        if not question.get('question'):
            return False, f"{question_type} question missing 'question' field"
        
        # Для single_choice проверяем, что ответ - одна цифра
        if question_type == 'single_choice':
            answer = str(question.get('answer', ''))
            if not answer.isdigit() or len(answer) != 1:
                return False, "Single choice answer must be a single digit"
    
    elif question_type == 'text_input':
        if not question.get('question'):
            return False, "Text input question missing 'question' field"
    
    # Проверяем номер ЕГЭ (если есть)
    exam_number = question.get('exam_number')
    if exam_number is not None:
        if not isinstance(exam_number, int) or not (1 <= exam_number <= 27):
            return False, f"Invalid exam_number: {exam_number}. Must be integer between 1 and 27"
    
    # Проверяем пояснение (если есть)
    explanation = question.get('explanation')
    if explanation is not None and not isinstance(explanation, str):
        return False, "Explanation must be a string"
    
    return True, ""

def load_questions() -> Tuple[Optional[Dict[str, Dict[str, List[Dict[str, Any]]]]], Optional[List[Dict[str, Any]]]]:
    """
    Загрузка и валидация вопросов с улучшенной обработкой ошибок.
    
    Returns:
        Tuple: (questions_data, questions_list_flat)
    """
    global QUESTIONS_DATA, QUESTIONS_LIST_FLAT, QUESTIONS_DICT_FLAT, AVAILABLE_BLOCKS
    
    # Проверяем существование файла
    if not os.path.exists(QUESTIONS_FILE):
        logger.error(f"Файл с вопросами '{QUESTIONS_FILE}' не найден.")
        return _init_empty_data()

    # Загружаем JSON
    try:
        with open(QUESTIONS_FILE, "r", encoding="utf-8") as f:
            questions_list_raw = json.load(f)
    except json.JSONDecodeError as e:
        logger.critical(f"Ошибка декодирования JSON в файле '{QUESTIONS_FILE}': {e}")
        return _init_empty_data()
    except Exception as e:
        logger.critical(f"Не удалось прочитать файл '{QUESTIONS_FILE}': {e}")
        return _init_empty_data()

    # Проверяем структуру данных
    if not isinstance(questions_list_raw, list):
        logger.critical(f"Ошибка структуры JSON: Ожидался список вопросов, получен {type(questions_list_raw)}")
        return _init_empty_data()

    # Обрабатываем вопросы
    processed_questions: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    processed_list_flat: List[Dict[str, Any]] = []
    question_ids: set = set()
    
    valid_count = 0
    invalid_count = 0
    duplicate_count = 0
    
    for i, question in enumerate(questions_list_raw):
        # Валидация вопроса
        is_valid, error_msg = validate_question(question)
        
        if not is_valid:
            logger.warning(f"Question {i+1} invalid: {error_msg}. Question: {str(question)[:100]}...")
            invalid_count += 1
            continue
        
        # Проверка на дублирование ID
        question_id = question['id']
        if question_id in question_ids:
            logger.warning(f"Duplicate question ID '{question_id}' found, skipping...")
            duplicate_count += 1
            continue
        
        question_ids.add(question_id)
        
        # Добавляем вопрос в структуры данных
        block = question["block"]
        topic = question["topic"]

        if block not in processed_questions:
            processed_questions[block] = {}
        if topic not in processed_questions[block]:
            processed_questions[block][topic] = []

        processed_questions[block][topic].append(question)
        processed_list_flat.append(question)
        valid_count += 1

    # Логируем результаты
    logger.info(f"Загрузка завершена: {valid_count} валидных, {invalid_count} невалидных, {duplicate_count} дублированных")
    
    if valid_count == 0:
        logger.error("Не найдено ни одного валидного вопроса!")
        return _init_empty_data()

    # Обновляем глобальные переменные
    QUESTIONS_DATA = processed_questions
    QUESTIONS_LIST_FLAT = processed_list_flat
    QUESTIONS_DICT_FLAT = {q["id"]: q for q in processed_list_flat}
    AVAILABLE_BLOCKS = sorted(list(processed_questions.keys()))

    # Строим кеш после загрузки вопросов если модуль доступен
    if questions_cache:
        try:
            questions_cache.build_from_data(processed_questions)
            logger.info("Questions cache built successfully")
        except Exception as e:
            logger.error(f"Failed to build questions cache: {e}")
    else:
        logger.info("Cache module not available, working without cache")
    
    # Выводим статистику по блокам
    logger.info("Статистика по блокам:")
    for block, topics in processed_questions.items():
        topic_count = len(topics)
        total_questions = sum(len(questions) for questions in topics.values())
        logger.info(f"  {block}: {topic_count} тем, {total_questions} вопросов")
    
    return processed_questions, processed_list_flat

def _init_empty_data() -> Tuple[Dict, List]:
    """Инициализирует пустые структуры данных."""
    global QUESTIONS_DATA, QUESTIONS_LIST_FLAT, QUESTIONS_DICT_FLAT, AVAILABLE_BLOCKS
    
    QUESTIONS_DATA = {}
    QUESTIONS_LIST_FLAT = []
    QUESTIONS_DICT_FLAT = {}
    AVAILABLE_BLOCKS = []
    
    return {}, []

# Добавить новую функцию статистики:
def get_stats() -> Dict[str, Any]:
    """Возвращает статистику загруженных данных."""
    stats = {
        "total_questions": len(QUESTIONS_LIST_FLAT) if QUESTIONS_LIST_FLAT else 0,
        "total_blocks": len(QUESTIONS_DATA) if QUESTIONS_DATA else 0,
        "total_topics": 0,
        "cache_built": False,
        "blocks": {}
    }
    
    if QUESTIONS_DATA:
        # Подсчитываем темы и статистику по блокам
        for block, topics in QUESTIONS_DATA.items():
            topic_count = len(topics)
            question_count = sum(len(questions) for questions in topics.values())
            
            stats["total_topics"] += topic_count
            stats["blocks"][block] = {
                "topics": topic_count,
                "questions": question_count
            }
    
    # Проверяем статус кеша
    if questions_cache:
        stats["cache_built"] = questions_cache._is_built
    
    return stats

# Добавить функцию перезагрузки:
def reload_questions() -> bool:
    """
    Перезагружает вопросы из файла.
    
    Returns:
        bool: True если перезагрузка прошла успешно
    """
    try:
        logger.info("Перезагрузка вопросов...")
        
        # Очищаем кеш
        if questions_cache:
            questions_cache.clear()
        
        # Загружаем заново
        data, flat_list = load_questions()
        
        if data and flat_list:
            logger.info("Перезагрузка вопросов завершена успешно")
            return True
        else:
            logger.error("Перезагрузка вопросов не удалась")
            return False
            
    except Exception as e:
        logger.error(f"Ошибка при перезагрузке вопросов: {e}")
        return False

# Добавить функцию проверки целостности:
def validate_data_integrity() -> Dict[str, Any]:
    """
    Проверяет целостность загруженных данных.
    
    Returns:
        Dict с результатами проверки
    """
    result = {
        "valid": True,
        "errors": [],
        "warnings": [],
        "stats": {}
    }
    
    if not QUESTIONS_DATA or not QUESTIONS_LIST_FLAT:
        result["valid"] = False
        result["errors"].append("No data loaded")
        return result
    
    # Проверяем согласованность структур
    flat_count = len(QUESTIONS_LIST_FLAT)
    structured_count = sum(
        len(questions) 
        for topics in QUESTIONS_DATA.values() 
        for questions in topics.values()
    )
    
    if flat_count != structured_count:
        result["valid"] = False
        result["errors"].append(
            f"Data inconsistency: flat list has {flat_count} questions, "
            f"structured data has {structured_count}"
        )
    
    # Проверяем уникальность ID
    if QUESTIONS_DICT_FLAT:
        dict_count = len(QUESTIONS_DICT_FLAT)
        if dict_count != flat_count:
            result["warnings"].append(
                f"ID dictionary has {dict_count} entries, "
                f"but flat list has {flat_count} questions"
            )
    
    # Статистика
    result["stats"] = get_stats()
    
    return result

# Добавить новую функцию для получения доступных блоков:
def get_available_blocks() -> List[str]:
    """Возвращает список доступных блоков."""
    global AVAILABLE_BLOCKS
    return AVAILABLE_BLOCKS or []

def get_questions_data() -> Optional[Dict[str, Dict[str, List[Dict[str, Any]]]]]:
    global QUESTIONS_DATA
    if QUESTIONS_DATA is None:
        logger.warning("Попытка доступа к QUESTIONS_DATA до загрузки.")
    return QUESTIONS_DATA

def get_questions_list_flat() -> Optional[List[Dict[str, Any]]]:
    global QUESTIONS_LIST_FLAT
    if QUESTIONS_LIST_FLAT is None:
        logger.warning("Попытка доступа к QUESTIONS_LIST_FLAT до загрузки.")
    return QUESTIONS_LIST_FLAT

def get_questions_dict_flat() -> Optional[Dict[str, Dict[str, Any]]]:
    global QUESTIONS_DICT_FLAT
    if QUESTIONS_DICT_FLAT is None:
        logger.warning("Попытка доступа к QUESTIONS_DICT_FLAT до загрузки.")
    return QUESTIONS_DICT_FLAT
# Автоматическая загрузка при импорте модуля
# Это гарантирует, что QUESTIONS_DATA будет инициализирован
if QUESTIONS_DATA is None:
    logger.info("Auto-loading questions on module import...")
    load_questions()