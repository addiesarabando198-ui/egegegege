"""
Слой базы данных для модуля карточек.

Таблицы:
- flashcard_decks: Колоды карточек
- flashcard_cards: Карточки внутри колод
- flashcard_progress: Прогресс пользователя по каждой карточке (SM-2)
"""

import logging
import aiosqlite
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from core.db import DATABASE_FILE

logger = logging.getLogger(__name__)


async def ensure_tables() -> None:
    """Создаёт таблицы, если они не существуют."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS flashcard_decks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT,
                category TEXT NOT NULL,
                icon TEXT DEFAULT '🃏',
                card_count INTEGER DEFAULT 0,
                is_premium INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS flashcard_cards (
                id TEXT PRIMARY KEY,
                deck_id TEXT NOT NULL,
                front_text TEXT NOT NULL,
                back_text TEXT NOT NULL,
                hint TEXT,
                sort_order INTEGER DEFAULT 0,
                FOREIGN KEY (deck_id) REFERENCES flashcard_decks(id)
            );

            CREATE TABLE IF NOT EXISTS flashcard_progress (
                user_id INTEGER NOT NULL,
                card_id TEXT NOT NULL,
                deck_id TEXT NOT NULL,
                easiness_factor REAL DEFAULT 2.5,
                interval_days INTEGER DEFAULT 0,
                repetition_number INTEGER DEFAULT 0,
                next_review TEXT,
                last_reviewed TEXT,
                total_reviews INTEGER DEFAULT 0,
                correct_count INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, card_id),
                FOREIGN KEY (card_id) REFERENCES flashcard_cards(id)
            );

            CREATE INDEX IF NOT EXISTS idx_fc_progress_review
                ON flashcard_progress(user_id, next_review);

            CREATE INDEX IF NOT EXISTS idx_fc_progress_deck
                ON flashcard_progress(user_id, deck_id);

            CREATE INDEX IF NOT EXISTS idx_fc_cards_deck
                ON flashcard_cards(deck_id);
        """)
        await db.commit()
        logger.info("Flashcard tables ensured")


# ============================================================
# DECK OPERATIONS
# ============================================================

