"""Daily allowance boundaries, persisted counters, HTTP errors and contention."""

import asyncio
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from modules.literature_pool.models.feature_usage_counter import FeatureUsageCounter
from modules.literature_pool.models.user import User
from modules.literature_pool.services.daily_quota_service import DailyQuotaService

pytestmark = pytest.mark.asyncio

FEATURES = (
    "literature_translate",
    "journals_translate",
    "wiw_generate",
    "graph_wiw",
    "pigeon_generate",
    "assistant_chat",
    "sports_data",
)


@pytest.mark.parametrize(
    "instant,day,reset",
    [
        ("2026-10-19T15:59:59+00:00", "2026-10-19", "2026-10-20T00:00:00+08:00"),
        ("2026-10-19T16:00:00+00:00", "2026-10-20", "2026-10-21T00:00:00+08:00"),
        ("2026-12-31T23:59:59+08:00", "2026-12-31", "2027-01-01T00:00:00+08:00"),
        ("2027-01-01T00:00:00+08:00", "2027-01-01", "2027-01-02T00:00:00+08:00"),
    ],
)
async def test_period_uses_beijing_midnight(instant, day, reset):
    actual_day, actual_reset = DailyQuotaService.period(datetime.fromisoformat(instant))
    assert actual_day.isoformat() == day
    assert actual_reset.isoformat() == reset


@pytest.mark.parametrize("feature", FEATURES)
async def test_each_feature_allows_exactly_ten_uses(
    db_session, test_user, quota_clock, feature
):
    service = DailyQuotaService(db_session)
    for used in range(1, 11):
        result = await service.consume(test_user.id, feature)
        assert result.allowed is True
        assert result.feature_key == feature
        assert result.limit == 10
        assert result.used == used
        assert result.remaining == 10 - used
        assert result.day == "2026-10-19"
        assert result.resets_at == "2026-10-20T00:00:00+08:00"
        assert not db_session.in_transaction()
    for _ in range(2):
        denied = await service.consume(test_user.id, feature)
        assert denied.allowed is False
        assert denied.used == 10
        assert denied.remaining == 0
        assert denied.detail()["code"] == "DAILY_LIMIT_EXCEEDED"
        assert not db_session.in_transaction()
    counters = (await db_session.execute(select(FeatureUsageCounter))).scalars().all()
    assert len(counters) == 1
    assert counters[0].feature_key == "daily:" + feature
    assert counters[0].week_start == date(2026, 10, 19)
    assert counters[0].count == 10


async def test_usage_is_read_only_and_ignores_historical_weekly_and_daily_rows(
    db_session, test_user, quota_clock
):
    db_session.add_all(
        [
            FeatureUsageCounter(
                user_id=test_user.id,
                feature_key="assistant_chat",
                week_start=date(2026, 10, 19),
                count=5,
            ),
            FeatureUsageCounter(
                user_id=test_user.id,
                feature_key="daily:assistant_chat",
                week_start=date(2026, 10, 18),
                count=10,
            ),
        ]
    )
    await db_session.commit()
    service = DailyQuotaService(db_session)
    for _ in range(2):
        usage = await service.usage(test_user.id)
        assert set(usage["features"]) == set(FEATURES)
        assert all(
            value == {"limit": 10, "used": 0, "remaining": 10}
            for value in usage["features"].values()
        )
    assert (
        await db_session.scalar(select(func.count()).select_from(FeatureUsageCounter))
        == 2
    )
    consumed = await service.consume(test_user.id, "assistant_chat")
    assert consumed.used == 1
    rows = (await db_session.execute(select(FeatureUsageCounter))).scalars().all()
    assert sorted(row.count for row in rows) == [1, 5, 10]


async def test_users_and_features_have_independent_allowances(
    db_session, test_user, quota_clock
):
    other = User(wechat_openid="anon:other-visitor", login_source="anonymous")
    db_session.add(other)
    await db_session.commit()
    service = DailyQuotaService(db_session)
    for _ in range(10):
        await service.consume(test_user.id, "assistant_chat")
    assert (await service.consume(test_user.id, "assistant_chat")).allowed is False
    for user_id, feature in [
        (other.id, "assistant_chat"),
        (test_user.id, "sports_data"),
    ]:
        result = await service.consume(user_id, feature)
        assert result.allowed is True
        assert result.used == 1
        assert result.remaining == 9


async def test_unknown_feature_does_not_create_counter(db_session, test_user):
    with pytest.raises(ValueError, match="Unknown daily quota feature"):
        await DailyQuotaService(db_session).consume(test_user.id, "not-a-feature")
    assert (
        await db_session.scalar(select(func.count()).select_from(FeatureUsageCounter))
        == 0
    )


