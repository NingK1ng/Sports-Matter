"""
翻译API路由

提供批量翻译接口，使用DeepSeek-Chat进行学术文献标题翻译
"""
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.services.batch_translator import BatchTranslator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/translate", tags=["翻译"])


# ==========================================
# 请求/响应模型
# ==========================================
class TranslateTitlesRequest(BaseModel):
    """批量翻译请求"""
    pmids: Optional[List[str]] = Field(None, description="文献PMID列表（用于literature表）")
    article_ids: Optional[List[int]] = Field(None, description="文章ID列表（用于journal_articles表）")

    class Config:
        json_schema_extra = {
            "example": {
                "pmids": ["39530145", "39530146"]
            }
        }


class TranslateTitlesResponse(BaseModel):
    """批量翻译响应"""
    translations: dict = Field(..., description="翻译结果映射 {pmid/id: title_zh}")
    count: int = Field(..., description="成功翻译的数量")
    cached: int = Field(0, description="缓存命中数量")
    newly_translated: int = Field(0, description="新翻译数量")

    class Config:
        json_schema_extra = {
            "example": {
                "translations": {
                    "39530145": "前交叉韧带重建术后心率变异性的变化",
                    "39530146": "运动干预对老年人认知功能的影响"
                },
                "count": 2,
                "cached": 1,
                "newly_translated": 1
            }
        }


class TranslateAbstractRequest(BaseModel):
    """单个摘要翻译请求"""
    identifier: str = Field(..., description="PMID（literature）或 article_id（journal）")
    abstract: str = Field(..., description="英文摘要")
    source_type: str = Field("literature", description="来源类型：literature 或 journal")

    class Config:
        json_schema_extra = {
            "example": {
                "identifier": "39530145",
                "abstract": "Background: Heart rate variability (HRV) is...",
                "source_type": "literature"
            }
        }


class TranslateAbstractResponse(BaseModel):
    """单个摘要翻译响应"""
    abstract_zh: str = Field(..., description="中文摘要")
    cached: bool = Field(False, description="是否为缓存结果")

    class Config:
        json_schema_extra = {
            "example": {
                "abstract_zh": "背景：心率变异性（HRV）是...",
                "cached": False
            }
        }


