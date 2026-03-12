# core/admin_tools.py
"""Административные инструменты для управления ботом."""
import logging
from typing import Dict, List, Any, Set, Optional, Callable
from datetime import datetime, timedelta, time
from functools import wraps
import asyncio
import json
import csv
import io
import pickle
import matplotlib
matplotlib.use('Agg')  # Для работы без GUI
import matplotlib.pyplot as plt
from io import BytesIO
import pandas as pd
import openpyxl
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (
    ContextTypes, 
    CommandHandler, 
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    filters
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden

logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
BROADCAST_TEXT, BROADCAST_CONFIRM = range(2)
USER_SEARCH = 3
SETTINGS_VALUE = 4
FILTER_INPUT = 5
PRICE_INPUT = 6
SCHEDULE_MESSAGE = 7
SCHEDULE_TIME = 8
EDIT_PRICE_PLAN = 10
EDIT_PRICE_VALUE = 11
PROMO_CODE_INPUT = 12
PROMO_DISCOUNT_INPUT = 13
PROMO_LIMIT_INPUT = 14

class AdminManager:
    """Менеджер для управления администраторами бота."""
    
    def __init__(self):
        """Инициализация менеджера администраторов."""
        self._admin_ids: Set[int] = set()
        self._failed_attempts: Dict[int, List[datetime]] = {}
        self._load_admins()
    
    def _load_admins(self) -> None:
        """Загрузка списка администраторов из конфигурации."""
        from core import config
        
        # Получаем ADMIN_IDS из конфига (уже список!)
        admin_ids_value = config.ADMIN_IDS
        
        if admin_ids_value:
            try:
                # config.ADMIN_IDS уже является списком чисел
                if isinstance(admin_ids_value, list):
                    self._admin_ids = set(admin_ids_value)
                elif isinstance(admin_ids_value, str):
                    # На случай если вдруг строка
                    admin_ids = [int(id_str.strip()) for id_str in admin_ids_value.split(',') if id_str.strip()]
                    self._admin_ids = set(admin_ids)
                else:
                    # Если одно число
                    self._admin_ids = {int(admin_ids_value)}
                
                logger.info(f"Loaded {len(self._admin_ids)} admin IDs")
            except (ValueError, TypeError) as e:
                logger.error(f"Error parsing ADMIN_IDS: {e}")
                self._admin_ids = {1020468401}
        else:
            # Если не задано или пустой список
            self._admin_ids = {1020468401}
            logger.warning("No ADMIN_IDS found, using default")
    
    def is_admin(self, user_id: int) -> bool:
        """Проверка, является ли пользователь администратором."""
        is_admin = user_id in self._admin_ids
        
        # Записываем неудачные попытки для мониторинга
        if not is_admin:
            now = datetime.now()
            if user_id not in self._failed_attempts:
                self._failed_attempts[user_id] = []
            
            # Очищаем старые попытки (старше часа)
            self._failed_attempts[user_id] = [
                attempt for attempt in self._failed_attempts[user_id]
                if now - attempt < timedelta(hours=1)
            ]
            
            # Добавляем новую попытку
            self._failed_attempts[user_id].append(now)
            
            # Предупреждение при подозрительной активности
            if len(self._failed_attempts[user_id]) >= 5:
                logger.warning(
                    f"⚠️ Suspicious activity: User {user_id} made "
                    f"{len(self._failed_attempts[user_id])} admin access attempts in the last hour"
                )
        
        return is_admin
    
    def add_admin(self, user_id: int) -> bool:
        """Добавление нового администратора."""
        if user_id not in self._admin_ids:
            self._admin_ids.add(user_id)
            logger.info(f"Added new admin: {user_id}")
            return True
        return False
    
    def remove_admin(self, user_id: int) -> bool:
        """Удаление администратора."""
        if user_id in self._admin_ids and len(self._admin_ids) > 1:
            self._admin_ids.remove(user_id)
            logger.info(f"Removed admin: {user_id}")
            return True
        return False
    
    def get_admin_list(self) -> List[int]:
        """Получение списка всех администраторов."""
        return list(self._admin_ids)
    
    def get_security_report(self) -> Dict[str, Any]:
        """Получение отчета о безопасности."""
        return {
            'total_admins': len(self._admin_ids),
            'failed_attempts': {
                user_id: len(attempts) 
                for user_id, attempts in self._failed_attempts.items()
            },
            'suspicious_users': [
                user_id for user_id, attempts in self._failed_attempts.items()
                if len(attempts) >= 3
            ]
        }


# Глобальный экземпляр
admin_manager = AdminManager()

class BroadcastScheduler:
    """Планировщик рассылок."""
    
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.scheduled_broadcasts = {}
        
    def start(self):
        """Запуск планировщика."""
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("Broadcast scheduler started")
    
    def add_broadcast(self, broadcast_id: str, run_time: datetime, message_data: dict, bot):
        """Добавление запланированной рассылки."""
        job = self.scheduler.add_job(
            self._execute_broadcast,
            'date',
            run_date=run_time,
            args=[broadcast_id, message_data, bot],
            id=broadcast_id
        )
        
        self.scheduled_broadcasts[broadcast_id] = {
            'job': job,
            'run_time': run_time,
            'message_data': message_data,
            'status': 'scheduled'
        }
        
        logger.info(f"Scheduled broadcast {broadcast_id} for {run_time}")
        return broadcast_id
    
    async def _execute_broadcast(self, broadcast_id: str, message_data: dict, bot):
        """Выполнение запланированной рассылки."""
        from core import db
        
        try:
            # Получаем всех пользователей
            conn = await db.get_db()
            cursor = await conn.execute("SELECT user_id FROM users")
            users = await cursor.fetchall()
            
            sent = 0
            failed = 0
            
            for (user_id,) in users:
                try:
                    if message_data.get('photo'):
                        await bot.send_photo(
                            chat_id=user_id,
                            photo=message_data['photo'],
                            caption=message_data.get('text', ''),
                            caption_entities=message_data.get('entities')
                        )
                    else:
                        await bot.send_message(
                            chat_id=user_id,
                            text=message_data['text'],
                            entities=message_data.get('entities')
                        )
                    sent += 1
                except Exception as e:
                    failed += 1
                    logger.error(f"Scheduled broadcast error for user {user_id}: {e}")
                
                await asyncio.sleep(0.05)
            
            # Обновляем статус
            self.scheduled_broadcasts[broadcast_id]['status'] = 'completed'
            self.scheduled_broadcasts[broadcast_id]['stats'] = {
                'sent': sent,
                'failed': failed,
                'total': len(users)
            }
            
            # Уведомляем админов
            for admin_id in admin_manager.get_admin_list():
                try:
                    await bot.send_message(
                        admin_id,
                        f"📨 Запланированная рассылка выполнена!\n\n"
                        f"ID: {broadcast_id}\n"
                        f"✅ Отправлено: {sent}\n"
                        f"❌ Ошибок: {failed}"
                    )
                except:
                    pass
                    
        except Exception as e:
            logger.error(f"Failed to execute scheduled broadcast {broadcast_id}: {e}")
            self.scheduled_broadcasts[broadcast_id]['status'] = 'failed'
    
    def cancel_broadcast(self, broadcast_id: str):
        """Отмена запланированной рассылки."""
        if broadcast_id in self.scheduled_broadcasts:
            self.scheduler.remove_job(broadcast_id)
            self.scheduled_broadcasts[broadcast_id]['status'] = 'cancelled'
            return True
        return False
    
    def get_scheduled(self):
        """Получение списка запланированных рассылок."""
        return [
            {
                'id': bid,
                'run_time': data['run_time'],
                'status': data['status']
            }
            for bid, data in self.scheduled_broadcasts.items()
            if data['status'] == 'scheduled'
        ]

# Глобальный экземпляр планировщика
broadcast_scheduler = BroadcastScheduler()

# ============================================
# УПРАВЛЕНИЕ ЦЕНАМИ (новый класс)
# ============================================

class PriceManager:
    """Менеджер цен и тарифов."""
    
    @staticmethod
    async def get_current_prices():
        """Получение текущих цен из БД."""
        from core import db
        
        try:
            conn = await db.get_db()
            cursor = await conn.execute("""
                SELECT plan_id, price, duration_days, description 
                FROM subscription_plans
                ORDER BY price
            """)
            prices = await cursor.fetchall()
            
            if not prices:
                # Возвращаем дефолтные цены
                return {
                    'trial_7days': {'price': 99, 'duration': 7, 'description': 'Пробный период'},
                    'premium_30days': {'price': 299, 'duration': 30, 'description': 'Месячная подписка'},
                    'premium_90days': {'price': 699, 'duration': 90, 'description': 'Квартальная подписка'}
                }
            
            return {
                plan_id: {
                    'price': price,
                    'duration': duration,
                    'description': desc
                }
                for plan_id, price, duration, desc in prices
            }
        except Exception as e:
            logger.error(f"Error getting prices: {e}")
            return {}
    
    @staticmethod
    async def update_price(plan_id: str, new_price: int):
        """Обновление цены тарифа."""
        from core import db
        
        try:
            conn = await db.get_db()
            await conn.execute("""
                UPDATE subscription_plans 
                SET price = ?, updated_at = datetime('now')
                WHERE plan_id = ?
            """, (new_price, plan_id))
            await conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error updating price: {e}")
            return False
    
    @staticmethod
    async def create_plan(plan_id: str, price: int, duration: int, description: str):
        """Создание нового тарифного плана."""
        from core import db
        
        try:
            conn = await db.get_db()
            await conn.execute("""
                INSERT INTO subscription_plans (plan_id, price, duration_days, description, created_at)
                VALUES (?, ?, ?, ?, datetime('now'))
            """, (plan_id, price, duration, description))
            await conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error creating plan: {e}")
            return False


def admin_only(func: Callable) -> Callable:
    """Декоратор для функций, доступных только администраторам."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not user:
            logger.warning("admin_only: не удалось определить пользователя")
            return  
            
        user_id = user.id
        username = user.username or "NoUsername"
        
        if not admin_manager.is_admin(user_id):
            logger.warning(
                f"❌ Попытка доступа к админ функции: "
                f"user_id={user_id}, username=@{username}, "
                f"function={func.__name__}"
            )
            
            if update.callback_query:
                await update.callback_query.answer(
                    "❌ Эта функция доступна только администраторам", 
                    show_alert=True
                )
            else:
                await update.message.reply_text(
                    "❌ Эта функция доступна только администраторам"
                )
            return  
        
        # Логируем успешное использование админских функций
        logger.info(
            f"✅ Админ {user_id} (@{username}) использует {func.__name__}"
        )
            
        return await func(update, context, *args, **kwargs)
    return wrapper


async def safe_edit_message(query, text: str, reply_markup=None, parse_mode=None):
    """
    Безопасное редактирование сообщения с обработкой ошибки "Message is not modified".

    Args:
        query: CallbackQuery объект
        text: Новый текст сообщения
        reply_markup: Клавиатура (опционально)
        parse_mode: Режим парсинга (опционально)

    Returns:
        True если сообщение успешно отредактировано, False в случае ошибки
    """
    try:
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
        return True
    except BadRequest as e:
        if "Message is not modified" in str(e):
            # Сообщение не изменилось - это не ошибка, просто игнорируем
            logger.debug(f"Message not modified in {query.message.chat_id}")
            return False
        else:
            # Другая ошибка BadRequest - пробрасываем дальше
            logger.error(f"BadRequest error editing message: {e}")
            raise
    except Exception as e:
        logger.error(f"Unexpected error editing message: {e}")
        raise


def get_admin_keyboard_extension(user_id: int) -> List[List[InlineKeyboardButton]]:
    """Возвращает дополнительные кнопки для админов."""
    if not admin_manager.is_admin(user_id):
        return []

    return [[InlineKeyboardButton("🔧 Админ", callback_data="admin:main")]]


class AdminStats:
    """Класс для сбора и анализа статистики."""
    
    @staticmethod
    async def get_global_stats(app) -> Dict[str, Any]:
        """Получение глобальной статистики бота."""
        from core import db
        
        try:
            conn = await db.get_db()
            
            # Общее количество пользователей
            cursor = await conn.execute("SELECT COUNT(*) FROM users")
            total_users = (await cursor.fetchone())[0]
            
            # Активные пользователи за последние 30 дней
            cursor = await conn.execute("""
                SELECT COUNT(*) FROM users 
                WHERE last_activity_date > datetime('now', '-30 days')
            """)
            active_users = (await cursor.fetchone())[0]
            
            # Общее количество попыток
            cursor = await conn.execute("SELECT COUNT(*) FROM attempts")
            total_attempts = (await cursor.fetchone())[0]
            
            # Статистика по модулям
            modules = ['task24', 'test_part', 'task19', 'task20', 'task25']
            by_module = {}
            
            for module in modules:
                cursor = await conn.execute(f"""
                    SELECT 
                        COUNT(DISTINCT user_id) as users,
                        COUNT(*) as attempts,
                        AVG(score) as avg_score
                    FROM attempts
                    WHERE module_type = ?
                """, (module,))
                
                result = await cursor.fetchone()
                if result:
                    by_module[module] = {
                        'users': result[0] or 0,
                        'attempts': result[1] or 0,
                        'avg_score': result[2] or 0
                    }
            
            return {
                'total_users': total_users,
                'active_users': active_users,
                'total_attempts': total_attempts,
                'by_module': by_module
            }
            
        except Exception as e:
            logger.error(f"Error getting global stats: {e}")
            return {
                'total_users': 0,
                'active_users': 0,
                'total_attempts': 0,
                'by_module': {}
            }


class AdminKeyboards:
    """Клавиатуры для админских функций."""
    
    @staticmethod
    def main_admin_menu() -> InlineKeyboardMarkup:
        """Главное админское меню."""
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📊 Статистика", callback_data="admin:stats"),
                InlineKeyboardButton("👥 Пользователи", callback_data="admin:users")
            ],
            [
                InlineKeyboardButton("📨 Рассылка", callback_data="admin:broadcast"),
                InlineKeyboardButton("⚙️ Настройки", callback_data="admin:settings")
            ],
            [
                InlineKeyboardButton("🔒 Безопасность", callback_data="admin:security"),
                InlineKeyboardButton("📤 Экспорт", callback_data="admin:export")
            ],
            [
                InlineKeyboardButton("🖥️ Мониторинг", callback_data="admin:system_monitor"),
                InlineKeyboardButton("📚 Контент", callback_data="admin:content_analysis")
            ],
            [InlineKeyboardButton("❌ Закрыть", callback_data="admin:close")]
        ])
    
    @staticmethod
    def stats_menu() -> InlineKeyboardMarkup:
        """Меню статистики."""
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🌍 Глобальная", callback_data="admin:global_stats"),
                InlineKeyboardButton("📈 Активность", callback_data="admin:activity_stats")
            ],
            [
                InlineKeyboardButton("📚 По модулям", callback_data="admin:module_stats"),
                InlineKeyboardButton("🏆 Топ юзеров", callback_data="admin:top_users")
            ],
            [
                InlineKeyboardButton("🔄 Retention", callback_data="admin:retention_stats"),
                InlineKeyboardButton("🎯 Конверсия", callback_data="admin:conversion_stats")
            ],
            [
                InlineKeyboardButton("💰 Финансы", callback_data="admin:financial_analytics")
            ],
            [
                InlineKeyboardButton("📊 Источники трафика", callback_data="admin:traffic_sources"),
                InlineKeyboardButton("📈 Кампании", callback_data="admin:campaign_stats")
            ],
            [
                InlineKeyboardButton("📉 Когортный анализ", callback_data="admin:cohort_analysis")
            ],
            [
                InlineKeyboardButton("🧪 A/B тесты", callback_data="admin:ab_test_stats")
            ],
            [InlineKeyboardButton("⬅️ Назад", callback_data="admin:main")]
        ])
    
    @staticmethod
    def users_menu() -> InlineKeyboardMarkup:
        """Меню управления пользователями."""
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📋 Список всех", callback_data="admin:users_list"),
                InlineKeyboardButton("💎 С подпиской", callback_data="admin:users_premium")
            ],
            [
                InlineKeyboardButton("🔍 Найти пользователя", callback_data="admin:user_search"),
                InlineKeyboardButton("📊 Статистика", callback_data="admin:users_stats")
            ],
            [InlineKeyboardButton("⬅️ Назад", callback_data="admin:main")]
        ])
    
    @staticmethod
    def user_actions(user_id: int, has_subscription: bool, is_banned: bool = False) -> InlineKeyboardMarkup:
        """Клавиатура действий с пользователем."""
        buttons = []

        if has_subscription:
            buttons.append([
                InlineKeyboardButton("❌ Отозвать подписку", callback_data=f"admin:revoke_sub:{user_id}"),
                InlineKeyboardButton("➕ Продлить подписку", callback_data=f"admin:extend_sub:{user_id}")
            ])
        else:
            buttons.append([
                InlineKeyboardButton("🎁 Подарить подписку", callback_data=f"admin:grant_sub:{user_id}")
            ])

        buttons.extend([
            [
                InlineKeyboardButton("📊 Статистика", callback_data=f"admin:user_stats:{user_id}"),
                InlineKeyboardButton("📨 Написать", callback_data=f"admin:message_user:{user_id}")
            ],
            [
                InlineKeyboardButton("🔄 Сбросить прогресс", callback_data=f"admin:reset_progress:{user_id}"),
                InlineKeyboardButton("🔓 Разбан" if is_banned else "⛔ Забанить",
                                   callback_data=f"admin:unban_user:{user_id}" if is_banned else f"admin:ban_user:{user_id}")
            ],
            [InlineKeyboardButton("⬅️ Назад", callback_data="admin:users")]
        ])

        return InlineKeyboardMarkup(buttons)
    
    @staticmethod
    def broadcast_confirm(stats: Dict) -> InlineKeyboardMarkup:
        """Клавиатура подтверждения рассылки."""
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Начать рассылку", callback_data="admin:broadcast_start"),
                InlineKeyboardButton("❌ Отменить", callback_data="admin:broadcast_cancel")
            ]
        ])
    
    @staticmethod
    def settings_menu() -> InlineKeyboardMarkup:
        """Меню настроек."""
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("💰 Цены подписок", callback_data="admin:settings_prices"),
                InlineKeyboardButton("📦 Модули", callback_data="admin:settings_modules")
            ],
            [
                InlineKeyboardButton("🔔 Уведомления", callback_data="admin:settings_notifications"),
                InlineKeyboardButton("🛡️ Режим работы", callback_data="admin:settings_mode")
            ],
            [InlineKeyboardButton("⬅️ Назад", callback_data="admin:main")]
        ])

    @staticmethod
    def export_menu() -> InlineKeyboardMarkup:
        """Меню экспорта данных."""
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📊 Статистика (CSV)", callback_data="admin:export_stats_csv"),
                InlineKeyboardButton("📊 Статистика (Excel)", callback_data="admin:export_stats_excel")
            ],
            [
                InlineKeyboardButton("👥 Пользователи (CSV)", callback_data="admin:export_users_csv"),
                InlineKeyboardButton("👥 Пользователи (Excel)", callback_data="admin:export_users_excel")
            ],
            [
                InlineKeyboardButton("💾 Полный бэкап", callback_data="admin:backup_full"),
                InlineKeyboardButton("📥 Восстановить", callback_data="admin:restore_backup")
            ],
            [InlineKeyboardButton("⬅️ Назад", callback_data="admin:main")]
        ])
    
    @staticmethod
    def filter_menu() -> InlineKeyboardMarkup:
        """Меню фильтров пользователей."""
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📅 По дате регистрации", callback_data="admin:filter_date"),
                InlineKeyboardButton("🕐 По активности", callback_data="admin:filter_activity")
            ],
            [
                InlineKeyboardButton("💎 С подпиской", callback_data="admin:filter_premium"),
                InlineKeyboardButton("❌ Без подписки", callback_data="admin:filter_free")
            ],
            [
                InlineKeyboardButton("📊 По модулям", callback_data="admin:filter_modules"),
                InlineKeyboardButton("🎯 По баллам", callback_data="admin:filter_scores")
            ],
            [InlineKeyboardButton("⬅️ Назад", callback_data="admin:users")]
        ])
    
    @staticmethod
    def schedule_menu() -> InlineKeyboardMarkup:
        """Меню планировщика рассылок."""
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("➕ Запланировать", callback_data="admin:schedule_new"),
                InlineKeyboardButton("📋 Список", callback_data="admin:schedule_list")
            ],
            [
                InlineKeyboardButton("⬅️ Назад", callback_data="admin:broadcast_menu")]
        ])
    
    @staticmethod
    def price_management() -> InlineKeyboardMarkup:
        """Меню управления ценами."""
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("💰 Текущие цены", callback_data="admin:prices_current"),
                InlineKeyboardButton("✏️ Изменить цены", callback_data="admin:prices_edit")
            ],
            [
                InlineKeyboardButton("➕ Новый тариф", callback_data="admin:prices_new"),
                InlineKeyboardButton("📊 Статистика продаж", callback_data="admin:prices_stats")
            ],
            [InlineKeyboardButton("⬅️ Назад", callback_data="admin:settings")]
        ])

# === Обработчики команд ===

@admin_only
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главная админ панель."""
    query = update.callback_query
    if query:
        await query.answer()
    
    user = update.effective_user
    text = (
        f"🔧 <b>Панель администратора</b>\n\n"
        f"Добро пожаловать, {user.first_name}!\n"
        f"Выберите раздел для управления ботом:"
    )
    
    kb = AdminKeyboards.main_admin_menu()
    
    if query:
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@admin_only
async def stats_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню статистики."""
    query = update.callback_query
    await query.answer()

    text = "📊 <b>Статистика</b>\n\nВыберите тип статистики:"
    kb = AdminKeyboards.stats_menu()

    await safe_edit_message(query, text, reply_markup=kb, parse_mode=ParseMode.HTML)


# === РАССЫЛКА ===

@admin_only
async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало процесса рассылки."""
    query = update.callback_query
    await query.answer()
    
    text = (
        "📨 <b>Рассылка сообщений</b>\n\n"
        "Отправьте сообщение, которое хотите разослать всем пользователям бота.\n\n"
        "Поддерживаются:\n"
        "• Текст с форматированием\n"
        "• Фото с подписью\n"
        "• Кнопки (используйте формат JSON)\n\n"
        "Для отмены отправьте /cancel"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отменить", callback_data="admin:main")]
    ])
    
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    
    # Устанавливаем состояние ожидания текста
    context.user_data['broadcast_mode'] = True
    return BROADCAST_TEXT


