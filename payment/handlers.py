# payment/handlers.py - адаптированная версия с поддержкой модулей
"""Обработчики команд для работы с платежами (модульная версия)."""

from __future__ import annotations  # Python 3.8 compatibility

import logging
from datetime import datetime, timedelta, timezone
import uuid
from typing import Optional, Dict, Any, List
import json
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update)
from telegram.error import BadRequest
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ContextTypes, 
    ConversationHandler,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters
)
from .promo_handler import (
    PromoCodeManager, 
    show_promo_input, 
    handle_promo_input,
    skip_promo,
    retry_promo,
    PROMO_INPUT
)
from .auto_renewal_consent import (
    AutoRenewalConsent, 
    show_auto_renewal_choice,
    SHOWING_TERMS, 
    CONSENT_CHECKBOX, 
    FINAL_CONFIRMATION
)
from core.db import DATABASE_FILE
import re
import aiosqlite
from core.error_handler import safe_handler
from .config import (
    SUBSCRIPTION_PLANS,
    SUBSCRIPTION_MODE,
    DURATION_DISCOUNTS,
    MODULE_PLANS,
    PAYMENT_ADMIN_CHAT_ID,
    ALL_PAID_MODULES,
    get_plan_price_kopecks,
    get_available_plans
)
from .subscription_manager import SubscriptionManager
from .tinkoff import TinkoffPayment

# Состояния для платежного процесса (строковые для ConversationHandler)
PROMO_INPUT = "promo_input"
CHOOSING_PLAN = "choosing_plan"
CHOOSING_DURATION = "choosing_duration"
ENTERING_EMAIL = "entering_email"
CONFIRMING = "confirming"
CHOOSING_MODULES = "choosing_modules"
AUTO_RENEWAL_CHOICE = "auto_renewal_choice"
FINAL_CONSENT = "final_consent"
PAYMENT_STATES = [
    CHOOSING_PLAN, CHOOSING_MODULES, CHOOSING_DURATION,
    PROMO_INPUT,
    ENTERING_EMAIL, FINAL_CONSENT, AUTO_RENEWAL_CHOICE, CONFIRMING
]

logger = logging.getLogger(__name__)

# Инициализация менеджеров
subscription_manager = SubscriptionManager()
tinkoff_payment = TinkoffPayment()


@safe_handler()
async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /subscribe - показывает планы подписки."""
    # Проверяем источник вызова
    if update.callback_query:
        # Вызов из callback - используем show_modular_interface
        return await show_modular_interface(update, context)
    elif update.message:
        # Вызов из команды - показываем интерфейс
        if SUBSCRIPTION_MODE == 'modular':
            return await show_modular_interface(update, context)
        else:
            return await show_unified_plans(update, context)
    else:
        # Неизвестный источник
        logger.error("cmd_subscribe called without message or callback_query")
        return ConversationHandler.END

@safe_handler()
async def check_payment_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверяет статус платежа по запросу пользователя."""
    query = update.callback_query
    await query.answer("Проверяю статус платежа...")
    
    user_id = update.effective_user.id
    
    # Получаем менеджер подписок
    subscription_manager = context.bot_data.get('subscription_manager', SubscriptionManager())
    
    # Проверяем последний платеж пользователя
    try:
        # Получаем последний платеж из БД
        from core.config import DATABASE_FILE
        async with aiosqlite.connect(DATABASE_FILE) as conn:
            cursor = await conn.execute("""
                SELECT order_id, status, plan_id, amount
                FROM payments
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT 1
            """, (user_id,))
            
            payment = await cursor.fetchone()
            
            if not payment:
                await query.edit_message_text(
                    "❌ Платеж не найден.\n\n"
                    "Возможно, вы еще не создавали платеж или он был отменен."
                )
                return
            
            order_id, status, plan_id, amount = payment
            
            # Проверяем статус платежа в Tinkoff
            from payment.tinkoff import TinkoffPayment
            tinkoff = TinkoffPayment()
            payment_status = await tinkoff.check_payment_status(order_id)
            
            if payment_status == 'CONFIRMED':
                # Платеж подтвержден
                await query.edit_message_text(
                    "✅ <b>Платеж успешно подтвержден!</b>\n\n"
                    "Ваша подписка активирована.\n"
                    "Используйте /my_subscriptions для просмотра деталей.",
                    parse_mode=ParseMode.HTML
                )
                
                # Активируем подписку если еще не активирована
                if status != 'completed':
                    await subscription_manager.activate_subscription(order_id)
                    
            elif payment_status in ['NEW', 'FORM_SHOWED', 'DEADLINE_EXPIRED']:
                # Платеж еще не оплачен
                await query.edit_message_text(
                    "⏳ <b>Платеж ожидает оплаты</b>\n\n"
                    f"Статус: {payment_status}\n"
                    f"Сумма: {amount}₽\n\n"
                    "Если вы уже оплатили, подождите несколько минут и проверьте снова.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔄 Проверить еще раз", callback_data="check_payment")
                    ]])
                )
            elif payment_status in ['REJECTED', 'CANCELED', 'REFUNDED']:
                # Платеж отклонен/отменен
                await query.edit_message_text(
                    f"❌ <b>Платеж отклонен</b>\n\n"
                    f"Статус: {payment_status}\n\n"
                    "Попробуйте создать новый платеж.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔄 Создать новый платеж", callback_data="payment_back")
                    ]])
                )
            else:
                # Неизвестный статус
                await query.edit_message_text(
                    f"❓ Неизвестный статус платежа: {payment_status}\n\n"
                    "Обратитесь к администратору для уточнения."
                )
                
    except Exception as e:
        logger.error(f"Error checking payment status: {e}")
        await query.edit_message_text(
            "❌ Ошибка при проверке статуса платежа.\n\n"
            "Попробуйте позже или обратитесь к администратору."
        )

def validate_email(email: str) -> tuple[bool, str]:
    """
    Валидирует email и возвращает (is_valid, error_message).
    """
    if not email:
        return False, "Email не указан"
    
    # Базовая проверка формата
    email = email.strip().lower()
    
    # Регулярное выражение для email
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    
    if not re.match(email_pattern, email):
        return False, "Неверный формат email"
    
    # Проверка длины
    if len(email) < 6:  # a@b.co минимум
        return False, "Email слишком короткий"
    
    if len(email) > 100:
        return False, "Email слишком длинный"
    
    # Проверка домена
    domain = email.split('@')[1]
    
    # Список распространенных опечаток
    common_typos = {
        'gmail.con': 'gmail.com',
        'gmail.co': 'gmail.com',
        'gmail.ru': 'gmail.com',
        'gmai.com': 'gmail.com',
        'gmial.com': 'gmail.com',
        'gnail.com': 'gmail.com',
        'yamdex.ru': 'yandex.ru',
        'yadex.ru': 'yandex.ru',
        'yandex.com': 'yandex.ru',
        'mail.ri': 'mail.ru',
        'mail.tu': 'mail.ru',
        'maio.ru': 'mail.ru',
        'maol.ru': 'mail.ru',
        'mali.ru': 'mail.ru',
        'outlok.com': 'outlook.com',
        'outlok.ru': 'outlook.com',
        'hotmial.com': 'hotmail.com',
        'hotmai.com': 'hotmail.com'
    }
    
    if domain in common_typos:
        return False, f"Возможна опечатка. Вы имели в виду @{common_typos[domain]}?"
    
    # Проверка на невалидные домены
    invalid_domains = ['gmail.con', 'gmail.co', 'test.com', 'example.com']
    if domain in invalid_domains:
        return False, f"Домен {domain} недействителен"
    
    # Проверка точек в домене
    if '..' in domain:
        return False, "Двойные точки в домене недопустимы"
    
    # Минимальная длина домена
    if len(domain) < 4:  # x.co минимум
        return False, "Домен слишком короткий"
    
    return True, ""

async def show_unified_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает старые единые планы подписки."""
    user_id = update.effective_user.id
    subscription_manager = context.bot_data.get('subscription_manager', SubscriptionManager())
    
    # Проверяем текущую подписку
    subscription = await subscription_manager.check_active_subscription(user_id)
    
    if subscription:
        expires = subscription['expires_at'].strftime('%d.%m.%Y')
        text = f"""✅ <b>У вас есть активная подписка!</b>

План: {SUBSCRIPTION_PLANS[subscription['plan_id']]['name']}
Действует до: {expires}

Используйте /status для просмотра детальной информации."""
        
        # Отправляем сообщение правильным способом
        if update.message:
            await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        elif update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.reply_text(text, parse_mode=ParseMode.HTML)
        
        return ConversationHandler.END
    
    # Показываем доступные планы
    text = "💎 <b>Выберите план подписки:</b>\n\n"

    keyboard = []
    # Получаем доступные тарифы для пользователя (тестовые тарифы видны только админу)
    available_plans = get_available_plans(user_id)
    for plan_id, plan in available_plans.items():
        text += f"<b>{plan['name']}</b>\n"
        text += f"💰 {plan['price_rub']} ₽\n"
        text += f"📝 {plan['description']}\n"
        for feature in plan.get('features', []):
            text += f"  {feature}\n"
        text += "\n"
        
        keyboard.append([
            InlineKeyboardButton(
                f"{plan['name']} - {plan['price_rub']} ₽",
                callback_data=f"pay_plan_{plan_id}"
            )
        ])
    
    keyboard.append([
        InlineKeyboardButton("❌ Отмена", callback_data="pay_cancel")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Отправляем сообщение правильным способом
    if update.message:
        await update.message.reply_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
    elif update.callback_query:
        query = update.callback_query
        await query.answer()
        try:
            await query.edit_message_text(
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
        except Exception:
            await query.message.reply_text(
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
    
    return CHOOSING_PLAN


@safe_handler()
async def show_modular_interface(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает упрощенный интерфейс с двумя тарифами."""
    user_id = update.effective_user.id
    subscription_manager = context.bot_data.get('subscription_manager', SubscriptionManager())

    # Проверяем пробный период
    has_trial = await subscription_manager.has_used_trial(user_id)

    # Получаем активные модули
    modules_data = await subscription_manager.get_user_modules(user_id)
    active_modules = bool(modules_data)

    # Проверяем, привязан ли ученик к учителю
    from teacher_mode.services.teacher_service import get_student_teachers
    student_teachers = await get_student_teachers(user_id)
    has_teacher = len(student_teachers) > 0
    
    # Определяем метод редактирования
    query = update.callback_query
    if query:
        await query.answer()
        edit_func = lambda txt, **kwargs: query.edit_message_text(txt, **kwargs)
    else:
        edit_func = lambda txt, **kwargs: update.message.reply_text(txt, **kwargs)
    
    # Формируем текст
    text = "💎 <b>Подписки на ЕГЭ по обществознанию</b>\n\n"
    
    # Показываем активные модули если есть
    if modules_data:
        text += "✅ <b>Ваши активные модули:</b>\n"
        module_names = {
            'test_part': '📝 Тестовая часть',
            'task19': '🎯 Задание 19',
            'task20': '📖 Задание 20',
            'task24': '💎 Задание 24',
            'task25': '✍️ Задание 25'
        }
        for module in modules_data:
            name = module_names.get(module['module_code'], module['module_code'])
            expires = module['expires_at'].strftime('%d.%m.%Y')
            text += f"• {name} (до {expires})\n"
        text += "\n"
    
    text += "<b>Доступные тарифы:</b>\n\n"
    
    # Пробный период (если не использован)
    if not has_trial:
        text += "🎁 <b>Пробный период</b> — 1₽\n"
        text += "   • Полный доступ на 7 дней\n"
        text += "   • Все задания с проверкой ИИ\n\n"
    
    # Полная подписка - показываем стандартную цену
    # Скидка от учителя применяется автоматически при оплате, если активна
    text += "👑 <b>Полная подписка</b> — 249₽/мес\n\n"

    text += "✅ <b>Вторая часть ЕГЭ — под полным контролем:</b>\n"
    text += "   • Задание 19 — Примеры, которые впечатлят эксперта\n"
    text += "   • Задание 20 — Аргументы на максимум баллов\n"
    text += "   • Задание 24 — Планы, которые не завалят\n"
    text += "   • Задание 25 — Обоснования, достойные 6/6\n\n"
    text += "🤖 <b>ИИ проверяет как строгий эксперт ФИПИ</b>\n"
    text += "💡 <i>Закрывай вторую часть на максимум и получай 90+ баллов!</i>"
    
    # Формируем кнопки
    keyboard = []
    
    # Кнопка пробного периода (если не использован)
    if not has_trial:
        keyboard.append([
            InlineKeyboardButton(
                "🎁 Пробный период - 1₽ (7 дней)",
                callback_data="pay_trial"
            )
        ])
    
    # Кнопка полной подписки - показываем стандартную цену
    # Скидка от учителя применяется автоматически при оплате
    keyboard.append([
        InlineKeyboardButton(
            "👑 Полная подписка - 249₽/мес",
            callback_data="pay_package_full"
        )
    ])

    # Кнопка подписок для учителей
    keyboard.append([
        InlineKeyboardButton("👨‍🏫 Подписки для учителей", callback_data="show_teacher_subscriptions")
    ])

    # Кнопка "Мои подписки" (если есть активные)
    if active_modules:
        keyboard.append([
            InlineKeyboardButton("📋 Мои подписки", callback_data="my_subscriptions")
        ])

    # Кнопка главного меню
    keyboard.append([
        InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")
    ])
    
    await edit_func(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML
    )

    # Всегда возвращаем состояние CHOOSING_PLAN для ConversationHandler
    # чтобы обработчики кнопок работали корректно
    return CHOOSING_PLAN


