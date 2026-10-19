"""Public authentication uses a signed per-browser identity, never a shared user."""

import asyncio
from datetime import datetime, timezone

import pytest
from jose import jwt
from sqlalchemy import func, select

from core.config import settings
from core.visitor_session import COOKIE_NAME, MAX_AGE
from modules.literature_pool.models.user import User
from modules.literature_pool.services.auth_service import AuthService

pytestmark = pytest.mark.asyncio

EXPECTED_FEATURES = {
    "literature_translate",
    "journals_translate",
    "wiw_generate",
    "graph_wiw",
    "pigeon_generate",
    "assistant_chat",
    "sports_data",
}


@pytest.mark.parametrize("prefix", ["/v1", "/api/v1"])
async def test_public_session_contract(client, prefix, quota_clock):
    response = await client.get(f"{prefix}/pool/auth/session")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["logged_in"] is True
    assert data["access_mode"] == "public"
    assert data["login_required"] is False
    assert data["user"]["is_guest"] is True
    assert data["user"]["nickname"] == "访客"
    assert data["quota"]["period"] == "day"
    assert data["quota"]["timezone"] == "Asia/Shanghai"
    assert data["quota"]["day"] == "2026-10-19"
    assert data["quota"]["resets_at"] == "2026-10-20T00:00:00+08:00"
    assert set(data["quota"]["features"]) == EXPECTED_FEATURES
    assert all(
        value == {"limit": 10, "used": 0, "remaining": 10}
        for value in data["quota"]["features"].values()
    )


async def test_signed_cookie_persists_identity_across_clients(
    client, client_factory, db_session
):
    first = await client.get("/v1/pool/auth/session")
    visitor = client.cookies[COOKIE_NAME]
    cookie_header = first.headers["set-cookie"].lower()
    assert "httponly" in cookie_header
    assert "samesite=lax" in cookie_header
    assert "path=/" in cookie_header
    assert f"max-age={MAX_AGE}" in cookie_header

    again = await client.get("/v1/pool/auth/session")
    assert again.json()["user"] == first.json()["user"]
    assert "set-cookie" not in again.headers
    async with client_factory(cookies={COOKIE_NAME: visitor}) as restored:
        response = await restored.get("/v1/pool/auth/session")
    assert response.json()["user"] == first.json()["user"]
    users = (await db_session.execute(select(User))).scalars().all()
    assert len(users) == 1
    assert users[0].wechat_openid == "anon:" + visitor.partition(".")[0]
    assert users[0].login_source == "anonymous"


