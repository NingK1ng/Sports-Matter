"""
知识图谱快照生成任务
"""
import logging
from datetime import datetime
from celery import shared_task
from sqlalchemy import select, desc
from core.task_runtime import run_async
from core.database import get_session_factory, init_database
from modules.knowledge_graph.models.snapshot import GraphSnapshot, CommunitySnapshot
from modules.knowledge_graph.services.kg_wiw_generator import KGWiWGenerator
from modules.knowledge_graph.services.snapshot_manager import SnapshotManager

logger = logging.getLogger(__name__)


async def _build_window(window: str) -> dict:
    """Build each source in a fresh session and report actual failures to Celery."""
    from zoneinfo import ZoneInfo
    await init_database()
    as_of = datetime.now(ZoneInfo("Asia/Shanghai"))
    session_factory = get_session_factory()
    completed, failed = [], []
    for source in ["sports_journals", "cns", "literature"]:
        async with session_factory() as db:
            try:
                snapshot = await SnapshotManager(db).create_or_get_snapshot(source, window, as_of)
                if snapshot is None:
                    raise RuntimeError("snapshot generation returned no result")
                completed.append(source)
            except Exception:
                await db.rollback()
                logger.exception("Failed to build %s/%s snapshot", source, window)
                failed.append(source)
    if failed:
        raise RuntimeError(f"Snapshot {window} failed for {', '.join(failed)}; completed: {', '.join(completed)}")
    return {"status": "success", "window": window, "sources": completed}


@shared_task(name="knowledge_graph.build_snapshot_1d", autoretry_for=(Exception,), retry_backoff=60, max_retries=2)
def build_snapshot_1d():
    return run_async(_build_window("1d"))


@shared_task(name="knowledge_graph.build_snapshot_7d", autoretry_for=(Exception,), retry_backoff=60, max_retries=2)
def build_snapshot_7d():
    return run_async(_build_window("7d"))


@shared_task(name="knowledge_graph.build_snapshot_30d", autoretry_for=(Exception,), retry_backoff=60, max_retries=2)
def build_snapshot_30d():
    return run_async(_build_window("30d"))


@shared_task(name="knowledge_graph.build_snapshot_180d", autoretry_for=(Exception,), retry_backoff=60, max_retries=2)
def build_snapshot_180d():
    return run_async(_build_window("180d"))