@safe_handler()
async def show_teacher_plans_in_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает доступные подписки для учителей в магазине."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    from payment.config import get_all_teacher_plans

    teacher_plans = get_all_teacher_plans(user_id)

    text = (
        "👨‍🏫 <b>Подписки для учителей</b>\n\n"
        "Управляйте учениками, создавайте задания и отслеживайте прогресс!\n\n"
        "<b>Выберите подходящий тариф:</b>\n"
    )

    keyboard = []
    for plan in teacher_plans:
        plan_id = plan['plan_id']
        name = plan['name']
        price = plan['price_rub']
        max_students = plan.get('max_students', 0)

        if max_students == -1:
            students_text = "∞ учеников"
        else:
            students_text = f"до {max_students} учеников"

        button_text = f"{name} — {price}₽/мес ({students_text})"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"view_teacher_plan_{plan_id}")])

    keyboard.append([InlineKeyboardButton("« Назад к подпискам", callback_data="subscribe")])
    keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

    return CHOOSING_PLAN


@safe_handler()
async def show_teacher_plan_details_in_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает детали конкретного плана учителя в магазине."""
    query = update.callback_query
    await query.answer()

    # Извлекаем plan_id из callback_data
    plan_id = query.data.replace("view_teacher_plan_", "")

    from payment.config import get_plan_info

    plan = get_plan_info(plan_id)
    if not plan:
        await query.edit_message_text("❌ План не найден")
        return CHOOSING_PLAN

    max_students = plan.get('max_students', 0)
    if max_students == -1:
        students_text = "Безлимит учеников"
    else:
        students_text = f"До {max_students} учеников"

    # Формируем описание плана
    text = f"👨‍🏫 <b>{plan['name']}</b>\n\n"
    text += f"💰 <b>Цена:</b> {plan['price_rub']}₽/месяц\n"
    text += f"👥 <b>Учеников:</b> {students_text}\n\n"

    if 'detailed_description' in plan:
        text += "<b>Возможности:</b>\n"
        for feature in plan['detailed_description']:
            text += f"{feature}\n"
    else:
        text += "<b>Возможности:</b>\n"
        for feature in plan.get('features', []):
            text += f"{feature}\n"

    keyboard = [
        [InlineKeyboardButton("💳 Оформить подписку", callback_data=f"pay_{plan_id}")],
        [InlineKeyboardButton("« Назад к тарифам", callback_data="show_teacher_subscriptions")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)

    return CHOOSING_PLAN


@safe_handler()
async def handle_plan_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик выбора плана подписки (trial, package_full и teacher plans)."""
    query = update.callback_query
    await query.answer()

    # Правильно извлекаем plan_id для teacher планов
    if query.data.startswith("pay_teacher_"):
        plan_id = query.data.replace("pay_teacher_", "")
    else:
        plan_id = query.data.replace("pay_", "")
    logger.info(f"Plan selected: {plan_id}")

    # Обработка пробного периода
    if plan_id == "trial":
        plan_id = "trial_7days"
        context.user_data['is_trial'] = True
        context.user_data['selected_plan'] = plan_id
        context.user_data['duration_months'] = 1
        context.user_data['total_price'] = 1
        context.user_data['base_price'] = 1
        context.user_data['plan_name'] = "🎁 Пробный период 7 дней"

        logger.info(f"Trial selected: price set to 1₽ for user {update.effective_user.id}")

        # Сразу запрашиваем email для триала
        return await request_email_for_trial(update, context)

    # Обработка полной подписки
    elif plan_id == "package_full":
        # Проверяем, привязан ли ученик к учителю
        from teacher_mode.services.teacher_service import get_student_teachers
        user_id = update.effective_user.id
        student_teachers = await get_student_teachers(user_id)
        has_teacher = len(student_teachers) > 0

        # Если ученик привязан к учителю, используем скидочный план
        if has_teacher:
            plan_id = "student_with_teacher"
            logger.info(f"User {user_id} has teacher, using discount plan: {plan_id}")
        else:
            plan_id = "package_full"

        context.user_data['is_trial'] = False
        context.user_data['selected_plan'] = plan_id

        # Получаем информацию о плане
        from payment.config import SUBSCRIPTION_PLANS
        plan = SUBSCRIPTION_PLANS.get(plan_id)

        if not plan:
            logger.error(f"Plan {plan_id} not found in configs!")
            await query.edit_message_text("❌ Ошибка: план не найден")
            return ConversationHandler.END

        # Сохраняем информацию о плане
        context.user_data['plan_info'] = plan
        context.user_data['plan_name'] = plan['name']
        context.user_data['base_price'] = plan['price_rub']

        logger.info(f"Plan info loaded: {plan['name']}, base price: {plan['price_rub']}₽")

        # Показываем варианты длительности
        return await show_duration_options(update, context)

    # Обработка подписок для учителей (teacher_basic, teacher_standard, teacher_premium, test_teacher_*)
    elif plan_id.startswith("teacher_") or plan_id.startswith("test_teacher_"):
        from payment.config import SUBSCRIPTION_PLANS, is_teacher_plan
        from payment.subscription_manager import SubscriptionManager

        # КРИТИЧНО: Проверяем использование trial для teacher_trial_7days и test_teacher_trial_7days
        if plan_id in ("teacher_trial_7days", "test_teacher_trial_7days"):
            subscription_manager = SubscriptionManager()
            user_id = update.effective_user.id

            if await subscription_manager.has_used_teacher_trial(user_id):
                await query.answer(
                    "❌ Вы уже использовали пробный период для учителей",
                    show_alert=True
                )
                logger.warning(f"User {user_id} attempted to use teacher trial twice")
                return CHOOSING_PLAN

        context.user_data['is_trial'] = False
        context.user_data['selected_plan'] = plan_id
        context.user_data['is_teacher_plan'] = True

        # Получаем информацию о плане
        plan = SUBSCRIPTION_PLANS.get(plan_id)

        if not plan or not is_teacher_plan(plan_id):
            logger.error(f"Teacher plan {plan_id} not found in configs!")
            await query.edit_message_text("❌ Ошибка: план не найден")
            return ConversationHandler.END

        # Сохраняем информацию о плане
        context.user_data['plan_info'] = plan
        context.user_data['plan_name'] = plan['name']
        context.user_data['base_price'] = plan['price_rub']

        logger.info(f"Teacher plan info loaded: {plan['name']}, base price: {plan['price_rub']}₽")

        # КРИТИЧНО: Подтверждаем, что пользователь действительно учитель
        tier_names = {
            'teacher_basic': 'Basic (до 10 учеников)',
            'teacher_standard': 'Standard (до 20 учеников)',
            'teacher_premium': 'Premium (безлимит учеников)'
        }
        tier_name = tier_names.get(plan_id, plan['name'])

        confirmation_text = (
            f"⚠️ <b>Подтверждение выбора учительского тарифа</b>\n\n"
            f"Вы выбрали тариф: <b>{tier_name}</b>\n"
            f"Цена: <b>{plan['price_rub']}₽/месяц</b>\n\n"
            f"Этот тариф предназначен для репетиторов и учителей, которые хотят:\n"
            f"• Создавать домашние задания для учеников\n"
            f"• Отслеживать прогресс своих учеников\n"
            f"• Получать аналитику по успеваемости\n"
            f"• Управлять группами учеников\n\n"
            f"<b>Вы действительно учитель/репетитор?</b>"
        )

        keyboard = [
            [InlineKeyboardButton("✅ Да, я учитель", callback_data=f"confirm_teacher_plan:{plan_id}")],
            [InlineKeyboardButton("❌ Нет, выбрать другой тариф", callback_data="subscribe_start")]
        ]

        await query.edit_message_text(
            confirmation_text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return CHOOSING_PLAN

    # Неизвестный план
    else:
        logger.error(f"Unknown plan_id: {plan_id}")
        await query.edit_message_text("❌ Ошибка: неизвестный план")
        return ConversationHandler.END


@safe_handler()
async def handle_teacher_plan_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик подтверждения выбора учительского тарифа.

    ИСПРАВЛЕНО: Добавлена специальная обработка для teacher_free и teacher_trial_7days.
    Для teacher_free (бесплатный тариф) - активация без выбора срока.
    Для teacher_trial_7days - переход к вводу email с фиксированным сроком 7 дней.
    """
    query = update.callback_query
    await query.answer()

    # Извлекаем plan_id из callback_data (формат: confirm_teacher_plan:teacher_basic)
    plan_id = query.data.replace("confirm_teacher_plan:", "")

    logger.info(f"✅ Teacher plan confirmed by user {update.effective_user.id}: {plan_id}")

    # ИСПРАВЛЕНО: Специальная обработка для teacher_free
    if plan_id == 'teacher_free':
        # teacher_free - бесплатный тариф, доступен по умолчанию
        # Просто создаем профиль учителя, который автоматически получает активную подписку на 100 лет
        user_id = update.effective_user.id

        try:
            # Проверяем, есть ли уже профиль учителя
            from teacher_mode.services.teacher_service import get_teacher_profile, create_teacher_profile
            teacher_profile = await get_teacher_profile(user_id)

            # Если профиля нет - создаем его
            if not teacher_profile:
                # Получаем имя пользователя
                user = update.effective_user
                display_name = user.first_name or user.username or f"User {user_id}"

                # Создаем профиль учителя с teacher_free
                # В create_teacher_profile для teacher_free автоматически устанавливается:
                # - has_active_subscription = True
                # - subscription_expires = now + 100 лет
                teacher_profile = await create_teacher_profile(
                    user_id=user_id,
                    display_name=display_name,
                    subscription_tier='teacher_free'
                )

            if teacher_profile:
                text = (
                    "🎉 <b>Бесплатный режим учителя доступен!</b>\n\n"
                    f"🔑 <b>Ваш код для учеников:</b> <code>{teacher_profile.teacher_code}</code>\n\n"
                    "✅ <b>Что вы получили:</b>\n"
                    "• Возможность добавить 1 ученика\n"
                    "• Создание домашних заданий\n"
                    "• Отслеживание прогресса ученика\n"
                    "• Базовая статистика\n\n"
                    "💡 <b>Как использовать:</b>\n"
                    "1. Отправьте код <code>{}</code> своему ученику\n"
                    "2. Ученик вводит код в боте\n"
                    "3. Вы сможете отслеживать его прогресс\n\n"
                    "📈 Хотите больше возможностей? Обновите тариф на платный!"
                ).format(teacher_profile.teacher_code)

                keyboard = [
                    [InlineKeyboardButton("👥 Перейти в режим учителя", callback_data="teacher_menu")],
                    [InlineKeyboardButton("💎 Посмотреть другие тарифы", callback_data="teacher_subscriptions")],
                    [InlineKeyboardButton("◀️ Главное меню", callback_data="main_menu")]
                ]

                await query.edit_message_text(
                    text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
                return ConversationHandler.END
            else:
                await query.edit_message_text(
                    "❌ Ошибка создания профиля учителя.\n"
                    "Пожалуйста, попробуйте позже или обратитесь в поддержку.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("◀️ Назад", callback_data="teacher_subscriptions")
                    ]])
                )
                return ConversationHandler.END

        except Exception as e:
            logger.error(f"Error creating teacher_free profile: {e}")
            import traceback
            traceback.print_exc()
            await query.edit_message_text(
                "❌ Произошла ошибка при создании профиля.\n"
                "Пожалуйста, попробуйте позже.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("◀️ Назад", callback_data="teacher_subscriptions")
                ]])
            )
            return ConversationHandler.END

    # ИСПРАВЛЕНО: Специальная обработка для teacher_trial_7days
    elif plan_id == 'teacher_trial_7days' or plan_id.startswith('test_teacher_trial'):
        # Пробный период учителя - фиксированный срок 7 дней за 1₽
        # Переходим сразу к вводу email, без выбора срока
        context.user_data['duration_months'] = 1
        context.user_data['total_price'] = 1
        from payment.config import get_plan_info
        plan_info = get_plan_info(plan_id)
        context.user_data['plan_name'] = plan_info['name'] if plan_info else "Пробный период учителя"

        return await request_email_for_trial(update, context)

    # Для остальных teacher планов - показываем выбор длительности
    # Все данные уже сохранены в context.user_data в handle_plan_selection
    return await show_duration_options(update, context)


# Также исправим request_email_for_trial:
@safe_handler()
async def request_email_for_trial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрашивает email для пробной подписки."""
    query = update.callback_query
    
    # ВАЖНО: Убеждаемся, что цена установлена правильно
    context.user_data['total_price'] = 1
    context.user_data['duration_months'] = 1
    context.user_data['plan_name'] = "🎁 Пробный период 7 дней"
    
    text = """🎁 <b>Оформление пробного периода</b>

Вы получите:
✅ Полный доступ ко всем материалам
✅ 7 дней бесплатного использования
✅ Возможность оценить все функции

💰 Стоимость: <b>1 ₽</b>

📧 Введите ваш email для отправки чека:"""
    
    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_payment")]]
    
    try:
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except BadRequest as e:
        if "Message is not modified" in str(e):
            logger.debug("Message already showing trial email request")
            await query.answer("Введите ваш email в чат", show_alert=False)
        else:
            logger.error(f"Error in request_email_for_trial: {e}")
            await query.message.reply_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    
    return ENTERING_EMAIL

# ИСПРАВЛЕНО: Удален дубликат функции request_email_for_trial (строка 745-781)
# Правильная версия находится выше (строка 702-742)

@safe_handler()
async def cmd_debug_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для отладки подписки пользователя."""
    user_id = update.effective_user.id
    subscription_manager = context.bot_data.get('subscription_manager', SubscriptionManager())
    
    text = f"🔍 <b>Отладочная информация для пользователя {user_id}</b>\n\n"
    text += f"SUBSCRIPTION_MODE: {SUBSCRIPTION_MODE}\n\n"
    
    # Проверяем общую подписку
    subscription = await subscription_manager.check_active_subscription(user_id)
    if subscription:
        text += "✅ <b>Активная подписка найдена:</b>\n"
        text += f"План: {subscription.get('plan_id')}\n"
        text += f"Истекает: {subscription.get('expires_at')}\n"
        text += f"Активные модули: {subscription.get('active_modules', [])}\n\n"
    else:
        text += "❌ <b>Активная подписка не найдена</b>\n\n"
    
    # Проверяем модули
    if SUBSCRIPTION_MODE == 'modular':
        modules = await subscription_manager.get_user_modules(user_id)
        if modules:
            text += "📦 <b>Активные модули:</b>\n"
            for module in modules:
                text += f"• {module['module_code']} до {module['expires_at']}\n"
        else:
            text += "📦 <b>Нет активных модулей</b>\n"
        
        text += "\n<b>Проверка доступа к модулям:</b>\n"
        for module_code in ALL_PAID_MODULES:
            has_access = await subscription_manager.check_module_access(user_id, module_code)
            text += f"• {module_code}: {'✅' if has_access else '❌'}\n"
    
    # Проверяем последние платежи
    try:
        async with aiosqlite.connect(DATABASE_FILE) as conn:
            cursor = await conn.execute(
                """
                SELECT order_id, plan_id, status, created_at 
                FROM payments 
                WHERE user_id = ? 
                ORDER BY created_at DESC 
                LIMIT 5
                """,
                (user_id)
            )
            payments = await cursor.fetchall()
            
            if payments:
                text += "\n💳 <b>Последние платежи:</b>\n"
                for payment in payments:
                    text += f"• {payment[1]} - {payment[2]} ({payment[3]})\n"
    except Exception as e:
        logger.error(f"Error getting payments: {e}")
    
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

# Также добавим альтернативный обработчик для перехода к выбору модулей
@safe_handler() 
async def back_to_modules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат к общему выбору планов подписки."""
    query = update.callback_query
    if query:
        await query.answer()
    
    # Очищаем выбранные модули
    context.user_data.pop('selected_modules', None)
    
    # Возвращаемся к выбору типа подписки
    return await show_modular_interface(update, context)
    
# Добавьте обработчик для продолжения с выбранными модулями:

@safe_handler()
async def show_duration_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает варианты длительности подписки (1, 3, 6 месяцев)."""
    query = update.callback_query
    if query:
        await query.answer()

    plan_id = context.user_data.get('selected_plan')
    base_price = context.user_data.get('base_price', 249)

    # Импортируем конфигурацию
    from payment.config import DURATION_DISCOUNTS, is_teacher_plan

    # Формируем текст
    text = "⏱ <b>Выберите срок подписки:</b>\n\n"
    text += f"💰 Базовая цена: {base_price}₽/месяц\n\n"

    # Формируем кнопки с вариантами длительности
    keyboard = []

    for months, discount_info in DURATION_DISCOUNTS.items():
        # Рассчитываем цену
        multiplier = discount_info['multiplier']
        total_price = int(base_price * multiplier)
        price_per_month = int(total_price / months)

        # Формируем текст кнопки
        button_text = f"{discount_info['label']}"

        if months == 1:
            button_text += f" — {total_price}₽"
        else:
            savings = discount_info.get('savings', 0)
            button_text += f" — {total_price}₽ (экономия {savings}₽)"

        # Добавляем badge если есть
        if discount_info.get('badge'):
            button_text = f"{discount_info['badge']} {button_text}"

        keyboard.append([
            InlineKeyboardButton(
                button_text,
                callback_data=f"duration_{months}"
            )
        ])

        # Добавляем детали в текст
        if months == 1:
            text += f"📅 <b>1 месяц:</b> {total_price}₽\n"
        else:
            text += f"📅 <b>{months} месяца:</b> {total_price}₽ ({price_per_month}₽/мес)\n"
            text += f"   💰 Экономия: {savings}₽ ({discount_info['discount_percent']}%)\n\n"

    # ИСПРАВЛЕНО: Кнопка назад зависит от типа плана
    if plan_id and is_teacher_plan(plan_id):
        # Для teacher планов - возврат к тарифам учителей
        keyboard.append([
            InlineKeyboardButton("⬅️ Назад к тарифам учителей", callback_data="teacher_subscriptions")
        ])
    else:
        # Для обычных планов - возврат к выбору плана
        keyboard.append([
            InlineKeyboardButton("⬅️ Назад к выбору плана", callback_data="back_to_plans")
        ])

    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Отправляем или редактируем сообщение
    try:
        if query:
            await query.edit_message_text(
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
        else:
            await update.message.reply_text(
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            logger.error(f"Error in show_duration_options: {e}")
            raise
    
    return CHOOSING_DURATION

@safe_handler()
async def handle_duration_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает выбор длительности подписки и переходит к промокоду."""
    query = update.callback_query
    await query.answer()
    
    logger.info(f"handle_duration_selection called with data: {query.data}")
    
    try:
        # Извлекаем длительность из callback_data
        duration = int(query.data.split('_')[1])
        context.user_data['duration_months'] = duration
        
        # Получаем план из контекста
        plan_id = context.user_data.get('selected_plan')
        
        if not plan_id:
            await query.edit_message_text(
                "❌ Ошибка: не выбран план подписки.\n"
                "Пожалуйста, начните заново с /subscribe"
            )
            return ConversationHandler.END
        
        # ИСПРАВЛЕНО: Убираем деление на 100, так как calculate_subscription_price 
        # из payment/handlers.py уже возвращает цену в рублях
        if plan_id.startswith('custom_'):
            # Для кастомных планов берем данные из контекста
            custom_plan = context.user_data.get('custom_plan')
            if custom_plan:
                # Используем локальную функцию, которая возвращает рубли
                total_price = calculate_subscription_price(
                    plan_id, 
                    duration, 
                    custom_plan_data=custom_plan
                )  # БЕЗ деления на 100!
            else:
                # Если custom_plan не найден, рассчитываем на основе модулей
                modules = context.user_data.get('selected_modules', [])
                total_price = calculate_custom_price(modules, duration)
        else:
            # Для обычных планов - используем функцию из handlers.py
            # которая уже возвращает цену в рублях
            total_price = calculate_subscription_price(plan_id, duration)  # БЕЗ деления на 100!
        
        # ВАЖНО: Сохраняем правильную цену в контекст
        context.user_data['total_price'] = total_price
        context.user_data['original_price'] = total_price  # Сохраняем оригинальную цену для промокода
        context.user_data['selected_duration'] = duration
        
        logger.info(f"Selected duration: {duration} months, calculated price: {total_price}₽")
        
        # Получаем информацию о плане
        from payment.config import MODULE_PLANS, SUBSCRIPTION_PLANS, DURATION_DISCOUNTS
        
        if plan_id.startswith('custom_'):
            plan_info = context.user_data.get('custom_plan', {})
            plan_name = plan_info.get('name', 'Индивидуальная подборка')
        elif plan_id in MODULE_PLANS:
            plan_info = MODULE_PLANS[plan_id]
            plan_name = plan_info['name']
        elif plan_id in SUBSCRIPTION_PLANS:
            plan_info = SUBSCRIPTION_PLANS[plan_id]
            plan_name = plan_info['name']
        else:
            plan_name = plan_id
            plan_info = {}
        
        # Сохраняем имя плана для использования в следующих шагах
        context.user_data['plan_name'] = plan_name
        
        # ==== ИЗМЕНЕНО: Переходим к вводу промокода вместо автопродления ====
        # Импортируем функцию показа промокода
        from .promo_handler import show_promo_input
        
        # Переходим к экрану ввода промокода
        return await show_promo_input(update, context)
        
    except ValueError:
        logger.error(f"Invalid duration in callback_data: {query.data}")
        await query.edit_message_text(
            "❌ Ошибка при выборе длительности.\n"
            "Пожалуйста, попробуйте снова."
        )
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in handle_duration_selection: {e}")
        await query.edit_message_text(
            "❌ Произошла ошибка.\n"
            "Пожалуйста, попробуйте позже."
        )
        return ConversationHandler.END

@safe_handler()
async def handle_back_to_duration_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возвращает к выбору длительности подписки из экрана подтверждения."""
    query = update.callback_query
    await query.answer()
    
    # Возвращаемся к выбору длительности
    return await show_duration_options(update, context)


# 3. НОВАЯ ФУНКЦИЯ: Обработчик для кнопки "Продлить/Добавить"
@safe_handler()
async def handle_payment_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик для кнопки 'Продлить/Добавить' - возвращает к началу процесса оплаты."""
    query = update.callback_query
    await query.answer()
    
    # Очищаем старые данные платежа
    payment_keys = ['selected_plan', 'selected_modules', 'custom_plan', 
                   'duration_months', 'total_price', 'plan_name']
    for key in payment_keys:
        context.user_data.pop(key, None)
    
    # Устанавливаем флаг процесса оплаты
    context.user_data['in_payment_process'] = True
    
    # Показываем интерфейс выбора подписки
    return await show_modular_interface(update, context)


@safe_handler()
async def request_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрашивает email пользователя."""
    
    # Определяем источник вызова
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        message = query.message
        is_callback = True
    else:
        message = update.message
        is_callback = False
    
    # Получаем данные о выбранном плане
    plan_id = context.user_data.get('selected_plan')
    duration = context.user_data.get('duration_months', 1)
    total_price = context.user_data.get('total_price')
    plan_name = context.user_data.get('plan_name', 'Подписка')
    
    # Если цена не сохранена, рассчитываем заново
    if not total_price:
        from payment.config import MODULE_PLANS, SUBSCRIPTION_PLANS
        plan = MODULE_PLANS.get(plan_id) or SUBSCRIPTION_PLANS.get(plan_id)
        if plan:
            total_price = calculate_subscription_price(plan_id, duration, plan)
            context.user_data['total_price'] = total_price
        else:
            total_price = 799 * duration  # Fallback
    
    text = f"""📧 <b>Введите email для отправки чека</b>

📦 План: <b>{plan_name}</b>
⏱ Срок: <b>{duration} мес.</b>
💰 К оплате: <b>{total_price} ₽</b>

✉️ На указанный email будет отправлен чек об оплате.

Введите ваш email:"""
    
    keyboard = [[InlineKeyboardButton("❌ Отмена", callback_data="cancel_payment")]]
    
    # Используем try/except для обработки ошибки "Message is not modified"
    try:
        if is_callback:
            await query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            # Если вызов не из callback, отправляем новое сообщение
            await message.reply_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    except BadRequest as e:
        if "Message is not modified" in str(e):
            # Если сообщение не изменилось, просто логируем и продолжаем
            logger.debug("Message already showing email request")
            # Можно показать небольшое уведомление
            if is_callback:
                await query.answer("Введите ваш email в чат", show_alert=False)
        else:
            # Если другая ошибка, пробуем отправить новое сообщение
            logger.error(f"Error in request_email: {e}")
            await message.reply_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    
    return ENTERING_EMAIL

@safe_handler()
async def handle_email_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ввод email и переходит к выбору автопродления."""
    email = update.message.text.strip()
    
    # Валидация email
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, email):
        await update.message.reply_text(
            "❌ Неверный формат email.\n\n"
            "Пожалуйста, введите корректный email адрес:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Отмена", callback_data="cancel_payment")
            ]])
        )
        return ENTERING_EMAIL
    
    # Сохраняем email
    context.user_data['email'] = email
    user_id = update.effective_user.id
    
    # Сохраняем email в БД
    try:
        from payment.subscription_manager import SubscriptionManager
        subscription_manager = SubscriptionManager()
        
        import aiosqlite
        async with aiosqlite.connect(subscription_manager.database_file) as conn:
            await conn.execute(
                """
                INSERT OR REPLACE INTO user_emails (user_id, email, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                """,
                (user_id, email)
            )
            await conn.commit()
            
    except Exception as e:
        logger.error(f"Error saving email: {e}")
    
    # Проверяем, есть ли 100% скидка (или почти 100%)
    promo_code = context.user_data.get('promo_code')
    total_price = context.user_data.get('total_price', 799)
    original_price = context.user_data.get('original_price', total_price)
    
    # Если цена 1 рубль и есть промокод с большой скидкой
    if total_price == 1 and promo_code and original_price > 100:
        # Спрашиваем, хочет ли пользователь активировать бесплатно или оплатить 1 рубль
        text = f"""🎉 <b>Почти бесплатная подписка!</b>

Благодаря промокоду <code>{promo_code}</code> ваша подписка стоит всего 1 ₽!

Это символический платеж, требуемый платежной системой.

Как вы хотите продолжить?"""
        
        keyboard = [
            [InlineKeyboardButton("💳 Оплатить 1 ₽", callback_data="pay_one_ruble")],
            [InlineKeyboardButton("🎁 Активировать бесплатно", callback_data="activate_free")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel_payment")]
        ]
        
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        return CONFIRMING
    
    logger.info(f"User {user_id} entered email: {email}")
    
    # ИЗМЕНЕНИЕ: Показываем экран выбора автопродления вместо прямого перехода к оплате
    await update.message.reply_text(
        f"✅ Email сохранен: {email}\n\n"
        "Настройка способа оплаты...",
        parse_mode=ParseMode.HTML
    )
    
    # Переходим к выбору автопродления
    from .auto_renewal_consent import show_auto_renewal_choice
    return await show_auto_renewal_choice(update, context)


@safe_handler()
async def handle_free_activation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Активирует подписку бесплатно при 100% скидке."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    plan_id = context.user_data.get('selected_plan')
    duration_months = context.user_data.get('duration_months', 1)
    promo_code = context.user_data.get('promo_code')

    # Активируем подписку напрямую
    subscription_manager = context.bot_data.get('subscription_manager')

    if subscription_manager:
        try:
            # Шаг 1: Создаем запись о "платеже" с нулевой суммой
            # Подготавливаем метаданные
            metadata = {
                'promo_code': promo_code,
                'payment_method': 'promo_100',
                'is_teacher_plan': context.user_data.get('is_teacher_plan', False)
            }

            # Создаем запись о платеже
            payment_data = await subscription_manager.create_payment(
                user_id=user_id,
                plan_id=plan_id,
                amount_kopecks=0,  # Бесплатно
                duration_months=duration_months,
                metadata=metadata
            )

            order_id = payment_data['order_id']
            logger.info(f"Created free payment record: {order_id} for user {user_id}")

            # Шаг 2: Активируем подписку
            success = await subscription_manager.activate_subscription(
                order_id=order_id,
                payment_id=f"FREE_{promo_code}"
            )

            if success:
                # Шаг 3: Регистрируем использование промокода
                if promo_code:
                    from payment.promo_handler import promo_manager
                    await promo_manager.apply_promo_code(promo_code, user_id, order_id)

                text = f"""🎉 <b>Подписка активирована!</b>

✅ План успешно активирован благодаря промокоду <code>{promo_code}</code>
📅 Срок действия: {duration_months} месяц(ев)

Используйте /my_subscriptions для просмотра деталей."""
            else:
                text = "❌ Ошибка при активации подписки. Обратитесь в поддержку."

        except Exception as e:
            logger.error(f"Error in free activation: {e}", exc_info=True)
            text = "❌ Ошибка при активации подписки. Обратитесь в поддержку."
    else:
        text = "❌ Сервис временно недоступен."

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📋 Мои подписки", callback_data="my_subscriptions")
        ]])
    )

    return ConversationHandler.END

