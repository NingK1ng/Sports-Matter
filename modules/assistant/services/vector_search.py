from __future__ import annotations

import logging
from typing import List, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.assistant.models.candidate import CandidateArticle

logger = logging.getLogger(__name__)


class VectorSearchService:
    """基于pgvector的向量检索服务"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def search(self, embedding: Sequence[float], limit_per_source: int = 10) -> List[CandidateArticle]:
        if not embedding:
            return []

        vec = self._to_pgvector(embedding)
        results: List[CandidateArticle] = []

        literature = await self._search_literature(vec, limit_per_source)
        journals = await self._search_journals(vec, limit_per_source)

        results.extend(literature)
        results.extend(journals)
        return results

    async def _search_literature(self, vec: str, limit: int) -> List[CandidateArticle]:
        query = text(
            """
            SELECT pmid,
                   title,
                   abstract,
                   journal_name,
                   publication_date,
                   authors,
                   embedding <-> (:vec)::vector AS distance
            FROM literature
            WHERE is_deleted = FALSE AND embedding IS NOT NULL
            ORDER BY embedding <-> (:vec)::vector
            LIMIT :limit
            """
        )
        try:
            result = await self.session.execute(query, {"vec": vec, "limit": limit})
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Vector search literature failed: %s", exc)
            try:
                await self.session.rollback()
            except Exception:  # pylint: disable=broad-except
                logger.debug("Vector search literature rollback failed", exc_info=True)
            return []

        rows = result.fetchall()
        candidates: List[CandidateArticle] = []
        for row in rows:
            pmid = row.pmid
            if not pmid:
                continue
            candidates.append(
                CandidateArticle(
                    pmid=pmid,
                    title=row.title or "",
                    abstract=row.abstract or "",
                    url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    source="literature",
                    journal_name=row.journal_name,
                    publication_year=row.publication_date.year if row.publication_date else None,
                    authors=self._format_authors_array(row.authors),
                )
            )
        return candidates

    async def _search_journals(self, vec: str, limit: int) -> List[CandidateArticle]:
        query = text(
            """
            SELECT pmid,
                   title,
                   abstract,
                   journal_name,
                   publication_date,
                   authors,
                   embedding <-> (:vec)::vector AS distance
            FROM journal_articles
            WHERE embedding IS NOT NULL AND pmid IS NOT NULL
            ORDER BY embedding <-> (:vec)::vector
            LIMIT :limit
            """
        )
        try:
            result = await self.session.execute(query, {"vec": vec, "limit": limit})
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Vector search journals failed: %s", exc)
            try:
                await self.session.rollback()
            except Exception:  # pylint: disable=broad-except
                logger.debug("Vector search journals rollback failed", exc_info=True)
            return []

        rows = result.fetchall()
        candidates: List[CandidateArticle] = []
        for row in rows:
            pmid = row.pmid
            if not pmid:
                continue
            candidates.append(
                CandidateArticle(
                    pmid=pmid,
                    title=row.title or "",
                    abstract=row.abstract or "",
                    url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    source="journals",
                    journal_name=row.journal_name,
                    publication_year=row.publication_date.year if row.publication_date else None,
                    authors=self._format_authors_json(row.authors),
                )
            )
        return candidates

    @staticmethod
    def _to_pgvector(values: Sequence[float]) -> str:
        return "[" + ",".join(f"{v:.6f}" for v in values) + "]"

    @staticmethod
    def _format_authors_array(authors: Optional[Sequence[str]]) -> Optional[str]:
        if not authors:
            return None
        try:
            preview = [str(a) for a in authors[:3]]
            if not preview:
                return None
            suffix = ", et al." if len(authors) > 3 else ""
            return ", ".join(preview) + suffix
        except Exception:  # pylint: disable=broad-except
            return None

    @staticmethod
    def _format_authors_json(authors: Optional[object]) -> Optional[str]:
        if not authors:
            return None
        try:
            preview = []
            if isinstance(authors, list):
                for item in authors[:3]:
                    if isinstance(item, dict):
                        name = item.get("name") or item.get("full_name") or item.get("last_name")
                    else:
                        name = str(item)
                    if name:
                        preview.append(name)
            if not preview:
                return None
            suffix = ", et al." if isinstance(authors, list) and len(authors) > 3 else ""
            return ", ".join(preview) + suffix
        except Exception:  # pylint: disable=broad-except
            return None
