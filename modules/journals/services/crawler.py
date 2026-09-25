"""
Crossref爬虫服务
任务2.2: 实现增量爬取和历史回填
"""
import asyncio
from datetime import datetime, timedelta, timezone, date
from typing import Dict, Any, List, Optional
import logging
import json
import os
from pathlib import Path

import httpx
from core.config import settings
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert

from modules.journals.models.journal import (
    JournalArticle,
    JournalMetadata,
    JournalCrawlState,
    CrawlTaskLog,
)
from modules.journals.services.crossref_client import CrossrefJournalClient
from modules.journals.services.text_cleaner import clean_jats_abstract
from modules.journals.services.abstract_fetcher import AbstractFetcher
from modules.journals.services.label_calculator import LabelCalculator
from modules.journals.services.research_filter import get_research_filter

logger = logging.getLogger(__name__)


class JournalCrawler:
    """期刊爬虫"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.client = CrossrefJournalClient()
        self.abstract_fetcher = AbstractFetcher()
        self.label_calculator = LabelCalculator()
        self.research_filter = None

    def _parse_csv_set(self, value: Optional[str]) -> set[str]:
        return {part.strip() for part in (value or "").split(",") if part and part.strip()}

    def _effective_enable_llm_filter(self, issn_l: str, enable_llm_filter: bool) -> bool:
        if not enable_llm_filter:
            return False
        disabled = self._parse_csv_set(settings.journals_disable_llm_filter_issns)
        return issn_l not in disabled

    def _effective_translate_titles(self, issn_l: str, translate_titles: bool) -> bool:
        if not translate_titles:
            return False
        disabled = self._parse_csv_set(settings.journals_disable_title_translation_issns)
        return issn_l not in disabled

    def _get_title_translation_cutoff(self) -> Optional[date]:
        raw = (settings.journals_title_translation_from_date or "").strip()
        if not raw:
            return None
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            logger.warning(
                "JOURNALS_TITLE_TRANSLATION_FROM_DATE=%s 无法解析，忽略该限制（格式需 YYYY-MM-DD）",
                raw,
            )
            return None

    async def incremental_crawl(
        self,
        issn_l: str,
        overlap_hours: int = 48,
        window_days: int = 3,
        safety_gap_hours: int = 0,
        enable_llm_filter: bool = True,
        translate_titles: bool = True,
        crossref_rows: Optional[int] = None,
        crossref_sleep_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        增量爬取（每日凌晨4点执行）

        改进：使用72小时（3天）窗口，与模块1保持一致，提高容错性

        Args:
            issn_l: 期刊ISSN-L
            overlap_hours: 重叠时间（小时，避免漏抓），默认3小时
            window_days: 时间窗口（天），默认3天
            enable_llm_filter: 是否启用LLM过滤非研究文章，默认True

        Returns:
            爬取结果统计
        """
        logger.info(f"开始增量爬取: {issn_l} (窗口={window_days}天)")

        enable_llm_filter = self._effective_enable_llm_filter(issn_l, enable_llm_filter)
        translate_titles = self._effective_translate_titles(issn_l, translate_titles)
        
        # 创建任务日志
        log = CrawlTaskLog(
            task_type="incremental",
            issn_l=issn_l,
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        self.session.add(log)
        await self.session.commit()
        
        try:
            # 获取期刊元数据
            result = await self.session.execute(
                select(JournalMetadata).where(JournalMetadata.issn_l == issn_l)
            )
            journal = result.scalar_one_or_none()
            if not journal:
                raise ValueError(f"期刊{issn_l}不存在")
            
            now = datetime.now(timezone.utc)
            window_until = now - timedelta(hours=safety_gap_hours)
            result_state = await self.session.execute(
                select(JournalCrawlState).where(JournalCrawlState.issn_l == issn_l)
            )
            state = result_state.scalar_one_or_none()
            if state and state.last_crawled_until:
                lf = state.last_crawled_until
                # 规范为UTC aware
                if lf.tzinfo is None:
                    lf = lf.replace(tzinfo=timezone.utc)
                else:
                    lf = lf.astimezone(timezone.utc)
                base_from = lf
            else:
                base_from = now - timedelta(days=window_days)
            window_from = base_from - timedelta(hours=overlap_hours)
            if window_from >= window_until:
                window_from = window_until - timedelta(hours=1)
            
            # 格式化为YYYY-MM-DD
            from_date = window_from.strftime("%Y-%m-%d")
            until_date = window_until.strftime("%Y-%m-%d")

            # index-date 增量窗口可能会命中大量“历史文章被更新”的记录。
            # 为避免出现“今日上新但发表很久以前”的噪声，同时控制 LLM 成本，
            # 这里为 index-date 查询增加一个可配置的 pub-date 回看窗口。
            # - 默认回看 60 天（可通过环境变量调整）
            # - 设置为 0/空 表示不限制 pub-date（仅用 index-date）
            pub_lookback_env = (os.getenv("JOURNALS_INDEXED_PUBDATE_LOOKBACK_DAYS") or "60").strip()
            try:
                pub_lookback_days = int(pub_lookback_env)
            except ValueError:
                logger.warning(
                    "JOURNALS_INDEXED_PUBDATE_LOOKBACK_DAYS=%s 无法解析，回退为 60",
                    pub_lookback_env,
                )
                pub_lookback_days = 60

            if pub_lookback_days > 0:
                from_pub_date = (window_until - timedelta(days=pub_lookback_days)).strftime("%Y-%m-%d")
                until_pub_date = until_date
            else:
                from_pub_date = None
                until_pub_date = None
            
            log.window_from = window_from
            log.window_until = window_until
            await self.session.commit()
            
            # 爬取文章（默认使用 index-date，必要时回退到 pub-date）
            # 优先使用ISSN-L（print），因为Crossref对某些期刊的electronic ISSN支持不完整
            stats = await self._crawl_articles(
                issn_l=issn_l,
                issn_query=journal.issn_print or journal.issn_l,
                category=journal.category,
                journal_name=journal.display_name,
                from_indexed_date=from_date,
                until_indexed_date=until_date,
                from_pub_date=from_pub_date,
                until_pub_date=until_pub_date,
                enable_llm_filter=enable_llm_filter,
                translate_titles=translate_titles,
                crossref_rows=crossref_rows,
                crossref_sleep_seconds=crossref_sleep_seconds,
            )
            
            # 更新日志
            log.status = "success"
            log.total_fetched = stats["total"]
            log.new_inserted = stats["new"]
            log.updated_count = stats["updated"]
            log.finished_at = datetime.now(timezone.utc)

            # 更新爬取状态
            await self._update_crawl_state(issn_l, window_until)

            await self.session.commit()

            filtered = stats.get("filtered", 0)
            logger.info(
                f"✅ 增量爬取完成: {issn_l}, 新增{stats['new']}篇"
                + (f", 过滤非研究{filtered}篇" if filtered > 0 else "")
            )
            return stats
        
        except Exception as e:
            logger.error(f"❌ 增量爬取失败: {issn_l}, {e}")
            log.status = "failed"
            log.error_message = str(e)
            log.finished_at = datetime.now(timezone.utc)
            await self.session.commit()
            raise

    async def cold_start_crawl(
        self,
        issn_l: str,
        from_date: str = "2020-01-01",
        *,
        abstract_strategy: str = "full",
        enable_llm_filter: bool = True,
        crossref_rows: Optional[int] = None,
        crossref_sleep_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        历史回填（冷启动）

        Args:
            issn_l: 期刊ISSN-L
            from_date: 起始日期（YYYY-MM-DD）
            abstract_strategy: 摘要抓取策略
            enable_llm_filter: 是否启用LLM过滤非研究文章

        Returns:
            爬取结果统计
        """
        logger.info(f"开始历史回填: {issn_l}, from={from_date}")

        enable_llm_filter = self._effective_enable_llm_filter(issn_l, enable_llm_filter)
        translate_titles = bool((settings.journals_title_translation_from_date or "").strip())
        translate_titles = self._effective_translate_titles(issn_l, translate_titles)
        
        # 创建任务日志
        log = CrawlTaskLog(
            task_type="cold_start",
            issn_l=issn_l,
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        self.session.add(log)
        await self.session.commit()
        
        try:
            # 获取期刊元数据
            result = await self.session.execute(
                select(JournalMetadata).where(JournalMetadata.issn_l == issn_l)
            )
            journal = result.scalar_one_or_none()
            if not journal:
                raise ValueError(f"期刊{issn_l}不存在")
            
            # 爬取文章（使用pub-date）
            # 优先使用ISSN-L（print），因为Crossref对某些期刊的electronic ISSN支持不完整
            stats = await self._crawl_articles(
                issn_l=issn_l,
                issn_query=journal.issn_print or journal.issn_l,
                category=journal.category,
                journal_name=journal.display_name,
                from_pub_date=from_date,
                use_pub_date=True,
                abstract_strategy=abstract_strategy,
                enable_llm_filter=enable_llm_filter,
                translate_titles=translate_titles,
                crossref_rows=crossref_rows,
                crossref_sleep_seconds=crossref_sleep_seconds,
            )
            
            # 更新日志
            log.status = "success"
            log.total_fetched = stats["total"]
            log.new_inserted = stats["new"]
            log.updated_count = stats["updated"]
            log.finished_at = datetime.now(timezone.utc)

            await self.session.commit()

            filtered = stats.get("filtered", 0)
            logger.info(
                f"✅ 历史回填完成: {issn_l}, 新增{stats['new']}篇"
                + (f", 过滤非研究{filtered}篇" if filtered > 0 else "")
            )
            return stats
        
        except Exception as e:
            logger.error(f"❌ 历史回填失败: {issn_l}, {e}")
            log.status = "failed"
            log.error_message = str(e)
            log.finished_at = datetime.now(timezone.utc)
            await self.session.commit()
            raise

    async def _crawl_articles(
        self,
        issn_l: str,
        issn_query: str,
        category: str,
        journal_name: str,
        from_indexed_date: Optional[str] = None,
        until_indexed_date: Optional[str] = None,
        from_pub_date: Optional[str] = None,
        until_pub_date: Optional[str] = None,
        use_pub_date: bool = False,
        abstract_strategy: str = "full",
        enable_llm_filter: bool = True,
        translate_titles: bool = False,
        crossref_rows: Optional[int] = None,
        crossref_sleep_seconds: Optional[float] = None,
    ) -> Dict[str, int]:
        """
        爬取文章（内部方法）

        Args:
            enable_llm_filter: 是否启用LLM过滤非研究文章（默认启用）

        Returns:
            {"total": 总数, "new": 新增数, "updated": 更新数, "filtered": 过滤数}
        """
        min_pub_year_env = (os.getenv("JOURNALS_MIN_PUBLICATION_YEAR") or "2020").strip()
        min_pub_year: Optional[int]
        if not min_pub_year_env or min_pub_year_env == "0":
            min_pub_year = None
        else:
            try:
                min_pub_year = int(min_pub_year_env)
            except ValueError:
                logger.warning(
                    "JOURNALS_MIN_PUBLICATION_YEAR=%s 无法解析，回退为 2020",
                    min_pub_year_env,
                )
                min_pub_year = 2020

        total = 0
        new = 0
        updated = 0
        filtered_non_research = 0
        filtered_by_year = 0
        cursor = "*"
        total_results_hint = 0
        page_index = 0
        started_at = datetime.utcnow()
        missing_abstract_dois: List[str] = []
        strategy = (abstract_strategy or "full").lower()
        enrich_abstract = strategy in ("fast", "full")

        rows = crossref_rows
        if rows is None:
            rows_env = (os.getenv("JOURNALS_CROSSREF_ROWS") or "100").strip()
            try:
                rows = int(rows_env)
            except ValueError:
                logger.warning("JOURNALS_CROSSREF_ROWS=%s 无法解析，回退为 100", rows_env)
                rows = 100
        else:
            try:
                rows = int(rows)
            except (TypeError, ValueError):
                logger.warning("crossref_rows=%s 无法解析，回退为 100", crossref_rows)
                rows = 100
        rows = max(1, min(rows, 1000))

        sleep_seconds = crossref_sleep_seconds
        if sleep_seconds is None:
            sleep_env = (os.getenv("JOURNALS_CROSSREF_SLEEP_SECONDS") or "1").strip()
            try:
                sleep_seconds = float(sleep_env)
            except ValueError:
                logger.warning(
                    "JOURNALS_CROSSREF_SLEEP_SECONDS=%s 无法解析，回退为 1", sleep_env
                )
                sleep_seconds = 1.0
        else:
            try:
                sleep_seconds = float(sleep_seconds)
            except (TypeError, ValueError):
                logger.warning(
                    "crossref_sleep_seconds=%s 无法解析，回退为 1", crossref_sleep_seconds
                )
                sleep_seconds = 1.0
        sleep_seconds = max(0.0, sleep_seconds)

        translator = None
        if translate_titles:
            try:
                from core.services.batch_translator import BatchTranslator

                translator = BatchTranslator()
            except Exception as e:
                translator = None
                translate_titles = False
                logger.warning("BatchTranslator 初始化失败，跳过标题翻译: %s", e)

        title_translation_cutoff = self._get_title_translation_cutoff()

        async def _fetch_page(cursor_value: str) -> Dict[str, Any]:
            nonlocal use_pub_date, from_pub_date
            while True:
                try:
                    if use_pub_date:
                        if not from_pub_date:
                            # 回退到 pub-date 时，确保有可用的起始日期
                            from_pub_date = from_indexed_date or from_pub_date
                        if not from_pub_date:
                            raise ValueError("pub-date 查询缺少 from_pub_date/from_indexed_date")
                        return await self.client.search_by_issn_pub_date(
                            issn=issn_query,
                            from_pub_date=from_pub_date,
                            until_pub_date=until_pub_date,
                            cursor=cursor_value,
                            rows=rows,
                        )

                    return await self.client.search_by_issn_indexed_date(
                        issn=issn_query,
                        from_indexed_date=from_indexed_date or from_pub_date,
                        until_indexed_date=until_indexed_date,
                        from_pub_date=from_pub_date,
                        until_pub_date=until_pub_date,
                        cursor=cursor_value,
                        rows=rows,
                    )
                except httpx.HTTPStatusError as exc:
                    status_code = exc.response.status_code
                    if status_code == 400 and not use_pub_date:
                        logger.warning(
                            "Crossref index-date 不可用，期刊 %s 回退到 pub-date", issn_query
                        )
                        use_pub_date = True
                        continue
                    raise

        # Crossref cursor 有“有效期”：若每页处理耗时过长，下一页可能返回 404（cursor 过期）导致丢页。
        # 这里采用“先预取下一页，再处理当前页”的顺序，确保 next_cursor 在有效期内被使用。
        next_response: Optional[Dict[str, Any]] = None

        while cursor:
            try:
                if next_response is None:
                    response = await _fetch_page(cursor)
                else:
                    response = next_response
                    next_response = None
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                if status_code == 404:
                    # 保守：cursor 不可用时，保留已抓取部分直接结束循环，避免无限重试/重复分页
                    logger.warning(
                        "Crossref 返回404，终止本次分页: ISSN=%s cursor=%s 已处理=%d",
                        issn_query,
                        cursor[:20] if cursor else "None",
                        total,
                    )
                    break
                raise
            
            # Crossref 返回的总记录数（用于估算整体进度）
            if not total_results_hint:
                total_results_hint = int(response.get("total_results") or 0)

            items = response["items"]
            next_cursor = response["next_cursor"]
            
            if not items:
                break

            cursor = next_cursor
            if cursor:
                try:
                    next_response = await _fetch_page(cursor)
                except httpx.HTTPStatusError as exc:
                    status_code = exc.response.status_code
                    if status_code == 404:
                        logger.warning(
                            "Crossref 返回404（cursor可能已过期），终止后续分页: ISSN=%s cursor=%s 已处理=%d",
                            issn_query,
                            cursor[:20] if cursor else "None",
                            total,
                        )
                        cursor = None
                        next_response = None
                    else:
                        raise
            
            page_index += 1
            
            # 先解析本页所有文章
            parsed_items: list[Dict[str, Any]] = []
            for item in items:
                parsed = self.client.parse_article(item)
                if parsed:
                    if parsed.get("abstract"):
                        parsed["abstract"] = clean_jats_abstract(parsed["abstract"])
                    if min_pub_year is not None:
                        pub_date = parsed.get("publication_date")
                        pub_year = getattr(pub_date, "year", None)
                        if pub_year is not None and pub_year < min_pub_year:
                            filtered_by_year += 1
                            continue
                    parsed_items.append(parsed)

            # 低成本 LLM 批量过滤：每页一次，仅基于标题判断非研究杂项（保守）
            if enable_llm_filter and parsed_items:
                if self.research_filter is None:
                    self.research_filter = get_research_filter()
                try:
                    flags = await self.research_filter.classify_non_research_titles_batch(
                        [p.get("title") or "" for p in parsed_items],
                        max_tokens=256,
                    )
                    if len(flags) == len(parsed_items):
                        kept: list[Dict[str, Any]] = []
                        for p, is_non_research in zip(parsed_items, flags):
                            if is_non_research:
                                filtered_non_research += 1
                            else:
                                kept.append(p)
                        parsed_items = kept
                except Exception as e:
                    logger.warning("LLM 批量过滤失败，默认全部保留: %s", e)

            # 批量清洗摘要 & 多来源补齐（并发网络请求，串行 DB 写入）
            if enrich_abstract and parsed_items:
                import asyncio as _asyncio

                async def _enrich_one(p: Dict[str, Any]) -> None:
                    fallback = await self.abstract_fetcher.ensure_abstract(
                        doi=p["doi"],
                        crossref_abstract=p["abstract"],
                        crossref_pmid=p.get("pmid"),
                        landing_url=p.get("landing_page_url"),
                        mode=strategy,
                    )
                    p["abstract"] = fallback.abstract
                    p["abstract_source"] = fallback.source
                    p["pmid"] = fallback.pmid

                # 控制并发量，避免一次性起太多任务
                sem = _asyncio.Semaphore(32)

                async def _wrapped(p: Dict[str, Any]) -> None:
                    async with sem:
                        await _enrich_one(p)

                await _asyncio.gather(*[_wrapped(p) for p in parsed_items])

            # 入库（upsert）+ LLM 过滤
            processed_dois_for_translation: List[str] = []
            for parsed in parsed_items:
                if not parsed.get("abstract") or not str(parsed.get("abstract")).strip():
                    missing_abstract_dois.append(parsed["doi"])

                if enable_llm_filter:
                    if self.research_filter is None:
                        self.research_filter = get_research_filter()
                    is_research, reason, confidence = await self.research_filter.is_research_article(
                        title=parsed["title"],
                        abstract=parsed["abstract"] or "",
                        threshold=0.8
                    )

                    if not is_research:
                        filtered_non_research += 1
                        continue

                is_new = await self._upsert_article(
                    issn_l=issn_l,
                    category=category,
                    journal_name=journal_name,
                    article_data=parsed,
                )

                total += 1
                if is_new:
                    new += 1
                else:
                    updated += 1

                if translate_titles and parsed.get("doi"):
                    if title_translation_cutoff is not None:
                        pub_date = parsed.get("publication_date")
                        pub_day = getattr(pub_date, "date", None)
                        if callable(pub_day):
                            pub_date = pub_day()
                        if pub_date is not None and pub_date < title_translation_cutoff:
                            continue
                    processed_dois_for_translation.append(parsed["doi"])
            
            # 批量提交
            await self.session.commit()

            # 增量任务：自动翻译本页新增/更新文章的标题（只补齐 title_zh 为空的）
            if translate_titles and translator and processed_dois_for_translation:
                try:
                    translated_count = await self._translate_titles_by_dois(
                        translator,
                        processed_dois_for_translation,
                    )
                    if translated_count:
                        logger.info("🈶 自动翻译期刊文章标题: %d 篇", translated_count)
                except Exception as e:
                    logger.warning("自动翻译期刊标题失败（忽略，不中断主流程）: %s", e)
            
            # 礼貌延迟
            if sleep_seconds:
                await asyncio.sleep(sleep_seconds)

            # 进度日志（便于冷启动脚本观察进展）
            progress_pct = 0
            if total_results_hint > 0 and total_results_hint >= total:
                progress_pct = int(total * 100 / total_results_hint)

            elapsed_sec = (datetime.utcnow() - started_at).total_seconds()
            elapsed_min = elapsed_sec / 60 if elapsed_sec > 0 else 0.0
            eta_min = 0.0
            if total_results_hint > 0 and total > 0 and elapsed_sec > 5:
                remain = max(total_results_hint - total, 0)
                rate = total / elapsed_sec  # 篇/秒
                if rate > 0:
                    eta_min = remain / rate / 60

            per_page = len(items) or 100
            est_pages = (total_results_hint + per_page - 1) // per_page if total_results_hint > 0 else 0
            page_info = f"{page_index}/{est_pages or '?'}"

            msg = (
                f"爬取进度 | ISSN={issn_query} 页={page_info} "
                f"total={total}/{total_results_hint or '?'} "
                f"new={new} updated={updated} "
                f"filtered_by_year={filtered_by_year} "
                f"filtered_non_research={filtered_non_research} "
                f"progress≈{progress_pct}% "
            )
            if elapsed_min:
                msg += f"已用≈{elapsed_min:.1f}min "
            if eta_min:
                msg += f"预计剩余≈{eta_min:.1f}min "
            msg += f"cursor={cursor[:20] if cursor else 'None'}"
            logger.info(msg)
            # 同步到控制台，方便脚本运行时观察
            print(msg)

        backlog_file = None
        if missing_abstract_dois:
            backlog_file = self._persist_missing_abstracts(
                issn_l,
                missing_abstract_dois,
                strategy,
            )

        if filtered_non_research > 0:
            logger.info(f"🗑️  本次爬取过滤非研究文章: {filtered_non_research}篇")
        if filtered_by_year > 0 and min_pub_year is not None:
            logger.info(
                "🗑️  本次爬取过滤发表年份<%d: %d篇", min_pub_year, filtered_by_year
            )

        return {
            "total": total,
            "new": new,
            "updated": updated,
            "filtered": filtered_non_research,
            "filtered_by_year": filtered_by_year,
            "missing_abstracts": len(missing_abstract_dois),
            "backlog_file": str(backlog_file) if backlog_file else None,
        }

    async def _translate_titles_by_dois(
        self,
        translator: Any,
        dois: List[str],
    ) -> int:
        """批量翻译期刊文章标题（按 DOI 列表定位未翻译记录）。"""
        dois_unique = [d for d in dict.fromkeys(dois) if d]
        if not dois_unique:
            return 0

        result = await self.session.execute(
            select(JournalArticle.id).where(
                JournalArticle.doi.in_(dois_unique),
                JournalArticle.title_zh.is_(None),
            )
        )
        article_ids = [row[0] for row in result.all()]
        if not article_ids:
            return 0

        translated_total = 0
        for i in range(0, len(article_ids), 50):
            translated = await translator.translate_titles_for_journals(
                article_ids[i : i + 50],
                self.session,
            )
            translated_total += len(translated)
        return translated_total

    def _persist_missing_abstracts(
        self,
        issn_l: str,
        dois: List[str],
        strategy: str,
    ) -> Optional[Path]:
        if not dois:
            return None
        logs_dir = Path("logs")
        logs_dir.mkdir(parents=True, exist_ok=True)
        file_path = logs_dir / f"abstract_backlog_{issn_l}.jsonl"
        timestamp = datetime.utcnow().isoformat()
        base = {
            "timestamp": timestamp,
            "issn_l": issn_l,
            "strategy": strategy,
        }
        with file_path.open("a", encoding="utf-8") as f:
            for doi in dois:
                record = dict(base)
                record["doi"] = doi
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        logger.info("📁 记录缺少摘要的DOI %s 个 -> %s", len(dois), file_path)
        return file_path

    async def _upsert_article(
        self,
        issn_l: str,
        category: str,
        journal_name: str,
        article_data: Dict[str, Any],
    ) -> bool:
        """
        插入或更新文章（幂等）
        
        Returns:
            True=新增, False=更新
        """
        time_labels = self.label_calculator.calculate_time_labels(
            article_data["published_at_precise"]
        )

        # 先尝试插入（不冲突时返回新增行）
        insert_stmt = insert(JournalArticle).values(
            doi=article_data["doi"],
            title=article_data["title"],
            abstract=article_data["abstract"],
            abstract_source=article_data["abstract_source"],
            authors=article_data["authors"],
            published_at_precise=article_data["published_at_precise"],
            publication_date=article_data["publication_date"],
            indexed_at=article_data["indexed_at"],
            pmid=article_data.get("pmid"),
            journal_issn=issn_l,
            journal_name=journal_name,
            category=category,
            labels=time_labels,
        ).on_conflict_do_nothing(index_elements=["doi"]).returning(JournalArticle.id)

        insert_result = await self.session.execute(insert_stmt)
        inserted_row = insert_result.fetchone()
        if inserted_row is not None:
            # 新增成功
            return True

        # 已存在：检查是否需要更新摘要/PMID
        result = await self.session.execute(
            select(
                JournalArticle.id,
                JournalArticle.abstract,
                JournalArticle.abstract_source,
                JournalArticle.pmid,
                JournalArticle.labels,
            ).where(JournalArticle.doi == article_data["doi"])
        )
        row = result.first()
        existing_abstract = row[1] if row else None
        existing_source = row[2] if row else "none"
        existing_pmid = row[3] if row else None
        existing_labels = row[4] if row else None

        new_abstract = article_data["abstract"]
        new_source = article_data["abstract_source"]

        should_replace_abstract = False
        if new_abstract and new_abstract.strip():
            if not existing_abstract or not existing_abstract.strip():
                should_replace_abstract = True
            else:
                should_replace_abstract = (
                    AbstractFetcher.priority(new_source)
                    >= AbstractFetcher.priority(existing_source)
                )

        update_values = {
            "title": article_data["title"],
            "indexed_at": article_data["indexed_at"],
            "updated_at": datetime.now(timezone.utc),
        }

        existing_non_time_labels = [
            l for l in (existing_labels or []) if l not in ("new", "recent")
        ]
        update_values["labels"] = list(
            dict.fromkeys([*time_labels, *existing_non_time_labels])
        )

        if should_replace_abstract:
            update_values["abstract"] = new_abstract
            update_values["abstract_source"] = new_source

        if article_data.get("pmid") and article_data["pmid"] != existing_pmid:
            update_values["pmid"] = article_data["pmid"]

        await self.session.execute(
            update(JournalArticle)
            .where(JournalArticle.doi == article_data["doi"])
            .values(**update_values)
        )
        return False

    async def _update_crawl_state(self, issn_l: str, last_crawled_until: datetime):
        """更新爬取状态"""
        stmt = insert(JournalCrawlState).values(
            issn_l=issn_l,
            last_crawled_until=last_crawled_until,
            updated_at=datetime.now(timezone.utc),
        ).on_conflict_do_update(
            index_elements=["issn_l"],
            set_={
                "last_crawled_until": last_crawled_until,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        await self.session.execute(stmt)

    async def close(self):
        """关闭客户端"""
        await self.client.close()
        await self.abstract_fetcher.close()
