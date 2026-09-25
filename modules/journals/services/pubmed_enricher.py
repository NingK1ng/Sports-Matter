"""
PubMed 摘要补全服务

职责：
- 通过 DOI 查询 PMID
- 通过 PMID 获取摘要（及可选类型/MeSH）并入库

使用方式：
    enricher = PubMedEnricher(session)
    await enricher.enrich_article(article)
"""

from __future__ import annotations

from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update

from core.external.pubmed import get_pubmed_client
from modules.journals.models.journal import JournalArticle


class PubMedEnricher:
    """基于PubMed的摘要补全。"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.client = get_pubmed_client()

    async def find_pmid_by_doi(self, doi: str) -> Optional[str]:
        """
        通过DOI查找PMID
        优先使用 [DOI] 字段，失败后回退到 [AID]
        """
        doi = (doi or '').strip().lower()
        if not doi:
            return None

        # 1) 直接 DOI 字段
        pmids = await self.client.search(f"{doi}[DOI]", retmax=1)
        if pmids:
            return pmids[0]

        # 2) 替代：AID（ArticleId 包含 DOI）
        pmids = await self.client.search(f"{doi}[AID]", retmax=1)
        if pmids:
            return pmids[0]

        return None

    async def enrich_article(self, article: JournalArticle) -> bool:
        """
        为单篇文章补全摘要（若缺失），返回是否发生了更新。
        """
        if article.abstract and article.abstract.strip():
            return False

        pmid = article.pmid
        if not pmid:
            pmid = await self.find_pmid_by_doi(article.doi)
            if not pmid:
                return False

        abstract, _pub_types, _mesh_terms = await self.client.fetch_abstract_and_types(pmid)
        if not abstract:
            # 即使找到了PMID，也可能无摘要；直接返回
            return False

        # UPDATE：设置abstract/pmid/abstract_source
        stmt = (
            update(JournalArticle)
            .where(JournalArticle.id == article.id)
            .values(
                pmid=pmid,
                abstract=abstract,
                abstract_source='pubmed',
            )
        )
        await self.session.execute(stmt)
        return True

























