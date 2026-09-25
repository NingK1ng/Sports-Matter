"""
Crossref API客户端（顶刊追踪专用）
任务2.1: 继承BaseAPIClient，实现期刊文章查询
"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import logging

from core.external.base import BaseAPIClient
from core.config import settings

logger = logging.getLogger(__name__)


class CrossrefJournalClient(BaseAPIClient):
    """Crossref API客户端（顶刊追踪）"""

    def __init__(self):
        super().__init__(
            base_url="https://api.crossref.org",
            timeout=30,
            enable_cache=True,
            cache_ttl=86400,  # 24小时
        )
        self.email = settings.crossref_email or settings.pubmed_email

    async def search_by_issn_indexed_date(
        self,
        issn: str,
        from_indexed_date: str,
        until_indexed_date: Optional[str] = None,
        from_pub_date: Optional[str] = None,
        until_pub_date: Optional[str] = None,
        cursor: str = "*",
        rows: int = 100,
    ) -> Dict[str, Any]:
        """
        按ISSN和index-date查询文章（增量爬取）
        
        Args:
            issn: 期刊ISSN（任意格式，Crossref会自动匹配）
            from_indexed_date: 起始收录日期（YYYY-MM-DD）
            until_indexed_date: 结束收录日期（YYYY-MM-DD，可选）
            from_pub_date: 起始发表日期（YYYY-MM-DD，可选，用于限制返回的发表时间范围）
            until_pub_date: 结束发表日期（YYYY-MM-DD，可选）
            cursor: 游标（用于分页，初始值为"*")
            rows: 每页数量（最大1000）
        
        Returns:
            Crossref响应（包含items和next-cursor）
        """
        params = {
            "filter": f"issn:{issn},type:journal-article,from-index-date:{from_indexed_date}",
            "rows": rows,
            "cursor": cursor,
        }
        
        if until_indexed_date:
            params["filter"] += f",until-index-date:{until_indexed_date}"

        # 可选：同时限定发表时间范围，避免 index-date 返回大量历史更新导致的噪声/成本
        if from_pub_date:
            params["filter"] += f",from-pub-date:{from_pub_date}"
        if until_pub_date:
            params["filter"] += f",until-pub-date:{until_pub_date}"
        
        if self.email:
            params["mailto"] = self.email
        
        logger.info(
            f"查询Crossref(index-date): ISSN={issn}, from={from_indexed_date}, cursor={cursor[:20]}..."
        )
        
        response = await self.get("/works", params=params, use_cache=False)
        
        message = response.get("message", {})
        items = message.get("items", [])
        next_cursor = message.get("next-cursor")
        total_results = message.get("total-results", 0)
        
        logger.info(
            "✅ 获取%s篇文章，总数=%s，next_cursor=%s",
            len(items),
            total_results,
            next_cursor[:20] if next_cursor else "None",
        )
        
        return {
            "items": items,
            "next_cursor": next_cursor,
            "total_results": total_results,
        }

    async def search_by_issn_pub_date(
        self,
        issn: str,
        from_pub_date: str,
        until_pub_date: Optional[str] = None,
        cursor: str = "*",
        rows: int = 100,
    ) -> Dict[str, Any]:
        """
        按ISSN和pub-date查询文章（历史回填）
        
        Args:
            issn: 期刊ISSN
            from_pub_date: 起始发表日期（YYYY-MM-DD）
            until_pub_date: 结束发表日期（YYYY-MM-DD，可选）
            cursor: 游标
            rows: 每页数量
        
        Returns:
            Crossref响应
        """
        params = {
            "filter": f"issn:{issn},type:journal-article,from-pub-date:{from_pub_date}",
            "rows": rows,
            "cursor": cursor,
        }
        
        if until_pub_date:
            params["filter"] += f",until-pub-date:{until_pub_date}"
        
        if self.email:
            params["mailto"] = self.email
        
        logger.info(f"查询Crossref（历史）: ISSN={issn}, from={from_pub_date}, cursor={cursor[:20]}...")
        
        response = await self.get("/works", params=params, use_cache=False)
        
        message = response.get("message", {})
        items = message.get("items", [])
        next_cursor = message.get("next-cursor")
        total_results = message.get("total-results", 0)
        
        logger.info(f"✅ 获取{len(items)}篇文章（历史），总数={total_results}")
        
        return {
            "items": items,
            "next_cursor": next_cursor,
            "total_results": total_results,
        }

    def parse_article(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        解析Crossref文章数据
        
        Args:
            item: Crossref返回的单篇文章数据
        
        Returns:
            解析后的文章数据（标准化格式）
        """
        try:
            # DOI（必须）
            doi = item.get("DOI")
            if not doi:
                logger.warning("文章缺少DOI，跳过")
                return None
            
            # 归一化DOI（小写、去空格）
            doi = doi.lower().strip()
            
            # 标题（必须）
            title_list = item.get("title", [])
            title = title_list[0] if title_list else None
            if not title:
                logger.warning(f"文章{doi}缺少标题，跳过")
                return None
            
            # 摘要（可选，需清洗JATS）
            abstract = item.get("abstract")
            abstract_source = "crossref" if abstract else "none"
            
            # 作者（可选）
            authors = item.get("author", [])
            
            # 发表时间（优先级：published-online → published-print → issued → created）
            published_at_precise = None
            for date_type in ["published-online", "published-print", "issued", "created"]:
                date_parts = item.get(date_type, {}).get("date-parts", [[]])[0]
                if date_parts and len(date_parts) >= 3:
                    try:
                        published_at_precise = datetime(date_parts[0], date_parts[1], date_parts[2])
                        break
                    except:
                        continue
            
            if not published_at_precise:
                logger.warning(f"文章{doi}缺少发表时间，跳过")
                return None
            
            # indexed时间（Crossref为对象：{"date-time":..., "timestamp":...}）
            indexed_at = None
            try:
                indexed_obj = item.get("indexed", {})
                if isinstance(indexed_obj, dict):
                    dt = indexed_obj.get("date-time")
                    if dt:
                        # 兼容以Z结尾的ISO时间
                        iso = dt.replace("Z", "+00:00")
                        indexed_at = datetime.fromisoformat(iso)
                    else:
                        ts = indexed_obj.get("timestamp")
                        if ts:
                            # 毫秒或秒时间戳（Crossref通常为毫秒）
                            ts_int = int(ts)
                            if ts_int > 1_000_000_000_000:
                                ts_int = ts_int // 1000
                            indexed_at = datetime.utcfromtimestamp(ts_int)
            except Exception:
                pass
            
            # ISSN列表
            issn_list = item.get("ISSN", [])
            
            # 期刊名称
            journal_name_list = item.get("container-title", [])
            journal_name = journal_name_list[0] if journal_name_list else None

            # PubMed 相关字段
            pmid = (
                item.get("pub-med-id")
                or item.get("pubmed-id")
                or item.get("pubMedId")
            )
            if isinstance(pmid, list):
                pmid = pmid[0]
            if isinstance(pmid, str):
                pmid = pmid.strip() or None
            
            return {
                "doi": doi,
                "title": title,
                "abstract": abstract,
                "abstract_source": abstract_source,
                "authors": authors,
                "published_at_precise": published_at_precise,
                "publication_date": published_at_precise.date(),
                "indexed_at": indexed_at,
                "issn_list": issn_list,
                "journal_name": journal_name,
                "pmid": pmid,
                "landing_page_url": item.get("URL"),
            }
        
        except Exception as e:
            logger.error(f"解析文章失败: {e}")
            return None
