import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def test_search_relevance_tiab_smoke():
    # 仅验证端到端请求路径（数据库可能为空，但应返回 200）
    resp = client.get(
        "/v1/stream/literature",
        params={
            "keywords": "\"oxidative stress\"",
            "search_scope": "tiab",
            "sort_by": "relevance",
            "page": 1,
            "per_page": 1,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data and "items" in data


def test_search_boolean_ti_smoke():
    resp = client.get(
        "/v1/stream/literature",
        params={
            "keywords": "muscle & strength",
            "search_scope": "ti",
            "page": 1,
            "per_page": 1,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data and "items" in data


def test_search_pubmed_syntax_tiab_smoke():
    resp = client.get(
        "/v1/stream/literature",
        params={
            "keywords": '(muscle OR strength) AND injury[tiab] NOT pediatric',
            "search_scope": "tiab",
            "page": 1,
            "per_page": 1,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data and "items" in data





















