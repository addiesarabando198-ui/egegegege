"""
Сервис для быстрой проверки работ учениками.

Предоставляет функционал для онлайн-школ и учителей для проверки
работ, которые не были назначены через бота.
"""

import logging
import json
import aiosqlite
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple, Any
from collections import defaultdict

from core.db import DATABASE_FILE
from ..models import (
    QuickCheck, QuickCheckTemplate, QuickCheckQuota,
    QuickCheckTaskType
)
from ..utils.datetime_utils import utc_now, parse_datetime_safe

logger = logging.getLogger(__name__)


def _safe_json_loads(json_str: str, default=None):
    """Безопасно парсит JSON с fallback на default значение."""
    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        logger.warning(f"Ошибка парсинга JSON: {e}, используем default значение")
        return default


# ============================================
# Работа с квотами
# ============================================

async def get_or_create_quota(teacher_id: int) -> Optional[QuickCheckQuota]:
    """
    Получает или создает квоту для учителя.
    При первом обращении создает квоту с дефолтными значениями.

    Args:
        teacher_id: ID учителя

    Returns:
        QuickCheckQuota или None при ошибке
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            # Проверяем существующую квоту
            cursor = await db.execute("""
                SELECT * FROM quick_check_quotas WHERE teacher_id = ?
            """, (teacher_id,))
            row = await cursor.fetchone()

            if row:
                return _row_to_quota(row)

            # Создаем новую квоту с дефолтными значениями
            # Лимит зависит от подписки учителя
            from .teacher_service import get_teacher_profile
            teacher = await get_teacher_profile(teacher_id)

            if not teacher:
                logger.error(f"Teacher {teacher_id} not found when creating quota")
                return None

            # Определяем лимит по тарифу
            monthly_limit = _get_monthly_limit_by_tier(teacher.subscription_tier)

            now = utc_now()
            period_end = now + timedelta(days=30)

            insert_cursor = await db.execute("""
                INSERT INTO quick_check_quotas (
                    teacher_id, monthly_limit, used_this_month,
                    current_period_start, current_period_end,
                    bonus_checks, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                teacher_id, monthly_limit, 0,
                now.isoformat(), period_end.isoformat(),
                0, now.isoformat()
            ))
            await db.commit()

            # Возвращаем созданную квоту
            return QuickCheckQuota(
                id=insert_cursor.lastrowid,
                teacher_id=teacher_id,
                monthly_limit=monthly_limit,
                used_this_month=0,
                current_period_start=now,
                current_period_end=period_end,
                bonus_checks=0,
                last_reset_at=None,
                updated_at=now
            )

    except Exception as e:
        logger.error(f"Error getting/creating quota for teacher {teacher_id}: {e}")
        return None


def _get_monthly_limit_by_tier(tier: str) -> int:
    """Возвращает месячный лимит проверок по тарифу"""
    limits = {
        'teacher_basic': 100,      # Базовый: 100 проверок
        'teacher_standard': 500,   # Стандарт: 500 проверок
        'teacher_premium': 2000,   # Премиум: 2000 проверок
    }
    return limits.get(tier, 50)  # По умолчанию 50


