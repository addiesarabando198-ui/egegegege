# payment/admin_commands.py
"""Админские команды для управления подписками."""
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, Application, CallbackQueryHandler
from telegram.constants import ParseMode
from functools import wraps
import aiosqlite
from core import config
from core.config import DATABASE_FILE
from .subscription_manager import SubscriptionManager
from .config import SUBSCRIPTION_MODE

DATABASE_PATH = 'quiz_async.db'
logger = logging.getLogger(__name__)


def admin_only(func):
    """Декоратор для проверки админских прав."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        # Проверяем список админов
        admin_ids = []
        if hasattr(config, 'ADMIN_IDS') and config.ADMIN_IDS:
            if isinstance(config.ADMIN_IDS, str):
                admin_ids = config.ADMIN_IDS if isinstance(config.ADMIN_IDS, list) else []
            elif isinstance(config.ADMIN_IDS, list):
                admin_ids = [int(id) for id in config.ADMIN_IDS]
        
        if user_id not in admin_ids:
            await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
            return
        
        return await func(update, context)
    
    return wrapper

@admin_only
async def cmd_test_webhook(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Тестирует webhook, отправляя тестовый запрос."""
    import aiohttp
    
    # Создаем тестовый платеж
    test_order_id = f"TEST_{int(datetime.now().timestamp())}"
    user_id = update.effective_user.id
    
    subscription_manager = context.bot_data.get('subscription_manager')
    
    # Создаем запись о платеже
    await subscription_manager.create_payment(
        user_id=user_id,
        plan_id='trial_7days',
        amount_kopecks=100
    )
    
    # Симулируем webhook от Tinkoff
    webhook_data = {
        "TerminalKey": config.TINKOFF_TERMINAL_KEY,
        "OrderId": test_order_id,
        "Status": "CONFIRMED",
        "PaymentId": "12345",
        "Token": "test_token"  # В реальности нужен правильный токен
    }
    
    webhook_url = f"http://localhost:8080/webhook"  # Или ваш webhook URL
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=webhook_data) as response:
                result = await response.text()
                status = response.status
        
        await update.message.reply_text(
            f"🧪 Тест webhook:\n"
            f"Status: {status}\n"
            f"Response: {result}\n"
            f"Order ID: {test_order_id}"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка теста: {e}")


@admin_only
async def cmd_grant_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выдает подписку пользователю вручную. Использование: /grant_subscription <user_id> <plan_id>"""
    # Импортируем здесь, если не импортировано выше
    from .config import SUBSCRIPTION_PLANS, SUBSCRIPTION_MODE
    from datetime import datetime
    
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Использование: /grant_subscription <user_id> <plan_id>\n\n"
            "Доступные планы:\n"
            "• trial_7days - пробный период\n"
            "• package_second_part - пакет 'Вторая часть'\n"
            "• package_full - полный доступ\n"
            "• module_test_part - только тестовая часть\n"
            "• module_task19 - только задание 19\n"
            "• module_task20 - только задание 20\n"
            "• module_task25 - только задание 25\n"
            "• module_task24 - только задание 24"
        )
        return
    
    try:
        user_id = int(context.args[0])
        plan_id = context.args[1]
        
        # Проверяем, существует ли план
        if plan_id not in SUBSCRIPTION_PLANS:
            await update.message.reply_text(f"❌ Неизвестный план: {plan_id}")
            return
        
        subscription_manager = context.bot_data.get('subscription_manager')
        if not subscription_manager:
            # Создаем новый экземпляр если не найден
            from .subscription_manager import SubscriptionManager
            subscription_manager = SubscriptionManager()
        
        # Создаем фиктивный payment_id
        payment_id = f"ADMIN_GRANT_{int(datetime.now().timestamp())}"
        
        # Активируем подписку
        try:
            if SUBSCRIPTION_MODE == 'modular':
                await subscription_manager._activate_modular_subscription(user_id, plan_id, payment_id)
            else:
                await subscription_manager._activate_unified_subscription(user_id, plan_id, payment_id)
        except Exception as e:
            logger.error(f"Error activating subscription: {e}")
            await update.message.reply_text(f"❌ Ошибка при активации: {e}")
            return
        
        # Получаем информацию о подписке
        subscription_info = await subscription_manager.get_subscription_info(user_id)
        
        text = f"✅ Подписка выдана успешно!\n\n"
        text += f"Пользователь: {user_id}\n"
        text += f"План: {SUBSCRIPTION_PLANS[plan_id]['name']}\n"
        
        if subscription_info:
            if SUBSCRIPTION_MODE == 'modular':
                modules = subscription_info.get('modules', [])
                if modules:
                    text += f"Модули: {', '.join(modules)}\n"
            text += f"Действует до: {subscription_info.get('expires_at')}"
        
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        
        # Уведомляем пользователя
        try:
            # Отправляем простое уведомление без деталей
            await context.bot.send_message(
                user_id,
                f"🎁 Администратор активировал для вас подписку!\n\n"
                f"Используйте /my_subscriptions для просмотра деталей."
            )
        except Exception as e:
            logger.error(f"Failed to notify user {user_id}: {e}")
            await update.message.reply_text(
                f"⚠️ Подписка активирована, но не удалось отправить уведомление пользователю"
            )
            
    except ValueError:
        await update.message.reply_text("❌ Неверный формат user_id. Используйте числовой ID.")
    except Exception as e:
        logger.exception(f"Error granting subscription: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")

@admin_only
async def cmd_promo_usage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает детальную статистику использования промокодов."""
    
    if not context.args:
        # Показываем общую статистику
        try:
            async with aiosqlite.connect(DATABASE_FILE) as conn:
                # Общая статистика
                cursor = await conn.execute("""
                    SELECT 
                        COUNT(DISTINCT promo_code) as total_codes,
                        COUNT(DISTINCT user_id) as unique_users,
                        COUNT(*) as total_uses,
                        SUM(discount_applied) as total_discount
                    FROM promo_usage_log
                """)
                stats = await cursor.fetchone()
                
                text = "📊 <b>Статистика использования промокодов</b>\n\n"
                
                if stats and stats[0]:
                    text += f"📋 Уникальных кодов: {stats[0]}\n"
                    text += f"👥 Уникальных пользователей: {stats[1]}\n"
                    text += f"🔄 Всего использований: {stats[2]}\n"
                    text += f"💸 Общая скидка: {stats[3] or 0} ₽\n\n"
                else:
                    text += "Промокоды еще не использовались\n\n"
                
                # Последние использования
                cursor = await conn.execute("""
                    SELECT 
                        p.promo_code,
                        p.user_id,
                        u.first_name,
                        p.discount_applied,
                        p.used_at
                    FROM promo_usage_log p
                    LEFT JOIN users u ON p.user_id = u.user_id
                    ORDER BY p.used_at DESC
                    LIMIT 10
                """)
                recent = await cursor.fetchall()
                
                if recent:
                    text += "<b>Последние использования:</b>\n"
                    for code, user_id, name, discount, used_at in recent:
                        user_text = f"{name or 'User'} ({user_id})"
                        text += f"• <code>{code}</code> - {user_text} - {discount}₽\n"
                
                text += "\n<b>Команды:</b>\n"
                text += "/promo_usage <code> - детали по коду\n"
                text += "/promo_usage user <user_id> - история пользователя"
                
                await update.message.reply_text(text, parse_mode=ParseMode.HTML)
                
        except Exception as e:
            logger.error(f"Error getting promo usage stats: {e}")
            await update.message.reply_text(f"❌ Ошибка: {e}")
    
    elif context.args[0].lower() == 'user' and len(context.args) > 1:
        # Показываем историю конкретного пользователя
        try:
            user_id = int(context.args[1])
            
            async with aiosqlite.connect(DATABASE_FILE) as conn:
                cursor = await conn.execute("""
                    SELECT 
                        promo_code,
                        discount_applied,
                        original_price,
                        final_price,
                        order_id,
                        used_at
                    FROM promo_usage_log
                    WHERE user_id = ?
                    ORDER BY used_at DESC
                """, (user_id,))
                
                usage = await cursor.fetchall()
                
                text = f"🔍 <b>История промокодов пользователя {user_id}</b>\n\n"
                
                if usage:
                    total_discount = 0
                    for code, discount, original, final, order_id, used_at in usage:
                        text += f"📅 {used_at}\n"
                        text += f"   Промокод: <code>{code}</code>\n"
                        text += f"   Скидка: {discount} ₽\n"
                        text += f"   Цена: {original/100 if original else 0}₽ → {final/100 if final else 0}₽\n"
                        if order_id:
                            text += f"   Заказ: <code>{order_id}</code>\n"
                        text += "\n"
                        total_discount += discount or 0
                    
                    text += f"💰 <b>Общая экономия: {total_discount} ₽</b>"
                else:
                    text += "Пользователь не использовал промокоды"
                
                await update.message.reply_text(text, parse_mode=ParseMode.HTML)
                
        except ValueError:
            await update.message.reply_text("❌ Неверный формат user_id")
        except Exception as e:
            logger.error(f"Error getting user promo history: {e}")
            await update.message.reply_text(f"❌ Ошибка: {e}")
    
    else:
        # Показываем детали конкретного промокода
        promo_code = context.args[0].upper()
        
        try:
            async with aiosqlite.connect(DATABASE_FILE) as conn:
                # Информация о промокоде
                cursor = await conn.execute("""
                    SELECT 
                        discount_percent,
                        discount_amount,
                        usage_limit,
                        used_count,
                        is_active,
                        created_at
                    FROM promo_codes
                    WHERE code = ?
                """, (promo_code,))
                
                promo_info = await cursor.fetchone()
                
                if not promo_info:
                    await update.message.reply_text(f"❌ Промокод {promo_code} не найден")
                    return
                
                text = f"🎁 <b>Промокод {promo_code}</b>\n\n"
                
                discount_percent, discount_amount, limit, used, active, created = promo_info
                
                text += f"📊 Скидка: "
                if discount_percent:
                    text += f"{discount_percent}%\n"
                else:
                    text += f"{discount_amount} ₽\n"
                
                text += f"📈 Использований: {used}"
                if limit:
                    text += f" из {limit}\n"
                else:
                    text += " (без лимита)\n"
                
                text += f"✅ Статус: {'Активен' if active else 'Неактивен'}\n"
                text += f"📅 Создан: {created}\n\n"
                
                # Кто использовал
                cursor = await conn.execute("""
                    SELECT 
                        p.user_id,
                        u.first_name,
                        u.username,
                        p.discount_applied,
                        p.used_at
                    FROM promo_usage_log p
                    LEFT JOIN users u ON p.user_id = u.user_id
                    WHERE p.promo_code = ?
                    ORDER BY p.used_at DESC
                    LIMIT 20
                """, (promo_code,))
                
                users = await cursor.fetchall()
                
                if users:
                    text += "<b>Использовали:</b>\n"
                    for user_id, name, username, discount, used_at in users:
                        user_text = f"{name or 'User'}"
                        if username:
                            user_text += f" (@{username})"
                        user_text += f" [{user_id}]"
                        
                        text += f"• {user_text}\n"
                        text += f"   {used_at} | -{discount}₽\n"
                else:
                    text += "Еще никто не использовал"
                
                await update.message.reply_text(text, parse_mode=ParseMode.HTML)
                
        except Exception as e:
            logger.error(f"Error getting promo details: {e}")
            await update.message.reply_text(f"❌ Ошибка: {e}")

@admin_only
async def cmd_check_user_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверяет подписку конкретного пользователя. Использование: /check_user_subscription <user_id>"""
    if not context.args:
        await update.message.reply_text(
            "Использование: /check_user_subscription <user_id>\n"
            "Например: /check_user_subscription 7390670490"
        )
        return
    
    try:
        user_id = int(context.args[0])
        subscription_manager = context.bot_data.get('subscription_manager', SubscriptionManager())
        
        text = f"🔍 <b>Проверка подписки для пользователя {user_id}</b>\n\n"
        
        # Проверяем общую подписку
        subscription = await subscription_manager.check_active_subscription(user_id)
        if subscription:
            text += "✅ <b>Активная подписка найдена:</b>\n"
            text += f"План: {subscription.get('plan_id')}\n"
            text += f"Истекает: {subscription.get('expires_at')}\n"
            
            if SUBSCRIPTION_MODE == 'modular':
                text += f"Активные модули: {', '.join(subscription.get('active_modules', []))}\n"
        else:
            text += "❌ <b>Активная подписка не найдена</b>\n"
        
        # Проверяем модули (если модульная система)
        if SUBSCRIPTION_MODE == 'modular':
            text += "\n📦 <b>Проверка доступа к модулям:</b>\n"
            modules = await subscription_manager.get_user_modules(user_id)
            
            if modules:
                for module in modules:
                    text += f"• {module['module_code']} до {module['expires_at']}\n"
            else:
                text += "Нет активных модулей\n"
        
        # Проверяем историю платежей
        text += "\n💳 <b>История платежей:</b>\n"
        try:
            async with aiosqlite.connect(DATABASE_FILE) as conn:
                cursor = await conn.execute(
                    """
                    SELECT order_id, plan_id, status, amount_kopecks, created_at 
                    FROM payments 
                    WHERE user_id = ? 
                    ORDER BY created_at DESC 
                    LIMIT 5
                    """,
                    (user_id,)
                )
                payments = await cursor.fetchall()
                
                if payments:
                    for payment in payments:
                        order_id, plan_id, status, amount, created_at = payment
                        text += f"• {plan_id} - {status} - {amount/100:.2f}₽ ({created_at})\n"
                else:
                    text += "Нет платежей\n"
        except Exception as e:
            logger.error(f"Error getting payment history: {e}")
            text += f"Ошибка при получении истории: {e}\n"
        
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        
    except ValueError:
        await update.message.reply_text("❌ Неверный формат user_id")
    except Exception as e:
        logger.exception(f"Error checking user subscription: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")

@admin_only
async def cmd_revoke_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отзывает подписку у пользователя."""
    if not context.args:
        await update.message.reply_text("Использование: /revoke <user_id>")
        return
    
    try:
        user_id = int(context.args[0])
        
        subscription_manager = SubscriptionManager()
        success = await subscription_manager.cancel_subscription(user_id)
        
        if success:
            await update.message.reply_text(
                f"✅ Подписка пользователя {user_id} отозвана"
            )
        else:
            await update.message.reply_text("❌ Ошибка при отзыве подписки")
            
    except ValueError:
        await update.message.reply_text("❌ Неверный ID пользователя")
    except Exception as e:
        logger.exception(f"Error revoking subscription: {e}")
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

@admin_only
async def cmd_activate_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Активирует pending платеж вручную. Использование: /activate_payment <order_id>"""
    if not context.args:
        # Показываем список pending платежей
        try:
            async with aiosqlite.connect(DATABASE_FILE) as conn:
                cursor = await conn.execute(
                    """
                    SELECT order_id, user_id, plan_id, amount_kopecks, created_at
                    FROM payments 
                    WHERE status = 'pending'
                    ORDER BY created_at DESC
                    LIMIT 10
                    """
                )
                pending_payments = await cursor.fetchall()
                
                if not pending_payments:
                    await update.message.reply_text("✅ Нет неподтвержденных платежей")
                    return
                
                text = "⚠️ <b>Неподтвержденные платежи:</b>\n\n"
                for payment in pending_payments:
                    order_id, user_id, plan_id, amount, created_at = payment
                    text += f"<code>{order_id}</code>\n"
                    text += f"├ User: {user_id}\n"
                    text += f"├ План: {plan_id}\n"
                    text += f"├ Сумма: {amount/100:.2f} руб.\n"
                    text += f"└ Создан: {created_at}\n\n"
                
                text += "Для активации используйте:\n"
                text += "<code>/activate_payment ORDER_ID</code>"
                
                await update.message.reply_text(text, parse_mode=ParseMode.HTML)
                
        except Exception as e:
            logger.error(f"Error listing pending payments: {e}")
            await update.message.reply_text(f"❌ Ошибка: {e}")
        return
    
    order_id = context.args[0]
    
    try:
        subscription_manager = context.bot_data.get('subscription_manager', SubscriptionManager())
        
        # Проверяем, существует ли платеж
        async with aiosqlite.connect(DATABASE_FILE) as conn:
            cursor = await conn.execute(
                "SELECT user_id, plan_id, status FROM payments WHERE order_id = ?",
                (order_id,)
            )
            payment = await cursor.fetchone()
            
            if not payment:
                await update.message.reply_text(f"❌ Платеж {order_id} не найден")
                return
            
            user_id, plan_id, status = payment
            
            if status != 'pending':
                await update.message.reply_text(
                    f"⚠️ Платеж {order_id} уже имеет статус: {status}"
                )
                return
        
        # Активируем подписку
        payment_id = f"ADMIN_ACTIVATE_{datetime.now().timestamp()}"
        success = await subscription_manager.activate_subscription(
            order_id=order_id,
            payment_id=payment_id
        )
        
        if success:
            text = f"✅ Платеж активирован успешно!\n\n"
            text += f"Order ID: <code>{order_id}</code>\n"
            text += f"User ID: {user_id}\n"
            text += f"План: {plan_id}\n\n"
            
            # Получаем информацию о подписке
            subscription_info = await subscription_manager.get_subscription_info(user_id)
            if subscription_info:
                if SUBSCRIPTION_MODE == 'modular':
                    text += f"Модули: {', '.join(subscription_info.get('modules', []))}\n"
                text += f"Действует до: {subscription_info.get('expires_at')}"
            
            await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text(
                f"❌ Ошибка при активации платежа {order_id}\n"
                f"Проверьте логи для деталей."
            )
            
    except Exception as e:
        logger.exception(f"Error activating payment: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")


@admin_only
async def cmd_check_webhook(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверяет настройки webhook."""
    from payment.config import WEBHOOK_BASE_URL, WEBHOOK_PATH, TINKOFF_TERMINAL_KEY
    
    text = "🔧 <b>Настройки Webhook:</b>\n\n"
    
    if WEBHOOK_BASE_URL:
        webhook_url = f"{WEBHOOK_BASE_URL}{WEBHOOK_PATH}"
        text += f"✅ URL: <code>{webhook_url}</code>\n"
        text += f"✅ Terminal Key: <code>{TINKOFF_TERMINAL_KEY[:8]}...</code>\n\n"
        text += "⚠️ <b>Убедитесь, что этот URL:</b>\n"
        text += "• Добавлен в настройках Tinkoff\n"
        text += "• Доступен из интернета\n"
        text += "• Использует HTTPS\n\n"
        text += f"<b>Для проверки выполните:</b>\n"
        text += f"<code>curl -X POST {webhook_url}</code>"
    else:
        text += "❌ <b>WEBHOOK_BASE_URL не настроен!</b>\n\n"
        text += "Добавьте в .env:\n"
        text += "<code>WEBHOOK_BASE_URL=https://yourdomain.com</code>\n\n"
        text += "⚠️ Без webhook платежи не будут активироваться автоматически!"
    
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    
@admin_only
async def cmd_payment_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает подробную статистику платежей и подписок."""
    try:
        import aiosqlite
        from payment.config import DATABASE_PATH, SUBSCRIPTION_MODE
        from datetime import datetime, timedelta, timezone
        
        await update.message.reply_text("⏳ Собираю статистику...")
        
        async with aiosqlite.connect(DATABASE_PATH) as db:
            # Общая статистика
            cursor = await db.execute("""
                SELECT 
                    COUNT(DISTINCT user_id) as total_users,
                    COUNT(*) as total_payments,
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed_payments,
                    SUM(CASE WHEN status = 'completed' THEN amount_kopecks ELSE 0 END) as total_revenue
                FROM payments
            """)
            stats = await cursor.fetchone()
            total_users, total_payments, completed_payments, total_revenue = stats
            
            # Статистика по планам
            cursor = await db.execute("""
                SELECT plan_id, COUNT(*) as count, SUM(amount_kopecks) as revenue
                FROM payments
                WHERE status = 'completed'
                GROUP BY plan_id
                ORDER BY count DESC
            """)
            plan_stats = await cursor.fetchall()
            
            # Активные подписки
            if SUBSCRIPTION_MODE == 'modular':
                # Для модульной системы
                cursor = await db.execute("""
                    SELECT COUNT(DISTINCT user_id) as active_users
                    FROM module_subscriptions
                    WHERE is_active = 1 AND expires_at > datetime('now')
                """)
                active_subs = await cursor.fetchone()
                active_users = active_subs[0]
                
                # Статистика по модулям
                cursor = await db.execute("""
                    SELECT module_code, COUNT(DISTINCT user_id) as users
                    FROM module_subscriptions
                    WHERE is_active = 1 AND expires_at > datetime('now')
                    GROUP BY module_code
                """)
                module_stats = await cursor.fetchall()
            else:
                # Для единой системы
                cursor = await db.execute("""
                    SELECT COUNT(DISTINCT user_id) as active_users
                    FROM user_subscriptions
                    WHERE status = 'active' AND expires_at > datetime('now')
                """)
                active_subs = await cursor.fetchone()
                active_users = active_subs[0]
                module_stats = []
            
            # Платежи за последние 30 дней
            cursor = await db.execute("""
                SELECT 
                    COUNT(*) as recent_payments,
                    SUM(CASE WHEN status = 'completed' THEN amount_kopecks ELSE 0 END) as recent_revenue
                FROM payments
                WHERE created_at > datetime('now', '-30 days')
            """)
            recent = await cursor.fetchone()
            recent_payments, recent_revenue = recent
            
            # Формируем сообщение
            text = "📊 <b>Статистика платежей</b>\n\n"
            
            text += "📈 <b>Общая статистика:</b>\n"
            text += f"👥 Всего пользователей: {total_users}\n"
            text += f"💳 Всего платежей: {total_payments}\n"
            text += f"✅ Успешных платежей: {completed_payments}\n"
            text += f"💰 Общий доход: {total_revenue/100:.2f}₽\n\n"
            
            text += "🎯 <b>Активные подписки:</b>\n"
            text += f"👤 Активных пользователей: {active_users}\n"
            
            if module_stats:
                text += "\n<b>По модулям:</b>\n"
                module_names = {
                    'test_part': '📝 Тестовая часть',
                    'task19': '🎯 Задание 19',
                    'task20': '📖 Задание 20',
                    'task24': '💎 Задание 24',
                    'task25': '✍️ Задание 25'
                }
                for module_code, users in module_stats:
                    name = module_names.get(module_code, module_code)
                    text += f"• {name}: {users} польз.\n"
            
            text += f"\n📅 <b>За последние 30 дней:</b>\n"
            text += f"💳 Платежей: {recent_payments}\n"
            text += f"💰 Доход: {recent_revenue/100:.2f}₽\n"
            
            if plan_stats:
                text += "\n💎 <b>Популярные планы:</b>\n"
                plan_names = {
                    'trial_7days': '🎁 Пробный период',
                    'package_second_part': '🎯 Вторая часть',
                    'package_full': '👑 Полный доступ',
                    'module_test_part': '📝 Тестовая часть',
                    'module_task19': '💡 Задание 19',
                    'module_task20': '📖 Задание 20',
                    'module_task24': '💎 Задание 24',
                    'module_task25': '✍️ Задание 25'
                }
                for plan_id, count, revenue in plan_stats[:5]:  # Топ-5 планов
                    name = plan_names.get(plan_id, plan_id)
                    text += f"• {name}: {count} шт. ({revenue/100:.0f}₽)\n"
            
            # Добавляем кнопки для дополнительных действий
            keyboard = [
                [InlineKeyboardButton("📋 Экспорт в CSV", callback_data="admin:export_payments")],
                [InlineKeyboardButton("👥 Список активных", callback_data="admin:list_active_users")],
                [InlineKeyboardButton("🔄 Обновить", callback_data="admin:refresh_stats")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                text, 
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
            
    except Exception as e:
        logger.exception(f"Error getting payment stats: {e}")
        await update.message.reply_text(f"❌ Ошибка получения статистики: {e}")

async def cmd_check_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверяет админские права пользователя."""
    user_id = update.effective_user.id
    
    # Получаем список админов из конфигурации
    admin_ids = []
    if hasattr(config, 'ADMIN_IDS') and config.ADMIN_IDS:
        if isinstance(config.ADMIN_IDS, str):
            admin_ids = config.ADMIN_IDS if isinstance(config.ADMIN_IDS, list) else []
        elif isinstance(config.ADMIN_IDS, list):
            admin_ids = config.ADMIN_IDS
    
    # Также проверяем BOT_ADMIN_IDS если есть
    if hasattr(config, 'BOT_ADMIN_IDS'):
        if isinstance(config.BOT_ADMIN_IDS, list):
            bot_admin_ids = config.BOT_ADMIN_IDS
        elif isinstance(config.BOT_ADMIN_IDS, str):
            bot_admin_ids = [int(id.strip()) for id in config.BOT_ADMIN_IDS.split(',') if id.strip()]
        else:
            bot_admin_ids = []
    else:
        bot_admin_ids = admin_ids  # Используем обычный ADMIN_IDS
    
    # Убираем дубликаты
    admin_ids = list(set(admin_ids))
    
    if user_id in admin_ids:
        await update.message.reply_text(
            f"✅ <b>Вы администратор!</b>\n\n"
            f"📱 Ваш ID: <code>{user_id}</code>\n"
            f"👥 Всего админов: {len(admin_ids)}\n"
            f"📋 Список ID админов: {', '.join(map(str, admin_ids))}\n\n"
            f"Доступные команды:\n"
            f"/grant &lt;user_id&gt; &lt;plan&gt; - выдать подписку\n"
            f"/revoke &lt;user_id&gt; - отозвать подписку\n"
            f"/payment_stats - статистика платежей",
            parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(
            f"❌ <b>Вы не администратор</b>\n\n"
            f"📱 Ваш ID: <code>{user_id}</code>\n"
            f"💡 Чтобы получить права администратора:\n\n"
            f"1. Добавьте ваш ID в файл <code>.env</code>:\n"
            f"   <code>ADMIN_IDS={user_id}</code>\n\n"
            f"2. Перезапустите бота\n\n"
            f"Текущие админы: {len(admin_ids)}",
            parse_mode=ParseMode.HTML
        )

@admin_only
async def cmd_subscribers_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Быстрая проверка количества активных подписчиков."""
    try:
        import aiosqlite
        from payment.config import DATABASE_PATH, SUBSCRIPTION_MODE
        
        async with aiosqlite.connect(DATABASE_PATH) as db:
            # Количество активных подписчиков
            if SUBSCRIPTION_MODE == 'modular':
                cursor = await db.execute("""
                    SELECT COUNT(DISTINCT user_id) 
                    FROM module_subscriptions
                    WHERE is_active = 1 AND expires_at > datetime('now')
                """)
            else:
                cursor = await db.execute("""
                    SELECT COUNT(DISTINCT user_id)
                    FROM user_subscriptions
                    WHERE status = 'active' AND expires_at > datetime('now')
                """)
            
            active_count = (await cursor.fetchone())[0]
            
            # Доход за сегодня
            cursor = await db.execute("""
                SELECT 
                    COUNT(*) as today_payments,
                    SUM(CASE WHEN status = 'completed' THEN amount_kopecks ELSE 0 END) as today_revenue
                FROM payments
                WHERE date(created_at) = date('now')
            """)
            today_payments, today_revenue = await cursor.fetchone()
            today_revenue = today_revenue or 0
            
            # Доход за месяц
            cursor = await db.execute("""
                SELECT SUM(amount_kopecks)
                FROM payments
                WHERE status = 'completed' 
                AND created_at > datetime('now', '-30 days')
            """)
            month_revenue = (await cursor.fetchone())[0] or 0
            
            text = f"""📊 <b>Быстрая статистика</b>

👥 Активных подписчиков: <b>{active_count}</b>

💰 <b>Сегодня:</b>
• Платежей: {today_payments}
• Доход: {today_revenue/100:.2f}₽

📅 <b>За 30 дней:</b>
• Доход: {month_revenue/100:.2f}₽
• Средний чек: {month_revenue/100/max(active_count, 1):.2f}₽

Используйте /payment_stats для подробной статистики"""
            
            await update.message.reply_text(text, parse_mode=ParseMode.HTML)
            
    except Exception as e:
        logger.exception(f"Error getting quick stats: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")

@admin_only
async def cmd_list_active_subscribers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список всех активных подписчиков."""
    try:
        import aiosqlite
        from payment.config import DATABASE_PATH, SUBSCRIPTION_MODE
        from datetime import datetime
        
        async with aiosqlite.connect(DATABASE_PATH) as db:
            if SUBSCRIPTION_MODE == 'modular':
                # Для модульной системы
                cursor = await db.execute("""
                    SELECT DISTINCT 
                        ms.user_id,
                        GROUP_CONCAT(ms.module_code) as modules,
                        MIN(ms.expires_at) as earliest_expiry,
                        MAX(ms.expires_at) as latest_expiry
                    FROM module_subscriptions ms
                    WHERE ms.is_active = 1 AND ms.expires_at > datetime('now')
                    GROUP BY ms.user_id
                    ORDER BY ms.user_id
                """)
            else:
                # Для единой системы
                cursor = await db.execute("""
                    SELECT 
                        us.user_id,
                        us.plan_id,
                        us.expires_at
                    FROM user_subscriptions us
                    WHERE us.status = 'active' AND us.expires_at > datetime('now')
                    ORDER BY us.user_id
                """)
            
            subscribers = await cursor.fetchall()
            
            if not subscribers:
                await update.message.reply_text("📭 Нет активных подписчиков")
                return
            
            # Формируем сообщение
            text = f"👥 <b>Активные подписчики ({len(subscribers)} чел.)</b>\n\n"
            
            # Если подписчиков много, показываем первых 20
            for i, sub in enumerate(subscribers[:20]):
                if SUBSCRIPTION_MODE == 'modular':
                    user_id, modules, earliest, latest = sub
                    text += f"{i+1}. User {user_id}\n"
                    text += f"   Модули: {modules}\n"
                    text += f"   До: {latest[:10]}\n\n"
                else:
                    user_id, plan_id, expires_at = sub
                    text += f"{i+1}. User {user_id}\n"
                    text += f"   План: {plan_id}\n"
                    text += f"   До: {expires_at[:10]}\n\n"
            
            if len(subscribers) > 20:
                text += f"... и еще {len(subscribers) - 20} подписчиков\n"
            
            # Кнопка для экспорта полного списка
            keyboard = [[
                InlineKeyboardButton(
                    "📥 Скачать полный список", 
                    callback_data="admin:export_subscribers"
                )
            ]]
            
            await update.message.reply_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
    except Exception as e:
        logger.exception(f"Error listing subscribers: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")

# Добавьте эти функции в файл payment/admin_commands.py ПЕРЕД функцией register_admin_commands

# ====================== НЕДОСТАЮЩИЕ ФУНКЦИИ ======================

@admin_only
async def handle_refresh_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обновляет и показывает статистику платежей."""
    query = update.callback_query
    await query.answer("Обновляю статистику...")
    
    try:
        import aiosqlite
        from datetime import datetime, timedelta
        
        async with aiosqlite.connect(DATABASE_PATH) as db:
            # Статистика за последние 30 дней
            cursor = await db.execute("""
                SELECT 
                    COUNT(*) as total_payments,
                    COUNT(CASE WHEN status = 'completed' THEN 1 END) as successful,
                    COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed,
                    COUNT(CASE WHEN status = 'pending' THEN 1 END) as pending,
                    SUM(CASE WHEN status = 'completed' THEN amount ELSE 0 END) as total_revenue,
                    AVG(CASE WHEN status = 'completed' THEN amount ELSE NULL END) as avg_payment
                FROM payments
                WHERE created_at > datetime('now', '-30 days')
            """)
            stats = await cursor.fetchone()
            
            # Статистика по планам
            cursor = await db.execute("""
                SELECT plan_id, COUNT(*) as count, SUM(amount) as revenue
                FROM payments
                WHERE status = 'completed' AND created_at > datetime('now', '-30 days')
                GROUP BY plan_id
                ORDER BY count DESC
                LIMIT 5
            """)
            top_plans = await cursor.fetchall()
            
            text = f"""📊 <b>Статистика платежей (30 дней)</b>

📈 <b>Общая статистика:</b>
├ Всего платежей: {stats[0]}
├ ✅ Успешных: {stats[1]}
├ ❌ Неудачных: {stats[2]}
├ ⏳ В ожидании: {stats[3]}
├ 💰 Общий доход: {stats[4] // 100 if stats[4] else 0} ₽
└ 💵 Средний чек: {stats[5] // 100 if stats[5] else 0} ₽

🏆 <b>Топ планов:</b>"""
            
            for i, (plan_id, count, revenue) in enumerate(top_plans, 1):
                text += f"\n{i}. {plan_id}: {count} шт. ({revenue // 100} ₽)"
            
            keyboard = [
                [
                    InlineKeyboardButton("📥 Экспорт CSV", callback_data="admin:export_payments"),
                    InlineKeyboardButton("📈 Графики", callback_data="admin:payment_charts")
                ],
                [InlineKeyboardButton("◀️ Назад", callback_data="admin:payment_stats")]
            ]
            
            await query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
    except Exception as e:
        logger.error(f"Error refreshing stats: {e}")
        await query.edit_message_text(
            "❌ Ошибка при обновлении статистики",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="admin:payment_stats")
            ]])
        )


@admin_only
async def handle_export_payments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспортирует историю платежей в CSV файл."""
    query = update.callback_query
    await query.answer("Экспортирую данные...")
    
    try:
        import aiosqlite
        import csv
        from io import StringIO, BytesIO
        from datetime import datetime
        
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute("""
                SELECT 
                    p.order_id,
                    p.user_id,
                    p.plan_id,
                    p.amount,
                    p.status,
                    p.created_at,
                    p.completed_at,
                    u.username,
                    u.first_name,
                    u.last_name
                FROM payments p
                LEFT JOIN users u ON p.user_id = u.user_id
                ORDER BY p.created_at DESC
                LIMIT 5000
            """)
            payments = await cursor.fetchall()
            
            # Создаем CSV в памяти
            output = StringIO()
            writer = csv.writer(output)
            
            # Заголовки
            writer.writerow([
                'Order ID', 'User ID', 'Username', 'Full Name', 
                'Plan', 'Amount (RUB)', 'Status', 
                'Created', 'Completed'
            ])
            
            # Данные
            for payment in payments:
                full_name = f"{payment[8] or ''} {payment[9] or ''}".strip()
                writer.writerow([
                    payment[0],  # order_id
                    payment[1],  # user_id
                    payment[7] or 'N/A',  # username
                    full_name or 'N/A',  # full name
                    payment[2],  # plan_id
                    payment[3] // 100 if payment[3] else 0,  # amount in rubles
                    payment[4],  # status
                    payment[5],  # created_at
                    payment[6] or 'N/A'  # completed_at
                ])
            
            # Конвертируем в байты
            csv_data = output.getvalue().encode('utf-8-sig')  # UTF-8 with BOM для Excel
            csv_file = BytesIO(csv_data)
            csv_file.name = f"payments_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            
            # Отправляем файл
            await query.message.reply_document(
                document=csv_file,
                filename=csv_file.name,
                caption=f"📊 <b>Экспорт платежей</b>\n\n"
                       f"📅 Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
                       f"📝 Записей: {len(payments)}\n"
                       f"💾 Формат: CSV (Excel-compatible)",
                parse_mode=ParseMode.HTML
            )
            
            await query.edit_message_text(
                "✅ Экспорт завершен! Файл отправлен.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("◀️ Назад", callback_data="admin:refresh_stats")
                ]])
            )
            
    except Exception as e:
        logger.error(f"Error exporting payments: {e}")
        await query.edit_message_text(
            f"❌ Ошибка при экспорте: {str(e)}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="admin:payment_stats")
            ]])
        )


