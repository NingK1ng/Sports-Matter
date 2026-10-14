"""
OpenAlex API客户端
任务3.1: 获取被引数据
"""
from typing import Optional, Dict, Any
import logging
import httpx
from urllib.parse import quote

from core.cache import cache_get, cache_set

from core.external.base import BaseAPIClient, UpstreamRateLimited
from core.config import settings

logger = logging.getLogger(__name__)


class OpenAlexClient(BaseAPIClient):
    """OpenAlex API客户端"""

    def __init__(
        self,
        *,
        email_override: Optional[str] = None,
        emails: Optional[list[str]] = None,
    ):
        super().__init__(
            base_url="https://api.openalex.org",
            timeout=10,
            enable_cache=True,
            cache_ttl=86400,  # 24小时
        )
        # One configured contact identity; rotating addresses does not add quota.
        self.email = email_override or next((e for e in (emails or []) if e), None) or settings.openalex_email or settings.pubmed_email
        if settings.openalex_api_key:
            self.client.headers["Authorization"] = f"Bearer {settings.openalex_api_key}"
        self.client.headers["User-Agent"] = "SportsMatter/1.0 (+https://sports-matter.com)"

    async def get_work_detail_by_doi(self, doi: str) -> Optional[Dict[str, Any]]:
        """Retrieve the full work using OpenAlex's free DOI singleton endpoint."""
        doi = (doi or "").strip()
        for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
            if doi.lower().startswith(prefix):
                doi = doi[len(prefix):]
                break
        if not doi.lower().startswith("10.") or "/" not in doi:
            return None
        endpoint = "/works/doi:" + quote(doi, safe="/")
        params = {"mailto": self.email} if self.email else {}
        miss_key = self._get_cache_key(endpoint, params) + ":missing"
        if await cache_get(miss_key):
            return None
        try:
            work = await self.get(endpoint, params=params, use_cache=True)
            return work if isinstance(work, dict) and work.get("id") else None
        except UpstreamRateLimited:
            raise
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                await cache_set(miss_key, True, ttl=86400)
                return None
            raise

    async def get_work_by_doi(self, doi: str) -> Optional[Dict[str, Any]]:
        """
        通过DOI获取作品信息
        """
        try:
            work = await self.get_work_detail_by_doi(doi)
            if not work:
                return None

            # 提取被引数据
            openalex_id = work.get("id")
            cited_by_count = work.get("cited_by_count")
            cited_by_percentile_year = None
            percentile_obj = work.get("cited_by_percentile_year")
            if isinstance(percentile_obj, dict):
                cited_by_percentile_year = percentile_obj.get("value")
            
            return {
                "openalex_id": openalex_id,
                "cited_by_count": cited_by_count,
                "cited_by_percentile_year": cited_by_percentile_year,
            }
        
        except UpstreamRateLimited:
            raise
        except Exception as e:
            logger.warning(f"OpenAlex查询失败: {doi}, {e}")
            return None

    async def batch_get_works(self, dois: list[str]) -> Dict[str, Dict[str, Any]]:
        """
        按 DOI 获取单篇作品信息（使用免费 singleton 接口）
        
        Args:
            dois: DOI列表
        
        Returns:
            {doi: work_data}
        """
        # 使用免费单篇直查；批量 filter 查询会消耗每日预算。
        results = {}
        for doi in dois:
            work = await self.get_work_by_doi(doi)
            if work:
                results[doi] = work
        return results
