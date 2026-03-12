import re
import math
import html
import logging
from .ai_checker import get_ai_checker
import asyncio
from typing import List, Tuple, Dict, Any, Optional, Set
from collections import defaultdict
from telegram import InlineKeyboardMarkup, InlineKeyboardButton

logger = logging.getLogger(__name__)


class PlanBotData:
    def __init__(self, data: Dict[str, Any]):
        logger.info(">>> Вход в PlanBotData.__init__")
        self._morph = None
        self._cache = {}  # Кэш для результатов лемматизации
        self.topics_by_block: Dict[str, List[Tuple[int, str]]] = defaultdict(list)
        self.topic_list_for_pagination: List[Tuple[int, str]] = []
        self.topic_index_map: Dict[int, str] = {}
        self.plans_data: Dict[str, Dict[str, Any]] = {}
        self.search_index: Dict[str, List[int]] = {}
        
        self._load_data(data)
        logger.info("<<< Выход из PlanBotData.__init__")
    
# Исправленная часть task24/checker.py (строки 27-40)
# Замените эти методы в классе PlanBotData:

    def get_topic_by_index(self, index: int) -> Optional[str]:
        """Получает название темы по индексу."""
        return self.topic_index_map.get(index)

    def get_available_blocks(self) -> List[str]:
        """Возвращает список доступных блоков."""
        return sorted([block for block, topics in self.topics_by_block.items() if topics])

    def get_topics_for_pagination(self, block_name: Optional[str] = None) -> List[Tuple[int, str]]:
        """Получает темы для пагинации (все или по блоку)."""
        if block_name:
            return self.topics_by_block.get(block_name, [])
        return self.topic_list_for_pagination
    
    def _load_data(self, data: Dict[str, Any]):
        """
        Загружает и обрабатывает данные плана:
        - поддерживает как формат {"plans": {...}, "blocks": {...}}, так и список тем [{...}, ...]
        - наполняет self.plans_data, self.topics_by_block, self.topic_list_for_pagination, self.topic_index_map
        """
        try:
            # --- Если data это список (старый формат) ---
            if isinstance(data, list):
                logger.warning("PlanBotData: data - это список, преобразую в структуру plans и blocks")
                raw_plans = {}
                blocks = {}
                topics = []
                # Каждый элемент списка — это тема (dict: {topic: {поля}})
                for obj in data:
                    if isinstance(obj, dict):
                        for topic, plan_data in obj.items():
                            raw_plans[topic] = plan_data
                            topics.append(topic)
                            # Блоки могут быть внутри plan_data
                            block = plan_data.get("block", "Без блока")
                            blocks.setdefault(block, []).append(topic)
                data = {"plans": raw_plans, "blocks": blocks}
            # --- Если data это словарь ---
            raw_plans = data.get("plans", {})
            if not isinstance(raw_plans, dict):
                logger.error(f"Ключ 'plans' должен быть словарём, но получен {type(raw_plans)}; сбрасываем в {{}}.")
                raw_plans = {}
            self.plans_data = raw_plans

            # 2. Обрабатываем блоки тем (pagination)
            blocks = data.get("blocks", {})
            if not isinstance(blocks, dict):
                logger.error(f"Ключ 'blocks' должен быть словарём, но получен {type(blocks)}; сброс.")
                blocks = {}

            # Очистим коллекции на всякий случай
            self.topics_by_block.clear()
            self.topic_list_for_pagination.clear()
            self.topic_index_map.clear()

            # Наполняем индексы тем
            idx = 0
            for block, topics in blocks.items():
                if not isinstance(topics, list):
                    logger.warning(f"Для блока {block} ожидается список, получен {type(topics)}; пропускаем.")
                    continue
                for topic in topics:
                    self.topics_by_block[block].append((idx, topic))
                    self.topic_list_for_pagination.append((idx, topic))
                    self.topic_index_map[idx] = topic
                    idx += 1

            logger.info(f"Loaded {len(self.topic_list_for_pagination)} topics from blocks.")
            
            # Создаем поисковый индекс
            self._build_search_index()

        except Exception as e:
            logger.error(f"Ошибка при инициализации PlanBotData: {e}", exc_info=True)
            # Обнуляем всё, чтобы не было непредвиденного поведения
            self.plans_data = {}
            self.topics_by_block.clear()
            self.topic_list_for_pagination.clear()
            self.topic_index_map.clear()
            self.search_index.clear()
        finally:
            logger.info("<<< Выход из PlanBotData._load_data")

    def _build_search_index(self):
        """Создание поискового индекса для быстрого поиска тем."""
        self.search_index = {}
        for idx, (_, topic) in enumerate(self.topic_list_for_pagination):
            # Индекс по словам в названии
            words = topic.lower().split()
            for word in words:
                if word not in self.search_index:
                    self.search_index[word] = []
                self.search_index[word].append(idx)

    def get_all_topics_list(self) -> List[Tuple[int, str]]:
        """
        Возвращает полный список (index, topic) для постраничного просмотра.
        """
        return self.topic_list_for_pagination

    def get_plan_data(self, topic_name):
        # Теперь использует self.plans_data, который был обработан в _load_data
        return self.plans_data.get(topic_name)
        
    def lemmatize_text(self, text: str) -> List[str]:
        """Лемматизация текста с кэшированием."""
        # Проверяем кэш
        cache_key = hash(text)
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        # Лемматизация
        result = self._do_lemmatize(text)
        
        # Сохраняем в кэш
        self._cache[cache_key] = result
        return result
    
    def _do_lemmatize(self, text: str) -> List[str]:
        """Выполняет лемматизацию текста с fallback на простую токенизацию."""
        try:
            if not self._morph:
                try:
                    import pymorphy2
                    self._morph = pymorphy2.MorphAnalyzer()
                    logger.info("pymorphy2 успешно загружен")
                except ImportError:
                    logger.warning(
                        "pymorphy2 не установлен, используется простая токенизация"
                    )
                    self._morph = "simple"  # Флаг для простой токенизации

            if self._morph == "simple":
                # Простая токенизация без лемматизации
                words = re.findall(r"\b\w+\b", text.lower())
                # Убираем слишком короткие слова
                return [w for w in words if len(w) > 2]
            else:
                # Полная лемматизация с pymorphy2
                words = re.findall(r"\b\w+\b", text.lower())
                lemmas = []
                for word in words:
                    try:
                        parsed = self._morph.parse(word)[0]
                        lemmas.append(parsed.normal_form)
                    except Exception as e:
                        logger.debug(
                            f"Ошибка лемматизации слова '{word}': {e}"
                        )
                        lemmas.append(word)  # Используем исходное слово
                return lemmas

        except Exception as e:
            logger.error(f"Критическая ошибка в лемматизации: {e}")
            # Fallback на простую токенизацию
            return [w for w in re.findall(r"\b\w+\b", text.lower()) if len(w) > 2]


