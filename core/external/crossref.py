"""
Crossref API客户端

提供期刊文章查询和DOI元数据获取
"""

from typing import List, Dict, Any, Optional

from core.config import settings
from core.external.base import BaseAPIClient


class CrossrefClient(BaseAPIClient):
    """Crossref API客户端"""

    def __init__(self):
        super().__init__(
            base_url="https://api.crossref.org",
            timeout=10,
            enable_cache=True,
            cache_ttl=86400,
        )
        self.email = settings.crossref_email

    async def get_journal_articles(
        self,
        issn: str,
        from_date: Optional[str] = None,
        rows: int = 100,
        use_cache: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        查询期刊文章

        Args:
            issn: 期刊ISSN
            from_date: 起始日期（格式：YYYY-MM-DD）
            rows: 返回数量
            use_cache: 是否使用缓存

        Returns:
            List[Dict]: 文章列表
        """
        params = {"rows": rows}

        if from_date:
            params["from-index-date"] = from_date

        if self.email:
            params["mailto"] = self.email

        response = await self.get(
            f"/works?filter=issn:{issn}", params=params, use_cache=use_cache
        )

        articles = response.get("message", {}).get("items", [])
        print(f"📰 Crossref: 获取{len(articles)}篇文章 (ISSN: {issn})")
        return articles

    async def get_article(
        self,
        doi: str,
        use_cache: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """
        获取文章详情

        Args:
            doi: DOI
            use_cache: 是否使用缓存

        Returns:
            Optional[Dict]: 文章元数据
        """
        params = {}
        if self.email:
            params["mailto"] = self.email

        response = await self.get(f"/works/{doi}", params=params, use_cache=use_cache)
        return response.get("message")


def get_crossref_client() -> CrossrefClient:
    """获取Crossref客户端"""
    return CrossrefClient()