async def get_all_decks() -> List[Dict[str, Any]]:
    """Возвращает все колоды."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM flashcard_decks ORDER BY category, title"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_deck(deck_id: str) -> Optional[Dict[str, Any]]:
    """Возвращает колоду по ID."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM flashcard_decks WHERE id = ?", (deck_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def upsert_deck(
    deck_id: str,
    title: str,
    description: str,
    category: str,
    icon: str = "🃏",
    is_premium: int = 0,
) -> None:
    """Создаёт или обновляет колоду."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute("""
            INSERT INTO flashcard_decks (id, title, description, category, icon, is_premium, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                description = excluded.description,
                category = excluded.category,
                icon = excluded.icon,
                is_premium = excluded.is_premium
        """, (
            deck_id, title, description, category, icon, is_premium,
            datetime.now(timezone.utc).isoformat()
        ))
        await db.commit()


async def update_deck_card_count(deck_id: str) -> None:
    """Обновляет количество карточек в колоде."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute("""
            UPDATE flashcard_decks
            SET card_count = (SELECT COUNT(*) FROM flashcard_cards WHERE deck_id = ?)
            WHERE id = ?
        """, (deck_id, deck_id))
        await db.commit()


# ============================================================
# CARD OPERATIONS
# ============================================================

async def get_cards_for_deck(deck_id: str) -> List[Dict[str, Any]]:
    """Возвращает все карточки колоды."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM flashcard_cards WHERE deck_id = ? ORDER BY sort_order",
            (deck_id,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def upsert_card(
    card_id: str,
    deck_id: str,
    front_text: str,
    back_text: str,
    hint: Optional[str] = None,
    sort_order: int = 0,
) -> None:
    """Создаёт или обновляет карточку."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute("""
            INSERT INTO flashcard_cards (id, deck_id, front_text, back_text, hint, sort_order)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                front_text = excluded.front_text,
                back_text = excluded.back_text,
                hint = excluded.hint,
                sort_order = excluded.sort_order
        """, (card_id, deck_id, front_text, back_text, hint, sort_order))
        await db.commit()


async def bulk_upsert_cards(cards: List[Dict[str, Any]]) -> None:
    """Массовое создание/обновление карточек."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.executemany("""
            INSERT INTO flashcard_cards (id, deck_id, front_text, back_text, hint, sort_order)
            VALUES (:id, :deck_id, :front_text, :back_text, :hint, :sort_order)
            ON CONFLICT(id) DO UPDATE SET
                front_text = excluded.front_text,
                back_text = excluded.back_text,
                hint = excluded.hint,
                sort_order = excluded.sort_order
        """, cards)
        await db.commit()


# ============================================================
# PROGRESS / SM-2 OPERATIONS
# ============================================================

async def get_cards_due_for_review(
    user_id: int,
    deck_id: str,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """
    Возвращает карточки, которые пора повторить.

    Порядок:
    1. Новые карточки (нет записи в flashcard_progress)
    2. Просроченные (next_review <= now), отсортированные по просроченности
    """
    now = datetime.now(timezone.utc).isoformat()

    async with aiosqlite.connect(DATABASE_FILE) as db:
        db.row_factory = aiosqlite.Row

        # Карточки, которые пора повторить (или новые)
        cursor = await db.execute("""
            SELECT
                c.id as card_id,
                c.deck_id,
                c.front_text,
                c.back_text,
                c.hint,
                COALESCE(p.easiness_factor, 2.5) as easiness_factor,
                COALESCE(p.interval_days, 0) as interval_days,
                COALESCE(p.repetition_number, 0) as repetition_number,
                p.next_review,
                p.last_reviewed,
                COALESCE(p.total_reviews, 0) as total_reviews,
                CASE
                    WHEN p.card_id IS NULL THEN 1
                    ELSE 0
                END as is_new
            FROM flashcard_cards c
            LEFT JOIN flashcard_progress p
                ON c.id = p.card_id AND p.user_id = ?
            WHERE c.deck_id = ?
              AND (p.next_review IS NULL OR p.next_review <= ?)
            ORDER BY
                is_new DESC,
                p.next_review ASC
            LIMIT ?
        """, (user_id, deck_id, now, limit))

        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def update_card_progress(
    user_id: int,
    card_id: str,
    deck_id: str,
    easiness_factor: float,
    interval_days: int,
    repetition_number: int,
    next_review: str,
    is_correct: bool,
) -> None:
    """Обновляет прогресс карточки после повторения."""
    now = datetime.now(timezone.utc).isoformat()

    async with aiosqlite.connect(DATABASE_FILE) as db:
        await db.execute("""
            INSERT INTO flashcard_progress (
                user_id, card_id, deck_id,
                easiness_factor, interval_days, repetition_number,
                next_review, last_reviewed,
                total_reviews, correct_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(user_id, card_id) DO UPDATE SET
                easiness_factor = excluded.easiness_factor,
                interval_days = excluded.interval_days,
                repetition_number = excluded.repetition_number,
                next_review = excluded.next_review,
                last_reviewed = excluded.last_reviewed,
                total_reviews = total_reviews + 1,
                correct_count = correct_count + excluded.correct_count
        """, (
            user_id, card_id, deck_id,
            easiness_factor, interval_days, repetition_number,
            next_review, now,
            1 if is_correct else 0,
        ))
        await db.commit()


async def get_deck_stats(user_id: int, deck_id: str) -> Dict[str, int]:
    """
    Возвращает статистику по колоде для пользователя.

    Returns:
        {total, learned, reviewing, new, due_today, mastered}
    """
    now = datetime.now(timezone.utc).isoformat()

    async with aiosqlite.connect(DATABASE_FILE) as db:
        # Общее количество карточек
        cursor = await db.execute(
            "SELECT COUNT(*) FROM flashcard_cards WHERE deck_id = ?",
            (deck_id,)
        )
        total = (await cursor.fetchone())[0]

        # Карточки с прогрессом
        cursor = await db.execute("""
            SELECT
                COUNT(*) as reviewed,
                SUM(CASE WHEN interval_days >= 21 THEN 1 ELSE 0 END) as mastered,
                SUM(CASE WHEN next_review <= ? THEN 1 ELSE 0 END) as due_today
            FROM flashcard_progress
            WHERE user_id = ? AND deck_id = ?
        """, (now, user_id, deck_id))

        row = await cursor.fetchone()
        reviewed = row[0] or 0
        mastered = row[1] or 0
        due_today = row[2] or 0

        new_cards = total - reviewed
        reviewing = reviewed - mastered

        return {
            'total': total,
            'new': new_cards,
            'reviewing': reviewing,
            'mastered': mastered,
            'due_today': due_today + new_cards,
        }


async def get_card_progress(user_id: int, card_id: str) -> Optional[Dict[str, Any]]:
    """Возвращает прогресс пользователя по конкретной карточке."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT * FROM flashcard_progress
            WHERE user_id = ? AND card_id = ?
        """, (user_id, card_id))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_user_overall_stats(user_id: int) -> Dict[str, Any]:
    """Возвращает общую статистику пользователя по всем колодам."""
    async with aiosqlite.connect(DATABASE_FILE) as db:
        cursor = await db.execute("""
            SELECT
                COUNT(*) as total_reviews,
                SUM(correct_count) as total_correct,
                COUNT(DISTINCT card_id) as unique_cards,
                COUNT(DISTINCT deck_id) as decks_touched
            FROM flashcard_progress
            WHERE user_id = ?
        """, (user_id,))

        row = await cursor.fetchone()
        return {
            'total_reviews': row[0] or 0,
            'total_correct': row[1] or 0,
            'unique_cards': row[2] or 0,
            'decks_touched': row[3] or 0,
        }


async def export_all_decks_json() -> list:
    """
    Экспортирует все колоды с карточками для статического JSON (WebApp).

    Returns:
        Список колод, каждая с вложенным списком 'cards'.
    """
    async with aiosqlite.connect(DATABASE_FILE) as db:
        db.row_factory = aiosqlite.Row

        decks_cursor = await db.execute(
            "SELECT * FROM flashcard_decks ORDER BY category, title"
        )
        decks = [dict(row) for row in await decks_cursor.fetchall()]

        for deck in decks:
            cards_cursor = await db.execute(
                "SELECT id, front_text, back_text, hint, sort_order "
                "FROM flashcard_cards WHERE deck_id = ? ORDER BY sort_order",
                (deck['id'],)
            )
            deck['cards'] = [dict(row) for row in await cards_cursor.fetchall()]

    return decks