async def check_and_use_quota(teacher_id: int, count: int = 1) -> Tuple[bool, Optional[QuickCheckQuota]]:
    """
    Проверяет квоту и уменьшает ее при возможности.

    Вся работа выполняется внутри одного соединения и одной
    EXCLUSIVE-транзакции, чтобы избежать deadlock.

    Args:
        teacher_id: ID учителя
        count: Количество проверок для списания

    Returns:
        (success, quota) - успешность операции и текущая квота
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN EXCLUSIVE")

            try:
                # Читаем квоту внутри того же соединения (без отдельного connect)
                cursor = await db.execute(
                    "SELECT * FROM quick_check_quotas WHERE teacher_id = ?",
                    (teacher_id,)
                )
                row = await cursor.fetchone()

                if not row:
                    # Квоты нет — создаём внутри той же транзакции
                    from .teacher_service import get_teacher_profile
                    teacher = await get_teacher_profile(teacher_id)

                    if not teacher:
                        await db.rollback()
                        return False, None

                    monthly_limit = _get_monthly_limit_by_tier(teacher.subscription_tier)
                    now = utc_now()
                    period_end = now + timedelta(days=30)

                    insert_cursor = await db.execute("""
                        INSERT INTO quick_check_quotas (
                            teacher_id, monthly_limit, used_this_month,
                            current_period_start, current_period_end,
                            bonus_checks, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (
                        teacher_id, monthly_limit, 0,
                        now.isoformat(), period_end.isoformat(),
                        0, now.isoformat()
                    ))

                    quota = QuickCheckQuota(
                        id=insert_cursor.lastrowid,
                        teacher_id=teacher_id,
                        monthly_limit=monthly_limit,
                        used_this_month=0,
                        current_period_start=now,
                        current_period_end=period_end,
                        bonus_checks=0,
                        last_reset_at=None,
                        updated_at=now
                    )
                else:
                    quota = _row_to_quota(row)

                # Проверяем, не истек ли период
                now = utc_now()
                if now > quota.current_period_end:
                    await _reset_quota_period(db, teacher_id, quota)
                    quota.used_this_month = 0
                    quota.current_period_start = now
                    quota.current_period_end = now + timedelta(days=30)

                # Проверяем достаточно ли квоты
                if quota.used_this_month + count > quota.monthly_limit + quota.bonus_checks:
                    await db.rollback()
                    return False, quota

                # Списываем квоту
                await db.execute("""
                    UPDATE quick_check_quotas
                    SET used_this_month = used_this_month + ?,
                        updated_at = ?
                    WHERE teacher_id = ?
                """, (count, now.isoformat(), teacher_id))

                await db.commit()

                # Обновляем объект
                quota.used_this_month += count
                quota.updated_at = now

                return True, quota

            except Exception as e:
                await db.rollback()
                raise e

    except Exception as e:
        logger.error(f"Error checking/using quota for teacher {teacher_id}: {e}")
        return False, None


async def refund_quota(teacher_id: int, count: int = 1) -> bool:
    """
    Возвращает квоту (уменьшает used_this_month).

    Используется при ошибке AI-проверки для корректного возврата
    вместо добавления бонусных проверок.
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute("""
                UPDATE quick_check_quotas
                SET used_this_month = MAX(0, used_this_month - ?),
                    updated_at = ?
                WHERE teacher_id = ?
            """, (count, utc_now().isoformat(), teacher_id))
            await db.commit()
            return True
    except Exception as e:
        logger.error(f"Error refunding quota for teacher {teacher_id}: {e}")
        return False


async def _reset_quota_period(db: aiosqlite.Connection, teacher_id: int, old_quota: QuickCheckQuota):
    """Сбрасывает период квоты (внутренняя функция)"""
    now = utc_now()
    period_end = now + timedelta(days=30)

    await db.execute("""
        UPDATE quick_check_quotas
        SET used_this_month = 0,
            current_period_start = ?,
            current_period_end = ?,
            last_reset_at = ?,
            updated_at = ?
        WHERE teacher_id = ?
    """, (now.isoformat(), period_end.isoformat(),
          now.isoformat(), now.isoformat(), teacher_id))


async def add_bonus_checks(teacher_id: int, count: int) -> bool:
    """
    Добавляет бонусные проверки учителю.

    Args:
        teacher_id: ID учителя
        count: Количество бонусных проверок

    Returns:
        True при успехе
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            quota = await get_or_create_quota(teacher_id)
            if not quota:
                return False

            await db.execute("""
                UPDATE quick_check_quotas
                SET bonus_checks = bonus_checks + ?,
                    updated_at = ?
                WHERE teacher_id = ?
            """, (count, utc_now().isoformat(), teacher_id))
            await db.commit()

            logger.info(f"Added {count} bonus checks to teacher {teacher_id}")
            return True

    except Exception as e:
        logger.error(f"Error adding bonus checks to teacher {teacher_id}: {e}")
        return False


# ============================================
# Проверка работ
# ============================================