@admin_only
async def broadcast_receive_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение сообщения для рассылки."""
    if not context.user_data.get('broadcast_mode'):
        return ConversationHandler.END
    
    # Сохраняем сообщение
    if update.message.photo:
        # Сообщение с фото
        context.user_data['broadcast_photo'] = update.message.photo[-1].file_id
        context.user_data['broadcast_text'] = update.message.caption or ""
        context.user_data['broadcast_caption_entities'] = update.message.caption_entities
    else:
        # Текстовое сообщение
        context.user_data['broadcast_text'] = update.message.text
        context.user_data['broadcast_entities'] = update.message.entities
        context.user_data['broadcast_photo'] = None
    
    # Получаем статистику для предпросмотра
    from core import db
    conn = await db.get_db()
    cursor = await conn.execute("SELECT COUNT(*) FROM users")
    total_users = (await cursor.fetchone())[0]
    
    # Показываем предпросмотр
    preview_text = (
        "📨 <b>Предпросмотр рассылки</b>\n\n"
        f"Получателей: {total_users} пользователей\n"
        f"Тип: {'Фото с текстом' if context.user_data.get('broadcast_photo') else 'Текст'}\n\n"
        "Сообщение будет выглядеть так:\n"
        "─────────────────"
    )
    
    await update.message.reply_text(preview_text, parse_mode=ParseMode.HTML)
    
    # Отправляем предпросмотр
    if context.user_data.get('broadcast_photo'):
        await update.message.reply_photo(
            photo=context.user_data['broadcast_photo'],
            caption=context.user_data['broadcast_text'],
            caption_entities=context.user_data.get('broadcast_caption_entities')
        )
    else:
        await update.message.reply_text(
            text=context.user_data['broadcast_text'],
            entities=context.user_data.get('broadcast_entities')
        )
    
    # Клавиатура подтверждения
    kb = AdminKeyboards.broadcast_confirm({'total_users': total_users})
    await update.message.reply_text(
        "─────────────────\n\n"
        "Подтвердите отправку рассылки:",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    return BROADCAST_CONFIRM

@admin_only  # или без этого декоратора для тестирования
async def cmd_debug_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /debugdata - показывает сохраненные данные."""
    
    text = "🔍 <b>DEBUG: User Data</b>\n\n"
    
    # Проверяем данные каждого модуля
    modules_data = {
        'task19': ['task19_results', 'task19_practice_stats'],
        'task20': ['task20_results', 'task20_practice_stats'],
        'task25': ['task25_results', 'task25_practice_stats'],
        'task24': ['task24_results', 'practiced_topics'],
    }
    
    for module, keys in modules_data.items():
        text += f"<b>{module}:</b>\n"
        for key in keys:
            if key in context.user_data:
                value = context.user_data[key]
                if isinstance(value, list):
                    text += f"  {key}: {len(value)} items\n"
                elif isinstance(value, dict):
                    text += f"  {key}: {len(value)} keys\n"
                elif isinstance(value, set):
                    text += f"  {key}: {len(value)} items\n"
                else:
                    text += f"  {key}: exists\n"
            else:
                text += f"  {key}: NOT FOUND ❌\n"
    
    text += f"\n<b>Total keys:</b> {len(context.user_data)}\n"
    text += f"<b>All keys:</b> {', '.join(list(context.user_data.keys())[:15])}"
    
    if len(context.user_data) > 15:
        text += f"... (+{len(context.user_data) - 15} more)"
    
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

@admin_only
async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запуск рассылки."""
    query = update.callback_query
    try:
        await query.answer("Начинаю рассылку...")
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    # Получаем всех пользователей
    from core import db
    conn = await db.get_db()
    cursor = await conn.execute("SELECT user_id FROM users")
    users = await cursor.fetchall()
    
    # Статистика рассылки
    total = len(users)
    sent = 0
    failed = 0
    blocked = 0
    
    # Обновляем сообщение
    progress_message = await query.edit_message_text(
        f"📨 <b>Рассылка запущена</b>\n\n"
        f"Прогресс: 0/{total}\n"
        f"Отправлено: 0\n"
        f"Ошибок: 0",
        parse_mode=ParseMode.HTML
    )
    
    # Отправляем сообщения
    for i, (user_id,) in enumerate(users, 1):
        try:
            if context.user_data.get('broadcast_photo'):
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=context.user_data['broadcast_photo'],
                    caption=context.user_data['broadcast_text'],
                    caption_entities=context.user_data.get('broadcast_caption_entities')
                )
            else:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=context.user_data['broadcast_text'],
                    entities=context.user_data.get('broadcast_entities')
                )
            sent += 1
            
        except Forbidden:
            # Пользователь заблокировал бота
            blocked += 1
            failed += 1
        except Exception as e:
            logger.error(f"Broadcast error for user {user_id}: {e}")
            failed += 1
        
        # Обновляем прогресс каждые 10 сообщений
        if i % 10 == 0 or i == total:
            try:
                await progress_message.edit_text(
                    f"📨 <b>Рассылка в процессе</b>\n\n"
                    f"Прогресс: {i}/{total}\n"
                    f"✅ Отправлено: {sent}\n"
                    f"❌ Ошибок: {failed}\n"
                    f"🚫 Заблокировали: {blocked}",
                    parse_mode=ParseMode.HTML
                )
            except:
                pass
        
        # Задержка для избежания лимитов
        await asyncio.sleep(0.05)
    
    # Финальный отчет
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Готово", callback_data="admin:main")]
    ])
    
    await progress_message.edit_text(
        f"📨 <b>Рассылка завершена!</b>\n\n"
        f"📊 Статистика:\n"
        f"• Всего пользователей: {total}\n"
        f"• ✅ Успешно отправлено: {sent}\n"
        f"• ❌ Ошибок: {failed}\n"
        f"• 🚫 Заблокировали бота: {blocked}\n\n"
        f"Успешность: {(sent/total*100):.1f}%",
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    
    # Очищаем данные рассылки
    context.user_data['broadcast_mode'] = False
    context.user_data.pop('broadcast_text', None)
    context.user_data.pop('broadcast_photo', None)
    
    return ConversationHandler.END


@admin_only
async def broadcast_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена рассылки."""
    query = update.callback_query
    await query.answer("Рассылка отменена")
    
    # Очищаем данные
    context.user_data['broadcast_mode'] = False
    context.user_data.pop('broadcast_text', None)
    context.user_data.pop('broadcast_photo', None)
    
    await admin_panel(update, context)
    return ConversationHandler.END


# === УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ ===

@admin_only
async def handle_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню управления пользователями."""
    query = update.callback_query
    await query.answer()
    
    # Получаем статистику
    from core import db
    from payment.config import SUBSCRIPTION_MODE
    
    conn = await db.get_db()
    
    # Общее количество пользователей
    cursor = await conn.execute("SELECT COUNT(*) FROM users")
    total_users = (await cursor.fetchone())[0]
    
    # Подсчет пользователей с подпиской в зависимости от режима
    if SUBSCRIPTION_MODE == 'modular':
        # Для модульной системы проверяем module_subscriptions
        cursor = await conn.execute("""
            SELECT COUNT(DISTINCT user_id) 
            FROM module_subscriptions 
            WHERE is_active = 1 
            AND expires_at > datetime('now')
        """)
        premium_users = (await cursor.fetchone())[0]
    else:
        # Для единой системы проверяем user_subscriptions
        cursor = await conn.execute("""
            SELECT COUNT(DISTINCT user_id) 
            FROM user_subscriptions 
            WHERE status = 'active' 
            AND expires_at > datetime('now')
        """)
        premium_users = (await cursor.fetchone())[0]
    
    text = (
        "👥 <b>Управление пользователями</b>\n\n"
        f"📊 Статистика:\n"
        f"• Всего пользователей: {total_users}\n"
        f"• С активной подпиской: {premium_users}\n\n"
        "Выберите действие:"
    )
    
    kb = AdminKeyboards.users_menu()
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@admin_only
async def users_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ списка всех пользователей."""
    query = update.callback_query
    try:
        await query.answer("Загрузка...")
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    # Получаем страницу
    page = context.user_data.get('users_page', 0)
    per_page = 10
    
    from core import db
    conn = await db.get_db()
    
    # Получаем общее количество
    cursor = await conn.execute("SELECT COUNT(*) FROM users")
    total_users = (await cursor.fetchone())[0]
    total_pages = (total_users + per_page - 1) // per_page
    
    # Получаем пользователей для текущей страницы
    cursor = await conn.execute("""
        SELECT user_id, username, first_name, last_activity_date 
        FROM users 
        ORDER BY last_activity_date DESC
        LIMIT ? OFFSET ?
    """, (per_page, page * per_page))
    
    users = await cursor.fetchall()
    
    text = f"👥 <b>Все пользователи</b> (стр. {page+1}/{total_pages})\n\n"
    
    for user_id, username, first_name, last_activity in users:
        name = first_name or "Без имени"
        username_str = f"@{username}" if username else "нет username"
        last_active = datetime.fromisoformat(last_activity).strftime("%d.%m.%Y")
        
        text += f"• {name} ({username_str})\n"
        text += f"  ID: <code>{user_id}</code> | Активность: {last_active}\n\n"
    
    # Кнопки навигации
    buttons = []
    nav_buttons = []
    
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️", callback_data=f"admin:users_page:{page-1}"))
    
    nav_buttons.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="admin:noop"))
    
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("▶️", callback_data=f"admin:users_page:{page+1}"))
    
    if nav_buttons:
        buttons.append(nav_buttons)
    
    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin:users")])
    
    kb = InlineKeyboardMarkup(buttons)
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@admin_only
async def users_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ пользователей с подпиской."""
    query = update.callback_query
    try:
        await query.answer("Загрузка...")
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    from core import db
    from payment.config import SUBSCRIPTION_MODE
    
    conn = await db.get_db()
    
    if SUBSCRIPTION_MODE == 'modular':
        # Для модульной системы
        cursor = await conn.execute("""
            SELECT DISTINCT 
                u.user_id, 
                u.username, 
                u.first_name,
                GROUP_CONCAT(ms.module_code) as modules,
                MAX(ms.expires_at) as expires_at
            FROM users u
            INNER JOIN module_subscriptions ms ON u.user_id = ms.user_id
            WHERE ms.is_active = 1 
            AND ms.expires_at > datetime('now')
            GROUP BY u.user_id
            ORDER BY expires_at DESC
            LIMIT 20
        """)
    else:
        # Для единой системы
        cursor = await conn.execute("""
            SELECT 
                u.user_id, 
                u.username, 
                u.first_name, 
                us.plan_id, 
                us.expires_at
            FROM users u
            INNER JOIN user_subscriptions us ON u.user_id = us.user_id
            WHERE us.status = 'active' 
            AND us.expires_at > datetime('now')
            ORDER BY us.expires_at DESC
            LIMIT 20
        """)
    
    premium_users = await cursor.fetchall()
    
    if not premium_users:
        text = "💎 <b>Пользователи с подпиской</b>\n\nПока нет пользователей с активной подпиской."
    else:
        text = f"💎 <b>Пользователи с подпиской</b> ({len(premium_users)})\n\n"
        
        if SUBSCRIPTION_MODE == 'modular':
            # Отображение для модульной системы
            for user_id, username, first_name, modules, expires_at in premium_users:
                name = first_name or "Без имени"
                username_str = f"@{username}" if username else ""
                expires = datetime.fromisoformat(expires_at).strftime("%d.%m.%Y")
                modules_list = modules.split(',') if modules else []
                
                text += f"• {name} {username_str}\n"
                text += f"  ID: <code>{user_id}</code>\n"
                text += f"  Модули: {', '.join(modules_list)}\n"
                text += f"  До: {expires}\n\n"
        else:
            # Отображение для единой системы
            for user_id, username, first_name, plan_id, expires_at in premium_users:
                name = first_name or "Без имени"
                username_str = f"@{username}" if username else ""
                expires = datetime.fromisoformat(expires_at).strftime("%d.%m.%Y")
                
                text += f"• {name} {username_str}\n"
                text += f"  ID: <code>{user_id}</code>\n"
                text += f"  План: {plan_id} | До: {expires}\n\n"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin:users")]
    ])
    
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@admin_only
async def user_search_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало поиска пользователя."""
    query = update.callback_query
    await query.answer()
    
    text = (
        "🔍 <b>Поиск пользователя</b>\n\n"
        "Отправьте:\n"
        "• User ID (например: 123456789)\n"
        "• Username (например: @username)\n"
        "• Имя (часть имени)\n\n"
        "Для отмены отправьте /cancel"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отменить", callback_data="admin:users")]
    ])
    
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    context.user_data['search_mode'] = True
    
    return USER_SEARCH


@admin_only
async def user_search_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка поиска пользователя."""
    if not context.user_data.get('search_mode'):
        return ConversationHandler.END
    
    search_query = update.message.text.strip()
    
    from core import db
    conn = await db.get_db()
    
    # Пытаемся найти пользователя
    user = None
    
    # Поиск по ID
    if search_query.isdigit():
        cursor = await conn.execute(
            "SELECT * FROM users WHERE user_id = ?",
            (int(search_query),)
        )
        user = await cursor.fetchone()
    
    # Поиск по username
    if not user and search_query.startswith('@'):
        cursor = await conn.execute(
            "SELECT * FROM users WHERE username = ?",
            (search_query[1:],)
        )
        user = await cursor.fetchone()
    
    # Поиск по имени
    if not user:
        cursor = await conn.execute(
            "SELECT * FROM users WHERE first_name LIKE ?",
            (f"%{search_query}%",)
        )
        user = await cursor.fetchone()
    
    if not user:
        await update.message.reply_text(
            "❌ Пользователь не найден.\n"
            "Попробуйте другой запрос или отправьте /cancel для отмены."
        )
        return USER_SEARCH
    
    # Показываем информацию о пользователе
    await show_user_details(update, context, user[0])  # user[0] - это user_id
    
    context.user_data['search_mode'] = False
    return ConversationHandler.END


async def show_user_details(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Показ детальной информации о пользователе."""
    from core import db
    from payment.subscription_manager import SubscriptionManager
    
    conn = await db.get_db()
    
    # Получаем данные пользователя
    cursor = await conn.execute(
        "SELECT user_id, username, first_name, last_name, created_at, last_activity_date FROM users WHERE user_id = ?",
        (user_id,)
    )
    user = await cursor.fetchone()

    if not user:
        text = "❌ Пользователь не найден"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад", callback_data="admin:users")]
        ])
        await update.message.reply_text(text, reply_markup=kb)
        return

    # Распаковываем данные
    _, username, first_name, last_name, created_at, last_activity = user
    
    # Проверяем подписку
    subscription_manager = SubscriptionManager()
    subscription = await subscription_manager.check_active_subscription(user_id)
    
    # Получаем статистику
    cursor = await conn.execute("""
        SELECT module_type, COUNT(*), AVG(score) 
        FROM attempts 
        WHERE user_id = ? 
        GROUP BY module_type
    """, (user_id,))
    stats = await cursor.fetchall()
    
    # Формируем текст
    text = f"👤 <b>Информация о пользователе</b>\n\n"
    text += f"🆔 ID: <code>{user_id}</code>\n"
    text += f"👤 Имя: {first_name or 'Не указано'}\n"
    
    if last_name:
        text += f"👤 Фамилия: {last_name}\n"
    
    if username:
        text += f"📱 Username: @{username}\n"
    
    text += f"📅 Регистрация: {datetime.fromisoformat(created_at).strftime('%d.%m.%Y %H:%M')}\n"
    text += f"🕐 Последняя активность: {datetime.fromisoformat(last_activity).strftime('%d.%m.%Y %H:%M')}\n\n"
    
    if subscription:
        text += f"💎 <b>Подписка активна</b>\n"
        text += f"План: {subscription['plan_id']}\n"
        text += f"До: {subscription['expires_at'].strftime('%d.%m.%Y')}\n\n"
    else:
        text += "❌ <b>Подписка не активна</b>\n\n"
    
    if stats:
        text += "📊 <b>Статистика по модулям:</b>\n"
        for module, attempts, avg_score in stats:
            text += f"• {module}: {attempts} попыток, средний балл: {avg_score:.2f}\n"
    
    # Клавиатура действий
    kb = AdminKeyboards.user_actions(user_id, bool(subscription))
    
    await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@admin_only
