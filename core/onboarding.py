"""
Интерактивный onboarding для новых пользователей с A/B тестированием.

Цель: Превратить 77% bounced пользователей в активных.

Варианты онбординга (A/B тест):
- control: AI-демо → 1 вопрос → trial (текущий)
- no_question: AI-демо → сразу trial (без вопроса)
- instant_value: Бесплатный вопрос → AI-демо → trial
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    CallbackQueryHandler
)
from telegram.constants import ParseMode
from datetime import datetime
from core import db
from analytics.ab_testing import assign_user_to_variant, get_user_variant, track_ab_conversion

logger = logging.getLogger(__name__)

# Состояния onboarding
ONBOARDING_WELCOME = 0
ONBOARDING_QUESTION_1 = 1
ONBOARDING_QUESTION_2 = 2
ONBOARDING_QUESTION_3 = 3
ONBOARDING_AI_DEMO = 4
ONBOARDING_TRIAL_OFFER = 5

# Простые демо-вопросы для onboarding
DEMO_QUESTIONS = [
    {
        "id": "demo_1",
        "question": "🎯 <b>Вопрос 1 из 3</b>\n\n<b>Что такое социализация?</b>",
        "options": [
            "A) Процесс усвоения социальных норм",
            "B) Общение с друзьями",
            "C) Поиск работы",
            "D) Учеба в школе"
        ],
        "correct": 0,
        "explanation": "✅ <b>Правильно!</b>\n\nСоциализация — это процесс усвоения индивидом социальных норм, ценностей и моделей поведения."
    },
    {
        "id": "demo_2",
        "question": "🎯 <b>Вопрос 2 из 3</b>\n\n<b>К какой сфере общества относятся банки?</b>",
        "options": [
            "A) Политическая",
            "B) Экономическая",
            "C) Социальная",
            "D) Духовная"
        ],
        "correct": 1,
        "explanation": "✅ <b>Правильно!</b>\n\nБанки относятся к экономической сфере — они управляют финансами и кредитами."
    },
    {
        "id": "demo_3",
        "question": "🎯 <b>Вопрос 3 из 3</b>\n\n<b>Что НЕ является признаком государства?</b>",
        "options": [
            "A) Территория",
            "B) Суверенитет",
            "C) Общий язык",
            "D) Налоги"
        ],
        "correct": 2,
        "explanation": "✅ <b>Правильно!</b>\n\nОбщий язык не обязателен для государства. Например, в Швейцарии 4 государственных языка."
    }
]


async def should_start_onboarding(user_id: int) -> bool:
    """
    Проверяет, нужен ли onboarding пользователю.

    Критерии:
    - Пользователь новый (< 1 дня с регистрации)
    - Не решил ни одного вопроса
    - Не проходил onboarding ранее
    """
    try:
        # Проверяем, проходил ли уже onboarding
        user_data = await db.get_user_data(user_id)
        if user_data and user_data.get('onboarding_completed'):
            return False

        # Проверяем количество ответов
        conn = await db.get_connection()
        cursor = await conn.execute(
            "SELECT COUNT(*) FROM answered_questions WHERE user_id = ?",
            (user_id,)
        )
        answer_count = (await cursor.fetchone())[0]

        # Если уже решал вопросы - onboarding не нужен
        if answer_count > 0:
            return False

        # Проверяем дату регистрации
        cursor = await conn.execute(
            "SELECT first_seen FROM users WHERE user_id = ?",
            (user_id,)
        )
        row = await cursor.fetchone()

        if row and row[0]:
            first_seen = datetime.fromisoformat(row[0])
            days_since_registration = (datetime.now() - first_seen).days

            # Onboarding только для совсем новых (< 7 дней)
            return days_since_registration < 7

        return True  # Новый пользователь

    except Exception as e:
        logger.error(f"Error checking onboarding status for user {user_id}: {e}")
        return False


async def start_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Начало onboarding процесса (вызывается из retention-нотификаций).
    ВАЖНО: Использует новый флоу с A/B тестами!
    """
    query = update.callback_query

    user = update.effective_user
    user_id = user.id
    user_name = user.first_name or "друг"

    # Назначаем пользователя на вариант A/B теста если ещё не назначен
    variant = context.user_data.get('ab_variant')
    if not variant:
        variant = await assign_user_to_variant(user_id, 'onboarding_flow')
        context.user_data['ab_variant'] = variant
        logger.info(f"Assigning A/B variant to returning user {user_id}: {variant}")

    # Сохраняем метку начала onboarding
    context.user_data['onboarding_started'] = datetime.now().isoformat()
    context.user_data['onboarding_correct_answers'] = 0

    # Вариант C: INSTANT VALUE - сразу даём попробовать вопрос
    if variant == 'instant_value':
        # Отвечаем на callback перед редактированием сообщения
        if query:
            await query.answer()

        welcome_text = f"""👋 <b>С возвращением, {user_name}!</b>

🎓 Попробуй прямо сейчас!
Вот простой вопрос из ЕГЭ. Выбери ответ и получи мгновенную проверку 👇
"""
        question_data = DEMO_QUESTIONS[0]
        context.user_data['current_question'] = 0

        # Прогресс-бар
        progress = "●○○"  # 1 из 3 шагов
        progress_text = f"<i>{progress} Шаг 1 из 3</i>\n\n"

        text = welcome_text + "\n" + progress_text + question_data['question'] + "\n\n"

        # Кнопки для ответов
        keyboard_buttons = []
        for i, option in enumerate(question_data['options']):
            keyboard_buttons.append([
                InlineKeyboardButton(
                    option,
                    callback_data=f"onboarding_answer_0_{i}"
                )
            ])

        if query:
            await query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup(keyboard_buttons),
                parse_mode=ParseMode.HTML
            )
        else:
            await update.message.reply_text(
                text,
                reply_markup=InlineKeyboardMarkup(keyboard_buttons),
                parse_mode=ParseMode.HTML
            )

        return ONBOARDING_QUESTION_1

    # Варианты A и B: показываем AI-демо первым
    else:
        # Если вызвано через callback (из /start), сразу показываем AI-демо
        # НЕ вызываем query.answer() здесь - show_ai_demo сделает это
        if query:
            return await show_ai_demo(update, context)

        # Если вызвано не через callback (из retention), показываем приветствие
        welcome_text = f"""👋 <b>С возвращением, {user_name}!</b>

🎓 Я — твой ИИ-репетитор по обществознанию с искусственным интеллектом.

<b>Сейчас покажу тебе секретный инструмент,</b> из-за которого сюда приходят:

🤖 <b>ИИ-проверка заданий 19-25</b>
Проверяю как эксперт ФИПИ, только мгновенно.

⏱ <b>Это займёт 30 секунд</b>
Готов посмотреть?
"""

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 Показывай!", callback_data="onboarding_ai_demo")]
        ])

        await update.message.reply_text(
            welcome_text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )

        return ONBOARDING_WELCOME


