"""
Сервис для работы с учителями.
"""

from __future__ import annotations  # Python 3.8 compatibility

import secrets
import string
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, List
import aiosqlite

from core.config import DATABASE_FILE
from ..models import TeacherProfile, TeacherStudentRelationship, RelationshipStatus
from ..utils.datetime_utils import utc_now, ensure_timezone_aware, parse_datetime_safe

logger = logging.getLogger(__name__)


def _safe_json_loads(json_str: str, default=None):
    """Безопасно парсит JSON с fallback на default значение."""
    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        logger.warning(f"Ошибка парсинга JSON: {e}, используем default значение")
        return default


def generate_teacher_code() -> str:
    """Генерирует уникальный код учителя формата TEACH-XXXXXX"""
    # 6 символов: буквы и цифры
    code_part = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
    return f"TEACH-{code_part}"


async def create_teacher_profile(
    user_id: int,
    display_name: str,
    subscription_tier: str = 'teacher_free',
    db_connection: Optional[aiosqlite.Connection] = None
) -> TeacherProfile:
    """
    Создает профиль учителя с защитой от database lock.

    ИСПРАВЛЕНО: Добавлена поддержка внешнего соединения для предотвращения
    множественных соединений с БД и database lock.

    Args:
        user_id: ID пользователя Telegram
        display_name: Отображаемое имя учителя
        subscription_tier: Уровень подписки (по умолчанию teacher_free)
        db_connection: Опциональное существующее соединение с БД для использования в транзакции

    Returns:
        TeacherProfile
    """
    try:
        # ИСПРАВЛЕНО: Используем переданное соединение или создаем новое с увеличенным timeout
        if db_connection is not None:
            # Используем переданное соединение (в рамках транзакции)
            db = db_connection
            should_commit = False  # Не коммитим - это делает внешняя транзакция
        else:
            # Создаем новое соединение с увеличенным timeout для предотвращения lock
            db = await aiosqlite.connect(DATABASE_FILE, timeout=30.0)
            should_commit = True

        try:
            # ИСПРАВЛЕНО: Начинаем эксклюзивную транзакцию для предотвращения race conditions
            if should_commit:
                await db.execute("BEGIN EXCLUSIVE")

            # Генерируем уникальный код
            teacher_code = generate_teacher_code()

            # Проверяем уникальность кода (на случай коллизии)
            while True:
                cursor = await db.execute(
                    "SELECT teacher_code FROM teacher_profiles WHERE teacher_code = ?",
                    (teacher_code,)
                )
                if not await cursor.fetchone():
                    break
                teacher_code = generate_teacher_code()

            # Добавляем роль teacher
            await db.execute(
                "INSERT OR IGNORE INTO user_roles (user_id, role) VALUES (?, 'teacher')",
                (user_id,)
            )

            # Создаем профиль учителя
            now = utc_now()  # ИСПРАВЛЕНО: используем timezone-aware datetime
            feedback_settings_json = json.dumps({})

            # Для teacher_free автоматически активируем подписку на 100 лет
            if subscription_tier == 'teacher_free':
                has_active = True
                expires = now + timedelta(days=36500)  # ~100 лет
            else:
                has_active = False
                expires = None

            await db.execute("""
                INSERT INTO teacher_profiles
                (user_id, teacher_code, display_name, subscription_tier,
                 has_active_subscription, subscription_expires, created_at, feedback_settings)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_id, teacher_code, display_name, subscription_tier,
                  has_active, expires.isoformat() if expires else None, now.isoformat(), feedback_settings_json))

            # Коммитим только если создали свое соединение
            if should_commit:
                await db.commit()

            profile = TeacherProfile(
                user_id=user_id,
                teacher_code=teacher_code,
                display_name=display_name,
                has_active_subscription=has_active,
                subscription_expires=expires,
                subscription_tier=subscription_tier,
                created_at=now,
                feedback_settings={}
            )

            logger.info(f"Создан профиль учителя для user_id={user_id}, код={teacher_code}, тариф={subscription_tier}")
            return profile

        except Exception as e:
            # Откатываем транзакцию только если создали свое соединение
            if should_commit:
                await db.rollback()
            raise

        finally:
            # Закрываем соединение только если создали свое
            if should_commit and db:
                await db.close()

    except Exception as e:
        logger.error(f"Ошибка при создании профиля учителя: {e}")
        raise


async def get_teacher_profile(user_id: int) -> Optional[TeacherProfile]:
    """
    Получает профиль учителя по user_id.

    Args:
        user_id: ID пользователя Telegram

    Returns:
        TeacherProfile или None
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT user_id, teacher_code, display_name, has_active_subscription,
                       subscription_expires, subscription_tier, created_at, feedback_settings
                FROM teacher_profiles
                WHERE user_id = ?
            """, (user_id,))

            row = await cursor.fetchone()
            if not row:
                return None

            return TeacherProfile(
                user_id=row['user_id'],
                teacher_code=row['teacher_code'],
                display_name=row['display_name'],
                has_active_subscription=bool(row['has_active_subscription']),
                subscription_expires=parse_datetime_safe(row['subscription_expires']),  # ИСПРАВЛЕНО: безопасный парсинг
                subscription_tier=row['subscription_tier'],
                created_at=parse_datetime_safe(row['created_at']) or utc_now(),  # ИСПРАВЛЕНО: fallback на текущее время
                feedback_settings=_safe_json_loads(row['feedback_settings'], {}) if row['feedback_settings'] else {}
            )

    except Exception as e:
        logger.error(f"Ошибка при получении профиля учителя: {e}")
        return None


async def get_teacher_by_code(teacher_code: str) -> Optional[TeacherProfile]:
    """
    Находит учителя по коду.

    Args:
        teacher_code: Код учителя (например, TEACH-ABC123)

    Returns:
        TeacherProfile или None
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT user_id, teacher_code, display_name, has_active_subscription,
                       subscription_expires, subscription_tier, created_at, feedback_settings
                FROM teacher_profiles
                WHERE teacher_code = ?
            """, (teacher_code,))

            row = await cursor.fetchone()
            if not row:
                return None

            return TeacherProfile(
                user_id=row['user_id'],
                teacher_code=row['teacher_code'],
                display_name=row['display_name'],
                has_active_subscription=bool(row['has_active_subscription']),
                subscription_expires=parse_datetime_safe(row['subscription_expires']),  # ИСПРАВЛЕНО: безопасный парсинг
                subscription_tier=row['subscription_tier'],
                created_at=parse_datetime_safe(row['created_at']) or utc_now(),  # ИСПРАВЛЕНО: fallback на текущее время
                feedback_settings=_safe_json_loads(row['feedback_settings'], {}) if row['feedback_settings'] else {}
            )

    except Exception as e:
        logger.error(f"Ошибка при поиске учителя по коду: {e}")
        return None


async def add_student_to_teacher(
    teacher_id: int,
    student_id: int
) -> Optional[TeacherStudentRelationship]:
    """
    Добавляет ученика к учителю с защитой от race conditions.

    ИСПРАВЛЕНО: Использует транзакцию с EXCLUSIVE блокировкой для
    атомарной проверки лимита и вставки записи.

    Args:
        teacher_id: ID учителя
        student_id: ID ученика

    Returns:
        TeacherStudentRelationship или None (если превышен лимит)
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # ИСПРАВЛЕНО: Начинаем эксклюзивную транзакцию для предотвращения race conditions
            await db.execute("BEGIN EXCLUSIVE")

            try:
                # Проверяем профиль учителя
                db.row_factory = aiosqlite.Row
                cursor = await db.execute("""
                    SELECT user_id, subscription_tier, has_active_subscription,
                           subscription_expires
                    FROM teacher_profiles
                    WHERE user_id = ?
                """, (teacher_id,))

                profile_row = await cursor.fetchone()
                if not profile_row:
                    await db.rollback()
                    logger.warning(f"Профиль учителя {teacher_id} не найден")
                    return None

                # Проверяем активность подписки
                has_active = bool(profile_row['has_active_subscription'])
                expires_str = profile_row['subscription_expires']

                if not has_active:
                    await db.rollback()
                    logger.warning(f"У учителя {teacher_id} нет активной подписки")
                    return None

                # Проверяем дату истечения внутри транзакции
                if expires_str:
                    expires_dt = parse_datetime_safe(expires_str)
                    if expires_dt and ensure_timezone_aware(expires_dt) < utc_now():
                        await db.rollback()
                        logger.warning(f"Подписка учителя {teacher_id} истекла")
                        return None

                # Получаем максимальное количество учеников для тарифа
                from payment.config import get_teacher_max_students
                subscription_tier = profile_row['subscription_tier']
                max_students = get_teacher_max_students(subscription_tier)

                # Проверяем текущее количество активных учеников (внутри транзакции)
                if max_students != -1:  # Если не безлимит
                    cursor = await db.execute("""
                        SELECT COUNT(*) as count
                        FROM teacher_student_relationships
                        WHERE teacher_id = ? AND status = 'active'
                    """, (teacher_id,))
                    row = await cursor.fetchone()
                    current_count = row['count'] if row else 0

                    if current_count >= max_students:
                        await db.rollback()
                        logger.warning(f"Учитель {teacher_id} достиг лимита учеников ({max_students})")
                        return None

                # Все проверки пройдены - добавляем ученика
                # Добавляем роль student ученику
                await db.execute(
                    "INSERT OR IGNORE INTO user_roles (user_id, role) VALUES (?, 'student')",
                    (student_id,)
                )

                # Создаем связь учитель-ученик
                now = utc_now()
                cursor = await db.execute("""
                    INSERT INTO teacher_student_relationships
                    (teacher_id, student_id, invited_at, status)
                    VALUES (?, ?, ?, 'active')
                """, (teacher_id, student_id, now.isoformat()))

                # Commit транзакции
                await db.commit()

                relationship = TeacherStudentRelationship(
                    id=cursor.lastrowid,
                    teacher_id=teacher_id,
                    student_id=student_id,
                    invited_at=now,
                    status=RelationshipStatus.ACTIVE
                )

                logger.info(f"Ученик {student_id} добавлен к учителю {teacher_id} (транзакция успешна)")
                return relationship

            except aiosqlite.IntegrityError:
                # Связь уже существует - rollback
                await db.rollback()
                logger.warning(f"Связь учитель {teacher_id} - ученик {student_id} уже существует")
                return None
            except Exception as e:
                # Любая другая ошибка - rollback
                await db.rollback()
                raise

    except Exception as e:
        logger.error(f"Ошибка при добавлении ученика к учителю: {e}")
        return None


async def get_teacher_students(teacher_id: int) -> List[int]:
    """
    Получает список ID учеников учителя.

    Args:
        teacher_id: ID учителя

    Returns:
        Список user_id учеников
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute("""
                SELECT student_id
                FROM teacher_student_relationships
                WHERE teacher_id = ? AND status = 'active'
            """, (teacher_id,))

            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    except Exception as e:
        logger.error(f"Ошибка при получении списка учеников: {e}")
        return []


async def get_student_teachers(student_id: int) -> List[int]:
    """
    Получает список ID учителей ученика.

    Args:
        student_id: ID ученика

    Returns:
        Список user_id учителей
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute("""
                SELECT teacher_id
                FROM teacher_student_relationships
                WHERE student_id = ? AND status = 'active'
            """, (student_id,))

            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    except Exception as e:
        logger.error(f"Ошибка при получении списка учителей: {e}")
        return []


async def can_add_student(teacher_id: int) -> tuple[bool, str]:
    """
    Проверяет, может ли учитель добавить еще одного ученика.

    Args:
        teacher_id: ID учителя

    Returns:
        Кортеж (bool, str): (можно добавить, сообщение-причина)
    """
    profile = await get_teacher_profile(teacher_id)
    if not profile:
        return False, "Профиль учителя не найден"

    # ИСПРАВЛЕНО: Проверяем дату истечения подписки с правильной timezone обработкой
    if profile.subscription_expires:
        expires_dt = ensure_timezone_aware(profile.subscription_expires)
        now = utc_now()

        if expires_dt < now:
            return False, "Подписка учителя истекла"

    if not profile.has_active_subscription:
        return False, "У учителя нет активной подписки"

    max_students = profile.max_students
    if max_students == -1:  # Безлимит
        return True, ""

    current_students = await get_teacher_students(teacher_id)
    current_count = len(current_students)

    if current_count >= max_students:
        return False, f"Достигнут лимит учеников ({max_students})"

    return True, ""


async def is_student_connected(teacher_id: int, student_id: int) -> bool:
    """
    Проверяет, подключен ли ученик к учителю.

    Args:
        teacher_id: ID учителя
        student_id: ID ученика

    Returns:
        True если связь существует и активна
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute("""
                SELECT id FROM teacher_student_relationships
                WHERE teacher_id = ? AND student_id = ? AND status = 'active'
            """, (teacher_id, student_id))

            row = await cursor.fetchone()
            return row is not None

    except Exception as e:
        logger.error(f"Ошибка при проверке связи учитель-ученик: {e}")
        return False


async def remove_student(teacher_id: int, student_id: int) -> bool:
    """
    Удаляет ученика от учителя (меняет статус на 'inactive').
    Слот ученика освобождается и может быть использован для другого ученика.

    Args:
        teacher_id: ID учителя
        student_id: ID ученика

    Returns:
        True если успешно удалено
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute("""
                UPDATE teacher_student_relationships
                SET status = 'inactive'
                WHERE teacher_id = ? AND student_id = ?
            """, (teacher_id, student_id))
            await db.commit()

            logger.info(f"Ученик {student_id} удалён от учителя {teacher_id}")
            return True

    except Exception as e:
        logger.error(f"Ошибка при удалении ученика: {e}")
        return False


async def block_student(teacher_id: int, student_id: int) -> bool:
    """
    Блокирует ученика (меняет статус на 'blocked').
    Ученик не сможет повторно подключиться к учителю.

    Args:
        teacher_id: ID учителя
        student_id: ID ученика

    Returns:
        True если успешно заблокирован
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute("""
                UPDATE teacher_student_relationships
                SET status = 'blocked'
                WHERE teacher_id = ? AND student_id = ?
            """, (teacher_id, student_id))
            await db.commit()

            logger.info(f"Ученик {student_id} заблокирован учителем {teacher_id}")
            return True

    except Exception as e:
        logger.error(f"Ошибка при блокировке ученика: {e}")
        return False


async def has_teacher_access(user_id: int) -> bool:
    """
    Единая функция проверки доступа учителя к функциям.

    Проверяет:
    1. Существование профиля учителя
    2. Активность подписки
    3. Дату истечения подписки

    Args:
        user_id: ID учителя

    Returns:
        True если учитель имеет доступ к функциям
    """
    profile = await get_teacher_profile(user_id)
    if not profile:
        return False

    if not profile.has_active_subscription:
        return False

    # ИСПРАВЛЕНО: Проверяем дату истечения с правильной timezone обработкой
    if profile.subscription_expires:
        expires_dt = ensure_timezone_aware(profile.subscription_expires)
        now = utc_now()

        if expires_dt < now:
            return False

    return True


async def validate_teacher_subscription_integrity(teacher_id: int) -> tuple[bool, Optional[str]]:
    """
    Проверяет согласованность данных между teacher_profiles и module_subscriptions.

    Проверяет:
    1. Соответствие флага has_active_subscription между таблицами
    2. Соответствие даты истечения подписки
    3. Наличие активной подписки в module_subscriptions для учительского плана

    Args:
        teacher_id: ID учителя

    Returns:
        Кортеж (bool, Optional[str]): (данные согласованы, описание проблемы)
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT
                    tp.has_active_subscription as tp_active,
                    tp.subscription_expires as tp_expires,
                    tp.subscription_tier,
                    ms.is_active as ms_active,
                    ms.expires_at as ms_expires,
                    ms.plan_id
                FROM teacher_profiles tp
                LEFT JOIN module_subscriptions ms
                    ON tp.user_id = ms.user_id
                    AND ms.plan_id IN ('teacher_basic', 'teacher_standard', 'teacher_premium')
                WHERE tp.user_id = ?
                ORDER BY ms.expires_at DESC
                LIMIT 1
            """, (teacher_id,))

            row = await cursor.fetchone()

            if not row:
                return False, f"Профиль учителя {teacher_id} не найден"

            # Проверяем соответствие активности
            tp_active = bool(row['tp_active'])
            ms_active = bool(row['ms_active']) if row['ms_active'] is not None else False

            if tp_active != ms_active:
                return False, (
                    f"Несоответствие активности: teacher_profiles.has_active_subscription={tp_active}, "
                    f"module_subscriptions.is_active={ms_active}"
                )

            # ИСПРАВЛЕНО: Если обе таблицы указывают на активную подписку, проверяем даты
            if tp_active and ms_active:
                tp_expires = parse_datetime_safe(row['tp_expires'])
                ms_expires = parse_datetime_safe(row['ms_expires'])

                if tp_expires and ms_expires:
                    # Оба datetime уже timezone-aware после parse_datetime_safe
                    # Допускаем разницу в 1 минуту из-за возможных задержек записи
                    time_diff = abs((tp_expires - ms_expires).total_seconds())
                    if time_diff > 60:
                        return False, (
                            f"Несоответствие дат истечения: "
                            f"teacher_profiles={tp_expires.strftime('%Y-%m-%d %H:%M:%S')}, "
                            f"module_subscriptions={ms_expires.strftime('%Y-%m-%d %H:%M:%S')}"
                        )

                # Проверяем, что plan_id соответствует subscription_tier
                if row['plan_id'] and row['subscription_tier']:
                    if row['plan_id'] != row['subscription_tier']:
                        return False, (
                            f"Несоответствие тарифов: "
                            f"teacher_profiles.subscription_tier={row['subscription_tier']}, "
                            f"module_subscriptions.plan_id={row['plan_id']}"
                        )

            return True, None

    except Exception as e:
        logger.error(f"Ошибка при проверке целостности данных учителя {teacher_id}: {e}")
        return False, f"Ошибка проверки: {str(e)}"


async def get_users_display_names(user_ids: List[int]) -> dict[int, str]:
    """
    Получает отображаемые имена пользователей по их ID.

    Args:
        user_ids: Список ID пользователей

    Returns:
        Словарь {user_id: display_name}, где display_name формируется как:
        - "Имя (@username)" если есть и имя и username
        - "@username" если есть только username
        - "Имя" если есть только имя
        - "ID: {user_id}" если нет ни username ни имени
    """
    if not user_ids:
        return {}

    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            # Формируем SQL запрос с множественным IN
            placeholders = ','.join('?' * len(user_ids))
            query = f"""
                SELECT user_id, username, first_name, last_name
                FROM users
                WHERE user_id IN ({placeholders})
            """

            cursor = await db.execute(query, user_ids)
            rows = await cursor.fetchall()

            result = {}
            for row in rows:
                user_id = row['user_id']
                username = row['username']
                first_name = row['first_name']
                last_name = row['last_name']

                # Формируем отображаемое имя
                if first_name and username:
                    display_name = f"{first_name} (@{username})"
                elif username:
                    display_name = f"@{username}"
                elif first_name:
                    full_name = f"{first_name} {last_name}" if last_name else first_name
                    display_name = full_name
                else:
                    display_name = f"ID: {user_id}"

                result[user_id] = display_name

            # Для пользователей, которых нет в БД, используем ID
            for user_id in user_ids:
                if user_id not in result:
                    result[user_id] = f"ID: {user_id}"

            return result

    except Exception as e:
        logger.error(f"Ошибка при получении имен пользователей: {e}")
        # Возвращаем fallback с ID
        return {user_id: f"ID: {user_id}" for user_id in user_ids}