# 2) Парсинг и оценка плана:
def parse_user_plan(text: str) -> List[Tuple[str, List[str]]]:
    """
    ИСПРАВЛЕННЫЙ парсер планов пользователя.

    Исправления:
    1. Игнорирует номера тем (> 50)
    2. Корректно извлекает подпункты из строк
    3. Поддерживает различные форматы
    4. НОВОЕ: Поддержка планов БЕЗ номеров пунктов
    """
    parsed_plan = []
    current_point_text = None
    current_subpoints = []

    # Паттерн для основных пунктов С НОМЕРАМИ
    point_pattern = re.compile(r"^\s*(\d+)\s*[\.\)\-]\s*(.*)")
    # Паттерн для классических подпунктов
    subpoint_pattern = re.compile(r"^\s*(?:([а-яёa-z])\s*[\.\)]|([*\-•]))\s*(.*)", re.IGNORECASE)

    lines = text.strip().split('\n')

    # НОВОЕ: Проверяем, есть ли вообще номера пунктов в тексте
    has_numbered_points = any(point_pattern.match(line.strip()) for line in lines)

    for i, line in enumerate(lines):
        stripped_line = line.strip()
        if not stripped_line:
            continue

        point_match = point_pattern.match(stripped_line)
        subpoint_match = subpoint_pattern.match(stripped_line)

        # НОВОЕ: Если план БЕЗ номеров, используем альтернативную логику
        if not has_numbered_points:
            # Строка - это пункт, если:
            # 1. Она НЕ начинается с маркера подпункта
            # 2. Она либо заканчивается двоеточием, либо следующая строка - подпункт
            is_potential_point = not subpoint_match

            if is_potential_point and not subpoint_match:
                # Проверяем, есть ли подпункты в следующих строках
                next_line_is_subpoint = False
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if next_line and subpoint_pattern.match(next_line):
                        next_line_is_subpoint = True

                # Если текущая строка заканчивается двоеточием или следующая строка - подпункт
                if stripped_line.endswith(':') or next_line_is_subpoint:
                    # Сохраняем предыдущий пункт
                    if current_point_text is not None:
                        parsed_plan.append((current_point_text, current_subpoints))

                    # Начинаем новый пункт
                    current_point_text = stripped_line.rstrip(':').strip()
                    current_subpoints = []
                    logger.debug(f"Пункт без номера: '{current_point_text}'")
                    continue

            # Если это подпункт
            if subpoint_match and current_point_text is not None:
                subpoint_text = subpoint_match.group(3).strip()
                if subpoint_text:
                    current_subpoints.append(subpoint_text)
                    marker = subpoint_match.group(1) or subpoint_match.group(2)
                    logger.debug(f"Подпункт ({marker}): '{subpoint_text}'")
                continue

            # Если это строка без маркера, но мы уже внутри пункта - это тоже может быть пункт
            if current_point_text is None and not subpoint_match:
                current_point_text = stripped_line
                current_subpoints = []
                logger.debug(f"Первый пункт без номера: '{current_point_text}'")
            continue
        
        if point_match:
            # Сохраняем предыдущий пункт
            if current_point_text is not None:
                # Перед сохранением проверяем, не содержит ли сам пункт перечисления
                if not current_subpoints:
                    current_subpoints = _extract_inline_subpoints(current_point_text)
                    # Если нашли подпункты внутри текста, очищаем основной текст
                    if current_subpoints:
                        current_point_text = _clean_point_text(current_point_text)
                
                parsed_plan.append((current_point_text, current_subpoints))
            
            # ИСПРАВЛЕНИЕ 1: Игнорируем номера тем
            point_number = int(point_match.group(1))
            if point_number > 50:
                logger.debug(f"Игнорируем номер темы: {point_number}")
                current_point_text = None
                current_subpoints = []
                continue
            
            # Начинаем новый пункт
            full_point_text = point_match.group(2).strip()
            
            # ИСПРАВЛЕНИЕ 2: Улучшенное извлечение подпунктов
            inline_subpoints = _extract_inline_subpoints(full_point_text)
            if inline_subpoints:
                # Отделяем основной текст пункта от подпунктов
                current_point_text = _clean_point_text(full_point_text)
                current_subpoints = inline_subpoints
            else:
                current_point_text = full_point_text
                current_subpoints = []
            
            logger.debug(f"Пункт {point_number}: '{current_point_text}' ({len(current_subpoints)} подпунктов)")
            
        elif subpoint_match and current_point_text is not None:
            # Классический подпункт с маркером
            subpoint_text = subpoint_match.group(3).strip()
            if subpoint_text:
                current_subpoints.append(subpoint_text)
                marker = subpoint_match.group(1) or subpoint_match.group(2)
                logger.debug(f"Подпункт ({marker}): '{subpoint_text}'")
                
        elif current_point_text is not None and stripped_line:
            # Строка без явного маркера после пункта
            # Проверяем, не является ли это продолжением предыдущей строки
            if stripped_line[0].islower() or stripped_line.startswith(('и ', 'или ', ', ')):
                # Добавляем к последнему элементу
                if current_subpoints:
                    current_subpoints[-1] += " " + stripped_line
                else:
                    current_point_text += " " + stripped_line
            else:
                # Проверяем, не начинается ли следующая строка с номера пункта
                next_line_is_point = False
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if point_pattern.match(next_line):
                        next_line_is_point = True
                
                # Если следующая строка - не пункт, и текущая строка достаточно длинная
                if not next_line_is_point and len(stripped_line) > 10:
                    # Это может быть подпункт без маркера
                    current_subpoints.append(stripped_line)
                    logger.debug(f"Подпункт без маркера: '{stripped_line}'")
    
    # Сохраняем последний пункт
    if current_point_text is not None:
        # Проверяем встроенные подпункты для последнего пункта
        if not current_subpoints:
            current_subpoints = _extract_inline_subpoints(current_point_text)
            if current_subpoints:
                current_point_text = _clean_point_text(current_point_text)
        
        parsed_plan.append((current_point_text, current_subpoints))
    
    if not parsed_plan and text.strip():
        logger.warning(f"Не удалось распознать структуру плана пользователя:\n{text[:200]}...")
    
    logger.info(f"План распарсен: {len(parsed_plan)} пунктов")
    for i, (point, subs) in enumerate(parsed_plan):
        logger.debug(f"Пункт {i+1}: '{point}' ({len(subs)} подпунктов)")
    
    return parsed_plan


def _clean_point_text(text: str) -> str:
    """Очищает текст пункта от подпунктов."""
    # Убираем подпункты через двоеточие
    if ':' in text:
        parts = text.split(':', 1)
        return parts[0].strip()
    
    # Убираем подпункты с буквенными маркерами
    cleaned = re.sub(r'\s+[а-яёa-z][\.\)][^;]*(?:;|$)', '', text, flags=re.IGNORECASE)
    
    # Убираем подпункты с точкой с запятой (если остались)
    if ';' in cleaned and cleaned.count(';') >= 2:
        parts = cleaned.split(';')
        return parts[0].strip()
    
    return cleaned.strip()