async def show_question(update: Update, context: ContextTypes.DEFAULT_TYPE, question_num: int):
    """Показывает вопрос из onboarding."""
    query = update.callback_query
    await query.answer()

    question_data = DEMO_QUESTIONS[question_num]
    context.user_data['current_question'] = question_num

    # Gamification: прогресс-бар
    # Для варианта "control" это шаг 2 из 3 (AI-демо уже был)
    # AI-демо (1) → Вопрос (2) → Trial (3)
    progress = "●●○"  # 2 из 3 шагов
    progress_text = f"<i>{progress} Шаг 2 из 3</i>\n\n"

    # Формируем текст с вариантами
    text = progress_text + question_data['question'] + "\n\n"

    # Создаем кнопки для ответов
    keyboard = []
    for i, option in enumerate(question_data['options']):
        keyboard.append([
            InlineKeyboardButton(
                option,
                callback_data=f"onboarding_answer_{question_num}_{i}"
            )
        ])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )

    # Возвращаем соответствующее состояние
    return ONBOARDING_QUESTION_1 + question_num


async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ответа на вопрос."""
    query = update.callback_query
    await query.answer()

    # Парсим callback_data
    _, _, question_num_str, answer_str = query.data.split('_')
    question_num = int(question_num_str)
    answer = int(answer_str)

    question_data = DEMO_QUESTIONS[question_num]
    is_correct = answer == question_data['correct']

    if is_correct:
        context.user_data['onboarding_correct_answers'] = \
            context.user_data.get('onboarding_correct_answers', 0) + 1

    # Показываем объяснение
    text = question_data['explanation']

    # Проверяем вариант A/B теста
    variant = context.user_data.get('ab_variant', 'control')

    # Вариант C (instant_value): после вопроса показываем AI-демо
    if variant == 'instant_value':
        text += f"\n\n🎉 <b>Отлично!</b>"

        if is_correct:
            text += " Правильный ответ!"
        else:
            text += " Ничего страшного, практика поможет!"

        text += "\n\n<b>Теперь покажу тебе секретный инструмент,</b> из-за которого сюда приходят 👇"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🤖 Показать AI-проверку", callback_data="onboarding_ai_demo")]
        ])

        await query.edit_message_text(
            text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )

        return ONBOARDING_AI_DEMO

    # Варианты A и B (control, no_question): после вопроса сразу trial
    else:
        text += f"\n\n🎉 <b>Отлично! Теперь ты знаешь, как работает бот!</b>"

        if is_correct:
            text += "\n\n⭐ <b>Правильный ответ!</b> У тебя хорошие шансы сдать ЕГЭ на высокий балл!"
        else:
            text += "\n\n💪 <b>Ничего страшного!</b> Практика поможет улучшить результат. Здесь есть 1000+ вопросов для тренировки!"

        text += "\n\n<b>Что дальше?</b>\n"
        text += "✅ 1000+ вопросов тестовой части (бесплатно)\n"
        text += "✅ 3 AI-проверки в неделю (бесплатно)\n"
        text += "💎 Безлимитные AI-проверки (trial 1₽)\n\n"
        text += "👇 Выбери, что тебе интересно:"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎁 Активировать trial (1₽)", callback_data="onboarding_trial")],
            [InlineKeyboardButton("🆓 Начать бесплатную подготовку", callback_data="onboarding_complete")]
        ])

        await query.edit_message_text(
            text,
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )

        return ONBOARDING_TRIAL_OFFER


async def start_first_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает первый вопрос onboarding."""
    return await show_question(update, context, 0)