@safe_handler()
async def handle_pay_one_ruble(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Продолжает с оплатой 1 рубля."""
    query = update.callback_query
    await query.answer()
    
    # Убеждаемся, что цена установлена в 1 рубль
    context.user_data['total_price'] = 1
    
    # Переходим к обычному процессу оплаты
    return await handle_payment_confirmation_with_recurrent(update, context)

@safe_handler()
async def handle_email_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает подтверждение исправленного email."""
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("use_email_"):
        # Извлекаем email из callback_data
        email = query.data.replace("use_email_", "")
        context.user_data['email'] = email
        
        # Сохраняем в БД
        user_id = update.effective_user.id
        try:
            from payment.subscription_manager import SubscriptionManager
            subscription_manager = SubscriptionManager()
            
            import aiosqlite
            async with aiosqlite.connect(subscription_manager.database_file) as conn:
                await conn.execute(
                    """
                    INSERT OR REPLACE INTO user_emails (user_id, email, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    """,
                    (user_id, email)
                )
                await conn.commit()
                
        except Exception as e:
            logger.error(f"Error saving email: {e}")
        
        await query.edit_message_text(
            f"✅ Email сохранен: {email}\n\n"
            "Настройка способа оплаты..."
        )
        
        # Переход к выбору автопродления
        from .auto_renewal_consent import show_auto_renewal_choice
        return await show_auto_renewal_choice(update, context)
    
    elif query.data == "retry_email":
        await query.edit_message_text(
            "📧 Введите ваш email для отправки чека:"
        )
        return ENTERING_EMAIL

@safe_handler()
async def show_auto_renewal_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает опции автопродления после ввода email."""
    query = update.callback_query
    if query:
        await query.answer()
    
    # Получаем информацию о выбранном плане
    plan_id = context.user_data.get('selected_plan')
    duration = context.user_data.get('duration_months', 1)
    
    # Определяем цену для ежемесячного продления
    if plan_id.startswith('custom_'):
        modules = context.user_data.get('selected_modules', [])
        monthly_price = calculate_custom_price(modules, 1)
        plan_name = f"Пакет из {len(modules)} модулей"
    else:
        from .config import MODULE_PLANS, SUBSCRIPTION_PLANS
        plan = MODULE_PLANS.get(plan_id) or SUBSCRIPTION_PLANS.get(plan_id)
        monthly_price = plan['price_rub']
        plan_name = plan['name']
    
    # Текст с полным описанием автопродления (по требованиям Т-Банка)
    text = f"""🔄 <b>Настройка автоматического продления</b>

<b>Ваша подписка:</b>
📦 {plan_name}
⏱ Первый период: {duration} мес.
💰 Далее: {monthly_price} ₽/месяц

<b>Выберите вариант оплаты:</b>

✅ <b>С автопродлением (рекомендуется)</b>
• Автоматическое списание {monthly_price} ₽ каждый месяц
• Непрерывный доступ к материалам
• Уведомление за 3 дня до списания
• Отмена в любой момент через /my_subscriptions
• Первое автосписание: {(datetime.now() + timedelta(days=30*duration)).strftime('%d.%m.%Y')}

❌ <b>Без автопродления</b>
• Разовая оплата на {duration} мес.
• Нужно будет продлевать вручную
• Риск потерять доступ при забывчивости

⚠️ <b>Важно:</b> Выбирая автопродление, вы соглашаетесь на ежемесячные списания до момента отмены подписки."""
    
    keyboard = [
        [InlineKeyboardButton(
            "✅ Включить автопродление", 
            callback_data="consent_auto_renewal"
        )],
        [InlineKeyboardButton(
            "❌ Оплатить без автопродления", 
            callback_data="no_auto_renewal"
        )],
        [InlineKeyboardButton(
            "ℹ️ Подробнее об условиях", 
            callback_data="auto_renewal_terms"
        )]
    ]
    
    if query:
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    return AUTO_RENEWAL_CHOICE  # Новое состояние

@safe_handler()
async def handle_auto_renewal_consent_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает выбор пользователя по автопродлению."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "consent_auto_renewal":
        # Показываем финальное подтверждение с чек-боксом
        await show_final_consent_screen(update, context)
        return FINAL_CONSENT
        
    elif query.data == "no_auto_renewal":
        context.user_data['enable_auto_renewal'] = False
        # Переходим к оплате без автопродления
        return await handle_payment_confirmation_with_recurrent(update, context)
        
    elif query.data == "auto_renewal_terms":
        await show_auto_renewal_terms(update, context)
        return AUTO_RENEWAL_CHOICE

@safe_handler()
async def show_final_consent_screen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает финальный экран согласия с имитацией чек-бокса."""
    query = update.callback_query
    await query.answer()
    
    plan_id = context.user_data.get('selected_plan')
    duration = context.user_data.get('duration_months', 1)
    
    # Определяем цену
    if plan_id.startswith('custom_'):
        modules = context.user_data.get('selected_modules', [])
        monthly_price = calculate_custom_price(modules, 1)
        total_price = calculate_custom_price(modules, duration)
    else:
        plan_info = SUBSCRIPTION_PLANS.get(plan_id, {})
        monthly_price = plan_info.get('price_rub', 799)
        total_price = calculate_subscription_price(plan_id, duration, plan_info)
    
    # Проверяем состояние согласия
    consent_given = context.user_data.get('auto_renewal_consent_confirmed', False)
    checkbox = "☑️" if consent_given else "⬜"
    
    text = f"""📋 <b>Подтверждение автоматического продления</b>

<b>Условия подписки:</b>
💳 Первый платеж: {total_price} ₽ (за {duration} мес.)
🔄 Далее: {monthly_price} ₽ ежемесячно
📅 Дата первого автосписания: {(datetime.now() + timedelta(days=30*duration)).strftime('%d.%m.%Y')}

<b>Согласие на автопродление:</b>
{checkbox} Я соглашаюсь на автоматическое ежемесячное списание {monthly_price} ₽ с моей карты для продления подписки. Я понимаю, что:

- Списание будет происходить автоматически каждый месяц
- Я получу уведомление за 3 дня до списания
- Я могу отменить автопродление в любой момент
- При отмене возврат осуществляется согласно правилам сервиса
- Мои платежные данные будут сохранены в защищенном виде

<b>Нажмите на чек-бокс выше, чтобы дать согласие</b>"""
    
    keyboard = []
    
    # Кнопка-чекбокс
    keyboard.append([InlineKeyboardButton(
        f"{checkbox} Согласие на автопродление",
        callback_data="toggle_consent"
    )])
    
    # Кнопки действий
    if consent_given:
        keyboard.append([InlineKeyboardButton(
            "✅ Подтвердить и перейти к оплате",
            callback_data="confirm_with_auto_renewal"
        )])
    else:
        keyboard.append([InlineKeyboardButton(
            "⚠️ Отметьте согласие для продолжения",
            callback_data="need_consent"
        )])
    
    keyboard.append([InlineKeyboardButton(
        "◀️ Назад",
        callback_data="payment_back"
    )])
    
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    return AUTO_RENEWAL_CHOICE

def calculate_custom_price(modules: List[str], duration_months: int) -> int:
    """
    Рассчитывает стоимость кастомного набора модулей в РУБЛЯХ.

    Args:
        modules: Список ID модулей
        duration_months: Длительность в месяцах

    Returns:
        Итоговая стоимость в РУБЛЯХ
    """
    # Базовая цена за модуль
    price_per_module = 199

    # Подсчитываем количество платных модулей (исключаем test_part)
    paid_modules = [m for m in modules if m not in ['test_part']]
    num_modules = len(paid_modules)

    if num_modules == 0:
        return 0

    # Базовая цена за месяц
    base_price = num_modules * price_per_module

    # Скидка при выборе всех модулей (4 модуля)
    if num_modules >= 4:
        base_price = 249  # Цена полного пакета

    # Умножаем на количество месяцев
    total_price = base_price * duration_months

    return total_price

def calculate_subscription_price(plan_id: str, duration_months: int, custom_plan_data: dict = None) -> int:
    """
    Рассчитывает стоимость подписки в РУБЛЯХ.
    
    Args:
        plan_id: ID плана подписки
        duration_months: Длительность в месяцах
        custom_plan_data: Данные для custom плана (опционально)
        
    Returns:
        Итоговая стоимость в РУБЛЯХ (не в копейках!)
    """
    from payment.config import MODULE_PLANS, SUBSCRIPTION_PLANS, DURATION_DISCOUNTS
    import logging
    
    logger = logging.getLogger(__name__)
    
    # Определяем базовую цену
    if plan_id.startswith('custom_') and custom_plan_data:
        base_price = custom_plan_data.get('price_rub', 799)
        logger.info(f"Using custom plan price: {base_price}₽")
    elif plan_id in MODULE_PLANS:
        base_price = MODULE_PLANS[plan_id].get('price_rub', 799)
        logger.info(f"Using MODULE_PLANS price for {plan_id}: {base_price}₽")
    elif plan_id in SUBSCRIPTION_PLANS:
        base_price = SUBSCRIPTION_PLANS[plan_id].get('price_rub', 799)
        logger.info(f"Using SUBSCRIPTION_PLANS price for {plan_id}: {base_price}₽")
    else:
        # Fallback для неизвестных планов
        base_price = 799
        logger.warning(f"Unknown plan {plan_id}, using default price: {base_price}₽")
    
    # Специальная обработка для пробного периода
    if plan_id == 'trial_7days':
        logger.info(f"Trial period detected, returning 1₽")
        return 1
    
    # Применяем множитель для длительности
    if duration_months in DURATION_DISCOUNTS:
        multiplier = DURATION_DISCOUNTS[duration_months].get('multiplier', duration_months)
        total_price = int(base_price * multiplier)
        logger.info(f"Applied discount for {duration_months} months: {base_price}₽ × {multiplier} = {total_price}₽")
    else:
        # Если нет скидки для этой длительности - просто умножаем
        total_price = base_price * duration_months
        logger.info(f"No discount for {duration_months} months, total={total_price}₽")
    
    logger.info(f"Final calculation: plan={plan_id}, base={base_price}₽, duration={duration_months}m, total={total_price}₽")
    
    return total_price

def get_price_in_kopecks(price_in_rubles: int) -> int:
    """Конвертирует цену из рублей в копейки для API."""
    return price_in_rubles * 100

@safe_handler()
async def toggle_consent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переключает состояние согласия."""
    query = update.callback_query
    
    # Переключаем состояние
    current = context.user_data.get('auto_renewal_consent_confirmed', False)
    context.user_data['auto_renewal_consent_confirmed'] = not current
    
    if not current:
        # Сохраняем время и данные согласия
        context.user_data['consent_timestamp'] = datetime.now().isoformat()
        context.user_data['consent_user_id'] = update.effective_user.id
        await query.answer("✅ Согласие получено", show_alert=False)
    else:
        await query.answer("Согласие отменено", show_alert=False)
    
    # Обновляем экран
    return await show_final_consent_screen(update, context)

@safe_handler()
async def confirm_with_auto_renewal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждает оплату с автопродлением после получения явного согласия."""
    query = update.callback_query
    
    if not context.user_data.get('auto_renewal_consent_confirmed', False):
        await query.answer(
            "⚠️ Необходимо дать согласие на автопродление",
            show_alert=True
        )
        return FINAL_CONSENT
    
    await query.answer("✅ Переход к оплате...")
    
    # Устанавливаем флаг автопродления
    context.user_data['enable_auto_renewal'] = True
    
    # Переходим к оплате
    return await handle_payment_confirmation_with_recurrent(update, context)

@safe_handler()
async def show_auto_renewal_terms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает подробные условия автопродления."""
    query = update.callback_query
    await query.answer()
    
    text = """📜 <b>Условия автоматического продления подписки</b>

<b>1. Общие положения</b>
• Автопродление активируется после первой успешной оплаты
• Списания происходят ежемесячно в день окончания текущего периода
• Услуга предоставляется ИП "Фролов Роман Антонович" (ИНН: 772459778593)

<b>2. Стоимость и списания</b>
• Стоимость указывается при оформлении подписки
• Списание происходит с карты, использованной при первой оплате
• При недостатке средств делается 3 попытки списания

<b>3. Уведомления</b>
• За 3 дня до списания - напоминание на email и в Telegram
• После успешного списания - подтверждение продления
• При проблемах - уведомление с инструкциями

<b>4. Отмена и возврат</b>
• Отмена доступна в любой момент через /my_subscriptions
• Отмена вступает в силу немедленно
• Доступ сохраняется до конца оплаченного периода
• Возврат возможен в течение 14 дней согласно ЗоЗПП

<b>5. Безопасность</b>
• Платежи обрабатывает Т-Банк (лицензия ЦБ РФ №2673)
• Данные карты хранятся в токенизированном виде
• Соответствие стандарту PCI DSS
• Защита 3D-Secure

<b>6. Поддержка</b>
📱 Telegram: @obshestvonapalcahsupport

<b>Нажимая "Согласен", вы принимаете данные условия</b>"""
    
    keyboard = [
        [InlineKeyboardButton("✅ Понятно", callback_data="payment_back")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_to_auto_renewal_options")]
    ]
    
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_payment_confirmation_with_recurrent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ИСПРАВЛЕННЫЙ обработчик подтверждения платежа с поддержкой рекуррентных платежей, duration_months и промокодов."""
    
    # Проверяем источник вызова и корректно обрабатываем
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        message = query.message
    else:
        # Если функция вызвана после ввода email (текстовое сообщение)
        query = None
        message = update.message
    
    plan_id = context.user_data.get('selected_plan')
    duration_months = context.user_data.get('duration_months', 1)
    user_email = context.user_data.get('email')  # Изменено с 'user_email' на 'email'
    user_id = update.effective_user.id
    enable_auto_renewal = context.user_data.get('enable_auto_renewal', False)
    
    # ==== НОВОЕ: Получаем данные о промокоде ====
    promo_code = context.user_data.get('promo_code')
    promo_discount = context.user_data.get('promo_discount', 0)
    original_price = context.user_data.get('original_price')
    promo_data = context.user_data.get('promo_data')
    
    if not all([plan_id, user_email]):
        error_text = (
            "❌ Ошибка: недостаточно данных для создания платежа.\n"
            "Попробуйте начать заново: /subscribe"
        )
        
        if query:
            await query.edit_message_text(error_text)
        else:
            await message.reply_text(error_text)
        return ConversationHandler.END
    
    # ==== ИЗМЕНЕНО: Проверяем, есть ли уже цена со скидкой в контексте ====
    if promo_code and 'total_price' in context.user_data:
        # Если промокод применен, используем цену со скидкой
        total_price_rub = context.user_data['total_price']
    else:
        # Иначе рассчитываем стандартную цену
        if plan_id.startswith('custom_'):
            modules = context.user_data.get('selected_modules', [])
            custom_plan_data = {
                'price_rub': calculate_custom_price(modules, 1),
                'modules': modules
            }
            total_price_rub = calculate_subscription_price(plan_id, duration_months, custom_plan_data)
        else:
            from payment.config import MODULE_PLANS, SUBSCRIPTION_PLANS
            plan_info = SUBSCRIPTION_PLANS.get(plan_id, MODULE_PLANS.get(plan_id))
            total_price_rub = calculate_subscription_price(plan_id, duration_months, plan_info)
    
    # ==== НОВОЕ: Проверяем минимальную сумму для Tinkoff ====
    if total_price_rub < 1:
        logger.warning(f"Price too low for Tinkoff: {total_price_rub}₽, setting to minimum 1₽")
        total_price_rub = 1
        
        # Обновляем в контексте
        context.user_data['total_price'] = 1
    
    # Конвертируем в копейки
    total_price_kopecks = total_price_rub * 100
    
    # ==== НОВОЕ: Дополнительная проверка для копеек ====
    if total_price_kopecks < 100:
        logger.error(f"Invalid amount in kopecks: {total_price_kopecks}")
        total_price_kopecks = 100
    
    # ==== НОВОЕ: Сохраняем оригинальную цену для отображения скидки ====
    if not original_price:
        original_price = total_price_rub

    # ==== КРИТИЧНОЕ: Проверяем rate limit перед созданием платежа ====
    from payment.rate_limiter import get_rate_limiter

    rate_limiter = get_rate_limiter()
    allowed, limit_message = rate_limiter.check_rate_limit(user_id)

    if not allowed:
        error_text = f"⚠️ {limit_message}\n\n" \
                    "Это защита от случайных множественных платежей.\n" \
                    "Если у вас возникли проблемы, обратитесь в поддержку: @obshestvonapalcahsupport"

        if query:
            await query.edit_message_text(error_text)
        else:
            await message.reply_text(error_text)

        logger.warning(f"Rate limit exceeded for user {user_id}: {limit_message}")
        return ConversationHandler.END

    try:
        # Создаем менеджер подписок
        from payment.subscription_manager import SubscriptionManager
        subscription_manager = context.bot_data.get('subscription_manager', SubscriptionManager())

        # Создаем уникальный order_id с UUID для предотвращения дублирования
        import uuid
        order_id = f"order_{user_id}_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:8]}"

        # Записываем попытку создания платежа в rate limiter
        rate_limiter.record_payment_attempt(user_id, order_id)
        
        # Получаем название плана
        from payment.config import MODULE_PLANS, SUBSCRIPTION_PLANS
        if plan_id.startswith('custom_'):
            plan_name = "Индивидуальный набор модулей"
        else:
            plan_info = SUBSCRIPTION_PLANS.get(plan_id, MODULE_PLANS.get(plan_id, {}))
            plan_name = plan_info.get('name', 'Подписка')
        
        # Описание платежа
        if duration_months == 1:
            description = f"{plan_name} (1 месяц)"
        else:
            description = f"{plan_name} ({duration_months} месяцев)"
        
        # ==== НОВОЕ: Добавляем информацию о промокоде в описание ====
        if promo_code:
            description += f" с промокодом {promo_code}"
        
        # Импортируем и создаем объект TinkoffPayment
        from payment.tinkoff import TinkoffPayment
        tinkoff = TinkoffPayment()
        
        # ВАЖНО: Проверяем, есть ли метод build_receipt_item
        # Если нет, создаем чек вручную
        receipt_items = [{
            "Name": description[:64],
            "Price": total_price_kopecks,
            "Quantity": 1,
            "Amount": total_price_kopecks,
            "Tax": "none",
            "PaymentMethod": "full_payment",
            "PaymentObject": "service"
        }]
        
        # Если есть метод build_receipt_item, используем его
        if hasattr(tinkoff, 'build_receipt_item'):
            receipt_items = [
                tinkoff.build_receipt_item(
                    name=description[:64],
                    price_kopecks=total_price_kopecks
                )
            ]
        
        # Инициализируем платеж
        payment_result = await tinkoff.init_payment(
            order_id=order_id,
            amount_kopecks=total_price_kopecks,
            description=description,
            user_email=user_email,
            receipt_items=receipt_items,
            user_data={
                "user_id": str(user_id),
                "email": user_email,
                "plan_id": plan_id,
                "duration_months": str(duration_months),
                "enable_auto_renewal": str(enable_auto_renewal),
                "modules": ','.join(context.user_data.get('selected_modules', [])) if plan_id.startswith('custom_') else '',
                "promo_code": promo_code or "",  # ==== НОВОЕ ====
                "promo_discount": str(promo_discount) if promo_discount else "0",  # ==== НОВОЕ ====
                "original_price": str(original_price * 100) if promo_code else ""  # ==== НОВОЕ ====
            },
            enable_recurrent=enable_auto_renewal,
            customer_key=str(user_id) if enable_auto_renewal else None
        )
        
        if payment_result.get("success"):
            payment_url = payment_result.get("payment_url")
            payment_id = payment_result.get("payment_id")
            
            # Сохраняем в БД
            try:
                import aiosqlite
                import json
                async with aiosqlite.connect(subscription_manager.database_file) as conn:
                    # Подготавливаем метаданные
                    metadata = {
                        'duration_months': duration_months,
                        'enable_recurrent': enable_auto_renewal,
                        'email': user_email,
                        'plan_name': plan_name,
                        'promo_code': promo_code,  # ==== НОВОЕ ====
                        'promo_discount': promo_discount,  # ==== НОВОЕ ====
                        'original_price': original_price * 100 if promo_code else None  # ==== НОВОЕ ====
                    }
                    
                    # Если это кастомный план, добавляем модули
                    if plan_id.startswith('custom_'):
                        metadata['modules'] = ','.join(context.user_data.get('selected_modules', []))
                    
                    await conn.execute(
                        """
                        INSERT INTO payments (
                            order_id, user_id, payment_id, amount_kopecks,
                            status, created_at, plan_id, metadata,
                            auto_renewal_enabled, promo_code, promo_discount
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            order_id, 
                            user_id, 
                            payment_id, 
                            total_price_kopecks,
                            'NEW', 
                            datetime.now().isoformat(), 
                            plan_id,
                            json.dumps(metadata),
                            1 if enable_auto_renewal else 0,
                            promo_code,  # ==== НОВОЕ ====
                            promo_discount  # ==== НОВОЕ ====
                        )
                    )
                    await conn.commit()
                    
                    # Сохраняем email в отдельную таблицу если она существует
                    cursor = await conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name='user_emails'"
                    )
                    if await cursor.fetchone():
                        await conn.execute(
                            """
                            INSERT OR REPLACE INTO user_emails (user_id, email, updated_at)
                            VALUES (?, ?, CURRENT_TIMESTAMP)
                            """,
                            (user_id, user_email)
                        )
                        await conn.commit()
                        
                    logger.info(f"Payment info saved: order_id={order_id}, amount={total_price_kopecks} kopecks, promo={promo_code}")
                    
            except Exception as e:
                logger.error(f"Failed to save payment info: {e}")
            
            # ==== ИЗМЕНЕНО: Формируем сообщение с учетом промокода ====
            if promo_code:
                success_text = f"""✅ <b>Платеж создан успешно!</b>

📦 План: <b>{plan_name}</b>
⏱ Срок: <b>{duration_months} мес.</b>
🎁 Промокод: <code>{promo_code}</code>
💰 Цена: <s>{original_price} ₽</s>
🎯 К оплате со скидкой: <b>{total_price_rub} ₽</b>
💸 Ваша выгода: <b>{promo_discount} ₽</b>
{"🔄 Автопродление: включено" if enable_auto_renewal else "💳 Разовая оплата"}

Нажмите кнопку ниже для перехода к оплате:"""
            else:
                success_text = f"""✅ <b>Платеж создан успешно!</b>

📦 План: <b>{plan_name}</b>
⏱ Срок: <b>{duration_months} мес.</b>
💰 К оплате: <b>{total_price_rub} ₽</b>
{"🔄 Автопродление: включено" if enable_auto_renewal else "💳 Разовая оплата"}

Нажмите кнопку ниже для перехода к оплате:"""
            
            keyboard = [
                [InlineKeyboardButton("💳 Оплатить", url=payment_url)],
                [InlineKeyboardButton("✅ Проверить оплату", callback_data="check_payment")],
                [InlineKeyboardButton("❌ Отменить", callback_data="cancel_payment")]
            ]
            
            if query:
                await query.edit_message_text(
                    success_text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.reply_text(
                    success_text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML
                )
                
        else:
            # Обработка ошибки создания платежа
            error_message = payment_result.get('error', 'Неизвестная ошибка')
            error_code = payment_result.get('error_code', '')
            
            error_text = (
                f"❌ <b>Ошибка создания платежа</b>\n\n"
                f"Код ошибки: {error_code}\n"
                f"Сообщение: {error_message}\n\n"
                "Попробуйте позже или обратитесь в поддержку."
            )
            
            error_keyboard = [
                [InlineKeyboardButton("🔄 Попробовать снова", callback_data="subscribe")],
                [InlineKeyboardButton("💬 Поддержка", callback_data="support")]
            ]
            
            if query:
                await query.edit_message_text(
                    error_text,
                    reply_markup=InlineKeyboardMarkup(error_keyboard),
                    parse_mode=ParseMode.HTML
                )
            else:
                await message.reply_text(
                    error_text,
                    reply_markup=InlineKeyboardMarkup(error_keyboard),
                    parse_mode=ParseMode.HTML
                )
            
    except Exception as e:
        logger.exception(f"Critical error creating payment: {e}")
        
        critical_error_text = (
            "❌ <b>Произошла критическая ошибка</b>\n\n"
            f"Ошибка: {str(e)}\n\n"
            "Пожалуйста, обратитесь в поддержку с этой информацией."
        )
        
        critical_error_keyboard = [
            [InlineKeyboardButton("🔄 Попробовать снова", callback_data="subscribe")],
            [InlineKeyboardButton("💬 Поддержка", callback_data="support")]
        ]
        
        if query:
            await query.edit_message_text(
                critical_error_text,
                reply_markup=InlineKeyboardMarkup(critical_error_keyboard),
                parse_mode=ParseMode.HTML
            )
        else:
            await message.reply_text(
                critical_error_text,
                reply_markup=InlineKeyboardMarkup(critical_error_keyboard),
                parse_mode=ParseMode.HTML
            )
    
    return ConversationHandler.END

async def handle_back_to_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возвращает к выбору длительности подписки."""
    query = update.callback_query
    await query.answer()
    
    # Возвращаемся к выбору длительности
    return await show_duration_options(update, context)

async def cancel_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена процесса оплаты."""
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("❌ Оформление подписки отменено.")
    else:
        await update.message.reply_text("❌ Оформление подписки отменено.")
    
    # Очищаем данные
    context.user_data.clear()
    
    return ConversationHandler.END

@safe_handler()
async def ask_auto_renewal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Спрашивает о включении автопродления."""
    query = update.callback_query
    await query.answer()
    
    plan_id = context.user_data.get('selected_plan')
    plan_name = context.user_data.get('plan_name', 'Подписка')
    duration = context.user_data.get('duration_months', 1)
    
    # ВАЖНО: Правильно определяем цену
    if plan_id == 'trial_7days':
        total_price = 1
    else:
        total_price = context.user_data.get('total_price')
        if not total_price:
            from payment.config import MODULE_PLANS, SUBSCRIPTION_PLANS
            plan_info = MODULE_PLANS.get(plan_id) or SUBSCRIPTION_PLANS.get(plan_id)
            if plan_info:
                total_price = calculate_subscription_price(plan_id, duration)
            else:
                total_price = 799 * duration
    
    context.user_data['total_price'] = total_price
    
    text = f"""💳 <b>Выберите тип оплаты</b>

📋 <b>Ваш заказ:</b>
• Тариф: {plan_name}
• Срок: {duration if plan_id != 'trial_7days' else '7 дней'}
• Стоимость: <b>{total_price} ₽</b>

<b>Доступные варианты:</b>

🔄 <b>С автопродлением</b>
После окончания срока подписка продлевается автоматически.
Вы можете отменить автопродление в любой момент.

💳 <b>Разовая оплата</b>
Подписка действует только выбранный срок.
После окончания нужно продлить вручную."""
    
    keyboard = [
        [InlineKeyboardButton("🔄 С автопродлением", callback_data="consent_auto_renewal")],
        [InlineKeyboardButton("💳 Разовая оплата", callback_data="no_auto_renewal")],
        [InlineKeyboardButton("❓ Подробнее", callback_data="auto_renewal_terms")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_to_duration")]  # Добавлена кнопка Назад
    ]
    
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    return AUTO_RENEWAL_CHOICE


@safe_handler()
async def handle_auto_renewal_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает выбор автопродления и переходит к запросу email."""
    query = update.callback_query
    await query.answer()
    
    if query.data == "enable_auto_renewal_payment":
        context.user_data['enable_auto_renewal'] = True
        await query.answer("✅ Автопродление будет включено после оплаты")
    else:
        context.user_data['enable_auto_renewal'] = False
        await query.answer("Автопродление не будет включено")
    
    # ИСПРАВЛЕНИЕ: Переходим к запросу email, а НЕ сразу к оплате!
    return await request_email(update, context)

@safe_handler()
async def cmd_my_subscriptions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /my_subscriptions - показывает активные подписки."""
    user_id = update.effective_user.id
    subscription_manager = context.bot_data.get('subscription_manager', SubscriptionManager())
    
    if SUBSCRIPTION_MODE == 'modular':
        modules = await subscription_manager.get_user_modules(user_id)
        
        if not modules:
            text = "📋 <b>Мои подписки</b>\n\nУ вас нет активных подписок.\n\nИспользуйте /subscribe для оформления."
        else:
            text = "📋 <b>Ваши активные модули:</b>\n\n"
            module_names = {
                'test_part': '📝 Тестовая часть',
                'task19': '🎯 Задание 19',
                'task20': '📖 Задание 20',
                'task24': '💎 Задание 24',
                'task25': '✍️ Задание 25'
            }
            for module in modules:
                name = module_names.get(module['module_code'], module['module_code'])
                expires = module['expires_at'].strftime('%d.%m.%Y')
                text += f"{name}\n└ Действует до: {expires}\n\n"
            
            text += "Используйте /subscribe для продления или добавления модулей."
    else:
        subscription = await subscription_manager.check_active_subscription(user_id)
        if subscription:
            plan = SUBSCRIPTION_PLANS.get(subscription['plan_id'], {})
            expires = subscription['expires_at'].strftime('%d.%m.%Y')
            text = f"""✅ <b>Активная подписка</b>

План: {plan.get('name', 'Подписка')}
Действует до: {expires}

Используйте /subscribe для продления."""
        else:
            text = "У вас нет активной подписки.\n\nИспользуйте /subscribe для оформления."
    
    # ДОБАВЛЕНО: кнопка главного меню
    keyboard = [
        [InlineKeyboardButton("🔄 Оформить/Продлить", callback_data="payment_back")],
        [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
    ]
    
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

@safe_handler()
async def handle_my_subscriptions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик callback my_subscriptions - показывает активные подписки."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    subscription_manager = context.bot_data.get('subscription_manager', SubscriptionManager())
    
    if SUBSCRIPTION_MODE == 'modular':
        modules = await subscription_manager.get_user_modules(user_id)
        
        if not modules:
            # Для пользователей без подписки показываем интерфейс подписки
            text = "📋 <b>Мои подписки</b>\n\nУ вас нет активных подписок.\n\n"
            text += "💡 С модульной системой вы платите только за те задания, которые вам нужны!"
            
            keyboard = [
                [InlineKeyboardButton("💳 Оформить подписку", callback_data="subscribe")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
            ]
            
            try:
                await query.edit_message_text(
                    text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except BadRequest as e:
                if "Message is not modified" not in str(e):
                    logger.error(f"Error in handle_my_subscriptions: {e}")
                    raise
        else:
            # Для пользователей с подпиской показываем их модули
            text = "📋 <b>Ваши активные модули:</b>\n\n"
            module_names = {
                'test_part': '📝 Тестовая часть',
                'task19': '🎯 Задание 19',
                'task20': '📖 Задание 20',
                'task24': '💎 Задание 24',
                'task25': '✍️ Задание 25'
            }
            
            for module in modules:
                name = module_names.get(module['module_code'], module['module_code'])
                expires = module['expires_at'].strftime('%d.%m.%Y')
                text += f"✅ {name}\n   └ Действует до: {expires}\n\n"
            
            # Детали доступа
            text += "📊 <b>Детали доступа:</b>\n"
            all_modules = ALL_PAID_MODULES
            inactive_modules = []
            
            for module_code in all_modules:
                has_access = await subscription_manager.check_module_access(user_id, module_code)
                if not has_access:
                    inactive_modules.append(module_names.get(module_code, module_code))
            
            if inactive_modules:
                text += f"❌ Неактивные: {', '.join(inactive_modules)}\n\n"
            else:
                text += "✅ У вас есть доступ ко всем модулям!\n\n"
            
            text += "Используйте /subscribe для продления или добавления модулей."
            
            keyboard = [
                [InlineKeyboardButton("🔄 Продлить/Добавить", callback_data="payment_back")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
            ]
            
            try:
                await query.edit_message_text(
                    text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except BadRequest as e:
                if "Message is not modified" not in str(e):
                    logger.error(f"Error editing message: {e}")
                    # Если не можем отредактировать, отправляем новое сообщение
                    await query.message.reply_text(
                        text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
    else:
        # Режим обычных подписок
        subscription = await subscription_manager.check_active_subscription(user_id)
        if subscription:
            plan = SUBSCRIPTION_PLANS.get(subscription['plan_id'], {})
            expires = subscription['expires_at'].strftime('%d.%m.%Y')
            text = f"""✅ <b>Активная подписка</b>

План: {plan.get('name', 'Подписка')}
Действует до: {expires}

Используйте /subscribe для продления."""
        else:
            text = "📋 <b>Мои подписки</b>\n\nУ вас нет активной подписки.\n\nИспользуйте /subscribe для оформления."
        
        keyboard = [
            [InlineKeyboardButton("🔄 Оформить/Продлить", callback_data="payment_back")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
        ]
        
        try:
            await query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                logger.error(f"Error editing message: {e}")
                await query.message.reply_text(
                    text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
    
    # ВАЖНО: НЕ возвращаем состояние ConversationHandler
    # чтобы обработчик работал как standalone
    return None
    
@safe_handler()
async def handle_back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Глобальный обработчик для возврата в главное меню."""
    query = update.callback_query
    await query.answer()
    
    # Очищаем флаг процесса оплаты если он был
    context.user_data.pop('in_payment_process', None)
    
    # Используем глобальный обработчик из core
    from core.menu_handlers import handle_to_main_menu
    return await handle_to_main_menu(update, context)

@safe_handler()
async def handle_module_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает информацию о модуле."""
    query = update.callback_query
    await query.answer()
    
    # Извлекаем код модуля из callback_data
    module_code = query.data.replace("module_info_", "")
    
    module_info = {
        'test_part': {
            'name': '📝 Тестовая часть ЕГЭ',
            'description': 'Полный доступ к банку заданий тестовой части',
            'features': [
                '✅ Все задания 1-16',
                '✅ Подробные объяснения',
                '✅ Статистика прогресса',
                '✅ Работа над ошибками'
            ],
            'price': '149₽/мес'
        },
        'task19': {
            'name': '🎯 Задание 19',
            'description': 'Примеры социальных объектов и явлений',
            'features': [
                '✅ База примеров по всем темам',
                '✅ Интерактивные тренажеры',
                '✅ Проверка ответов'
            ],
            'price': '199₽/мес'
        },
        'task20': {
            'name': '📖 Задание 20',
            'description': 'Текст с пропущенными словами',
            'features': [
                '✅ Тексты по всем разделам',
                '✅ Подробные пояснения',
                '✅ Тренировка навыков'
            ],
            'price': '199₽/мес'
        },
        'task24': {
            'name': '💎 Задание 24',
            'description': 'Составление сложного плана',
            'features': [
                '✅ База готовых планов',
                '✅ Экспертная проверка',
                '✅ Персональные рекомендации',
                '✅ VIP поддержка'
            ],
            'price': '399₽/мес'
        },
        'task25': {
            'name': '✍️ Задание 25',
            'description': 'Понятия и термины',
            'features': [
                '✅ Полная база понятий',
                '✅ Интерактивная проверка',
                '✅ Адаптивная сложность'
            ],
            'price': '199₽/мес'
        }
    }
    
    info = module_info.get(module_code)
    if not info:
        await query.edit_message_text(
            "❌ Информация о модуле не найдена",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="back_to_modules")
            ]])
        )
        return
    
    text = f"<b>{info['name']}</b>\n\n"
    text += f"{info['description']}\n\n"
    text += "<b>Что входит:</b>\n"
    for feature in info['features']:
        text += f"{feature}\n"
    text += f"\n💰 <b>Стоимость:</b> {info['price']}"
    
    keyboard = [
        [InlineKeyboardButton("💳 Оформить подписку", callback_data="subscribe")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_modules")]
    ]
    
    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# Добавьте эту функцию ПЕРЕД функцией register_payment_handlers в файле payment/handlers.py

@safe_handler()
async def standalone_pay_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик для прямых кнопок оплаты (только trial и full)."""
    query = update.callback_query
    await query.answer()
    
    # Устанавливаем флаг процесса оплаты
    context.user_data['in_payment_process'] = True

    # Проверяем какая кнопка нажата
    if query.data == "pay_trial" or query.data == "subscribe_trial_7days":
        plan_id = "trial_7days"
        context.user_data['is_trial'] = True
        context.user_data['selected_plan'] = plan_id
        context.user_data['duration_months'] = 1
        context.user_data['total_price'] = 1
        context.user_data['base_price'] = 1
        context.user_data['plan_name'] = "🎁 Пробный период 7 дней"

        # Для триала сразу запрашиваем email
        return await request_email_for_trial(update, context)
    
    elif query.data == "pay_package_full":
        plan_id = "package_full"
        context.user_data['selected_plan'] = plan_id
        context.user_data['is_trial'] = False
        
        # Получаем информацию о плане
        from payment.config import SUBSCRIPTION_PLANS
        plan = SUBSCRIPTION_PLANS.get(plan_id)
        
        if plan:
            context.user_data['plan_info'] = plan
            context.user_data['plan_name'] = plan['name']
            context.user_data['base_price'] = plan['price_rub']
            
            # Показываем варианты длительности
            return await show_duration_options(update, context)
        else:
            await query.edit_message_text("❌ Ошибка: план не найден")
            return ConversationHandler.END
    
    else:
        # Неизвестная кнопка
        context.user_data.pop('in_payment_process', None)
        await query.answer("Неизвестное действие", show_alert=True)
        return ConversationHandler.END

def register_payment_handlers(app):
    """Регистрирует обработчики платежей с упрощенным потоком (только trial и full)."""
    logger.info("Registering payment handlers...")
    
    # Инициализируем обработчик согласия
    subscription_manager = app.bot_data.get('subscription_manager', SubscriptionManager())
    consent_handler = AutoRenewalConsent(subscription_manager)
    
    # Создаем ConversationHandler с правильными состояниями
    payment_conv = ConversationHandler(
        entry_points=[
            CommandHandler("subscribe", cmd_subscribe),
            CallbackQueryHandler(show_modular_interface, pattern="^subscribe$"),
            CallbackQueryHandler(show_modular_interface, pattern="^subscribe_start$"),
            # ОБНОВЛЕНО: Только trial и package_full
            CallbackQueryHandler(standalone_pay_handler, pattern="^pay_trial$"),
            CallbackQueryHandler(standalone_pay_handler, pattern="^subscribe_trial_7days$"),  # ДОБАВЛЕНО: для onboarding
            CallbackQueryHandler(standalone_pay_handler, pattern="^pay_package_full$"),
            # УДАЛЕНО: pay_package_second, pay_individual_modules
        ],
        states={
            CHOOSING_PLAN: [
                CallbackQueryHandler(handle_plan_selection, pattern="^pay_"),
                # Обработчики для подписок учителей
                CallbackQueryHandler(show_teacher_plans_in_shop, pattern="^show_teacher_subscriptions$"),
                CallbackQueryHandler(show_teacher_plan_details_in_shop, pattern="^view_teacher_plan_"),
                CallbackQueryHandler(handle_teacher_plan_confirmation, pattern="^confirm_teacher_plan:"),
                # УДАЛЕНО: show_individual_modules - больше нет отдельных модулей
                CallbackQueryHandler(show_modular_interface, pattern="^(back_to_main|subscribe)$"),
                CallbackQueryHandler(handle_my_subscriptions, pattern="^my_subscriptions$")
            ],
            
            PROMO_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_promo_input),
                CallbackQueryHandler(skip_promo, pattern="^skip_promo$"),
                CallbackQueryHandler(retry_promo, pattern="^retry_promo$"),
                CallbackQueryHandler(show_promo_input, pattern="^retry_promo$"),
                CallbackQueryHandler(handle_back_to_duration_selection, pattern="^back_to_duration_selection$"),
                CallbackQueryHandler(cancel_payment, pattern="^cancel_payment$")
            ],
            
            # УДАЛЕНО: Весь блок CHOOSING_MODULES - больше не нужен
            
            CHOOSING_DURATION: [
                CallbackQueryHandler(handle_duration_selection, pattern="^duration_"),
                # УДАЛЕНО: show_individual_modules - больше нет отдельных модулей
                CallbackQueryHandler(show_modular_interface, pattern="^back_to_plans$")
            ],
            
            CONFIRMING: [
                # Обработчики для бесплатной активации и 1 рубля
                CallbackQueryHandler(handle_free_activation, pattern="^activate_free$"),
                CallbackQueryHandler(handle_pay_one_ruble, pattern="^pay_one_ruble$"),
                
                # Обработчики автопродления
                CallbackQueryHandler(
                    handle_auto_renewal_choice, 
                    pattern="^(enable|disable)_auto_renewal_payment$"
                ),
                CallbackQueryHandler(
                    handle_back_to_duration_selection,
                    pattern="^back_to_duration_selection$"
                ),
                CallbackQueryHandler(cancel_payment, pattern="^cancel_payment$"),
            ],
            
            ENTERING_EMAIL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_email_input),
                CallbackQueryHandler(cancel_payment, pattern="^cancel_payment$")
            ],

            AUTO_RENEWAL_CHOICE: [
                # Обработчик для основного выбора
                CallbackQueryHandler(
                    consent_handler.handle_choice_selection,
                    pattern="^(consent_auto_renewal|choose_auto_renewal|choose_no_auto_renewal|show_auto_renewal_terms)$"
                ),
                CallbackQueryHandler(
                    handle_auto_renewal_choice,
                    pattern="^(no_auto_renewal|auto_renewal_terms)$"
                ),
                
                # Обработчики для кнопок с экрана согласия
                CallbackQueryHandler(
                    toggle_consent,
                    pattern="^toggle_consent_checkbox$"
                ),
                CallbackQueryHandler(
                    toggle_consent,
                    pattern="^toggle_consent$"
                ),
                CallbackQueryHandler(
                    confirm_with_auto_renewal,
                    pattern="^confirm_with_auto_renewal$"
                ),
                CallbackQueryHandler(
                    lambda u, c: u.callback_query.answer("⚠️ Отметьте согласие", show_alert=True),
                    pattern="^need_consent_reminder$"
                ),
                CallbackQueryHandler(
                    lambda u, c: u.callback_query.answer("⚠️ Отметьте согласие", show_alert=True),
                    pattern="^need_consent$"
                ),
                
                # Навигация
                CallbackQueryHandler(
                    handle_back_to_duration,
                    pattern="^back_to_duration$"
                ),
                CallbackQueryHandler(
                    handle_payment_back,
                    pattern="^(payment_back|back_to_payment_choice)$"
                ),
                CallbackQueryHandler(
                    cancel_payment,
                    pattern="^cancel_payment$"
                )
            ],
            
            SHOWING_TERMS: [
                CallbackQueryHandler(
                    consent_handler.handle_choice_selection,
                    pattern="^(choose_auto_renewal|choose_no_auto_renewal|show_auto_renewal_terms)$"
                ),
                CallbackQueryHandler(
                    consent_handler.handle_back_navigation,
                    pattern="^back_to_duration$"
                ),
                CallbackQueryHandler(
                    cancel_payment,
                    pattern="^cancel_payment$"
                )
            ],

            CONSENT_CHECKBOX: [
                # Переключение чекбокса согласия
                CallbackQueryHandler(
                    consent_handler.toggle_consent,
                    pattern="^toggle_consent_checkbox$"
                ),
                # Подтверждение с согласием
                CallbackQueryHandler(
                    consent_handler.confirm_with_auto_renewal,
                    pattern="^confirm_with_auto_renewal$"
                ),
                # Напоминание о необходимости согласия
                CallbackQueryHandler(
                    lambda u, c: u.callback_query.answer("⚠️ Пожалуйста, отметьте согласие", show_alert=True),
                    pattern="^need_consent_reminder$"
                ),
                # Показ подробных условий
                CallbackQueryHandler(
                    consent_handler.show_detailed_terms,
                    pattern="^show_user_agreement$"
                ),
                # Навигация назад
                CallbackQueryHandler(
                    consent_handler.handle_back_navigation,
                    pattern="^back_to_payment_choice$"
                ),
                CallbackQueryHandler(
                    cancel_payment,
                    pattern="^cancel_payment$"
                )
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_payment),
            CallbackQueryHandler(cancel_payment, pattern="^pay_cancel$"),
            CallbackQueryHandler(handle_my_subscriptions, pattern="^my_subscriptions$")
        ],
        name="payment_conversation",
        persistent=True,
        allow_reentry=True,
        per_message=False
    )
    
    # Регистрируем ConversationHandler
    app.add_handler(payment_conv, group=-50)
    
    # Дополнительные обработчики вне ConversationHandler
    app.add_handler(
        CallbackQueryHandler(
            check_payment_status,
            pattern="^check_payment$"
        ),
        group=-45
    )
    
    app.add_handler(
        CallbackQueryHandler(
            handle_payment_back,
            pattern="^payment_back$"
        ),
        group=-45
    )
    
    app.add_handler(
        CallbackQueryHandler(
            handle_my_subscriptions, 
            pattern="^my_subscriptions$"
        ), 
        group=-45
    )
    
    app.add_handler(
        CommandHandler("my_subscriptions", cmd_my_subscriptions), 
        group=-45
    )
    
    # Обработчик для возврата в главное меню
    async def payment_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Переход в главное меню из payment."""
        from core.menu_handlers import handle_to_main_menu
        context.user_data.pop('in_payment_process', None)
        await handle_to_main_menu(update, context)
        return ConversationHandler.END
    
    app.add_handler(
        CallbackQueryHandler(
            payment_to_main_menu,
            pattern="^(main_menu|to_main_menu)$"
        ),
        group=-45
    )
    
    app.add_handler(
        CallbackQueryHandler(
            handle_back_to_main_menu, 
            pattern="^back_to_main$"
        ), 
        group=-49
    )
    
    app.add_handler(
        CallbackQueryHandler(
            handle_module_info, 
            pattern="^module_info_"
        ), 
        group=-45
    )
    
    # Debug команда (если существует)
    try:
        app.add_handler(
            CommandHandler("debug_subscription", cmd_debug_subscription), 
            group=-50
        )

        # Обработчик для кнопки "Отмена"
        app.add_handler(
            CallbackQueryHandler(
                handle_close_message,
                pattern="^close_message$"
            ),
            group=-45
        )
    except NameError:
        logger.info("cmd_debug_subscription not defined, skipping")
    
    logger.info("Payment handlers registered successfully")
    logger.info("ConversationHandler configured for trial and full subscription only")
    logger.info("Priority groups: -50 (ConversationHandler), -45 (standalone)")

# Обработчик для закрытия сообщений (кнопка "Отмена")
@safe_handler()
async def handle_close_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Закрывает сообщение при нажатии кнопки Отмена."""
    query = update.callback_query
    
    try:
        # Отвечаем на callback query
        await query.answer("Отменено")
        
        # Удаляем сообщение
        await query.message.delete()
        
    except Exception as e:
        logger.debug(f"Error closing message: {e}")
        # Если не получилось удалить, просто отвечаем
        if query:
            await query.answer()
