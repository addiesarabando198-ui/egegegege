"""
UTM-tracking для отслеживания источников трафика и эффективности рекламы.

Поддерживает:
- Парсинг UTM-меток из deep links
- Сохранение источника пользователя в БД
- Атрибуция конверсий к источникам
- Отслеживание YCLID для Яндекс.Директ
"""

import logging
import json
from typing import Dict, Optional, Tuple
from datetime import datetime
import aiosqlite
from core.config import DATABASE_FILE

logger = logging.getLogger(__name__)


def parse_utm_from_deeplink(start_param: str) -> Dict[str, str]:
    """
    Парсит UTM-метки из deep link параметра.

    Поддерживаемые форматы:
    1. utm_source-yandex_medium-cpc_campaign-ege2025
    2. source-yandex_campaign-ege2025_yclid-123456
    3. yclid-123456_source-direct

    Args:
        start_param: Параметр из /start команды

    Returns:
        Dict с UTM-метками и дополнительными параметрами
    """
    utm_data = {}

    if not start_param:
        return utm_data

    try:
        # Разбиваем по _ для получения пар ключ-значение
        parts = start_param.split('_')

        for part in parts:
            if '-' in part:
                # Разбиваем только по первому дефису
                key, value = part.split('-', 1)
                utm_data[key] = value

        # Нормализация ключей (убираем utm_ префикс если есть)
        normalized = {}
        for key, value in utm_data.items():
            # utm_source -> source
            clean_key = key.replace('utm_', '')
            normalized[clean_key] = value

        logger.info(f"Parsed UTM data: {normalized}")
        return normalized

    except Exception as e:
        logger.error(f"Error parsing UTM from '{start_param}': {e}")
        return {}


async def save_user_source(
    user_id: int,
    utm_data: Dict[str, str],
    referrer: Optional[str] = None
) -> bool:
    """
    Сохраняет источник пользователя в БД.

    Args:
        user_id: ID пользователя Telegram
        utm_data: Словарь с UTM-метками
        referrer: Откуда пришёл пользователь (опционально)

    Returns:
        True если успешно сохранено
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Проверяем существование таблицы
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='user_sources'"
            )
            table_exists = await cursor.fetchone()

            if not table_exists:
                # Создаём таблицу
                await db.execute("""
                    CREATE TABLE user_sources (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL UNIQUE,
                        source TEXT,
                        medium TEXT,
                        campaign TEXT,
                        content TEXT,
                        term TEXT,
                        yclid TEXT,
                        referrer TEXT,
                        utm_data_json TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(user_id)
                    )
                """)
                await db.execute("CREATE INDEX idx_user_sources_user ON user_sources(user_id)")
                await db.execute("CREATE INDEX idx_user_sources_campaign ON user_sources(campaign)")
                await db.execute("CREATE INDEX idx_user_sources_source ON user_sources(source)")
                await db.commit()
                logger.info("Created user_sources table")

            # Сохраняем источник (только для первого визита)
            # Если пользователь уже есть - не перезаписываем
            utm_json = json.dumps(utm_data, ensure_ascii=False)

            await db.execute("""
                INSERT OR IGNORE INTO user_sources
                (user_id, source, medium, campaign, content, term, yclid, referrer, utm_data_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                utm_data.get('source'),
                utm_data.get('medium'),
                utm_data.get('campaign'),
                utm_data.get('content'),
                utm_data.get('term'),
                utm_data.get('yclid'),
                referrer,
                utm_json
            ))

            await db.commit()

            logger.info(f"Saved source for user {user_id}: {utm_data.get('source')} / {utm_data.get('campaign')}")
            return True

    except Exception as e:
        logger.error(f"Error saving user source for {user_id}: {e}")
        return False


async def get_user_source(user_id: int) -> Optional[Dict[str, str]]:
    """
    Получает источник пользователя из БД.

    Args:
        user_id: ID пользователя

    Returns:
        Dict с данными источника или None
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            cursor = await db.execute("""
                SELECT source, medium, campaign, content, term, yclid,
                       referrer, utm_data_json, created_at
                FROM user_sources
                WHERE user_id = ?
            """, (user_id,))

            row = await cursor.fetchone()

            if row:
                return dict(row)

            return None

    except Exception as e:
        logger.error(f"Error getting user source for {user_id}: {e}")
        return None


async def get_user_yclid(user_id: int) -> Optional[str]:
    """
    Получает YCLID пользователя для передачи конверсий в Яндекс.Директ.

    Args:
        user_id: ID пользователя

    Returns:
        YCLID или None
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            cursor = await db.execute("""
                SELECT yclid FROM user_sources WHERE user_id = ?
            """, (user_id,))

            row = await cursor.fetchone()
            return row[0] if row and row[0] else None

    except Exception as e:
        logger.error(f"Error getting YCLID for {user_id}: {e}")
        return None


