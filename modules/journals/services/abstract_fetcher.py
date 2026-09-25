"""
摘要多来源补齐服务

优先级：
1. Crossref（原始数据）
2. PubMed（通过 DOI 映射到 PMID）
3. OpenAlex（abstract_inverted_index）
4. Publisher Landing（尝试解析 meta description）
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional, Tuple

import asyncio
import httpx

from core.external.pubmed import get_pubmed_client
from modules.journals.services.openalex_client import OpenAlexClient

logger = logging.getLogger(__name__)


@dataclass
class AbstractResult:
    abstract: Optional[str]
    source: str
    pmid: Optional[str] = None


class AbstractFetcher:
    """负责从多来源获取摘要"""

    _SOURCE_PRIORITY = {
        "none": 0,
        "crossref": 1,
        "openalex": 2,
        "pubmed": 3,
        "publisher": 4,
    }

    def __init__(self):
        self._pubmed = get_pubmed_client()
        self._openalex = OpenAlexClient()
        self._http_client = httpx.AsyncClient(timeout=15, follow_redirects=True)

    @classmethod
    def priority(cls, source: Optional[str]) -> int:
        return cls._SOURCE_PRIORITY.get((source or "none").lower(), 0)

    async def ensure_abstract(
        self,
        doi: str,
        crossref_abstract: Optional[str],
        crossref_pmid: Optional[str] = None,
        landing_url: Optional[str] = None,
        mode: str = "full",
    ) -> AbstractResult:
        """
        根据优先级返回最佳摘要
        
        Args:
            mode: fast|full
        """
        mode = (mode or "full").lower()

        # 1) Crossref 直接可用
        if crossref_abstract and crossref_abstract.strip():
            return AbstractResult(abstract=crossref_abstract.strip(), source="crossref", pmid=crossref_pmid)

        # fast模式：仅尝试PubMed（DOI->PMID）以保证速度
        if mode == "fast":
            pubmed_abstract, pmid = await self._fetch_from_pubmed(doi, crossref_pmid)
            if pubmed_abstract:
                return AbstractResult(abstract=pubmed_abstract, source="pubmed", pmid=pmid)
            return AbstractResult(abstract=None, source="none", pmid=pmid or crossref_pmid)

        # full模式：并行调用 PubMed、OpenAlex、Publisher
        import asyncio
        tasks = [
            self._fetch_from_pubmed(doi, crossref_pmid),
            self._fetch_from_openalex(doi),
        ]
        if landing_url:
            tasks.append(self._fetch_from_publisher(landing_url))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # PubMed 结果
        pubmed_result = results[0] if not isinstance(results[0], Exception) else (None, None)
        pubmed_abstract, pmid = pubmed_result if isinstance(pubmed_result, tuple) else (None, crossref_pmid)
        if pubmed_abstract:
            return AbstractResult(abstract=pubmed_abstract, source="pubmed", pmid=pmid)
        
        # OpenAlex 结果
        openalex_abstract = results[1] if not isinstance(results[1], Exception) else None
        if openalex_abstract:
            return AbstractResult(abstract=openalex_abstract, source="openalex", pmid=crossref_pmid)
        
        # Publisher 结果
        if landing_url and len(results) > 2:
            publisher_abstract = results[2] if not isinstance(results[2], Exception) else None
            if publisher_abstract:
                return AbstractResult(abstract=publisher_abstract, source="publisher", pmid=crossref_pmid)

        return AbstractResult(abstract=None, source="none", pmid=crossref_pmid)

    async def _fetch_from_pubmed(
        self,
        doi: str,
        existing_pmid: Optional[str] = None,
    ) -> Tuple[Optional[str], Optional[str]]:
        """通过 PubMed 获取摘要"""
        pmid = (existing_pmid or "").strip()
        try:
            if not pmid:
                # 先尝试 DOI 检索
                pmids = await self._pubmed.search(f"{doi}[DOI]", retmax=1, use_cache=True)
                if pmids:
                    pmid = pmids[0]
                else:
                    pmids = await self._pubmed.search(f"{doi}[AID]", retmax=1, use_cache=True)
                    pmid = pmids[0] if pmids else None

            if not pmid:
                return None, None

            abstract, _types, _mesh = await self._pubmed.fetch_abstract_and_types(pmid, use_cache=True)
            if abstract:
                return abstract.strip(), pmid
        except Exception as exc:
            logger.warning(f"PubMed 摘要获取失败: {doi} ({exc})")
        return None, pmid

    async def _fetch_from_openalex(self, doi: str) -> Optional[str]:
        """通过 OpenAlex abstract_inverted_index 生成摘要"""
        # OpenAlex 偶发 500/网络错误，这里做有限次数重试，避免整页过早放弃
        max_retries = 3
        delay_base = 1.0

        for attempt in range(1, max_retries + 1):
            try:
                work = await self._openalex.get_work_detail_by_doi(doi)
                if not work:
                    return None

                # 直接返回现成摘要
                display = work.get("abstract")
                if isinstance(display, str) and display.strip():
                    return display.strip()

                index = work.get("abstract_inverted_index")
                if not index:
                    return None

                positions = []
                for token, offsets in index.items():
                    for offset in offsets:
                        positions.append((offset, token))

                if not positions:
                    return None

                positions.sort(key=lambda item: item[0])
                tokens = [token for _, token in positions]
                abstract = " ".join(tokens)
                return abstract.strip() if abstract.strip() else None
            except Exception as exc:
                logger.warning(
                    "OpenAlex 摘要生成失败（第%s次，DOI=%s）: %s",
                    attempt,
                    doi,
                    exc,
                )
                if attempt < max_retries:
                    await asyncio.sleep(delay_base * attempt)
                else:
                    return None

    async def _fetch_from_publisher(self, url: str) -> Optional[str]:
        """尝试从出版社落地页解析摘要（简单版 - meta 标签）"""
        try:
            resp = await self._http_client.get(url, headers={"User-Agent": "Sports-Matter/1.0"})
            resp.raise_for_status()
            html = resp.text
        except Exception as exc:
            logger.info(f"Publisher 页面获取失败: {url} ({exc})")
            return None

        # 优先 meta description / og:description
        meta_patterns = [
            r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']+)["\']',
            r'<meta\s+property=["\']og:description["\']\s+content=["\']([^"\']+)["\']',
        ]
        for pattern in meta_patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                content = match.group(1).strip()
                if content:
                    return content

        # 退化：提取 <p> 段落中的第一段文字
        paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", html, re.IGNORECASE | re.DOTALL)
        for para in paragraphs:
            # 去除HTML标签
            cleaned = re.sub(r"<[^>]+>", " ", para)
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            if 80 <= len(cleaned) <= 4000:
                return cleaned

        return None

    async def close(self):
        """关闭底层客户端"""
        try:
            await self._openalex.close()
        except Exception:
            pass
        try:
            await self._http_client.aclose()
        except Exception:
            pass