async def user_details_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик callback для просмотра деталей пользователя."""
    query = update.callback_query
    await query.answer()

    # Извлекаем user_id из callback_data
    user_id = int(query.data.split(':')[-1])

    from core import db
    from payment.subscription_manager import SubscriptionManager

    conn = await db.get_db()

    # Получаем данные пользователя
    cursor = await conn.execute(
        "SELECT user_id, username, first_name, last_name, created_at, last_activity_date FROM users WHERE user_id = ?",
        (user_id,)
    )
    user = await cursor.fetchone()

    if not user:
        text = "❌ Пользователь не найден"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад", callback_data="admin:users")]
        ])
        await query.edit_message_text(text, reply_markup=kb)
        return

    # Распаковываем данные
    user_id, username, first_name, last_name, created_at, last_activity = user

    # Проверяем подписку
    subscription_manager = SubscriptionManager()
    subscription = await subscription_manager.check_active_subscription(user_id)

    # Проверяем статус бана
    cursor = await conn.execute("""
        SELECT 1 FROM banned_users WHERE user_id = ?
    """, (user_id,))
    is_banned = (await cursor.fetchone()) is not None

    # Получаем статистику
    cursor = await conn.execute("""
        SELECT module_type, COUNT(*), AVG(score)
        FROM attempts
        WHERE user_id = ?
        GROUP BY module_type
    """, (user_id,))
    stats = await cursor.fetchall()

    # Формируем текст
    text = f"👤 <b>Информация о пользователе</b>\n\n"
    text += f"🆔 ID: <code>{user_id}</code>\n"
    text += f"👤 Имя: {first_name or 'Не указано'}\n"

    if last_name:
        text += f"👤 Фамилия: {last_name}\n"

    if username:
        text += f"📱 Username: @{username}\n"

    if is_banned:
        text += f"⛔ <b>Статус: ЗАБЛОКИРОВАН</b>\n"

    if created_at:
        text += f"📅 Регистрация: {created_at}\n"
    if last_activity:
        text += f"🕐 Последняя активность: {last_activity}\n\n"

    if subscription:
        text += f"💎 <b>Подписка активна</b>\n"
        text += f"План: {subscription.get('plan_id', 'Неизвестно')}\n"
        if subscription.get('expires_at'):
            text += f"До: {subscription['expires_at']}\n\n"
    else:
        text += "❌ <b>Подписка не активна</b>\n\n"

    if stats:
        text += "📊 <b>Статистика по модулям:</b>\n"
        module_names = {
            'task24': '📝 Задание 24',
            'test_part': '📚 Тестовая часть',
            'task19': '🎯 Задание 19',
            'task20': '💭 Задание 20',
            'task25': '📋 Задание 25'
        }
        for module, attempts, avg_score in stats:
            name = module_names.get(module, module)
            text += f"• {name}: {attempts} попыток, средний балл: {avg_score:.2f}\n"

    # Клавиатура действий
    kb = AdminKeyboards.user_actions(user_id, bool(subscription), is_banned)

    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@admin_only
async def grant_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выдача подписки пользователю."""
    query = update.callback_query
    user_id = int(query.data.split(':')[-1])

    try:
        await query.answer("Выдаю подписку...")
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    from payment.subscription_manager import SubscriptionManager
    subscription_manager = SubscriptionManager()
    
    # Выдаем подписку на 30 дней
    await subscription_manager.activate_subscription(
        user_id=user_id,
        plan_id='premium_30days',
        payment_id='ADMIN_GRANT',
        amount=0
    )
    
    # Уведомляем пользователя
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text="🎁 <b>Поздравляем!</b>\n\n"
                 "Администратор подарил вам премиум подписку на 30 дней!\n"
                 "Теперь вам доступны все функции бота без ограничений.",
            parse_mode=ParseMode.HTML
        )
    except:
        pass
    
    await query.edit_message_text(
        "✅ Подписка успешно выдана!\n\n"
        f"Пользователь {user_id} получил подписку на 30 дней.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад", callback_data="admin:users")]
        ]),
        parse_mode=ParseMode.HTML
    )


@admin_only
async def revoke_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отзыв подписки у пользователя."""
    query = update.callback_query
    user_id = int(query.data.split(':')[-1])

    try:
        await query.answer("Отзываю подписку...")
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    from core import db
    conn = await db.get_db()
    
    # Деактивируем подписку
    await conn.execute("""
        UPDATE subscriptions 
        SET expires_at = datetime('now', '-1 day')
        WHERE user_id = ? AND expires_at > datetime('now')
    """, (user_id,))
    await conn.commit()
    
    await query.edit_message_text(
        f"✅ Подписка пользователя {user_id} отозвана.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад", callback_data="admin:users")]
        ])
    )


@admin_only
async def message_user_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало процесса отправки сообщения пользователю."""
    query = update.callback_query
    await query.answer()

    user_id = int(query.data.split(':')[-1])
    context.user_data['message_target_user'] = user_id

    text = (
        f"📨 <b>Отправка сообщения пользователю {user_id}</b>\n\n"
        "Отправьте мне сообщение, которое нужно переслать этому пользователю.\n"
        "Поддерживаются:\n"
        "• Текст\n"
        "• Фото с подписью\n"
        "• Файлы\n\n"
        "Для отмены используйте /cancel"
    )

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Отмена", callback_data="admin:users")
        ]]),
        parse_mode=ParseMode.HTML
    )

    return 'AWAITING_MESSAGE'


@admin_only
async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Банит пользователя."""
    query = update.callback_query
    user_id = int(query.data.split(':')[-1])

    try:
        await query.answer("Баню пользователя...")
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    from core import db

    try:
        conn = await db.get_db()

        # Создаем таблицу banned_users если не существует
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS banned_users (
                user_id INTEGER PRIMARY KEY,
                banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                banned_by INTEGER,
                reason TEXT
            )
        """)

        # Добавляем пользователя в бан
        await conn.execute("""
            INSERT OR REPLACE INTO banned_users (user_id, banned_by)
            VALUES (?, ?)
        """, (user_id, update.effective_user.id))

        await conn.commit()

        # Уведомляем пользователя
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="⛔ Ваш доступ к боту был ограничен администратором."
            )
        except:
            pass

        await query.edit_message_text(
            f"✅ Пользователь {user_id} заблокирован.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔓 Разблокировать", callback_data=f"admin:unban_user:{user_id}"),
                InlineKeyboardButton("⬅️ Назад", callback_data="admin:users")
            ]])
        )

    except Exception as e:
        logger.error(f"Error banning user {user_id}: {e}")
        await query.edit_message_text(
            f"❌ Ошибка при блокировке пользователя: {e}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="admin:users")
            ]])
        )


@admin_only
async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Разбанивает пользователя."""
    query = update.callback_query
    user_id = int(query.data.split(':')[-1])

    try:
        await query.answer("Разблокирую пользователя...")
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    from core import db

    try:
        conn = await db.get_db()

        await conn.execute("""
            DELETE FROM banned_users WHERE user_id = ?
        """, (user_id,))

        await conn.commit()

        # Уведомляем пользователя
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="✅ Ваш доступ к боту восстановлен!"
            )
        except:
            pass

        await query.edit_message_text(
            f"✅ Пользователь {user_id} разблокирован.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="admin:users")
            ]])
        )

    except Exception as e:
        logger.error(f"Error unbanning user {user_id}: {e}")
        await query.edit_message_text(
            f"❌ Ошибка при разблокировке: {e}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="admin:users")
            ]])
        )


@admin_only
async def reset_user_progress_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сбрасывает прогресс пользователя."""
    query = update.callback_query
    user_id = int(query.data.split(':')[-1])

    try:
        await query.answer("Сбрасываю прогресс...")
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    from core import db

    try:
        await db.reset_user_progress(user_id)

        # Уведомляем пользователя
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="🔄 Администратор сбросил ваш прогресс.\nВы можете начать заново!"
            )
        except:
            pass

        await query.edit_message_text(
            f"✅ Прогресс пользователя {user_id} сброшен.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data=f"admin:user_details:{user_id}")
            ]])
        )

    except Exception as e:
        logger.error(f"Error resetting progress for {user_id}: {e}")
        await query.edit_message_text(
            f"❌ Ошибка при сбросе прогресса: {e}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="admin:users")
            ]])
        )


# === НАСТРОЙКИ ===

@admin_only
async def handle_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню настроек бота."""
    query = update.callback_query
    await query.answer()
    
    from payment.config import SUBSCRIPTION_MODE
    
    # Получаем настройки уведомлений
    notifications = context.bot_data.get('notifications_settings', {})
    notif_count = sum(1 for v in notifications.values() if v)
    
    text = (
        "⚙️ <b>Настройки бота</b>\n\n"
        f"🛡️ Режим работы: <b>{'Модульный' if SUBSCRIPTION_MODE == 'modular' else 'Единый'}</b>\n"
        f"🔔 Активных уведомлений: <b>{notif_count}</b>\n"
        f"📦 Загружено модулей: <b>{len(getattr(context.bot_data.get('plugins', []), 'PLUGINS', []))}</b>\n\n"
        "Выберите раздел настроек:"
    )
    
    kb = AdminKeyboards.settings_menu()
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@admin_only
async def settings_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Изменение режима работы бота."""
    query = update.callback_query
    await query.answer()
    
    from payment.config import SUBSCRIPTION_MODE
    
    current_mode = SUBSCRIPTION_MODE
    
    text = (
        "🛡️ <b>Режим работы бота</b>\n\n"
        f"Текущий режим: <b>{'Модульный' if current_mode == 'modular' else 'Единый'}</b>\n\n"
        "• <b>Единый</b> - одна подписка на все модули\n"
        "• <b>Модульный</b> - отдельная оплата каждого модуля\n\n"
        "Выберите режим:"
    )
    
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "✅ Единый" if current_mode == 'unified' else "Единый",
                callback_data="admin:set_mode:unified"
            ),
            InlineKeyboardButton(
                "✅ Модульный" if current_mode == 'modular' else "Модульный",
                callback_data="admin:set_mode:modular"
            )
        ],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin:settings")]
    ])
    
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@admin_only
async def set_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установка режима работы."""
    query = update.callback_query
    mode = query.data.split(':')[-1]
    
    # Здесь должно быть сохранение в конфиг
    # Для демонстрации просто показываем сообщение
    await query.answer(f"Режим изменен на {mode}", show_alert=True)
    
    await settings_mode(update, context)


# === Обработчики статистики (оставляем как были) ===

@admin_only
async def global_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ глобальной статистики."""
    query = update.callback_query
    try:
        await query.answer("Загрузка статистики...")
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    stats = await AdminStats.get_global_stats(context.application)
    
    text = (
        "📊 <b>Глобальная статистика бота</b>\n\n"
        f"👥 Всего пользователей: {stats['total_users']}\n"
        f"🎯 Активных (30 дней): {stats['active_users']}\n"
        f"📝 Всего попыток: {stats['total_attempts']}\n\n"
        "<b>По модулям:</b>\n"
    )
    
    for module, data in stats['by_module'].items():
        if data['users'] > 0:
            module_names = {
                'task24': '📝 Задание 24',
                'test_part': '📚 Тестовая часть',
                'task19': '🎯 Задание 19',
                'task20': '💭 Задание 20',
                'task25': '📋 Задание 25'
            }
            name = module_names.get(module, module)
            text += (
                f"\n{name}:\n"
                f"  • Пользователей: {data['users']}\n"
                f"  • Попыток: {data['attempts']}\n"
            )
            if data.get('avg_score'):
                text += f"  • Средний балл: {data['avg_score']:.2f}\n"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 Подробная статистика", callback_data="admin:stats_menu")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin:main")]
    ])
    
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@admin_only
async def activity_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ статистики активности."""
    query = update.callback_query
    try:
        await query.answer("Загрузка активности...")
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    from core import db
    
    text = "📈 <b>Статистика активности</b>\n\n"
    
    try:
        conn = await db.get_db()
        
        cursor = await conn.execute("""
            SELECT 
                DATE(last_activity_date) as day,
                COUNT(DISTINCT user_id) as active_users
            FROM users
            WHERE last_activity_date > datetime('now', '-14 days')
            GROUP BY DATE(last_activity_date)
            ORDER BY day DESC
        """)
        daily_activity = await cursor.fetchall()
        
        if daily_activity:
            text += "📊 <b>Активность за последние 14 дней:</b>\n\n"
            
            max_users = max(row[1] for row in daily_activity) if daily_activity else 1
            
            for day, users in daily_activity:
                bar_length = int((users / max_users) * 20) if max_users > 0 else 0
                bar = "▓" * bar_length + "░" * (20 - bar_length)
                date_str = datetime.strptime(day, "%Y-%m-%d").strftime("%d.%m")
                text += f"<code>{date_str} {bar} {users}</code>\n"
        
    except Exception as e:
        logger.error(f"Ошибка при получении статистики активности: {e}")
        text += "❌ Ошибка при загрузке данных"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Обновить", callback_data="admin:activity_stats")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin:stats_menu")]
    ])

    await safe_edit_message(query, text, reply_markup=kb, parse_mode=ParseMode.HTML)


@admin_only
async def module_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика по модулям."""
    query = update.callback_query
    try:
        await query.answer("Загрузка статистики модулей...")
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    from core import db
    
    text = "📚 <b>Статистика по модулям</b>\n\n"
    
    try:
        conn = await db.get_db()
        
        modules = [
            ('task24', '📝 Задание 24'),
            ('test_part', '📚 Тестовая часть'),
            ('task19', '🎯 Задание 19'),
            ('task20', '💭 Задание 20'),
            ('task25', '📋 Задание 25')
        ]
        
        for module_type, module_name in modules:
            cursor = await conn.execute("""
                SELECT 
                    COUNT(DISTINCT user_id) as unique_users,
                    COUNT(*) as total_attempts,
                    AVG(score) as avg_score,
                    COUNT(CASE WHEN score > 0 THEN 1 END) as successful
                FROM attempts
                WHERE module_type = ?
                AND created_at > datetime('now', '-30 days')
            """, (module_type,))
            
            stats = await cursor.fetchone()
            
            if stats and stats[0] > 0:
                unique_users, total_attempts, avg_score, successful = stats
                success_rate = (successful / total_attempts * 100) if total_attempts > 0 else 0
                
                text += f"<b>{module_name}</b>\n"
                text += f"├ 👥 Пользователей: {unique_users}\n"
                text += f"├ 📝 Попыток: {total_attempts}\n"
                text += f"├ ⭐ Средний балл: {avg_score:.2f}\n"
                text += f"└ ✅ Успешность: {success_rate:.1f}%\n\n"
        
    except Exception as e:
        logger.error(f"Ошибка при получении статистики модулей: {e}")
        text += "❌ Ошибка при загрузке данных"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Обновить", callback_data="admin:module_stats")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin:stats_menu")]
    ])

    await safe_edit_message(query, text, reply_markup=kb, parse_mode=ParseMode.HTML)


@admin_only
async def top_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ топа пользователей."""
    query = update.callback_query
    try:
        await query.answer("Загрузка топа пользователей...")
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    from core import db
    
    text = "🏆 <b>Топ активных пользователей</b>\n\n"
    
    try:
        conn = await db.get_db()
        
        cursor = await conn.execute("""
            SELECT 
                user_id,
                COUNT(*) as total_attempts,
                SUM(score) as total_score,
                COUNT(DISTINCT module_type) as modules_used
            FROM attempts
            WHERE created_at > datetime('now', '-30 days')
            GROUP BY user_id
            ORDER BY total_attempts DESC
            LIMIT 10
        """)
        
        top_users_data = await cursor.fetchall()
        
        if top_users_data:
            for i, (user_id, attempts, score, modules) in enumerate(top_users_data, 1):
                cursor = await conn.execute(
                    "SELECT first_name, username FROM users WHERE user_id = ?",
                    (user_id,)
                )
                user_info = await cursor.fetchone()
                
                if user_info:
                    name = user_info[0] or "Пользователь"
                    username = f"@{user_info[1]}" if user_info[1] else ""
                    
                    medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
                    
                    text += f"{medal} <b>{name}</b> {username}\n"
                    text += f"   📝 Попыток: {attempts}\n"
                    text += f"   📚 Модулей: {modules}/5\n"
                    text += f"   ⭐ Общий балл: {score:.0f}\n\n"
        else:
            text += "Пока нет активных пользователей"
        
    except Exception as e:
        logger.error(f"Ошибка при получении топа пользователей: {e}")
        text += "❌ Ошибка при загрузке данных"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Обновить", callback_data="admin:top_users")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin:stats_menu")]
    ])

    await safe_edit_message(query, text, reply_markup=kb, parse_mode=ParseMode.HTML)


@admin_only
async def retention_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика удержания пользователей (Retention)."""
    query = update.callback_query
    try:
        await query.answer("Загрузка retention...")
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    from core import db
    from datetime import datetime, timedelta

    text = "📊 <b>Retention - Удержание пользователей</b>\n\n"

    try:
        conn = await db.get_db()

        # Retention по дням (1, 7, 14, 30 дней)
        periods = [1, 7, 14, 30]
        today = datetime.now()

        for days in periods:
            # Пользователи, зарегистрированные N дней назад
            target_date = (today - timedelta(days=days)).date()

            cursor = await conn.execute("""
                SELECT COUNT(*) FROM users
                WHERE DATE(created_at) = ?
            """, (target_date,))
            registered = (await cursor.fetchone())[0]

            if registered == 0:
                continue

            # Сколько из них были активны сегодня
            cursor = await conn.execute("""
                SELECT COUNT(*) FROM users
                WHERE DATE(created_at) = ?
                AND last_activity_date = date('now')
            """, (target_date,))
            active_today = (await cursor.fetchone())[0]

            retention_rate = (active_today * 100 / registered) if registered > 0 else 0

            text += f"<b>День {days}:</b>\n"
            text += f"• Зарегистрировано: {registered}\n"
            text += f"• Активны сегодня: {active_today}\n"
            text += f"• Retention: {retention_rate:.1f}%\n\n"

        # Общий retention за последнюю неделю
        cursor = await conn.execute("""
            SELECT
                COUNT(DISTINCT CASE WHEN created_at > datetime('now', '-7 days') THEN user_id END) as new_users,
                COUNT(DISTINCT CASE
                    WHEN created_at > datetime('now', '-7 days')
                    AND last_activity_date > date('now', '-3 days')
                    THEN user_id END) as active_new
            FROM users
        """)

        stats = await cursor.fetchone()
        if stats and stats[0] > 0:
            week_retention = (stats[1] * 100 / stats[0])
            text += f"<b>📈 Retention за неделю:</b>\n"
            text += f"• Новых пользователей: {stats[0]}\n"
            text += f"• Остались активны: {stats[1]}\n"
            text += f"• Retention: {week_retention:.1f}%\n"

    except Exception as e:
        logger.error(f"Error getting retention stats: {e}")
        text += "❌ Ошибка при загрузке данных"

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Обновить", callback_data="admin:retention_stats"),
            InlineKeyboardButton("📊 Конверсия", callback_data="admin:conversion_stats")
        ],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin:stats_menu")]
    ])

    await safe_edit_message(query, text, reply_markup=kb, parse_mode=ParseMode.HTML)


