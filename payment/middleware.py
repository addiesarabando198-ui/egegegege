# payment/middleware.py - ПОЛНАЯ версия с оптимизациями
"""Middleware для проверки подписок и лимитов использования с поддержкой модулей."""
import logging
import time
from typing import Optional, Dict, Set, Tuple
from datetime import datetime, timezone
from functools import lru_cache
from .config import FREE_MODULES, FREEMIUM_MODULES
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackContext, ApplicationHandlerStop, ContextTypes

from core import db
from core import config

logger = logging.getLogger(__name__)


class SubscriptionMiddleware:
    """Оптимизированный middleware для проверки подписок с поддержкой модульной системы."""
    
    def __init__(
        self,
        free_commands: Optional[Set[str]] = None,
        free_patterns: Optional[Set[str]] = None,
        check_channel: bool = False
    ):
        """
        Инициализация middleware.
        
        Args:
            free_commands: Команды, доступные без подписки
            free_patterns: Паттерны callback, доступные без подписки
            check_channel: Проверять ли подписку на канал
        """
        self.free_commands = free_commands or {
            'start', 'help', 'subscribe', 'status', 
            'my_subscriptions', 'menu', 'cancel', 'support'
        }
        
        self.free_patterns = free_patterns or {
            'subscribe', 'subscribe_start', 'payment_', 'pay_',
            'to_main_menu', 'main_menu', 'check_subscription',
            'module_info_', 'back_to_main', 'my_subscriptions',
            'duration_', 'confirm_payment'
        }
        
        self.check_channel = check_channel
        self.channel = config.REQUIRED_CHANNEL if check_channel else None
        
        # Паттерны для определения модулей (оптимизированы)
        self.module_patterns = {
            'test_part': {
                'commands': ['test', 'test_stats', 'quiz', 'mistakes', 'score'],
                'callbacks': [
                    'choose_test_part', 'to_test_part_menu', 'test_',
                    'initial:', 'block:', 'topic:', 'exam_num:', 
                    'next_random', 'next_topic', 'skip_question',
                    'mode:', 'exam_', 'mistake_', 'test_part_'
                ],
                'exclude': ['test_back_to_mode']
            },
            'task19': {
                'commands': ['task19'],
                'callbacks': ['choose_task19', 'to_task19_menu', 't19_', 'task19_'],
            },
            'task20': {
                'commands': ['task20'],
                'callbacks': ['choose_task20', 'to_task20_menu', 't20_', 'task20_', 'choose_t20'],
            },
            'task24': {
                'commands': ['task24'],
                'callbacks': ['choose_task24', 'to_task24_menu', 't24_'],
            },
            'task23': {
                'commands': ['task23'],
                'callbacks': ['choose_task23', 'to_task23_menu', 't23_', 'task23_'],
            },
            'task25': {
                'commands': ['task25'],
                'callbacks': ['choose_task25', 'to_task25_menu', 't25_', 'task25_'],
            },
            # Алиасы для обратной совместимости
            't20': {
                'commands': ['task20'],
                'callbacks': ['choose_t20', 'to_task20_menu', 't20_', 'task20_'],
            }
        }
        
        # Кэш для ускорения проверок
        self._module_cache = {}  # {update_key: module_code}
        self._access_cache = {}  # {(user_id, module): has_access}
        self._cache_ttl = 60
        self._cache_timestamps = {}
    
    @lru_cache(maxsize=256)
    def _get_update_key(self, update: Update) -> Optional[str]:
        """Получает уникальный ключ из update для кэширования."""
        if update.message and update.message.text:
            return f"msg:{update.message.text}"
        elif update.callback_query and update.callback_query.data:
            return f"cb:{update.callback_query.data}"
        return None
    
    def _get_module_from_update(self, update: Update) -> Optional[str]:
        """
        Определяет модуль по update с использованием кэша.
        
        Args:
            update: Telegram update
            
        Returns:
            Код модуля или None
        """
        # Пытаемся получить из кэша
        update_key = self._get_update_key(update)
        if update_key and update_key in self._module_cache:
            return self._module_cache[update_key]
        
        module_code = None
        
        # Для команд
        if update.message and update.message.text and update.message.text.startswith('/'):
            command = update.message.text.split()[0][1:].split('@')[0].lower()
            
            for module, patterns in self.module_patterns.items():
                if command in patterns['commands']:
                    module_code = module
                    break
        
        # Для callback_query
        elif update.callback_query and update.callback_query.data:
            callback_data = update.callback_query.data
            
            # Прямое соответствие для кнопок главного меню
            direct_mapping = {
                'choose_test_part': 'test_part',
                'choose_task19': 'task19',
                'choose_task20': 'task20',
                'choose_task24': 'task24',
                'choose_task25': 'task25',
                'choose_personal_cabinet': 'personal_cabinet',
                'choose_teacher_mode': 'teacher_mode',
            }

            if callback_data in direct_mapping:
                module_code = direct_mapping[callback_data]
            else:
                # Проверяем паттерны
                for module, patterns in self.module_patterns.items():
                    # Проверяем исключения
                    if any(callback_data == exc or callback_data.startswith(exc) 
                           for exc in patterns.get('exclude', [])):
                        continue
                    
                    # Проверяем паттерны
                    for pattern in patterns['callbacks']:
                        if pattern.endswith('_') and callback_data.startswith(pattern):
                            module_code = module
                            break
                        elif callback_data == pattern:
                            module_code = module
                            break
                    
                    if module_code:
                        break
        
        # Сохраняем в кэш
        if update_key and module_code:
            self._module_cache[update_key] = module_code
        
        return module_code
    
    async def process_update(
        self,
        update: Update,
        application: Application,
        check_update: bool,
        context: ContextTypes.DEFAULT_TYPE
    ) -> bool:
        """
        Обрабатывает update и проверяет доступ.
        
        Args:
            update: Telegram update
            application: Приложение
            check_update: Проверять ли обновление
            context: Контекст
            
        Returns:
            True если доступ разрешен
            
        Raises:
            ApplicationHandlerStop: Если доступ запрещен
        """
        # КРИТИЧЕСКИ ВАЖНО: /start всегда работает
        if update.message and update.message.text:
            text = update.message.text.strip()
            if text.startswith('/start'):
                logger.debug(f"Command /start detected - bypassing ALL subscription checks")
                return True
        
        # Пропускаем если нет пользователя
        if not update.effective_user:
            return True
        
        user_id = update.effective_user.id
        
        # Проверяем админов
        admin_ids = self._get_admin_ids()
        if user_id in admin_ids:
            logger.debug(f"Admin user {user_id} - skipping subscription check")
            return True
        
        # Проверяем бесплатные действия
        if self._is_free_action(update, context):
            logger.debug(f"Free action detected for user {user_id}")
            return True
        
        # ИСПРАВЛЕНИЕ: Сначала определяем модуль
        module_code = self._get_module_from_update(update)
        if module_code:
            module_code = self._normalize_module_code(module_code)
        
        # Если модуль не определен, берем из контекста
        if not module_code and context:
            module_code = context.user_data.get('active_module')
        
        # Сохраняем активный модуль в контексте
        if module_code and context:
            context.user_data['active_module'] = module_code
        
        # Если модуль не определен - пропускаем
        if not module_code:
            logger.debug(f"No module detected for user {user_id}")
            return True

        # Проверяем бесплатные модули
        if module_code in FREE_MODULES:
            logger.info(f"Free module {module_code} accessed by user {user_id}")
            return True

        # Модули с freemium доступом - пропускаем, обработчик сам проверит лимиты
        if module_code in FREEMIUM_MODULES:
            logger.info(f"Freemium module {module_code} accessed by user {user_id} - delegating check to handler")
            return True

        # Получаем менеджер подписок
        subscription_manager = application.bot_data.get('subscription_manager')
        if not subscription_manager:
            logger.warning("SubscriptionManager not found in bot_data")
            return True

        # Проверяем доступ к модулю (с кэшем + TTL)
        cache_key = (user_id, module_code)
        cache_timestamp = self._cache_timestamps.get(cache_key, 0)
        cache_expired = (time.time() - cache_timestamp) > self._cache_ttl

        if cache_key in self._access_cache and not cache_expired:
            has_access = self._access_cache[cache_key]
        else:
            has_access = await subscription_manager.check_module_access(user_id, module_code)
            self._access_cache[cache_key] = has_access
            self._cache_timestamps[cache_key] = time.time()

        if not has_access:
            logger.info(f"Access denied for user {user_id} to module {module_code}")
            await self._send_module_subscription_required(update, context, module_code)
            raise ApplicationHandlerStop()
        
        # Проверяем лимиты использования
        can_use, used, limit = await self._check_usage_limit(user_id, subscription_manager)
        
        if not can_use:
            await self._send_limit_exceeded(update, context, used, limit)
            raise ApplicationHandlerStop()
        
        # Увеличиваем счетчик использования для платных модулей
        if module_code not in FREE_MODULES:
            await self._increment_usage(user_id)
        
        # Сохраняем информацию в context
        if context:
            context.user_data['subscription_info'] = await subscription_manager.get_subscription_info(user_id)
            context.user_data['usage_info'] = {'used': used + 1, 'limit': limit}
        
        # Показываем оставшийся лимит при необходимости
        if update.callback_query and limit > 0 and limit != -1:
            remaining = limit - used - 1
            if remaining > 0 and remaining <= 10 and module_code not in FREE_MODULES:
                await update.callback_query.answer(f"Осталось вопросов: {remaining}")
        
        logger.info(f"Access granted for user {user_id} to module {module_code}")
        return True
    
    def _normalize_module_code(self, module_code: str) -> str:
        """Нормализует код модуля для консистентности."""
        # Маппинг алиасов к основным кодам
        module_aliases = {
            't20': 'task20',
            't19': 'task19',
            't24': 'task24',
            't25': 'task25',
            'test': 'test_part'
        }
        return module_aliases.get(module_code, module_code)

    def _is_free_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """
        Проверяет, является ли действие бесплатным.
        
        Args:
            update: Telegram update
            context: Контекст
            
        Returns:
            True если действие бесплатное
        """
        # Проверка команд
        if update.message and update.message.text:
            text = update.message.text.strip()
            
            if text.startswith('/'):
                command = text.split()[0][1:].split('@')[0].lower()
                if command in self.free_commands:
                    return True
        
        # Проверка callback
        if update.callback_query and update.callback_query.data:
            callback_data = update.callback_query.data
            
            # Проверяем по паттернам
            for pattern in self.free_patterns:
                if pattern.endswith('_'):
                    if callback_data.startswith(pattern):
                        return True
                else:
                    if callback_data == pattern:
                        return True
        
        # Проверка состояния тестовой части в контексте
        if context and context.user_data.get('test_state') in ['ANSWERING', 'EXAM_MODE', 'CHOOSING_MODE']:
            return True
        
        return False
    
    def _get_admin_ids(self) -> list:
        """Получает список ID администраторов."""
        admin_ids = []
        if hasattr(config, 'ADMIN_IDS') and config.ADMIN_IDS:
            if isinstance(config.ADMIN_IDS, str):
                admin_ids = [int(id.strip()) for id in config.ADMIN_IDS.split(',') if id.strip()]
            elif isinstance(config.ADMIN_IDS, list):
                admin_ids = config.ADMIN_IDS
        return admin_ids
    
    async def _check_channel_membership(self, user_id: int, bot) -> bool:
        """
        Проверяет подписку на канал.
        
        Args:
            user_id: ID пользователя
            bot: Экземпляр бота
            
        Returns:
            True если подписан
        """
        if not self.channel:
            return True
        
        try:
            member = await bot.get_chat_member(self.channel, user_id)
            return member.status in ['member', 'administrator', 'creator']
        except Exception as e:
            logger.error(f"Error checking channel membership: {e}")
            return False
    
    async def _check_usage_limit(self, user_id: int, subscription_manager) -> Tuple[bool, int, int]:
        """
        Проверяет лимиты использования.
        
        Args:
            user_id: ID пользователя
            subscription_manager: Менеджер подписок
            
        Returns:
            (can_use, used_count, limit)
        """
        # Получаем данные пользователя
        user_data = await db.get_or_create_user_status(user_id)
        usage_count = user_data.get('monthly_usage_count', 0)
        
        # Проверяем подписку
        subscription = await subscription_manager.check_active_subscription(user_id)
        
        if subscription:
            # Для активной подписки нет лимитов (или большие лимиты)
            plan_id = subscription.get('plan_id')
            
            # Pro планы без лимитов
            if plan_id in ['pro_month', 'pro_ege', 'package_full']:
                return (True, usage_count, -1)  # -1 = безлимит
            
            # Базовые планы с лимитами
            elif plan_id in ['basic_month', 'package_second']:
                limit = 100  # вопросов в день
                # Проверяем дневной лимит
                today_count = user_data.get('daily_usage_count', 0)
                if today_count >= limit:
                    return (False, today_count, limit)
                return (True, today_count, limit)
        
        # Для бесплатных пользователей - месячный лимит
        FREE_LIMIT = 50
        
        if usage_count >= FREE_LIMIT:
            return (False, usage_count, FREE_LIMIT)
        
        return (True, usage_count, FREE_LIMIT)
    
    async def _increment_usage(self, user_id: int):
        """
        Увеличивает счетчик использования.
        
        Args:
            user_id: ID пользователя
        """
        try:
            today = datetime.now().date().isoformat()
            
            # Обновляем оба счетчика
            await db.execute_with_retry(
                """
                UPDATE users 
                SET monthly_usage_count = monthly_usage_count + 1,
                    daily_usage_count = CASE 
                        WHEN last_usage_date = ? THEN daily_usage_count + 1 
                        ELSE 1 
                    END,
                    last_usage_date = ?
                WHERE user_id = ?
                """,
                (today, today, user_id)
            )
        except Exception as e:
            logger.error(f"Error incrementing usage for user {user_id}: {e}")
    
    async def _send_subscription_required(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отправляет упрощенное сообщение о необходимости подписки."""
        from .config import SUBSCRIPTION_MODE
        
        text = "❌ <b>Для доступа к этой функции необходима подписка!</b>\n\n"
        text += "💎 <b>Доступные тарифы:</b>\n\n"
        
        text += "🎁 <b>Пробный период</b> — 1₽\n"
        text += "   • Полный доступ на 7 дней\n"
        text += "   • Все задания с проверкой ИИ\n\n"
        
        text += "👑 <b>Полная подписка</b> — 249₽/мес\n"
        text += "   • Все задания второй части\n"
        text += "   • Задания 19, 20, 24, 25\n"
        text += "   • Безлимитные проверки\n\n"
        
        text += "💡 <i>Рекомендуем начать с пробного периода!</i>"
        
        keyboard = [
            [InlineKeyboardButton("💳 Оформить подписку", callback_data="subscribe_start")],
            [InlineKeyboardButton("⬅️ Главное меню", callback_data="to_main_menu")]
        ]
        
        if self.channel and self.check_channel:
            text += f"\n\n📣 Или подпишитесь на канал {self.channel} для бесплатного доступа"
            keyboard.insert(1, [
                InlineKeyboardButton("📣 Подписаться на канал", url=f"https://t.me/{self.channel[1:]}")
            ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await update.callback_query.answer("Требуется подписка!", show_alert=True)
            try:
                await update.callback_query.edit_message_text(
                    text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML
                )
            except Exception:
                await update.callback_query.message.reply_text(
                    text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML
                )
        elif update.message:
            await update.message.reply_text(
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
    
    async def _send_module_subscription_required(self, update: Update, context: ContextTypes.DEFAULT_TYPE, module_code: str):
        """
        Отправляет упрощенное сообщение о необходимости подписки для модуля.

        Args:
            update: Telegram update
            context: Контекст
            module_code: Код модуля
        """
        # Детальная информация о модулях
        module_info = {
            'task19': {
                'icon': '🎯',
                'name': 'Задание 19 — Примеры и иллюстрации',
                'description': 'Научись подбирать убедительные примеры к любой теории',
                'value': '✅ Эталонные примеры для каждой темы\n✅ ИИ оценивает как эксперт ЕГЭ\n✅ Примеры из разных сфер жизни'
            },
            'task20': {
                'icon': '📖',
                'name': 'Задание 20 — Аргументация',
                'description': 'Строй железную аргументацию на максимум баллов',
                'value': '✅ Готовые аргументы по всем темам\n✅ Техники убедительной аргументации\n✅ Проверка от ИИ по критериям ФИПИ'
            },
            'task24': {
                'icon': '💎',
                'name': 'Задание 24 — Планы',
                'description': 'Создавай развернутые планы без ошибок',
                'value': '✅ Эталонные планы по всем темам\n✅ Проверка структуры и полноты\n✅ Детализация каждого пункта'
            },
            'task25': {
                'icon': '✍️',
                'name': 'Задание 25 — Мини-сочинение',
                'description': 'Пиши обоснования на 6 из 6 баллов',
                'value': '✅ Пошаговая структура ответа\n✅ Проверка теории и примеров\n✅ Разбор каждого критерия ФИПИ'
            },
            'test_part': {
                'icon': '📝',
                'name': 'Тестовая часть',
                'description': 'Тренировка заданий 1-16',
                'value': '✅ 1000+ вопросов\n✅ Детальные объяснения\n✅ Трекинг прогресса'
            }
        }

        # Нормализуем код модуля
        if hasattr(self, '_normalize_module_code'):
            normalized_code = self._normalize_module_code(module_code)
        else:
            normalized_code = module_code

        info = module_info.get(normalized_code, {
            'icon': '🔒',
            'name': normalized_code,
            'description': 'Этот модуль требует подписку',
            'value': ''
        })

        # Формируем информативное сообщение
        text = f"{info['icon']} <b>{info['name']}</b>\n\n"
        text += f"<b>Что это?</b>\n{info['description']}\n\n"

        if info['value']:
            text += f"<b>Что входит:</b>\n{info['value']}\n\n"

        text += "<b>Варианты доступа:</b>\n\n"

        # Показываем два варианта
        text += "🎁 <b>Пробный период</b> — 1₽\n"
        text += "   • Полный доступ на 7 дней\n"
        text += "   • Все задания с проверкой ИИ\n\n"

        text += "👑 <b>Полная подписка</b> — 249₽/мес\n"
        text += "   • Безлимитные проверки\n"
        text += "   • Все задания 19-25\n\n"

        text += "💡 <i>Попробуй бесплатно 7 дней за 1₽!</i>"
        
        # Кнопки - только 2 варианта
        buttons = [
            [InlineKeyboardButton("🎁 Попробовать за 1₽", callback_data="pay_trial")],
            [InlineKeyboardButton("👑 Полная подписка - 249₽/мес", callback_data="pay_package_full")],
            [InlineKeyboardButton("🛒 Все подписки", callback_data="subscribe_start")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
        ]
        
        reply_markup = InlineKeyboardMarkup(buttons)
        
        # Отправляем сообщение
        if update.callback_query:
            await update.callback_query.answer("Требуется подписка!", show_alert=True)
            try:
                await update.callback_query.edit_message_text(
                    text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.debug(f"Could not edit message: {e}")
                await update.callback_query.message.reply_text(
                    text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML
                )
        elif update.message:
            await update.message.reply_text(
                text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
    async def _send_limit_exceeded(self, update: Update, context: ContextTypes.DEFAULT_TYPE, used: int, limit: int):
        """
        Отправляет сообщение о превышении лимита.
        
        Args:
            update: Telegram update  
            context: Контекст
            used: Использовано
            limit: Лимит
        """
        if limit == 50:
            text = f"❌ <b>Вы достигли месячного лимита!</b>\n\n"
            text += f"Использовано: {used}/50 вопросов в месяц\n\n"
            text += "Оформите подписку для увеличения лимита!"
        else:
            text = f"❌ <b>Вы достигли дневного лимита!</b>\n\n"
            text += f"Использовано: {used}/{limit} вопросов сегодня\n\n"
            text += "Попробуйте завтра или улучшите подписку!"
        
        keyboard = [
            [InlineKeyboardButton("💳 Улучшить подписку", callback_data="subscribe_start")],
            [InlineKeyboardButton("⬅️ Главное меню", callback_data="to_main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await update.callback_query.answer("Лимит исчерпан!", show_alert=True)
            try:
                await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
            except:
                await update.callback_query.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        elif update.message:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    
    async def _send_channel_required(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отправляет сообщение о необходимости подписки на канал."""
        text = f"❌ <b>Для использования бота необходима подписка на канал {self.channel}</b>\n\n"
        text += "После подписки нажмите кнопку «Проверить подписку»"
        
        keyboard = [
            [InlineKeyboardButton("📣 Подписаться на канал", url=f"https://t.me/{self.channel[1:]}")],
            [InlineKeyboardButton("🔄 Проверить подписку", callback_data="check_subscription")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await update.callback_query.answer("Требуется подписка на канал!", show_alert=True)
            try:
                await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
            except:
                await update.callback_query.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        elif update.message:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    
    def clear_cache(self, user_id: Optional[int] = None):
        """
        Очищает кэш.
        
        Args:
            user_id: ID пользователя (если None - очищает весь кэш)
        """
        if user_id:
            # Очищаем кэш для конкретного пользователя
            self._access_cache = {
                k: v for k, v in self._access_cache.items()
                if k[0] != user_id
            }
        else:
            # Полная очистка кэшей
            self._module_cache.clear()
            self._access_cache.clear()


def setup_subscription_middleware(
    application: Application,
    free_commands: Optional[Set[str]] = None,
    free_patterns: Optional[Set[str]] = None,
    check_channel: bool = False
) -> SubscriptionMiddleware:
    """
    Настраивает middleware для проверки подписок (упрощенная версия).
    
    Args:
        application: Приложение Telegram
        free_commands: Бесплатные команды
        free_patterns: Бесплатные паттерны
        check_channel: Проверять ли канал
        
    Returns:
        Экземпляр middleware
    """
    # Дефолтные бесплатные паттерны (ОБНОВЛЕНО - убраны модульные паттерны)
    default_free_patterns = {
        # Базовые паттерны
        'main_menu', 'to_main_menu', 'start_', 'help_',
        'subscribe', 'pay_', 'confirm_', 'cancel_',
        'module_info_', 'duration_', 'back_to_',
        'check_subscription', 'support_', 'settings_',
        
        # Паттерны для подписки
        'my_subscription', 'subscribe_start', 'my_subscriptions',
        
        # УДАЛЕНЫ паттерны для выбора модулей:
        # 'toggle_', 'info_', 'proceed_with_modules',
        # 'pay_individual_modules', 'back_to_module_selection', 'back_to_modules'
        
        # Паттерны для оплаты (только trial и full)
        'pay_trial', 'pay_package_full',
        
        # Паттерны для навигации (общие)
        'back_to_main', 'back_to_plans',
        
        # Админские паттерны
        'admin_', 'broadcast_', 'stats_', 'test_',
        'add_user_', 'remove_user_', 'list_users_',
        'refresh_'
    }
    
    # Дефолтные бесплатные команды
    default_free_commands = {
        # Базовые команды
        'start', 'help', 'subscribe', 'status', 
        'my_subscriptions', 'menu', 'cancel', 'support',
        
        # Админские команды
        'grant_subscription', 'activate_payment', 'check_webhook',
        'list_subscriptions', 'check_user_subscription', 'revoke',
        'payment_stats', 'check_admin', 'grant', 'revoke_subscription'
    }
    
    # Объединяем с пользовательскими
    if free_commands:
        default_free_commands.update(free_commands)
    if free_patterns:
        default_free_patterns.update(free_patterns)
    
    # Создаем middleware
    middleware = SubscriptionMiddleware(
        free_commands=default_free_commands,
        free_patterns=default_free_patterns,
        check_channel=check_channel
    )
    
    # Сохраняем в bot_data
    application.bot_data['subscription_middleware'] = middleware
    
    # Создаем обработчик
    async def check_subscription_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик для проверки подписки."""
        try:
            await middleware.process_update(update, application, True, context)
        except ApplicationHandlerStop:
            raise
    
    # Регистрируем с высоким приоритетом
    from telegram.ext import TypeHandler
    application.add_handler(
        TypeHandler(Update, check_subscription_handler),
        group=-100  # Выполняется первым
    )
    
    logger.info("Subscription middleware установлен (упрощенная версия)")
    logger.info("Поддержка только trial и full подписок")
    
    return middleware