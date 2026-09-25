"""
PubMed Toolkit - Agent工具集
任务3: Agent在线PubMed工具链

基于Youtu-agent的轻量化实现，包含4个工具：
1. query_refiner - 规范化查询式（支持Sports Gate）
2. pubmed_esearch - 调用ESearch获取PMID列表
3. pubmed_summary - 调用ESummary/EFetch获取摘要
4. format_citations - 格式化为统一DTO
"""
import re
import asyncio
from typing import List, Dict, Any, Optional
import logging
import hashlib
from core.cache import cache_get, cache_set

from core.external.pubmed import PubMedClient
from core.external.deepseek import DeepSeekClient
from modules.assistant.services.query_translator import QueryTranslator
from modules.assistant.services.query_planner import QueryPlanner, PlanResult
from modules.assistant.models.candidate import CandidateArticle

logger = logging.getLogger(__name__)


# Sports Gate定义（MeSH terms）
SPORTS_GATE = "(Sports[mh] OR Athletes[mh] OR sport*[tiab] OR athlet*[tiab] OR exercise[mh])"


class PubMedToolkit:
    """PubMed工具集"""
    
    def __init__(self, pubmed_client: Optional[PubMedClient] = None, deepseek_client: Optional[DeepSeekClient] = None):
        self.pubmed_client = pubmed_client or PubMedClient()
        self._deepseek = deepseek_client or DeepSeekClient()
        self._translator = QueryTranslator(self._deepseek)
        self._planner = QueryPlanner(self._deepseek, self.pubmed_client)
        self.last_plan: Optional[PlanResult] = None
    
    async def query_refiner(
        self,
        query: str,
        sports_gate: bool = False
    ) -> str:
        """
        工具1: 规范化PubMed查询式（优化版，支持多同义词）
        
        Args:
            query: 原始用户查询
            sports_gate: 是否添加Sports Gate限定
        
        Returns:
            规范化的PubMed查询式
        """
        query = query.strip()
        
        # 如果已经是PubMed格式，直接使用
        if any(marker in query for marker in ["[tiab]", "[title]", "[mh]", " AND ", " OR ", " NOT "]):
            refined_query = query
        else:
            # 检测中文
            has_chinese = bool(re.search(r'[\u4e00-\u9fff]', query))
            
            if has_chinese:
                # 中文查询：使用多同义词翻译
                try:
                    translation = await self._translator.translate_with_synonyms(query)
                    refined_query = self._build_pubmed_query(translation)
                except Exception as e:
                    logger.warning(f"Translation failed, using simple query: {e}")
                    # 回退：简单翻译
                    en = await self._translator.translate_query(query)
                    refined_query = f"{en}[tiab]"
            else:
                # 英文查询：简单处理
                words = query.split()
                if len(words) == 1:
                    refined_query = f"{query}[tiab]"
                elif len(words) <= 4:
                    # 不加引号，让ATM自动映射
                    refined_query = " AND ".join([f"{w}[tiab]" for w in words])
                else:
                    refined_query = f'"{query}"[tiab]'
        
        # 添加Sports Gate
        if sports_gate:
            refined_query = f"({SPORTS_GATE}) AND ({refined_query})"
        
        logger.info(f"Query refined: {refined_query[:150]}...")
        return refined_query
    
    def _build_pubmed_query(self, translation: Dict) -> str:
        """
        从翻译结果构建PubMed查询式
        
        策略：
        1. MeSH Terms优先（精确匹配）
        2. 主词+同义词（宽泛召回，不加引号让ATM映射）
        3. 缩写独立（不加引号）
        
        Args:
            translation: 翻译结果字典
        
        Returns:
            PubMed查询式
        """
        parts = []
        
        # 1. MeSH Terms（如果有）
        mesh_terms = translation.get("mesh_terms", [])
        if mesh_terms:
            # 不加引号，让PubMed ATM自动映射到MeSH数据库
            mesh_queries = [f"{term}[MeSH Terms]" for term in mesh_terms]
            parts.append("(" + " OR ".join(mesh_queries) + ")")
        
        # 2. 主词（完整术语）
        primary = translation.get("primary", "")
        if primary:
            # 不加引号，允许词形变化和ATM映射
            parts.append(f"{primary}[tiab]")
        
        # 3. 同义词
        synonyms = translation.get("synonyms", [])
        if synonyms:
            syn_queries = [f"{syn}[tiab]" for syn in synonyms[:5]]  # 最多5个同义词
            parts.append("(" + " OR ".join(syn_queries) + ")")
        
        # 4. 缩写（独立OR）
        abbreviations = translation.get("abbreviations", [])
        if abbreviations:
            abbr_queries = [f"{abbr}[tiab]" for abbr in abbreviations]
            parts.append("(" + " OR ".join(abbr_queries) + ")")
        
        # 用OR连接所有部分（宽泛召回）
        if not parts:
            # 回退：使用原查询
            return f"{primary or 'unknown'}[tiab]"
        
        return " OR ".join(parts)
    
    async def pubmed_esearch(
        self,
        query: str,
        retmax: int = 50
    ) -> List[str]:
        """
        工具2: 调用PubMed ESearch获取PMID列表
        
        Args:
            query: PubMed查询式
            retmax: 最大返回数量
        
        Returns:
            PMID列表
        """
        try:
            # PubMedClient.search方法返回List[str]
            pmids = await self.pubmed_client.search(
                query=query,
                retmax=retmax,
                retstart=0,
                use_cache=True
            )
            
            logger.info(f"ESearch found {len(pmids)} PMIDs")
            return pmids
            
        except Exception as e:
            logger.error(f"ESearch failed: {e}")
            return []
    
    async def pubmed_summary(
        self,
        pmids: List[str]
    ) -> List[Dict[str, Any]]:
        """
        工具3: 调用PubMed ESummary获取文献摘要
        
        Args:
            pmids: PMID列表
        
        Returns:
            文献摘要列表 [{"pmid": ..., "title": ..., "abstract": ...}, ...]
        """
        if not pmids:
            return []
        
        try:
            # 调用fetch_summary（批量获取，最多200条）
            articles = await self.pubmed_client.fetch_summary(pmids[:200], use_cache=True)
            
            summaries = []
            
            for article in articles:
                pmid = article.get("pmid", "")
                if not pmid:
                    continue
                
                title = article.get("title", "")
                
                # 提取基本信息
                # ✅ ESummary不返回abstract，但单独fetch会超时，先用空字符串
                # 前端会根据URL让用户去PubMed查看完整摘要
                abstract_text = article.get("abstract", "")
                # ❌ 禁用单独fetch_abstract，会导致30秒超时
                # if not abstract_text:
                #     try:
                #         abstract_text = await self.pubmed_client.fetch_abstract(pmid, use_cache=True) or ""
                #     except Exception as fetch_err:
                #         logger.warning(f"Fetch abstract failed for {pmid}: {fetch_err}")
                #         abstract_text = ""
                # ✅ 修复字段名映射（fetch_summary返回source/pubdate，不是journal/pub_date）
                summary = {
                    "pmid": pmid,
                    "title": title,  # 使用前面提取的title变量
                    "abstract": abstract_text,
                    "journal": article.get("source", "") or article.get("journal", ""),  # source是期刊名
                    "pub_date": article.get("pubdate", "") or article.get("pub_date", ""),  # pubdate是发表日期
                    "authors": article.get("authors", []),
                }
                
                # ✅ 关键检查：如果title为空，记录警告并跳过
                if not title or title.strip() == "":
                    logger.warning(f"Skipping PMID {pmid} in pubmed_summary: empty title")
                    continue
                
                summaries.append(summary)
            
            logger.info(f"Retrieved {len(summaries)} summaries")
            return summaries
            
        except Exception as e:
            logger.error(f"ESummary failed: {e}")
            return []
    
    async def format_citations(
        self,
        summaries: List[Dict[str, Any]]
    ) -> List[CandidateArticle]:
        """
        工具4: 格式化为统一的CandidateArticle DTO
        
        Args:
            summaries: 文献摘要列表
        
        Returns:
            CandidateArticle列表
        """
        candidates = []
        skipped_count = 0
        
        for summary in summaries:
            pmid = summary.get("pmid", "")
            if not pmid:
                skipped_count += 1
                logger.debug(f"Skipped article: missing PMID")
                continue
            
            # 检查必需字段
            title = summary.get("title", "")
            if not title or title.strip() == "":
                skipped_count += 1
                logger.warning(f"Skipped PMID {pmid}: missing title")
                continue
            
            # 提取发表年份
            pub_date = summary.get("pub_date", "")
            year = None
            if pub_date:
                year_match = re.search(r'(\d{4})', pub_date)
                if year_match:
                    year = int(year_match.group(1))
            
            # 提取作者
            authors = summary.get("authors", [])
            author_str = None
            if authors:
                if isinstance(authors, list):
                    # 取前3个作者
                    author_names = [a.get("name", "") if isinstance(a, dict) else str(a) for a in authors[:3]]
                    author_str = ", ".join(filter(None, author_names))
                    if len(authors) > 3:
                        author_str += ", et al."
            
            candidate = CandidateArticle(
                pmid=pmid,
                title=title,
                abstract=(summary.get("abstract", "") or "")[:300],
                url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                source="pubmed_agent",
                journal_name=summary.get("journal", None),
                publication_year=year,
                authors=author_str
            )
            
            candidates.append(candidate)
        
        if skipped_count > 0:
            logger.warning(f"Skipped {skipped_count} articles due to missing required fields")
        logger.info(f"Formatted {len(candidates)} candidates from {len(summaries)} summaries")
        return candidates
    
    async def run_agent_pipeline(
        self,
        query: str,
        sports_gate: bool = False,
        top_k: int = 10,
        timeout: int = 30
    ) -> List[CandidateArticle]:
        """
        完整的Agent管线（组合4个工具，带超时保护）
        
        Args:
            query: 用户查询
            sports_gate: 是否启用Sports Gate
            top_k: 返回数量
            timeout: 总超时时间（秒，默认30秒）
        
        Returns:
            候选文献列表
        """
        try:
            # 添加超时保护
            return await asyncio.wait_for(
                self._run_pipeline_internal(query, sports_gate, top_k),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            logger.error(f"Agent pipeline timeout after {timeout}s for query: {query}")
            return []
        except Exception as e:
            logger.error(f"Agent pipeline error: {e}", exc_info=True)
            return []
    
    async def _run_pipeline_internal(
        self,
        query: str,
        sports_gate: bool,
        top_k: int
    ) -> List[CandidateArticle]:
        """Agent管线内部实现"""
        # 1. LLM检索规划
        self.last_plan = await self._planner.plan(
            query,
            sports_gate=sports_gate,
            sports_gate_clause=SPORTS_GATE,
            max_candidates=4,
            retmax=max(top_k * 3, 25),
        )

        pmid_candidates: List[str] = []
        for planned in self.last_plan.queries:
            pmid_candidates.extend(planned.pmids)

        # 去重保持顺序
        seen: set[str] = set()
        deduped_pmids: List[str] = []
        for pmid in pmid_candidates:
            if pmid and pmid not in seen:
                seen.add(pmid)
                deduped_pmids.append(pmid)

        if not deduped_pmids:
            logger.warning("QueryPlanner未返回有效PMID")
            return []

        fetch_limit = max(top_k * 2, top_k)
        pmids = deduped_pmids[:fetch_limit]

        # 2. 获取摘要（多取一些供后续重排）
        summary_limit = max(top_k * 2, 10)
        summaries = await self.pubmed_summary(pmids[:summary_limit])
        if not summaries:
            logger.warning("No summaries retrieved")
            return []

        # 3. 格式化
        candidates = await self.format_citations(summaries)

        # ✅ 返回top_k篇而不是summary_limit篇（summary_limit只是用于多召回一些备选）
        return candidates[:top_k]