@admin_only
async def sales_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает детальную статистику продаж."""
    query = update.callback_query
    await query.answer()
    
    try:
        import aiosqlite
        from datetime import datetime, timedelta
        
        async with aiosqlite.connect(DATABASE_PATH) as db:
            # Статистика за сегодня
            cursor = await db.execute("""
                SELECT 
                    COUNT(*) as count,
                    SUM(amount) as revenue
                FROM payments
                WHERE status = 'completed' 
                AND DATE(created_at) = DATE('now')
            """)
            today = await cursor.fetchone()
            
            # Статистика за вчера
            cursor = await db.execute("""
                SELECT 
                    COUNT(*) as count,
                    SUM(amount) as revenue
                FROM payments
                WHERE status = 'completed' 
                AND DATE(created_at) = DATE('now', '-1 day')
            """)
            yesterday = await cursor.fetchone()
            
            # Статистика за неделю
            cursor = await db.execute("""
                SELECT 
                    COUNT(*) as count,
                    SUM(amount) as revenue
                FROM payments
                WHERE status = 'completed' 
                AND created_at > datetime('now', '-7 days')
            """)
            week = await cursor.fetchone()
            
            # Статистика за месяц
            cursor = await db.execute("""
                SELECT 
                    COUNT(*) as count,
                    SUM(amount) as revenue
                FROM payments
                WHERE status = 'completed' 
                AND created_at > datetime('now', '-30 days')
            """)
            month = await cursor.fetchone()
            
            text = f"""💰 <b>Статистика продаж</b>

