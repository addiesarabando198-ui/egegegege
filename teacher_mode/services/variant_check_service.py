"""
Сервис для сохранения и получения результатов проверки вариантов.
"""

import logging
import json
import aiosqlite
from datetime import datetime
from typing import Optional, List, Dict, Any

from core.db import DATABASE_FILE
from ..utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)


async def save_variant_check(
    teacher_id: int,
    variant_source: str,
    variant_id: Optional[str],
    tasks_checked: List[int],
    student_name: Optional[str],
    results: Dict[int, Dict],
    total_score: int,
    max_score: int,
) -> Optional[int]:
    """
    Сохраняет результат проверки варианта в БД.

    Returns:
        ID записи или None при ошибке.
    """
    try:
        # Конвертируем ключи results в строки для JSON
        results_for_json = {str(k): v for k, v in results.items()}

        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute("""
                INSERT INTO variant_checks (
                    teacher_id, variant_source, variant_id,
                    tasks_checked, student_name, results_json,
                    total_score, max_score, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                teacher_id,
                variant_source,
                variant_id,
                json.dumps(tasks_checked),
                student_name,
                json.dumps(results_for_json, ensure_ascii=False),
                total_score,
                max_score,
                utc_now().isoformat(),
            ))
            await db.commit()
            return cursor.lastrowid

    except Exception as e:
        logger.error(f"Error saving variant check: {e}", exc_info=True)
        return None


async def get_variant_check_history(
    teacher_id: int,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """Получает историю проверок вариантов."""
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT * FROM variant_checks
                WHERE teacher_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (teacher_id, limit))

            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    except Exception as e:
        logger.error(f"Error getting variant check history: {e}", exc_info=True)
        return []