@pytest.mark.parametrize("identity", ["anonymous", "existing_login"])
async def test_http_exhaustion_and_beijing_day_reset(
    client, db_session, test_user_token, quota_clock, monkeypatch, identity
):
    from core.services.batch_translator import BatchTranslator

    # Mock only the paid operation. Authentication, quota SQL, middleware,
    # response serialization and the endpoint's cache lookup remain real.
    translate = AsyncMock(return_value="测试译文")
    monkeypatch.setenv("DS_API_KEY", "test-only-not-a-real-key")
    monkeypatch.setattr(BatchTranslator, "translate_abstract", translate)
    quota_clock.now = datetime(2026, 10, 19, 15, 59, 59, tzinfo=timezone.utc)
    headers = (
        {"Authorization": f"Bearer {test_user_token}"}
        if identity == "existing_login"
        else {}
    )
    body = {
        "identifier": "99999999",
        "abstract": "Exercise improves health.",
        "source_type": "literature",
    }
    session_before = await client.get("/v1/pool/auth/session", headers=headers)
    user_id = session_before.json()["user"]["id"]

    for _ in range(10):
        response = await client.post(
            "/v1/translate/abstract", json=body, headers=headers
        )
        assert response.status_code == 200
        assert response.json() == {"abstract_zh": "测试译文", "cached": False}
    for _ in range(2):
        response = await client.post(
            "/v1/translate/abstract", json=body, headers=headers
        )
        assert response.status_code == 429
        detail = response.json()["detail"]
        assert {key: value for key, value in detail.items() if key != "message"} == {
            "code": "DAILY_LIMIT_EXCEEDED",
            "feature": "literature_translate",
            "day": "2026-10-19",
            "resets_at": "2026-10-20T00:00:00+08:00",
            "limit": 10,
            "used": 10,
            "remaining": 0,
        }
        assert detail["message"]
    assert translate.await_count == 10
    exhausted = await client.get("/v1/pool/auth/session", headers=headers)
    assert exhausted.status_code == 200
    assert exhausted.json()["quota"]["features"]["literature_translate"] == {
        "limit": 10,
        "used": 10,
        "remaining": 0,
    }

    quota_clock.now = datetime(2026, 10, 19, 16, 0, 0, tzinfo=timezone.utc)
    reset = await client.get("/v1/pool/auth/session", headers=headers)
    assert reset.json()["user"]["id"] == user_id
    assert reset.json()["quota"]["day"] == "2026-10-20"
    assert reset.json()["quota"]["resets_at"] == "2026-10-21T00:00:00+08:00"
    assert reset.json()["quota"]["features"]["literature_translate"] == {
        "limit": 10,
        "used": 0,
        "remaining": 10,
    }
    response = await client.post("/v1/translate/abstract", json=body, headers=headers)
    assert response.status_code == 200
    assert translate.await_count == 11
    rows = (
        (
            await db_session.execute(
                select(FeatureUsageCounter)
                .where(
                    FeatureUsageCounter.user_id == user_id,
                    FeatureUsageCounter.feature_key == "daily:literature_translate",
                )
                .order_by(FeatureUsageCounter.week_start)
            )
        )
        .scalars()
        .all()
    )
    assert [(row.week_start, row.count) for row in rows] == [
        (date(2026, 10, 19), 10),
        (date(2026, 10, 20), 1),
    ]


async def test_quota_dependency_stops_handler_after_exhaustion_and_isolates_visitors(
    client, client_factory, monkeypatch, quota_clock
):
    from modules.sports_data.api import routes

    # The actual sports-data endpoint checks its cache after the real quota
    # dependency. Returning a cached empty search avoids Tavily completely.
    cached_search = AsyncMock(return_value=[])
    monkeypatch.setattr(routes, "_tavily_cache_get", cached_search)
    for _ in range(10):
        response = await client.get(
            "/v1/sports-data/datasets", params={"q": "exercise"}
        )
        assert response.status_code == 200
    response = await client.get("/v1/sports-data/datasets", params={"q": "exercise"})
    assert response.status_code == 429
    assert response.json()["detail"]["feature"] == "sports_data"
    assert cached_search.await_count == 10
    async with client_factory() as other:
        assert (
            await other.get("/v1/sports-data/datasets", params={"q": "exercise"})
        ).status_code == 200
        usage = (await other.get("/v1/pool/auth/session")).json()["quota"]["features"]
        assert usage["sports_data"] == {"limit": 10, "used": 1, "remaining": 9}


async def test_cached_translation_remains_available_after_exhaustion(
    client, db_session, quota_clock, monkeypatch
):
    from core.services.batch_translator import BatchTranslator
    from modules.literature_stream.models.literature import Literature

    monkeypatch.setenv("DS_API_KEY", "test-only-not-a-real-key")
    translate = AsyncMock()
    monkeypatch.setattr(BatchTranslator, "translate_abstract", translate)
    user_id = (await client.get("/v1/pool/auth/session")).json()["user"]["id"]
    db_session.add(
        Literature(
            id=1, pmid="99999999", title="Cached article", abstract_zh="已缓存的译文"
        )
    )
    await db_session.commit()
    for _ in range(10):
        await DailyQuotaService(db_session).consume(user_id, "literature_translate")
    response = await client.post(
        "/v1/translate/abstract",
        json={
            "identifier": "99999999",
            "abstract": "Exercise improves health.",
            "source_type": "literature",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"abstract_zh": "已缓存的译文", "cached": True}
    translate.assert_not_awaited()
    usage = await DailyQuotaService(db_session).usage(user_id)
    assert usage["features"]["literature_translate"] == {
        "limit": 10,
        "used": 10,
        "remaining": 0,
    }


@pytest.mark.parametrize("already_used", [0, 9])
async def test_concurrent_consumers_cannot_overshoot_ten(
    session_factory, db_session, test_user, quota_clock, already_used
):
    for _ in range(already_used):
        await DailyQuotaService(db_session).consume(test_user.id, "assistant_chat")
    start = asyncio.Event()

    async def consume():
        async with session_factory() as session:
            await start.wait()
            result = await DailyQuotaService(session).consume(
                test_user.id, "assistant_chat"
            )
            assert not session.in_transaction()
            return result

    tasks = [asyncio.create_task(consume()) for _ in range(25)]
    start.set()
    results = await asyncio.gather(*tasks)
    allowed = [result for result in results if result.allowed]
    assert len(allowed) == 10 - already_used
    assert sorted(result.used for result in allowed) == list(
        range(already_used + 1, 11)
    )
    assert all(
        result.used == 10 and result.remaining == 0
        for result in results
        if not result.allowed
    )
    counters = (await db_session.execute(select(FeatureUsageCounter))).scalars().all()
    assert len(counters) == 1
    assert counters[0].count == 10