📅 <b>Сегодня:</b>
├ Продаж: {today[0]}
└ Доход: {today[1] // 100 if today[1] else 0} ₽

📅 <b>Вчера:</b>
├ Продаж: {yesterday[0]}
└ Доход: {yesterday[1] // 100 if yesterday[1] else 0} ₽

📅 <b>За 7 дней:</b>
├ Продаж: {week[0]}
├ Доход: {week[1] // 100 if week[1] else 0} ₽
└ Средний чек: {week[1] // week[0] // 100 if week[0] > 0 else 0} ₽

📅 <b>За 30 дней:</b>
├ Продаж: {month[0]}
├ Доход: {month[1] // 100 if month[1] else 0} ₽
└ Средний чек: {month[1] // month[0] // 100 if month[0] > 0 else 0} ₽"""
            
            keyboard = [
                [
                    InlineKeyboardButton("📊 По планам", callback_data="admin:stats_by_plan"),
                    InlineKeyboardButton("👥 По пользователям", callback_data="admin:stats_by_user")
                ],
                [InlineKeyboardButton("◀️ Назад", callback_data="admin:payment_stats")]
            ]
            
            await query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
    except Exception as e:
        logger.error(f"Error showing sales stats: {e}")
        await query.edit_message_text(
            "❌ Ошибка при получении статистики",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="admin:payment_stats")
            ]])
        )


@admin_only
async def payment_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает историю последних платежей."""
    query = update.callback_query
    await query.answer()
    
    try:
        import aiosqlite
        from datetime import datetime
        
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute("""
                SELECT 
                    p.order_id,
                    p.user_id,
                    u.username,
                    p.plan_id,
                    p.amount,
                    p.status,
                    p.created_at
                FROM payments p
                LEFT JOIN users u ON p.user_id = u.user_id
                ORDER BY p.created_at DESC
                LIMIT 10
            """)
            payments = await cursor.fetchall()
            
            text = "📜 <b>История платежей (последние 10)</b>\n\n"
            
            status_emoji = {
                'completed': '✅',
                'pending': '⏳',
                'failed': '❌',
                'refunded': '↩️'
            }
            
            for payment in payments:
                created = datetime.fromisoformat(payment[6])
                username = f"@{payment[2]}" if payment[2] else f"ID:{payment[1]}"
                status = status_emoji.get(payment[5], '❓')
                
                text += f"{status} <b>{created.strftime('%d.%m %H:%M')}</b>\n"
                text += f"├ {username}\n"
                text += f"├ План: {payment[3]}\n"
                text += f"├ Сумма: {payment[4] // 100} ₽\n"
                text += f"└ ID: <code>{payment[0][:20]}</code>\n\n"
            
            keyboard = [
                [
                    InlineKeyboardButton("🔍 Поиск", callback_data="admin:search_payment"),
                    InlineKeyboardButton("📥 Экспорт", callback_data="admin:export_payments")
                ],
                [InlineKeyboardButton("◀️ Назад", callback_data="admin:payment_stats")]
            ]
            
            await query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
    except Exception as e:
        logger.error(f"Error showing payment history: {e}")
        await query.edit_message_text(
            "❌ Ошибка при получении истории",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="admin:payment_stats")
            ]])
        )


@admin_only
async def export_payments_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Алиас для handle_export_payments."""
    return await handle_export_payments(update, context)


@admin_only
async def handle_list_active_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список активных пользователей с подписками."""
    query = update.callback_query
    await query.answer()
    
    try:
        import aiosqlite
        from datetime import datetime
        
        async with aiosqlite.connect(DATABASE_PATH) as db:
            if SUBSCRIPTION_MODE == 'modular':
                cursor = await db.execute("""
                    SELECT DISTINCT 
                        ms.user_id,
                        u.username,
                        u.first_name,
                        u.last_name,
                        GROUP_CONCAT(ms.module_code) as modules,
                        MIN(ms.expires_at) as expires_soon
                    FROM module_subscriptions ms
                    LEFT JOIN users u ON ms.user_id = u.user_id
                    WHERE ms.is_active = 1 AND ms.expires_at > datetime('now')
                    GROUP BY ms.user_id
                    ORDER BY ms.expires_at DESC
                    LIMIT 20
                """)
            else:
                cursor = await db.execute("""
                    SELECT 
                        us.user_id,
                        u.username,
                        u.first_name,
                        u.last_name,
                        us.plan_id,
                        us.expires_at
                    FROM user_subscriptions us
                    LEFT JOIN users u ON us.user_id = u.user_id
                    WHERE us.status = 'active' AND us.expires_at > datetime('now')
                    ORDER BY us.expires_at DESC
                    LIMIT 20
                """)
            
            users = await cursor.fetchall()
            
            text = f"👥 <b>Активные подписчики (топ 20)</b>\n\n"
            
            for i, user in enumerate(users, 1):
                username = f"@{user[1]}" if user[1] else f"ID:{user[0]}"
                full_name = f"{user[2] or ''} {user[3] or ''}".strip()
                
                if SUBSCRIPTION_MODE == 'modular':
                    modules = user[4]
                    expires = datetime.fromisoformat(user[5])
                    text += f"{i}. {username}"
                    if full_name:
                        text += f" ({full_name})"
                    text += f"\n├ Модули: {modules}\n"
                    text += f"└ До: {expires.strftime('%d.%m.%Y')}\n\n"
                else:
                    plan = user[4]
                    expires = datetime.fromisoformat(user[5])
                    text += f"{i}. {username}"
                    if full_name:
                        text += f" ({full_name})"
                    text += f"\n├ План: {plan}\n"
                    text += f"└ До: {expires.strftime('%d.%m.%Y')}\n\n"
            
            # Получаем общее количество
            cursor = await db.execute("""
                SELECT COUNT(DISTINCT user_id) 
                FROM module_subscriptions 
                WHERE is_active = 1 AND expires_at > datetime('now')
            """ if SUBSCRIPTION_MODE == 'modular' else """
                SELECT COUNT(*) 
                FROM user_subscriptions 
                WHERE status = 'active' AND expires_at > datetime('now')
            """)
            total = await cursor.fetchone()
            
            text += f"📊 Всего активных: {total[0]}"
            
            keyboard = [
                [
                    InlineKeyboardButton("📥 Экспорт всех", callback_data="admin:export_users"),
                    InlineKeyboardButton("🔍 Поиск", callback_data="admin:search_user")
                ],
                [InlineKeyboardButton("◀️ Назад", callback_data="admin:users")]
            ]
            
            await query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            
    except Exception as e:
        logger.error(f"Error listing active users: {e}")
        await query.edit_message_text(
            "❌ Ошибка при получении списка пользователей",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="admin:users")
            ]])
        )


@admin_only
async def handle_payment_charts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает графики платежей (заглушка)."""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "📈 <b>Графики платежей</b>\n\n"
        "Функция в разработке. Здесь будут:\n"
        "• График доходов по дням\n"
        "• Распределение по планам\n"
        "• Динамика конверсии\n"
        "• Анализ когорт",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("◀️ Назад", callback_data="admin:refresh_stats")
        ]])
    )


