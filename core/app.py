# core/app.py - исправленная версия с правильной интеграцией платежей

import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, PicklePersistence, ContextTypes, PersistenceInput
from telegram.constants import ParseMode
import sys
import os

# Добавляем путь к корневой директории для импорта модулей
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import config, db
from payment import init_payment_module

logger = logging.getLogger(__name__)


async def send_message_with_retry(message, text, reply_markup=None, parse_mode=None, max_retries=3, initial_delay=1.0):
    """
    Отправляет сообщение с автоматическими повторными попытками при сетевых ошибках.

    Args:
        message: Telegram Message объект
        text: Текст сообщения
        reply_markup: Клавиатура (опционально)
        parse_mode: Режим парсинга (опционально)
        max_retries: Максимальное количество повторных попыток
        initial_delay: Начальная задержка между попытками в секундах

    Returns:
        Отправленное сообщение или None при неудаче
    """
    from telegram.error import TimedOut, NetworkError

    delay = initial_delay
    last_error = None

    for attempt in range(max_retries):
        try:
            return await message.reply_text(
                text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
        except (TimedOut, NetworkError) as e:
            last_error = e
            if attempt < max_retries - 1:
                logger.warning(f"Message send failed (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {delay}s...")
                await asyncio.sleep(delay)
                delay *= 2  # Экспоненциальная задержка
            else:
                logger.error(f"Message send failed after {max_retries} attempts: {e}")
                raise
        except Exception as e:
            # Другие ошибки не retry-им
            logger.error(f"Non-retryable error while sending message: {e}")
            raise

    # Если все попытки исчерпаны
    if last_error:
        raise last_error


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Глобальный обработчик ошибок для бота."""
    from telegram.error import BadRequest, Forbidden, NetworkError, TimedOut

    # Получаем информацию об ошибке
    error = context.error

    # Обрабатываем специфичные типы ошибок
    if isinstance(error, BadRequest):
        if "Message is not modified" in str(error):
            # Это не критичная ошибка - сообщение просто не изменилось
            logger.debug(f"Ignored 'Message is not modified' error")
            return
        if "Query is too old" in str(error) or "query id is invalid" in str(error):
            # Старые callback queries при перезапуске бота - не критично
            logger.debug(f"Ignored old callback query: {error}")
            return
        logger.warning(f"BadRequest error: {error}")
        # Логируем BadRequest как warning, не error

    elif isinstance(error, Forbidden):
        # Пользователь заблокировал бота
        logger.warning(f"Bot was blocked by user")
        # Можно добавить логику деактивации пользователя
        return  # Выходим без попытки отправить сообщение

    elif isinstance(error, (NetworkError, TimedOut)):
        # ИСПРАВЛЕНО: Сетевые ошибки и таймауты - логируем как WARNING, не ERROR
        # так как это временные проблемы, не требующие немедленного вмешательства
        logger.warning(f"Network error (will be retried automatically): {error}")
        # НЕ пытаемся отправить сообщение - это может вызвать еще один timeout
        return  # Выходим без попытки отправить сообщение

    else:
        # Все остальные ошибки - это действительно проблемы
        logger.error(f"Exception while handling an update:", exc_info=context.error)
        logger.error(f"Unhandled error: {type(error).__name__}: {error}")

    # Пытаемся уведомить пользователя об ошибке (если возможно)
    # ТОЛЬКО для не-сетевых ошибок
    try:
        if update and hasattr(update, 'effective_message') and update.effective_message:
            await update.effective_message.reply_text(
                "😔 Произошла ошибка при обработке вашего запроса.\n"
                "Пожалуйста, попробуйте позже или обратитесь в поддержку."
            )
        elif update and hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.answer(
                "❌ Произошла ошибка. Попробуйте позже.",
                show_alert=True
            )
    except Exception as e:
        # Не удалось отправить сообщение пользователю
        logger.error(f"Failed to send error message to user: {e}")


async def post_init(application: Application) -> None:
    """Инициализация после запуска бота"""
    logger.info("Выполняется post-init...")

    # Регистрация глобального обработчика ошибок
    application.add_error_handler(error_handler)
    logger.info("Global error handler registered")

    # Инициализация БД
    await db.init_db()

    # Применяем миграцию onboarding
    try:
        conn = await db.get_db()
        await db.apply_onboarding_migration(conn)
        logger.info("Onboarding migration applied")
    except Exception as e:
        logger.error(f"Failed to apply onboarding migration: {e}")

    # Применяем миграцию улучшенной системы стриков (Phase 1)
    try:
        from core.streak_migration import apply_streak_system_migration
        success = await apply_streak_system_migration()
        if success:
            logger.info("✓ Streak system migration applied successfully")
        else:
            logger.error("✗ Streak system migration failed")
    except Exception as e:
        logger.error(f"Failed to apply streak migration: {e}")

    try:
        from core.admin_tools import init_price_tables
        await init_price_tables()
        logger.info("Price tables initialized")
    except Exception as e:
        logger.error(f"Failed to initialize price tables: {e}")

    # Регистрируем callback filter middleware ПЕРВЫМ (group=-2)
    # для фильтрации старых callback queries при перезапуске
    try:
        from core.callback_filter_middleware import register_callback_filter_middleware
        register_callback_filter_middleware(application)
        logger.info("Callback filter middleware registered")
    except Exception as e:
        logger.error(f"Failed to register callback filter middleware: {e}")

    try:
        from core.user_middleware import register_user_middleware
        register_user_middleware(application)
        logger.info("User middleware registered")
    except Exception as e:
        logger.error(f"Failed to register user middleware: {e}")
        # Добавляем глобальную команду cancel
    async def global_cancel(update: Update, context):
        """Глобальный обработчик команды /cancel"""
        # Очищаем состояние пользователя
        context.user_data.clear()
        
        # Пробуем получить меню
        try:
            from core.plugin_loader import build_main_menu
            kb = build_main_menu()
            
            await update.message.reply_text(
                "❌ Действие отменено.\n\n"
                "📚 Выберите раздел для подготовки:",
                reply_markup=kb,
                parse_mode=ParseMode.HTML
            )
        except:
            await update.message.reply_text(
                "❌ Действие отменено.\n\n"
                "Используйте /menu для возврата в главное меню."
            )
    # Добавляем базовые команды
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("menu", menu_command))
    # Обработчик my_subscription теперь в плагине personal_cabinet
    application.add_handler(CommandHandler("cancel", global_cancel), group=10)
    # ВАЖНО: Регистрируем глобальные обработчики меню
    try:
        from core.menu_handlers import register_global_handlers
        register_global_handlers(application)
        logger.info("Registered global menu handlers")
    except ImportError as e:
        logger.error(f"Could not import menu_handlers: {e}")
    except Exception as e:
        logger.error(f"Error registering global handlers: {e}")
    
    # Регистрируем админские обработчики
    try:
        from core.admin_tools import register_admin_handlers
        register_admin_handlers(application)
        logger.info("Admin handlers registered")
    except ImportError as e:
        logger.error(f"Could not import admin_tools: {e}")
    except Exception as e:
        logger.error(f"Error registering admin handlers: {e}")

    # Регистрируем админские обработчики для жалоб
    try:
        from core.complaint_admin import register_admin_complaint_handlers
        register_admin_complaint_handlers(application)
        logger.info("Admin complaint handlers registered")
    except ImportError as e:
        logger.error(f"Could not import complaint_admin: {e}")
    except Exception as e:
        logger.error(f"Error registering admin complaint handlers: {e}")

    # Регистрируем retention admin обработчики
    try:
        from core.retention_admin import register_retention_admin_handlers
        register_retention_admin_handlers(application)
        logger.info("Retention admin handlers registered")
    except ImportError as e:
        logger.error(f"Could not import retention_admin: {e}")
    except Exception as e:
        logger.error(f"Error registering retention admin handlers: {e}")

    # Регистрируем onboarding handler
    try:
        from core.onboarding import get_onboarding_handler, skip_onboarding_before_start

        # Добавляем обработчик для кнопки "Пропустить обучение" вне conversation
        application.add_handler(
            CallbackQueryHandler(skip_onboarding_before_start, pattern="^start_onboarding_skip$"),
            group=0
        )

        onboarding_handler = get_onboarding_handler()
        application.add_handler(onboarding_handler, group=0)
        logger.info("Onboarding handler registered")
    except ImportError as e:
        logger.error(f"Could not import onboarding: {e}")
    except Exception as e:
        logger.error(f"Error registering onboarding handler: {e}")

    # Регистрируем админские команды для воронки
    try:
        from core.funnel_admin import register_funnel_admin_handlers
        register_funnel_admin_handlers(application)
        logger.info("Funnel admin handlers registered")
    except ImportError as e:
        logger.error(f"Could not import funnel_admin: {e}")
    except Exception as e:
        logger.error(f"Error registering funnel admin handlers: {e}")

    # Регистрируем команды для тестирования
    try:
        from core.testing_commands import register_testing_commands
        register_testing_commands(application)
        logger.info("Testing commands registered")
    except ImportError as e:
        logger.error(f"Could not import testing_commands: {e}")
    except Exception as e:
        logger.error(f"Error registering testing commands: {e}")

    # Инициализация модуля платежей
    await init_payment_module(application)

    # Инициализация FreemiumManager
    try:
        from core.freemium_manager import get_freemium_manager
        subscription_manager = application.bot_data.get('subscription_manager')
        freemium_manager = get_freemium_manager(subscription_manager)
        application.bot_data['freemium_manager'] = freemium_manager
        logger.info("FreemiumManager initialized and added to bot_data")

        # ДОБАВЛЕНО: Автоматическая очистка старых AI лимитов каждую неделю (понедельник в 3:00 МСК)
        from datetime import time as dt_time
        from zoneinfo import ZoneInfo
        msk_tz = ZoneInfo("Europe/Moscow")

        async def cleanup_old_limits(context):
            """Очищает старые записи AI лимитов из БД."""
            try:
                fm = context.bot_data.get('freemium_manager')
                if fm:
                    deleted = await fm.reset_weekly_limits()
                    logger.info(f"Weekly AI limits cleanup: {deleted} old records deleted")
            except Exception as e:
                logger.error(f"Error during weekly limits cleanup: {e}")

        application.job_queue.run_daily(
            cleanup_old_limits,
            time=dt_time(hour=3, minute=0, second=0, tzinfo=msk_tz),
            days=(0,),  # 0 = Понедельник
            name='weekly_ai_limits_cleanup'
        )
        logger.info("Weekly AI limits cleanup scheduled for Mondays at 3:00 MSK")

    except Exception as e:
        logger.error(f"Failed to initialize FreemiumManager: {e}")

    # Регистрация обработчиков уведомлений
    try:
        from core.notification_handlers import register_notification_handlers
        register_notification_handlers(application)
        logger.info("Notification handlers registered")
    except Exception as e:
        logger.error(f"Failed to register notification handlers: {e}")

    # Регистрация streak callback handlers (Phase 2: Notifications)
    try:
        from core.streak_handlers import register_streak_handlers
        register_streak_handlers(application)
        logger.info("Streak callback handlers registered")
    except Exception as e:
        logger.error(f"Failed to register streak handlers: {e}")

    # Регистрация protection shop handlers (Phase 3: Protection Mechanics)
    try:
        from core.streak_protection_shop import register_protection_shop_handlers
        register_protection_shop_handlers(application)
        logger.info("Protection shop handlers registered")
    except Exception as e:
        logger.error(f"Failed to register protection shop handlers: {e}")

    # Регистрация middleware для отслеживания кликов по retention уведомлениям
    try:
        from core.retention_click_middleware import register_retention_click_middleware
        register_retention_click_middleware(application)
        logger.info("Retention click middleware registered")
    except Exception as e:
        logger.error(f"Failed to register retention click middleware: {e}")

    # Инициализация retention scheduler
    try:
        from datetime import time as dt_time
        from zoneinfo import ZoneInfo
        from core.retention_scheduler import get_retention_scheduler

        scheduler = get_retention_scheduler()
        application.bot_data['retention_scheduler'] = scheduler

        # Запускаем ежедневную отправку уведомлений в 18:00 МСК (после школы)
        # Используем московское время явно
        msk_tz = ZoneInfo("Europe/Moscow")
        application.job_queue.run_daily(
            scheduler.send_daily_notifications,
            time=dt_time(hour=18, minute=0, second=0, tzinfo=msk_tz),
            name='daily_retention_notifications'
        )

        logger.info("Retention scheduler initialized and scheduled for 18:00 MSK daily")
    except Exception as e:
        logger.error(f"Failed to initialize retention scheduler: {e}")

    # Инициализация deadline reminder scheduler
    try:
        from teacher_mode.deadline_scheduler import get_deadline_scheduler

        deadline_scheduler = get_deadline_scheduler()
        application.bot_data['deadline_scheduler'] = deadline_scheduler

        # Запускаем проверку дедлайнов каждые 3 часа
        application.job_queue.run_repeating(
            deadline_scheduler.check_and_send_reminders,
            interval=10800,  # 3 часа в секундах
            first=10,  # Первый запуск через 10 секунд после старта
            name='deadline_reminders_check'
        )

        logger.info("Deadline scheduler initialized and scheduled to run every 3 hours")
    except Exception as e:
        logger.error(f"Failed to initialize deadline scheduler: {e}")

    # Инициализация teacher subscription scheduler
    try:
        from teacher_mode.subscription_scheduler import register_teacher_subscription_jobs

        register_teacher_subscription_jobs(application)
        logger.info("Teacher subscription scheduler initialized")
    except Exception as e:
        logger.error(f"Failed to initialize teacher subscription scheduler: {e}")

    # Инициализация streak reminder scheduler (Phase 2: Notifications)
    try:
        from core.streak_reminder_scheduler import get_streak_reminder_scheduler

        streak_scheduler = get_streak_reminder_scheduler()
        application.bot_data['streak_reminder_scheduler'] = streak_scheduler

        # Запускаем проверку стриков каждый час
        application.job_queue.run_repeating(
            streak_scheduler.check_and_send_reminders,
            interval=3600,  # 1 час в секундах
            first=300,  # Первый запуск через 5 минут после старта
            name='streak_reminders_check'
        )

        logger.info("Streak reminder scheduler initialized and scheduled to run every hour")
    except Exception as e:
        logger.error(f"Failed to initialize streak reminder scheduler: {e}")

    # Инициализация timezone manager и сброс счётчиков уведомлений
    try:
        from core.timezone_manager import get_timezone_manager

        tz_manager = get_timezone_manager()
        application.bot_data['timezone_manager'] = tz_manager

        # Job для сброса дневных счётчиков уведомлений в 00:00 UTC
        async def reset_daily_notification_counters(context: ContextTypes.DEFAULT_TYPE):
            try:
                tm = context.bot_data.get('timezone_manager')
                if tm:
                    reset_count = await tm.reset_daily_notification_counters()
                    logger.info(f"Daily notification counters reset: {reset_count} users")
            except Exception as e:
                logger.error(f"Error resetting daily notification counters: {e}")

        # Запускаем сброс счётчиков в 00:00 UTC каждый день
        application.job_queue.run_daily(
            reset_daily_notification_counters,
            time=dt_time(hour=0, minute=0, second=0, tzinfo=timezone.utc),
            name='reset_daily_notification_counters'
        )

        # Job для сброса недельных счётчиков в понедельник 00:00 UTC
        async def reset_weekly_notification_counters(context: ContextTypes.DEFAULT_TYPE):
            try:
                tm = context.bot_data.get('timezone_manager')
                if tm:
                    reset_count = await tm.reset_weekly_notification_counters()
                    logger.info(f"Weekly notification counters reset: {reset_count} users")
            except Exception as e:
                logger.error(f"Error resetting weekly notification counters: {e}")

        application.job_queue.run_daily(
            reset_weekly_notification_counters,
            time=dt_time(hour=0, minute=5, second=0, tzinfo=timezone.utc),
            days=(0,),  # 0 = Понедельник
            name='reset_weekly_notification_counters'
        )

        logger.info("Timezone manager initialized with daily/weekly counter reset jobs")
    except Exception as e:
        logger.error(f"Failed to initialize timezone manager: {e}")

    # Регистрация timezone handlers
    try:
        from core.timezone_handlers import register_timezone_handlers
        register_timezone_handlers(application)
        logger.info("Timezone handlers registered")
    except Exception as e:
        logger.error(f"Failed to register timezone handlers: {e}")

    # Загрузка модулей-плагинов
    try:
        from core import plugin_loader
        if hasattr(plugin_loader, 'load_modules'):
            plugin_loader.load_modules(application)
        else:
            # Если load_modules не существует, используем discover_plugins
            plugin_loader.discover_plugins()
            
            # Регистрируем плагины вручную
            for plugin in plugin_loader.PLUGINS:
                try:
                    logger.info(f"Registering plugin: {plugin.title}")
                    plugin.register(application)
                except Exception as e:
                    logger.error(f"Failed to register plugin {plugin.code}: {e}")
            
            # Добавляем обработчик для главного меню
            application.add_handler(
                CallbackQueryHandler(show_plugin_menu, pattern="^main_menu$")
            )
    except Exception as e:
        logger.error(f"Error loading plugins: {e}")
        logger.info("Bot will work without additional plugins")
    # Инициализируем плагины
    if 'plugin_post_init_tasks' in application.bot_data:
        for plugin in application.bot_data['plugin_post_init_tasks']:
            try:
                logger.info(f"Running post_init for plugin: {plugin.title}")
                await plugin.post_init(application)
                logger.info(f"✅ Plugin {plugin.title} initialized")
            except Exception as e:
                logger.error(f"Failed to initialize plugin {plugin.title}: {e}")
            
    logger.info("Post-init завершен")

async def post_shutdown(application: Application) -> None:
    """Очистка ресурсов при остановке бота"""
    logger.info("Выполняется shutdown...")

    # Вызываем дополнительные shutdown handlers из модулей
    if 'custom_shutdown_handlers' in application.bot_data:
        for handler in application.bot_data['custom_shutdown_handlers']:
            try:
                await handler(application)
                logger.info(f"Custom shutdown handler executed successfully")
            except Exception as e:
                logger.error(f"Error in custom shutdown handler: {e}")

    # Закрываем соединение с БД
    await db.close_db()

    logger.info("Shutdown завершен")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start с улучшенным приветствием."""
    user = update.effective_user
    user_id = user.id

    # Сохраняем/обновляем информацию о пользователе
    await db.update_user_info(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name
    )

    # Парсим и сохраняем UTM-метки из deep link (для аналитики рекламы)
    try:
        if context.args and len(context.args) > 0:
            start_param = context.args[0]

            # Пропускаем служебные параметры (payment_success, payment_fail)
            if not start_param.startswith('payment_'):
                from analytics.utm_tracker import parse_utm_from_deeplink, save_user_source

                utm_data = parse_utm_from_deeplink(start_param)

                if utm_data:
                    await save_user_source(user_id, utm_data)
                    logger.info(f"User {user_id} came from {utm_data.get('source', 'unknown')} / {utm_data.get('campaign', 'unknown')}")
    except Exception as e:
        logger.error(f"Error processing UTM for user {user_id}: {e}")
        # Не прерываем работу бота если ошибка в аналитике

    # Проверяем, нужен ли onboarding
    try:
        from core.onboarding import should_start_onboarding
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        if await should_start_onboarding(user_id):
            # Назначаем пользователя на вариант A/B теста СРАЗУ
            from analytics.ab_testing import assign_user_to_variant
            variant = await assign_user_to_variant(user_id, 'onboarding_flow')
            context.user_data['ab_variant'] = variant
            context.user_data['onboarding_started'] = datetime.now().isoformat()
            context.user_data['onboarding_correct_answers'] = 0

            logger.info(f"Starting onboarding for user {user_id}, variant: {variant}")
            await db.track_funnel_event(user_id, 'onboarding_started', {'ab_variant': variant})

            user_name = user.first_name or "друг"

            # Вариант C: INSTANT VALUE - кнопка для старта
            if variant == 'instant_value':
                welcome_text = f"""👋 <b>Привет, {user_name}!</b>

🎓 Я — твой ИИ-репетитор по обществознанию с искусственным интеллектом.

<b>Попробуй прямо сейчас!</b>
Реши простой вопрос из ЕГЭ и получи мгновенную проверку 👇
"""

                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎯 Попробовать!", callback_data="start_onboarding")]
                ])

                await send_message_with_retry(
                    update.message,
                    welcome_text,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML
                )
                return

            # Варианты A и B: показываем AI-демо первым
            else:
                welcome_text = f"""👋 <b>Привет, {user_name}!</b>

🎓 Я — твой ИИ-репетитор по обществознанию с искусственным интеллектом.

<b>Сейчас покажу тебе секретный инструмент,</b> из-за которого сюда приходят:

🤖 <b>ИИ-проверка заданий 19-25</b>
Проверяю как эксперт ФИПИ, только мгновенно.

⏱ <b>Это займёт 30 секунд</b>
Готов посмотреть?
"""

                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🚀 Показывай!", callback_data="start_onboarding")]
                ])

                await send_message_with_retry(
                    update.message,
                    welcome_text,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.HTML
                )
                return

    except Exception as e:
        logger.error(f"Error checking onboarding for user {user_id}: {e}")
        # Продолжаем нормальный flow если ошибка

    args = context.args
    
    if args and len(args) > 0:
        param = args[0]
        
        # Обработка возврата после оплаты
        if param.startswith('payment_success_'):
            order_id = param.replace('payment_success_', '')
            await send_message_with_retry(
                update.message,
                "✅ <b>Спасибо за оплату!</b>\n\n"
                "Ваша подписка будет активирована в течение нескольких минут.\n"
                "Используйте /my_subscriptions для проверки статуса.",
                parse_mode=ParseMode.HTML
            )
            return

        elif param.startswith('payment_fail_'):
            order_id = param.replace('payment_fail_', '')
            await send_message_with_retry(
                update.message,
                "❌ <b>Оплата не прошла</b>\n\n"
                "Попробуйте оформить подписку еще раз.\n"
                "Используйте /subscribe для выбора плана.",
                parse_mode=ParseMode.HTML
            )
            return
    
    # Проверяем/создаем пользователя в БД
    await db.ensure_user(user_id)
    
    # Определяем, новый ли это пользователь (через context.user_data)
    is_new_user = not context.user_data.get('returning_user', False)
    context.user_data['returning_user'] = True
    
    # Проверяем подписку
    subscription_manager = context.bot_data.get('subscription_manager')
    subscription_info = None
    
    if subscription_manager:
        subscription_info = await subscription_manager.get_subscription_info(user_id)
    
    # Персонализированное приветствие
    user_name = user.first_name or "друг"
    current_hour = datetime.now().hour
    
    if 5 <= current_hour < 12:
        greeting = "Доброе утро"
    elif 12 <= current_hour < 17:
        greeting = "Добрый день"
    elif 17 <= current_hour < 23:
        greeting = "Добрый вечер"
    else:
        greeting = "Привет"
    
    # Формируем текст в зависимости от статуса подписки и нового/старого пользователя
    if is_new_user:
        # КРАТКОЕ и убедительное приветствие для НОВЫХ пользователей
        welcome_text = f"{greeting}, {user_name}! 👋\n\n"
        welcome_text += "🎯 <b>Готовься к ЕГЭ по обществознанию с ИИ-репетитором</b>\n\n"

        welcome_text += "✨ <b>Что тебя ждёт:</b>\n\n"

        welcome_text += "🆓 <b>Тестовая часть:</b> 1000+ вопросов с разборами\n"
        welcome_text += "💎 <b>Вторая часть:</b> ИИ проверяет задания 19-25 как эксперт ФИПИ\n"
        welcome_text += "🎁 <b>Бонус:</b> 3 бесплатных AI-проверки в неделю\n\n"

        if not subscription_info or not subscription_info.get('is_active'):
            welcome_text += "🚀 <b>Попробуй прямо сейчас:</b>\n"
            welcome_text += "• Пробный период: 1₽ за 7 дней полного доступа\n"
            welcome_text += "• Полная подписка: 249₽/мес\n\n"

        welcome_text += "👇 <b>Начни с бесплатной тестовой части или попробуй AI-проверку!</b>"
        
    else:
        # КОРОТКОЕ приветствие для ВОЗВРАЩАЮЩИХСЯ пользователей
        if subscription_info and subscription_info.get('is_active'):
            # Пользователь с активной подпиской
            expires = subscription_info.get('expires_at').strftime('%d.%m.%Y')
            welcome_text = f"{greeting}, {user_name}! С возвращением! 👋\n\n"
            welcome_text += f"✅ <b>Подписка активна до {expires}</b>\n\n"
            
            # Показываем доступные модули
            if subscription_info.get('type') == 'modular':
                welcome_text += "📚 <b>Твои модули:</b>\n"
                modules = subscription_info.get('modules', [])

                module_names = {
                    'task19': '• ✅ Задание 19',
                    'task20': '• ✅ Задание 20',
                    'task24': '• ✅ Задание 24',
                    'task25': '• ✅ Задание 25'
                }

                # ИСПРАВЛЕНИЕ: Отображаем только платные модули (test_part бесплатен для всех)
                for module in modules:
                    if module != 'test_part':  # Исключаем бесплатный модуль
                        display_name = module_names.get(module, f'• ✅ {module}')
                        welcome_text += f"{display_name}\n"
            else:
                welcome_text += "📚 <b>Все модули доступны!</b>\n"
            
            # Мотивационное сообщение
            if 5 <= current_hour < 9:
                welcome_text += "\n☕ Отличное время для утренней практики!"
            elif 9 <= current_hour < 12:
                welcome_text += "\n🧠 Мозг на пике активности — лови момент!"
            elif 12 <= current_hour < 15:
                welcome_text += "\n📚 Самое время закрепить материал!"
            elif 15 <= current_hour < 18:
                welcome_text += "\n⚡ Используй время с пользой!"
            elif 18 <= current_hour < 22:
                welcome_text += "\n🎯 Вечерняя тренировка — ключ к успеху!"
            else:
                welcome_text += "\n🌙 Полуночная подготовка? Уважаю!"
            
            welcome_text += "\n\nВыбирай модуль и продолжим подготовку:"
            
        else:
            # Возвращающийся пользователь без подписки - среднее по длине сообщение
            welcome_text = f"{greeting}, {user_name}! С возвращением! 👋\n\n"

            # Показываем информацию о лимитах
            freemium_manager = context.bot_data.get('freemium_manager')
            if freemium_manager:
                limit_info = await freemium_manager.get_limit_info(user_id)
                remaining = limit_info.get('checks_remaining', 0)
                if remaining > 0:
                    welcome_text += f"📊 Сегодня доступно: <b>{remaining} AI-проверки</b>\n\n"
                else:
                    welcome_text += "⏳ Лимит проверок исчерпан. Обновится завтра.\n\n"

            welcome_text += "🆓 <b>Тестовая часть всегда бесплатна!</b>\n"
            welcome_text += "• 1000+ вопросов с разборами\n"
            welcome_text += "• Все блоки и темы ЕГЭ\n"
            welcome_text += "• Отслеживание прогресса\n\n"

            welcome_text += "💎 <b>Открой больше возможностей:</b>\n"
            welcome_text += "• ИИ-проверка заданий 19-25\n"
            welcome_text += "• Персональные рекомендации\n"
            welcome_text += "• 249₽/месяц за полный доступ\n\n"

            welcome_text += "👇 Начни тренировку или оформи подписку:"

    # Получаем меню с индикацией доступа (используем оригинальную функцию)
    menu_keyboard = await show_main_menu_with_access(context, user_id)

    # ============ НОВОЕ: Добавляем информацию о стриках ============
    # Информация уже загружена в show_main_menu_with_access
    streak_display = context.user_data.get('streak_display')
    streak_progress = context.user_data.get('streak_progress')
    streak_warning = context.user_data.get('streak_warning')

    # Добавляем информацию о стриках в приветствие
    if streak_display:
        welcome_text += f"\n\n{streak_display}"

        if streak_progress:
            welcome_text += f"\n{streak_progress}"

        if streak_warning:
            welcome_text += f"\n\n{streak_warning}"
    # ================================================

    # Используем retry-обертку для надежной отправки сообщения
    await send_message_with_retry(
        update.message,
        welcome_text,
        reply_markup=menu_keyboard,
        parse_mode="HTML"
    )