async def track_conversion(
    user_id: int,
    conversion_type: str,
    value: float = 0,
    metadata: Optional[Dict] = None
) -> bool:
    """
    Отслеживает конверсию пользователя с привязкой к источнику.

    Args:
        user_id: ID пользователя
        conversion_type: Тип конверсии (trial_purchase, subscription_purchase, etc.)
        value: Стоимость конверсии в рублях
        metadata: Дополнительные данные

    Returns:
        True если успешно сохранено
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            # Проверяем существование таблицы
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='conversions'"
            )
            table_exists = await cursor.fetchone()

            if not table_exists:
                # Создаём таблицу конверсий
                await db.execute("""
                    CREATE TABLE conversions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        conversion_type TEXT NOT NULL,
                        value_rub REAL DEFAULT 0,
                        metadata_json TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(user_id)
                    )
                """)
                await db.execute("CREATE INDEX idx_conversions_user ON conversions(user_id)")
                await db.execute("CREATE INDEX idx_conversions_type ON conversions(conversion_type)")
                await db.execute("CREATE INDEX idx_conversions_date ON conversions(created_at)")
                await db.commit()
                logger.info("Created conversions table")

            # Сохраняем конверсию
            metadata_json = json.dumps(metadata, ensure_ascii=False) if metadata else None

            await db.execute("""
                INSERT INTO conversions (user_id, conversion_type, value_rub, metadata_json)
                VALUES (?, ?, ?, ?)
            """, (user_id, conversion_type, value, metadata_json))

            await db.commit()

            logger.info(f"Tracked conversion: {conversion_type} for user {user_id}, value: {value}₽")
            return True

    except Exception as e:
        logger.error(f"Error tracking conversion for {user_id}: {e}")
        return False


async def get_campaign_stats(
    campaign_name: Optional[str] = None,
    days: int = 30
) -> Dict[str, any]:
    """
    Получает статистику по рекламной кампании.

    Args:
        campaign_name: Название кампании (или None для всех)
        days: За сколько дней (по умолчанию 30)

    Returns:
        Dict со статистикой кампании
    """
    try:
        async with aiosqlite.connect(DATABASE_FILE) as db:
            db.row_factory = aiosqlite.Row

            # Базовый запрос
            where_clause = "WHERE us.created_at >= datetime('now', ?)"
            params = [f'-{days} days']

            if campaign_name:
                where_clause += " AND us.campaign = ?"
                params.append(campaign_name)

            cursor = await db.execute(f"""
                SELECT
                    us.campaign,
                    us.source,
                    COUNT(DISTINCT us.user_id) as total_users,
                    COUNT(DISTINCT CASE
                        WHEN c.conversion_type = 'trial_purchase' THEN c.user_id
                    END) as trial_conversions,
                    COUNT(DISTINCT CASE
                        WHEN c.conversion_type = 'subscription_purchase' THEN c.user_id
                    END) as paid_conversions,
                    COALESCE(SUM(CASE
                        WHEN c.conversion_type = 'subscription_purchase' THEN c.value_rub
                        ELSE 0
                    END), 0) as total_revenue
                FROM user_sources us
                LEFT JOIN conversions c ON us.user_id = c.user_id
                {where_clause}
                GROUP BY us.campaign, us.source
                ORDER BY total_revenue DESC
            """, params)

            rows = await cursor.fetchall()

            stats = []
            for row in rows:
                trial_cr = (row['trial_conversions'] / row['total_users'] * 100) if row['total_users'] > 0 else 0
                paid_cr = (row['paid_conversions'] / row['total_users'] * 100) if row['total_users'] > 0 else 0

                stats.append({
                    'campaign': row['campaign'],
                    'source': row['source'],
                    'total_users': row['total_users'],
                    'trial_conversions': row['trial_conversions'],
                    'paid_conversions': row['paid_conversions'],
                    'trial_cr': round(trial_cr, 2),
                    'paid_cr': round(paid_cr, 2),
                    'total_revenue': row['total_revenue']
                })

            return {
                'campaigns': stats,
                'period_days': days
            }

    except Exception as e:
        logger.error(f"Error getting campaign stats: {e}")
        return {'campaigns': [], 'period_days': days}
