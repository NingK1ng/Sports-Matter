"""Isolated database and in-process HTTP fixtures; no live services are used."""

import os
import socket
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import (
    BigInteger,
    DefaultClause,
    Integer,
    JSON,
    MetaData,
    Text,
    event,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# Supply required settings before importing the app, even on a clean checkout.
# These deliberately unusable service addresses never come from a local .env.
for key, value in {
    "DATABASE_URL": "postgresql://test:test@127.0.0.1:1/sports_matter_test",
    "CELERY_BROKER_URL": "memory://",
    "CELERY_RESULT_BACKEND": "cache+memory://",
    "PUBMED_EMAIL": "tests@example.invalid",
    "SECRET_KEY": "sports-matter-tests-only",
    "JWT_SECRET_KEY": "sports-matter-tests-only",
    "APP_ENV": "test",
}.items():
    os.environ[key] = value

from api.main import app as application
from core.config import settings
from core.database import get_db
from modules.journals.models.journal import JournalArticle
from modules.literature_pool.models.article import PoolArticle
from modules.literature_pool.models.feature_usage_counter import FeatureUsageCounter
from modules.literature_pool.models.subscription import PoolSubscription
from modules.literature_pool.models.user import User
from modules.literature_pool.models.wiw_card import PoolWiWCard
from modules.literature_pool.services.auth_service import AuthService
from modules.literature_stream.models.literature import Literature
from modules.research_gap.models.wiw import WiWResult


@pytest.fixture
def database_url(tmp_path):
    """Default to a temporary SQLite file, or explicitly opt into local test PG."""
    configured = os.getenv("SPORTS_MATTER_TEST_DATABASE_URL")
    if not configured:
        return make_url(f"sqlite+aiosqlite:///{tmp_path / 'pool-test.sqlite'}")
    url = make_url(configured)
    if (
        url.get_backend_name() != "postgresql"
        or url.host not in {"localhost", "127.0.0.1", "::1"}
        or url.database != "sports_matter_test"
        or url.query
    ):
        pytest.fail(
            "Use a loopback PostgreSQL database named sports_matter_test (no URL query)."
        )
    return url.set(drivername="postgresql+asyncpg")


@pytest.fixture(autouse=True)
def isolated_services(monkeypatch, database_url):
    """Fail closed on outbound networking, except the explicitly selected test PG."""
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    pg_port = (
        (database_url.port or 5432)
        if database_url.get_backend_name() == "postgresql"
        else None
    )

    def check_address(address):
        if not (
            pg_port is not None
            and isinstance(address, tuple)
            and address[0] in {"127.0.0.1", "::1"}
            and address[1] == pg_port
        ):
            raise AssertionError(
                "External network access is forbidden in literature-pool tests"
            )

    def connect(sock, address):
        check_address(address)
        return original_connect(sock, address)

    def connect_ex(sock, address):
        check_address(address)
        return original_connect_ex(sock, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(settings, "app_env", "test")
    monkeypatch.setattr(settings, "jwt_secret_key", "sports-matter-tests-only")

    from core import database
    from modules.literature_pool.tasks.search_tasks import search_stream_articles_task

    monkeypatch.setattr(
        database,
        "init_database",
        AsyncMock(side_effect=AssertionError("Use the test session factory")),
    )
    # Creating a subscription must not dispatch a worker or search PubMed.
    monkeypatch.setattr(search_stream_articles_task, "delay", Mock())


@pytest.fixture
async def session_factory(database_url):
    """Separate sessions per request/worker, with a fresh database/schema per test."""
    options = {"poolclass": NullPool}
    schema = None
    if database_url.get_backend_name() == "postgresql":
        schema = "pool_test_" + uuid4().hex
        options["connect_args"] = {"server_settings": {"search_path": schema}}
    else:
        options["connect_args"] = {"timeout": 30}
    engine = create_async_engine(database_url, **options)

    if schema is None:

        @event.listens_for(engine.sync_engine, "connect")
        def sqlite_foreign_keys(connection, _):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    # Only create the tables used here. SQLite adaptations apply to a COPY of
    # metadata; production mappings and the real auth/quota UPSERTs stay intact.
    metadata = MetaData()
    for model in (
        User,
        PoolSubscription,
        FeatureUsageCounter,
        Literature,
        WiWResult,
        JournalArticle,
        PoolArticle,
        PoolWiWCard,
    ):
        table = model.__table__.to_metadata(metadata)
        if schema is None:
            for column in table.columns:
                if isinstance(column.type, (ARRAY, JSONB)):
                    column.type = JSON()
                elif isinstance(column.type, TSVECTOR):
                    column.type = Text()
                elif isinstance(column.type, BigInteger):
                    column.type = Integer()
                if (
                    column.server_default is not None
                    and str(column.server_default.arg).upper() == "NOW()"
                ):
                    column.server_default = DefaultClause(text("CURRENT_TIMESTAMP"))

    schema_created = False
    try:
        async with engine.begin() as connection:
            if schema:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.run_sync(metadata.create_all)
        schema_created = schema is not None
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    finally:
        try:
            if schema_created:
                async with engine.begin() as connection:
                    await connection.execute(
                        text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
                    )
        finally:
            await engine.dispose()


@pytest.fixture
async def db_session(session_factory):
    async with session_factory() as session:
        yield session


@pytest.fixture
def app(session_factory):
    async def override_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    previous = application.dependency_overrides.copy()
    application.dependency_overrides[get_db] = override_db
    try:
        yield application
    finally:
        application.dependency_overrides.clear()
        application.dependency_overrides.update(previous)


@pytest.fixture
def client_factory(app):
    # ASGITransport exercises the real routes/middleware without app lifespan,
    # TCP requests, global database initialization, Redis, or worker startup.
    return lambda **kwargs: httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", **kwargs
    )


@pytest.fixture
async def client(client_factory):
    async with client_factory() as instance:
        yield instance


@pytest.fixture
def quota_clock(monkeypatch):
    from modules.literature_pool.services import daily_quota_service

    clock = SimpleNamespace(now=datetime(2026, 10, 19, 4, tzinfo=timezone.utc))

    class ClockDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock.now.astimezone(tz) if tz else clock.now.replace(tzinfo=None)

    monkeypatch.setattr(daily_quota_service, "datetime", ClockDateTime)
    return clock


@pytest.fixture
async def test_user(db_session):
    user = User(
        wechat_openid="test_openid_fixture",
        wechat_nickname="测试用户",
        login_source="wechat_open",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def test_user_token(db_session, test_user):
    return AuthService(db_session).create_jwt_token(test_user.id)


@pytest.fixture
async def test_subscription(db_session, test_user):
    subscription = PoolSubscription(
        user_id=test_user.id, title="测试订阅", query_text="test query", is_active=1
    )
    db_session.add(subscription)
    await db_session.commit()
    await db_session.refresh(subscription)
    return subscription


@pytest.fixture
def test_subscription_id(test_subscription):
    return test_subscription.id
