"""
Pydantic-схемы для Flashcards WebApp API.
"""

from pydantic import BaseModel, Field
from typing import List, Optional


class CardSchema(BaseModel):
    id: str
    front_text: str
    back_text: str
    hint: Optional[str] = None
    sort_order: int = 0


class DeckSchema(BaseModel):
    id: str
    title: str
    description: str = ""
    category: str = ""
    icon: str = "🃏"
    card_count: int = 0


class DeckWithStatsSchema(DeckSchema):
    total: int = 0
    mastered: int = 0
    reviewing: int = 0
    new: int = 0
    due_today: int = 0


class ReviewRequest(BaseModel):
    rating: int = Field(..., ge=0, le=3, description="0=again, 1=hard, 2=good, 3=easy")


class ReviewResponse(BaseModel):
    success: bool
    next_review: str
    interval_days: int
    xp_earned: float


class UserStatsSchema(BaseModel):
    total_xp: float = 0
    weekly_xp: float = 0
    level_name: str = "Новичок"
    level_icon: str = "🌱"
    rank: int = 0
    total_users: int = 0
    cards_reviewed: int = 0
    quizzes_completed: int = 0
    challenges_completed: int = 0


class LeaderboardEntrySchema(BaseModel):
    rank: int
    user_id: int
    first_name: Optional[str] = None
    xp: float