@admin_only
async def handle_stats_by_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает статистику по планам."""
    query = update.callback_query
    await query.answer()
    
    try:
        import aiosqlite
        
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute("""
                SELECT 
                    plan_id,
                    COUNT(*) as sales_count,
                    SUM(amount) as total_revenue,
                    AVG(amount) as avg_amount
                FROM payments
                WHERE status = 'completed'
                GROUP BY plan_id
                ORDER BY total_revenue DESC
            """)
            plans = await cursor.fetchall()
            
            text = "📊 <b>Статистика по планам</b>\n\n"
            
            for plan in plans:
                text += f"<b>{plan[0]}</b>\n"
                text += f"├ Продаж: {plan[1]}\n"
                text += f"├ Доход: {plan[2] // 100 if plan[2] else 0} ₽\n"
                text += f"└ Средний чек: {plan[3] // 100 if plan[3] else 0} ₽\n\n"
            
            await query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("◀️ Назад", callback_data="admin:sales_stats")
                ]])
            )
            
    except Exception as e:
        logger.error(f"Error showing stats by plan: {e}")
        await query.edit_message_text("❌ Ошибка при получении статистики")


@admin_only
async def handle_stats_by_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает топ пользователей по платежам."""
    query = update.callback_query
    await query.answer()
    
    try:
        import aiosqlite
        
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute("""
                SELECT 
                    p.user_id,
                    u.username,
                    u.first_name,
                    COUNT(*) as payment_count,
                    SUM(p.amount) as total_spent
                FROM payments p
                LEFT JOIN users u ON p.user_id = u.user_id
                WHERE p.status = 'completed'
                GROUP BY p.user_id
                ORDER BY total_spent DESC
                LIMIT 10
            """)
            users = await cursor.fetchall()
            
            text = "🏆 <b>Топ-10 пользователей по платежам</b>\n\n"
            
            for i, user in enumerate(users, 1):
                username = f"@{user[1]}" if user[1] else f"ID:{user[0]}"
                text += f"{i}. {username}"
                if user[2]:
                    text += f" ({user[2]})"
                text += f"\n├ Платежей: {user[3]}\n"
                text += f"└ Потрачено: {user[4] // 100} ₽\n\n"
            
            await query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("◀️ Назад", callback_data="admin:sales_stats")
                ]])
            )
            
    except Exception as e:
        logger.error(f"Error showing stats by user: {e}")
        await query.edit_message_text("❌ Ошибка при получении статистики")


