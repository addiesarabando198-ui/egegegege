"""
API-роуты для Flashcards WebApp.

Обеспечивает:
- Список колод с прогрессом пользователя
- Карточки для повторения (due today)
- Отправка результата повторения (SM-2)
- Статистика и лидерборд
"""

import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException

from api.middleware.telegram_auth import get_current_user_id
from api.schemas.flashcards import (
    DeckWithStatsSchema,
    CardSchema,
    ReviewRequest,
    ReviewResponse,
    UserStatsSchema,
    LeaderboardEntrySchema,
)
from flashcards import db as flashcard_db
from flashcards.sm2 import review_card
from flashcards.leaderboard import (
    add_xp, get_user_xp, get_user_rank, get_leaderboard, get_xp_level,
    XP_CARD_CORRECT, XP_CARD_WRONG,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/decks", response_model=List[DeckWithStatsSchema])
async def list_decks(user_id: int = Depends(get_current_user_id)):
    """Возвращает список всех колод с прогрессом пользователя."""
    decks = await flashcard_db.get_all_decks()
    result = []

    for deck in decks:
        stats = await flashcard_db.get_deck_stats(user_id, deck['id'])
        result.append(DeckWithStatsSchema(
            id=deck['id'],
            title=deck['title'],
            description=deck.get('description', ''),
            category=deck.get('category', ''),
            icon=deck.get('icon', '🃏'),
            card_count=deck.get('card_count', 0),
            total=stats['total'],
            mastered=stats['mastered'],
            reviewing=stats['reviewing'],
            new=stats['new'],
            due_today=stats['due_today'],
        ))

    return result


@router.get("/decks/{deck_id}/cards", response_model=List[CardSchema])
async def get_deck_cards(
    deck_id: str,
    mode: str = "due",
    limit: int = 20,
    user_id: int = Depends(get_current_user_id),
):
    """
    Возвращает карточки колоды.

    mode:
    - "due" — только карточки к повторению
    - "all" — все карточки колоды
    """
    if mode == "due":
        cards = await flashcard_db.get_cards_due_for_review(user_id, deck_id, limit=limit)
        return [CardSchema(
            id=c['card_id'],
            front_text=c['front_text'],
            back_text=c['back_text'],
            hint=c.get('hint'),
            sort_order=0,
        ) for c in cards]
    else:
        cards = await flashcard_db.get_cards_for_deck(deck_id)
        return [CardSchema(
            id=c['id'],
            front_text=c['front_text'],
            back_text=c['back_text'],
            hint=c.get('hint'),
            sort_order=c.get('sort_order', 0),
        ) for c in cards[:limit]]


@router.post("/cards/{card_id}/review", response_model=ReviewResponse)
async def review_card_endpoint(
    card_id: str,
    body: ReviewRequest,
    deck_id: str = "",
    user_id: int = Depends(get_current_user_id),
):
    """Отправляет результат повторения карточки (SM-2)."""
    # Получаем текущий прогресс
    progress = await flashcard_db.get_card_progress(user_id, card_id)

    rep_number = progress.get('repetition_number', 0) if progress else 0
    ef = progress.get('easiness_factor', 2.5) if progress else 2.5
    interval = progress.get('interval_days', 0) if progress else 0
    p_deck_id = progress.get('deck_id', deck_id) if progress else deck_id

    result = review_card(
        quality=body.rating,
        repetition_number=rep_number,
        easiness_factor=ef,
        interval_days=interval,
    )

    is_correct = body.rating >= 2
    await flashcard_db.update_card_progress(
        user_id=user_id,
        card_id=card_id,
        deck_id=p_deck_id,
        easiness_factor=result.easiness_factor,
        interval_days=result.interval_days,
        repetition_number=result.repetition_number,
        next_review=result.next_review.isoformat(),
        is_correct=is_correct,
    )

    # XP
    xp = XP_CARD_CORRECT if is_correct else XP_CARD_WRONG
    xp_earned = await add_xp(user_id, xp, 'card_review', f'webapp_{card_id}')

    return ReviewResponse(
        success=True,
        next_review=result.next_review.isoformat(),
        interval_days=result.interval_days,
        xp_earned=xp_earned,
    )


@router.get("/stats", response_model=UserStatsSchema)
async def get_stats(user_id: int = Depends(get_current_user_id)):
    """Возвращает XP-статистику пользователя."""
    xp_data = await get_user_xp(user_id)
    rank_data = await get_user_rank(user_id)
    level = get_xp_level(xp_data.get('total_xp', 0)) or {'name': 'Новичок', 'icon': '🌱'}

    return UserStatsSchema(
        total_xp=xp_data.get('total_xp', 0),
        weekly_xp=xp_data.get('weekly_xp', 0),
        level_name=level['name'],
        level_icon=level['icon'],
        rank=rank_data['rank'],
        total_users=rank_data['total_users'],
        cards_reviewed=xp_data.get('cards_reviewed', 0),
        quizzes_completed=xp_data.get('quizzes_completed', 0),
        challenges_completed=xp_data.get('challenges_completed', 0),
    )


@router.get("/leaderboard", response_model=List[LeaderboardEntrySchema])
async def get_leaderboard_endpoint(
    period: str = "all",
    limit: int = 10,
    user_id: int = Depends(get_current_user_id),
):
    """Возвращает лидерборд."""
    top = await get_leaderboard(period=period, limit=limit)
    return [LeaderboardEntrySchema(
        rank=entry['rank'],
        user_id=entry['user_id'],
        first_name=entry.get('first_name'),
        xp=entry['xp'],
    ) for entry in top]
