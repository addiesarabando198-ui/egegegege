"""
Генератор колод карточек из существующих JSON-данных проекта.

Источники данных:
- data/task23_questions.json → Колода "Конституция РФ"
- WebApp/glossary.json → Колода "Глоссарий обществознания"
- user_mistakes + questions.json → Персональная колода ошибок
"""

import json
import logging
import os
from typing import List, Dict, Any

import aiosqlite

from . import db as flashcard_db

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(__file__))


async def generate_all_decks() -> None:
    """Генерирует все колоды из доступных источников данных."""
    logger.info("Starting deck generation...")

    await generate_constitution_deck()
    await generate_glossary_decks()
    await generate_topic_decks()

    logger.info("Deck generation complete")


# ============================================================
# КОНСТИТУЦИЯ РФ (Задание 23)
# ============================================================

async def generate_constitution_deck() -> None:
    """
    Генерирует колоду карточек из task23_questions.json.

    Для каждого вопроса:
    - Лицевая сторона: характеристика
    - Обратная сторона: положения Конституции (model_answers)
    """
    data_path = os.path.join(BASE_DIR, 'data', 'task23_questions.json')

    try:
        with open(data_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.warning(f"Task23 data not found: {data_path}")
        return

    questions = data.get('questions', [])
    if not questions:
        logger.warning("No questions found in task23 data")
        return

    deck_id = "constitution_rf"
    await flashcard_db.upsert_deck(
        deck_id=deck_id,
        title="Конституция РФ",
        description="Положения Конституции для задания 23 ЕГЭ",
        category="Конституционное право",
        icon="📜",
        is_premium=0,
    )

    cards: List[Dict[str, Any]] = []

    for i, question in enumerate(questions):
        model_type = question.get('model_type', 1)
        characteristics = question.get('characteristics', [])
        model_answers = question.get('model_answers', [])
        question_id = question.get('id', f'task23_{i+1:03d}')

        if model_type == 1:
            # Тип 1: одна характеристика → несколько подтверждений
            if characteristics and model_answers:
                char_text = characteristics[0]
                # Формируем обратную сторону
                answers_text = "\n".join(
                    f"{j+1}. {ans}" for j, ans in enumerate(model_answers)
                )

                cards.append({
                    'id': f"fc_{question_id}",
                    'deck_id': deck_id,
                    'front_text': f"Конституция РФ закрепляет:\n\n{char_text}\n\nНазовите положения Конституции, подтверждающие это.",
                    'back_text': answers_text,
                    'hint': f"Нужно вспомнить {min(3, len(model_answers))} подтверждения",
                    'sort_order': i,
                })

        elif model_type == 2:
            # Тип 2: несколько характеристик → по одному подтверждению
            if characteristics and isinstance(model_answers, dict):
                for j, char in enumerate(characteristics):
                    char_answers = model_answers.get(char, [])
                    if not char_answers:
                        continue

                    answers_text = "\n".join(
                        f"• {ans}" for ans in char_answers
                    )

                    cards.append({
                        'id': f"fc_{question_id}_c{j+1}",
                        'deck_id': deck_id,
                        'front_text': f"Какие положения Конституции подтверждают характеристику РФ:\n\n{char}",
                        'back_text': answers_text,
                        'hint': "Назовите хотя бы одно положение",
                        'sort_order': i * 10 + j,
                    })

    if cards:
        await flashcard_db.bulk_upsert_cards(cards)
        await flashcard_db.update_deck_card_count(deck_id)
        logger.info(f"Generated {len(cards)} constitution flashcards")


# ============================================================
# ГЛОССАРИЙ ОБЩЕСТВОЗНАНИЯ
# ============================================================

# Категории терминов для разбиения на колоды
GLOSSARY_CATEGORIES = {
    'economy': {
        'title': 'Экономика',
        'icon': '💰',
        'keywords': [
            'банк', 'бюджет', 'экономич', 'рынок', 'собственность',
            'налог', 'предприни', 'труд', 'торг', 'финанс', 'монопол',
            'конкуренц', 'производств', 'издержк', 'фактор', 'капитал',
            'специализ', 'профессия', 'специальность', 'заработн',
            'коммерч', 'юридическ', 'предприят', 'фирм', 'ввп',
            'ассигнован', 'цифров', 'эффективн',
        ],
    },
    'philosophy': {
        'title': 'Человек и общество',
        'icon': '🧠',
        'keywords': [
            'истин', 'познан', 'сознан', 'мировоззрен', 'деятельн',
            'потребн', 'личност', 'общество', 'культур', 'наук',
            'религ', 'миф', 'мотив', 'цель', 'образован', 'общен',
            'рефлекс', 'свобод', 'ощущен', 'восприят', 'представлен',
            'понят', 'суждени', 'умозаключен', 'знан', 'гносеолог',
            'бессознатель', 'агностиц', 'здравый', 'стереотип',
            'коммуникац', 'обыденн', 'рациональ', 'чувственн',
            'самореализац', 'смысл', 'заблуждени', 'интерес',
            'массов', 'обществен', 'социальн_наук', 'установк',
            'киберпреступ', 'необходим', 'понимани',
        ],
    },
    'law': {
        'title': 'Право',
        'icon': '⚖️',
        'keywords': [
            'прав', 'закон', 'суд', 'кодекс', 'конституц',
            'ответственн', 'наказан', 'процесс', 'гражданск',
            'уголовн', 'административн', 'алимент', 'брак',
            'наследован', 'сделк', 'договор', 'апелляц', 'кассац',
            'приговор', 'вердикт', 'вещн', 'обязательствен',
            'имуществен', 'потребитель', 'дисципл', 'образовательн',
            'комбатант', 'международн', 'экологич', 'семейн',
            'местн_самоуправлен', 'федерац', 'институт_прав',
            'отрасл', 'публичн', 'частн', 'материальн_прав',
            'государствен_служб',
        ],
    },
    'politics': {
        'title': 'Политика и социология',
        'icon': '🏛',
        'keywords': [
            'полити', 'власт', 'партий', 'идеолог', 'государств',
            'режим', 'элит', 'выбор', 'электорат', 'легитимн',
            'популиз', 'экстремиз', 'абсентеиз', 'лидерств',
            'конфликт', 'социал', 'страти', 'девиант', 'делинквент',
            'молодёж', 'семь', 'нуклеарн', 'демограф', 'нация',
            'этнос', 'этнич', 'субкультур', 'форм_правл', 'форм_государ',
            'форм_территориальн', 'суверенитет', 'конформ', 'ценност',
            'роль', 'статус', 'институционализац', 'информатизац',
            'класс', 'компетенц', 'авторитет', 'муниципальн',
            'средств_массов',
        ],
    },
}


def _classify_term(term_id: str, term_text: str, definition: str) -> str:
    """Определяет категорию термина по ключевым словам."""
    text_lower = (term_id + ' ' + term_text + ' ' + definition).lower()

    best_cat = 'philosophy'  # По умолчанию
    best_score = 0

    for cat_id, cat_info in GLOSSARY_CATEGORIES.items():
        score = sum(1 for kw in cat_info['keywords'] if kw in text_lower)
        if score > best_score:
            best_score = score
            best_cat = cat_id

    return best_cat


async def generate_glossary_decks() -> None:
    """
    Генерирует колоды из glossary.json.

    Разбивает термины по категориям (Экономика, Право, Политика, Человек и общество).
    """
    # Ищем glossary.json в нескольких местах (WebApp может быть не задеплоен)
    possible_paths = [
        os.path.join(BASE_DIR, 'data', 'glossary.json'),
        os.path.join(BASE_DIR, 'WebApp', 'glossary.json'),
    ]

    terms = None
    for data_path in possible_paths:
        try:
            with open(data_path, 'r', encoding='utf-8') as f:
                terms = json.load(f)
            break
        except FileNotFoundError:
            continue

    if terms is None:
        logger.warning(f"Glossary data not found in: {possible_paths}")
        return

    if not terms:
        logger.warning("No terms found in glossary")
        return

    # Классифицируем термины по категориям
    categorized: Dict[str, List[Dict]] = {cat: [] for cat in GLOSSARY_CATEGORIES}

    for term_data in terms:
        term_id = term_data.get('id', '')
        term = term_data.get('term', '')
        definition = term_data.get('definition', '')

        if not term or not definition:
            continue

        category = _classify_term(term_id, term, definition)
        categorized[category].append(term_data)

    # Создаём колоды
    for cat_id, cat_info in GLOSSARY_CATEGORIES.items():
        cat_terms = categorized.get(cat_id, [])
        if not cat_terms:
            continue

        deck_id = f"glossary_{cat_id}"
        await flashcard_db.upsert_deck(
            deck_id=deck_id,
            title=f"Термины: {cat_info['title']}",
            description=f"Определения терминов раздела \"{cat_info['title']}\"",
            category="Глоссарий",
            icon=cat_info['icon'],
            is_premium=0,
        )

        cards = []
        for i, term_data in enumerate(cat_terms):
            term = term_data['term']
            definition = term_data['definition']
            term_id = term_data.get('id', f'term_{i}')

            cards.append({
                'id': f"fc_gl_{term_id}",
                'deck_id': deck_id,
                'front_text': term,
                'back_text': definition,
                'hint': None,
                'sort_order': i,
            })

        if cards:
            await flashcard_db.bulk_upsert_cards(cards)
            await flashcard_db.update_deck_card_count(deck_id)
            logger.info(
                f"Generated {len(cards)} glossary flashcards for {cat_info['title']}"
            )


# ============================================================
# ПЕРСОНАЛЬНЫЕ КАРТОЧКИ ИЗ ОШИБОК
# ============================================================

async def generate_mistakes_deck(user_id: int) -> int:
    """
    Генерирует персональную колоду из ошибок пользователя.

    Берёт question_id из user_mistakes, находит вопрос в questions.json,
    создаёт карточку из вопроса и его explanation.

    Args:
        user_id: ID пользователя

    Returns:
        Количество сгенерированных карточек
    """
    from core.db import DATABASE_FILE as MAIN_DB

    # Получаем список ошибок пользователя
    async with aiosqlite.connect(MAIN_DB) as db:
        cursor = await db.execute(
            "SELECT question_id FROM user_mistakes WHERE user_id = ?",
            (user_id,)
        )
        rows = await cursor.fetchall()

    if not rows:
        return 0

    mistake_ids = {row[0] for row in rows}

    # Загружаем вопросы
    questions_path = os.path.join(BASE_DIR, 'data', 'questions.json')
    try:
        with open(questions_path, 'r', encoding='utf-8') as f:
            all_questions = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logger.warning("questions.json not found for mistakes deck")
        return 0

    # Индексируем по id
    questions_map = {}
    for q in all_questions:
        qid = q.get('id', '')
        if qid in mistake_ids:
            questions_map[qid] = q

    if not questions_map:
        return 0

    # Создаём/обновляем колоду
    deck_id = f"mistakes_{user_id}"
    await flashcard_db.upsert_deck(
        deck_id=deck_id,
        title="Мои ошибки",
        description="Карточки из вопросов, в которых вы ошиблись",
        category="Персональное",
        icon="🔴",
        is_premium=0,
    )

    cards = []
    for i, (qid, q) in enumerate(questions_map.items()):
        question_text = q.get('question', '')
        explanation = q.get('explanation', '')
        answer = q.get('answer', '')

        if not question_text or not explanation:
            continue

        # Лицевая сторона: вопрос
        front = question_text
        # Обратная сторона: правильный ответ + объяснение
        back = f"Ответ: {answer}\n\n{explanation}" if answer else explanation

        cards.append({
            'id': f"fc_err_{user_id}_{qid}",
            'deck_id': deck_id,
            'front_text': front,
            'back_text': back,
            'hint': f"Правильный ответ: {answer}" if answer else None,
            'sort_order': i,
        })

    if cards:
        await flashcard_db.bulk_upsert_cards(cards)
        await flashcard_db.update_deck_card_count(deck_id)
        logger.info(f"Generated {len(cards)} mistake flashcards for user {user_id}")

    return len(cards)


# ============================================================
# ТЕМАТИЧЕСКИЕ КОЛОДЫ (Задание 13, издержки, налоги и т.д.)
# ============================================================

async def generate_topic_decks() -> None:
    """
    Генерирует тематические колоды из data/flashcard_topics.json.

    Каждый элемент JSON содержит deck_id, title, description, category, icon
    и массив cards с полями front/back.
    """
    data_path = os.path.join(BASE_DIR, 'data', 'flashcard_topics.json')

    try:
        with open(data_path, 'r', encoding='utf-8') as f:
            topics = json.load(f)
    except FileNotFoundError:
        logger.warning(f"Topic decks data not found: {data_path}")
        return
    except json.JSONDecodeError as e:
        logger.warning(f"Invalid JSON in flashcard_topics.json: {e}")
        return

    if not topics:
        logger.warning("No topic decks found in flashcard_topics.json")
        return

    for topic in topics:
        deck_id = topic.get('deck_id', '')
        if not deck_id:
            continue

        await flashcard_db.upsert_deck(
            deck_id=deck_id,
            title=topic.get('title', ''),
            description=topic.get('description', ''),
            category=topic.get('category', 'Темы'),
            icon=topic.get('icon', '📚'),
            is_premium=0,
        )

        raw_cards = topic.get('cards', [])
        cards = []
        for i, card_data in enumerate(raw_cards):
            front = card_data.get('front', '')
            back = card_data.get('back', '')
            if not front or not back:
                continue

            cards.append({
                'id': f"fc_topic_{deck_id}_{i:03d}",
                'deck_id': deck_id,
                'front_text': front,
                'back_text': back,
                'hint': card_data.get('hint'),
                'sort_order': i,
            })

        if cards:
            await flashcard_db.bulk_upsert_cards(cards)
            await flashcard_db.update_deck_card_count(deck_id)
            logger.info(
                f"Generated {len(cards)} topic flashcards for '{topic.get('title', deck_id)}'"
            )