async def test_production_visitor_cookie_is_secure(client, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    response = await client.get("/v1/pool/auth/session")
    assert response.status_code == 200
    assert "secure" in response.headers["set-cookie"].lower()


async def test_visitors_keep_separate_subscriptions(client, client_factory):
    created = await client.post(
        "/v1/pool/subscriptions", json={"title": "owner", "query_text": "exercise"}
    )
    assert created.status_code == 201
    subscription_id = created.json()["id"]
    own = await client.get("/v1/pool/subscriptions")
    assert own.json()["total"] == 1

    async with client_factory() as other:
        listing = await other.get("/v1/pool/subscriptions")
        assert listing.json() == {"subscriptions": [], "total": 0}
        assert other.cookies[COOKIE_NAME] != client.cookies[COOKIE_NAME]
        for method, kwargs in [
            ("GET", {}),
            ("PATCH", {"json": {"title": "other"}}),
            ("DELETE", {}),
        ]:
            response = await other.request(
                method, f"/v1/pool/subscriptions/{subscription_id}", **kwargs
            )
            assert response.status_code == 404
    still_owned = await client.get(f"/v1/pool/subscriptions/{subscription_id}")
    assert still_owned.status_code == 200
    assert still_owned.json()["title"] == "owner"


@pytest.mark.parametrize("tamper", ["identifier", "signature", "malformed"])
async def test_tampered_cookie_receives_new_identity(client, client_factory, tamper):
    original = await client.get("/v1/pool/auth/session")
    identifier, _, signature = client.cookies[COOKIE_NAME].partition(".")
    replace_first = lambda value: ("A" if value[0] != "A" else "B") + value[1:]
    forged = {
        "identifier": replace_first(identifier) + "." + signature,
        "signature": identifier + "." + replace_first(signature),
        "malformed": "unsigned-visitor",
    }[tamper]
    async with client_factory(cookies={COOKIE_NAME: forged}) as other:
        response = await other.get("/v1/pool/auth/session")
        assert response.status_code == 200
        assert response.json()["user"]["is_guest"] is True
        assert response.json()["user"]["id"] != original.json()["user"]["id"]
        assert COOKIE_NAME + "=" in response.headers["set-cookie"]
        again = await other.get("/v1/pool/auth/session")
        assert again.json()["user"] == response.json()["user"]


@pytest.mark.parametrize("source", ["header", "cookie"])
async def test_valid_login_keeps_existing_user_and_data(
    client, test_user, test_user_token, test_subscription, source
):
    headers = {}
    if source == "header":
        headers["Authorization"] = f"Bearer {test_user_token}"
    else:
        client.cookies.set("auth_token", test_user_token)
    session = await client.get("/v1/pool/auth/session", headers=headers)
    assert session.status_code == 200
    assert session.json()["user"]["id"] == test_user.id
    assert session.json()["user"]["is_guest"] is False
    listing = await client.get("/v1/pool/subscriptions", headers=headers)
    assert [item["id"] for item in listing.json()["subscriptions"]] == [
        test_subscription.id
    ]


@pytest.mark.parametrize("source", ["header", "cookie"])
async def test_invalid_login_falls_back_on_first_request(client, source):
    headers = {}
    if source == "header":
        headers["Authorization"] = "Bearer invalid_token_123"
    else:
        client.cookies.set("auth_token", "invalid_token_123")
    first = await client.get("/v1/pool/auth/session", headers=headers)
    assert first.status_code == 200
    assert first.json()["user"]["is_guest"] is True
    second = await client.get("/v1/pool/auth/session", headers=headers)
    assert second.json()["user"] == first.json()["user"]


@pytest.mark.parametrize(
    "case", ["expired", "missing_user", "inactive", "shared_guest"]
)
async def test_unusable_login_returns_current_visitor(
    client, db_session, test_user, case
):
    visitor = (await client.get("/v1/pool/auth/session")).json()["user"]
    user_id = test_user.id
    if case == "inactive":
        test_user.is_active = False
    elif case == "shared_guest":
        test_user.wechat_openid = "public_guest"
    elif case == "missing_user":
        user_id += 100000
    await db_session.commit()
    if case == "expired":
        token = jwt.encode(
            {"sub": str(user_id), "exp": datetime(2000, 1, 1, tzinfo=timezone.utc)},
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
    else:
        token = AuthService(db_session).create_jwt_token(user_id)
    response = await client.get(
        "/v1/pool/auth/session", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["user"] == visitor
    assert visitor["id"] != test_user.id


async def test_concurrent_first_requests_reuse_one_anonymous_user(
    client, client_factory, db_session
):
    # The real middleware signs a cookie before any anonymous user row exists.
    assert (await client.get("/health")).status_code == 200
    cookie = client.cookies[COOKIE_NAME]
    assert await db_session.scalar(select(func.count()).select_from(User)) == 0
    await db_session.rollback()

    async def request_session():
        async with client_factory(cookies={COOKIE_NAME: cookie}) as browser:
            response = await browser.get("/v1/pool/auth/session")
            assert response.status_code == 200
            return response.json()["user"]["id"]

    ids = await asyncio.gather(*(request_session() for _ in range(12)))
    assert len(set(ids)) == 1
    assert await db_session.scalar(select(func.count()).select_from(User)) == 1


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/qq/login"),
        ("GET", "/qq/callback"),
        ("GET", "/wechat/login"),
        ("GET", "/wechat/callback"),
        ("POST", "/dev/login"),
        ("POST", "/invite/redeem"),
    ],
)
async def test_retired_login_endpoints_report_public_access(client, method, path):
    response = await client.request(method, "/v1/pool/auth" + path)
    assert response.status_code == 410
    assert response.json()["detail"]["code"] == "PUBLIC_ACCESS"
