"""
Daily check-in API schemas.
"""

from pydantic import BaseModel, Field


class CheckinStatusResponse(BaseModel):
    today: str
    streak_days: int = 0
    unlocked_count: int = 0
    selected_cursor_id: int | None = None
    checked_dates: list[str] = Field(default_factory=list)
    total_cursors: int = 31


class CheckinClaimResponse(BaseModel):
    claimed: bool
    today: str
    streak_days: int
    unlocked_count: int
    reward_cursor_id: int
    selected_cursor_id: int | None = None


class SelectCursorRequest(BaseModel):
    cursor_id: int


class SelectCursorResponse(BaseModel):
    selected_cursor_id: int | None = None