def _extract_inline_subpoints(text: str) -> List[str]:
    """
    ИСПРАВЛЕННОЕ извлечение подпунктов из текста.
    """
    subpoints = []
    
    logger.debug(f"Извлечение подпунктов из: '{text}'")
    
    # ИСПРАВЛЕНИЕ: Сначала ищем классические подпункты а), б), в)
    classic_pattern = r'([а-яёa-z])\)\s*([^;а-яёa-z]+?)(?=\s*[а-яёa-z]\)|$)'
    classic_matches = re.findall(classic_pattern, text, re.IGNORECASE)
    
    if classic_matches:
        for letter, subtext in classic_matches:
            clean_text = subtext.strip().rstrip(';.,').strip()
            if len(clean_text) > 2:
                subpoints.append(clean_text)
                logger.debug(f"Найден классический подпункт: {letter}) {clean_text}")
        
        if subpoints:
            return subpoints
    
    # Проверяем наличие двоеточия с последующим перечислением
    if ':' in text:
        parts = text.split(':', 1)
        if len(parts) == 2:
            enumeration = parts[1].strip()
            logger.debug(f"Найдено перечисление после двоеточия: '{enumeration}'")
            
            # Пробуем разделить по точке с запятой
            if ';' in enumeration:
                items = [item.strip() for item in enumeration.split(';')]
                # Фильтруем пустые и слишком короткие элементы
                subpoints = [item for item in items if len(item) > 3]
                logger.debug(f"Разделено по ';': {len(subpoints)} подпунктов")
            # Если нет точки с запятой, пробуем по запятой (но только если элементов больше 2)
            elif enumeration.count(',') >= 2:
                items = [item.strip() for item in enumeration.split(',')]
                # Проверяем, что это действительно перечисление, а не просто предложение
                if all(len(item) < 50 for item in items) and len(items) >= 3:
                    subpoints = [item for item in items if len(item) > 3]
                    logger.debug(f"Разделено по ',': {len(subpoints)} подпунктов")
    
    # Альтернативный вариант: просто точки с запятой без двоеточия
    elif ';' in text and text.count(';') >= 2:
        items = [item.strip() for item in text.split(';')]
        # Берем все элементы, кроме первого (он остается как заголовок пункта)
        if len(items) > 2:
            subpoints = [item for item in items[1:] if len(item) > 3]
            logger.debug(f"Разделено по ';' без ':': {len(subpoints)} подпунктов")
    
    # Очистка подпунктов от лишних символов
    cleaned_subpoints = []
    for sp in subpoints:
        original_sp = sp
        # Убираем конечные точки, если они есть
        sp = sp.rstrip('.')
        # Убираем номера в начале, если есть (1), 2) и т.д.)
        sp = re.sub(r'^\d+[\)\.]?\s*', '', sp)
        # Убираем буквы в начале а), б) и т.д.
        sp = re.sub(r'^[а-яёa-z][\)\.]?\s*', '', sp, flags=re.IGNORECASE)
        
        if len(sp) > 3:  # Минимальная длина для подпункта
            cleaned_subpoints.append(sp)
            if sp != original_sp:
                logger.debug(f"Очищен подпункт: '{original_sp}' -> '{sp}'")
    
    logger.debug(f"Итого извлечено подпунктов: {len(cleaned_subpoints)}")
    return cleaned_subpoints

def _check_subpoints_relevance(parsed_plan: List[Tuple[str, List[str]]], 
                               found_obligatory: List[Dict], 
                               ideal_plan_data: dict,
                               bot_data: PlanBotData) -> Dict[str, List[int]]:
    """
    Проверяет релевантность подпунктов найденных обязательных пунктов.
    Возвращает словарь с индексами пунктов, имеющих релевантные подпункты.
    """
    points_with_relevant_subpoints = {}
    ideal_points = ideal_plan_data.get("points_data", [])
    
    for obligatory in found_obligatory:
        user_point_idx = obligatory.get('user_point_index')
        if user_point_idx is None or user_point_idx >= len(parsed_plan):
            continue
            
        point_text, user_subpoints = parsed_plan[user_point_idx]
        
        # Находим соответствующий эталонный пункт
        ideal_point = None
        for ip in ideal_points:
            if isinstance(ip, dict) and ip.get('point_text') == obligatory.get('text'):
                ideal_point = ip
                break
        
        if not ideal_point:
            continue
            
        # Получаем эталонные подпункты
        ideal_subpoints = ideal_point.get('sub_points', ideal_point.get('subpoints', []))
        if not ideal_subpoints:
            # Если нет эталонных подпунктов, считаем любые подпункты валидными
            points_with_relevant_subpoints[user_point_idx] = len(user_subpoints)
            continue
        
        # Лемматизируем все эталонные подпункты
        ideal_subpoints_lemmas = []
        for isp in ideal_subpoints:
            if isinstance(isp, str):
                lemmas = set(bot_data.lemmatize_text(isp))
                # Убираем стоп-слова
                stop_words = {'и', 'в', 'на', 'с', 'по', 'для', 'к', 'из', 'от', 'до', 'при', 'под', 'над', 'а', 'б', 'в', 'г'}
                lemmas = lemmas - stop_words
                ideal_subpoints_lemmas.append(lemmas)
        
        # Проверяем каждый подпункт пользователя
        relevant_count = 0
        junk_count = 0
        
        for usp in user_subpoints:
            # Сначала проверяем на мусор
            if _is_junk_subpoint(usp, obligatory.get('text', '')):
                junk_count += 1
                logger.debug(f"Обнаружен мусорный подпункт: '{usp}'")
                continue
            
            user_lemmas = set(bot_data.lemmatize_text(usp))
            user_lemmas = user_lemmas - {'и', 'в', 'на', 'с', 'по', 'для', 'к', 'из', 'от', 'до', 'при', 'под', 'над', 'а', 'б', 'в', 'г'}
            
            # Проверяем минимальную длину и осмысленность
            if len(user_lemmas) < 2 or len(usp) < 5:
                continue
            
            # Проверяем совпадение с любым эталонным подпунктом
            is_relevant = False
            for ideal_lemmas in ideal_subpoints_lemmas:
                if ideal_lemmas and user_lemmas:
                    # Если есть хотя бы одно совпадение значимых слов
                    if len(ideal_lemmas & user_lemmas) > 0:
                        is_relevant = True
                        break
                    # Или если подпункт содержит ключевые термины темы
                    topic_keywords = bot_data.lemmatize_text(obligatory.get('text', ''))
                    if len(set(topic_keywords) & user_lemmas) > 0:
                        is_relevant = True
                        break
            
            if is_relevant:
                relevant_count += 1
        
        # Если больше половины подпунктов - мусор, не засчитываем пункт
        if junk_count > len(user_subpoints) / 2:
            logger.warning(f"Пункт '{point_text}' содержит слишком много мусорных подпунктов ({junk_count}/{len(user_subpoints)})")
            continue
        
        # Требуем минимум 2 релевантных подпункта из 3
        if relevant_count >= 2:
            points_with_relevant_subpoints[user_point_idx] = relevant_count
    
    return points_with_relevant_subpoints