@admin_only
async def conversion_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Воронка конверсии (регистрация → подписка)."""
    query = update.callback_query
    try:
        await query.answer("Загрузка воронки конверсии...")
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    from core import db
    from payment.config import SUBSCRIPTION_MODE

    text = "🎯 <b>Воронка конверсии</b>\n\n"

    try:
        conn = await db.get_db()

        # Всего пользователей
        cursor = await conn.execute("SELECT COUNT(*) FROM users")
        total_users = (await cursor.fetchone())[0]

        # Пользователи с хотя бы одной попыткой
        cursor = await conn.execute("SELECT COUNT(DISTINCT user_id) FROM attempts")
        users_with_attempts = (await cursor.fetchone())[0]

        # Пользователи с подпиской
        if SUBSCRIPTION_MODE == 'modular':
            cursor = await conn.execute("""
                SELECT COUNT(DISTINCT user_id)
                FROM module_subscriptions
                WHERE is_active = 1 AND expires_at > datetime('now')
            """)
        else:
            cursor = await conn.execute("""
                SELECT COUNT(DISTINCT user_id)
                FROM user_subscriptions
                WHERE status = 'active' AND expires_at > datetime('now')
            """)
        subscribers = (await cursor.fetchone())[0]

        # Пользователи с платежами
        cursor = await conn.execute("""
            SELECT COUNT(DISTINCT user_id) FROM payments
            WHERE status = 'completed'
        """)
        paid_users = (await cursor.fetchone())[0]

        # Рассчитываем конверсии
        activation_rate = (users_with_attempts * 100 / total_users) if total_users > 0 else 0
        subscription_rate = (subscribers * 100 / total_users) if total_users > 0 else 0
        payment_rate = (paid_users * 100 / total_users) if total_users > 0 else 0

        text += "📊 <b>Этапы воронки:</b>\n\n"
        text += f"1️⃣ Регистрация: {total_users} (100%)\n"
        text += f"    ↓\n"
        text += f"2️⃣ Активация (сделали попытку): {users_with_attempts} ({activation_rate:.1f}%)\n"
        text += f"    ↓\n"
        text += f"3️⃣ Подписка: {subscribers} ({subscription_rate:.1f}%)\n"
        text += f"    ↓\n"
        text += f"4️⃣ Оплата: {paid_users} ({payment_rate:.1f}%)\n\n"

        # Конверсия активных → подписчики
        if users_with_attempts > 0:
            active_to_sub = (subscribers * 100 / users_with_attempts)
            text += f"<b>💡 Ключевые метрики:</b>\n"
            text += f"• Активация: {activation_rate:.1f}%\n"
            text += f"• Конверсия в подписку: {subscription_rate:.1f}%\n"
            text += f"• Конверсия активных в подписку: {active_to_sub:.1f}%\n"
            text += f"• Платящие пользователи: {payment_rate:.1f}%\n"

    except Exception as e:
        logger.error(f"Error getting conversion stats: {e}")
        text += "❌ Ошибка при загрузке данных"

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Обновить", callback_data="admin:conversion_stats"),
            InlineKeyboardButton("📈 Retention", callback_data="admin:retention_stats")
        ],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin:stats_menu")]
    ])

    await safe_edit_message(query, text, reply_markup=kb, parse_mode=ParseMode.HTML)


@admin_only
async def financial_analytics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Финансовая аналитика: LTV, MRR, Churn, ARPU."""
    query = update.callback_query
    try:
        await query.answer("Загрузка финансовой аналитики...")
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    from core import db
    from datetime import datetime, timedelta

    text = "💰 <b>Финансовая аналитика</b>\n\n"

    try:
        conn = await db.get_db()

        # 1. LTV (Lifetime Value) - средний доход с платящего пользователя
        cursor = await conn.execute("""
            SELECT
                COUNT(DISTINCT user_id) as paying_users,
                SUM(amount_kopecks) as total_revenue
            FROM payments
            WHERE status IN ('completed', 'confirmed')
        """)
        ltv_data = await cursor.fetchone()

        if ltv_data and ltv_data[0] > 0:
            paying_users = ltv_data[0]
            total_revenue_rub = (ltv_data[1] or 0) / 100
            ltv = total_revenue_rub / paying_users

            text += f"<b>💎 LTV (Lifetime Value):</b>\n"
            text += f"• Средний доход с пользователя: {ltv:.0f}₽\n"
            text += f"• Платящих пользователей: {paying_users}\n"
            text += f"• Общий доход: {total_revenue_rub:.0f}₽\n\n"

        # 2. MRR (Monthly Recurring Revenue)
        # Подписки, которые активны сейчас
        cursor = await conn.execute("""
            SELECT
                COUNT(DISTINCT user_id) as active_subs,
                AVG(amount_kopecks) as avg_payment
            FROM payments
            WHERE status IN ('completed', 'confirmed')
            AND created_at > datetime('now', '-30 days')
        """)
        mrr_data = await cursor.fetchone()

        if mrr_data and mrr_data[0] > 0:
            active_subs = mrr_data[0]
            avg_payment = (mrr_data[1] or 0) / 100
            mrr = active_subs * avg_payment

            text += f"<b>📊 MRR (Monthly Recurring Revenue):</b>\n"
            text += f"• MRR: {mrr:.0f}₽/месяц\n"
            text += f"• Активных подписок: {active_subs}\n"
            text += f"• Средний чек: {avg_payment:.0f}₽\n\n"

        # 3. Churn Rate - процент отказов
        # Пользователи, чья подписка истекла за последние 30 дней
        cursor = await conn.execute("""
            SELECT
                COUNT(DISTINCT CASE
                    WHEN expires_at > datetime('now', '-30 days')
                    AND expires_at < datetime('now')
                    THEN user_id
                END) as churned,
                COUNT(DISTINCT CASE
                    WHEN expires_at > datetime('now', '-30 days')
                    THEN user_id
                END) as total_had_subscription
            FROM user_subscriptions
        """)
        churn_data = await cursor.fetchone()

        if churn_data and churn_data[1] > 0:
            churned = churn_data[0] or 0
            total_subs = churn_data[1]
            churn_rate = (churned * 100 / total_subs) if total_subs > 0 else 0

            text += f"<b>📉 Churn Rate (отток):</b>\n"
            text += f"• Churn Rate: {churn_rate:.1f}%\n"
            text += f"• Отказались: {churned} из {total_subs}\n"
            text += f"• Retention: {100 - churn_rate:.1f}%\n\n"

        # 4. ARPU (Average Revenue Per User)
        cursor = await conn.execute("SELECT COUNT(*) FROM users")
        total_users = (await cursor.fetchone())[0]

        if total_users > 0 and ltv_data:
            arpu = total_revenue_rub / total_users

            text += f"<b>💵 ARPU (Average Revenue Per User):</b>\n"
            text += f"• ARPU: {arpu:.0f}₽\n"
            text += f"• На {total_users} пользователей\n\n"

        # 5. Прогноз дохода
        cursor = await conn.execute("""
            SELECT SUM(amount_kopecks) / 100.0
            FROM payments
            WHERE status IN ('completed', 'confirmed')
            AND created_at > datetime('now', '-30 days')
        """)
        last_month_revenue = (await cursor.fetchone())[0] or 0

        if mrr_data and mrr_data[0] > 0:
            projected_revenue = last_month_revenue * 1.0  # Консервативный прогноз
            text += f"<b>📈 Прогноз на следующий месяц:</b>\n"
            text += f"• Прогноз: ~{projected_revenue:.0f}₽\n"
            text += f"• На основе: {last_month_revenue:.0f}₽ за последний месяц\n"

    except Exception as e:
        logger.error(f"Error getting financial analytics: {e}")
        text += "❌ Ошибка при загрузке данных"

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Обновить", callback_data="admin:financial_analytics"),
            InlineKeyboardButton("📊 Подробнее", callback_data="admin:payment_stats")
        ],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin:stats_menu")]
    ])

    await safe_edit_message(query, text, reply_markup=kb, parse_mode=ParseMode.HTML)


@admin_only
async def system_monitor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Мониторинг системы."""
    query = update.callback_query
    try:
        await query.answer("Загрузка мониторинга...")
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    import sys
    from datetime import datetime

    text = "🖥️ <b>Системный мониторинг</b>\n\n"

    # Попытка импортировать psutil
    try:
        import psutil
        PSUTIL_AVAILABLE = True
    except ImportError:
        PSUTIL_AVAILABLE = False
        logger.warning("psutil module not available - system monitoring will be limited")

    if PSUTIL_AVAILABLE:
        try:
            # CPU
            cpu_percent = psutil.cpu_percent(interval=1)
            cpu_count = psutil.cpu_count()
            text += f"<b>💻 CPU:</b>\n"
            text += f"• Использование: {cpu_percent}%\n"
            text += f"• Ядер: {cpu_count}\n\n"

            # Memory
            memory = psutil.virtual_memory()
            text += f"<b>🧠 Память:</b>\n"
            text += f"• Использовано: {memory.percent}%\n"
            text += f"• Всего: {memory.total / (1024**3):.1f} GB\n"
            text += f"• Доступно: {memory.available / (1024**3):.1f} GB\n\n"

            # Disk
            disk = psutil.disk_usage('/')
            text += f"<b>💾 Диск:</b>\n"
            text += f"• Использовано: {disk.percent}%\n"
            text += f"• Всего: {disk.total / (1024**3):.1f} GB\n"
            text += f"• Свободно: {disk.free / (1024**3):.1f} GB\n\n"

            # Bot info
            process = psutil.Process()
            bot_memory = process.memory_info().rss / (1024**2)
            uptime = datetime.now() - datetime.fromtimestamp(process.create_time())

            text += f"<b>🤖 Бот:</b>\n"
            text += f"• Память: {bot_memory:.1f} MB\n"
            text += f"• Uptime: {uptime.days}д {uptime.seconds//3600}ч\n"
            text += f"• Python: {sys.version.split()[0]}\n"

        except Exception as e:
            logger.error(f"Error getting system monitor: {e}")
            text += f"❌ Ошибка мониторинга: {e}"
    else:
        # psutil не установлен - показываем базовую информацию
        text += "⚠️ <b>Модуль psutil не установлен</b>\n\n"
        text += "Для полного мониторинга системы установите:\n"
        text += "<code>pip install psutil</code>\n\n"
        text += f"<b>🤖 Базовая информация:</b>\n"
        text += f"• Python: {sys.version.split()[0]}\n"
        text += f"• Платформа: {sys.platform}\n"

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Обновить", callback_data="admin:system_monitor"),
            InlineKeyboardButton("📋 Логи", callback_data="admin:view_logs")
        ],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin:main")]
    ])

    await safe_edit_message(query, text, reply_markup=kb, parse_mode=ParseMode.HTML)


@admin_only
async def content_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Анализ контента - статистика по вопросам."""
    query = update.callback_query
    try:
        await query.answer("Анализирую контент...")
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    from core import db

    text = "📚 <b>Анализ контента</b>\n\n"

    try:
        conn = await db.get_db()

        # Общая статистика по попыткам
        cursor = await conn.execute("""
            SELECT
                COUNT(*) as total_attempts,
                AVG(score) as avg_score,
                COUNT(DISTINCT user_id) as users_attempted
            FROM attempts
        """)
        general = await cursor.fetchone()

        if general and general[0] > 0:
            total_attempts, avg_score, users = general
            text += f"<b>📊 Общая статистика:</b>\n"
            text += f"• Всего попыток: {total_attempts}\n"
            text += f"• Средний балл: {avg_score:.1f}\n"
            text += f"• Пользователей: {users}\n\n"

        # Статистика по модулям
        cursor = await conn.execute("""
            SELECT
                module_type,
                COUNT(*) as attempts,
                AVG(score) as avg_score,
                MIN(score) as min_score,
                MAX(score) as max_score
            FROM attempts
            GROUP BY module_type
            ORDER BY attempts DESC
        """)
        modules = await cursor.fetchall()

        if modules:
            text += "<b>📚 По модулям:</b>\n"
            module_names = {
                'task24': '📝 Задание 24',
                'test_part': '📚 Тестовая часть',
                'task19': '🎯 Задание 19',
                'task20': '💭 Задание 20',
                'task25': '📋 Задание 25'
            }

            for module, attempts, avg, min_s, max_s in modules:
                name = module_names.get(module, module)
                text += f"\n{name}:\n"
                text += f"  • Попыток: {attempts}\n"
                text += f"  • Ср. балл: {avg:.1f}\n"
                text += f"  • Мин/Макс: {min_s:.0f}/{max_s:.0f}\n"

        text += "\n\n💡 <i>Для детального анализа используйте кнопки ниже</i>"

    except Exception as e:
        logger.error(f"Error in content analysis: {e}")
        text += "❌ Ошибка при анализе"

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔴 Сложные", callback_data="admin:content_difficult"),
            InlineKeyboardButton("🟢 Легкие", callback_data="admin:content_easy")
        ],
        [
            InlineKeyboardButton("📊 Подробнее", callback_data="admin:content_detailed")
        ],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin:main")]
    ])

    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@admin_only
async def content_difficult(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Анализ сложных вопросов."""
    query = update.callback_query
    try:
        await query.answer("Ищу сложные вопросы...")
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    from core import db

    text = "🔴 <b>Сложные вопросы</b>\n\n"
    text += "Вопросы с самым низким средним баллом:\n\n"

    try:
        conn = await db.get_db()

        # Ищем вопросы с низким средним баллом
        # Примечание: это работает если question_id записывается в таблицу attempts
        cursor = await conn.execute("""
            SELECT
                module_type,
                COUNT(*) as attempts,
                AVG(score) as avg_score
            FROM attempts
            GROUP BY module_type
            HAVING COUNT(*) >= 5
            ORDER BY avg_score ASC
            LIMIT 10
        """)

        difficult = await cursor.fetchall()

        if difficult:
            module_names = {
                'task24': '📝 Задание 24',
                'test_part': '📚 Тестовая часть',
                'task19': '🎯 Задание 19',
                'task20': '💭 Задание 20',
                'task25': '📋 Задание 25'
            }

            for module, attempts, avg_score in difficult:
                name = module_names.get(module, module)
                difficulty_icon = "🔴" if avg_score < 50 else "🟡"
                text += f"{difficulty_icon} {name}\n"
                text += f"   Попыток: {attempts} | Балл: {avg_score:.1f}\n\n"

            text += "\n💡 Рекомендация: Рассмотрите возможность упрощения этих заданий"
        else:
            text += "Данных недостаточно для анализа"

    except Exception as e:
        logger.error(f"Error analyzing difficult content: {e}")
        text += "❌ Ошибка анализа"

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🟢 Легкие", callback_data="admin:content_easy"),
            InlineKeyboardButton("🔄 Обновить", callback_data="admin:content_difficult")
        ],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin:content_analysis")]
    ])

    await safe_edit_message(query, text, reply_markup=kb, parse_mode=ParseMode.HTML)


@admin_only
async def content_easy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Анализ легких вопросов."""
    query = update.callback_query
    try:
        await query.answer("Ищу легкие вопросы...")
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    from core import db

    text = "🟢 <b>Легкие вопросы</b>\n\n"
    text += "Вопросы с самым высоким средним баллом:\n\n"

    try:
        conn = await db.get_db()

        cursor = await conn.execute("""
            SELECT
                module_type,
                COUNT(*) as attempts,
                AVG(score) as avg_score
            FROM attempts
            GROUP BY module_type
            HAVING COUNT(*) >= 5
            ORDER BY avg_score DESC
            LIMIT 10
        """)

        easy = await cursor.fetchall()

        if easy:
            module_names = {
                'task24': '📝 Задание 24',
                'test_part': '📚 Тестовая часть',
                'task19': '🎯 Задание 19',
                'task20': '💭 Задание 20',
                'task25': '📋 Задание 25'
            }

            for module, attempts, avg_score in easy:
                name = module_names.get(module, module)
                difficulty_icon = "🟢" if avg_score > 80 else "🟡"
                text += f"{difficulty_icon} {name}\n"
                text += f"   Попыток: {attempts} | Балл: {avg_score:.1f}\n\n"

            text += "\n💡 Эти задания хорошо усваиваются пользователями"
        else:
            text += "Данных недостаточно для анализа"

    except Exception as e:
        logger.error(f"Error analyzing easy content: {e}")
        text += "❌ Ошибка анализа"

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔴 Сложные", callback_data="admin:content_difficult"),
            InlineKeyboardButton("🔄 Обновить", callback_data="admin:content_easy")
        ],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin:content_analysis")]
    ])

    await safe_edit_message(query, text, reply_markup=kb, parse_mode=ParseMode.HTML)


