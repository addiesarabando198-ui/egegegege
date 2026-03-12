# payment/promo_handler.py
"""Обработчик промокодов для платежного модуля."""


import logging
from typing import Dict, Any, Optional, Tuple, List
import aiosqlite
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram.error import BadRequest

from core.db import DATABASE_FILE
from core.error_handler import safe_handler

logger = logging.getLogger(__name__)

# Состояние для ввода промокода
PROMO_INPUT = "promo_input"


class PromoCodeManager:
    """Менеджер для работы с промокодами с защитой от повторного использования."""
    
    def __init__(self, database_file: str = DATABASE_FILE):
        self.database_file = database_file
    
    async def check_promo_code(self, code: str, user_id: int = None) -> Optional[Dict[str, Any]]:
        """
        Проверяет валидность промокода с учетом использования пользователем.
        
        Args:
            code: Код промокода
            user_id: ID пользователя для проверки повторного использования
        
        Returns:
            Словарь с данными промокода или None если не найден/недействителен
        """
        try:
            async with aiosqlite.connect(self.database_file) as conn:
                # Проверяем существование и активность промокода
                cursor = await conn.execute(
                    """
                    SELECT id, code, discount_percent, discount_amount,
                           usage_limit, used_count, is_active,
                           first_purchase_only, min_duration_months
                    FROM promo_codes
                    WHERE code = ? AND is_active = 1
                    """,
                    (code.upper(),)
                )
                row = await cursor.fetchone()

                if not row:
                    return None

                (promo_id, code, discount_percent, discount_amount,
                 usage_limit, used_count, is_active,
                 first_purchase_only, min_duration_months) = row

                # Проверяем общий лимит использований
                if usage_limit is not None and used_count >= usage_limit:
                    logger.info(f"Promo code {code} exceeded usage limit")
                    return None

                # Проверяем, использовал ли ЭТОТ пользователь промокод ранее.
                # Каждый пользователь может использовать любой промокод только ОДИН раз,
                # независимо от usage_limit (usage_limit ограничивает общее число использований,
                # а не повторные использования одним пользователем).
                if user_id:
                    cursor = await conn.execute(
                        """
                        SELECT COUNT(*) FROM promo_usage_log
                        WHERE promo_code = ? AND user_id = ?
                        """,
                        (code.upper(), user_id)
                    )
                    used_by_user = await cursor.fetchone()

                    if used_by_user and used_by_user[0] > 0:
                        logger.info(f"Promo code {code} already used by user {user_id}")
                        return None  # Пользователь уже использовал этот промокод
                
                return {
                    'id': promo_id,
                    'code': code,
                    'discount_percent': discount_percent or 0,
                    'discount_amount': discount_amount or 0,
                    'usage_limit': usage_limit,
                    'used_count': used_count,
                    'is_active': is_active,
                    'first_purchase_only': bool(first_purchase_only),
                    'min_duration_months': min_duration_months or 0
                }

        except Exception as e:
            logger.error(f"Error checking promo code: {e}")
            return None

    def calculate_discount(self, base_price: int, promo_data: Dict[str, Any]) -> Tuple[int, int]:
        """
        Рассчитывает финальную цену и размер скидки на основе данных промокода.

        Args:
            base_price: Базовая цена в рублях
            promo_data: Данные промокода (discount_percent, discount_amount)

        Returns:
            (final_price, discount_amount): Финальная цена и размер скидки в рублях
        """
        discount_percent = promo_data.get('discount_percent', 0)
        discount_amount_fixed = promo_data.get('discount_amount', 0)

        # Применяем процентную скидку
        if discount_percent > 0:
            discount_amount = int(base_price * discount_percent / 100)
        # Или фиксированную скидку
        elif discount_amount_fixed > 0:
            discount_amount = discount_amount_fixed
        else:
            discount_amount = 0

        # Рассчитываем финальную цену (минимум 1 рубль)
        final_price = max(1, base_price - discount_amount)

        # Корректируем размер скидки, если цена уперлась в минимум
        discount_amount = base_price - final_price

        return final_price, discount_amount

    async def check_promo_conditions(
        self, promo_data: Dict[str, Any], user_id: int, duration_months: int = 1
    ) -> Tuple[bool, str]:
        """
        Проверяет дополнительные условия промокода.

        Args:
            promo_data: Данные промокода из check_promo_code()
            user_id: ID пользователя
            duration_months: Выбранная длительность подписки в месяцах

        Returns:
            (ok, error_message): True если условия выполнены
        """
        # Условие: только для первой покупки
        if promo_data.get('first_purchase_only'):
            try:
                async with aiosqlite.connect(self.database_file) as conn:
                    cursor = await conn.execute(
                        """
                        SELECT COUNT(*) FROM payments
                        WHERE user_id = ? AND status = 'completed'
                        """,
                        (user_id,)
                    )
                    row = await cursor.fetchone()
                    if row and row[0] > 0:
                        return False, "Этот промокод действует только на первую покупку."
            except Exception as e:
                logger.error(f"Error checking first purchase condition: {e}")

        # Условие: минимальная длительность подписки
        min_months = promo_data.get('min_duration_months', 0)
        if min_months and duration_months < min_months:
            month_word = "месяца" if min_months in (2, 3, 4) else "месяцев"
            return False, (
                f"Этот промокод действует только при покупке от {min_months} {month_word}."
            )

        return True, ""

    async def apply_promo_code(self, code: str, user_id: int, order_id: str = None) -> bool:
        """
        Применяет промокод - регистрирует использование в БД.

        ВАЖНО: Этот метод должен вызываться ТОЛЬКО после успешной оплаты/активации!
        Не вызывайте его при вводе промокода, иначе счетчик увеличится без фактической покупки.

        Args:
            code: Код промокода
            user_id: ID пользователя
            order_id: ID заказа (опционально)

        Returns:
            True если промокод успешно применен
        """
        try:
            async with aiosqlite.connect(self.database_file) as conn:
                # Получаем информацию о промокоде
                cursor = await conn.execute(
                    """
                    SELECT usage_limit FROM promo_codes
                    WHERE code = ?
                    """,
                    (code.upper(),)
                )
                promo_info = await cursor.fetchone()

                if not promo_info:
                    logger.error(f"Promo code {code} not found when trying to apply")
                    return False

                usage_limit = promo_info[0]

                # Увеличиваем счетчик использований промокода
                await conn.execute(
                    """
                    UPDATE promo_codes
                    SET used_count = used_count + 1
                    WHERE code = ?
                    """,
                    (code.upper(),)
                )

                # Записываем в лог использования (каждый промокод — один раз на пользователя)
                await conn.execute(
                    """
                    INSERT OR IGNORE INTO promo_usage_log (promo_code, user_id, order_id, used_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (code.upper(), user_id, order_id)
                )
                logger.info(f"Recorded usage of promo {code} by user {user_id}")

                await conn.commit()
                logger.info(f"Applied promo code {code} for user {user_id}, order {order_id}")
                return True

        except Exception as e:
            logger.error(f"Error applying promo code: {e}")
            return False

    async def get_user_promo_history(self, user_id: int) -> List[Dict[str, Any]]:
        """
        Получает историю использования промокодов пользователем.
        
        Returns:
            Список использованных промокодов
        """
        try:
            async with aiosqlite.connect(self.database_file) as conn:
                cursor = await conn.execute(
                    """
                    SELECT promo_code, discount_applied, original_price, 
                           final_price, order_id, used_at
                    FROM promo_usage_log
                    WHERE user_id = ?
                    ORDER BY used_at DESC
                    """,
                    (user_id,)
                )
                
                history = []
                rows = await cursor.fetchall()
                for row in rows:
                    history.append({
                        'promo_code': row[0],
                        'discount_applied': row[1],
                        'original_price': row[2],
                        'final_price': row[3],
                        'order_id': row[4],
                        'used_at': row[5]
                    })
                
                return history
                
        except Exception as e:
            logger.error(f"Error getting promo history: {e}")
            return []
    
    async def is_promo_available_for_user(self, code: str, user_id: int) -> Tuple[bool, str]:
        """
        Проверяет доступность промокода для конкретного пользователя.
        
        Returns:
            (доступен, сообщение об ошибке если недоступен)
        """
        try:
            async with aiosqlite.connect(self.database_file) as conn:
                # Проверяем существование промокода
                cursor = await conn.execute(
                    """
                    SELECT usage_limit, used_count, is_active
                    FROM promo_codes
                    WHERE code = ?
                    """,
                    (code.upper(),)
                )
                promo = await cursor.fetchone()
                
                if not promo:
                    return False, "Промокод не найден"
                
                usage_limit, used_count, is_active = promo
                
                if not is_active:
                    return False, "Промокод деактивирован"
                
                if usage_limit and used_count >= usage_limit:
                    return False, "Промокод больше не действителен (исчерпан лимит)"
                
                # Проверяем использование пользователем
                cursor = await conn.execute(
                    """
                    SELECT COUNT(*) FROM promo_usage_log
                    WHERE promo_code = ? AND user_id = ?
                    """,
                    (code.upper(), user_id)
                )
                used = await cursor.fetchone()
                
                if used and used[0] > 0:
                    return False, "Вы уже использовали этот промокод"
                
                return True, "OK"
                
        except Exception as e:
            logger.error(f"Error checking promo availability: {e}")
            return False, "Ошибка проверки промокода"


# Инициализируем менеджер промокодов
promo_manager = PromoCodeManager()


@safe_handler()
async def show_promo_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает экран ввода промокода."""
    query = update.callback_query
    if query:
        await query.answer()
    
    # Получаем текущую цену и план
    total_price = context.user_data.get('total_price', 0)
    plan_name = context.user_data.get('plan_name', 'Подписка')
    duration = context.user_data.get('duration_months', 1)
    
    text = f"""🎁 <b>Применение промокода</b>

📦 План: <b>{plan_name}</b>
⏱ Срок: <b>{duration} мес.</b>
💰 Стоимость: <b>{total_price} ₽</b>

Введите промокод для получения скидки или нажмите "Продолжить без промокода":"""
    
    keyboard = [
        [InlineKeyboardButton("➡️ Продолжить без промокода", callback_data="skip_promo")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_duration_selection")],
        [InlineKeyboardButton("❌ Отменить", callback_data="cancel_payment")]
    ]
    
    try:
        if query:
            await query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            message = update.message or update.callback_query.message
            await message.reply_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    except BadRequest as e:
        if "Message is not modified" in str(e):
            logger.debug("Message already showing promo input")
            if query:
                await query.answer("Введите промокод в чат", show_alert=False)
    
    return PROMO_INPUT


@safe_handler()
async def handle_promo_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ввод промокода с проверкой повторного использования."""
    promo_code = update.message.text.strip().upper()
    user_id = update.effective_user.id

    # Сначала проверяем доступность с детальным сообщением об ошибке
    is_available, error_message = await promo_manager.is_promo_available_for_user(promo_code, user_id)

    if not is_available:
        keyboard = [
            [InlineKeyboardButton("🔄 Попробовать другой", callback_data="retry_promo")],
            [InlineKeyboardButton("➡️ Продолжить без промокода", callback_data="skip_promo")],
            [InlineKeyboardButton("❌ Отменить", callback_data="cancel_payment")]
        ]

        if "уже использовали" in error_message:
            text = (
                f"❌ <b>Промокод уже использован</b>\n\n"
                f"Вы уже применяли промокод <code>{promo_code}</code> ранее.\n"
                "Каждый промокод можно использовать только один раз.\n\n"
                "Попробуйте другой промокод или продолжите без скидки."
            )
        else:
            text = (
                f"❌ <b>Промокод недействителен</b>\n\n"
                f"{error_message}\n\n"
                "Попробуйте другой промокод или продолжите без скидки."
            )

        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return PROMO_INPUT

    # Проверяем условия промокода (первая покупка, мин. длительность)
    promo_data = await promo_manager.check_promo_code(promo_code, user_id)
    if not promo_data:
        # На случай гонки между is_promo_available_for_user и check_promo_code
        keyboard = [
            [InlineKeyboardButton("🔄 Попробовать другой", callback_data="retry_promo")],
            [InlineKeyboardButton("➡️ Продолжить без промокода", callback_data="skip_promo")],
            [InlineKeyboardButton("❌ Отменить", callback_data="cancel_payment")]
        ]
        await update.message.reply_text(
            f"❌ <b>Промокод недействителен</b>\n\n"
            f"Промокод <code>{promo_code}</code> не найден или уже использован.\n\n"
            "Попробуйте другой промокод или продолжите без скидки.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return PROMO_INPUT

    # Проверяем условия промокода
    duration_months = context.user_data.get('duration_months', 1)
    condition_ok, condition_msg = await promo_manager.check_promo_conditions(
        promo_data, user_id, duration_months
    )
    if not condition_ok:
        keyboard = [
            [InlineKeyboardButton("🔄 Попробовать другой", callback_data="retry_promo")],
            [InlineKeyboardButton("➡️ Продолжить без промокода", callback_data="skip_promo")],
            [InlineKeyboardButton("❌ Отменить", callback_data="cancel_payment")]
        ]
        await update.message.reply_text(
            f"❌ <b>Промокод нельзя применить</b>\n\n{condition_msg}\n\n"
            "Попробуйте другой промокод или продолжите без скидки.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return PROMO_INPUT
    
    # Промокод валиден - рассчитываем скидку
    base_price = context.user_data.get('total_price', 0)
    final_price, discount_amount = promo_manager.calculate_discount(base_price, promo_data)
    
    # Сохраняем данные промокода в контексте
    context.user_data['promo_code'] = promo_code
    context.user_data['promo_discount'] = discount_amount
    context.user_data['original_price'] = base_price
    context.user_data['total_price'] = final_price  # Обновляем цену со скидкой
    context.user_data['promo_data'] = promo_data
    
    # Формируем текст с информацией о скидке
    if promo_data['discount_percent'] > 0:
        discount_text = f"{promo_data['discount_percent']}%"
    else:
        discount_text = f"{promo_data['discount_amount']} ₽"
    
    plan_name = context.user_data.get('plan_name', 'Подписка')
    duration = context.user_data.get('duration_months', 1)
    
    text = f"""✅ <b>Промокод применен!</b>

🎁 Промокод: <code>{promo_code}</code>
💸 Скидка: <b>{discount_text}</b>

📦 План: <b>{plan_name}</b>
⏱ Срок: <b>{duration} мес.</b>

💰 Стоимость: <s>{base_price} ₽</s>
🎯 Со скидкой: <b>{final_price} ₽</b>
📉 Ваша выгода: <b>{discount_amount} ₽</b>

Для продолжения введите ваш email:"""
    
    keyboard = [
        [InlineKeyboardButton("❌ Отменить", callback_data="cancel_payment")]
    ]
    
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    # ВАЖНО: НЕ применяем промокод здесь!
    # Промокод будет применен ТОЛЬКО после успешной оплаты/активации
    # в момент вызова activate_subscription()

    # Переходим к вводу email
    from .handlers import ENTERING_EMAIL
    return ENTERING_EMAIL


@safe_handler()
async def skip_promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пропускает ввод промокода и переходит к email."""
    query = update.callback_query
    await query.answer()
    
    # Очищаем данные промокода если были
    context.user_data.pop('promo_code', None)
    context.user_data.pop('promo_discount', None)
    context.user_data.pop('promo_data', None)
    
    # Переходим к запросу email
    from .handlers import request_email
    return await request_email(update, context)


@safe_handler()
async def retry_promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Повторный ввод промокода."""
    query = update.callback_query
    await query.answer()
    
    # Показываем экран ввода промокода снова
    return await show_promo_input(update, context)


async def init_promo_tables():
    """Создает таблицы для промокодов если их нет."""
    async with aiosqlite.connect(DATABASE_FILE) as conn:
        # Таблица промокодов
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS promo_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                discount_percent INTEGER DEFAULT 0,
                discount_amount INTEGER DEFAULT 0,
                usage_limit INTEGER,
                used_count INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT 1,
                first_purchase_only BOOLEAN DEFAULT 0,
                min_duration_months INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Миграция: добавляем новые колонки для условий, если их нет
        cursor = await conn.execute("PRAGMA table_info(promo_codes)")
        columns = {col[1] for col in await cursor.fetchall()}

        if 'first_purchase_only' not in columns:
            await conn.execute(
                "ALTER TABLE promo_codes ADD COLUMN first_purchase_only BOOLEAN DEFAULT 0"
            )
            logger.info("Added first_purchase_only column to promo_codes")

        if 'min_duration_months' not in columns:
            await conn.execute(
                "ALTER TABLE promo_codes ADD COLUMN min_duration_months INTEGER DEFAULT 0"
            )
            logger.info("Added min_duration_months column to promo_codes")

        # Таблица логов использования промокодов
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS promo_usage_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                promo_code TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                order_id TEXT,
                discount_applied INTEGER,
                used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (promo_code) REFERENCES promo_codes(code)
            )
        """)

        # Уникальный индекс: один промокод — одно использование на пользователя
        await conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_promo_usage_unique
            ON promo_usage_log(promo_code, user_id)
        """)

        # Индексы для оптимизации
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_promo_code
            ON promo_codes(code, is_active)
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_promo_usage_user
            ON promo_usage_log(user_id, used_at)
        """)

        await conn.commit()
        logger.info("Promo code tables initialized")