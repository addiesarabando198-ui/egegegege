# payment/__init__.py
"""Модуль платежей и подписок с поддержкой автопродления."""
import logging
import asyncio
from telegram.ext import Application, CallbackQueryHandler
from .subscription_manager import SubscriptionManager
from .handlers import register_payment_handlers
from .middleware import setup_subscription_middleware
from .decorators import requires_subscription
from .webhook import start_webhook_server, stop_webhook_server
from .admin_commands import register_admin_commands
from .tinkoff import TinkoffPayment
from core import config

logger = logging.getLogger(__name__)

# Экспортируемые объекты
__all__ = [
    'init_payment_module',
    'requires_subscription',
    'SubscriptionManager'
]

# Глобальные объекты
subscription_manager = None
webhook_task = None
auto_renewal_scheduler = None


async def init_payment_module(app: Application):
    """Инициализирует модуль платежей с поддержкой автопродления."""
    global subscription_manager, webhook_task, auto_renewal_scheduler
    
    logger.info("Initializing payment module...")
    
    try:
        # Создаем менеджер подписок
        subscription_manager = SubscriptionManager()
        
        # Сохраняем менеджер в bot_data для доступа из других модулей
        app.bot_data['subscription_manager'] = subscription_manager
        
        # Инициализируем таблицы БД
        await subscription_manager.init_tables()
        logger.info("Database tables initialized")
        
        # Регистрируем основные обработчики платежей
        register_payment_handlers(app)
        logger.info("Payment handlers registered")
        
        # Регистрируем обработчики автопродления
        try:
            from .auto_renewal_handlers import register_auto_renewal_handlers
            register_auto_renewal_handlers(app)
            logger.info("Auto-renewal handlers registered")
        except ImportError as e:
            logger.warning(f"Auto-renewal handlers not available: {e}")
        except Exception as e:
            logger.error(f"Error registering auto-renewal handlers: {e}")
        
        # Регистрируем админские команды (если пользователь админ)
        if hasattr(config, 'ADMIN_IDS') and config.ADMIN_IDS:
            try:
                register_admin_commands(app)
                logger.info("Admin commands registered")
            except Exception as e:
                logger.error(f"Error registering admin commands: {e}")
        
        # Регистрируем middleware для проверки подписок
        try:
            setup_subscription_middleware(
                app,
                free_commands={'start', 'help', 'subscribe', 'menu', 'support', 'my_subscriptions', 'cancel', 'status'},
                free_patterns={
                    'subscribe', 'subscribe_start', 'payment_', 'pay_',
                    'to_main_menu', 'main_menu', 'check_subscription',
                    'module_info_', 'back_to_main', 'my_subscriptions',
                    'duration_', 'confirm_payment', 'cancel_',
                    'support_', 'settings_', 'help_'
                },
                check_channel=False  # Или True, если нужна проверка канала
            )
            logger.info("Subscription middleware setup complete with explicit free commands")
        except Exception as e:
            logger.error(f"Error setting up middleware: {e}")
        
        # Запускаем планировщик автопродления
        try:
            from .auto_renewal_scheduler import AutoRenewalScheduler
            
            auto_renewal_scheduler = AutoRenewalScheduler(
                bot=app.bot,
                subscription_manager=subscription_manager,
                tinkoff_api=TinkoffPayment()
            )
            auto_renewal_scheduler.start()
            app.bot_data['auto_renewal_scheduler'] = auto_renewal_scheduler
            logger.info("Auto-renewal scheduler started")
            
            # Регистрируем обработчик остановки планировщика
            async def shutdown_scheduler(application: Application) -> None:
                """Останавливает планировщик при завершении работы бота."""
                if 'auto_renewal_scheduler' in application.bot_data:
                    scheduler = application.bot_data['auto_renewal_scheduler']
                    if hasattr(scheduler, 'stop'):
                        scheduler.stop()
                        logger.info("Auto-renewal scheduler stopped")

            # Добавляем обработчик в bot_data для вызова при shutdown
            if 'custom_shutdown_handlers' not in app.bot_data:
                app.bot_data['custom_shutdown_handlers'] = []
            app.bot_data['custom_shutdown_handlers'].append(shutdown_scheduler)
            
        except ImportError:
            logger.warning("Auto-renewal scheduler not available (missing apscheduler)")
        except Exception as e:
            logger.error(f"Error starting auto-renewal scheduler: {e}")
        
        # Запускаем webhook сервер для приема уведомлений от платежной системы
        try:
            webhook_task = asyncio.create_task(
                start_webhook_server(
                    bot=app.bot,  # Правильный параметр
                    port=8080      # Опционально: можно указать порт
                )
            )
            logger.info("Payment webhook server started")
        except Exception as e:
            logger.error(f"Error starting webhook server: {e}")
        
        logger.info("✅ Payment module initialized successfully")
        
    except Exception as e:
        logger.error(f"Failed to initialize payment module: {e}")
        raise


async def shutdown_payment_module(app: Application):
    """Корректно завершает работу модуля платежей."""
    global webhook_task, auto_renewal_scheduler
    
    logger.info("Shutting down payment module...")
    
    # Останавливаем webhook сервер
    if webhook_task:
        try:
            await stop_webhook_server()
            webhook_task.cancel()
            await webhook_task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error stopping webhook server: {e}")
    
    # Останавливаем планировщик
    if auto_renewal_scheduler:
        try:
            auto_renewal_scheduler.stop()
        except Exception as e:
            logger.error(f"Error stopping scheduler: {e}")
    
    logger.info("Payment module shutdown complete")
