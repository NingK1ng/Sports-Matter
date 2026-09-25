"""
OpenAlex API客户端
任务3.1: 获取被引数据
"""
from typing import Optional, Dict, Any
import logging
import asyncio

from core.external.base import BaseAPIClient
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
        candidate_emails = emails or [settings.openalex_email, settings.pubmed_email]

        if email_override:
            candidate_emails = [email_override]

        self.emails = [email for email in candidate_emails if email]
        if not self.emails:
            raise ValueError("OpenAlex email list is empty; configure OPENALEX_EMAIL or PUBMED_EMAIL.")

        self._email_index = 0
        self._email_lock = asyncio.Lock()

        # 设置默认 User-Agent，以首个邮箱为主
        default_email = self.emails[0]
        self.client.headers.update(
            {
                "User-Agent": f"SportsMatterOpenAlexClient/1.0 (+mailto:{default_email})",
            }
        )

    async def _next_email(self) -> str:
        async with self._email_lock:
            email = self.emails[self._email_index]
            self._email_index = (self._email_index + 1) % len(self.emails)
            return email

    async def get_work_detail_by_doi(self, doi: str) -> Optional[Dict[str, Any]]:
        """
        返回完整作品信息（包括 abstract_inverted_index 等字段）
        """
        try:
            params = {"filter": f"doi:{doi}"}
            email = await self._next_email()
            params["mailto"] = email
            headers = {
                "User-Agent": f"SportsMatterOpenAlexClient/1.0 (+mailto:{email})"
            }
            response = await self.get("/works", params=params, use_cache=True, headers=headers)
            if not response:
                return None
            results = response.get("results")
            if not isinstance(results, list) or not results:
                return None
            work = results[0]
            if not isinstance(work, dict):
                return None
            return work
        except Exception as exc:
            logger.warning(f"OpenAlex 作品详情获取失败: {doi} ({exc})")
            return None

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
        
        except Exception as e:
            logger.warning(f"OpenAlex查询失败: {doi}, {e}")
            return None

    async def batch_get_works(self, dois: list[str]) -> Dict[str, Dict[str, Any]]:
        """
        批量获取作品信息（未实现，OpenAlex不支持批量查询）
        
        Args:
            dois: DOI列表
        
        Returns:
            {doi: work_data}
        """
        # OpenAlex不支持批量查询，需要逐个查询
        results = {}
        for doi in dois:
            work = await self.get_work_by_doi(doi)
            if work:
                results[doi] = work
        return results
