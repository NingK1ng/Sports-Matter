"""
Dev API - 文献池开发用端点

提供本地/开发环境下的一键生成WiW卡片能力，便于联调与验证。
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.config import settings
from modules.literature_pool.models.subscription import PoolSubscription
from sqlalchemy import select
from modules.literature_pool.services.pool_service import PoolService
from modules.literature_pool.services.wiw_service import WiWService
from modules.literature_pool.services.auth_service import AuthService


router = APIRouter(prefix="/dev", tags=["Dev"])


def _ensure_dev_env():
    env = str(settings.app_env).lower()
    if env not in ["development", "dev", "local", "staging"]:
        raise HTTPException(status_code=403, detail="DEV_ENDPOINT_DISABLED")


@router.post("/login")
async def dev_login(response: Response, db: AsyncSession = Depends(get_db)):
    """
    开发环境快速登录：自动创建测试用户并设置Cookie
    """
    _ensure_dev_env()

    auth_service = AuthService(db)

    # 创建或获取测试用户
    test_user = await auth_service.get_or_create_user(
        openid="dev_test_user_123",
        unionid="dev_union_123",
        nickname="测试用户",
        avatar=""
    )

    # 生成JWT
    jwt_token = auth_service.create_jwt_token(test_user.id)

    # 设置HttpOnly Cookie
    response.set_cookie(
        key="auth_token",
        value=jwt_token,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=7 * 24 * 60 * 60
    )

    return {
        "status": "success",
        "message": "Dev login successful",
        "user": {
            "id": test_user.id,
            "nickname": test_user.wechat_nickname,
            "openid": test_user.wechat_openid
        }
    }


@router.post("/quick_wiw")
async def dev_quick_wiw(
    keywords: str = Query(..., description="关键词，如'HIIT training'"),
    track: str = Query("stream", pattern="^(stream|journals)$"),
    db: AsyncSession = Depends(get_db),
):
    """
    🚀 开发快捷测试：输入关键词一键生成WiW卡片
    
    - 无需创建订阅，直接检索文献并生成WiW
    - stream: 从模块1文献库检索
    - journals: 从模块2顶刊库检索
    - 返回完整的WiW卡片JSON
    """
    _ensure_dev_env()
    
    from modules.literature_stream.services.search_service import LiteratureSearchService
    from modules.journals.services.search_service import SearchService as JournalSearchService
    from modules.journals.services.pubmed_enricher import PubMedEnricher
    from modules.research_gap.services.wiw_generator import WiWGenerator
    
    wiw_generator = WiWGenerator()
    
    # 1. 检索文献
    chosen_pmid = None
    article_info = None
    
    if track == "stream":
        # 模块1：literature表全文检索
        search_service = LiteratureSearchService(db)
        results, total = await search_service.search(
            keywords=keywords,
            limit=10
        )
        if not results:
            raise HTTPException(status_code=404, detail="no_literature_found")
        
        # 优先选择有PMID的文章
        for lit in results:
            if lit.pmid:
                chosen_pmid = lit.pmid
                article_info = {
                    "title": lit.title,
                    "journal_name": lit.journal_name,
                    "publication_date": str(lit.publication_date) if lit.publication_date else None
                }
                break
        
        if not chosen_pmid:
            raise HTTPException(status_code=400, detail="no_pmid_in_results")
    
    else:  # journals
        # 模块2：journal_articles表检索
        search_service = JournalSearchService(db)
        stmt = search_service.build_search_query(keywords, category=None)
        stmt = stmt.limit(15)
        result = await db.execute(stmt)
        articles = result.scalars().all()
        
        if not articles:
            raise HTTPException(status_code=404, detail="no_journals_found")
        
        # 准备候选PMID列表：优先直接PMID，其次DOI→PMID
        enricher = PubMedEnricher(db)
        candidate_pmids: list[tuple[str, dict]] = []
        for art in articles:
            pmid_val = None
            if art.pmid:
                pmid_val = art.pmid
            elif art.doi:
                try:
                    pmid_try = await enricher.find_pmid_by_doi(art.doi)
                    if pmid_try:
                        pmid_val = pmid_try
                except Exception:
                    pmid_val = None
            if pmid_val:
                candidate_pmids.append((pmid_val, {
                    "title": art.title,
                    "journal_name": art.journal_name,
                    "publication_date": str(art.publication_date) if art.publication_date else None
                }))
        
        if not candidate_pmids:
            raise HTTPException(status_code=400, detail="pmid_resolution_failed")
    
    # 2. 生成WiW卡片（journals模式尝试多个候选，stream模式只有一个）
    def _format_ok_resp(pmid_ok: str, info: dict, wiw_result: dict):
        wiw_card = {
            **wiw_result.get("card", {}),
            "references": wiw_result.get("references", []),
            "top_journal_recommendations": wiw_result.get("top_journal_recommendations", [])
        }
        return {
            "status": "success",
            "keywords": keywords,
            "track": track,
            "source_pmid": pmid_ok,
            "source_article": {
                "title": info.get("title", ""),
                "journal": info.get("journal_name", ""),
                "year": info.get("publication_date", "")[:4] if info.get("publication_date") else None
            },
            "wiw_card": wiw_card
        }

    if track == "stream":
        try:
            wiw_result = await wiw_generator.generate_wiw(
                pmid=chosen_pmid,
                top_k=10,
                language="zh"
            )
            return _format_ok_resp(chosen_pmid, article_info, wiw_result)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"WiW生成失败: {str(e)}")
    else:
        last_err = None
        for pmid_try, info in candidate_pmids:
            try:
                wiw_result = await wiw_generator.generate_wiw(
                    pmid=pmid_try,
                    top_k=10,
                    language="zh"
                )
                return _format_ok_resp(pmid_try, info, wiw_result)
            except Exception as e:
                last_err = e
                continue
        raise HTTPException(status_code=500, detail=f"WiW生成失败: {str(last_err) if last_err else 'no_valid_candidate'}")


@router.post("/generate_wiw")
async def dev_generate_wiw(
    subscription_id: int = Query(..., ge=1),
    track: str = Query("journals", pattern="^(stream|journals)$"),
    pmid: str | None = Query(None, description="可选，指定PMID直接生成映射"),
    db: AsyncSession = Depends(get_db),
):
    """
    开发用：为指定订阅立即生成一张WiW卡片（stream|journals）。
    - stream：先补充模块1候选池，再随机选1篇生成
    - journals：实时从模块2查询候选，并随机选1篇生成
    """
    _ensure_dev_env()

    # 读取订阅
    stmt = select(PoolSubscription).where(PoolSubscription.id == subscription_id)
    result = await db.execute(stmt)
    subscription = result.scalar_one_or_none()
    if not subscription:
        raise HTTPException(status_code=404, detail="subscription_not_found")

    pool_service = PoolService(db)
    wiw_service = WiWService(db)

    if pmid:
        chosen_pmid = pmid
    elif track == "stream":
        # 补充候选池（最多50篇）
        await pool_service.search_and_add_stream_articles(subscription, limit=50)
        # 随机取一篇
        candidates = await pool_service.get_random_stream_articles(subscription_id, count=1)
        if not candidates:
            raise HTTPException(status_code=400, detail="no_stream_candidates")
        chosen_pmid = candidates[0].pmid
    else:
        # journals：实时查询候选并解析PMID（优先用DOI→PMID）
        from modules.journals.services.pubmed_enricher import PubMedEnricher
        candidates = await pool_service.get_candidate_articles_journals(subscription, limit=50)
        if not candidates:
            raise HTTPException(status_code=400, detail="no_journals_candidates")
        enricher = PubMedEnricher(db)
        chosen_pmid = None
        for art in candidates:
            if art.pmid:
                chosen_pmid = art.pmid
                break
            if art.doi:
                pmid_try = await enricher.find_pmid_by_doi(art.doi)
                if pmid_try:
                    chosen_pmid = pmid_try
                    break
        if not chosen_pmid:
            raise HTTPException(status_code=400, detail="pmid_resolution_failed")

    if not chosen_pmid:
        raise HTTPException(status_code=400, detail="pmid_missing")

    wiw_card = await wiw_service.generate_or_reuse_wiw(
        pmid=chosen_pmid,
        subscription_id=subscription_id,
        track=track,
    )

    return {"status": "ok", "wiw_card_id": wiw_card.id, "track": track, "pmid": chosen_pmid}