async def create_quick_check(
    teacher_id: int,
    task_type: QuickCheckTaskType,
    task_condition: str,
    student_answer: str,
    student_id: Optional[int] = None,
    ai_feedback: Optional[str] = None,
    is_correct: Optional[bool] = None,
    teacher_comment: Optional[str] = None,
    tags: Optional[List[str]] = None,
    template_name: Optional[str] = None
) -> Optional[QuickCheck]:
    """
    Создает запись быстрой проверки.

    Args:
        teacher_id: ID учителя
        task_type: Тип задания
        task_condition: Условие задания
        student_answer: Ответ ученика
        student_id: ID ученика (опционально)
        ai_feedback: Обратная связь от AI
        is_correct: Правильность ответа
        teacher_comment: Комментарий учителя
        tags: Теги для категоризации
        template_name: Название шаблона (если использовался)

    Returns:
        QuickCheck или None при ошибке
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            now = utc_now()
            tags_json = json.dumps(tags) if tags else None

            cursor = await db.execute("""
                INSERT INTO quick_checks (
                    teacher_id, task_type, task_condition, student_answer,
                    student_id, ai_feedback, is_correct, teacher_comment,
                    tags, template_name, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                teacher_id, task_type.value, task_condition, student_answer,
                student_id, ai_feedback, is_correct, teacher_comment,
                tags_json, template_name, now.isoformat()
            ))
            await db.commit()

            check_id = cursor.lastrowid

            logger.info(f"Created quick check {check_id} for teacher {teacher_id}")

            return QuickCheck(
                id=check_id,
                teacher_id=teacher_id,
                task_type=task_type,
                task_condition=task_condition,
                student_answer=student_answer,
                student_id=student_id,
                ai_feedback=ai_feedback,
                is_correct=is_correct,
                score=None,
                teacher_comment=teacher_comment,
                tags=tags,
                template_name=template_name,
                created_at=now,
                updated_at=None
            )

    except Exception as e:
        logger.error(f"Error creating quick check: {e}")
        return None


async def get_teacher_quick_checks(
    teacher_id: int,
    limit: int = 50,
    offset: int = 0,
    task_type: Optional[QuickCheckTaskType] = None
) -> List[QuickCheck]:
    """
    Получает историю быстрых проверок учителя.

    Args:
        teacher_id: ID учителя
        limit: Максимальное количество записей
        offset: Смещение для пагинации
        task_type: Фильтр по типу задания

    Returns:
        Список QuickCheck
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            if task_type:
                cursor = await db.execute("""
                    SELECT * FROM quick_checks
                    WHERE teacher_id = ? AND task_type = ?
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                """, (teacher_id, task_type.value, limit, offset))
            else:
                cursor = await db.execute("""
                    SELECT * FROM quick_checks
                    WHERE teacher_id = ?
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                """, (teacher_id, limit, offset))

            rows = await cursor.fetchall()
            return [_row_to_quick_check(row) for row in rows]

    except Exception as e:
        logger.error(f"Error getting quick checks for teacher {teacher_id}: {e}")
        return []


async def get_quick_check_stats(teacher_id: int, days: int = 30) -> Dict[str, Any]:
    """
    Получает статистику по быстрым проверкам учителя.

    Args:
        teacher_id: ID учителя
        days: Период для статистики (в днях)

    Returns:
        Словарь со статистикой
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            cutoff_date = utc_now() - timedelta(days=days)

            # Общая статистика
            cursor = await db.execute("""
                SELECT
                    COUNT(*) as total_checks,
                    SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END) as correct_count,
                    COUNT(DISTINCT task_type) as unique_task_types
                FROM quick_checks
                WHERE teacher_id = ? AND created_at >= ?
            """, (teacher_id, cutoff_date.isoformat()))

            stats_row = await cursor.fetchone()

            # Распределение по типам заданий
            cursor = await db.execute("""
                SELECT task_type, COUNT(*) as count
                FROM quick_checks
                WHERE teacher_id = ? AND created_at >= ?
                GROUP BY task_type
                ORDER BY count DESC
            """, (teacher_id, cutoff_date.isoformat()))

            task_distribution = {row['task_type']: row['count']
                                for row in await cursor.fetchall()}

            # Получаем текущую квоту
            quota = await get_or_create_quota(teacher_id)

            return {
                'total_checks': stats_row['total_checks'] or 0,
                'correct_count': stats_row['correct_count'] or 0,
                'accuracy_rate': (stats_row['correct_count'] / stats_row['total_checks'] * 100)
                                if stats_row['total_checks'] > 0 else 0,
                'task_distribution': task_distribution,
                'quota': {
                    'monthly_limit': quota.monthly_limit if quota else 0,
                    'used_this_month': quota.used_this_month if quota else 0,
                    'remaining': quota.remaining_checks if quota else 0,
                    'bonus_checks': quota.bonus_checks if quota else 0
                } if quota else None,
                'period_days': days
            }

    except Exception as e:
        logger.error(f"Error getting stats for teacher {teacher_id}: {e}")
        return {
            'total_checks': 0,
            'correct_count': 0,
            'accuracy_rate': 0,
            'task_distribution': {},
            'quota': None,
            'period_days': days
        }


