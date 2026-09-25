"""
BioRxiv 爬取服务
L1 层：BioRxiv 官方 API 按日期范围抓取预印本

API 文档参考：https://api.biorxiv.org/
本实现使用 details 接口：
  https://api.biorxiv.org/details/biorxiv/YYYY-MM-DD/YYYY-MM-DD/0
并按 cursor 递增分页，直到返回空集合。

注意：
- 为了复用 arxiv_articles 表结构，这里将 BioRxiv 记录也映射为 article dict，
  并设置 source="biorxiv"。
- 由于 arxiv_id 字段长度为 20，这里为 BioRxiv 记录生成一个稳定的短 ID：
  "bx" + md5(doi) 的前 18 位，确保唯一性且长度为 20。
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Optional, Set, Tuple

import httpx

# 复用 arXiv 爬虫中的运动科学关键词，作为 BioRxiv 的 L1 过滤条件
from modules.arxiv.services.arxiv_crawler import SPORTS_KEYWORDS

logger = logging.getLogger(__name__)

BIORXIV_API_BASE = "https://api.biorxiv.org/details/biorxiv"

# 预处理为小写，便于快速匹配
SPORTS_KEYWORDS_LOWER = [kw.lower() for kw in SPORTS_KEYWORDS]
TOKEN_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


@dataclass
class BiorxivRecord:
    """内部使用的 BioRxiv 记录结构"""

    doi: str
    title: str
    abstract: str
    authors_raw: str
    category: Optional[str]
    date_str: str
    version: Optional[int] = None

    @property
    def submitted_date(self) -> Optional[date]:
        try:
            return datetime.strptime(self.date_str, "%Y-%m-%d").date()
        except Exception:
            return None


class BiorxivCrawler:
    """BioRxiv 爬取器（L1 层）"""

    def __init__(self, page_delay: int = 3) -> None:
        """初始化爬取器。

        Args:
            page_delay: 分页请求之间的延迟（秒），默认 3 秒。
        """
        self.page_delay = page_delay

    def _stable_id_from_doi(self, doi: str) -> str:
        """根据 DOI 生成 arxiv_id 字段可用的稳定短 ID（长度 20）。"""
        h = hashlib.md5(doi.encode("utf-8")).hexdigest()
        return "bx" + h[:18]

    def _is_sports_related(self, title: str, abstract: str) -> bool:
        """使用与 arXiv 相同的一套运动关键词做 L1 过滤（标题+摘要）。

        注意：对单词类关键词使用 token 精确匹配，避免 "sport" 命中 "support/transport" 等造成大量误召回。
        """
        raw = f"{title or ''} {abstract or ''}".lower()
        text = re.sub(r"\s+", " ", raw).strip()
        tokens = set(TOKEN_RE.findall(text))
        for kw in SPORTS_KEYWORDS_LOWER:
            if not kw:
                continue
            if " " in kw:
                if kw in text:
                    return True
            else:
                if kw in tokens:
                    return True
        return False

    def _parse_record(self, item: Dict) -> Optional[Dict]:
        """将 BioRxiv API 的单条记录映射为 article dict。"""
        doi = item.get("doi")
        if not doi:
            return None

        title = item.get("title") or ""
        abstract = item.get("abstract") or ""

        # L1：使用与 arXiv 相同的关键词表先做一次粗过滤
        if not self._is_sports_related(title, abstract):
            return None

        authors_raw = item.get("authors") or ""
        category = item.get("category") or None
        date_str = item.get("date") or ""
        try:
            version = int(item.get("version") or 1)
        except Exception:
            version = 1

        record = BiorxivRecord(
            doi=doi,
            title=title,
            abstract=abstract,
            authors_raw=authors_raw,
            category=category,
            date_str=date_str,
            version=version,
        )

        submitted = record.submitted_date
        if submitted is None:
            return None

        # authors 字符串形如 "Lastname, Firstname; Lastname2, Firstname2"
        authors_list: List[Dict] = []
        for part in authors_raw.split(";"):
            name = part.strip()
            if not name:
                continue
            authors_list.append({"name": name})

        # 生成用于 arxiv_articles 表的稳定 ID
        arxiv_id = self._stable_id_from_doi(doi)

        # 构建 BioRxiv 内容链接（约定：content/<doi>v<version>）
        abs_url = f"https://www.biorxiv.org/content/{doi}v{version}"
        pdf_url = abs_url + ".full.pdf"

        return {
            "arxiv_id": arxiv_id,
            "version": version,
            "source": "biorxiv",
            "title": title,
            "abstract": abstract,
            "authors": authors_list,
            "primary_category": category,
            "categories": [category] if category else [],
            "published_date": submitted,
            "updated_date": submitted,
            "submitted_date": submitted,
            "pdf_url": pdf_url,
            "abs_url": abs_url,
        }

    def _fetch_page(self, date_from: str, date_to: str, cursor: int) -> Tuple[List[Dict], Dict]:
        """调用 BioRxiv details API 获取一页记录及分页元数据。

        返回:
            (collection, meta) 元组，其中 meta 至少包含:
            - total: 当前日期区间内 API 报告的总记录数（含多版本）
            - count: 当前页记录数
            - count_new_papers: 当前区间内新论文总数（按 DOI 去重）
            - cursor: 本次请求使用的游标
            - interval: 本次请求的日期区间字符串

        注意：
            - 为了避免将临时的网络/SSL问题误判为“无更多数据”，这里在失败时会重试多次；
            - 若多次重试后仍失败，则抛出异常，由上层任务整体失败并记录日志，避免静默丢数。
        """
        url = f"{BIORXIV_API_BASE}/{date_from}/{date_to}/{cursor}"
        logger.info(f"BioRxiv L1请求：{url}")

        last_error: Optional[Exception] = None
        for attempt in range(3):
            try:
                resp = httpx.get(url, timeout=30.0)
                resp.raise_for_status()
                break
            except Exception as e:
                last_error = e
                logger.error(
                    f"BioRxiv 请求失败（cursor={cursor}，第{attempt + 1}次尝试）: {e}"
                )
                # 前两次失败时短暂停顿后重试，第三次仍失败则抛出异常
                if attempt < 2:
                    time.sleep(2)
                else:
                    raise

        try:
            data = resp.json()
        except Exception as e:
            logger.error(f"BioRxiv 响应解析失败（cursor={cursor}）: {e}")
            # JSON 解析失败通常意味着本页数据不可用，直接抛出异常让上层感知失败
            raise

        collection = data.get("collection") or []
        messages = data.get("messages") or []

        meta: Dict = {
            "total": 0,
            "count": len(collection),
            "count_new_papers": 0,
            "cursor": cursor,
            "interval": f"{date_from}:{date_to}",
        }

        if messages:
            msg0 = messages[0] or {}
            # total: 区间内总记录数（含多版本）
            try:
                if msg0.get("total") is not None:
                    meta["total"] = int(msg0.get("total"))
            except Exception:
                pass

            # count: 当前页记录数（通常等于 len(collection)）
            try:
                if msg0.get("count") is not None:
                    meta["count"] = int(msg0.get("count"))
            except Exception:
                meta["count"] = len(collection)

            # count_new_papers: 区间内新论文数（按 DOI 去重）
            try:
                if msg0.get("count_new_papers") is not None:
                    meta["count_new_papers"] = int(msg0.get("count_new_papers"))
            except Exception:
                pass

            # cursor / interval 原样带回，便于调试
            if msg0.get("cursor") is not None:
                meta["cursor"] = msg0.get("cursor")
            if msg0.get("interval"):
                meta["interval"] = msg0.get("interval")

        return collection, meta

    def crawl_date_range(self, date_from: date, date_to: date, batch_delay: Optional[int] = None) -> List[Dict]:
        """按日期范围抓取 BioRxiv 预印本。

        Args:
            date_from: 起始日期
            date_to: 结束日期
            batch_delay: 分页之间的延迟，优先级高于初始化参数

        Returns:
            去重后的文章列表（每条为 arxiv_articles 兼容的 dict）
        """
        delay = self.page_delay if batch_delay is None else batch_delay
        date_from_str = date_from.strftime("%Y-%m-%d")
        date_to_str = date_to.strftime("%Y-%m-%d")

        logger.info(f"BioRxiv L1爬取：{date_from_str} 至 {date_to_str}")

        # all_articles：已经通过运动关键词 L1 粗过滤的记录
        all_articles: List[Dict] = []
        # raw_total_seen：实际抓到的原始记录条数（可能包含重复 DOI / 多版本）
        raw_total_seen = 0
        # raw_total_api：API messages.total 报告的区间内总记录数
        raw_total_api: Optional[int] = None
        # 以 DOI 为单位去重，用于检测是否在重复翻页
        seen_dois: Set[str] = set()

        # BioRxiv API 的 cursor 是“偏移量（offset）”，不是页码；下一页应当加上本页返回条数（通常 100）
        cursor = 0

        while True:
            page_items, meta = self._fetch_page(date_from_str, date_to_str, cursor)
            if not page_items:
                logger.info(f"BioRxiv L1 offset={cursor} 返回为空，结束分页")
                break

            # 首次从 API 元数据中读取 total，便于诊断和分页停止条件
            if raw_total_api is None and meta:
                total_from_api = int(meta.get("total") or 0)
                raw_total_api = total_from_api or None
                if total_from_api:
                    count_per_page = int(meta.get("count") or len(page_items)) or len(page_items)
                    expected_pages = (total_from_api + count_per_page - 1) // count_per_page if count_per_page else None
                    logger.info(
                        "BioRxiv L1 API 报告区间内共有 %s 条记录，预期页数约 %s 页（每页 %s 条）",
                        total_from_api,
                        expected_pages,
                        count_per_page,
                    )

            raw_total_seen += len(page_items)
            kept_this_page = 0
            new_dois_this_page = 0
            logger.info(f"BioRxiv L1 offset={cursor}，API 返回 {len(page_items)} 条")

            for item in page_items:
                doi = item.get("doi")
                if doi and doi not in seen_dois:
                    seen_dois.add(doi)
                    new_dois_this_page += 1

                try:
                    parsed = self._parse_record(item)
                    if parsed is not None:
                        all_articles.append(parsed)
                        kept_this_page += 1
                except Exception as e:
                    logger.error(f"解析 BioRxiv 记录失败: {e}")

            logger.info(
                "BioRxiv L1 offset=%s，运动关键词过滤后保留 %s 条，累计保留 %s 条 / 原始累计 %s 条（本页新增 DOI %s 个）",
                cursor,
                kept_this_page,
                len(all_articles),
                raw_total_seen,
                new_dois_this_page,
            )

            # 下一页游标（offset），按本页返回条数递增
            next_cursor = cursor + len(page_items)

            # 如果 API 报告了 total，则抓到最后一页后停止
            if raw_total_api is not None and next_cursor >= raw_total_api:
                logger.info("BioRxiv L1 已抓取到区间总数 %s（offset=%s），结束分页", raw_total_api, next_cursor)
                break

            # 兜底：如果本页没有任何新增 DOI，且游标不再推进，则避免死循环
            if next_cursor == cursor or (new_dois_this_page == 0 and cursor > 0):
                logger.warning(
                    "BioRxiv L1 本页无新增 DOI（offset=%s），为避免重复分页提前停止",
                    cursor,
                )
                break

            cursor = next_cursor

            logger.info(f"BioRxiv 翻页延迟 {delay} 秒...")
            time.sleep(delay)

        logger.info(
            "BioRxiv L1 完成：API 报告原始共 %s 条，实际抓取累计 %s 条，经运动关键词过滤后保留 %s 条",
            raw_total_api if raw_total_api is not None else "未知",
            raw_total_seen,
            len(all_articles),
        )

        # 按 arxiv_id 去重（实际上是基于 DOI 的 stable ID），保留最高版本
        # 先统计版本分布用于诊断
        doi_version_count: Dict[str, int] = {}
        for article in all_articles:
            aid = article["arxiv_id"]
            doi_version_count[aid] = doi_version_count.get(aid, 0) + 1

        # 打印版本分布统计
        if len(all_articles) > 0:
            max_versions = max(doi_version_count.values())
            avg_versions = sum(doi_version_count.values()) / len(doi_version_count)
            logger.info(
                f"BioRxiv 版本分布：{len(doi_version_count)} 个不同DOI，"
                f"平均每个DOI有 {avg_versions:.1f} 个版本，最多 {max_versions} 个版本"
            )

            # 打印版本数最多的前3个DOI，用于诊断
            top_3 = sorted(doi_version_count.items(), key=lambda x: x[1], reverse=True)[:3]
            for aid, count in top_3:
                # 找到对应文章的标题
                sample_article = next((a for a in all_articles if a["arxiv_id"] == aid), None)
                title = sample_article["title"][:50] if sample_article else "unknown"
                logger.info(f"  - {aid}: {count} 个版本 | {title}...")

        deduped: Dict[str, Dict] = {}
        for article in all_articles:
            aid = article["arxiv_id"]
            version = article.get("version", 1) or 1
            if aid not in deduped or version > deduped[aid].get("version", 1):
                deduped[aid] = article

        result = list(deduped.values())
        logger.info(
            f"BioRxiv 去重后：{len(result)} 篇（去重前 {len(all_articles)} 篇，经 L1 关键词过滤）"
        )
        return result
