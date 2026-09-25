"""
Daily check-in API.

Requires login (non-guest) users.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from modules.checkin.schemas.checkin import (
    CheckinClaimResponse,
    CheckinStatusResponse,
    SelectCursorRequest,
    SelectCursorResponse,
)
from modules.checkin.services.checkin_service import CheckinService, TOTAL_REWARDS
from modules.literature_pool.api.auth import require_login_user
from modules.literature_pool.models.user import User

router = APIRouter(prefix="/checkin", tags=["Daily Checkin"])


@router.get("/status", response_model=CheckinStatusResponse)
async def get_checkin_status(
    month: str | None = Query(default=None, description="YYYY-MM"),
    user: User = Depends(require_login_user),
    db: AsyncSession = Depends(get_db),
):
    service = CheckinService(db)
    status = await service.get_status(user.id, month=month)
    return {
        "today": status.today.isoformat(),
        "streak_days": status.streak_days,
        "unlocked_count": status.unlocked_count,
        "selected_cursor_id": status.selected_cursor_id,
        "checked_dates": [d.isoformat() for d in status.checked_dates],
        "total_cursors": TOTAL_REWARDS,
    }


@router.post("/claim", response_model=CheckinClaimResponse)
async def claim_today(
    user: User = Depends(require_login_user),
    db: AsyncSession = Depends(get_db),
):
    service = CheckinService(db)
    claimed, state, reward_cursor_id = await service.claim_today(user.id)
    return {
        "claimed": claimed,
        "today": service.today().isoformat(),
        "streak_days": int(getattr(state, "streak_days", 0) or 0),
        "unlocked_count": int(getattr(state, "unlocked_count", 0) or 0),
        "reward_cursor_id": reward_cursor_id,
        "selected_cursor_id": getattr(state, "selected_cursor_id", None),
    }


@router.post("/select-cursor", response_model=SelectCursorResponse)
async def select_cursor(
    payload: SelectCursorRequest,
    user: User = Depends(require_login_user),
    db: AsyncSession = Depends(get_db),
):
    service = CheckinService(db)
    try:
        selected = await service.select_cursor(user.id, int(payload.cursor_id))
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_CURSOR_ID", "message": "cursor_id 不合法"},
        )
    except PermissionError:
        raise HTTPException(
            status_code=403,
            detail={"code": "CURSOR_LOCKED", "message": "该鼠标图标尚未解锁"},
        )

    return {"selected_cursor_id": selected}