async def show_next_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переход к следующему вопросу."""
    query = update.callback_query
    question_num = int(query.data.split('_')[-1])

    return await show_question(update, context, question_num)


async def show_ai_demo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Показывает демо AI-проверки с A/B тестированием разных флоу.

    Варианты:
    - control: AI-демо → 1 вопрос → trial (стандартный)
    - no_question: AI-демо → сразу trial (без вопроса)
    - instant_value: уже показали вопрос, теперь AI-демо → trial
    """
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Проверяем, уже назначен ли вариант (для instant_value назначается в /start)
    variant = context.user_data.get('ab_variant')
    if not variant:
        # Назначаем вариант только если ещё не назначен
        variant = await assign_user_to_variant(user_id, 'onboarding_flow')
        context.user_data['ab_variant'] = variant
        logger.info(f"User {user_id} assigned to onboarding variant: {variant}")

    # Gamification: прогресс-бар
    # Для instant_value это шаг 2 (вопрос был первым)
    # Для остальных это шаг 1
    if variant == 'instant_value':
        progress = "●●○"  # 2 из 3 шагов
        progress_text = f"<i>{progress} Шаг 2 из 3</i>\n\n"
    else:
        progress = "●○○"  # 1 из 3 шагов
        progress_text = f"<i>{progress} Шаг 1 из 3</i>\n\n"

    demo_text = progress_text + """🤖 <b>ИИ-проверка — твой секретный инструмент</b>

Задания второй части (19-25) проверяет не просто программа, а <b>искусственный интеллект</b>, обученный на критериях ФИПИ.

<b>Вот реальный пример:</b>

📝 <b>Задание 24: Составить план "Семья как социальный институт"</b>

❌ <b>Ответ ученика (2 балла):</b>
1. Понятие семьи
2. Типы семей
   а) Нуклеарная семья
   б) Расширенная семья
   в) Неполная семья
3. Функции семьи

🤖 <b>Оценка ИИ:</b>
"<i>План раскрывает тему, но только один пункт детализирован. По критериям ФИПИ — 2 из 4 баллов.</i>"

✅ <b>После улучшения (4 балла):</b>
1. Семья как социальный институт
   а) Понятие семьи
   б) Брак как основа семьи
   в) Роль семьи в обществе
2. Типы семейных структур
   а) По числу поколений (нуклеарная, расширенная)
   б) По составу родителей (полная, неполная)
   в) По количеству детей (многодетная, малодетная)
3. Функции семьи в обществе
   а) Репродуктивная функция
   б) Социализация и воспитание детей
   в) Экономическая и хозяйственная поддержка

💎 <b>Результат: +2 балла на ЕГЭ!</b>
"""

    # Разные кнопки в зависимости от варианта A/B теста
    if variant == 'no_question':
        # Вариант B: сразу к trial без вопроса
        demo_text += "\n\n<b>Готов попробовать на своих заданиях?</b>"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎁 Активировать trial (1₽)", callback_data="onboarding_trial")],
            [InlineKeyboardButton("🆓 Продолжить бесплатно", callback_data="onboarding_complete")]
        ])
        next_state = ONBOARDING_TRIAL_OFFER
    elif variant == 'instant_value':
        # Вариант C: уже показали вопрос, теперь сразу trial
        demo_text += "\n\n<b>Понравилось? Теперь можешь получить безлимитный доступ!</b>"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎁 Попробовать за 1₽ (7 дней)", callback_data="onboarding_trial")],
            [InlineKeyboardButton("🆓 Остаться на бесплатном", callback_data="onboarding_complete")]
        ])
        next_state = ONBOARDING_TRIAL_OFFER
    else:
        # Вариант A (control): стандартный флоу с вопросом
        demo_text += "\n\n<b>Теперь твоя очередь:</b>\nПопробуй решить один простой вопрос, чтобы я показал тебе остальные возможности 👇"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎯 Попробовать прямо сейчас!", callback_data="onboarding_start")],
            [InlineKeyboardButton("🎁 Сразу к trial (1₽)", callback_data="onboarding_trial")],
            [InlineKeyboardButton("🆓 Бесплатный доступ", callback_data="onboarding_complete")]
        ])
        next_state = ONBOARDING_AI_DEMO

    await query.edit_message_text(
        demo_text,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )

    return next_state