def _check_plan_structure(parsed_plan: List[Tuple[str, List[str]]], ideal_plan_data: dict) -> Dict[str, Any]:
    """
    Проверяет структуру плана согласно требованиям ЕГЭ 2025.
    Возвращает словарь с результатами проверки.
    """
    num_user_points = len(parsed_plan)
    
    # Подсчет пунктов с подпунктами
    points_with_subpoints = []
    for i, (point_text, subpoints) in enumerate(parsed_plan):
        if len(subpoints) > 0:
            points_with_subpoints.append({
                'index': i,
                'text': point_text,
                'subpoints': subpoints,
                'subpoints_count': len(subpoints)
            })
    
    # Минимальные требования из эталона
    min_subpoints_req = ideal_plan_data.get("min_subpoints", 3)
    
    # Подсчет пунктов с достаточным количеством подпунктов
    points_with_enough_subpoints = [p for p in points_with_subpoints 
                                   if p['subpoints_count'] >= min_subpoints_req]
    
    # Подсчет пунктов с недостаточным количеством подпунктов
    points_with_few_subpoints = [p for p in points_with_subpoints 
                                 if 0 < p['subpoints_count'] < min_subpoints_req]
    
    return {
        'total_points': num_user_points,
        'points_with_subpoints': points_with_subpoints,
        'points_with_enough_subpoints': points_with_enough_subpoints,
        'points_with_few_subpoints': points_with_few_subpoints,
        'min_subpoints_required': min_subpoints_req
    }


def _check_obligatory_points(user_plan_text: str, parsed_plan: List[Tuple[str, List[str]]], 
                           ideal_plan_data: dict, bot_data: PlanBotData) -> Dict[str, Any]:
    """
    Проверяет наличие обязательных пунктов эталонного плана в плане пользователя.
    Согласно ЕГЭ 2025, для баллов К1 нужны МИНИМУМ 3 пункта, раскрывающих тему.
    """
    ideal_points = ideal_plan_data.get("points_data", [])
    
    # Находим обязательные пункты
    obligatory_points = []
    for point in ideal_points:
        if isinstance(point, dict) and point.get("is_potentially_key", False):
            obligatory_points.append(point)
    
    # Если обязательные пункты не помечены, но есть данные о пунктах
    if not obligatory_points and ideal_points:
        logger.warning("Обязательные пункты не помечены в данных")
        # Если пунктов 3 или меньше, считаем все обязательными
        # Если больше - берем первые 3-4 как наиболее важные
        if len(ideal_points) <= 4:
            for point in ideal_points:
                if isinstance(point, dict) and 'point_text' in point:
                    obligatory_points.append(point)
        else:
            # Берем первые 4 пункта как основные
            for i, point in enumerate(ideal_points[:4]):
                if isinstance(point, dict) and 'point_text' in point:
                    obligatory_points.append(point)
    
    # Если вообще нет данных о пунктах, возвращаем упрощенный результат
    if not obligatory_points:
        logger.warning("Нет данных об обязательных пунктах для проверки")
        return {
            'total_obligatory': 0,
            'found_obligatory': [],
            'missed_obligatory': [],
            'min_required_obligatory': 3,
            'has_minimum_obligatory': True,  # Разрешаем оценку по структуре
            'all_obligatory_found': True
        }
    
    # Лемматизация плана пользователя
    user_lemmas_set = set(bot_data.lemmatize_text(user_plan_text))
    
    # Лемматизация текстов пунктов пользователя для более точного поиска
    user_points_lemmas = []
    for point_text, subpoints in parsed_plan:
        point_lemmas = set(bot_data.lemmatize_text(point_text))
        subpoints_text = " ".join(subpoints)
        subpoints_lemmas = set(bot_data.lemmatize_text(subpoints_text))
        user_points_lemmas.append({
            'point_lemmas': point_lemmas,
            'subpoints_lemmas': subpoints_lemmas,
            'all_lemmas': point_lemmas | subpoints_lemmas,
            'original_text': point_text
        })
    
    # Проверяем каждый обязательный пункт
    found_obligatory = []
    missed_obligatory = []
    
    for obligatory_point in obligatory_points:
        point_text = obligatory_point.get('point_text', 'Неизвестный пункт')
        keywords = obligatory_point.get('lemmatized_keywords', [])
        
        # Если нет ключевых слов, создаем их из текста пункта
        if not keywords:
            keywords = bot_data.lemmatize_text(point_text)
            # Фильтруем стоп-слова
            stop_words = {'и', 'в', 'на', 'с', 'по', 'для', 'к', 'из', 'от', 'до', 'при', 'под', 'над'}
            keywords = [w for w in keywords if w not in stop_words and len(w) > 2]
        
        if not keywords:
            logger.warning(f"Не удалось извлечь ключевые слова для пункта: {point_text}")
            continue
        
        # Определяем требуемое количество совпадений (смягченные требования)
        num_keywords = len(keywords)
        required_matches = (
            1 if num_keywords <= 3 else
            2 if num_keywords <= 6 else
            max(2, math.ceil(num_keywords * 0.3))  # Снижено с 0.4 до 0.3
        )
        
        # Ищем совпадения в общем тексте
        matches_in_text = sum(1 for kw in keywords if kw in user_lemmas_set)
        
        # Ищем лучшее совпадение среди пунктов пользователя
        best_match = None
        best_match_count = 0
        
        for i, user_point_lemmas in enumerate(user_points_lemmas):
            point_matches = sum(1 for kw in keywords if kw in user_point_lemmas['all_lemmas'])
            if point_matches > best_match_count:
                best_match_count = point_matches
                best_match = i
        
        # Используем лучший результат
        final_match_count = max(matches_in_text, best_match_count)
        
        if final_match_count >= required_matches:
            found_obligatory.append({
                'text': point_text,
                'matched_keywords': final_match_count,
                'total_keywords': num_keywords,
                'required': required_matches,
                'user_point_index': best_match if best_match_count >= required_matches else None
            })
        else:
            missed_obligatory.append({
                'text': point_text,
                'reason': f'найдено {final_match_count} из {required_matches} требуемых ключевых слов'
            })
    
    # Проверяем минимум 3 пункта, а не все
    min_required_obligatory = 3
    has_minimum_obligatory = len(found_obligatory) >= min_required_obligatory
    
    # Добавляем проверку на все обязательные пункты
    all_obligatory_found = len(found_obligatory) == len(obligatory_points)
    
    return {
        'total_obligatory': len(obligatory_points),
        'found_obligatory': found_obligatory,
        'missed_obligatory': missed_obligatory,
        'min_required_obligatory': min_required_obligatory,
        'has_minimum_obligatory': has_minimum_obligatory,
        'all_obligatory_found': all_obligatory_found
    }


