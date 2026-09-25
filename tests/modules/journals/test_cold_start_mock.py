"""
冷启动脚本/爬虫冷启动路径的模拟测试（无网络、无真实DB）

目标：验证对十几本期刊（配置文件）均能完成分页抓取与解析、入库调用链（通过patch upsert）无异常。
"""
import asyncio
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml

from modules.journals.services.crawler import JournalCrawler
from modules.journals.services.crossref_client import CrossrefJournalClient


class FakeSession:
    async def commit(self):
        return None

    async def execute(self, *args, **kwargs):
        class _R:
            def scalars(self):
                class _S:
                    def all(self):
                        return []

                    def first(self):
                        return None

                return _S()

        return _R()


class FakeCrossrefClient:
    """模拟Crossref客户端，仅返回伪造的分页数据，并复用真实parse_article。"""

    def __init__(self):
        self.page = 0
        self._parser = CrossrefJournalClient()  # 仅用于parse_article，不会发网络

    def _make_item(self, doi: str, title: str, issn: str, journal_name: str) -> Dict[str, Any]:
        return {
            "DOI": doi,
            "title": [title],
            "abstract": "<jats:p>Sample abstract</jats:p>",
            "author": [],
            "published-online": {"date-parts": [[2024, 10, 1]]},
            "indexed": {"date-time": "2024-10-02T12:34:56Z"},
            "ISSN": [issn],
            "container-title": [journal_name],
        }

    async def search_by_issn_pub_date(self, issn: str, from_pub_date: str, cursor: str = "*", rows: int = 100, **kwargs):
        # 两页：第一页2条，第二页1条，然后结束
        self.page += 1
        if self.page == 1:
            items = [
                self._make_item(f"10.1234/{issn}.p1", f"Title p1 a ({issn})", issn, "Journal X"),
                self._make_item(f"10.1234/{issn}.p2", f"Title p1 b ({issn})", issn, "Journal X"),
            ]
            return {"items": items, "next_cursor": "cursor-2", "total_results": 3}
        elif self.page == 2:
            items = [
                self._make_item(f"10.1234/{issn}.p3", f"Title p2 a ({issn})", issn, "Journal X"),
            ]
            return {"items": items, "next_cursor": None, "total_results": 3}
        else:
            return {"items": [], "next_cursor": None, "total_results": 3}

    def parse_article(self, item: Dict[str, Any]) -> Dict[str, Any] | None:
        return self._parser.parse_article(item)


@pytest.fixture(autouse=True)
def no_asyncio_sleep(monkeypatch):
    async def _sleep(*args, **kwargs):
        return None
    monkeypatch.setattr(asyncio, "sleep", _sleep)


@pytest.mark.asyncio
async def test_cold_start_crawl_all_journals_mocked():
    # 读取配置，拿到13本期刊
    project_root = Path(__file__).resolve().parents[3]
    cfg_file = project_root / "config" / "journals-tracking" / "journals.yaml"
    with open(cfg_file, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    journals: List[Dict[str, Any]] = cfg["journals"]
    assert len(journals) >= 13

    # 准备爬虫（替换client为fake，替换upsert与更新状态为no-op）
    session = FakeSession()
    crawler = JournalCrawler(session)
    crawler.client = FakeCrossrefClient()

    # 记录入库调用次数
    upserts: List[Dict[str, Any]] = []

    async def _fake_upsert(**kwargs):
        upserts.append(kwargs)
        return True  # 视为新增

    async def _fake_update_state(*args, **kwargs):
        return None

    crawler._upsert_article = _fake_upsert  # type: ignore
    crawler._update_crawl_state = _fake_update_state  # type: ignore

    # 对前13本逐个执行 _crawl_articles（等价于冷启动内部逻辑的核心抓取）
    totals = []
    for j in journals[:13]:
        # 确保每个期刊都有新的fake客户端（分页状态重置）
        crawler.client = FakeCrossrefClient()
        stats = await crawler._crawl_articles(
            issn_l=j["issn_l"],
            issn_query=j.get("issn_electronic") or j["issn_l"],
            category=j["category"],
            journal_name=j["display_name"],
            from_pub_date="2020-01-01",
            use_pub_date=True,
        )
        # 两页共3条 → total=3, new=3, updated=0
        assert stats["total"] == 3
        assert stats["new"] == 3
        assert stats["updated"] == 0
        totals.append(stats)

    # 确认13本均无异常
    assert len(totals) == 13
    # 至少有 13*3 次 upsert 调用
    assert len(upserts) >= 39
