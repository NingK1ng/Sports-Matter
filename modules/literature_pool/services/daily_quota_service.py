"""Daily, atomic quotas shared by HTTP requests and background workers.

The existing week_start column stores the local day for daily:* keys. Historical
weekly counters retain their original keys and are not changed.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from modules.literature_pool.models.feature_usage_counter import FeatureUsageCounter

DAILY_LIMIT = 10
FEATURES = ("literature_translate", "journals_translate", "wiw_generate",
            "graph_wiw", "pigeon_generate", "assistant_chat", "sports_data")
TIMEZONE = ZoneInfo("Asia/Shanghai")

@dataclass(frozen=True)
class DailyQuotaResult:
    allowed: bool
    feature_key: str
    day: str
    resets_at: str
    used: int
    limit: int = DAILY_LIMIT

    @property
    def remaining(self):
        return max(0, self.limit - self.used)

    def detail(self):
        return {"code": "DAILY_LIMIT_EXCEEDED", "feature": self.feature_key,
                "message": f"本模块今天的 {self.limit} 次免费额度已用完，北京时间次日零点恢复。",
                "day": self.day, "resets_at": self.resets_at, "limit": self.limit,
                "used": self.used, "remaining": self.remaining}

class DailyQuotaExceeded(ValueError):
    def __init__(self, result):
        self.result = result
        super().__init__(result.detail()["message"])

class DailyQuotaService:
    def __init__(self, session):
        self.session = session

    @staticmethod
    def period(now=None):
        now = now or datetime.now(TIMEZONE)
        day = now.astimezone(TIMEZONE).date()
        reset = datetime.combine(day + timedelta(days=1), time.min, TIMEZONE)
        return day, reset

    async def usage(self, user_id):
        day, reset = self.period()
        rows = await self.session.execute(select(FeatureUsageCounter.feature_key, FeatureUsageCounter.count).where(
            FeatureUsageCounter.user_id == user_id, FeatureUsageCounter.week_start == day,
            FeatureUsageCounter.feature_key.in_(["daily:" + k for k in FEATURES])))
        counts = {key.removeprefix("daily:"): int(count) for key, count in rows.all()}
        return {"period": "day", "timezone": "Asia/Shanghai", "day": day.isoformat(),
                "resets_at": reset.isoformat(), "features": {
                    k: {"limit": DAILY_LIMIT, "used": counts.get(k, 0),
                        "remaining": max(0, DAILY_LIMIT - counts.get(k, 0))} for k in FEATURES}}

    async def consume(self, user_id, feature_key):
        if feature_key not in FEATURES:
            raise ValueError("Unknown daily quota feature")
        day, reset = self.period()
        key = "daily:" + feature_key
        stmt = insert(FeatureUsageCounter).values(user_id=user_id, feature_key=key, week_start=day, count=1)
        stmt = stmt.on_conflict_do_update(index_elements=["user_id", "feature_key", "week_start"],
            set_={"count": FeatureUsageCounter.count + 1}, where=FeatureUsageCounter.count < DAILY_LIMIT
        ).returning(FeatureUsageCounter.count)
        result = await self.session.execute(stmt)
        count = result.scalar_one_or_none()
        # End the transaction even when denied; never hold a row lock during SSE or an API call.
        await self.session.commit()
        return DailyQuotaResult(count is not None, feature_key, day.isoformat(), reset.isoformat(),
                                int(count) if count is not None else DAILY_LIMIT)