async def show_main_menu_with_access(context, user_id):
    """
    Показывает главное меню с правильной индикацией доступа и системными кнопками.

    Phase 1 Updates:
    1. Добавлена информация о стриках
    2. Progress bar до следующего уровня
    3. Countdown warning при угрозе потери стрика
    4. Счетчик домашних заданий для учеников
    """
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    subscription_manager = context.bot_data.get('subscription_manager')
    buttons = []

    # ============ НОВОЕ: Информация о стриках ============
    try:
        from core.streak_ui import get_streak_ui
        streak_ui = get_streak_ui()

        # Получаем информацию о стриках для отображения
        streak_display = await streak_ui.get_streak_display_for_menu(user_id)
        progress_display = await streak_ui.get_progress_to_next_level(user_id)
        countdown_warning = await streak_ui.get_countdown_warning(user_id)

        # Сохраняем в context для использования в start_command
        context.user_data['streak_display'] = streak_display
        context.user_data['streak_progress'] = progress_display
        context.user_data['streak_warning'] = countdown_warning

    except Exception as e:
        import logging
        logging.getLogger(__name__).debug(f"Streak UI not available: {e}")
        context.user_data['streak_display'] = None
        context.user_data['streak_progress'] = None
        context.user_data['streak_warning'] = None
    # ================================================

    # Получаем список плагинов
    from core import plugin_loader
    plugins = plugin_loader.PLUGINS

    # Получаем информацию о freemium лимитах для отображения счетчика
    freemium_info = None
    try:
        from core.freemium_manager import get_freemium_manager
        freemium_manager = get_freemium_manager(subscription_manager)
        freemium_info = await freemium_manager.get_limit_info(user_id)
    except Exception as e:
        import logging
        logging.getLogger(__name__).debug(f"Freemium manager not available: {e}")

    for plugin in plugins:
        if plugin.code == 'test_part':
            # Тестовая часть - всегда доступна бесплатно
            icon = "🆓"
            badge = " БЕСПЛАТНО"
            text = f"{icon} {plugin.title}{badge}"

        elif plugin.code == 'personal_cabinet':
            # Личный кабинет - всегда доступен без замочка
            icon = ""
            text = f"{plugin.title}"

        elif plugin.code == 'teacher_mode':
            # Режим учителя - всегда доступен (проверка доступа внутри)
            icon = ""
            text = f"{plugin.title}"

        elif subscription_manager:
            # Проверяем доступ к платным модулям
            has_access = await subscription_manager.check_module_access(user_id, plugin.code)

            if has_access:
                icon = "✅"
                text = f"{icon} {plugin.title}"
            else:
                icon = "🔒"
                # Для закрытых модулей показываем счетчик бесплатных проверок
                if freemium_info and not freemium_info['is_premium']:
                    remaining = freemium_info['checks_remaining']
                    if remaining > 0:
                        # Сокращаем длинные названия и выносим счетчик в начало
                        display_title = plugin.title
                        # Убираем длинные подзаголовки в скобках для экономии места
                        if '(' in display_title and ')' in display_title:
                            display_title = display_title[:display_title.find('(')].strip()
                        text = f"🆓 {remaining}/3 {icon} {display_title}"
                    else:
                        text = f"{icon} {plugin.title}"
                else:
                    text = f"{icon} {plugin.title}"
        else:
            # Если система подписок недоступна
            icon = "📚"
            text = f"{icon} {plugin.title}"

        button = InlineKeyboardButton(
            text=text,
            callback_data=f"choose_{plugin.code}"
        )
        buttons.append([button])

    # Добавляем кнопку домашних заданий для учеников с учителем
    try:
        from teacher_mode.services.teacher_service import get_student_teachers
        from teacher_mode.services.assignment_service import count_new_homeworks

        student_teachers = await get_student_teachers(user_id)
        if len(student_teachers) > 0:
            # Ученик привязан к учителю - показываем кнопку ДЗ
            new_count = await count_new_homeworks(user_id)

            if new_count > 0:
                hw_text = f"📚 Домашние задания ({new_count} новых)"
            else:
                hw_text = "📚 Домашние задания"

            homework_button = InlineKeyboardButton(
                text=hw_text,
                callback_data="student_homework_list"
            )
            # Вставляем после тестовой части (обычно 1-я кнопка)
            buttons.insert(1, [homework_button])
    except Exception as e:
        # Если модуль учителя недоступен, просто не показываем кнопку
        import logging
        logging.getLogger(__name__).debug(f"Teacher module not available: {e}")

    return InlineKeyboardMarkup(buttons)