@admin_only
async def view_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просмотр последних логов."""
    query = update.callback_query
    try:
        await query.answer("Загрузка логов...")
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    text = "📋 <b>Последние логи</b>\n\n"

    try:
        import os

        log_file = "bot.log"
        if os.path.exists(log_file):
            with open(log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                last_lines = lines[-20:]  # Последние 20 строк

                for line in last_lines:
                    # Обрезаем длинные строки
                    if len(line) > 100:
                        line = line[:97] + "...\n"
                    text += f"<code>{line.strip()}</code>\n"
        else:
            text += "Файл логов не найден"

    except Exception as e:
        logger.error(f"Error viewing logs: {e}")
        text += f"❌ Ошибка чтения логов: {e}"

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Обновить", callback_data="admin:view_logs"),
            InlineKeyboardButton("🗑️ Очистить", callback_data="admin:clear_logs")
        ],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin:system_monitor")]
    ])

    await safe_edit_message(query, text, reply_markup=kb, parse_mode=ParseMode.HTML)


@admin_only
async def users_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Общая статистика по пользователям."""
    query = update.callback_query
    try:
        await query.answer("Загрузка статистики пользователей...")
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    from core import db
    from payment.config import SUBSCRIPTION_MODE

    text = "👥 <b>Статистика пользователей</b>\n\n"

    try:
        conn = await db.get_db()

        # Общая статистика пользователей
        cursor = await conn.execute("""
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN last_activity_date > datetime('now', '-1 day') THEN 1 END) as active_1d,
                COUNT(CASE WHEN last_activity_date > datetime('now', '-7 days') THEN 1 END) as active_7d,
                COUNT(CASE WHEN last_activity_date > datetime('now', '-30 days') THEN 1 END) as active_30d
            FROM users
        """)
        stats = await cursor.fetchone()

        if stats:
            total, active_1d, active_7d, active_30d = stats

            text += "<b>📊 Активность:</b>\n"
            text += f"• Всего пользователей: {total}\n"
            text += f"• Активны за день: {active_1d} ({active_1d*100//max(total,1)}%)\n"
            text += f"• Активны за неделю: {active_7d} ({active_7d*100//max(total,1)}%)\n"
            text += f"• Активны за месяц: {active_30d} ({active_30d*100//max(total,1)}%)\n\n"

        # Статистика подписок
        if SUBSCRIPTION_MODE == 'modular':
            cursor = await conn.execute("""
                SELECT COUNT(DISTINCT user_id)
                FROM module_subscriptions
                WHERE is_active = 1 AND expires_at > datetime('now')
            """)
        else:
            cursor = await conn.execute("""
                SELECT COUNT(DISTINCT user_id)
                FROM user_subscriptions
                WHERE status = 'active' AND expires_at > datetime('now')
            """)

        premium_count = (await cursor.fetchone())[0]

        text += "<b>💎 Подписки:</b>\n"
        text += f"• С активной подпиской: {premium_count}\n"
        text += f"• Без подписки: {total - premium_count}\n"
        text += f"• Конверсия: {premium_count*100//max(total,1)}%\n\n"

        # Популярные модули
        cursor = await conn.execute("""
            SELECT
                module_type,
                COUNT(DISTINCT user_id) as users,
                COUNT(*) as attempts
            FROM attempts
            WHERE created_at > datetime('now', '-30 days')
            GROUP BY module_type
            ORDER BY users DESC
            LIMIT 5
        """)

        modules_data = await cursor.fetchall()

        if modules_data:
            text += "<b>📚 Популярные модули (30 дней):</b>\n"
            module_names = {
                'task24': '📝 Задание 24',
                'test_part': '📚 Тестовая часть',
                'task19': '🎯 Задание 19',
                'task20': '💭 Задание 20',
                'task25': '📋 Задание 25'
            }

            for module_type, users, attempts in modules_data:
                name = module_names.get(module_type, module_type)
                text += f"• {name}\n"
                text += f"  👥 {users} польз. | 📝 {attempts} попыток\n"

    except Exception as e:
        logger.error(f"Error getting users stats: {e}")
        text += "❌ Ошибка при загрузке данных"

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Обновить", callback_data="admin:users_stats"),
            InlineKeyboardButton("📋 Список", callback_data="admin:users_list")
        ],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin:users")]
    ])

    await safe_edit_message(query, text, reply_markup=kb, parse_mode=ParseMode.HTML)


@admin_only
async def user_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Детальная статистика конкретного пользователя."""
    query = update.callback_query
    try:
        await query.answer("Загрузка статистики пользователя...")
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    # Извлекаем user_id из callback_data
    callback_data = query.data
    user_id = int(callback_data.split(':')[-1])

    from core import db

    text = f"📊 <b>Статистика пользователя {user_id}</b>\n\n"

    try:
        conn = await db.get_db()

        # Основная информация о пользователе
        cursor = await conn.execute("""
            SELECT first_name, username, last_activity_date, created_at
            FROM users
            WHERE user_id = ?
        """, (user_id,))

        user_info = await cursor.fetchone()

        if not user_info:
            text = f"❌ Пользователь {user_id} не найден"
        else:
            first_name, username, last_activity, created_at = user_info

            text += f"<b>👤 Информация:</b>\n"
            text += f"• Имя: {first_name or 'Не указано'}\n"
            if username:
                text += f"• Username: @{username}\n"
            text += f"• Последняя активность: {last_activity or 'Никогда'}\n"
            text += f"• Регистрация: {created_at or 'Неизвестно'}\n\n"

            # Статистика попыток
            cursor = await conn.execute("""
                SELECT
                    COUNT(*) as total_attempts,
                    AVG(score) as avg_score,
                    MAX(score) as max_score,
                    COUNT(DISTINCT module_type) as modules_used
                FROM attempts
                WHERE user_id = ?
            """, (user_id,))

            attempts_stats = await cursor.fetchone()

            if attempts_stats and attempts_stats[0] > 0:
                total_attempts, avg_score, max_score, modules_used = attempts_stats

                text += f"<b>📝 Активность:</b>\n"
                text += f"• Всего попыток: {total_attempts}\n"
                text += f"• Средний балл: {avg_score:.1f}\n"
                text += f"• Лучший балл: {max_score:.0f}\n"
                text += f"• Использовано модулей: {modules_used}/5\n\n"

                # Статистика по модулям
                cursor = await conn.execute("""
                    SELECT
                        module_type,
                        COUNT(*) as attempts,
                        AVG(score) as avg_score,
                        MAX(score) as max_score
                    FROM attempts
                    WHERE user_id = ?
                    GROUP BY module_type
                    ORDER BY attempts DESC
                """, (user_id,))

                modules_data = await cursor.fetchall()

                if modules_data:
                    text += "<b>📚 По модулям:</b>\n"
                    module_names = {
                        'task24': '📝 Задание 24',
                        'test_part': '📚 Тестовая часть',
                        'task19': '🎯 Задание 19',
                        'task20': '💭 Задание 20',
                        'task25': '📋 Задание 25'
                    }

                    for module_type, attempts, avg, max_s in modules_data:
                        name = module_names.get(module_type, module_type)
                        text += f"\n{name}:\n"
                        text += f"  • Попыток: {attempts}\n"
                        text += f"  • Средний балл: {avg:.1f}\n"
                        text += f"  • Лучший балл: {max_s:.0f}\n"
            else:
                text += "<b>📝 Активность:</b>\n"
                text += "• Пользователь еще не проходил тесты\n"

    except Exception as e:
        logger.error(f"Error getting user stats for {user_id}: {e}")
        text += "\n❌ Ошибка при загрузке данных"

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Обновить", callback_data=f"admin:user_stats:{user_id}"),
            InlineKeyboardButton("👤 Инфо", callback_data=f"admin:user_details:{user_id}")
        ],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin:users")]
    ])

    await safe_edit_message(query, text, reply_markup=kb, parse_mode=ParseMode.HTML)


@admin_only
async def security_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отчет о безопасности."""
    query = update.callback_query
    await query.answer()
    
    report = admin_manager.get_security_report()
    
    text = (
        "🔒 <b>Отчет о безопасности</b>\n\n"
        f"👮 Администраторов: {report['total_admins']}\n\n"
    )
    
    if report['suspicious_users']:
        text += "⚠️ <b>Подозрительная активность:</b>\n"
        for user_id in report['suspicious_users']:
            attempts = report['failed_attempts'].get(user_id, 0)
            text += f"  • User {user_id}: {attempts} попыток за час\n"
    else:
        text += "✅ Подозрительной активности не обнаружено\n"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Обновить", callback_data="admin:security")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin:main")]
    ])

    await safe_edit_message(query, text, reply_markup=kb, parse_mode=ParseMode.HTML)


@admin_only
async def close_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Закрытие админской панели."""
    query = update.callback_query
    await query.answer("Панель закрыта")
    try:
        await query.delete_message()
    except BadRequest as e:
        # Если сообщение не может быть удалено (слишком старое или уже удалено)
        # просто игнорируем ошибку - панель уже закрыта с точки зрения пользователя
        logger.debug(f"Не удалось удалить сообщение админ-панели: {e}")


@admin_only
async def handle_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню экспорта данных."""
    query = update.callback_query
    await query.answer()
    
    text = (
        "📤 <b>Экспорт и бэкап данных</b>\n\n"
        "Выберите формат экспорта или создайте полный бэкап базы данных:"
    )
    
    kb = AdminKeyboards.export_menu()
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

@admin_only
async def export_stats_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспорт статистики в CSV."""
    query = update.callback_query
    try:
        await query.answer("Генерирую CSV файл...")
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    from core import db
    
    try:
        conn = await db.get_db()
        
        # Получаем данные
        cursor = await conn.execute("""
            SELECT 
                a.user_id,
                u.username,
                u.first_name,
                a.module_type,
                a.score,
                a.created_at
            FROM attempts a
            JOIN users u ON a.user_id = u.user_id
            ORDER BY a.created_at DESC
        """)
        
        data = await cursor.fetchall()
        
        # Создаем CSV в памяти
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Заголовки
        writer.writerow(['User ID', 'Username', 'Name', 'Module', 'Score', 'Date'])
        
        # Данные
        for row in data:
            writer.writerow(row)
        
        # Отправляем файл
        csv_data = output.getvalue().encode('utf-8-sig')  # BOM для корректного отображения в Excel
        
        await context.bot.send_document(
            chat_id=update.effective_user.id,
            document=io.BytesIO(csv_data),
            filename=f"statistics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            caption="📊 Экспорт статистики в CSV"
        )
        
        await query.edit_message_text(
            "✅ CSV файл успешно сгенерирован и отправлен!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data="admin:export")]
            ])
        )
        
    except Exception as e:
        logger.error(f"Error exporting CSV: {e}")
        await query.edit_message_text(
            f"❌ Ошибка при экспорте: {str(e)}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data="admin:export")]
            ])
        )

@admin_only
async def export_stats_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспорт статистики в Excel с несколькими листами."""
    query = update.callback_query
    try:
        await query.answer("Генерирую Excel файл...")
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    from core import db
    
    try:
        conn = await db.get_db()
        
        # Создаем Excel файл в памяти
        output = io.BytesIO()
        
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            # Лист 1: Общая статистика
            cursor = await conn.execute("""
                SELECT 
                    u.user_id,
                    u.username,
                    u.first_name,
                    COUNT(a.attempt_id) as total_attempts,
                    AVG(a.score) as avg_score,
                    MAX(a.score) as max_score,
                    COUNT(DISTINCT a.module_type) as modules_used
                FROM users u
                LEFT JOIN attempts a ON u.user_id = a.user_id
                GROUP BY u.user_id
            """)
            
            columns = ['User ID', 'Username', 'Name', 'Total Attempts', 'Avg Score', 'Max Score', 'Modules Used']
            df_stats = pd.DataFrame(await cursor.fetchall(), columns=columns)
            df_stats.to_excel(writer, sheet_name='Общая статистика', index=False)
            
            # Лист 2: Статистика по модулям
            cursor = await conn.execute("""
                SELECT 
                    module_type,
                    COUNT(DISTINCT user_id) as unique_users,
                    COUNT(*) as total_attempts,
                    AVG(score) as avg_score,
                    MAX(score) as max_score,
                    MIN(score) as min_score
                FROM attempts
                GROUP BY module_type
            """)
            
            columns = ['Module', 'Unique Users', 'Total Attempts', 'Avg Score', 'Max Score', 'Min Score']
            df_modules = pd.DataFrame(await cursor.fetchall(), columns=columns)
            df_modules.to_excel(writer, sheet_name='По модулям', index=False)
            
            # Лист 3: Подписки
            cursor = await conn.execute("""
                SELECT 
                    u.user_id,
                    u.username,
                    u.first_name,
                    s.plan_id,
                    s.started_at,
                    s.expires_at,
                    s.amount
                FROM subscriptions s
                JOIN users u ON s.user_id = u.user_id
                ORDER BY s.started_at DESC
            """)
            
            columns = ['User ID', 'Username', 'Name', 'Plan', 'Started', 'Expires', 'Amount']
            df_subs = pd.DataFrame(await cursor.fetchall(), columns=columns)
            df_subs.to_excel(writer, sheet_name='Подписки', index=False)
        
        # Отправляем файл
        output.seek(0)
        
        await context.bot.send_document(
            chat_id=update.effective_user.id,
            document=output,
            filename=f"statistics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            caption="📊 Полный экспорт статистики в Excel"
        )
        
        await query.edit_message_text(
            "✅ Excel файл успешно сгенерирован и отправлен!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data="admin:export")]
            ])
        )
        
    except Exception as e:
        logger.error(f"Error exporting Excel: {e}")
        await query.edit_message_text(
            f"❌ Ошибка при экспорте: {str(e)}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data="admin:export")]
            ])
        )

@admin_only
async def backup_full(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создание полного бэкапа БД."""
    query = update.callback_query
    try:
        await query.answer("Создаю бэкап...")
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    try:
        # Путь к БД
        db_path = 'bot_database.db'
        
        # Читаем файл БД
        with open(db_path, 'rb') as f:
            db_data = f.read()
        
        # Отправляем файл
        await context.bot.send_document(
            chat_id=update.effective_user.id,
            document=io.BytesIO(db_data),
            filename=f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db",
            caption="💾 Полный бэкап базы данных\n\n"
                   "⚠️ Храните этот файл в безопасном месте!"
        )
        
        await query.edit_message_text(
            "✅ Бэкап успешно создан!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data="admin:export")]
            ])
        )
        
    except Exception as e:
        logger.error(f"Error creating backup: {e}")
        await query.edit_message_text(
            f"❌ Ошибка при создании бэкапа: {str(e)}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data="admin:export")]
            ])
        )

@admin_only
async def generate_charts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Генерация графиков статистики."""
    query = update.callback_query
    try:
        await query.answer("Генерирую графики...")
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    from core import db
    
    try:
        conn = await db.get_db()
        
        # Создаем фигуру с несколькими графиками
        fig, axes = plt.subplots(2, 2, figsize=(12, 10))
        fig.suptitle('Статистика бота', fontsize=16)
        
        # График 1: Активность по дням
        cursor = await conn.execute("""
            SELECT DATE(created_at) as day, COUNT(*) as attempts
            FROM attempts
            WHERE created_at > datetime('now', '-30 days')
            GROUP BY DATE(created_at)
            ORDER BY day
        """)
        data = await cursor.fetchall()
        
        if data:
            days = [datetime.strptime(d[0], '%Y-%m-%d') for d in data]
            attempts = [d[1] for d in data]
            
            axes[0, 0].plot(days, attempts, marker='o')
            axes[0, 0].set_title('Активность за последние 30 дней')
            axes[0, 0].set_xlabel('Дата')
            axes[0, 0].set_ylabel('Количество попыток')
            axes[0, 0].grid(True)
            axes[0, 0].tick_params(axis='x', rotation=45)
        
        # График 2: Распределение по модулям
        cursor = await conn.execute("""
            SELECT module_type, COUNT(*) as count
            FROM attempts
            GROUP BY module_type
        """)
        data = await cursor.fetchall()
        
        if data:
            modules = [d[0] for d in data]
            counts = [d[1] for d in data]
            
            axes[0, 1].pie(counts, labels=modules, autopct='%1.1f%%')
            axes[0, 1].set_title('Распределение по модулям')
        
        # График 3: Средние баллы по модулям
        cursor = await conn.execute("""
            SELECT module_type, AVG(score) as avg_score
            FROM attempts
            GROUP BY module_type
        """)
        data = await cursor.fetchall()
        
        if data:
            modules = [d[0] for d in data]
            scores = [d[1] for d in data]
            
            axes[1, 0].bar(modules, scores)
            axes[1, 0].set_title('Средние баллы по модулям')
            axes[1, 0].set_xlabel('Модуль')
            axes[1, 0].set_ylabel('Средний балл')
            axes[1, 0].grid(True, axis='y')
        
        # График 4: Рост пользователей
        cursor = await conn.execute("""
            SELECT DATE(created_at) as day, COUNT(*) as new_users
            FROM users
            WHERE created_at > datetime('now', '-30 days')
            GROUP BY DATE(created_at)
            ORDER BY day
        """)
        data = await cursor.fetchall()
        
        if data:
            days = [datetime.strptime(d[0], '%Y-%m-%d') for d in data]
            new_users = [d[1] for d in data]
            
            # Кумулятивная сумма
            cumulative = []
            total = 0
            for count in new_users:
                total += count
                cumulative.append(total)
            
            axes[1, 1].plot(days, cumulative, marker='o', color='green')
            axes[1, 1].set_title('Рост аудитории (30 дней)')
            axes[1, 1].set_xlabel('Дата')
            axes[1, 1].set_ylabel('Всего пользователей')
            axes[1, 1].grid(True)
            axes[1, 1].tick_params(axis='x', rotation=45)
        
        plt.tight_layout()
        
        # Сохраняем в буфер
        buf = BytesIO()
        plt.savefig(buf, format='png', dpi=100)
        buf.seek(0)
        plt.close()
        
        # Отправляем изображение
        await context.bot.send_photo(
            chat_id=update.effective_user.id,
            photo=buf,
            caption="📊 Графики статистики бота"
        )
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Обновить", callback_data="admin:generate_charts")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="admin:stats")]
        ])

        await safe_edit_message(
            query,
            "✅ Графики успешно сгенерированы!",
            reply_markup=kb
        )

    except Exception as e:
        logger.error(f"Error generating charts: {e}")
        await safe_edit_message(
            query,
            f"❌ Ошибка при генерации графиков: {str(e)}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data="admin:stats")]
            ])
        )

@admin_only
async def show_filters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ меню фильтров."""
    query = update.callback_query
    await query.answer()
    
    text = (
        "🔍 <b>Фильтры пользователей</b>\n\n"
        "Выберите критерий фильтрации:"
    )
    
    kb = AdminKeyboards.filter_menu()
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

@admin_only
async def filter_by_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Фильтр по дате регистрации."""
    query = update.callback_query
    await query.answer()
    
    text = (
        "📅 <b>Фильтр по дате регистрации</b>\n\n"
        "Выберите период:"
    )
    
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Сегодня", callback_data="admin:filter_apply:today"),
            InlineKeyboardButton("Вчера", callback_data="admin:filter_apply:yesterday")
        ],
        [
            InlineKeyboardButton("7 дней", callback_data="admin:filter_apply:week"),
            InlineKeyboardButton("30 дней", callback_data="admin:filter_apply:month")
        ],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin:show_filters")]
    ])
    
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

@admin_only
async def settings_modules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Управление модулями."""
    query = update.callback_query
    await query.answer()
    
    from core import plugin_loader
    
    text = "📦 <b>Управление модулями</b>\n\n"
    
    # Получаем список плагинов
    plugins = plugin_loader.PLUGINS
    
    if plugins:
        text += f"Всего модулей: {len(plugins)}\n\n"
        
        for plugin in plugins:
            text += f"• <b>{plugin.title}</b>\n"
            text += f"  Код: <code>{plugin.code}</code>\n"
            text += f"  Приоритет: {plugin.menu_priority}\n\n"
    else:
        text += "Модули не загружены"
    
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Перезагрузить", callback_data="admin:reload_modules"),
            InlineKeyboardButton("📊 Статистика", callback_data="admin:modules_usage")
        ],
        [
            InlineKeyboardButton("⚙️ Настройки доступа", callback_data="admin:modules_access"),
            InlineKeyboardButton("🔧 Отладка", callback_data="admin:modules_debug")
        ],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin:settings")]
    ])
    
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

@admin_only
async def modules_usage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика использования модулей."""
    query = update.callback_query
    await query.answer()
    
    from core import db
    
    try:
        conn = await db.get_db()
        
        # Статистика по модулям
        cursor = await conn.execute("""
            SELECT 
                module_type,
                COUNT(DISTINCT user_id) as unique_users,
                COUNT(*) as total_uses,
                AVG(score) as avg_score,
                MAX(created_at) as last_used
            FROM attempts
            WHERE created_at > datetime('now', '-30 days')
            GROUP BY module_type
            ORDER BY total_uses DESC
        """)
        
        modules_stats = await cursor.fetchall()
        
        text = "📊 <b>Использование модулей (30 дней)</b>\n\n"
        
        if modules_stats:
            for module, users, uses, avg_score, last_used in modules_stats:
                last_date = datetime.fromisoformat(last_used).strftime("%d.%m.%Y")
                
                module_names = {
                    'task24': '📋 Задание 24',
                    'test_part': '📚 Тестовая часть',
                    'task19': '🎯 Задание 19',
                    'task20': '💭 Задание 20',
                    'task25': '📝 Задание 25'
                }
                
                name = module_names.get(module, module)
                
                text += f"<b>{name}</b>\n"
                text += f"👥 Пользователей: {users}\n"
                text += f"📝 Использований: {uses}\n"
                text += f"⭐ Средний балл: {avg_score:.2f}\n"
                text += f"📅 Последнее: {last_date}\n\n"
        else:
            text += "Нет данных об использовании"
        
    except Exception as e:
        logger.error(f"Error getting modules usage: {e}")
        text = "❌ Ошибка при загрузке статистики"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Обновить", callback_data="admin:modules_usage")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin:settings_modules")]
    ])

    await safe_edit_message(query, text, reply_markup=kb, parse_mode=ParseMode.HTML)