# ====================== КОНЕЦ НЕДОСТАЮЩИХ ФУНКЦИЙ ======================

# Добавьте эту функцию в register_admin_commands:
def register_admin_commands(app: Application):
    """Регистрирует админские команды для управления подписками."""
    app.add_handler(CommandHandler("grant_subscription", cmd_grant_subscription))
    app.add_handler(CommandHandler("activate_payment", cmd_activate_payment))
    app.add_handler(CommandHandler("check_webhook", cmd_check_webhook))
    app.add_handler(CommandHandler("revoke", cmd_revoke_subscription))
    app.add_handler(CommandHandler("payment_stats", cmd_payment_stats))
    app.add_handler(CommandHandler("stats", cmd_subscribers_count))
    app.add_handler(CommandHandler("check_admin", cmd_check_admin))
    app.add_handler(CommandHandler("list_subscribers", cmd_list_active_subscribers))
    app.add_handler(CommandHandler("promo_usage", cmd_promo_usage))
    # Обработчики для callback кнопок
    app.add_handler(CallbackQueryHandler(
        handle_export_payments, pattern="^admin:export_payments$"
    ))
    app.add_handler(CallbackQueryHandler(
        handle_list_active_users, pattern="^admin:list_active_users$"
    ))
    app.add_handler(CallbackQueryHandler(
        handle_refresh_stats, pattern="^admin:refresh_stats$"
    ))
    
    logger.info("Admin payment commands registered")
