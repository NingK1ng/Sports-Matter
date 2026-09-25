"""
知识图谱API路由
"""
import logging
import os
from datetime import datetime, date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from core.database import get_db
from modules.literature_pool.api.auth import is_member_user, require_login_user
from modules.knowledge_graph.api.schemas import (
    CommunityListResponse,
    CommunityDetail,
    WiWRequest,
    WiWResponse,
    WiWCitation,
)
from modules.knowledge_graph.models.snapshot import GraphSnapshot, CommunitySnapshot
from modules.knowledge_graph.services.snapshot_manager import SnapshotManager
from modules.knowledge_graph.services.kg_wiw_generator import KGWiWGenerator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/graph", tags=["knowledge-graph"])


@router.get("/communities", response_model=CommunityListResponse)
async def get_communities(
    source: str = Query(..., description="数据源: literature|sports_journals|cns"),
    window: str = Query(..., description="时间窗口: 1d|7d|30d|180d"),
    as_of: Optional[str] = Query(None, description="快照日期 (YYYY-MM-DD, UTC)"),
    db: AsyncSession = Depends(get_db),
    user=Depends(require_login_user),
):
    """
    获取社区列表（只读快照，不在请求时计算）

    - items: 社区摘要列表
    - snapshot: 快照元数据
    - total: 社区总数
    """
    if source not in ["literature", "sports_journals", "cns"]:
        raise HTTPException(status_code=400, detail="Invalid source")
    if window not in ["1d", "7d", "30d", "180d"]:
        raise HTTPException(status_code=400, detail="Invalid window")

    # 访问控制：非会员仅可访问「文献上新」图谱
    if source != "literature" and not is_member_user(user):
        raise HTTPException(
            status_code=403,
            detail={"code": "MEMBERSHIP_REQUIRED", "message": "非会员仅可访问「文献上新」图谱"},
        )

    # 查找匹配快照：指定 as_of 则精确匹配；否则取最新 as_of
    if as_of:
        try:
            as_of_date = datetime.strptime(as_of, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format, use YYYY-MM-DD")
        query = (
            select(GraphSnapshot)
            .where(
                GraphSnapshot.source == source,
                GraphSnapshot.window == window,
                GraphSnapshot.as_of == as_of_date,
            )
            .limit(1)
        )
    else:
        query = (
            select(GraphSnapshot)
            .where(
                GraphSnapshot.source == source,
                GraphSnapshot.window == window,
            )
            .order_by(desc(GraphSnapshot.as_of))
            .limit(1)
        )

    result = await db.execute(query)
    snapshot = result.scalar_one_or_none()
    if not snapshot:
        # Dev-only fallback: 自动创建快照（默认关闭，设置 KG_DEV_AUTOBUILD=1 开启）
        if os.getenv("KG_DEV_AUTOBUILD", "0").lower() in ("1", "true", "yes"):
            manager = SnapshotManager(db)
            # 选择 as_of：用户给定日期或今日UTC
            build_as_of = datetime.utcnow() if not as_of else datetime.strptime(as_of, "%Y-%m-%d")
            created = await manager.create_or_get_snapshot(source, window, build_as_of)
            if not created:
                raise HTTPException(status_code=404, detail="No data available (auto-build failed)")
            snapshot = created
        else:
            raise HTTPException(status_code=404, detail="No data available for this snapshot")

    return CommunityListResponse(
        items=snapshot.communities_summary or [],
        snapshot={
            "snapshot_id": snapshot.snapshot_id,
            "source": snapshot.source,
            "window": snapshot.window,
            "as_of": snapshot.as_of.strftime("%Y-%m-%d"),
            "meta": snapshot.meta or {},
        },
        total=len(snapshot.communities_summary or []),
    )


@router.get("/snapshots/{snapshot_id}/community/{community_id}", response_model=CommunityDetail)
async def get_community_detail(
    snapshot_id: str,
    community_id: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_login_user),
):
    """
    获取社区详情（使用snapshot_id确保跨快照唯一）
    
    返回体包含：
    - 完整的metrics（modularity, density, coverage, keywords_coverage, detector, degraded）
    - Top10论文
    - 代表性关键词（≤10）
    - LLM生成的摘要
    """
    # 查询快照
    snapshot_query = select(GraphSnapshot).where(GraphSnapshot.snapshot_id == snapshot_id)
    snapshot_result = await db.execute(snapshot_query)
    snapshot = snapshot_result.scalar_one_or_none()
    
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    if snapshot.source != "literature" and not is_member_user(user):
        raise HTTPException(
            status_code=403,
            detail={"code": "MEMBERSHIP_REQUIRED", "message": "非会员仅可访问「文献上新」图谱"},
        )
    
    # 查询社区详情
    comm_query = select(CommunitySnapshot).where(
        CommunitySnapshot.snapshot_id == snapshot_id,
        CommunitySnapshot.community_id == community_id
    )
    comm_result = await db.execute(comm_query)
    community = comm_result.scalar_one_or_none()
    
    if not community:
        raise HTTPException(status_code=404, detail="Community not found")
    
    # 构造响应
    return CommunityDetail(
        community_id=community.community_id,
        size=community.size,
        activity=community.activity,
        representative_terms=community.representative_terms,
        top_papers=community.top_papers,
        summary=community.summary,
        metrics=community.metrics,
        snapshot={
            "snapshot_id": snapshot.snapshot_id,
            "source": snapshot.source,
            "window": snapshot.window,
            "as_of": snapshot.as_of.strftime("%Y-%m-%d"),
            "meta": snapshot.meta,
        },
        graph_data=community.graph_data,
    )


