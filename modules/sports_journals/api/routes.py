"""FastAPI routes for sports_journals module."""

from __future__ import annotations

import re
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Integer, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from modules.literature_pool.api.auth import is_member_user
from modules.literature_stream.models.literature import Literature
from modules.literature_stream.models.literature import JournalMetadata
from modules.sports_journals.models.dto import (
    SportsJournalDetail,
    SportsJournalListResponse,
)
from modules.sports_journals.services.service import (
    get_journal_detail,
    list_journals,
)
from modules.literature_pool.api.auth import require_login_user


router = APIRouter(prefix="/sports-journals", tags=["sports-journals"])

ISSN_RE = re.compile(r"\b\d{4}-\d{3}[\dXx]\b")


def _extract_issns(value: str | None) -> list[str]:
    if not value:
        return []
    found = ISSN_RE.findall(value)
    if found:
        return [x.upper() for x in found]
    return [value.strip()]


async def _resolve_issn_aliases(primary_issns: set[str], db: AsyncSession) -> dict[str, list[str]]:
    """Map a primary ISSN to all ISSN aliases for the same journal.

    We use journal_metadata as the source of truth because literature.journal_issn
    may store eISSN/ISSN-L while LetPub often returns print ISSN.
    """

    if not primary_issns:
        return {}

    meta_query = (
        select(JournalMetadata.issn, JournalMetadata.nlm_abbr, JournalMetadata.full_name)
        .where(JournalMetadata.issn.in_(sorted(primary_issns)))
    )
    meta_res = await db.execute(meta_query)
    meta_rows = meta_res.all()
    if not meta_rows:
        return {}

    by_issn: dict[str, tuple[str | None, str | None]] = {}
    nlm_abbrs: set[str] = set()
    full_names: set[str] = set()
    for issn, nlm_abbr, full_name in meta_rows:
        if not issn:
            continue
        abbr = str(nlm_abbr).strip() if nlm_abbr else None
        name = str(full_name).strip() if full_name else None
        by_issn[str(issn).upper()] = (abbr, name)
        if abbr:
            nlm_abbrs.add(abbr)
        if name:
            full_names.add(name)

    conditions = []
    if nlm_abbrs:
        conditions.append(JournalMetadata.nlm_abbr.in_(sorted(nlm_abbrs)))
    if full_names:
        conditions.append(JournalMetadata.full_name.in_(sorted(full_names)))
    if not conditions:
        return {}

    alias_query = select(JournalMetadata.issn, JournalMetadata.nlm_abbr, JournalMetadata.full_name).where(
        or_(*conditions)
    )
    alias_res = await db.execute(alias_query)

    aliases_by_abbr: dict[str, set[str]] = {}
    aliases_by_name: dict[str, set[str]] = {}
    for issn, nlm_abbr, full_name in alias_res.all():
        if not issn:
            continue
        issn_u = str(issn).upper()
        abbr = str(nlm_abbr).strip() if nlm_abbr else None
        name = str(full_name).strip() if full_name else None
        if abbr:
            aliases_by_abbr.setdefault(abbr, set()).add(issn_u)
        if name:
            aliases_by_name.setdefault(name, set()).add(issn_u)

    alias_map: dict[str, list[str]] = {}
    for issn, (abbr, name) in by_issn.items():
        alias_set: set[str] = set()
        if abbr:
            alias_set.update(aliases_by_abbr.get(abbr, set()))
        if name:
            alias_set.update(aliases_by_name.get(name, set()))
        if not alias_set:
            alias_set.add(issn)
        alias_map[issn] = sorted({x for x in alias_set if x})

    return alias_map