def _calculate_score_ege2025(structure_check: Dict[str, Any], content_check: Dict[str, Any], 
                            ideal_plan_data: dict, parsed_plan: List[Tuple[str, List[str]]],
                            bot_data: PlanBotData) -> Tuple[int, int, List[str]]:
    """
    ИСПРАВЛЕННАЯ функция расчета баллов К1 и К2 согласно критериям ЕГЭ 2025.
    """
    k1_score = 0
    k2_score = 0
    explanations = []
    
    # Если нет данных об обязательных пунктах, используем упрощенную оценку
    if content_check['total_obligatory'] == 0:
        logger.warning("Нет данных об обязательных пунктах, используем упрощенную оценку по структуре")
        
        # Оцениваем только по структуре
        total_points = structure_check['total_points']
        points_with_enough = len(structure_check['points_with_enough_subpoints'])
        min_subpoints = structure_check['min_subpoints_required']
        
        # ИСПРАВЛЕНИЕ: Требуем МИНИМУМ 3 пункта для любой оценки
        if total_points < 3:
            k1_score = 0
            explanations.append(
                f"❌ К1: 0 баллов - недостаточно пунктов ({total_points} < 3)"
            )
        elif total_points >= 3 and points_with_enough >= 3:
            k1_score = 3
            explanations.append(
                f"✅ К1: 3 балла - план содержит {total_points} пунктов, "
                f"из них {points_with_enough} детализированы {min_subpoints}+ подпунктами"
            )
        elif total_points >= 3 and points_with_enough == 2:
            k1_score = 2
            explanations.append(
                f"⚠️ К1: 2 балла - план содержит {total_points} пунктов, "
                f"но только {points_with_enough} детализированы {min_subpoints}+ подпунктами"
            )
        elif total_points >= 3 and points_with_enough == 1:
            k1_score = 1
            explanations.append(
                f"⚠️ К1: 1 балл - план содержит {total_points} пунктов, "
                f"но только {points_with_enough} детализирован {min_subpoints}+ подпунктами"
            )
        else:
            k1_score = 0
            explanations.append(
                f"❌ К1: 0 баллов - нет достаточно детализированных пунктов ({points_with_enough})"
            )
        
        explanations.append(
            "⚠️ Примечание: оценка выполнена только по структуре, "
            "так как отсутствуют данные об обязательных пунктах эталона"
        )
    else:
        # Стандартная оценка с проверкой обязательных пунктов
        
        # ИСПРАВЛЕНИЕ: Сначала проверяем базовые требования
        total_points = structure_check['total_points']
        if total_points < 3:
            k1_score = 0
            explanations.append(
                f"❌ К1: 0 баллов - недостаточно пунктов в плане ({total_points} < 3)"
            )
            k2_score = 0
            explanations.append("❌ К2: 0 баллов (т.к. К1 = 0)")
            return k1_score, k2_score, explanations
        
        # Проверяем наличие минимума обязательных пунктов
        if not content_check['has_minimum_obligatory']:
            k1_score = 0
            explanations.append(
                f"❌ К1: 0 баллов - не найдено минимальное количество ключевых пунктов "
                f"(найдено {len(content_check['found_obligatory'])} из минимум {content_check['min_required_obligatory']} требуемых)"
            )
            k2_score = 0
            explanations.append("❌ К2: 0 баллов (т.к. К1 = 0)")
            return k1_score, k2_score, explanations
        
        # Минимум обязательных пунктов найден, проверяем детализацию
        found_obligatory = content_check['found_obligatory']
        points_with_enough = structure_check['points_with_enough_subpoints']
        min_subpoints = structure_check['min_subpoints_required']
        
        # Проверяем релевантность подпунктов
        points_with_relevant_subpoints = _check_subpoints_relevance(
            parsed_plan, found_obligatory, ideal_plan_data, bot_data
        )
        
        # Сопоставляем найденные обязательные пункты с детализированными И релевантными
        detailed_obligatory_count = 0
        poorly_detailed_points = []
        
        for obligatory in found_obligatory:
            user_point_idx = obligatory.get('user_point_index')
            if user_point_idx is not None:
                # Проверяем, детализирован ли этот пункт
                is_detailed = False
                for detailed_point in points_with_enough:
                    if detailed_point['index'] == user_point_idx:
                        is_detailed = True
                        break
                
                # Проверяем релевантность подпунктов
                is_relevant = user_point_idx in points_with_relevant_subpoints
                
                if is_detailed and is_relevant:
                    detailed_obligatory_count += 1
                elif is_detailed and not is_relevant:
                    poorly_detailed_points.append({
                        'text': obligatory['text'],
                        'reason': 'подпункты не соответствуют теме'
                    })
        
        # ИСПРАВЛЕНИЕ: Более строгие требования для К1
        if detailed_obligatory_count >= 3:
            k1_score = 3
            explanations.append(
                f"✅ К1: 3 балла - найдено {len(content_check['found_obligatory'])} ключевых пунктов "
                f"(из {content_check['total_obligatory']} в эталоне), "
                f"минимум 3 из них детализированы {min_subpoints}+ релевантными подпунктами"
            )
        elif detailed_obligatory_count == 2:
            k1_score = 2
            explanations.append(
                f"⚠️ К1: 2 балла - найдено {len(content_check['found_obligatory'])} ключевых пунктов, "
                f"но только 2 из них детализированы {min_subpoints}+ релевантными подпунктами"
            )
            if poorly_detailed_points:
                explanations.append(
                    f"❗ Проблемные пункты: {', '.join([p['text'] for p in poorly_detailed_points[:2]])} - "
                    f"{poorly_detailed_points[0]['reason']}"
                )
        elif detailed_obligatory_count == 1:
            k1_score = 1
            explanations.append(
                f"⚠️ К1: 1 балл - найдено {len(content_check['found_obligatory'])} ключевых пунктов, "
                f"но только 1 из них детализирован {min_subpoints}+ релевантными подпунктами"
            )
            if poorly_detailed_points:
                explanations.append(
                    f"❗ Проблемные пункты: {', '.join([p['text'] for p in poorly_detailed_points[:2]])} - "
                    f"{poorly_detailed_points[0]['reason']}"
                )
        else:
            k1_score = 0
            explanations.append(
                f"❌ К1: 0 баллов - ключевые пункты найдены ({len(content_check['found_obligatory'])}), "
                f"но ни один не детализирован минимум {min_subpoints} релевантными подпунктами"
            )
            if poorly_detailed_points:
                explanations.append(
                    f"❗ Подпункты не соответствуют теме в пунктах: "
                    f"{', '.join([p['text'] for p in poorly_detailed_points[:3]])}"
                )
    
    # К2 только при К1=3
    if k1_score == 3:
        k2_score = 1
        explanations.append("✅ К2: 1 балл (выставляется при К1=3)")
    else:
        k2_score = 0
        explanations.append(f"➖ К2: 0 баллов (т.к. К1 = {k1_score} меньше 3)")
    
    return k1_score, k2_score, explanations

