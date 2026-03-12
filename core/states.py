"""Состояния FSM для PTB ConversationHandler."""

# Общие состояния
CHOOSING_SECTION = 1      # Выбор test_part или task24
CHOOSING_MODE = 2         # Выбор режима работы
CHOOSING_BLOCK = 3        # Выбор блока
CHOOSING_TOPIC = 4        # Выбор темы
CHOOSING_EXAM_NUMBER = 5  # Выбор номера ЕГЭ
ANSWERING = 6            # Ответ на вопрос
CHOOSING_NEXT_ACTION = 7  # После ответа
REVIEWING_MISTAKES = 8    # Работа над ошибками
EXAM_MODE = 9  # Режим экзамена

# Состояния для task19
SELECTING_TOPIC = 10     # Выбор темы для task19
WAITING_ANSWER = 11      # Ожидание ответа для task19
SEARCHING = 12

# Состояния для task24
AWAITING_PLAN = 20       # Ожидание плана от пользователя
SHOWING_PLAN = 21        # Показ эталонного плана
AWAITING_SEARCH = 22     # Ожидание поискового запроса
AWAITING_FEEDBACK = 23     

# Новые состояния для task25
CHOOSING_BLOCK_T25 = 101  # Выбор блока тем
ANSWERING_PARTS = 102  # Ответ по частям
# Уникальные состояния для изоляции модулей
TASK19_WAITING = 119  # Состояние ожидания ответа task19
TASK20_WAITING = 120  # Состояние ожидания ответа task20
TASK25_WAITING = 125  # Состояние ожидания ответа task25
# Состояния для task20
ANSWERING_T20 = 2001
SEARCHING = 2002
VIEWING_EXAMPLE = 2003
CONFIRMING_RESET = 2004

# Состояния для task17
ANSWERING_T17 = 1701

# Состояния для task18
ANSWERING_T18 = 1801
AWAITING_T17_TEXT = 1802  # Ожидание текста ответа на задание 17

# Состояния для task21
ANSWERING_T21 = 2101

# Состояния для task22
ANSWERING_T22 = 2201

# Состояния для task23
ANSWERING_T23 = 2301

# Состояния для full_exam (полный вариант ЕГЭ)
FULL_EXAM_OVERVIEW = 3001       # Обзор варианта с навигацией
FULL_EXAM_TEST_PART = 3002      # Ответ на задание тестовой части
FULL_EXAM_PART2_ANSWER = 3003   # Ответ на задание второй части (AI-проверка)
FULL_EXAM_RESULTS = 3004        # Итоговые результаты
FULL_EXAM_TASK_REVIEW = 3005    # Просмотр задания/ответа

# Состояния для flashcards (карточки)
FC_MENU = 4001              # Список колод
FC_DECK_VIEW = 4002         # Просмотр колоды
FC_REVIEWING = 4003         # Сессия повторения
FC_QUIZ = 4004              # Quiz-режим (Верно/Неверно, Выбор)
FC_DAILY = 4005             # Ежедневный челлендж
FC_PLAN = 4006              # Конструктор планов
FC_DUEL = 4007              # Дуэли
FC_TEACHER = 4008           # Учительские колоды (создание)