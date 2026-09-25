"""Data transfer objects for sports_journals module.

This module does NOT define SQLAlchemy ORM models yet.
For now we load data from JSON (data/sports_journals_enriched.json)
into these Pydantic models.

Later, if we decide to persist to PostgreSQL, we can mirror these
structures in proper SQLAlchemy models and an Alembic migration.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, HttpUrl


class ChinaPaper(BaseModel):
    title: str
    authors: str
    journal_info: str
    doi_text: Optional[str] = None
    doi_url: Optional[HttpUrl] = None
    pubmed_url: Optional[HttpUrl] = None
    letpub_article_url: Optional[HttpUrl] = None


class SportsJournalBase(BaseModel):
    """Shared fields between list and detail views."""

    id: str  # LetPub journalid
    name: str
    url: HttpUrl
    issn: str
    # 同刊ISSN别名（print/eISSN/ISSN-L 等），用于与 literature.journal_issn 对齐统计口径
    issn_aliases: Optional[List[str]] = None

    # 分类与来源
    category: Optional[str] = None  # sports_science | high_volume
    source: Optional[str] = None  # manual | letpub_literature

    # 文章数量（来自 literature 模块统计）
    literature_count: Optional[int] = None
    # 年文章数趋势（来自 literature 模块统计，2020-2025）
    yearly_counts: Optional[Dict[str, int]] = None

    # existing list-level fields from LetPub search result
    score: Optional[str] = None
    cas_partition: Optional[str] = None
    subject: Optional[str] = None
    sci_index: Optional[str] = None
    is_oa: Optional[str] = None
    acceptance: Optional[str] = None
    review_time: Optional[str] = None

    # enriched fields
    year_articles: Optional[int] = None
    wos_category: Optional[str] = None
    wos_jif_quartile: Optional[str] = None
    wos_jif_rank: Optional[str] = None
    wos_jif_percentile: Optional[float] = None
    cas_warning_summary: Optional[str] = None


class SportsJournalListItem(SportsJournalBase):
    """Fields used in list view (no heavy nested structures)."""

    pass


class SportsJournalDetail(SportsJournalBase):
    """Full detail view used when expanding a journal card."""

    official_site: Optional[HttpUrl] = None
    submission_site: Optional[HttpUrl] = None
    guidelines_site: Optional[HttpUrl] = None

    publisher: Optional[str] = None
    founded_year: Optional[int] = None
    publish_frequency: Optional[str] = None

    gold_oa_percent: Optional[float] = None
    research_article_percent: Optional[float] = None
    pmc_link: Optional[str] = None

    china_recent_papers: List[ChinaPaper] = []


class SportsJournalListResponse(BaseModel):
    total: int
    page: int
    per_page: int
    pages: int
    items: List[SportsJournalListItem]