# ============================================
# 3. УПРАВЛЕНИЕ УВЕДОМЛЕНИЯМИ
# ============================================

@admin_only
async def settings_notifications(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Настройки уведомлений."""
    query = update.callback_query
    await query.answer()
    
    # Получаем текущие настройки (можно хранить в bot_data)
    notifications = context.bot_data.get('notifications_settings', {
        'new_user': True,
        'new_payment': True,
        'daily_report': True,
        'errors': True,
        'low_balance': True
    })
    
    text = "🔔 <b>Настройки уведомлений</b>\n\n"
    text += "Выберите, о чём вы хотите получать уведомления:\n\n"
    
    buttons = []
    
    for key, enabled in notifications.items():
        names = {
            'new_user': '👤 Новые пользователи',
            'new_payment': '💳 Новые платежи',
            'daily_report': '📊 Ежедневный отчёт',
            'errors': '❌ Ошибки',
            'low_balance': '💰 Низкий баланс'
        }
        
        status = "✅" if enabled else "❌"
        button_text = f"{status} {names.get(key, key)}"
        buttons.append([InlineKeyboardButton(button_text, callback_data=f"admin:toggle_notif:{key}")])
    
    buttons.extend([
        [
            InlineKeyboardButton("📨 Тестовое уведомление", callback_data="admin:test_notification")
        ],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin:settings")]
    ])
    
    kb = InlineKeyboardMarkup(buttons)
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

@admin_only
async def toggle_notification(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переключение уведомления."""
    query = update.callback_query
    notif_type = query.data.split(':')[-1]
    
    # Получаем текущие настройки
    notifications = context.bot_data.get('notifications_settings', {
        'new_user': True,
        'new_payment': True,
        'daily_report': True,
        'errors': True,
        'low_balance': True
    })
    
    # Переключаем
    notifications[notif_type] = not notifications.get(notif_type, False)
    context.bot_data['notifications_settings'] = notifications
    
    await query.answer(f"{'Включено' if notifications[notif_type] else 'Выключено'}")
    
    # Обновляем меню
    await settings_notifications(update, context)

@admin_only
async def test_notification(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправка тестового уведомления."""
    query = update.callback_query
    try:
        await query.answer("Отправляю тестовое уведомление...")
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    test_message = """
🔔 <b>Тестовое уведомление</b>

Это тестовое сообщение для проверки работы уведомлений.

Если вы видите это сообщение, значит уведомления работают корректно!

Время: {time}
    """.format(time=datetime.now().strftime("%d.%m.%Y %H:%M:%S"))
    
    try:
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text=test_message,
            parse_mode=ParseMode.HTML
        )
        
        await query.edit_message_text(
            "✅ Тестовое уведомление отправлено!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data="admin:settings_notifications")]
            ])
        )
    except Exception as e:
        logger.error(f"Error sending test notification: {e}")
        await query.edit_message_text(
            f"❌ Ошибка отправки: {str(e)}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data="admin:settings_notifications")]
            ])
        )

# ============================================
# 4. ДОПОЛНИТЕЛЬНЫЕ ФУНКЦИИ
# ============================================

@admin_only
async def export_payments_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспорт платежей в CSV."""
    query = update.callback_query
    try:
        await query.answer("Генерирую файл...")
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    from core import db
    import csv
    import io
    
    try:
        conn = await db.get_db()
        # ИСПРАВЛЕНО: amount -> amount_kopecks
        cursor = await conn.execute("""
            SELECT 
                p.user_id,
                u.username,
                u.first_name,
                p.plan_id,
                p.amount_kopecks / 100.0 as amount_rub,
                p.status,
                p.payment_id,
                p.created_at,
                p.confirmed_at
            FROM payments p
            LEFT JOIN users u ON p.user_id = u.user_id
            ORDER BY p.created_at DESC
        """)
        
        payments = await cursor.fetchall()
        
        # Создаём CSV
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Заголовки
        writer.writerow(['User ID', 'Username', 'Name', 'Plan', 'Amount (RUB)', 'Status', 'Payment ID', 'Created', 'Completed'])
        
        # Данные
        for row in payments:
            writer.writerow(row)
        
        # Отправляем файл
        csv_data = output.getvalue().encode('utf-8-sig')
        
        await context.bot.send_document(
            chat_id=update.effective_user.id,
            document=io.BytesIO(csv_data),
            filename=f"payments_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            caption="💳 Экспорт всех платежей"
        )
        
        await query.edit_message_text(
            "✅ Файл отправлен!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data="admin:payment_history")]
            ])
        )
        
    except Exception as e:
        logger.error(f"Error exporting payments: {e}")
        await query.edit_message_text(
            f"❌ Ошибка: {str(e)}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data="admin:payment_history")]
            ])
        )

@admin_only
async def apply_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Применение фильтра."""
    query = update.callback_query
    filter_type = query.data.split(':')[-1]

    try:
        await query.answer("Применяю фильтр...")
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    from core import db
    conn = await db.get_db()
    
    # Определяем SQL условие
    where_clause = ""
    filter_name = ""
    
    if filter_type == 'today':
        where_clause = "DATE(created_at) = DATE('now')"
        filter_name = "зарегистрированные сегодня"
    elif filter_type == 'yesterday':
        where_clause = "DATE(created_at) = DATE('now', '-1 day')"
        filter_name = "зарегистрированные вчера"
    elif filter_type == 'week':
        where_clause = "created_at > datetime('now', '-7 days')"
        filter_name = "зарегистрированные за последнюю неделю"
    elif filter_type == 'month':
        where_clause = "created_at > datetime('now', '-30 days')"
        filter_name = "зарегистрированные за последний месяц"
    
    # Получаем пользователей
    cursor = await conn.execute(f"""
        SELECT user_id, username, first_name, created_at
        FROM users
        WHERE {where_clause}
        ORDER BY created_at DESC
        LIMIT 20
    """)
    
    users = await cursor.fetchall()
    
    if users:
        text = f"👥 <b>Пользователи ({filter_name})</b>\n\n"
        text += f"Найдено: {len(users)}\n\n"
        
        for user_id, username, first_name, created_at in users[:10]:
            name = first_name or "Без имени"
            username_str = f"@{username}" if username else ""
            date_str = datetime.fromisoformat(created_at).strftime("%d.%m.%Y %H:%M")
            
            text += f"• {name} {username_str}\n"
            text += f"  ID: <code>{user_id}</code>\n"
            text += f"  Дата: {date_str}\n\n"
    else:
        text = f"❌ Пользователи не найдены ({filter_name})"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin:show_filters")]
    ])
    
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

# ============================================
# ПЛАНИРОВЩИК РАССЫЛОК
# ============================================

@admin_only
async def schedule_broadcast_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню планировщика рассылок."""
    query = update.callback_query
    await query.answer()
    
    scheduled = broadcast_scheduler.get_scheduled()
    
    text = "📅 <b>Планировщик рассылок</b>\n\n"
    
    if scheduled:
        text += "Запланированные рассылки:\n\n"
        for item in scheduled[:5]:
            run_time = item['run_time'].strftime("%d.%m.%Y %H:%M")
            text += f"• ID: {item['id']}\n"
            text += f"  Время: {run_time}\n\n"
    else:
        text += "Нет запланированных рассылок"
    
    kb = AdminKeyboards.schedule_menu()
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

@admin_only
async def schedule_new_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало планирования новой рассылки."""
    query = update.callback_query
    await query.answer()
    
    text = (
        "📅 <b>Планирование рассылки</b>\n\n"
        "Шаг 1: Отправьте сообщение для рассылки\n"
        "(текст или фото с подписью)\n\n"
        "Для отмены отправьте /cancel"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отменить", callback_data="admin:schedule_menu")]
    ])
    
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    
    context.user_data['scheduling'] = True
    return SCHEDULE_MESSAGE

# ============================================
# УПРАВЛЕНИЕ ЦЕНАМИ
# ============================================

@admin_only
async def prices_current(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ текущих цен."""
    query = update.callback_query
    await query.answer()
    
    prices = await PriceManager.get_current_prices()
    
    text = "💰 <b>Текущие тарифы и цены</b>\n\n"
    
    for plan_id, data in prices.items():
        text += f"📦 <b>{plan_id}</b>\n"
        text += f"  • Цена: {data['price']} руб.\n"
        text += f"  • Длительность: {data['duration']} дней\n"
        text += f"  • Описание: {data['description']}\n\n"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Изменить цены", callback_data="admin:prices_edit")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin:price_management")]
    ])
    
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

@admin_only
async def prices_edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало редактирования цен."""
    query = update.callback_query
    await query.answer()
    
    prices = await PriceManager.get_current_prices()
    
    text = "✏️ <b>Изменение цен</b>\n\n"
    text += "Выберите тариф для изменения цены:\n\n"
    
    buttons = []
    for plan_id, data in prices.items():
        buttons.append([
            InlineKeyboardButton(
                f"{plan_id} ({data['price']} руб.)",
                callback_data=f"admin:price_change:{plan_id}"
            )
        ])
    
    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin:price_management")])
    
    kb = InlineKeyboardMarkup(buttons)
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

@admin_only
async def price_change_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрос новой цены."""
    query = update.callback_query
    plan_id = query.data.split(':')[-1]
    
    await query.answer()
    
    context.user_data['editing_plan'] = plan_id
    
    text = (
        f"💰 <b>Изменение цены для {plan_id}</b>\n\n"
        "Отправьте новую цену в рублях (только число):\n\n"
        "Например: 299"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отменить", callback_data="admin:prices_edit")]
    ])
    
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    return PRICE_INPUT

async def noop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пустой обработчик для неактивных кнопок."""
    query = update.callback_query
    await query.answer()

@admin_only
async def export_users_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспорт списка пользователей в CSV."""
    query = update.callback_query
    try:
        await query.answer("Генерирую CSV файл...")
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    from core import db
    
    try:
        conn = await db.get_db()
        cursor = await conn.execute("""
            SELECT 
                user_id,
                username,
                first_name,
                last_name,
                created_at,
                last_activity_date
            FROM users
            ORDER BY created_at DESC
        """)
        
        data = await cursor.fetchall()
        
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['User ID', 'Username', 'First Name', 'Last Name', 'Created', 'Last Activity'])
        
        for row in data:
            writer.writerow(row)
        
        csv_data = output.getvalue().encode('utf-8-sig')
        
        await context.bot.send_document(
            chat_id=update.effective_user.id,
            document=io.BytesIO(csv_data),
            filename=f"users_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            caption="👥 Экспорт пользователей в CSV"
        )
        
        await query.edit_message_text(
            "✅ CSV файл успешно отправлен!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data="admin:export")]
            ])
        )
        
    except Exception as e:
        logger.error(f"Error exporting users CSV: {e}")
        await query.edit_message_text(
            f"❌ Ошибка: {str(e)}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data="admin:export")]
            ])
        )

@admin_only
async def export_users_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспорт пользователей в Excel."""
    query = update.callback_query
    try:
        await query.answer("Генерирую Excel файл...")
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    from core import db
    
    try:
        conn = await db.get_db()
        
        # Получаем данные пользователей
        cursor = await conn.execute("""
            SELECT 
                u.user_id,
                u.username,
                u.first_name,
                u.last_name,
                u.created_at,
                u.last_activity_date,
                COUNT(DISTINCT a.attempt_id) as attempts,
                AVG(a.score) as avg_score,
                COUNT(DISTINCT a.module_type) as modules
            FROM users u
            LEFT JOIN attempts a ON u.user_id = a.user_id
            GROUP BY u.user_id
            ORDER BY u.created_at DESC
        """)
        
        columns = ['User ID', 'Username', 'First Name', 'Last Name', 'Created', 'Last Activity', 'Attempts', 'Avg Score', 'Modules']
        df = pd.DataFrame(await cursor.fetchall(), columns=columns)
        
        output = io.BytesIO()
        df.to_excel(output, index=False, sheet_name='Users')
        output.seek(0)
        
        await context.bot.send_document(
            chat_id=update.effective_user.id,
            document=output,
            filename=f"users_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            caption="👥 Экспорт пользователей в Excel"
        )
        
        await query.edit_message_text(
            "✅ Excel файл успешно отправлен!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data="admin:export")]
            ])
        )
        
    except Exception as e:
        logger.error(f"Error exporting users Excel: {e}")
        await query.edit_message_text(
            f"❌ Ошибка: {str(e)}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data="admin:export")]
            ])
        )

@admin_only
async def receive_scheduled_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение сообщения для планирования."""
    if not context.user_data.get('scheduling'):
        return ConversationHandler.END
    
    # Сохраняем сообщение
    message_data = {}
    if update.message.photo:
        message_data['photo'] = update.message.photo[-1].file_id
        message_data['text'] = update.message.caption or ""
        message_data['entities'] = update.message.caption_entities
    else:
        message_data['text'] = update.message.text
        message_data['entities'] = update.message.entities
    
    context.user_data['scheduled_message'] = message_data
    
    text = (
        "📅 <b>Планирование рассылки</b>\n\n"
        "Шаг 2: Укажите дату и время отправки\n\n"
        "Формат: ДД.ММ.ГГГГ ЧЧ:ММ\n"
        "Например: 25.12.2024 18:00"
    )
    
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    return SCHEDULE_TIME

@admin_only
async def receive_schedule_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение времени для планирования."""
    try:
        # Парсим время
        time_str = update.message.text.strip()
        scheduled_time = datetime.strptime(time_str, "%d.%m.%Y %H:%M")
        
        if scheduled_time <= datetime.now():
            await update.message.reply_text("❌ Время должно быть в будущем!")
            return SCHEDULE_TIME
        
        # Создаем ID рассылки
        broadcast_id = f"broadcast_{int(datetime.now().timestamp())}"
        
        # Планируем рассылку
        broadcast_scheduler.add_broadcast(
            broadcast_id=broadcast_id,
            run_time=scheduled_time,
            message_data=context.user_data['scheduled_message'],
            bot=context.bot
        )
        
        text = (
            f"✅ <b>Рассылка запланирована!</b>\n\n"
            f"ID: {broadcast_id}\n"
            f"Время отправки: {scheduled_time.strftime('%d.%m.%Y %H:%M')}"
        )
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📅 К планировщику", callback_data="admin:schedule_menu")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="admin:main")]
        ])
        
        await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        
        # Очищаем данные
        context.user_data.pop('scheduling', None)
        context.user_data.pop('scheduled_message', None)
        
        return ConversationHandler.END
        
    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат!\n\n"
            "Используйте формат: ДД.ММ.ГГГГ ЧЧ:ММ\n"
            "Например: 25.12.2024 18:00"
        )
        return SCHEDULE_TIME

@admin_only
async def process_new_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка новой цены."""
    try:
        new_price = int(update.message.text.strip())
        
        if new_price < 0:
            await update.message.reply_text("❌ Цена не может быть отрицательной!")
            return PRICE_INPUT
        
        plan_id = context.user_data.get('editing_plan')
        
        # Обновляем цену
        success = await PriceManager.update_price(plan_id, new_price)
        
        if success:
            text = f"✅ Цена для {plan_id} успешно изменена на {new_price} руб."
        else:
            text = "❌ Ошибка при обновлении цены"
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 К ценам", callback_data="admin:price_management")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="admin:main")]
        ])
        
        await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        
        context.user_data.pop('editing_plan', None)
        return ConversationHandler.END
        
    except ValueError:
        await update.message.reply_text("❌ Введите число!")
        return PRICE_INPUT

@admin_only
async def price_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню управления ценами."""
    query = update.callback_query
    await query.answer()
    
    text = (
        "💰 <b>Управление ценами</b>\n\n"
        "Здесь вы можете управлять тарифами и ценами подписок."
    )
    
    kb = AdminKeyboards.price_management()
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

@admin_only
async def settings_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Управление ценами подписок."""
    query = update.callback_query
    await query.answer()
    
    from payment.config import SUBSCRIPTION_MODE, MODULE_PLANS, SUBSCRIPTION_PLANS
    
    text = "💰 <b>Управление ценами подписок</b>\n\n"
    
    if SUBSCRIPTION_MODE == 'modular':
        text += "📦 <b>Модульная система</b>\n\n"
        text += "<b>Текущие цены модулей:</b>\n"
        for module_id, module_data in MODULE_PLANS.items():
            text += f"• {module_data['name']}: {module_data['price_rub']}₽/мес\n"
    else:
        text += "📋 <b>Единая система подписок</b>\n\n"
        text += "<b>Текущие тарифы:</b>\n"
        for plan_id, plan_data in SUBSCRIPTION_PLANS.items():
            text += f"• {plan_data['name']}: {plan_data['price']}₽\n"
            text += f"  Длительность: {plan_data['duration_days']} дней\n\n"
    
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ Изменить цены", callback_data="admin:edit_prices"),
            InlineKeyboardButton("📊 Статистика продаж", callback_data="admin:sales_stats")
        ],
        [
            InlineKeyboardButton("🎁 Промокоды", callback_data="admin:promo_codes"),
            InlineKeyboardButton("💳 История платежей", callback_data="admin:payment_history")
        ],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin:settings")]
    ])
    
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