async def handle_trial_offer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора trial."""
    query = update.callback_query
    await query.answer()

    # Gamification: последний шаг!
    progress = "●●●"  # 3 из 3 шагов - завершение!
    progress_text = f"<i>{progress} Финальный шаг!</i>\n\n"

    trial_text = progress_text + """🎁 <b>Пробный период за 1 рубль</b>

<b>Что получишь на 7 дней:</b>
✅ Безлимитные ИИ-проверки заданий 19-25
✅ Персональные рекомендации по каждому ответу
✅ Эталонные примеры ответов
✅ Доступ ко всем тренировочным модулям

💰 <b>Стоимость:</b> всего 1₽ (вместо 249₽)

⏰ <b>Почему так дёшево?</b>
Мы хотим, чтобы ты попробовал и убедился в качестве. После пробного периода — 249₽/мес.

🔒 <b>Безопасно:</b> оплата через Тинькофф

<b>Активировать пробный период?</b>
"""

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Оплатить 1₽", callback_data="subscribe_trial_7days")],
        [InlineKeyboardButton("⬅️ Назад к бесплатному", callback_data="onboarding_complete")]
    ])

    await query.edit_message_text(
        trial_text,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )

    return ONBOARDING_TRIAL_OFFER


async def handle_payment_redirect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработка перехода к оплате из онбординга.
    Завершаем онбординг и напрямую вызываем payment handler.
    """
    user_id = update.effective_user.id

    # Помечаем онбординг как завершенный (пользователь перешел к оплате)
    try:
        conn = await db.get_connection()
        await conn.execute(
            """UPDATE users
               SET onboarding_completed = 1,
                   onboarding_completed_at = datetime('now')
               WHERE user_id = ?""",
            (user_id,)
        )
        await conn.commit()

        # Трекинг: пользователь перешел к оплате из онбординга
        ab_variant = context.user_data.get('ab_variant', 'unknown')
        await db.track_funnel_event(user_id, 'onboarding_payment_redirect', {
            'ab_variant': ab_variant
        })
        logger.info(f"User {user_id} redirected to payment from onboarding (variant: {ab_variant})")

    except Exception as e:
        logger.error(f"Error marking onboarding as completed for user {user_id}: {e}")

    # Очищаем данные onboarding
    context.user_data.pop('onboarding_started', None)
    context.user_data.pop('onboarding_correct_answers', None)
    context.user_data.pop('current_question', None)

    # Вызываем payment handler напрямую, чтобы обработать подписку
    try:
        from payment.handlers import standalone_pay_handler
        await standalone_pay_handler(update, context)
    except Exception as e:
        logger.error(f"Error calling payment handler from onboarding: {e}")
        # Fallback: показываем сообщение об ошибке
        query = update.callback_query
        if query:
            await query.answer("Произошла ошибка. Попробуйте через /subscribe", show_alert=True)

    return ConversationHandler.END