@shared_task(name="knowledge_graph.precompute_wiw")
def precompute_wiw(
    top_n: int | None = None,
    windows: str | None = None,
    sources: str | None = None,
    force: bool = False,
):
    """
    预生成社区 WiW 摘要（写入 CommunitySnapshot.metrics 缓存），避免用户首次访问等待。

    - 默认：对 latest 的 1d/7d/30d 快照，每个 source 预生成 Top5 社区 WiW
    - 可通过环境变量或参数覆盖：
      - KG_WIW_PRECOMPUTE_TOP_N（默认5）
      - KG_WIW_PRECOMPUTE_WINDOWS（默认 1d,7d,30d）
      - KG_WIW_PRECOMPUTE_SOURCES（默认 literature,sports_journals,cns）
      - KG_WIW_PRECOMPUTE_CONCURRENCY（默认3）
    """
    import asyncio
    import os

    def _parse_csv(v: str | None) -> list[str]:
        return [x.strip() for x in (v or "").split(",") if x and x.strip()]

    async def _run():
        await init_database()
        session_factory = get_session_factory()
        async with session_factory() as db:
            try:
                generator = KGWiWGenerator()
            except Exception as e:
                logger.error("KG WiW precompute init failed: %s", e)
                return {"status": "failed", "error": str(e)}

            cache_key = "wiw_text_zh_v3"
            cache_key_citations = "wiw_citations_zh_v3"

            try:
                cfg_top_n = int(os.getenv("KG_WIW_PRECOMPUTE_TOP_N", "5"))
            except Exception:
                cfg_top_n = 5
            n = int(top_n) if top_n is not None else cfg_top_n
            if n <= 0:
                return {"status": "skipped", "reason": "top_n<=0"}

            win_list = _parse_csv(windows) or _parse_csv(os.getenv("KG_WIW_PRECOMPUTE_WINDOWS", "1d,7d,30d"))
            src_list = _parse_csv(sources) or _parse_csv(os.getenv("KG_WIW_PRECOMPUTE_SOURCES", "literature,sports_journals,cns"))
            if not win_list or not src_list:
                return {"status": "skipped", "reason": "no windows/sources"}

            try:
                concurrency = max(1, int(os.getenv("KG_WIW_PRECOMPUTE_CONCURRENCY", "3")))
            except Exception:
                concurrency = 3

            sem = asyncio.Semaphore(concurrency)

            total_candidates = 0
            total_generated = 0
            total_skipped = 0
            total_failed = 0

            async def _generate_one(snapshot: GraphSnapshot, community: CommunitySnapshot) -> dict | None:
                metrics = community.metrics or {}
                cached = (metrics.get(cache_key) or "").strip() if isinstance(metrics, dict) else ""
                if cached and not force:
                    return None

                rep_terms = community.representative_terms or []
                main_label = ""
                if rep_terms:
                    first = rep_terms[0]
                    if isinstance(first, dict):
                        main_label = (first.get("term") or "").strip()
                    elif isinstance(first, str):
                        main_label = first.strip()

                async with sem:
                    wiw_text = await generator.generate_for_community(
                        community_label=main_label,
                        representative_terms=rep_terms,
                        top_papers=community.top_papers or [],
                        window=snapshot.window,
                        as_of=snapshot.as_of.strftime("%Y-%m-%d"),
                        language="zh",
                    )

                wiw_text = (wiw_text or "").strip()
                if not wiw_text:
                    raise RuntimeError("empty wiw_text")

                # 引用映射（index -> url）
                citations_list: list[dict] = []
                for idx, p in enumerate(community.top_papers or [], 1):
                    if idx > 10:
                        break
                    pmid = (p.get("pmid") if isinstance(p, dict) else None) or None
                    doi = (p.get("doi") if isinstance(p, dict) else None) or None
                    url = None
                    if pmid:
                        p_str = str(pmid).strip()
                        if p_str.isdigit():
                            url = f"https://pubmed.ncbi.nlm.nih.gov/{p_str}/"
                        elif p_str.lower().startswith("doi:"):
                            doi_val = p_str[4:].strip()
                            if doi_val:
                                doi = doi_val
                                url = f"https://doi.org/{doi_val}"
                    if not url and doi:
                        url = f"https://doi.org/{doi}"
                    citations_list.append(
                        {
                            "index": idx,
                            "pmid": pmid,
                            "doi": doi,
                            "url": url,
                        }
                    )

                return {
                    "snapshot_id": snapshot.snapshot_id,
                    "community_id": community.community_id,
                    "wiw_text": wiw_text,
                    "citations": citations_list,
                }

            for window in win_list:
                for source in src_list:
                    snap_res = await db.execute(
                        select(GraphSnapshot)
                        .where(GraphSnapshot.source == source, GraphSnapshot.window == window)
                        .order_by(desc(GraphSnapshot.as_of))
                        .limit(1)
                    )
                    snapshot = snap_res.scalar_one_or_none()
                    if not snapshot:
                        continue

                    comm_res = await db.execute(
                        select(CommunitySnapshot)
                        .where(CommunitySnapshot.snapshot_id == snapshot.snapshot_id)
                        .order_by(desc(CommunitySnapshot.size))
                        .limit(n)
                    )
                    communities = comm_res.scalars().all()
                    if not communities:
                        continue

                    total_candidates += len(communities)

                    tasks = []
                    for comm in communities:
                        metrics = comm.metrics or {}
                        cached = (metrics.get(cache_key) or "").strip() if isinstance(metrics, dict) else ""
                        if cached and not force:
                            total_skipped += 1
                            continue
                        tasks.append((snapshot, comm))

                    if not tasks:
                        continue

                    results = await asyncio.gather(
                        *[_generate_one(s, c) for s, c in tasks],
                        return_exceptions=True,
                    )

                    for r in results:
                        if isinstance(r, Exception):
                            total_failed += 1
                            logger.error("KG WiW precompute failed: %s", r)
                            continue
                        if not r:
                            continue

                        comm_id = r.get("community_id")
                        wiw_text = (r.get("wiw_text") or "").strip()
                        citations = r.get("citations") or []
                        if not comm_id or not wiw_text:
                            total_failed += 1
                            continue

                        # 顺序写库：避免并发操作同一 AsyncSession
                        for comm in communities:
                            if comm.community_id == comm_id:
                                metrics_prev = comm.metrics if isinstance(comm.metrics, dict) else {}
                                metrics = dict(metrics_prev)
                                metrics[cache_key] = wiw_text
                                metrics[cache_key_citations] = citations
                                metrics[f"{cache_key}_generated_at"] = datetime.utcnow().isoformat()
                                comm.metrics = metrics
                                db.add(comm)
                                break
                        total_generated += 1

                    await db.commit()

            return {
                "status": "success",
                "timestamp": datetime.utcnow().isoformat(),
                "candidates": total_candidates,
                "generated": total_generated,
                "skipped": total_skipped,
                "failed": total_failed,
                "top_n": n,
                "windows": win_list,
                "sources": src_list,
                "concurrency": concurrency,
            }

    return run_async(_run())