async def handle_my_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает информацию о подписке пользователя."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    subscription_manager = context.bot_data.get('subscription_manager')
    
    if not subscription_manager:
        await query.edit_message_text("❌ Сервис подписок временно недоступен")
        return
    
    subscription_info = await subscription_manager.get_subscription_info(user_id)
    
    if subscription_info:
        if subscription_info.get('type') == 'modular':
            # Модульная подписка
            text = "💳 <b>Ваша подписка</b>\n\n"
            text += "✅ <b>Активные модули:</b>\n"
            
            for module in subscription_info.get('modules', []):
                text += f"   • {module}\n"
            
            text += f"\n📅 <b>Действует до:</b> {subscription_info.get('expires_at').strftime('%d.%m.%Y')}\n"
            
            # Проверяем доступ к каждому модулю для детальной информации
            text += "\n📊 <b>Детали доступа:</b>\n"
            # ИСПРАВЛЕНИЕ 3: Убираем test_part из списка проверяемых модулей
            modules_to_check = ['task19', 'task20', 'task21', 'task22', 'task23', 'task24', 'task25']
            module_names = {
                'task19': '🎯 Задание 19',
                'task20': '📖 Задание 20',
                'task21': '📊 Задание 21',
                'task22': '📝 Задание 22',
                'task23': '📜 Задание 23',
                'task24': '💎 Задание 24',
                'task25': '✍️ Задание 25'
            }
            
            for module_code in modules_to_check:
                has_access = await subscription_manager.check_module_access(user_id, module_code)
                status = "✅" if has_access else "❌"
                text += f"   {status} {module_names.get(module_code, module_code)}\n"
        else:
            # Единая подписка
            text = "💳 <b>Ваша подписка</b>\n\n"
            text += f"✅ <b>План:</b> {subscription_info.get('plan_name')}\n"
            text += f"📅 <b>Действует до:</b> {subscription_info.get('expires_at').strftime('%d.%m.%Y')}\n"
    else:
        text = "💎 <b>Модульная система подписок</b>\n\n"
        text += "У вас пока нет активной подписки.\n\n"
        text += "<b>Доступные тарифы:</b>\n\n"
        
        text += "🎁 <b>Пробный период</b> — 1₽\n"
        text += "   • Полный доступ на 7 дней\n"
        text += "   • Все модули включены\n\n"
        
        text += "🎯 <b>Пакет «Вторая часть»</b> — 499₽/мес\n"
        text += "   • Задание 19, 20, 25\n"
        text += "   <i>Экономия 98₽</i>\n\n"
        
        text += "👑 <b>Полный доступ</b> — 799₽/мес\n"
        text += "   • Все модули\n"
        text += "   • Приоритетная поддержка\n"
        text += "   <i>Экономия 97₽</i>\n\n"
        
        text += "📚 Или выберите отдельные модули"
    
    buttons = []
    
    # ИСПРАВЛЕНИЕ 1: Добавляем кнопки продления/обновления подписки
    if subscription_info:
        # Пользователь с активной подпиской
        buttons.append([InlineKeyboardButton("🔄 Продлить подписку", callback_data="renew_subscription")])
        buttons.append([InlineKeyboardButton("➕ Добавить модули", callback_data="subscribe_start")])
    else:
        # Пользователь без подписки
        buttons.append([InlineKeyboardButton("💳 Оформить подписку", callback_data="subscribe_start")])
    
    buttons.append([InlineKeyboardButton("⬅️ Главное меню", callback_data="to_main_menu")])
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML"
    )

