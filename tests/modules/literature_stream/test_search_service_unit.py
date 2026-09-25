import pytest

from modules.literature_stream.services.search_service import LiteratureSearchService
from core.search_query import QueryParseError


@pytest.fixture()
def svc():
    return LiteratureSearchService()


def test_preprocess_keeps_ops_and_quotes_and_hyphen(svc):
    cleaned = svc.preprocess_query('muscle-strength & "oxidative stress" | !injury')
    assert 'muscle-strength' in cleaned
    assert '"oxidative stress"' in cleaned
    assert '&' in cleaned and '|' in cleaned and '!' in cleaned


def test_build_tsquery_phrase(svc):
    sql, params = svc.build_tsquery('"oxidative stress"')
    assert 'to_tsquery' in sql
    assert "<->" in params["kw"]


def test_build_tsquery_boolean(svc):
    sql, params = svc.build_tsquery('muscle & strength')
    assert 'to_tsquery' in sql
    assert "muscle" in params["kw"]
    assert "strength" in params["kw"]
    assert "&" in params["kw"]


def test_build_tsquery_plain(svc):
    sql, params = svc.build_tsquery('muscle strength power')
    assert 'to_tsquery' in sql
    assert "muscle" in params["kw"]
    assert "strength" in params["kw"]
    assert "power" in params["kw"]
    assert "&" in params["kw"]


def test_build_tsquery_pubmed_and_or_not(svc):
    _, params = svc.build_tsquery('(muscle OR strength) NOT injury')
    assert "|" in params["kw"]
    assert "!" in params["kw"]


def test_build_tsquery_pubmed_prefix_wildcard(svc):
    _, params = svc.build_tsquery('exercise*')
    assert ":*" in params["kw"]


def test_build_tsquery_allows_tiab_field_tag(svc):
    _, params = svc.build_tsquery('injury[tiab] AND athlete[tiab]')
    assert "injury" in params["kw"]
    assert "athlete" in params["kw"]


def test_build_tsquery_rejects_other_field_tags(svc):
    with pytest.raises(QueryParseError):
        svc.build_tsquery("injury[ti] AND athlete")





















