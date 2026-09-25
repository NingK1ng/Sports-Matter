"""Service layer for sports_journals.

For now this module loads data from a local JSON file and performs
filtering / pagination in memory. This keeps things simple while the
feature is prototyped. Later we can swap to PostgreSQL-backed models
without changing the API surface.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Iterable, List, Optional

import json

from modules.sports_journals.models.dto import (
    SportsJournalBase,
    SportsJournalDetail,
    SportsJournalListItem,
    SportsJournalListResponse,
)

# Dynamically locate the project root (directory that contains both
# `modules/` and `data/`). This works in local dev and inside Docker.
CURRENT_FILE = Path(__file__).resolve()
BASE_DIR: Path | None = None
for ancestor in CURRENT_FILE.parents:
    if (ancestor / "modules").is_dir() and (ancestor / "data").is_dir():
        BASE_DIR = ancestor
        break

if BASE_DIR is None:
    # Fallback: assume three levels up (best effort)
    BASE_DIR = CURRENT_FILE.parents[2]

DATA_PATH = BASE_DIR / "data" / "sports_journals_enriched.json"


@lru_cache(maxsize=1)
def _load_all() -> List[SportsJournalBase]:
    if not DATA_PATH.exists():
        raise RuntimeError(f"sports_journals data file not found: {DATA_PATH}")
    with DATA_PATH.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    items: List[SportsJournalBase] = []
    for obj in raw:
        try:
            items.append(SportsJournalBase(**obj))
        except Exception:
            # If validation fails, skip that journal but keep going
            continue
    return items


def list_journals(
    q: Optional[str] = None,
    cas_partition: Optional[str] = None,
    oa_type: Optional[str] = None,
    category: Optional[str] = None,
    page: int = 1,
    per_page: int = 10,
) -> SportsJournalListResponse:
    """Filter journals in memory and return a paginated list."""

    items = _load_all()

    def _matches(j: SportsJournalBase) -> bool:
        if q:
            q_low = q.lower()
            if q_low not in j.name.lower() and q_low not in (j.issn or "").lower():
                return False
        if cas_partition and cas_partition != "all":
            if not j.cas_partition or cas_partition not in j.cas_partition:
                return False
        if oa_type and oa_type != "all":
            val = (j.is_oa or "").strip().lower()
            if oa_type == "oa" and val != "yes":
                return False
            if oa_type == "non_oa" and val != "no":
                return False
            if oa_type == "hybrid" and "hybrid" not in val:
                return False
        if category and category != "all":
            j_cat = (j.category or "").strip()
            if j_cat != category:
                return False
        return True

    filtered: List[SportsJournalBase] = [j for j in items if _matches(j)]

    # 默认排序：按中科院分区优先级 + score 降序
    def _cas_priority(cp: Optional[str]) -> int:
        if not cp:
            return 99
        if "1" in cp:
            return 1
        if "2" in cp:
            return 2
        if "3" in cp:
            return 3
        if "4" in cp:
            return 4
        return 50

    def _score_value(s: Optional[str]) -> float:
        if not s:
            return 0.0
        # Some score fields embed JS; take first numeric prefix
        import re

        m = re.search(r"[0-9]+(?:\.[0-9]+)?", s)
        return float(m.group(0)) if m else 0.0

    filtered.sort(
        key=lambda j: (_cas_priority(j.cas_partition), -_score_value(j.score), j.name.lower()),
    )

    total = len(filtered)
    if per_page <= 0:
        per_page = 10
    start = (page - 1) * per_page
    end = start + per_page
    page_items = filtered[start:end]

    list_items = [SportsJournalListItem(**j.model_dump()) for j in page_items]

    pages = (total + per_page - 1) // per_page if total > 0 else 0

    return SportsJournalListResponse(
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
        items=list_items,
    )


def get_journal_detail(journal_id: str) -> Optional[SportsJournalDetail]:
    """Return full detail for a given journal id."""

    if not DATA_PATH.exists():
        raise RuntimeError(f"sports_journals data file not found: {DATA_PATH}")

    with DATA_PATH.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    for obj in raw:
        if str(obj.get("id")) == str(journal_id):
            return SportsJournalDetail(**obj)

    return None