# ============================================
# Работа с шаблонами
# ============================================

async def create_template(
    teacher_id: int,
    template_name: str,
    task_type: QuickCheckTaskType,
    task_condition: str,
    tags: Optional[List[str]] = None
) -> Optional[QuickCheckTemplate]:
    """Создает шаблон задания"""
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            now = utc_now()
            tags_json = json.dumps(tags) if tags else None

            cursor = await db.execute("""
                INSERT INTO quick_check_templates (
                    teacher_id, template_name, task_type, task_condition,
                    tags, usage_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (teacher_id, template_name, task_type.value, task_condition,
                  tags_json, 0, now.isoformat()))
            await db.commit()

            return QuickCheckTemplate(
                id=cursor.lastrowid,
                teacher_id=teacher_id,
                template_name=template_name,
                task_type=task_type,
                task_condition=task_condition,
                tags=tags,
                usage_count=0,
                created_at=now,
                updated_at=None
            )

    except Exception as e:
        logger.error(f"Error creating template: {e}")
        return None


async def get_teacher_templates(teacher_id: int) -> List[QuickCheckTemplate]:
    """Получает все шаблоны учителя"""
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT * FROM quick_check_templates
                WHERE teacher_id = ?
                ORDER BY usage_count DESC, created_at DESC
            """, (teacher_id,))

            rows = await cursor.fetchall()
            return [_row_to_template(row) for row in rows]

    except Exception as e:
        logger.error(f"Error getting templates for teacher {teacher_id}: {e}")
        return []


async def increment_template_usage(template_id: int):
    """Увеличивает счетчик использований шаблона"""
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            await db.execute("""
                UPDATE quick_check_templates
                SET usage_count = usage_count + 1,
                    updated_at = ?
                WHERE id = ?
            """, (utc_now().isoformat(), template_id))
            await db.commit()

    except Exception as e:
        logger.error(f"Error incrementing template usage: {e}")


# ============================================
# Вспомогательные функции
# ============================================

def _row_to_quick_check(row: aiosqlite.Row) -> QuickCheck:
    """Конвертирует строку БД в QuickCheck"""
    tags = _safe_json_loads(row['tags'], None) if row['tags'] else None

    return QuickCheck(
        id=row['id'],
        teacher_id=row['teacher_id'],
        task_type=QuickCheckTaskType(row['task_type']),
        task_condition=row['task_condition'],
        student_answer=row['student_answer'],
        student_id=row['student_id'],
        ai_feedback=row['ai_feedback'],
        is_correct=bool(row['is_correct']) if row['is_correct'] is not None else None,
        score=row['score'],
        teacher_comment=row['teacher_comment'],
        tags=tags,
        template_name=row['template_name'],
        created_at=parse_datetime_safe(row['created_at']),
        updated_at=parse_datetime_safe(row['updated_at'])
    )


def _row_to_template(row: aiosqlite.Row) -> QuickCheckTemplate:
    """Конвертирует строку БД в QuickCheckTemplate"""
    tags = _safe_json_loads(row['tags'], None) if row['tags'] else None

    return QuickCheckTemplate(
        id=row['id'],
        teacher_id=row['teacher_id'],
        template_name=row['template_name'],
        task_type=QuickCheckTaskType(row['task_type']),
        task_condition=row['task_condition'],
        tags=tags,
        usage_count=row['usage_count'],
        created_at=parse_datetime_safe(row['created_at']),
        updated_at=parse_datetime_safe(row['updated_at'])
    )


def _row_to_quota(row: aiosqlite.Row) -> QuickCheckQuota:
    """Конвертирует строку БД в QuickCheckQuota"""
    return QuickCheckQuota(
        id=row['id'],
        teacher_id=row['teacher_id'],
        monthly_limit=row['monthly_limit'],
        used_this_month=row['used_this_month'],
        current_period_start=parse_datetime_safe(row['current_period_start']),
        current_period_end=parse_datetime_safe(row['current_period_end']),
        bonus_checks=row['bonus_checks'],
        last_reset_at=parse_datetime_safe(row['last_reset_at']),
        updated_at=parse_datetime_safe(row['updated_at'])
    )