async def _attach_literature_stats(items, db: AsyncSession) -> None:
    if not items:
        return

    item_issns: dict[str, list[str]] = {}
    primary_issns: set[str] = set()
    for it in items:
        issns = _extract_issns(getattr(it, "issn", None))
        if not issns:
            continue
        normalized = [str(x).strip().upper() for x in issns if x and str(x).strip()]
        if not normalized:
            continue
        item_issns[str(getattr(it, "id", ""))] = normalized
        for x in issns:
            if x:
                primary_issns.add(str(x).strip().upper())

    if not primary_issns:
        return

    alias_map = await _resolve_issn_aliases(primary_issns, db)

    all_issns: set[str] = set()
    item_aliases: dict[str, list[str]] = {}
    for it in items:
        it_id = str(getattr(it, "id", ""))
        issns = item_issns.get(it_id) or _extract_issns(getattr(it, "issn", None))
        aliases: set[str] = set()
        for x in issns or []:
            if not x:
                continue
            aliases.update(alias_map.get(str(x).upper(), [str(x).upper()]))
        if not aliases:
            continue
        alias_list = sorted(aliases)
        item_aliases[it_id] = alias_list
        for x in alias_list:
            if x:
                all_issns.add(x)

    if not all_issns:
        return

    # 与「文献上新」默认规则对齐：隐藏明确标记为 non_research 的文献
    base_filters = [
        Literature.is_deleted == False,
        Literature.publication_date.is_not(None),
        Literature.journal_issn.in_(sorted(all_issns)),
        or_(
            Literature.literature_types.is_(None),
            ~Literature.literature_types.contains(["non_research"]),
        ),
    ]

    # 近两年（滚动 730 天）相关文章数
    start_2y = date.today() - timedelta(days=730)
    two_year_query = (
        select(Literature.journal_issn, func.count())
        .where(*base_filters, Literature.publication_date >= start_2y)
        .group_by(Literature.journal_issn)
    )
    two_year_res = await db.execute(two_year_query)
    two_year_map: dict[str, int] = {r[0]: int(r[1]) for r in two_year_res.all() if r and r[0]}

    # 2020-2025 年文章数
    years = [2020, 2021, 2022, 2023, 2024, 2025]
    year_expr = func.extract("year", Literature.publication_date).cast(Integer)
    yearly_query = (
        select(Literature.journal_issn, year_expr.label("y"), func.count())
        .where(
            *base_filters,
            Literature.publication_date >= date(2020, 1, 1),
            Literature.publication_date <= date(2025, 12, 31),
            year_expr.in_(years),
        )
        .group_by(Literature.journal_issn, year_expr)
    )
    yearly_res = await db.execute(yearly_query)
    yearly_map: dict[tuple[str, int], int] = {}
    for issn, y, cnt in yearly_res.all():
        if not issn or y is None:
            continue
        yearly_map[(str(issn), int(y))] = int(cnt)

    for it in items:
        it_id = str(getattr(it, "id", ""))
        issns = item_aliases.get(it_id) or item_issns.get(it_id) or _extract_issns(getattr(it, "issn", None))
        if not issns:
            continue

        it.literature_count = sum(two_year_map.get(x, 0) for x in issns)
        it.yearly_counts = {str(y): sum(yearly_map.get((x, y), 0) for x in issns) for y in years}
        it.issn_aliases = issns


@router.get("/list", response_model=SportsJournalListResponse)
async def list_sports_journals(
    q: str | None = Query(None, description="关键词（期刊名或ISSN，模糊匹配)"),
    cas_partition: str | None = Query(
        None,
        description="中科院分区：1区|2区|3区|4区，或省略表示全部",
    ),
    oa_type: str | None = Query(
        None,
        description=(
            "OA类型：oa（纯OA期刊）|non_oa（非OA期刊）|hybrid（Hybrid OA），或省略表示全部"
        ),
    ),
    category: str | None = Query(
        None,
        description="期刊类别：sports_science（运动科学专刊）|high_volume（高领域发文期刊），或省略表示全部",
    ),
    page: int = Query(1, ge=1, description="页码，从1开始"),
    per_page: int = Query(10, ge=1, le=100, description="每页数量"),
    db: AsyncSession = Depends(get_db),
    user=Depends(require_login_user),
) -> SportsJournalListResponse:
    """Return paginated list of sports journals.

    All filtering is done in memory based on local JSON data.
    """

    if category == "high_volume" and not is_member_user(user):
        raise HTTPException(
            status_code=403,
            detail={"code": "MEMBERSHIP_REQUIRED", "message": "会员才能解锁「文献上新高频期刊」"},
        )

    resp = list_journals(
        q=q,
        cas_partition=cas_partition,
        oa_type=oa_type,
        category=category,
        page=page,
        per_page=per_page,
    )
    await _attach_literature_stats(resp.items, db)
    return resp


@router.get("/{journal_id}", response_model=SportsJournalDetail)
async def get_sports_journal_detail(
    journal_id: str,
    _user=Depends(require_login_user),
) -> SportsJournalDetail:
    """Return detailed info for a single journal."""

    detail = get_journal_detail(journal_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Journal not found")
    return detail
