"""
FSM состояния для режима учителя.
"""

from enum import IntEnum


class TeacherStates(IntEnum):
    """Состояния для учителей"""
    # Регистрация
    TEACHER_MENU = 1
    AWAITING_TEACHER_NAME = 2

    # Управление учениками
    STUDENT_LIST = 10
    STUDENT_DETAIL = 11

    # Создание домашнего задания
    CREATE_ASSIGNMENT = 20
    SELECT_ASSIGNMENT_TYPE = 21
    SELECT_SELECTION_MODE = 22  # Способ отбора заданий (все/темы/номера)
    SELECT_TOPICS = 23  # Выбор тем/блоков из банка
    SELECT_SPECIFIC_QUESTIONS = 24  # Выбор конкретных заданий из выбранных блоков
    ENTER_QUESTION_NUMBERS = 25  # Ввод конкретных номеров заданий
    ENTER_QUESTION_COUNT = 26  # Ввод количества случайных заданий для режима "все"
    ENTER_ASSIGNMENT_TITLE = 27  # Ввод названия домашнего задания

    # Просмотр статистики
    VIEW_STATISTICS = 30

    # Дарение подписок
    GIFT_SUBSCRIPTION_MENU = 40
    SELECT_STUDENT_FOR_GIFT = 41
    SELECT_GIFT_DURATION = 42
    CONFIRM_GIFT = 43

    # Промокоды
    CREATE_PROMO_CODE = 50
    SET_PROMO_USES = 51
    SET_PROMO_DURATION = 52

    # Проверка ответов учеников
    ENTERING_COMMENT = 60  # Ввод комментария к ответу ученика
    OVERRIDING_SCORE = 61  # Переоценка ответа

    # Кастомные задания
    ENTER_CUSTOM_QUESTION = 70  # Ввод текста кастомного вопроса
    REVIEW_CUSTOM_QUESTIONS = 71  # Просмотр и подтверждение всех вопросов
    SELECT_CUSTOM_QUESTION_TYPE = 72  # Выбор типа задания для кастомного вопроса
    ENTER_CUSTOM_QUESTION_ANSWER = 73  # Ввод правильного ответа/критериев оценки

    # Браузер заданий
    BROWSER_SEARCH = 74  # Поиск заданий в браузере

    # Оплата подписки
    PAYMENT_ENTERING_PROMO = 80  # Ввод промокода для оплаты подписки
    PAYMENT_ENTERING_EMAIL = 81  # Ввод email для оплаты подписки
    PAYMENT_AUTO_RENEWAL_CHOICE = 82  # Выбор типа оплаты (с автопродлением или разовая)

    # Быстрая проверка работ (Quick Check)
    QUICK_CHECK_MENU = 90  # Меню быстрой проверки
    QUICK_CHECK_SELECT_TYPE = 91  # Выбор типа задания
    QUICK_CHECK_ENTER_CONDITION = 92  # Ввод условия задания
    QUICK_CHECK_ENTER_ANSWER = 93  # Ввод ответа (одиночная проверка)
    QUICK_CHECK_ENTER_ANSWERS_BULK = 94  # Ввод ответов (массовая проверка)
    QUICK_CHECK_VIEWING_RESULT = 95  # Просмотр результата проверки
    QUICK_CHECK_HISTORY = 96  # История проверок
    QUICK_CHECK_TEMPLATES = 97  # Управление шаблонами
    QUICK_CHECK_SAVE_TEMPLATE = 98  # Сохранение шаблона

    # Проверка варианта (Variant Check)
    VARIANT_CHECK_MENU = 200  # Меню проверки варианта
    VARIANT_CHECK_SOURCE = 201  # Выбор источника (внешний/из бота)
    VARIANT_CHECK_SELECT_TASKS = 202  # Выбор заданий для проверки
    VARIANT_CHECK_ENTER_KEYS = 203  # Ввод ключей/критериев (для внешнего варианта)
    VARIANT_CHECK_ENTER_ANSWER = 204  # Ввод ответа ученика на текущее задание
    VARIANT_CHECK_CONFIRM = 205  # Подтверждение перед проверкой
    VARIANT_CHECK_RESULTS = 206  # Просмотр результатов
    VARIANT_CHECK_BATCH_NEXT = 207  # Пакетный режим: ввод следующего ученика
    VARIANT_CHECK_ENTER_SOURCE_TEXT = 208  # Ввод текста-источника (для задания 18)

    # Быстрая проверка: ввод текста-источника (для задания 18)
    QUICK_CHECK_ENTER_SOURCE_TEXT = 99


class StudentStates(IntEnum):
    """Состояния для учеников (связь с учителем)"""
    # Подключение к учителю
    ENTER_TEACHER_CODE = 100
    CONFIRM_TEACHER = 101

    # Домашние задания
    HOMEWORK_LIST = 110
    HOMEWORK_DETAIL = 111
    DOING_HOMEWORK = 112

    # Активация промокода
    ENTER_PROMO_CODE = 120
