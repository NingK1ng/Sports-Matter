"""
OpenAlex API客户端

提供文献被引数据和学科分类查询
"""

from typing import Dict, Any, Optional

from core.config import settings
from core.external.base import BaseAPIClient


class OpenAlexClient(BaseAPIClient):
    """OpenAlex API客户端"""

    def __init__(self):
        super().__init__(
            base_url="https://api.openalex.org",
            timeout=10,
            enable_cache=True,
            cache_ttl=86400,
        )
        self.email = settings.openalex_email

    async def get_citations(
        self,
        identifier: str,
        use_cache: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """
        查询文献被引数

        Args:
            identifier: DOI或PMID（格式：doi:10.xxxx 或 pmid:xxxxx）
            use_cache: 是否使用缓存

        Returns:
            Optional[Dict]: 被引数据
        """
        params = {}
        if self.email:
            params["mailto"] = self.email

        response = await self.get(
            f"/works/{identifier}", params=params, use_cache=use_cache
        )

        if response:
            cited_by_count = response.get("cited_by_count", 0)
            print(f"📊 OpenAlex: 被引{cited_by_count}次 ({identifier})")

        return response

    async def get_concepts(
        self,
        work_id: str,
        use_cache: bool = True,
    ) -> list:
        """
        获取学科分类

        Args:
            work_id: OpenAlex Work ID
            use_cache: 是否使用缓存

        Returns:
            list: 学科概念列表
        """
        params = {}
        if self.email:
            params["mailto"] = self.email

        response = await self.get(
            f"/works/{work_id}", params=params, use_cache=use_cache
        )

        return response.get("concepts", []) if response else []


def get_openalex_client() -> OpenAlexClient:
    """获取OpenAlex客户端"""
    return OpenAlexClient()