@router.post("/snapshots/{snapshot_id}/community/{community_id}/wiw", response_model=WiWResponse)
async def generate_wiw_analysis(
    snapshot_id: str,
    community_id: str,
    request: WiWRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(require_login_user),
):
    """
    生成社区WiW分析（统一走snapshot路径，确保community_id在正确快照上下文）
    """
    # 查询社区详情
    comm_query = select(CommunitySnapshot).where(
        CommunitySnapshot.snapshot_id == snapshot_id,
        CommunitySnapshot.community_id == community_id
    )
    comm_result = await db.execute(comm_query)
    community = comm_result.scalar_one_or_none()
    if not community:
        raise HTTPException(status_code=404, detail="Community not found")

    # 查询快照元信息（用于传递时间窗口/日期给 LLM）
    snap_query = select(GraphSnapshot).where(GraphSnapshot.snapshot_id == snapshot_id)
    snap_result = await db.execute(snap_query)
    snapshot = snap_result.scalar_one_or_none()
    if not snapshot:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    if snapshot.source != "literature" and not is_member_user(user):
        raise HTTPException(
            status_code=403,
            detail={"code": "MEMBERSHIP_REQUIRED", "message": "非会员仅可访问「文献上新」图谱"},
        )

    # 优先使用缓存（metrics 中已保存的社区摘要文本）
    lang = (request.lang or "zh").lower()
    force_regenerate = request.force_regenerate or False
    metrics = community.metrics or {}
    # 带版本号的缓存键，避免旧版本格式干扰（v3: 严格失败、不再fallback）
    cache_key = "wiw_text_zh_v3" if lang == "zh" else f"wiw_text_{lang}_v3"
    cache_key_citations = "wiw_citations_zh_v3" if lang == "zh" else f"wiw_citations_{lang}_v3"
    cached_text = (metrics.get(cache_key) or "").strip() if isinstance(metrics, dict) else ""
    cached_ts = metrics.get(f"{cache_key}_generated_at") if isinstance(metrics, dict) else None
    cached_citations_raw = metrics.get(cache_key_citations) if isinstance(metrics, dict) else None

    citations: list[WiWCitation] = []
    if isinstance(cached_citations_raw, list):
        for c in cached_citations_raw:
            try:
                citations.append(
                    WiWCitation(
                        index=int(c.get("index")),
                        pmid=c.get("pmid"),
                        doi=c.get("doi"),
                        url=c.get("url"),
                    )
                )
            except Exception:
                continue

    # 如果不强制重新生成且缓存存在，直接返回缓存
    if cached_text and not force_regenerate:
        return WiWResponse(
            community_id=community_id,
            wiw_analysis=cached_text,
            generated_at=cached_ts or datetime.utcnow().isoformat(),
            citations=citations,
        )

    # 需要调用 LLM 生成新的社区中文摘要（WiW 风格），失败时直接报错
    import logging
    logger = logging.getLogger(__name__)
    try:
        generator = KGWiWGenerator()
    except ValueError as e:
        raise HTTPException(status_code=500, detail=f"WiW generator init failed: {e}")

    # 取社区主标签（优先 representative_terms[0]）
    rep_terms = community.representative_terms or []
    main_label = ""
    if rep_terms:
        first = rep_terms[0]
        if isinstance(first, dict):
            main_label = (first.get("term") or "").strip()
        elif isinstance(first, str):
            main_label = first.strip()

    try:
        wiw_text = await generator.generate_for_community(
            community_label=main_label,
            representative_terms=rep_terms,
            top_papers=community.top_papers or [],
            window=snapshot.window,
            as_of=snapshot.as_of.strftime("%Y-%m-%d"),
            language=lang,
        )
    except Exception as e:
        logger.exception("KG WiW generation failed for %s/%s", snapshot_id, community_id)
        raise HTTPException(status_code=500, detail=f"WiW generation failed: {e}")

    wiw_text = (wiw_text or "").strip()
    if not wiw_text:
        logger.error("KG WiW generation returned empty text for %s/%s", snapshot_id, community_id)
        raise HTTPException(status_code=500, detail="WiW generation failed: empty text")

    citations_list: list[dict] = []
    # 构造引用映射（index -> pmid/doi/url），不依赖 LLM
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

    # 将结果写回 metrics，随快照生命周期缓存
    metrics_prev = metrics if isinstance(metrics, dict) else {}
    metrics_new = dict(metrics_prev)
    metrics_new[cache_key] = wiw_text
    metrics_new[cache_key_citations] = citations_list
    metrics_new[f"{cache_key}_generated_at"] = datetime.utcnow().isoformat()
    community.metrics = metrics_new
    db.add(community)
    await db.commit()
    await db.refresh(community)

    return WiWResponse(
        community_id=community_id,
        wiw_analysis=wiw_text,
        generated_at=community.metrics.get(f"{cache_key}_generated_at") if isinstance(community.metrics, dict) else datetime.utcnow().isoformat(),
        citations=[WiWCitation(**c) for c in citations_list],
    )


@router.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "module": "knowledge-graph"}