def _is_junk_subpoint(subpoint: str, topic_context: str) -> bool:
    """
    Проверяет, является ли подпункт "мусорным" (явно нерелевантным).
    """
    # Нормализуем текст
    normalized = subpoint.lower().strip()
    
    # Слишком короткие подпункты
    if len(normalized) < 5:
        return True
    
    # Проверка на повторяющиеся символы
    if any(char * 3 in normalized for char in 'абвгдеёжзийклмнопрстуфхцчшщъыьэюя'):
        return True
    
    # Проверка на случайный набор букв
    words = normalized.split()
    for word in words:
        if len(word) > 3:
            # Проверяем, есть ли гласные
            vowels = set('аеёиоуыэюя')
            if not any(char in vowels for char in word):
                return True
    
    # Проверка на явно нерелевантные слова
    junk_patterns = [
        r'\b(тест|test|asdf|qwerty|абвгд|123|ааа|ббб|ввв)\b',
        r'\b(blah|bla|lol|хаха|хехе|хихи|ололо)\b',
        r'\b(фыва|йцук|ячсм)\b',  # клавиатурные последовательности
    ]
    
    for pattern in junk_patterns:
        if re.search(pattern, normalized, re.IGNORECASE):
            return True
    
    # Проверка на национальности/этносы без контекста
    # Для темы "Искусство" слова типа "русский", "беларус" без контекста - мусор
    if 'искусств' in topic_context.lower():
        nationality_pattern = r'^(русский|беларус|украинец|американец|немец|француз|китаец|японец|индус|араб|еврей|грузин|армянин|казах|узбек|таджик|киргиз|туркмен|молдаван|латыш|литовец|эстонец|финн|швед|норвеж|датчан|поляк|чех|словак|болгар|серб|хорват|словен|македон|албан|грек|турок|иранец|афган|пакистан|бангладеш|непал|бутан|монгол|кореец|вьетнам|тайланд|малайз|индонез|филиппин|австрал|новозеланд|канад|мексикан|бразил|аргентин|чилий|перуан|венесуэл|колумбий|эквадор|уругвай|парагвай|боливий|гайан|суринам|француз|гвиан|британ|ирланд|исланд|португал|испан|итальян|швейцар|австрий|бельгий|голланд|люксембур|монак|андорр|ватикан|сан-марин|лихтенштейн|мальт|кипр|венгр|румын|словен|босний|черногор|косов|эфиоп|египт|ливий|тунис|алжир|марокк|судан|сомали|кений|уганд|танзаний|мозамбик|зимбабв|ботсван|намибий|южноафрик|ангол|замбий|малави|мадагаскар|маврикий|сейшел|коморск|эритрей|джибут|руанд|бурунд|центральноафрик|чад|нигер|мали|буркина|мавритан|сенегал|гамбий|гвиней|сьерра-леон|либерий|кот-д|гана|того|бенин|нигерий|камерун|экваториальн|габон|конго|демократическ|ангол|намибий|ботсван|лесот|свазиленд|южносудан|папуас|фиджий|вануат|соломон|тувал|наур|кирибат|маршалл|микронез|палау|самоа|тонга|барбадос|багам|ямайк|гаити|доминик|куб|гренад|сент-люсий|сент-винсент|антигуа|тринидад|гайан|суринам|белиз|гватемал|гондурас|сальвадор|никарагуа|коста-рик|панам).*$'
        if re.search(nationality_pattern, normalized, re.IGNORECASE):
            # Проверяем, есть ли дополнительный контекст
            if len(words) <= 2:  # Только национальность или национальность + одно слово
                return True
    
    # Проверка на бессмысленные фразы
    if normalized in ['да', 'нет', 'не знаю', 'незнаю', 'хз', 'пока', 'привет', 'ок', 'окей', 
                      'спасибо', 'пожалуйста', 'извините', 'простите', 'ладно', 'хорошо',
                      'понятно', 'ясно', 'точно', 'конечно', 'может быть', 'наверное',
                      'думаю', 'считаю', 'полагаю', 'кажется', 'вроде', 'типа', 'как бы',
                      'ну', 'эээ', 'ммм', 'угу', 'ага', 'неа', 'йоу', 'ыыы', 'ээээ']:
        return True
    
    # Проверка на отсутствие осмысленных слов
    meaningful_word_count = 0
    for word in words:
        if len(word) >= 3 and any(char in 'аеёиоуыэюя' for char in word):
            meaningful_word_count += 1
    
    if meaningful_word_count == 0:
        return True
    
    # Проверка на слишком общие/неинформативные подпункты для любой темы
    generic_junk = [
        'разное', 'другое', 'прочее', 'остальное', 'всякое', 'и так далее', 'и тд',
        'и т.д.', 'и т. д.', 'и тп', 'и т.п.', 'и т. п.', 'и др', 'и др.', 
        'и другие', 'и прочее', 'и прочие', 'и другое', 'и так далее', 'и тому подобное',
        'много', 'мало', 'несколько', 'немного', 'чуть-чуть', 'совсем', 'вообще',
        'что-то', 'кто-то', 'где-то', 'когда-то', 'как-то', 'почему-то', 'зачем-то',
        'что-нибудь', 'кто-нибудь', 'где-нибудь', 'когда-нибудь', 'как-нибудь',
        'какой-то', 'какая-то', 'какое-то', 'какие-то', 'чей-то', 'чья-то', 'чье-то', 'чьи-то'
    ]
    
    if normalized in generic_junk:
        return True
    
    return False