# Исправленная функция show_main_menu
def show_main_menu(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    """Синхронная обертка для совместимости."""
    # Возвращаем базовое меню без проверки доступа
    # Асинхронную версию нужно вызывать отдельно
    from core.plugin_loader import build_main_menu
    return build_main_menu()

async def help_command(update: Update, context):
    """Обработчик команды /help"""
    
    # Попробуем получить актуальные цены
    try:
        from payment.config import SUBSCRIPTION_MODE, MODULE_PLANS, LEGACY_SUBSCRIPTION_PLANS
        
        if SUBSCRIPTION_MODE == 'modular':
            pricing_text = """
💎 О подписках (модульная система):
- Бесплатно: 50 вопросов в месяц
- Отдельные модули: от 149₽/мес
- Пакеты: от 499₽/мес
- Полный доступ: 999₽/мес
"""
        else:
            plans = LEGACY_SUBSCRIPTION_PLANS
            pricing_text = f"""
💎 О подписках:
- Бесплатно: 50 вопросов в месяц
- Базовая ({plans['basic_month']['price_rub']}₽/мес): 100 вопросов в день
- Pro ({plans['pro_month']['price_rub']}₽/мес): неограниченно
- Pro до ЕГЭ ({plans['pro_ege']['price_rub']}₽): неограниченно до ЕГЭ 2025
"""
    except:
        # Fallback
        pricing_text = """
💎 О подписках:
- Бесплатно: 50 вопросов в месяц
- Различные планы подписки доступны
- Используйте /subscribe для просмотра актуальных цен
"""
    
    help_text = f"""
📚 Справка по командам:

/start - начать работу с ботом
/menu - показать главное меню
/subscribe - оформить подписку
/status - проверить статус подписки
/help - показать эту справку

{pricing_text}

По всем вопросам: @obshestvonapalcahsupport
    """
    await update.message.reply_text(help_text, parse_mode="HTML")

async def menu_command(update: Update, context):
    """Обработчик команды /menu"""
    user = update.effective_user
    
    # НОВОЕ: Обновляем информацию о пользователе при каждом вызове /menu
    await db.update_user_info(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name
    )
    
    try:
        # Пробуем использовать меню с проверкой доступа
        user_id = update.effective_user.id
        try:
            from core.app import show_main_menu_with_access
            kb = await show_main_menu_with_access(context, user_id)
        except:
            # Если функция недоступна, используем базовое меню
            from core.plugin_loader import build_main_menu
            kb = build_main_menu()
        
        text = "📚 Выберите раздел для подготовки к ЕГЭ:"
        
        # Добавим приветствие с именем если доступно
        if user.first_name:
            text = f"👋 Привет, {user.first_name}!\n\n" + text
        
        await update.message.reply_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Error in menu_command: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка при загрузке меню.\n"
            "Попробуйте /start для перезапуска бота."
        )

