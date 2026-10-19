# Public access regression tests

Run from the repository root (Python 3.11+):

```bash
python -m pip install -r tests/test_literature_pool/requirements.txt
python -m pytest tests/test_literature_pool
```

The default backend is a fresh, file-backed SQLite database for each test.
Each HTTP request and concurrent quota consumer receives its own SQLAlchemy
session/connection. The app's real routers, visitor middleware, JWT verification,
anonymous-user UPSERT, and quota UPSERT run unchanged through HTTPX ASGITransport.
The fixture supplies test settings and does not run the application's lifespan.
Outbound sockets are blocked, subscription search task dispatch is mocked, and
tests of paid operations replace the translator or return a local search cache.
No production database, Redis, broker, PubMed, Tavily, or model API is used.

SQLite adaptations are limited to a copy of the schema metadata for unrelated
PostgreSQL column types/defaults. They are not proof of PostgreSQL row-lock
behavior. Use the PostgreSQL backend to validate the production dialect and
concurrent UPSERTs:

```bash
# Create a disposable local PostgreSQL instance, for example:
docker run --rm --name sports-matter-test-db \
  -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=test-only \
  -e POSTGRES_DB=sports_matter_test -p 127.0.0.1:55432:5432 postgres:16

# In another terminal, after the database is ready:
SPORTS_MATTER_TEST_DATABASE_URL=postgresql://postgres:test-only@127.0.0.1:55432/sports_matter_test \
  python -m pytest tests/test_literature_pool
```

The explicit test URL must use a loopback host and the database name
`sports_matter_test`; the fixture never reads the production `DATABASE_URL`.
Each test creates and drops only its own randomly named `pool_test_*` schema.
The PostgreSQL user needs permission to create schemas in this disposable
database. No existing tables are dropped or truncated.

The suite preserves the existing JWT, user, subscription CRUD, health, and feed
checks. Old missing/invalid-token rejection checks now verify public access and
anonymous fallback. The removed three-subscription cap is checked as unlimited
access, and the ordering test uses explicit timestamps to avoid second-resolution
ties on SQLite.

New coverage includes:

- Public session response and both `/v1` and `/api/v1` prefixes.
- Signed visitor-cookie persistence, separate visitors, tampering, secure cookie
  attributes, and concurrent first requests for the same visitor.
- Existing valid JWTs, invalid/expired JWTs, missing/inactive accounts, and the
  retired shared guest/login endpoints.
- All seven daily feature allowances: ten successes, denial without increment,
  independent user/feature budgets, read-only usage, and preserved weekly/history
  counters.
- Real HTTP 429 details, handler short-circuiting, cached translations after
  exhaustion, and the Beijing 23:59:59 → 00:00:00 reset, including year boundaries.
- Twenty-five concurrent consumers starting with zero or nine uses; the stored
  count must stop at ten and both admitted and denied transactions must close.

These are isolated regression results, not a production smoke test or a claim
about the deployed service. The GitHub Actions workflow uses a disposable native
PostgreSQL 16 service and requires no repository secrets.