def _format_evaluation_feedback(k1: int, k2: int, score_explanation: List[str], 
                              structure_check: Dict[str, Any], content_check: Dict[str, Any], 
                              topic_name: str) -> str:
    """Форматирует итоговое сообщение с использованием HTML."""
    try:
        total_score = k1 + k2
        escaped_topic_name = html.escape(str(topic_name)) if topic_name else "Неизвестная тема"
        score_emoji = "🎉" if total_score == 4 else "👍" if total_score == 3 else "🤔" if total_score > 0 else "😔"

        feedback = [f"📌 <b>Тема:</b> {escaped_topic_name}\n"]
        feedback.append(f"{score_emoji} <b>Предварительная оценка: {total_score} из 4</b>")
        feedback.append(f"▫️ К1 (Раскрытие темы): <b>{k1}/3</b>")
        feedback.append(f"▫️ К2 (Корректность): <b>{k2}/1</b>\n")
        
        # Критерии оценки
        feedback.append("📋 <b>Критерии оценки:</b>")
        for exp in score_explanation:
            # НЕ экранируем, так как эти строки формируются в коде
            feedback.append(f"  {exp}")
        
        feedback.append("\n<i>⚠️ Важно: Это автоматическая проверка. Окончательную оценку ставит эксперт ЕГЭ.</i>")
        feedback.append("\n" + "━" * 30 + "\n")
        
        # Детальный анализ
        feedback.append("🔍 <b>Детальный анализ:</b>\n")
        
        # Структура плана
        feedback.append("📊 <b>Структура вашего плана:</b>")
        feedback.append(f"▫️ Всего пунктов: {structure_check.get('total_points', 0)}")
        feedback.append(f"▫️ Пунктов с подпунктами: {len(structure_check.get('points_with_subpoints', []))}")
        feedback.append(f"▫️ Пунктов с {structure_check.get('min_subpoints_required', 3)}+ подпунктами: "
                       f"{len(structure_check.get('points_with_enough_subpoints', []))}")
        
        if structure_check.get('points_with_few_subpoints'):
            feedback.append(f"▫️ Пунктов с недостаточным числом подпунктов: "
                           f"{len(structure_check['points_with_few_subpoints'])}")
        
        # Содержание плана
        feedback.append("\n🔑 <b>Соответствие эталону:</b>")
        
        # Изменено: показываем минимальное требование
        min_required = content_check.get('min_required_obligatory', 3)
        
        if content_check.get('total_obligatory', 0) > 0:
            feedback.append(f"▫️ Ключевых пунктов в эталоне: {content_check['total_obligatory']}")
            feedback.append(f"▫️ Минимум требуется: {min_required}")
            feedback.append(f"▫️ Найдено в вашем плане: {len(content_check.get('found_obligatory', []))}")
        else:
            feedback.append(f"▫️ Оценка выполнена по структуре плана")
            feedback.append(f"▫️ Детализированных пунктов: {len(structure_check.get('points_with_enough_subpoints', []))}")
        
        # Найденные пункты
        if content_check.get('found_obligatory'):
            feedback.append("\n<b>✅ Найденные ключевые пункты:</b>")
            for point in content_check['found_obligatory']:
                try:
                    # Экранируем текст пункта с проверкой на None
                    point_text = point.get('text', '')
                    if not point_text:
                        point_text = 'Неизвестный пункт'
                    safe_text = html.escape(str(point_text))
                    feedback.append(f"  • {safe_text}")
                    
                    # Безопасное получение числовых значений
                    matched = point.get('matched_keywords', 0)
                    total = point.get('total_keywords', 0)
                    feedback.append(f"    (совпадений: {matched}/{total})")
                except Exception as e:
                    logger.error(f"Ошибка форматирования найденного пункта: {e}")
                    continue
        
        # Пропущенные пункты (только если найдено меньше минимума и есть данные об обязательных)
        if (content_check.get('total_obligatory', 0) > 0 and 
            len(content_check.get('found_obligatory', [])) < min_required and 
            content_check.get('missed_obligatory')):
            feedback.append("\n<b>❌ Не найденные ключевые пункты:</b>")
            # Показываем только несколько примеров
            for i, point in enumerate(content_check.get('missed_obligatory', [])[:3]):
                try:
                    # Экранируем текст пункта с проверкой на None
                    point_text = point.get('text', '')
                    if not point_text:
                        point_text = 'Неизвестный пункт'
                    safe_text = html.escape(str(point_text))
                    
                    reason = point.get('reason', '')
                    if not reason:
                        reason = 'причина не указана'
                    safe_reason = html.escape(str(reason))
                    
                    feedback.append(f"  • {safe_text}")
                    feedback.append(f"    ({safe_reason})")
                except Exception as e:
                    logger.error(f"Ошибка форматирования пропущенного пункта: {e}")
                    continue
                    
            if len(content_check.get('missed_obligatory', [])) > 3:
                feedback.append(f"  ... и еще {len(content_check['missed_obligatory']) - 3}")
        
        # Рекомендации
        feedback.append("\n💡 <b>Рекомендации:</b>")
        if k1 < 3:
            if content_check.get('total_obligatory', 0) > 0 and len(content_check.get('found_obligatory', [])) < min_required:
                feedback.append(f"▫️ Включите больше ключевых аспектов темы (минимум {min_required})")
            elif len(structure_check.get('points_with_enough_subpoints', [])) < 3:
                feedback.append(f"▫️ Детализируйте больше пунктов (минимум {structure_check.get('min_subpoints_required', 3)} подпункта в каждом)")
            else:
                feedback.append("▫️ Проверьте соответствие пунктов теме")
        else:
            feedback.append("▫️ Отличная работа! План соответствует требованиям.")
        
        return "\n".join(feedback)
        
    except Exception as e:
        logger.error(f"Критическая ошибка форматирования отзыва: {e}", exc_info=True)
        # Возвращаем минимальный безопасный отзыв
        return f"<b>Оценка:</b> К1={k1}/3, К2={k2}/1\n\n<i>Произошла ошибка при формировании детального отзыва.</i>"


def evaluate_plan(
    user_plan_text: str,
    ideal_plan_data: dict,
    bot_data: PlanBotData,
    topic_name: str
) -> str:
    """Базовая проверка плана без использования AI."""
    parsing_error_message = (
        "<b>Ошибка разбора плана!</b>\n\n"
        "Не удалось распознать структуру вашего плана.\n"
        "Пожалуйста, используйте нумерацию вида '1.', '2)', 'а)', 'б.', '-', '*' для пунктов и подпунктов.\n"
        "Убедитесь, что каждый пункт и подпункт начинается с новой строки."
    )

    parsed_user_plan = parse_user_plan(user_plan_text)
    if not parsed_user_plan and user_plan_text.strip():
        return parsing_error_message
    elif not parsed_user_plan:
        return "Вы прислали пустой план. Пожалуйста, пришлите ваш вариант плана."

    structure_check = _check_plan_structure(parsed_user_plan, ideal_plan_data)
    content_check = _check_obligatory_points(
        user_plan_text, parsed_user_plan, ideal_plan_data, bot_data
    )

    k1, k2, explanation = _calculate_score_ege2025(
        structure_check, content_check, ideal_plan_data, parsed_user_plan, bot_data
    )

    feedback_message = _format_evaluation_feedback(
        k1, k2, explanation, structure_check, content_check, topic_name
    )

    return feedback_message