# ==========================================
# API端点
# ==========================================
@router.post("/titles", response_model=TranslateTitlesResponse)
async def translate_titles(
    request: TranslateTitlesRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    批量翻译文献标题（使用DeepSeek-Chat）

    - 优先返回数据库缓存
    - 仅对未翻译的标题调用LLM
    - 支持literature表（pmids）和journal_articles表（article_ids）
    - 批量大小限制：50个

    **成本**：每20个标题约 ¥0.006（使用DeepSeek-Chat）
    """
    # 验证输入
    if not request.pmids and not request.article_ids:
        raise HTTPException(
            status_code=400,
            detail="必须提供 pmids 或 article_ids 参数"
        )

    if request.pmids and request.article_ids:
        raise HTTPException(
            status_code=400,
            detail="不能同时提供 pmids 和 article_ids 参数"
        )

    try:
        translator = BatchTranslator()
    except ValueError as e:
        logger.error(f"BatchTranslator初始化失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"翻译服务初始化失败: {str(e)}"
        )

    # 处理文献表翻译
    if request.pmids:
        pmids = request.pmids[:50]  # 限制批量大小

        # 查询已缓存的翻译数量
        from sqlalchemy import select, func
        from modules.literature_stream.models.literature import Literature

        cached_query = select(func.count()).where(
            Literature.pmid.in_(pmids),
            Literature.title_zh.is_not(None)
        )
        cached_result = await db.execute(cached_query)
        cached_count = cached_result.scalar() or 0

        # 执行翻译（自动跳过已缓存）
        try:
            translations = await translator.translate_titles_for_literature(pmids, db)
        except Exception as e:
            logger.error(f"文献翻译失败: {e!r}")
            raise HTTPException(
                status_code=500,
                detail=f"翻译失败: {str(e)}"
            )

        newly_translated = len(translations)

        # 返回所有翻译（包括缓存的）
        all_query = select(Literature.pmid, Literature.title_zh).where(
            Literature.pmid.in_(pmids),
            Literature.title_zh.is_not(None)
        )
        all_result = await db.execute(all_query)
        all_translations = {row.pmid: row.title_zh for row in all_result}

        return TranslateTitlesResponse(
            translations=all_translations,
            count=len(all_translations),
            cached=cached_count,
            newly_translated=newly_translated
        )

    # 处理期刊文章表翻译
    elif request.article_ids:
        article_ids = request.article_ids[:50]  # 限制批量大小

        # 查询已缓存的翻译数量
        from sqlalchemy import select, func
        from modules.journals.models.journal import JournalArticle

        cached_query = select(func.count()).where(
            JournalArticle.id.in_(article_ids),
            JournalArticle.title_zh.is_not(None)
        )
        cached_result = await db.execute(cached_query)
        cached_count = cached_result.scalar() or 0

        # 执行翻译（自动跳过已缓存）
        try:
            translations = await translator.translate_titles_for_journals(article_ids, db)
        except Exception as e:
            logger.error(f"期刊文章翻译失败: {e!r}")
            raise HTTPException(
                status_code=500,
                detail=f"翻译失败: {str(e)}"
            )

        newly_translated = len(translations)

        # 返回所有翻译（包括缓存的）
        all_query = select(JournalArticle.id, JournalArticle.title_zh).where(
            JournalArticle.id.in_(article_ids),
            JournalArticle.title_zh.is_not(None)
        )
        all_result = await db.execute(all_query)
        all_translations = {row.id: row.title_zh for row in all_result}

        return TranslateTitlesResponse(
            translations=all_translations,
            count=len(all_translations),
            cached=cached_count,
            newly_translated=newly_translated
        )


@router.post("/abstract", response_model=TranslateAbstractResponse)
async def translate_abstract(
    request: TranslateAbstractRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    翻译单个文献摘要（使用DeepSeek-Chat，按需翻译）

    - 优先返回数据库缓存
    - 缓存未命中时调用LLM翻译并存入数据库
    - 支持literature表和journal_articles表
    - 用于用户点击"翻译摘要"按钮时的按需翻译

    **成本**：每个摘要约 ¥0.01-0.02（使用DeepSeek-Chat）
    """
    # 验证输入
    if not request.abstract or not request.abstract.strip():
        raise HTTPException(
            status_code=400,
            detail="摘要内容不能为空"
        )

    if request.source_type not in ["literature", "journal"]:
        raise HTTPException(
            status_code=400,
            detail="source_type 必须是 'literature' 或 'journal'"
        )

    try:
        translator = BatchTranslator()
    except ValueError as e:
        logger.error(f"BatchTranslator初始化失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"翻译服务初始化失败: {str(e)}"
        )

    # 检查是否已有缓存
    cached = False
    if request.source_type == "literature":
        from sqlalchemy import select
        from modules.literature_stream.models.literature import Literature

        cache_query = select(Literature.abstract_zh).where(
            Literature.pmid == request.identifier,
            Literature.abstract_zh.is_not(None)
        )
        cache_result = await db.execute(cache_query)
        cached_translation = cache_result.scalar_one_or_none()

        if cached_translation:
            cached = True
            return TranslateAbstractResponse(
                abstract_zh=cached_translation,
                cached=True
            )
    else:  # journal
        from sqlalchemy import select
        from modules.journals.models.journal import JournalArticle

        try:
            article_id = int(request.identifier)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid article_id: {request.identifier}"
            )

        cache_query = select(JournalArticle.abstract_zh).where(
            JournalArticle.id == article_id,
            JournalArticle.abstract_zh.is_not(None)
        )
        cache_result = await db.execute(cache_query)
        cached_translation = cache_result.scalar_one_or_none()

        if cached_translation:
            cached = True
            return TranslateAbstractResponse(
                abstract_zh=cached_translation,
                cached=True
            )

    # 执行翻译并缓存
    try:
        abstract_zh = await translator.translate_abstract(
            identifier=request.identifier,
            abstract=request.abstract,
            db=db,
            source_type=request.source_type
        )
    except ValueError as e:
        logger.error(f"摘要翻译失败: {e}")
        raise HTTPException(
            status_code=404,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"摘要翻译失败: {e!r}")
        raise HTTPException(
            status_code=500,
            detail=f"翻译失败: {str(e)}"
        )

    return TranslateAbstractResponse(
        abstract_zh=abstract_zh,
        cached=False
    )


@router.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "module": "translate"}
