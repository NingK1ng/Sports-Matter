"""
本地检索服务 - 并行查询模块1和模块2数据库
任务1.2: 封装LocalSearchService
"""
import asyncio
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from core.services.embedding_service import get_embedding_service
from modules.assistant.services.vector_search import VectorSearchService
from modules.literature_stream.services.search_service import LiteratureSearchService
from modules.journals.services.search_service import SearchService
from modules.assistant.models.candidate import CandidateArticle
from modules.assistant.services.deduplicator import deduplicate_by_pmid

logger = logging.getLogger(__name__)


class LocalSearchService:
    """本地文献检索服务（模块1+模块2）"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
        self.lit_service = LiteratureSearchService(session)
        self.journal_service = SearchService(session)
    
    async def search(
        self,
        query: str,
        top_k: int = 10,
        search_scope: str = "tiab",
        source: str = "both",
    ) -> List[CandidateArticle]:
        """
        并行查询两表，去重并返回top_k条候选文献
        
        Args:
            query: 查询关键词
            top_k: 返回数量（默认10）
            search_scope: 搜索范围 ti|tiab
        
        Returns:
            去重后的候选文献列表（最多top_k条）
        """
        # 各召回topK*1.5条（如10→15），为去重留余量
        fetch_count = int(top_k * 1.5)
        
        # ✅ 根据数据源选择查询范围：文献流 / 顶刊 / 两者
        lit_candidates: List[CandidateArticle] = []
        journal_candidates: List[CandidateArticle] = []

        if source == "both":
            # AsyncSession 不能并发执行查询；且最终排序原本优先模块1，模块1足够时无需等待模块2。
            lit_candidates = await self._search_literature(query, fetch_count, search_scope)
            if len(deduplicate_by_pmid(lit_candidates)) < top_k:
                journal_candidates = await self._search_journals(query, fetch_count, search_scope)
        elif source == "stream":
            lit_candidates = await self._search_literature(query, fetch_count, search_scope)
        elif source == "journals":
            journal_candidates = await self._search_journals(query, fetch_count, search_scope)
        
        # 向量检索补充召回 - ❌ 临时禁用（方案A测试）
        # Embedding API调用太慢（30-60秒），方案B会添加缓存优化
        vector_candidates = []
        # try:
        #     embedding_service = get_embedding_service()
        #     query_embedding = embedding_service.generate_embedding(query)
        #     if query_embedding:
        #         vector_service = VectorSearchService(self.session)
        #         vector_limit = max(5, top_k)
        #         vector_candidates = await vector_service.search(query_embedding, limit_per_source=vector_limit)
        # except Exception as exc:  # pylint: disable=broad-except
        #     logger.warning(f"Vector search failed: {exc}")

        # 合并候选
        all_candidates = lit_candidates + journal_candidates + vector_candidates
        
        # PMID去重（保留摘要更完整的）
        deduped = deduplicate_by_pmid(all_candidates)
        
        # 裁剪到topK
        final = deduped[:top_k]
        
        logger.info(
            "Local search: lit=%s, journal=%s, vector=%s, deduped=%s, final=%s",
            len(lit_candidates),
            len(journal_candidates),
            len(vector_candidates),
            len(deduped),
            len(final),
        )
        
        return final
    
    async def _search_literature(
        self, 
        query: str, 
        limit: int, 
        scope: str
    ) -> List[CandidateArticle]:
        """查询模块1数据库"""
        try:
            items, _ = await self.lit_service.search(
                keywords=query,
                search_scope=scope,
                sort_by="relevance",
                limit=limit,
                offset=0
            )
            
            candidates = []
            for lit in items:
                # literature表通常都有PMID，但也添加DOI支持以防万一
                if not lit.pmid and not getattr(lit, 'doi', None):
                    continue  # 跳过既没有PMID也没有DOI的文献

                # 构建URL：优先PubMed，否则使用DOI
                if lit.pmid:
                    url = f"https://pubmed.ncbi.nlm.nih.gov/{lit.pmid}/"
                elif getattr(lit, 'doi', None):
                    url = f"https://doi.org/{lit.doi}"
                else:
                    url = ""

                candidates.append(CandidateArticle(
                    pmid=lit.pmid,
                    doi=getattr(lit, 'doi', None),
                    title=lit.title or "",
                    abstract=lit.abstract or "",
                    url=url,
                    source="literature",
                    journal_name=lit.journal_name,
                    publication_year=lit.publication_date.year if lit.publication_date else None,
                    authors=", ".join(lit.authors[:3]) if lit.authors else None
                ))
            
            return candidates
        except Exception as e:
            logger.error(f"Literature search error: {e}")
            return []
    
    async def _search_journals(
        self, 
        query: str, 
        limit: int, 
        scope: str
    ) -> List[CandidateArticle]:
        """查询模块2数据库"""
        try:
            items, _ = await self.journal_service.search_articles(
                keywords=query,
                search_scope=scope,
                sort_by="relevance",
                per_page=limit,
                page=1
            )
            
            candidates = []
            for article in items:
                # ✅ 修复：支持没有PMID的journal文章
                # 86.8%的journal_articles没有PMID，使用DOI作为备用标识
                if not article.pmid and not article.doi:
                    continue  # 只跳过既没有PMID也没有DOI的文章

                # authors 可能为 List[Dict] 或 List[str]
                author_str = None
                if article.authors:
                    try:
                        preview = []
                        for a in article.authors[:3]:
                            if isinstance(a, dict):
                                name = a.get("name") or a.get("full_name") or a.get("last_name") or str(a)
                            else:
                                name = str(a)
                            if name:
                                preview.append(name)
                        if preview:
                            author_str = ", ".join(preview)
                    except Exception:
                        author_str = None

                # 构建URL：优先PubMed，否则使用DOI
                if article.pmid:
                    url = f"https://pubmed.ncbi.nlm.nih.gov/{article.pmid}/"
                elif article.doi:
                    url = f"https://doi.org/{article.doi}"
                else:
                    url = ""  # 理论上不会走到这里

                candidates.append(CandidateArticle(
                    pmid=article.pmid,  # 可能为None
                    doi=article.doi,    # 可能为None
                    title=article.title or "",
                    abstract=article.abstract or "",
                    url=url,
                    source="journals",
                    journal_name=article.journal_name,
                    publication_year=article.publication_date.year if article.publication_date else None,
                    authors=author_str
                ))
            
            return candidates
        except Exception as e:
            logger.error(f"Journal search error: {e}")
            return []