async def show_plugin_menu(update: Update, context):
    """Показывает меню плагинов"""
    query = update.callback_query
    await query.answer()
    
    try:
        from core import plugin_loader
        menu = plugin_loader.build_main_menu()
        await query.edit_message_text(
            "📚 Выберите раздел для подготовки:",
            reply_markup=menu
        )
    except Exception as e:
        logger.error(f"Error showing plugin menu: {e}")
        await query.edit_message_text("❌ Ошибка при загрузке меню")

def main():
    """Главная функция запуска бота"""
    # Настройка логирования
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    
    # Проверка наличия токена
    if not hasattr(config, 'BOT_TOKEN') or not config.BOT_TOKEN:
        logger.error("BOT_TOKEN не найден в конфигурации!")
        return
    
    # Создание приложения
    try:
        builder = Application.builder()
        builder.token(config.BOT_TOKEN)
        
        persistence = PicklePersistence(
            filepath="bot_persistence.pickle",
            # Сохраняем данные каждые 30 секунд и при завершении
            update_interval=30,
            # ИСПРАВЛЕНИЕ: Исключаем bot_data из сохранения, т.к. он содержит
            # несериализуемые объекты (managers, schedulers с ссылками на Bot)
            store_data=PersistenceInput(
                bot_data=False,      # НЕ сохраняем bot_data (содержит менеджеры)
                chat_data=True,      # Сохраняем chat_data
                user_data=True,      # Сохраняем user_data
                callback_data=True   # Сохраняем callback_data
            )
        )
        builder.persistence(persistence)
        
        # Настройка параметров
        builder.post_init(post_init)
        builder.post_shutdown(post_shutdown)
        
        # Дополнительные настройки
        from telegram.request import HTTPXRequest

        # ИСПРАВЛЕНО: Увеличены timeout для предотвращения TimedOut ошибок
        # Особенно важно при медленном соединении или через прокси
        # Увеличены значения для более стабильной работы с Telegram API
        # Установлены максимальные значения для проблемных соединений
        request_kwargs = {
            'connect_timeout': 30.0,  # было 20.0 - увеличено до 30s
            'read_timeout': 60.0,     # было 30.0 - увеличено до 60s
            'write_timeout': 60.0,    # было 30.0 - увеличено до 60s
            'pool_timeout': 30.0      # было 20.0 - увеличено до 30s
        }

        if hasattr(config, 'PROXY_URL') and config.PROXY_URL:
            request_kwargs['proxy'] = config.PROXY_URL

        # Создаем HTTP клиент с настройками timeout и retry
        http_request = HTTPXRequest(**request_kwargs)
        builder.request(http_request)

        # Также настраиваем отдельный клиент для get_updates с более длительным timeout
        # get_updates использует long polling и требует более длинный timeout
        get_updates_request_kwargs = request_kwargs.copy()
        get_updates_request_kwargs['read_timeout'] = 90.0  # 90 секунд для long polling
        get_updates_http_request = HTTPXRequest(**get_updates_request_kwargs)
        builder.get_updates_request(get_updates_http_request)
        
        # Создаем приложение
        application = builder.build()
        
        logger.info("Запуск бота...")
        
        # Запуск бота
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )
        
    except Exception as e:
        logger.exception(f"Критическая ошибка при запуске бота: {e}")
        raise

if __name__ == '__main__':
    main()