async def evaluate_plan_with_ai(
    user_plan_text: str,
    ideal_plan_data: dict,
    bot_data: PlanBotData,
    topic_name: str,
    use_ai: bool = True,
    user_id: int = None
) -> str:
    """
    Расширенная версия evaluate_plan с углубленной AI-проверкой

    Args:
        user_plan_text: Текст плана ученика
        ideal_plan_data: Эталонные данные плана
        bot_data: Данные бота с темами
        topic_name: Название темы
        use_ai: Использовать ли AI-проверку
        user_id: ID пользователя (для логирования применения подсказок)
    """
    # Сначала выполняем обычную проверку для получения баллов
    basic_feedback = evaluate_plan(user_plan_text, ideal_plan_data, bot_data, topic_name)
    
    if not use_ai:
        return basic_feedback
    
    try:
        # Парсим план для AI-анализа
        parsed = parse_user_plan(user_plan_text)
        
        # Получаем AI-проверщик
        ai_checker = get_ai_checker()
        
        # Извлекаем баллы из basic_feedback
        k1_match = re.search(r'К1.*?(\d+)/3', basic_feedback)
        k2_match = re.search(r'К2.*?(\d+)/1', basic_feedback)
        k1 = int(k1_match.group(1)) if k1_match else 0
        k2 = int(k2_match.group(1)) if k2_match else 0
        
        # Параллельно выполняем все AI-проверки (с передачей user_id для логирования подсказок)

        relevance_task = ai_checker.check_plan_relevance(
            user_plan_text,
            topic_name,
            ideal_plan_data.get('points_data', []),
            user_id=user_id
        )

        errors_task = ai_checker.check_factual_errors(
            user_plan_text,
            topic_name,
            ideal_plan_data,
            user_id=user_id
        )

        comparison_task = ai_checker.compare_with_etalon(
            user_plan_text,
            parsed,
            ideal_plan_data,
            topic_name
        )
        
        # Ждем завершения всех проверок
        relevance_check, factual_errors, comparison_result = await asyncio.gather(
            relevance_task,
            errors_task,
            comparison_task,
            return_exceptions=True
        )
        
        # Получаем пропущенные пункты
        content_check = _check_obligatory_points(
            user_plan_text, parsed, ideal_plan_data, bot_data
        )
        missed_points = [m.get('text', '') for m in content_check.get('missed_obligatory', [])]

        # НОВОЕ: Корректируем К2 если AI нашла критические ошибки
        if factual_errors and isinstance(factual_errors, list) and k2 == 1:
            # Если есть хотя бы одна ошибка high/medium severity - К2 = 0
            critical_errors = [e for e in factual_errors if e.get('severity') in ['high', 'medium']]
            if critical_errors:
                logger.warning(f"Найдено {len(critical_errors)} критических ошибок, К2 снижен с 1 до 0")
                k2 = 0

        # Генерация персонализированной обратной связи
        personalized_feedback = await ai_checker.generate_personalized_feedback(
            user_plan_text,
            topic_name,
            k1,
            k2,
            missed_points,
            factual_errors if isinstance(factual_errors, list) else None,
            comparison_result if isinstance(comparison_result, dict) else None
        )
        
        # Форматируем структурированный AI-фидбек
        return _format_ai_feedback(
            topic_name=topic_name,
            k1=k1,
            k2=k2,
            relevance_check=relevance_check if isinstance(relevance_check, dict) else None,
            factual_errors=factual_errors if isinstance(factual_errors, list) else None,
            comparison_result=comparison_result if isinstance(comparison_result, dict) else None,
            personalized_feedback=personalized_feedback
        )
            
    except Exception as e:
        logger.error(f"Критическая ошибка AI-проверки: {e}", exc_info=True)
        # В случае ошибки возвращаем базовую проверку
        return basic_feedback + "\n\n<i>⚠️ AI-проверка временно недоступна</i>"

def _clean_markdown_syntax(text: str) -> str:
    """
    Очищает Markdown-синтаксис из текста, который должен отображаться в HTML.

    Убирает:
    - **жирный** и __жирный__
    - *курсив* и _курсив_
    - `код`
    - [ссылка](url)
    """
    if not text:
        return text

    # Убираем жирный текст: **текст** или __текст__
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'__([^_]+)__', r'\1', text)

    # Убираем курсив: *текст* или _текст_ (но не затрагиваем подчеркивания в словах)
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    text = re.sub(r'\b_([^_]+)_\b', r'\1', text)

    # Убираем код: `текст`
    text = re.sub(r'`([^`]+)`', r'\1', text)

    # Убираем ссылки: [текст](url) → текст
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)

    return text


def _format_ai_feedback(
    topic_name: str,
    k1: int,
    k2: int,
    relevance_check: Optional[Dict] = None,
    factual_errors: Optional[List] = None,
    comparison_result: Optional[Dict] = None,
    personalized_feedback: Optional[str] = None
) -> str:
    """
    ОПТИМИЗИРОВАННЫЙ формат AI-фидбека.

    Изменения:
    - Компактная строка с баллами
    - Убраны дублирующиеся блоки
    - Краткий отзыв эксперта (3-4 предложения)
    - Минимум эмодзи
    - Очистка Markdown-синтаксиса
    """

    total_score = k1 + k2

    # Компактный заголовок с баллами в одну строку
    feedback_parts = [
        f"📋 <b>Тема:</b> {html.escape(topic_name)}",
        f"📊 <b>Оценка:</b> К1: {k1}/3 | К2: {k2}/1 | <b>Итого: {total_score}/4</b>\n"
    ]

    # Персонализированный отзыв эксперта (теперь короткий - 3-4 предложения)
    if personalized_feedback:
        # НОВОЕ: Очищаем Markdown-синтаксис перед выводом
        cleaned_feedback = _clean_markdown_syntax(personalized_feedback)
        feedback_parts.append("💬 <b>Отзыв эксперта:</b>")
        feedback_parts.append(cleaned_feedback)
        feedback_parts.append("")

    # Краткая итоговая рекомендация (только одна строка)
    if total_score == 4:
        recommendation = "🎯 Отлично! Готовы к экзамену по этой теме."
    elif total_score == 3:
        recommendation = "🎯 Хороший результат. Внесите небольшие правки и будет идеально."
    elif total_score == 2:
        recommendation = "🎯 Доработайте план - добавьте недостающие пункты."
    elif total_score == 1:
        recommendation = "🎯 План требует существенной доработки. Изучите эталон."
    else:
        recommendation = "🎯 Начните заново с эталонного плана."

    feedback_parts.append(recommendation)

    return "\n".join(feedback_parts)


# Inline-клавиатура для фидбека (статичная, для обратной совместимости)
FEEDBACK_KB = InlineKeyboardMarkup([
    [
        InlineKeyboardButton("🔄 Ещё тема", callback_data="next_topic"),
        InlineKeyboardButton("📝 Меню планов", callback_data="t24_menu")
    ],
    [
        InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")
    ]
])


