"""
Celery 任务：文献流增量与回补（EDAT 72h / EDAT 7d / PDAT 7d）

说明：
- 不依赖旧的 PubMedCrawler；直接使用 core.external.pubmed + 当前模型层
- 与 scripts/ 中对应实现等价，便于由 Celery Beat 定时调度
"""
import asyncio
from datetime import datetime, timedelta
from typing import List, Set, Dict, Any

from celery import shared_task
from sqlalchemy import select

from core.database import get_db_session, init_database
from core.cache import init_cache
from core.external.pubmed import get_pubmed_client, map_pub_types_to_lit_types
from modules.literature_stream.models.literature import (
    Literature,
    CrawlTaskLog,
    SubjectCategoryConfig,
)
from modules.literature_stream.services.journal_matcher import JournalMatcher
from modules.literature_stream.services.llm_classifier import get_llm_classifier


async def _fetch_all_pmids_for_query(pubmed, query: str) -> List[str]:
    all_pmids: List[str] = []
    retstart = 0
    retmax = 9999
    while True:
        batch = await pubmed.search(query, retmax=retmax, retstart=retstart)
        if not batch:
            break
        all_pmids.extend(batch)
        if len(batch) < retmax:
            break
        retstart += retmax
    return all_pmids


async def _ingest_pmids(db, pubmed, pmids: List[str]) -> Dict[str, int]:
    matcher = JournalMatcher(db)
    saved = 0
    skipped = 0
    step = 50
    from dateutil import parser as date_parser

    for i in range(0, len(pmids), step):
        batch_pmids = pmids[i:i+step]
        summaries = await pubmed.fetch_summary(batch_pmids, use_cache=True)
        summary_map = {s['pmid']: s for s in summaries}

        # 预取摘要/类型并为LLM准备输入
        llm_inputs = []
        article_state: Dict[str, Dict[str, Any]] = {}
        for pmid in batch_pmids:
            s = summary_map.get(pmid) or {}
            abstract, pub_types, mesh_terms = await pubmed.fetch_abstract_and_types(pmid)
            article_state[pmid] = {
                "summary": s,
                "abstract": abstract or "",
                "pub_types": pub_types or [],
                "mesh_terms": mesh_terms or [],
            }
            llm_inputs.append({
                "title": s.get('title', ''),
                "abstract": abstract or "",
                "pub_types": pub_types or [],
                "mesh_terms": mesh_terms or [],
            })

        # 执行LLM分类，获得subject_categories等
        try:
            llm = get_llm_classifier()
            classifications = await llm.classify_batch(llm_inputs, batch_size=32)
            merged = llm.merge_results(llm_inputs, classifications)
        except Exception:
            # LLM不可用时退化为无分类
            merged = [{"subject_categories": [], "classification_confidence": [], "primary_category": None} for _ in llm_inputs]

        # 写入数据库
        for pmid, enriched in zip(batch_pmids, merged):
            # 去重
            exists = await db.execute(select(Literature).where(Literature.pmid == pmid))
            if exists.scalar() is not None:
                skipped += 1
                continue

            s = article_state[pmid]["summary"]
            abstract = article_state[pmid]["abstract"]
            pub_types = article_state[pmid]["pub_types"]
            mesh_terms = article_state[pmid]["mesh_terms"]

            lit_types = map_pub_types_to_lit_types(pub_types, mesh_terms, s.get('title', ''), abstract)

            j = await matcher.match_journal(issn=None, journal_name=s.get('source', ''))

            pub_date = datetime.utcnow().date()
            try:
                if s.get('pubdate'):
                    pub_date = date_parser.parse(s['pubdate']).date()
            except Exception:
                pass

            db.add(Literature(
                pmid=pmid,
                title=s.get('title', ''),
                abstract=abstract,
                authors=s.get('authors', []),
                publication_date=pub_date,
                journal_name=s.get('source', ''),
                journal_issn=j.get('issn'),
                journal_nlm_abbr=j.get('nlm_abbr'),
                journal_if_5y=j.get('if_5y'),
                journal_citescore=j.get('citescore'),
                journal_zone=j.get('zone'),
                doi=s.get('doi', ''),
                subject_categories=enriched.get('subject_categories', []),
                literature_types=lit_types,
                extra_metadata={
                    "classification_confidence": enriched.get('classification_confidence', []),
                    "primary_category": enriched.get('primary_category')
                }
            ))
            saved += 1

        await db.commit()

    return {"saved": saved, "skipped": skipped}