@admin_only
async def edit_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню изменения цен."""
    query = update.callback_query
    await query.answer()
    
    from payment.config import SUBSCRIPTION_MODE, MODULE_PLANS, SUBSCRIPTION_PLANS
    
    text = "✏️ <b>Изменение цен</b>\n\n"
    text += "Выберите тариф для изменения цены:\n\n"
    
    buttons = []
    
    if SUBSCRIPTION_MODE == 'modular':
        for module_id, module_data in MODULE_PLANS.items():
            button_text = f"{module_data['name']}: {module_data['price_rub']}₽"
            buttons.append([InlineKeyboardButton(
                button_text, 
                callback_data=f"admin:price_edit:{module_id}"
            )])
    else:
        for plan_id, plan_data in SUBSCRIPTION_PLANS.items():
            button_text = f"{plan_data['name']}: {plan_data['price']}₽"
            buttons.append([InlineKeyboardButton(
                button_text,
                callback_data=f"admin:price_edit:{plan_id}"
            )])
    
    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="admin:settings_prices")])
    
    kb = InlineKeyboardMarkup(buttons)
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

@admin_only
async def price_edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало изменения цены конкретного тарифа."""
    query = update.callback_query
    plan_id = query.data.split(':')[-1]
    
    await query.answer()
    
    # Сохраняем план для редактирования
    context.user_data['editing_plan_id'] = plan_id
    
    from payment.config import MODULE_PLANS, SUBSCRIPTION_PLANS, SUBSCRIPTION_MODE
    
    if SUBSCRIPTION_MODE == 'modular':
        plans = MODULE_PLANS
        current_price = plans.get(plan_id, {}).get('price_rub', 0)
        plan_name = plans.get(plan_id, {}).get('name', plan_id)
    else:
        plans = SUBSCRIPTION_PLANS
        current_price = plans.get(plan_id, {}).get('price', 0)
        plan_name = plans.get(plan_id, {}).get('name', plan_id)
    
    text = (
        f"💰 <b>Изменение цены</b>\n\n"
        f"Тариф: {plan_name}\n"
        f"Текущая цена: {current_price}₽\n\n"
        f"Отправьте новую цену в рублях (только число):\n"
        f"Например: 299"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отменить", callback_data="admin:edit_prices")]
    ])
    
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    return EDIT_PRICE_VALUE

@admin_only
async def price_edit_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка новой цены."""
    try:
        new_price = int(update.message.text.strip())
        
        if new_price < 0:
            await update.message.reply_text("❌ Цена не может быть отрицательной!")
            return EDIT_PRICE_VALUE
        
        plan_id = context.user_data.get('editing_plan_id')
        
        from core import db
        from payment.config import MODULE_PLANS, SUBSCRIPTION_PLANS, SUBSCRIPTION_MODE
        
        conn = await db.get_db()
        
        # Проверяем, существует ли план в таблице
        cursor = await conn.execute(
            "SELECT plan_id, duration_days FROM subscription_plans WHERE plan_id = ?",
            (plan_id,)
        )
        existing_plan = await cursor.fetchone()
        
        if existing_plan:
            # Если план существует - обновляем только цену
            await conn.execute("""
                UPDATE subscription_plans 
                SET price = ?, updated_at = CURRENT_TIMESTAMP
                WHERE plan_id = ?
            """, (new_price, plan_id))
        else:
            # Если плана нет - создаём новый с дефолтными значениями
            # Получаем длительность из конфига
            duration_days = 30  # Дефолтное значение
            description = plan_id
            
            if SUBSCRIPTION_MODE == 'modular':
                # Для модулей всегда 30 дней
                duration_days = 30
                description = MODULE_PLANS.get(plan_id, {}).get('name', plan_id)
            else:
                # Для обычных планов берём из конфига
                plan_data = SUBSCRIPTION_PLANS.get(plan_id, {})
                duration_days = plan_data.get('duration_days', 30)
                description = plan_data.get('name', plan_id)
            
            await conn.execute("""
                INSERT INTO subscription_plans (plan_id, price, duration_days, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """, (plan_id, new_price, duration_days, description))
        
        await conn.commit()
        
        # Обновляем цену в конфиге (для текущей сессии)
        # Это временное решение - в идеале нужно перезагружать конфиг из БД
        if SUBSCRIPTION_MODE == 'modular':
            if plan_id in MODULE_PLANS:
                MODULE_PLANS[plan_id]['price_rub'] = new_price
        else:
            if plan_id in SUBSCRIPTION_PLANS:
                SUBSCRIPTION_PLANS[plan_id]['price'] = new_price
        
        text = f"✅ Цена для тарифа {plan_id} успешно изменена на {new_price}₽"
        
        # Уведомляем других админов об изменении
        for admin_id in admin_manager.get_admin_list():
            if admin_id != update.effective_user.id:
                try:
                    await context.bot.send_message(
                        admin_id,
                        f"⚠️ Админ @{update.effective_user.username} изменил цену {plan_id} на {new_price}₽",
                        parse_mode=ParseMode.HTML
                    )
                except:
                    pass
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ Изменить другой", callback_data="admin:edit_prices")],
            [InlineKeyboardButton("⬅️ К настройкам", callback_data="admin:settings_prices")]
        ])
        
        await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        
        context.user_data.pop('editing_plan_id', None)
        return ConversationHandler.END
        
    except ValueError:
        await update.message.reply_text("❌ Введите число!")
        return EDIT_PRICE_VALUE
    except Exception as e:
        logger.error(f"Error updating price: {e}")
        await update.message.reply_text(
            f"❌ Ошибка при обновлении цены: {str(e)}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data="admin:edit_prices")]
            ])
        )
        return ConversationHandler.END

# ============================================
# 4. ФУНКЦИИ УПРАВЛЕНИЯ ПРОМОКОДАМИ
# ============================================

@admin_only
async def promo_codes_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню управления промокодами."""
    query = update.callback_query
    await query.answer()
    
    from core import db
    
    try:
        conn = await db.get_db()
        
        # Получаем активные промокоды
        cursor = await conn.execute("""
            SELECT code, discount_percent, discount_amount, usage_limit, used_count
            FROM promo_codes
            WHERE is_active = 1
            ORDER BY created_at DESC
            LIMIT 10
        """)
        
        promos = await cursor.fetchall()
        
        text = "🎁 <b>Управление промокодами</b>\n\n"
        
        if promos:
            text += "<b>Активные промокоды:</b>\n"
            for code, disc_percent, disc_amount, limit, used in promos:
                discount = f"{disc_percent}%" if disc_percent else f"{disc_amount}₽"
                usage = f"{used}/{limit}" if limit else f"{used}/∞"
                text += f"• <code>{code}</code> - {discount} (исп: {usage})\n"
        else:
            text += "Активных промокодов нет"
        
    except Exception as e:
        logger.error(f"Error loading promo codes: {e}")
        text = "🎁 <b>Управление промокодами</b>\n\nОшибка загрузки"
    
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Создать", callback_data="admin:promo_create"),
            InlineKeyboardButton("📦 Массово", callback_data="admin:promo_bulk_create")
        ],
        [
            InlineKeyboardButton("📋 Все промокоды", callback_data="admin:promo_list"),
            InlineKeyboardButton("📊 Статистика", callback_data="admin:promo_stats")
        ],
        [
            InlineKeyboardButton("🔒 Деактивировать", callback_data="admin:promo_deactivate"),
            InlineKeyboardButton("📤 Экспорт CSV", callback_data="admin:promo_export")
        ],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin:settings_prices")]
    ])
    
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

@admin_only
async def promo_create_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало создания промокода."""
    query = update.callback_query
    await query.answer()
    
    text = (
        "🎁 <b>Создание промокода</b>\n\n"
        "Шаг 1: Введите код промокода\n\n"
        "Требования:\n"
        "• Только латинские буквы и цифры\n"
        "• Длина от 4 до 20 символов\n"
        "• Например: SUMMER2024, DISCOUNT50\n\n"
        "Для отмены отправьте /cancel"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отменить", callback_data="admin:promo_codes")]
    ])
    
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    
    context.user_data['promo_creation'] = {}
    return PROMO_CODE_INPUT

@admin_only
async def promo_code_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение кода промокода."""
    code = update.message.text.strip().upper()
    
    # Валидация
    if not code.isalnum():
        await update.message.reply_text("❌ Используйте только буквы и цифры!")
        return PROMO_CODE_INPUT
    
    if len(code) < 4 or len(code) > 20:
        await update.message.reply_text("❌ Длина должна быть от 4 до 20 символов!")
        return PROMO_CODE_INPUT
    
    # Проверяем уникальность
    from core import db
    conn = await db.get_db()
    cursor = await conn.execute("SELECT id FROM promo_codes WHERE code = ?", (code,))
    exists = await cursor.fetchone()
    
    if exists:
        await update.message.reply_text("❌ Такой промокод уже существует!")
        return PROMO_CODE_INPUT
    
    context.user_data['promo_creation']['code'] = code
    
    text = (
        f"🎁 <b>Создание промокода</b>\n\n"
        f"Код: <code>{code}</code>\n\n"
        f"Шаг 2: Выберите тип скидки:"
    )
    
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Процент", callback_data="admin:promo_type:percent"),
            InlineKeyboardButton("💰 Фикс. сумма", callback_data="admin:promo_type:amount")
        ],
        [InlineKeyboardButton("❌ Отменить", callback_data="admin:promo_codes")]
    ])
    
    await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    return PROMO_DISCOUNT_INPUT

@admin_only
async def promo_type_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор типа скидки."""
    query = update.callback_query
    discount_type = query.data.split(':')[-1]
    
    await query.answer()
    
    context.user_data['promo_creation']['type'] = discount_type
    
    if discount_type == 'percent':
        text = (
            "🎁 <b>Создание промокода</b>\n\n"
            "Введите размер скидки в процентах (1-100):\n"
            "Например: 50"
        )
    else:
        text = (
            "🎁 <b>Создание промокода</b>\n\n"
            "Введите размер скидки в рублях:\n"
            "Например: 100"
        )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Отменить", callback_data="admin:promo_codes")]
    ])
    
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    return PROMO_DISCOUNT_INPUT

@admin_only
async def promo_discount_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение размера скидки."""
    try:
        discount = int(update.message.text.strip())
        
        discount_type = context.user_data['promo_creation'].get('type', 'percent')
        
        if discount_type == 'percent':
            if discount < 1 or discount > 100:
                await update.message.reply_text("❌ Процент должен быть от 1 до 100!")
                return PROMO_DISCOUNT_INPUT
            context.user_data['promo_creation']['discount_percent'] = discount
            context.user_data['promo_creation']['discount_amount'] = 0
        else:
            if discount < 1:
                await update.message.reply_text("❌ Сумма должна быть положительной!")
                return PROMO_DISCOUNT_INPUT
            context.user_data['promo_creation']['discount_amount'] = discount
            context.user_data['promo_creation']['discount_percent'] = 0
        
        text = (
            "🎁 <b>Создание промокода</b>\n\n"
            "Шаг 3: Введите лимит использований\n"
            "(0 - без ограничений):"
        )
        
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        return PROMO_LIMIT_INPUT
        
    except ValueError:
        await update.message.reply_text("❌ Введите число!")
        return PROMO_DISCOUNT_INPUT

@admin_only
async def promo_limit_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение лимита использований."""
    try:
        limit = int(update.message.text.strip())
        
        if limit < 0:
            await update.message.reply_text("❌ Лимит не может быть отрицательным!")
            return PROMO_LIMIT_INPUT
        
        # Сохраняем промокод в БД
        from core import db
        conn = await db.get_db()
        
        promo_data = context.user_data['promo_creation']
        
        await conn.execute("""
            INSERT INTO promo_codes (
                code, discount_percent, discount_amount, 
                usage_limit, used_count, is_active
            ) VALUES (?, ?, ?, ?, 0, 1)
        """, (
            promo_data['code'],
            promo_data.get('discount_percent', 0),
            promo_data.get('discount_amount', 0),
            limit if limit > 0 else None
        ))
        await conn.commit()
        
        discount_text = f"{promo_data.get('discount_percent', 0)}%" if promo_data.get('type') == 'percent' else f"{promo_data.get('discount_amount', 0)}₽"
        limit_text = f"{limit} раз" if limit > 0 else "без ограничений"
        
        text = (
            f"✅ <b>Промокод создан!</b>\n\n"
            f"Код: <code>{promo_data['code']}</code>\n"
            f"Скидка: {discount_text}\n"
            f"Лимит: {limit_text}"
        )
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎁 К промокодам", callback_data="admin:promo_codes")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="admin:main")]
        ])
        
        await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
        
        context.user_data.pop('promo_creation', None)
        return ConversationHandler.END
        
    except ValueError:
        await update.message.reply_text("❌ Введите число!")
        return PROMO_LIMIT_INPUT

@admin_only
async def promo_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список всех промокодов."""
    query = update.callback_query
    await query.answer()
    
    from core import db
    conn = await db.get_db()
    
    cursor = await conn.execute("""
        SELECT code, discount_percent, discount_amount, usage_limit, used_count, is_active
        FROM promo_codes
        ORDER BY created_at DESC
    """)
    
    promos = await cursor.fetchall()
    
    text = "📋 <b>Все промокоды</b>\n\n"
    
    if promos:
        for code, disc_percent, disc_amount, limit, used, active in promos[:20]:
            status = "✅" if active else "❌"
            discount = f"{disc_percent}%" if disc_percent else f"{disc_amount}₽"
            usage = f"{used}/{limit}" if limit else f"{used}/∞"
            
            text += f"{status} <code>{code}</code>\n"
            text += f"   Скидка: {discount} | Исп: {usage}\n\n"
    else:
        text += "Промокодов нет"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin:promo_codes")]
    ])
    
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)

@admin_only
async def promo_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика использования промокодов."""
    query = update.callback_query
    await query.answer()
    
    from core import db
    conn = await db.get_db()
    
    cursor = await conn.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(used_count) as total_used,
            COUNT(CASE WHEN is_active = 1 THEN 1 END) as active
        FROM promo_codes
    """)
    
    stats = await cursor.fetchone()
    total, total_used, active = stats
    
    # Топ промокодов по использованию
    cursor = await conn.execute("""
        SELECT code, used_count
        FROM promo_codes
        WHERE used_count > 0
        ORDER BY used_count DESC
        LIMIT 5
    """)
    
    top_promos = await cursor.fetchall()
    
    text = (
        "📊 <b>Статистика промокодов</b>\n\n"
        f"Всего создано: {total}\n"
        f"Активных: {active}\n"
        f"Использований: {total_used or 0}\n\n"
    )
    
    if top_promos:
        text += "<b>Топ по использованию:</b>\n"
        for code, used in top_promos:
            text += f"• <code>{code}</code>: {used} раз\n"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin:promo_codes")]
    ])
    
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@admin_only
async def promo_bulk_create_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало массового создания промокодов."""
    query = update.callback_query
    await query.answer()

    text = (
        "📦 <b>Массовое создание промокодов</b>\n\n"
        "Отправьте данные в формате:\n"
        "<code>количество скидка тип [лимит]</code>\n\n"
        "Примеры:\n"
        "• <code>10 20 percent</code> - 10 кодов со скидкой 20%\n"
        "• <code>5 500 fixed 1</code> - 5 кодов по 500₽, лимит 1 использование\n"
        "• <code>100 15 percent 5</code> - 100 кодов 15%, лимит 5 использований\n\n"
        "Коды будут сгенерированы автоматически."
    )

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Отмена", callback_data="admin:promo_codes")
        ]]),
        parse_mode=ParseMode.HTML
    )

    return 'PROMO_BULK_INPUT'


@admin_only
async def promo_bulk_create_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка массового создания промокодов."""
    from core import db
    import random
    import string

    message = update.message
    parts = message.text.split()

    if len(parts) < 3:
        await message.reply_text(
            "❌ Неверный формат. Используйте:\n"
            "<code>количество скидка тип [лимит]</code>",
            parse_mode=ParseMode.HTML
        )
        return 'PROMO_BULK_INPUT'

    try:
        count = int(parts[0])
        discount = int(parts[1])
        promo_type = parts[2]
        limit = int(parts[3]) if len(parts) > 3 else None

        if count > 100:
            await message.reply_text("❌ Максимум 100 промокодов за раз")
            return 'PROMO_BULK_INPUT'

        if promo_type not in ['percent', 'fixed']:
            await message.reply_text("❌ Тип должен быть percent или fixed")
            return 'PROMO_BULK_INPUT'

        # Генерация промокодов
        conn = await db.get_db()
        created_codes = []

        for _ in range(count):
            # Генерация уникального кода
            while True:
                code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
                cursor = await conn.execute(
                    "SELECT 1 FROM promo_codes WHERE code = ?", (code,)
                )
                if not await cursor.fetchone():
                    break

            # Создание промокода
            await conn.execute("""
                INSERT INTO promo_codes
                (code, discount_type, discount_value, usage_limit, is_active)
                VALUES (?, ?, ?, ?, 1)
            """, (code, promo_type, discount, limit))

            created_codes.append(code)

        await conn.commit()

        # Отправка результата
        text = f"✅ Создано {count} промокодов!\n\n"
        text += f"Тип: {promo_type}\n"
        text += f"Скидка: {discount}{'%' if promo_type == 'percent' else '₽'}\n"
        if limit:
            text += f"Лимит: {limit} исп.\n\n"

        text += "<b>Коды:</b>\n"
        for code in created_codes[:10]:
            text += f"<code>{code}</code>\n"

        if len(created_codes) > 10:
            text += f"\n...и еще {len(created_codes) - 10} кодов"

        await message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📋 Экспорт", callback_data="admin:promo_export_recent"),
                InlineKeyboardButton("◀️ Назад", callback_data="admin:promo_codes")
            ]]),
            parse_mode=ParseMode.HTML
        )

        return ConversationHandler.END

    except ValueError:
        await message.reply_text("❌ Ошибка в формате. Проверьте числа.")
        return 'PROMO_BULK_INPUT'
    except Exception as e:
        logger.error(f"Error bulk creating promos: {e}")
        await message.reply_text(f"❌ Ошибка: {e}")
        return ConversationHandler.END


@admin_only
async def promo_deactivate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Деактивация промокода."""
    query = update.callback_query
    await query.answer()

    text = (
        "🔒 <b>Деактивация промокода</b>\n\n"
        "Отправьте код промокода для деактивации:"
    )

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Отмена", callback_data="admin:promo_codes")
        ]]),
        parse_mode=ParseMode.HTML
    )

    return 'PROMO_DEACTIVATE_INPUT'


@admin_only
async def promo_deactivate_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка деактивации промокода."""
    from core import db

    message = update.message
    code = message.text.strip().upper()

    try:
        conn = await db.get_db()

        # Проверяем существование
        cursor = await conn.execute(
            "SELECT is_active FROM promo_codes WHERE code = ?", (code,)
        )
        promo = await cursor.fetchone()

        if not promo:
            await message.reply_text(
                f"❌ Промокод <code>{code}</code> не найден",
                parse_mode=ParseMode.HTML
            )
            return ConversationHandler.END

        if not promo[0]:
            await message.reply_text(
                f"ℹ️ Промокод <code>{code}</code> уже деактивирован",
                parse_mode=ParseMode.HTML
            )
            return ConversationHandler.END

        # Деактивация
        await conn.execute(
            "UPDATE promo_codes SET is_active = 0 WHERE code = ?", (code,)
        )
        await conn.commit()

        await message.reply_text(
            f"✅ Промокод <code>{code}</code> деактивирован",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="admin:promo_codes")
            ]]),
            parse_mode=ParseMode.HTML
        )

        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Error deactivating promo: {e}")
        await message.reply_text(f"❌ Ошибка: {e}")
        return ConversationHandler.END


