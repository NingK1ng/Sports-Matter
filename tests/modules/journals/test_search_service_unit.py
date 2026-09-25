"""
SearchService 单元测试（不依赖数据库）
验证 PubMed-like 语法编译为 tsquery
"""
import pytest

from modules.journals.services.search_service import SearchService
from core.search_query import QueryParseError


class DummySession:
    async def execute(self, *args, **kwargs):
        raise NotImplementedError


@pytest.fixture
def svc():
    return SearchService(session=DummySession())


def test_preprocess_allows_hyphen_and_quotes(svc: SearchService):
    q = 'COVID-19 "oxidative stress" muscle & strength'
    cleaned = svc.preprocess_query(q)
    # 保留连字符与引号与布尔运算符
    assert 'COVID-19' in cleaned
    assert '"oxidative stress"' in cleaned
    assert '&' in cleaned


def test_build_tsquery_phrase(svc: SearchService):
    sql, params = svc.build_tsquery('"oxidative stress"')
    assert 'to_tsquery' in sql
    assert 'unaccent' in sql
    assert "<->" in params["kw"]


def test_build_tsquery_boolean(svc: SearchService):
    sql, params = svc.build_tsquery('muscle & strength')
    assert 'to_tsquery' in sql
    assert 'unaccent' in sql
    assert "muscle" in params["kw"]
    assert "strength" in params["kw"]
    assert "&" in params["kw"]


def test_build_tsquery_plain(svc: SearchService):
    sql, params = svc.build_tsquery('muscle strength power')
    assert 'to_tsquery' in sql
    assert 'unaccent' in sql
    assert "muscle" in params["kw"]
    assert "strength" in params["kw"]
    assert "power" in params["kw"]
    assert "&" in params["kw"]


def test_build_tsquery_pubmed_and_or_not(svc: SearchService):
    sql, params = svc.build_tsquery('(muscle OR strength) NOT injury')
    assert 'to_tsquery' in sql
    assert "|" in params["kw"]
    assert "!" in params["kw"]


def test_build_tsquery_pubmed_prefix_wildcard(svc: SearchService):
    _, params = svc.build_tsquery('exercise*')
    assert ":*" in params["kw"]


def test_build_tsquery_allows_tiab_field_tag(svc: SearchService):
    _, params = svc.build_tsquery('injury[tiab] AND athlete[tiab]')
    assert "injury" in params["kw"]
    assert "athlete" in params["kw"]
    assert "AND" not in params["kw"]


def test_build_tsquery_rejects_other_field_tags(svc: SearchService):
    with pytest.raises(QueryParseError):
        svc.build_tsquery("injury[ti] AND athlete")
