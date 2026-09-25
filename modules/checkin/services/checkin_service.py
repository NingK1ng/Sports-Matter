"""
Daily check-in service.

- Uses Asia/Shanghai date boundary for "today"
- Supports 30-day cursor rewards + hidden 31-day bonus
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from modules.checkin.models.checkin import UserCheckin, UserCheckinEvent


TOTAL_CURSORS = 30
TOTAL_REWARDS = 31
MONTHLY_BONUS_STREAK_DAY = 31
MONTHLY_BONUS_DURATION_DAYS = 30
DEFAULT_TIMEZONE = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class CheckinStatus:
    today: date
    streak_days: int
    unlocked_count: int
    selected_cursor_id: int | None
    checked_dates: list[date]


class CheckinService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def today(self) -> date:
        return datetime.now(DEFAULT_TIMEZONE).date()

    @staticmethod
    def _month_bounds(any_day: date) -> tuple[date, date]:
        month_start = date(any_day.year, any_day.month, 1)
        if any_day.month == 12:
            next_month = date(any_day.year + 1, 1, 1)
        else:
            next_month = date(any_day.year, any_day.month + 1, 1)
        month_end = next_month - timedelta(days=1)
        return month_start, month_end

    @staticmethod
    def _parse_month(month: str | None, fallback_today: date) -> date:
        if not month:
            return fallback_today
        value = month.strip()
        if not value:
            return fallback_today
        # Accept YYYY-MM
        try:
            year_str, month_str = value.split("-", 1)
            year = int(year_str)
            mon = int(month_str)
            if year < 1970 or mon < 1 or mon > 12:
                return fallback_today
            return date(year, mon, 1)
        except Exception:
            return fallback_today

    async def _get_state_for_update(self, user_id: int) -> UserCheckin | None:
        res = await self.db.execute(
            select(UserCheckin).where(UserCheckin.user_id == user_id).with_for_update()
        )
        return res.scalar_one_or_none()

    async def _get_state(self, user_id: int) -> UserCheckin | None:
        res = await self.db.execute(select(UserCheckin).where(UserCheckin.user_id == user_id))
        return res.scalar_one_or_none()

    async def _ensure_state(self, user_id: int) -> UserCheckin:
        state = await self._get_state(user_id)
        if state:
            return state
        state = UserCheckin(
            user_id=user_id,
            last_checkin_date=None,
            streak_days=0,
            unlocked_count=0,
            selected_cursor_id=None,
        )
        self.db.add(state)
        await self.db.flush()
        return state

    async def get_status(self, user_id: int, *, month: str | None = None) -> CheckinStatus:
        today = self.today()
        month_day = self._parse_month(month, today)
        month_start, month_end = self._month_bounds(month_day)

        state = await self._get_state(user_id)
        if not state:
            return CheckinStatus(
                today=today,
                streak_days=0,
                unlocked_count=0,
                selected_cursor_id=None,
                checked_dates=[],
            )

        res = await self.db.execute(
            select(UserCheckinEvent.checkin_date)
            .where(
                and_(
                    UserCheckinEvent.user_id == user_id,
                    UserCheckinEvent.checkin_date >= month_start,
                    UserCheckinEvent.checkin_date <= month_end,
                )
            )
            .order_by(UserCheckinEvent.checkin_date.asc())
        )
        checked = [row[0] for row in res.all()]
        return CheckinStatus(
            today=today,
            streak_days=int(getattr(state, "streak_days", 0) or 0),
            unlocked_count=int(getattr(state, "unlocked_count", 0) or 0),
            selected_cursor_id=getattr(state, "selected_cursor_id", None),
            checked_dates=checked,
        )

    async def claim_today(self, user_id: int) -> tuple[bool, UserCheckin, int]:
        """
        Claim today's check-in.

        Returns:
            (claimed, state, reward_cursor_id)
        """
        today = self.today()

        try:
            state = await self._get_state_for_update(user_id)
            if not state:
                state = UserCheckin(
                    user_id=user_id,
                    last_checkin_date=None,
                    streak_days=0,
                    unlocked_count=0,
                    selected_cursor_id=None,
                )
                self.db.add(state)
                await self.db.flush()

            if getattr(state, "last_checkin_date", None) == today:
                reward_cursor_id = min(max(int(getattr(state, "streak_days", 1) or 1), 1), TOTAL_CURSORS)
                return False, state, reward_cursor_id

            last_day = getattr(state, "last_checkin_date", None)
            if last_day and last_day == today - timedelta(days=1):
                new_streak = int(getattr(state, "streak_days", 0) or 0) + 1
            else:
                new_streak = 1

            reward_cursor_id = min(new_streak, TOTAL_CURSORS)
            new_unlocked = max(int(getattr(state, "unlocked_count", 0) or 0), reward_cursor_id)

            state.last_checkin_date = today
            state.streak_days = new_streak
            state.unlocked_count = new_unlocked
            if getattr(state, "selected_cursor_id", None) is None:
                state.selected_cursor_id = reward_cursor_id

            self.db.add(UserCheckinEvent(user_id=user_id, checkin_date=today))
            await self.db.flush()

            if new_streak == MONTHLY_BONUS_STREAK_DAY:
                await self._grant_monthly_bonus(user_id)

            return True, state, reward_cursor_id
        except IntegrityError:
            # Concurrency/unique constraint: treat as already claimed and load latest state.
            await self.db.rollback()
            state = await self._ensure_state(user_id)
            reward_cursor_id = min(max(int(getattr(state, "streak_days", 1) or 1), 1), TOTAL_CURSORS)
            return False, state, reward_cursor_id

    async def _grant_monthly_bonus(self, user_id: int) -> None:
        """
        Hidden bonus: grant +30 days membership on 31-day streak.

        Notes:
        - Does not create a 31st cursor icon; cursor unlock remains 1..30.
        - Does not downgrade existing monthly/yearly tiers; it only extends expiry.
        """
        from modules.literature_pool.models.user import User

        res = await self.db.execute(select(User).where(User.id == user_id).with_for_update())
        user = res.scalar_one_or_none()
        if not user:
            return
        if bool(getattr(user, "membership_is_lifetime", False)):
            return

        now = datetime.now(timezone.utc)
        base = now

        exp = getattr(user, "membership_expires_at", None)
        if exp is not None:
            if getattr(exp, "tzinfo", None) is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp > now:
                base = exp

        tier = (getattr(user, "membership_tier", "") or "").strip().lower()
        if tier in {"", "weekly_invite"}:
            user.membership_tier = "monthly"
        user.membership_started_at = getattr(user, "membership_started_at", None) or now
        user.membership_expires_at = base + timedelta(days=MONTHLY_BONUS_DURATION_DAYS)
        self.db.add(user)

    async def select_cursor(self, user_id: int, cursor_id: int) -> int | None:
        if cursor_id == 0:
            state = await self._ensure_state(user_id)
            state.selected_cursor_id = None
            await self.db.flush()
            return None

        if cursor_id < 1 or cursor_id > TOTAL_CURSORS:
            raise ValueError("cursor_id_out_of_range")

        state = await self._ensure_state(user_id)
        unlocked = int(getattr(state, "unlocked_count", 0) or 0)
        if cursor_id > unlocked:
            raise PermissionError("cursor_locked")

        state.selected_cursor_id = cursor_id
        await self.db.flush()
        return cursor_id