async def _run_by_category(date_filter_clause: str, mode: str) -> Dict[str, Any]:
    # 确保DB已初始化（Celery 进程不走 FastAPI 启动钩子）
    await init_database()
    try:
        await init_cache()
    except Exception:
        # 缓存可选，失败不阻塞任务
        pass
    pubmed = get_pubmed_client()
    async with get_db_session() as db:
        res = await db.execute(
            select(SubjectCategoryConfig)
            .where(SubjectCategoryConfig.is_enabled == True)
            .order_by(SubjectCategoryConfig.display_order)
        )
        categories = res.scalars().all()

        task = CrawlTaskLog(
            task_type=mode,
            category_key='ALL',
            query_params={'date_filter': date_filter_clause, 'mode': 'by_category'},
            status='running',
            started_at=datetime.utcnow(),
        )
        db.add(task)
        await db.commit()

        # 汇总PMIDs
        seen: Set[str] = set()
        for cat in categories:
            q = f"(\n{cat.pubmed_query}\n) AND {date_filter_clause}"
            pmids = await _fetch_all_pmids_for_query(pubmed, q)
            seen.update(pmids)

        pmid_list = list(seen)
        if not pmid_list:
            task.status = 'success'
            task.total_fetched = 0
            task.new_inserted = 0
            task.duplicates_skipped = 0
            task.finished_at = datetime.utcnow()
            await db.commit()
            return {"total": 0, "saved": 0, "skipped": 0}

        # 入库
        stats = await _ingest_pmids(db, pubmed, pmid_list)
        task.status = 'success'
        task.total_fetched = len(pmid_list)
        task.new_inserted = stats["saved"]
        task.duplicates_skipped = stats["skipped"]
        task.finished_at = datetime.utcnow()
        await db.commit()

        return {"total": len(pmid_list), **stats}


@shared_task(name="literature_stream.incremental_edat_72h")
def incremental_edat_72h() -> Dict[str, Any]:
    end_utc = datetime.utcnow()
    start_utc = end_utc - timedelta(hours=72)
    edat_start = start_utc.strftime('%Y/%m/%d %H:%M:%S')
    edat_end = end_utc.strftime('%Y/%m/%d %H:%M:%S')
    date_filter = f'("{edat_start}"[EDAT] : "{edat_end}"[EDAT])'
    return asyncio.run(_run_by_category(date_filter, mode='incremental_edat_72h'))


@shared_task(name="literature_stream.rollup_edat_7d")
def rollup_edat_7d() -> Dict[str, Any]:
    end_utc = datetime.utcnow()
    start_utc = end_utc - timedelta(days=7)
    edat_start = start_utc.strftime('%Y/%m/%d %H:%M:%S')
    edat_end = end_utc.strftime('%Y/%m/%d %H:%M:%S')
    date_filter = f'("{edat_start}"[EDAT] : "{edat_end}"[EDAT])'
    return asyncio.run(_run_by_category(date_filter, mode='rollup_edat_7d'))


@shared_task(name="literature_stream.backfill_pdat_7d")
def backfill_pdat_7d() -> Dict[str, Any]:
    end_utc = datetime.utcnow()
    start_utc = end_utc - timedelta(days=7)
    pdat_start = start_utc.strftime('%Y/%m/%d')
    pdat_end = end_utc.strftime('%Y/%m/%d')
    date_filter = f'("{pdat_start}"[dp] : "{pdat_end}"[dp])'
    return asyncio.run(_run_by_category(date_filter, mode='backfill_pdat_7d'))