async def complete_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Завершение onboarding."""
    query = update.callback_query
    await query.answer("🎉 Отлично! Теперь ты готов к подготовке!")

    user_id = update.effective_user.id

    # Сохраняем метку завершения onboarding
    try:
        conn = await db.get_connection()
        await conn.execute(
            """UPDATE users
               SET onboarding_completed = 1,
                   onboarding_completed_at = datetime('now')
               WHERE user_id = ?""",
            (user_id,)
        )
        await conn.commit()

        # A/B test tracking: onboarding completed
        ab_variant = context.user_data.get('ab_variant', 'unknown')
        await track_ab_conversion(
            user_id=user_id,
            test_name='onboarding_flow',
            conversion_type='onboarding_completed',
            value=0
        )
        logger.info(f"User {user_id} completed onboarding (variant: {ab_variant})")

        # Трекинг для аналитики
        await db.track_funnel_event(user_id, 'onboarding_completed', {
            'correct_answers': context.user_data.get('onboarding_correct_answers', 0),
            'duration_seconds': (
                datetime.now() - datetime.fromisoformat(context.user_data.get('onboarding_started', datetime.now().isoformat()))
            ).seconds,
            'ab_variant': ab_variant
        })

    except Exception as e:
        logger.error(f"Error completing onboarding for user {user_id}: {e}")

    completion_text = """🎓 <b>Обучение завершено!</b>

Теперь ты готов к подготовке! Вот что доступно:

🆓 <b>БЕСПЛАТНО навсегда:</b>
• Тестовая часть (задания 1-16)
• 3 ИИ-проверки в неделю для заданий 19-25
• Трекинг прогресса

💎 <b>ПОДПИСКА (249₽/мес):</b>
• Безлимитные ИИ-проверки заданий 19-25
• Подробный разбор каждого ответа
• Эталонные примеры решений

👇 <b>Выбери раздел:</b>
"""

    # Получаем главное меню
    from core.app import show_main_menu_with_access
    keyboard = await show_main_menu_with_access(context, user_id)

    await query.edit_message_text(
        completion_text,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )

    # Очищаем данные onboarding
    context.user_data.pop('onboarding_started', None)
    context.user_data.pop('onboarding_correct_answers', None)
    context.user_data.pop('current_question', None)

    return ConversationHandler.END


async def skip_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пропуск onboarding."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Отмечаем, что пользователь пропустил
    try:
        conn = await db.get_connection()
        await conn.execute(
            """UPDATE users
               SET onboarding_completed = 1,
                   onboarding_skipped = 1,
                   onboarding_completed_at = datetime('now')
               WHERE user_id = ?""",
            (user_id,)
        )
        await conn.commit()

        # Трекинг
        await db.track_funnel_event(user_id, 'onboarding_skipped')

    except Exception as e:
        logger.error(f"Error skipping onboarding for user {user_id}: {e}")

    skip_text = """⏭️ <b>Обучение пропущено</b>

