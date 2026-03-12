"""
Сервис для работы с подарочными подписками и промокодами.
"""

from __future__ import annotations  # Python 3.8 compatibility

import secrets
import string
import logging
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import aiosqlite

from core.config import DATABASE_FILE
from ..models import GiftedSubscription, PromoCode
from ..utils.datetime_utils import utc_now, ensure_timezone_aware

logger = logging.getLogger(__name__)


# ==================== ПРЯМОЕ ДАРЕНИЕ ПОДПИСОК ====================

async def gift_subscription(
    gifter_id: int,
    recipient_id: int,
    duration_days: int
) -> Optional[GiftedSubscription]:
    """
    Дарит подписку конкретному пользователю.

    Args:
        gifter_id: ID того, кто дарит (может быть учитель или любой пользователь)
        recipient_id: ID получателя
        duration_days: Длительность подписки в днях

    Returns:
        GiftedSubscription или None в случае ошибки
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            now = utc_now()  # ИСПРАВЛЕНО: timezone-aware datetime
            expires_at = now + timedelta(days=duration_days)

            cursor = await db.execute("""
                INSERT INTO gifted_subscriptions
                (gifter_id, recipient_id, duration_days, activated_at, expires_at, status)
                VALUES (?, ?, ?, ?, ?, 'active')
            """, (gifter_id, recipient_id, duration_days, now, expires_at))

            await db.commit()

            gift = GiftedSubscription(
                id=cursor.lastrowid,
                gifter_id=gifter_id,
                recipient_id=recipient_id,
                duration_days=duration_days,
                activated_at=now,
                expires_at=expires_at,
                status='active'
            )

            logger.info(f"Подарена подписка: {gifter_id} -> {recipient_id}, {duration_days} дней")
            return gift

    except Exception as e:
        logger.error(f"Ошибка при дарении подписки: {e}")
        return None


async def get_gifted_subscriptions_by_gifter(gifter_id: int) -> List[GiftedSubscription]:
    """
    Получает список всех подарков от конкретного пользователя.

    Args:
        gifter_id: ID дарителя

    Returns:
        Список GiftedSubscription
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT id, gifter_id, recipient_id, duration_days,
                       activated_at, expires_at, status
                FROM gifted_subscriptions
                WHERE gifter_id = ?
                ORDER BY activated_at DESC
            """, (gifter_id,))

            rows = await cursor.fetchall()
            gifts = []

            for row in rows:
                gifts.append(GiftedSubscription(
                    id=row['id'],
                    gifter_id=row['gifter_id'],
                    recipient_id=row['recipient_id'],
                    duration_days=row['duration_days'],
                    activated_at=datetime.fromisoformat(row['activated_at']),
                    expires_at=datetime.fromisoformat(row['expires_at']),
                    status=row['status']
                ))

            return gifts

    except Exception as e:
        logger.error(f"Ошибка при получении подарков: {e}")
        return []


async def get_active_gifted_subscription(recipient_id: int) -> Optional[GiftedSubscription]:
    """
    Получает активную подаренную подписку для пользователя.

    Args:
        recipient_id: ID получателя

    Returns:
        GiftedSubscription или None
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT id, gifter_id, recipient_id, duration_days,
                       activated_at, expires_at, status
                FROM gifted_subscriptions
                WHERE recipient_id = ? AND status = 'active'
                  AND expires_at > ?
                ORDER BY expires_at DESC
                LIMIT 1
            """, (recipient_id, utc_now().isoformat()))

            row = await cursor.fetchone()
            if not row:
                return None

            return GiftedSubscription(
                id=row['id'],
                gifter_id=row['gifter_id'],
                recipient_id=row['recipient_id'],
                duration_days=row['duration_days'],
                activated_at=datetime.fromisoformat(row['activated_at']),
                expires_at=datetime.fromisoformat(row['expires_at']),
                status=row['status']
            )

    except Exception as e:
        logger.error(f"Ошибка при получении активной подаренной подписки: {e}")
        return None


async def has_active_gifted_subscription(recipient_id: int) -> bool:
    """
    Проверяет, есть ли у пользователя активная подаренная подписка.

    Args:
        recipient_id: ID пользователя

    Returns:
        True если есть активная подаренная подписка
    """
    gift = await get_active_gifted_subscription(recipient_id)
    return gift is not None


# ==================== ПРОМОКОДЫ ====================

def generate_promo_code(length: int = 8) -> str:
    """
    Генерирует случайный промокод.

    Args:
        length: Длина кода

    Returns:
        Промокод формата GIFT-XXXXXXXX
    """
    code_part = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(length))
    return f"GIFT-{code_part}"


async def create_promo_code(
    creator_id: int,
    duration_days: int,
    max_uses: int,
    expires_at: Optional[datetime] = None
) -> Optional[PromoCode]:
    """
    Создает промокод для подписки.

    Для создания промокода учитель должен иметь тариф teacher_premium
    (или быть администратором).

    Args:
        creator_id: ID создателя (обычно учитель)
        duration_days: На сколько дней дается подписка
        max_uses: Максимальное количество использований
        expires_at: Дата истечения промокода (опционально)

    Returns:
        PromoCode или None

    Raises:
        PermissionError: если у учителя нет прав на создание промокодов
    """
    try:
        # Проверяем права учителя на уровне сервиса
        is_admin = False
        try:
            from core.config import ADMIN_IDS
            is_admin = creator_id in ADMIN_IDS
        except ImportError:
            pass

        if not is_admin:
            async with aiosqlite.connect(DATABASE_FILE) as db:
                cursor = await db.execute(
                    "SELECT subscription_tier FROM teacher_profiles WHERE user_id = ?",
                    (creator_id,)
                )
                row = await cursor.fetchone()
                if not row:
                    logger.warning(f"Teacher {creator_id} not found when creating promo code")
                    raise PermissionError("Профиль учителя не найден")
                tier = row[0]
                if tier != 'teacher_premium':
                    logger.warning(
                        f"Teacher {creator_id} with tier '{tier}' tried to create promo code"
                    )
                    raise PermissionError(
                        "Создание промокодов доступно только на тарифе Teacher Premium"
                    )

        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Генерируем уникальный код
            code = generate_promo_code()

            # Проверяем уникальность
            while True:
                cursor = await db.execute(
                    "SELECT code FROM gift_promo_codes WHERE code = ?",
                    (code,)
                )
                if not await cursor.fetchone():
                    break
                code = generate_promo_code()

            now = utc_now()

            await db.execute("""
                INSERT INTO gift_promo_codes
                (code, creator_id, duration_days, max_uses, used_count, created_at, expires_at, status)
                VALUES (?, ?, ?, ?, 0, ?, ?, 'active')
            """, (code, creator_id, duration_days, max_uses, now, expires_at))

            await db.commit()

            promo = PromoCode(
                code=code,
                creator_id=creator_id,
                duration_days=duration_days,
                max_uses=max_uses,
                used_count=0,
                created_at=now,
                expires_at=expires_at,
                status='active'
            )

            logger.info(f"Создан промокод {code}: {duration_days} дней, {max_uses} использований")
            return promo

    except Exception as e:
        logger.error(f"Ошибка при создании промокода: {e}")
        return None


async def get_promo_code(code: str) -> Optional[PromoCode]:
    """
    Получает информацию о промокоде.

    Args:
        code: Код промокода

    Returns:
        PromoCode или None
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT code, creator_id, duration_days, max_uses, used_count,
                       created_at, expires_at, status
                FROM gift_promo_codes
                WHERE code = ?
            """, (code,))

            row = await cursor.fetchone()
            if not row:
                return None

            return PromoCode(
                code=row['code'],
                creator_id=row['creator_id'],
                duration_days=row['duration_days'],
                max_uses=row['max_uses'],
                used_count=row['used_count'],
                created_at=datetime.fromisoformat(row['created_at']),
                expires_at=datetime.fromisoformat(row['expires_at']) if row['expires_at'] else None,
                status=row['status']
            )

    except Exception as e:
        logger.error(f"Ошибка при получении промокода: {e}")
        return None


async def validate_promo_code(code: str, user_id: int) -> tuple[bool, str]:
    """
    Проверяет валидность промокода для пользователя.

    Args:
        code: Код промокода
        user_id: ID пользователя

    Returns:
        (is_valid, error_message)
    """
    promo = await get_promo_code(code)

    if not promo:
        return False, "Промокод не найден"

    if promo.status != 'active':
        return False, "Промокод неактивен"

    # Проверяем срок действия
    if promo.expires_at and ensure_timezone_aware(promo.expires_at) < utc_now():
        return False, "Срок действия промокода истёк"

    # Проверяем лимит использований
    if promo.used_count >= promo.max_uses:
        return False, "Промокод уже использован максимальное количество раз"

    # Проверяем, не использовал ли пользователь этот промокод ранее
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute("""
                SELECT COUNT(*) FROM promo_code_usage
                WHERE promo_code = ? AND student_id = ?
            """, (code, user_id))

            count = (await cursor.fetchone())[0]
            if count > 0:
                return False, "Вы уже использовали этот промокод"

    except Exception as e:
        logger.error(f"Ошибка при проверке использования промокода: {e}")
        return False, "Ошибка при проверке промокода"

    return True, ""


async def activate_promo_code(code: str, user_id: int) -> Optional[GiftedSubscription]:
    """
    Активирует промокод для пользователя.

    Args:
        code: Код промокода
        user_id: ID пользователя

    Returns:
        GiftedSubscription или None
    """
    is_valid, error_message = await validate_promo_code(code, user_id)

    if not is_valid:
        logger.warning(f"Попытка активации невалидного промокода {code}: {error_message}")
        return None

    promo = await get_promo_code(code)
    if not promo:
        return None

    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Записываем использование промокода
            await db.execute("""
                INSERT INTO promo_code_usage (promo_code, student_id, used_at)
                VALUES (?, ?, ?)
            """, (code, user_id, utc_now().isoformat()))

            # Увеличиваем счётчик использований
            await db.execute("""
                UPDATE gift_promo_codes
                SET used_count = used_count + 1
                WHERE code = ?
            """, (code,))

            # Проверяем, не исчерпан ли промокод
            await db.execute("""
                UPDATE gift_promo_codes
                SET status = 'exhausted'
                WHERE code = ? AND used_count >= max_uses
            """, (code,))

            await db.commit()

        # Создаем подаренную подписку
        gift = await gift_subscription(
            gifter_id=promo.creator_id,
            recipient_id=user_id,
            duration_days=promo.duration_days
        )

        logger.info(f"Промокод {code} активирован пользователем {user_id}")
        return gift

    except Exception as e:
        logger.error(f"Ошибка при активации промокода: {e}")
        return None


async def get_creator_promo_codes(creator_id: int) -> List[PromoCode]:
    """
    Получает список всех промокодов, созданных пользователем.

    Args:
        creator_id: ID создателя

    Returns:
        Список PromoCode
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT code, creator_id, duration_days, max_uses, used_count,
                       created_at, expires_at, status
                FROM gift_promo_codes
                WHERE creator_id = ?
                ORDER BY created_at DESC
            """, (creator_id,))

            rows = await cursor.fetchall()
            promos = []

            for row in rows:
                promos.append(PromoCode(
                    code=row['code'],
                    creator_id=row['creator_id'],
                    duration_days=row['duration_days'],
                    max_uses=row['max_uses'],
                    used_count=row['used_count'],
                    created_at=datetime.fromisoformat(row['created_at']),
                    expires_at=datetime.fromisoformat(row['expires_at']) if row['expires_at'] else None,
                    status=row['status']
                ))

            return promos

    except Exception as e:
        logger.error(f"Ошибка при получении промокодов: {e}")
        return []


async def deactivate_promo_code(code: str) -> bool:
    """
    Деактивирует промокод.

    Args:
        code: Код промокода

    Returns:
        True если успешно
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute("""
                UPDATE gift_promo_codes
                SET status = 'expired'
                WHERE code = ?
            """, (code,))

            await db.commit()

        logger.info(f"Промокод {code} деактивирован")
        return True

    except Exception as e:
        logger.error(f"Ошибка при деактивации промокода: {e}")
        return False

# Псевдоним для совместимости с teacher_handlers
async def get_teacher_promo_codes(teacher_id: int) -> List[PromoCode]:
    """
    Псевдоним для get_creator_promo_codes.
    Получает промокоды учителя.
    """
    return await get_creator_promo_codes(teacher_id)