@admin_only
async def promo_export_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспорт промокодов в CSV."""
    query = update.callback_query
    try:
        await query.answer("Экспортирую промокоды...")
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    from core import db
    import io
    import csv

    try:
        conn = await db.get_db()

        cursor = await conn.execute("""
            SELECT code, discount_type, discount_value, usage_limit,
                   used_count, is_active, created_at
            FROM promo_codes
            ORDER BY created_at DESC
        """)

        promos = await cursor.fetchall()

        if not promos:
            await query.edit_message_text(
                "❌ Нет промокодов для экспорта",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("◀️ Назад", callback_data="admin:promo_codes")
                ]])
            )
            return

        # Создание CSV
        output = io.StringIO()
        writer = csv.writer(output)

        # Заголовки
        writer.writerow(['Код', 'Тип', 'Скидка', 'Лимит', 'Использовано', 'Активен', 'Создан'])

        # Данные
        for promo in promos:
            writer.writerow(promo)

        output.seek(0)

        # Отправка файла
        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=output.getvalue().encode('utf-8'),
            filename=f"promo_codes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            caption="📋 Экспорт промокодов"
        )

        await query.edit_message_text(
            "✅ Промокоды экспортированы!",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="admin:promo_codes")
            ]])
        )

    except Exception as e:
        logger.error(f"Error exporting promos: {e}")
        await query.edit_message_text(
            f"❌ Ошибка экспорта: {e}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀️ Назад", callback_data="admin:promo_codes")
            ]])
        )


@admin_only
async def sales_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика продаж."""
    query = update.callback_query
    try:
        await query.answer("Загрузка статистики...")
    except Exception as e:
        logger.warning(f"Failed to answer callback query: {e}")

    from core import db
    
    try:
        conn = await db.get_db()
        
        # Статистика за последние 30 дней
        # ИСПРАВЛЕНО: amount -> amount_kopecks, и конвертируем копейки в рубли
        cursor = await conn.execute("""
            SELECT 
                COUNT(*) as total_payments,
                SUM(amount_kopecks) / 100.0 as total_revenue,
                AVG(amount_kopecks) / 100.0 as avg_payment,
                COUNT(DISTINCT user_id) as unique_buyers
            FROM payments
            WHERE status IN ('completed', 'confirmed')
            AND created_at > datetime('now', '-30 days')
        """)
        
        stats = await cursor.fetchone()
        
        if stats:
            total_payments, total_revenue, avg_payment, unique_buyers = stats
            
            # Статистика по планам
            cursor = await conn.execute("""
                SELECT 
                    plan_id,
                    COUNT(*) as count,
                    SUM(amount_kopecks) / 100.0 as revenue
                FROM payments
                WHERE status IN ('completed', 'confirmed')
                AND created_at > datetime('now', '-30 days')
                GROUP BY plan_id
                ORDER BY revenue DESC
            """)
            
            plans_stats = await cursor.fetchall()
            
            text = "📊 <b>Статистика продаж (30 дней)</b>\n\n"
            text += f"💰 Общая выручка: {total_revenue or 0:,.0f}₽\n"
            text += f"📦 Всего покупок: {total_payments or 0}\n"
            text += f"👥 Уникальных покупателей: {unique_buyers or 0}\n"
            text += f"💵 Средний чек: {avg_payment or 0:,.0f}₽\n\n"
            
            if plans_stats:
                text += "<b>По тарифам:</b>\n"
                for plan_id, count, revenue in plans_stats:
                    text += f"• {plan_id}: {count} шт. на {revenue:,.0f}₽\n"
        else:
            text = "📊 <b>Статистика продаж</b>\n\nДанных пока нет."
        
    except Exception as e:
        logger.error(f"Error getting sales stats: {e}")
        text = "❌ Ошибка при загрузке статистики"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Обновить", callback_data="admin:sales_stats")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin:settings_prices")]
    ])

    await safe_edit_message(query, text, reply_markup=kb, parse_mode=ParseMode.HTML)

@admin_only
async def payment_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """История платежей."""
    query = update.callback_query
    await query.answer()
    
    from core import db
    
    try:
        conn = await db.get_db()
        
        # Последние 20 платежей
        # ИСПРАВЛЕНО: amount -> amount_kopecks
        cursor = await conn.execute("""
            SELECT 
                p.user_id,
                u.username,
                u.first_name,
                p.plan_id,
                p.amount_kopecks / 100.0 as amount_rub,
                p.status,
                p.created_at
            FROM payments p
            LEFT JOIN users u ON p.user_id = u.user_id
            ORDER BY p.created_at DESC
            LIMIT 20
        """)
        
        payments = await cursor.fetchall()
        
        text = "💳 <b>История платежей</b>\n\n"
        
        if payments:
            for user_id, username, first_name, plan_id, amount_rub, status, created_at in payments[:10]:
                name = first_name or "Пользователь"
                username_str = f"@{username}" if username else f"ID: {user_id}"
                status_emoji = "✅" if status in ("completed", "confirmed") else "⏳" if status == "pending" else "❌"
                date_str = datetime.fromisoformat(created_at).strftime("%d.%m %H:%M")
                
                text += f"{status_emoji} {date_str} - {name} ({username_str})\n"
                text += f"   {plan_id}: {amount_rub:.0f}₽\n\n"
        else:
            text += "Платежей пока нет"
        
    except Exception as e:
        logger.error(f"Error getting payment history: {e}")
        text = "❌ Ошибка при загрузке истории"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Экспорт в CSV", callback_data="admin:export_payments")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="admin:settings_prices")]
    ])
    
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


async def init_price_tables():
    """Создание таблиц для управления ценами."""
    from core import db
    
    conn = await db.get_db()
    
    # Таблица тарифных планов
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS subscription_plans (
            plan_id TEXT PRIMARY KEY,
            price INTEGER NOT NULL,
            duration_days INTEGER NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Добавляем дефолтные планы если их нет
    await conn.execute("""
        INSERT OR IGNORE INTO subscription_plans (plan_id, price, duration_days, description)
        VALUES 
            ('trial_7days', 99, 7, 'Пробный период'),
            ('premium_30days', 299, 30, 'Месячная подписка'),
            ('premium_90days', 699, 90, 'Квартальная подписка')
    """)
    
    await conn.commit()
    logger.info("Price tables initialized")

def register_price_promo_handlers(app):
    """Регистрация обработчиков цен и промокодов."""
    from telegram.ext import CallbackQueryHandler, MessageHandler, filters, ConversationHandler
    
    # ConversationHandler для изменения цен
    price_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(price_edit_start, pattern="^admin:price_edit:")],
        states={
            EDIT_PRICE_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, price_edit_process)]
        },
        fallbacks=[
            CallbackQueryHandler(edit_prices, pattern="^admin:edit_prices$")
        ]
    )
    app.add_handler(price_conv)
    
    # ConversationHandler для создания промокодов
    promo_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(promo_create_start, pattern="^admin:promo_create$")],
        states={
            PROMO_CODE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, promo_code_receive)],
            PROMO_DISCOUNT_INPUT: [
                CallbackQueryHandler(promo_type_select, pattern="^admin:promo_type:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, promo_discount_receive)
            ],
            PROMO_LIMIT_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, promo_limit_receive)]
        },
        fallbacks=[
            CallbackQueryHandler(promo_codes_menu, pattern="^admin:promo_codes$"),
            CommandHandler("cancel", lambda u, c: ConversationHandler.END)
        ]
    )
    app.add_handler(promo_conv)
    
    # ConversationHandler для массового создания промокодов
    promo_bulk_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(promo_bulk_create_start, pattern="^admin:promo_bulk_create$")],
        states={
            'PROMO_BULK_INPUT': [MessageHandler(filters.TEXT & ~filters.COMMAND, promo_bulk_create_process)]
        },
        fallbacks=[
            CommandHandler("cancel", lambda u, c: ConversationHandler.END),
            CallbackQueryHandler(promo_codes_menu, pattern="^admin:promo_codes$")
        ]
    )
    app.add_handler(promo_bulk_conv)

    # ConversationHandler для деактивации промокодов
    promo_deact_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(promo_deactivate, pattern="^admin:promo_deactivate$")],
        states={
            'PROMO_DEACTIVATE_INPUT': [MessageHandler(filters.TEXT & ~filters.COMMAND, promo_deactivate_process)]
        },
        fallbacks=[
            CommandHandler("cancel", lambda u, c: ConversationHandler.END),
            CallbackQueryHandler(promo_codes_menu, pattern="^admin:promo_codes$")
        ]
    )
    app.add_handler(promo_deact_conv)

    # Обычные обработчики
    app.add_handler(CallbackQueryHandler(edit_prices, pattern="^admin:edit_prices$"))
    app.add_handler(CallbackQueryHandler(promo_codes_menu, pattern="^admin:promo_codes$"))
    app.add_handler(CallbackQueryHandler(promo_list, pattern="^admin:promo_list$"))
    app.add_handler(CallbackQueryHandler(promo_stats, pattern="^admin:promo_stats$"))

    logger.info("Price and promo handlers registered")

def register_admin_handlers(app):
    """Регистрация админских обработчиков."""
    from telegram.ext import CommandHandler, CallbackQueryHandler, MessageHandler, filters
    
    # Команда /admin
    app.add_handler(CommandHandler("admin", admin_panel))
    
    # ConversationHandler для рассылки
    broadcast_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_broadcast, pattern="^admin:broadcast$")],
        states={
            BROADCAST_TEXT: [MessageHandler(filters.ALL & ~filters.COMMAND, broadcast_receive_message)],
            BROADCAST_CONFIRM: []
        },
        fallbacks=[
            CommandHandler("cancel", lambda u, c: ConversationHandler.END),
            CallbackQueryHandler(broadcast_cancel, pattern="^admin:broadcast_cancel$"),
            CallbackQueryHandler(admin_panel, pattern="^admin:main$")
        ]
    )
    app.add_handler(broadcast_conv)
    
    # ConversationHandler для поиска пользователей
    search_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(user_search_start, pattern="^admin:user_search$")],
        states={
            USER_SEARCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, user_search_process)]
        },
        fallbacks=[
            CommandHandler("cancel", lambda u, c: ConversationHandler.END),
            CallbackQueryHandler(handle_users, pattern="^admin:users$")
        ]
    )
    app.add_handler(search_conv)
        # Экспорт и бэкап
    app.add_handler(CallbackQueryHandler(handle_export, pattern="^admin:export$"))
    app.add_handler(CallbackQueryHandler(export_stats_csv, pattern="^admin:export_stats_csv$"))
    app.add_handler(CallbackQueryHandler(export_stats_excel, pattern="^admin:export_stats_excel$"))
    app.add_handler(CallbackQueryHandler(export_users_csv, pattern="^admin:export_users_csv$"))
    app.add_handler(CallbackQueryHandler(export_users_excel, pattern="^admin:export_users_excel$"))
    app.add_handler(CallbackQueryHandler(backup_full, pattern="^admin:backup_full$"))
    
    # Графики
    app.add_handler(CallbackQueryHandler(generate_charts, pattern="^admin:generate_charts$"))
    
    # Фильтры пользователей
    app.add_handler(CallbackQueryHandler(show_filters, pattern="^admin:show_filters$"))
    app.add_handler(CallbackQueryHandler(filter_by_date, pattern="^admin:filter_date$"))
    app.add_handler(CallbackQueryHandler(apply_filter, pattern="^admin:filter_apply:"))
    app.add_handler(CommandHandler("debugdata", cmd_debug_data))
    # Настройки - Цены подписок
    app.add_handler(CallbackQueryHandler(settings_prices, pattern="^admin:settings_prices$"))
    app.add_handler(CallbackQueryHandler(sales_stats, pattern="^admin:sales_stats$"))
    app.add_handler(CallbackQueryHandler(payment_history, pattern="^admin:payment_history$"))
    app.add_handler(CallbackQueryHandler(export_payments_csv, pattern="^admin:export_payments$"))
    
    # Настройки - Модули
    app.add_handler(CallbackQueryHandler(settings_modules, pattern="^admin:settings_modules$"))
    app.add_handler(CallbackQueryHandler(modules_usage, pattern="^admin:modules_usage$"))
    
    # Настройки - Уведомления
    app.add_handler(CallbackQueryHandler(settings_notifications, pattern="^admin:settings_notifications$"))
    app.add_handler(CallbackQueryHandler(toggle_notification, pattern="^admin:toggle_notif:"))
    app.add_handler(CallbackQueryHandler(test_notification, pattern="^admin:test_notification$"))
    
    logger.info("Settings handlers registered successfully")

    # Планировщик рассылок
    app.add_handler(CallbackQueryHandler(schedule_broadcast_menu, pattern="^admin:schedule_menu$"))
    app.add_handler(CallbackQueryHandler(schedule_new_broadcast, pattern="^admin:schedule_new$"))
    
    # ConversationHandler для планировщика
    schedule_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(schedule_new_broadcast, pattern="^admin:schedule_new$")],
        states={
            SCHEDULE_MESSAGE: [MessageHandler(filters.ALL & ~filters.COMMAND, receive_scheduled_message)],
            SCHEDULE_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_schedule_time)]
        },
        fallbacks=[
            CommandHandler("cancel", lambda u, c: ConversationHandler.END),
            CallbackQueryHandler(schedule_broadcast_menu, pattern="^admin:schedule_menu$")
        ]
    )
    app.add_handler(schedule_conv)
    
    # Управление ценами
    app.add_handler(CallbackQueryHandler(price_management, pattern="^admin:price_management$"))
    app.add_handler(CallbackQueryHandler(prices_current, pattern="^admin:prices_current$"))
    app.add_handler(CallbackQueryHandler(prices_edit_start, pattern="^admin:prices_edit$"))
    app.add_handler(CallbackQueryHandler(price_change_request, pattern="^admin:price_change:"))
    
    # ConversationHandler для изменения цен
    price_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(price_change_request, pattern="^admin:price_change:")],
        states={
            PRICE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_new_price)]
        },
        fallbacks=[
            CommandHandler("cancel", lambda u, c: ConversationHandler.END),
            CallbackQueryHandler(prices_edit_start, pattern="^admin:prices_edit$")
        ]
    )
    app.add_handler(price_conv)
    
    # Запуск планировщика
    broadcast_scheduler.start()
    
    logger.info("Extended admin handlers registered successfully")
    # Главное меню
    app.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin:main$"))
    app.add_handler(CallbackQueryHandler(stats_menu, pattern="^admin:stats$"))
    app.add_handler(CallbackQueryHandler(handle_users, pattern="^admin:users$"))
    app.add_handler(CallbackQueryHandler(handle_settings, pattern="^admin:settings$"))
    app.add_handler(CallbackQueryHandler(handle_export, pattern="^admin:export$"))
    app.add_handler(CallbackQueryHandler(security_report, pattern="^admin:security$"))
    app.add_handler(CallbackQueryHandler(close_admin_panel, pattern="^admin:close$"))
    
    # Рассылка
    app.add_handler(CallbackQueryHandler(broadcast_start, pattern="^admin:broadcast_start$"))
    
    # Управление пользователями
    app.add_handler(CallbackQueryHandler(users_list, pattern="^admin:users_list$"))
    app.add_handler(CallbackQueryHandler(users_premium, pattern="^admin:users_premium$"))
    app.add_handler(CallbackQueryHandler(user_details_callback, pattern="^admin:user_details:"))
    app.add_handler(CallbackQueryHandler(grant_subscription, pattern="^admin:grant_sub:"))
    app.add_handler(CallbackQueryHandler(revoke_subscription, pattern="^admin:revoke_sub:"))
    app.add_handler(CallbackQueryHandler(
        lambda u, c: (c.user_data.__setitem__('users_page', int(u.callback_query.data.split(':')[-1])), 
                     users_list(u, c))[1],
        pattern="^admin:users_page:"
    ))
    
    # Настройки
    app.add_handler(CallbackQueryHandler(settings_mode, pattern="^admin:settings_mode$"))
    app.add_handler(CallbackQueryHandler(set_mode, pattern="^admin:set_mode:"))
    
    # Статистика
    app.add_handler(CallbackQueryHandler(stats_menu, pattern="^admin:stats_menu$"))
    app.add_handler(CallbackQueryHandler(global_stats, pattern="^admin:global_stats$"))
    app.add_handler(CallbackQueryHandler(activity_stats, pattern="^admin:activity_stats$"))
    app.add_handler(CallbackQueryHandler(module_stats, pattern="^admin:module_stats$"))
    app.add_handler(CallbackQueryHandler(top_users, pattern="^admin:top_users$"))
    app.add_handler(CallbackQueryHandler(users_stats, pattern="^admin:users_stats$"))
    app.add_handler(CallbackQueryHandler(user_stats, pattern="^admin:user_stats:"))
    app.add_handler(CallbackQueryHandler(retention_stats, pattern="^admin:retention_stats$"))
    app.add_handler(CallbackQueryHandler(conversion_stats, pattern="^admin:conversion_stats$"))
    app.add_handler(CallbackQueryHandler(financial_analytics, pattern="^admin:financial_analytics$"))

    # UTM-аналитика и источники трафика
    from analytics.admin_stats import traffic_sources_stats, campaign_stats, cohort_analysis, ab_test_stats
    app.add_handler(CallbackQueryHandler(traffic_sources_stats, pattern="^admin:traffic_sources$"))
    app.add_handler(CallbackQueryHandler(campaign_stats, pattern="^admin:campaign_stats$"))
    app.add_handler(CallbackQueryHandler(cohort_analysis, pattern="^admin:cohort_analysis$"))
    app.add_handler(CallbackQueryHandler(ab_test_stats, pattern="^admin:ab_test_stats$"))

    # Управление пользователями (новые функции)
    app.add_handler(CallbackQueryHandler(message_user_start, pattern="^admin:message_user:"))
    app.add_handler(CallbackQueryHandler(ban_user, pattern="^admin:ban_user:"))
    app.add_handler(CallbackQueryHandler(unban_user, pattern="^admin:unban_user:"))
    app.add_handler(CallbackQueryHandler(reset_user_progress_admin, pattern="^admin:reset_progress:"))

    # Мониторинг и логи
    app.add_handler(CallbackQueryHandler(system_monitor, pattern="^admin:system_monitor$"))
    app.add_handler(CallbackQueryHandler(view_logs, pattern="^admin:view_logs$"))

    # Анализ контента
    app.add_handler(CallbackQueryHandler(content_analysis, pattern="^admin:content_analysis$"))
    app.add_handler(CallbackQueryHandler(content_difficult, pattern="^admin:content_difficult$"))
    app.add_handler(CallbackQueryHandler(content_easy, pattern="^admin:content_easy$"))

    # Промокоды расширенные
    app.add_handler(CallbackQueryHandler(promo_bulk_create_start, pattern="^admin:promo_bulk_create$"))
    app.add_handler(CallbackQueryHandler(promo_deactivate, pattern="^admin:promo_deactivate$"))
    app.add_handler(CallbackQueryHandler(promo_export_csv, pattern="^admin:promo_export$"))

    # Пустой обработчик
    app.add_handler(CallbackQueryHandler(noop, pattern="^admin:noop$"))
    register_price_promo_handlers(app)

    logger.info("Admin handlers registered successfully")