"""
UsageLimitService - 试用次数限制（按周）
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from modules.literature_pool.models.feature_usage_counter import FeatureUsageCounter


@dataclass(frozen=True)
class WeeklyQuotaResult:
    allowed: bool
    feature_key: str
    week_start: date
    week_end: date
    used: int
    limit: int

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)


class UsageLimitService:
    """按周试用次数限制服务"""

    def __init__(self, session: AsyncSession):
        self.session = session

    def _week_start(self, today: date) -> date:
        # Monday = 0
        return today - timedelta(days=today.weekday())

    def get_current_week_range(self) -> tuple[date, date]:
        # 使用配置时区计算本周（默认 Asia/Shanghai）
        today = datetime.now().date()
        try:
            from zoneinfo import ZoneInfo

            tz = ZoneInfo(str(getattr(settings, "timezone", None) or "Asia/Shanghai"))
            today = datetime.now(tz).date()
        except Exception:
            today = datetime.now().date()
        start = self._week_start(today)
        end = start + timedelta(days=7)
        return start, end

    async def get_weekly_usage_counts(
        self,
        *,
        user_id: int,
        feature_keys: list[str],
    ) -> tuple[date, date, dict[str, int]]:
        """
        查询当前周内各功能已用次数（不消费额度）。
        """
        week_start, week_end = self.get_current_week_range()
        keys = [k for k in dict.fromkeys(feature_keys or []) if k]
        if not keys:
            return week_start, week_end, {}

        stmt = select(FeatureUsageCounter.feature_key, FeatureUsageCounter.count).where(
            FeatureUsageCounter.user_id == user_id,
            FeatureUsageCounter.week_start == week_start,
            FeatureUsageCounter.feature_key.in_(keys),
        )
        result = await self.session.execute(stmt)
        counts = {row[0]: int(row[1] or 0) for row in result.all()}
        # 补齐不存在的 key 为 0
        for k in keys:
            counts.setdefault(k, 0)
        return week_start, week_end, counts

    async def consume_weekly_quota(
        self,
        *,
        user_id: int,
        feature_key: str,
        limit: int,
    ) -> WeeklyQuotaResult:
        """
        消费一次本周额度（原子自增）

        - 若未超限：自增并返回 allowed=True
        - 若超限：不自增并返回 allowed=False
        """
        if limit <= 0:
            start, end = self.get_current_week_range()
            return WeeklyQuotaResult(
                allowed=False,
                feature_key=feature_key,
                week_start=start,
                week_end=end,
                used=0,
                limit=limit,
            )

        week_start, week_end = self.get_current_week_range()

        stmt = (
            insert(FeatureUsageCounter)
            .values(
                user_id=user_id,
                feature_key=feature_key,
                week_start=week_start,
                count=1,
            )
            .on_conflict_do_update(
                index_elements=["user_id", "feature_key", "week_start"],
                set_={"count": FeatureUsageCounter.count + 1},
                where=FeatureUsageCounter.count < limit,
            )
            .returning(FeatureUsageCounter.count)
        )

        result = await self.session.execute(stmt)
        new_count = result.scalar_one_or_none()

        if new_count is not None:
            await self.session.commit()
            return WeeklyQuotaResult(
                allowed=True,
                feature_key=feature_key,
                week_start=week_start,
                week_end=week_end,
                used=int(new_count),
                limit=limit,
            )

        # 未更新：说明已达上限（或并发冲突），查询当前计数
        query = select(FeatureUsageCounter.count).where(
            FeatureUsageCounter.user_id == user_id,
            FeatureUsageCounter.feature_key == feature_key,
            FeatureUsageCounter.week_start == week_start,
        )
        row = await self.session.execute(query)
        used = row.scalar_one_or_none() or limit
        return WeeklyQuotaResult(
            allowed=False,
            feature_key=feature_key,
            week_start=week_start,
            week_end=week_end,
            used=int(used),
            limit=limit,
        )