Ничего страшного! Ты всегда можешь вернуться к нему через /start

👇 <b>Выбери раздел для подготовки:</b>
"""

    from core.app import show_main_menu_with_access
    keyboard = await show_main_menu_with_access(context, user_id)

    await query.edit_message_text(
        skip_text,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )

    return ConversationHandler.END


async def skip_onboarding_before_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пропуск onboarding до начала ConversationHandler."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Отмечаем, что пользователь пропустил
    try:
        conn = await db.get_connection()
        await conn.execute(
            """UPDATE users
               SET onboarding_completed = 1,
                   onboarding_skipped = 1,
                   onboarding_completed_at = datetime('now')
               WHERE user_id = ?""",
            (user_id,)
        )
        await conn.commit()

        # Трекинг
        await db.track_funnel_event(user_id, 'onboarding_skipped')

    except Exception as e:
        logger.error(f"Error skipping onboarding for user {user_id}: {e}")

    skip_text = """⏭️ <b>Обучение пропущено</b>

Ничего страшного! Ты всегда можешь вернуться к нему через /start

👇 <b>Выбери раздел для подготовки:</b>
"""

    from core.app import show_main_menu_with_access
    keyboard = await show_main_menu_with_access(context, user_id)

    await query.edit_message_text(
        skip_text,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )

    return None  # Standalone handler, не в ConversationHandler


def get_onboarding_handler():
    """
    Возвращает ConversationHandler для onboarding с A/B тестами.

    Поддерживаемые флоу:
    - Control: AI-демо → вопрос → trial
    - No question: AI-демо → trial
    - Instant value: вопрос → AI-демо → trial
    """
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_onboarding, pattern="^start_onboarding$")
        ],
        states={
            # ONBOARDING_WELCOME: Начальное состояние после start_onboarding
            # Переход к AI-демо (для вариантов A и B)
            ONBOARDING_WELCOME: [
                CallbackQueryHandler(show_ai_demo, pattern="^onboarding_ai_demo$")
                # Кнопка "Пропустить" удалена - онбординг обязательный!
            ],

            # ONBOARDING_QUESTION_1: Ответ на первый вопрос
            # Для вариантов A (control) и C (instant_value)
            ONBOARDING_QUESTION_1: [
                CallbackQueryHandler(handle_answer, pattern="^onboarding_answer_")
            ],

            # ONBOARDING_AI_DEMO: Показ AI-демо
            # Переходы в зависимости от варианта:
            # - Control: к вопросу (onboarding_start)
            # - No question: к trial
            # - Instant value: показываем AI-демо после вопроса (onboarding_ai_demo)
            ONBOARDING_AI_DEMO: [
                CallbackQueryHandler(show_ai_demo, pattern="^onboarding_ai_demo$"),
                CallbackQueryHandler(start_first_question, pattern="^onboarding_start$"),
                CallbackQueryHandler(handle_trial_offer, pattern="^onboarding_trial$"),
                CallbackQueryHandler(complete_onboarding, pattern="^onboarding_complete$"),
                CallbackQueryHandler(handle_payment_redirect, pattern="^subscribe_trial_7days$")
            ],

            # ONBOARDING_TRIAL_OFFER: Предложение trial
            ONBOARDING_TRIAL_OFFER: [
                CallbackQueryHandler(handle_trial_offer, pattern="^onboarding_trial$"),
                CallbackQueryHandler(complete_onboarding, pattern="^onboarding_complete$"),
                CallbackQueryHandler(handle_payment_redirect, pattern="^subscribe_trial_7days$")
            ]
        },
        fallbacks=[
            # Fallback только для отмены через команду
            CommandHandler("cancel", skip_onboarding)
        ],
        name="onboarding",
        persistent=True,
        allow_reentry=True  # Разрешаем перезапуск онбординга если пользователь вернулся через /start
    )
