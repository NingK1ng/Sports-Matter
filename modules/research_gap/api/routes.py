"""
研究空白Agent API路由

提供WiW生成、相关文献查询、顶刊推荐等接口
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field, validator, model_validator
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

import hashlib

from core.database import get_db
from modules.research_gap.services.wiw_generator import WiWGenerator
from modules.research_gap.models.wiw import WiWResult
from core.external.pubmed import get_pubmed_client
from modules.literature_pool.api.auth import require_weekly_quota


router = APIRouter(prefix="/wiw", tags=["研究空白"])


# ========== 请求体模型 ==========

class WiWGenerateRequest(BaseModel):
    """WiW生成请求"""
    pmid: Optional[str] = Field(None, description="输入文献PMID（8位数字）")
    doi: Optional[str] = Field(None, description="输入文献DOI（10.前缀）")
    title: Optional[str] = Field(None, description="输入文献标题")
    
    top_k: int = Field(10, description="召回文献数量（仅允许5/10/15）")
    language: str = Field("zh", description="输出语言（zh/en）")
    enable_inspiration: bool = Field(True, description="是否启用顶刊推荐（已废弃，强制开启，返回1-3篇）")
    strategy_version: str = Field("v1", description="召回策略版本")
    template_version: str = Field("v1", description="Prompt模板版本")
    
    @validator("top_k")
    def validate_top_k(cls, v):
        if v not in [5, 10, 15]:
            raise ValueError("INVALID_TOPK: topK仅允许5/10/15")
        return v
    
    @validator("pmid")
    def validate_pmid_format(cls, v):
        if v:
            if not v.isdigit():
                raise ValueError("INVALID_PMID_FORMAT: PMID必须为纯数字")
            if len(v) < 6 or len(v) > 9:
                raise ValueError("INVALID_PMID_FORMAT: PMID长度必须为6-9位数字")
        return v
    
    @validator("doi")
    def validate_doi_format(cls, v):
        if v and not v.startswith("10."):
            raise ValueError("INVALID_DOI_FORMAT: DOI必须包含10.前缀")
        return v
    
    @model_validator(mode='after')
    def validate_input(self):
        """验证至少提供一个输入（在所有字段解析完成后执行）"""
        if not any([self.pmid, self.doi, self.title]):
            raise ValueError("INVALID_INPUT_TYPE: 必须提供pmid、doi或title之一")
        
        return self


# ========== API端点 ==========

@router.post("/generate", summary="生成WiW分析")
async def generate_wiw(
    request: WiWGenerateRequest,
    session: AsyncSession = Depends(get_db),
    _user=Depends(require_weekly_quota("wiw_generate", 3)),
):
    """
    生成WiW（What is What）研究空白分析
    
    支持三种输入方式：
    1. PMID输入：直接召回相似文献
    2. DOI输入：先通过PubMed搜索定位PMID，再召回
    3. 标题输入：通过PubMed标题搜索定位PMID，再召回
    
    返回：
    - card: {focus, next_questions, conflicts, gaps}
    - references: 召回的相关文献列表
    - top_journal_recommendations: 顶刊推荐（来自模块2，强制返回2-8篇，不与输入文献重复）
    - meta: 元数据（recall_mode, dedup_count, elapsed_ms等）
    """
    try:
        # 1. 输入归一化：将DOI/标题转换为PMID
        pmid = await _resolve_input_to_pmid(request)
        
        # 2. 生成WiW
        generator = WiWGenerator()
        result = await generator.generate_wiw(
            pmid=pmid,
            top_k=request.top_k,
            language=request.language,
            enable_inspiration=request.enable_inspiration
        )
        
        # 3. 保存到数据库
        await _save_wiw_result(
            session,
            pmid=pmid,
            doi=request.doi,
            title=request.title,
            top_k=request.top_k,
            strategy_version=request.strategy_version,
            template_version=request.template_version,
            language=request.language,
            result=result
        )
        
        return {
            "card": result["card"],
            "references": result["references"],
            "top_journal_recommendations": result["top_journal_recommendations"],
            "meta": result["meta"]
        }
        
    except ValueError as e:
        error_msg = str(e)
        if "PMID_NOT_FOUND" in error_msg:
            raise HTTPException(status_code=404, detail={"code": "PMID_NOT_FOUND", "message": error_msg})
        elif "DOI_RESOLUTION_FAILED" in error_msg:
            raise HTTPException(status_code=404, detail={"code": "DOI_RESOLUTION_FAILED", "message": error_msg})
        elif "TITLE_NOT_FOUND" in error_msg:
            raise HTTPException(status_code=404, detail={"code": "TITLE_NOT_FOUND", "message": error_msg})
        elif "TITLE_MULTIPLE_MATCHES" in error_msg:
            raise HTTPException(status_code=400, detail={"code": "TITLE_MULTIPLE_MATCHES", "message": error_msg})
        elif "LOW_RECALL" in error_msg:
            raise HTTPException(status_code=502, detail={"code": "LOW_RECALL", "message": error_msg})
        elif "CONTEXT_OVERFLOW" in error_msg:
            raise HTTPException(status_code=500, detail={"code": "CONTEXT_OVERFLOW", "message": error_msg})
        elif "LLM_TIMEOUT" in error_msg:
            raise HTTPException(status_code=503, detail={"code": "LLM_TIMEOUT", "message": error_msg})
        elif "LLM_GENERATION_FAILED" in error_msg:
            raise HTTPException(status_code=500, detail={"code": "LLM_GENERATION_FAILED", "message": error_msg})
        elif "INVALID_" in error_msg:
            raise HTTPException(status_code=400, detail={"code": "INVALID_INPUT", "message": error_msg})
        else:
            raise HTTPException(status_code=500, detail={"code": "INTERNAL_ERROR", "message": error_msg})
    
    except Exception as e:
        print(f"❌ WiW生成失败: {e}")
        raise HTTPException(status_code=500, detail={"code": "INTERNAL_ERROR", "message": str(e)})


@router.get("/related", summary="获取相关文献列表")
async def get_related_literature(
    pmid: str,
    top_k: int = 10
):
    """
    获取指定PMID的相关文献列表（仅返回文献列表，不生成WiW）
    
    Args:
        pmid: 输入文献PMID
        top_k: 返回文献数量（默认10）
    
    Returns:
        List of {pmid, title, doi, abstract}
    """
    try:
        if top_k not in [5, 10, 15]:
            raise HTTPException(status_code=400, detail={"code": "INVALID_TOPK", "message": "topK仅允许5/10/15"})
        
        pubmed_client = get_pubmed_client()
        
        # 召回相似文献
        related_pmids = await pubmed_client.elink(pmid, retmax=50)
        
        if len(related_pmids) < 5:
            raise HTTPException(
                status_code=502,
                detail={"code": "LOW_RECALL", "message": f"相似文献不足（仅{len(related_pmids)}篇）"}
            )
        
        # 去重并截取topK
        seen = {pmid}
        unique_pmids = [p for p in related_pmids if p not in seen and not seen.add(p)]
        selected_pmids = unique_pmids[:top_k]
        
        # 获取详情
        summaries = await pubmed_client.fetch_summary(selected_pmids)
        summary_map = {s["pmid"]: s for s in summaries}
        
        # 批量获取摘要
        import asyncio
        tasks = [pubmed_client.fetch_abstract(p) for p in selected_pmids]
        abstracts = await asyncio.gather(*tasks, return_exceptions=True)
        
        results = []
        for idx, pid in enumerate(selected_pmids):
            if pid in summary_map:
                abstract = abstracts[idx] if not isinstance(abstracts[idx], Exception) else ""
                results.append({
                    "pmid": pid,
                    "title": summary_map[pid].get("title", ""),
                    "doi": summary_map[pid].get("doi", ""),
                    "abstract": abstract or ""
                })
        
        return results
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ 获取相关文献失败: {e}")
        raise HTTPException(status_code=500, detail={"code": "INTERNAL_ERROR", "message": str(e)})


@router.get("/inspiration", summary="获取顶刊推荐")
async def get_inspiration(
    pmid: str,
    limit: int = 5
):
    """
    获取顶刊推荐（来自模块2的13本期刊）
    
    Args:
        pmid: 输入文献PMID
        limit: 返回数量（默认5篇）
    
    Returns:
        List of {title, journal, doi, pmid}
    """
    try:
        # 暂未实现，返回空列表
        print(f"⚠️  顶刊推荐功能需要集成模块2的search_service")
        return []
        
    except Exception as e:
        print(f"❌ 获取顶刊推荐失败: {e}")
        raise HTTPException(status_code=503, detail={"code": "INSPIRATION_FAILED", "message": str(e)})


# ========== 辅助函数 ==========

async def _resolve_input_to_pmid(request: WiWGenerateRequest) -> str:
    """
    将输入（PMID/DOI/标题）归一化为PMID
    
    Returns:
        str: PMID
    
    Raises:
        ValueError: 无法解析输入
    """
    import time
    
    # 优先使用PMID
    if request.pmid:
        print(f"✅ 直接使用PMID: {request.pmid}")
        return request.pmid
    
    pubmed_client = get_pubmed_client()
    
    # DOI输入
    if request.doi:
        print(f"\n{'='*60}")
        print(f"🔍 开始DOI解析: {request.doi}")
        print(f"⏱️  时间: {time.strftime('%H:%M:%S')}")
        print(f"{'='*60}")
        
        # 路径1：esearch term="<doi>[DOI]"
        print(f"\n🔍 路径1: 使用[DOI]字段搜索...")
        try:
            start = time.time()
            pmids = await pubmed_client.search(f'"{request.doi}"[DOI]', retmax=1)
            elapsed = time.time() - start
            print(f"   耗时: {elapsed:.1f}s")
            
            if pmids:
                print(f"✅ DOI解析成功: {request.doi} → PMID {pmids[0]}")
                print(f"{'='*60}\n")
                return pmids[0]
            else:
                print(f"⚠️  未找到匹配结果")
        except Exception as e:
            print(f"❌ DOI搜索失败（路径1）: {e}")
        
        # 路径2：esearch term="<doi>[AID]"
        print(f"\n🔍 路径2: 使用[AID]字段搜索...")
        try:
            start = time.time()
            pmids = await pubmed_client.search(f'"{request.doi}"[AID]', retmax=1)
            elapsed = time.time() - start
            print(f"   耗时: {elapsed:.1f}s")
            
            if pmids:
                print(f"✅ DOI解析成功（AID）: {request.doi} → PMID {pmids[0]}")
                print(f"{'='*60}\n")
                return pmids[0]
            else:
                print(f"⚠️  未找到匹配结果")
        except Exception as e:
            print(f"❌ DOI搜索失败（路径2）: {e}")
        
        # 所有路径都失败
        print(f"\n❌ DOI解析失败: {request.doi}")
        print(f"💡 可能原因:")
        print(f"   1. DOI格式错误")
        print(f"   2. 文献未被PubMed收录")
        print(f"   3. PubMed数据库延迟")
        print(f"{'='*60}\n")
        raise ValueError(f"DOI_RESOLUTION_FAILED: 无法定位DOI {request.doi}对应的PMID")
    
    # 标题输入
    if request.title:
        try:
            pmids = await pubmed_client.search(f'"{request.title}"[Title]', retmax=5)
            
            if not pmids:
                raise ValueError(f"TITLE_NOT_FOUND: 未找到匹配文献，请检查标题或使用PMID/DOI")
            
            if len(pmids) == 1:
                print(f"✅ 标题解析成功: {request.title[:50]}... → PMID {pmids[0]}")
                return pmids[0]
            
            # 多个匹配：返回候选列表供用户选择
            summaries = await pubmed_client.fetch_summary(pmids)
            candidates = [{"pmid": s["pmid"], "title": s.get("title", "")} for s in summaries]
            raise ValueError(f"TITLE_MULTIPLE_MATCHES: 找到{len(pmids)}个匹配结果，请使用PMID精确指定")
            
        except ValueError:
            raise
        except Exception as e:
            print(f"⚠️  标题搜索失败: {e}")
            raise ValueError(f"TITLE_NOT_FOUND: 标题搜索失败")
    
    raise ValueError("INVALID_INPUT_TYPE: 必须提供pmid、doi或title之一")


async def _save_wiw_result(
    session: AsyncSession,
    pmid: str,
    doi: Optional[str],
    title: Optional[str],
    top_k: int,
    strategy_version: str,
    template_version: str,
    language: str,
    result: Dict[str, Any]
):
    """保存WiW结果到数据库"""
    try:
        # 生成输入指纹
        input_str = f"{pmid}:{top_k}:{strategy_version}:{template_version}"
        input_fingerprint = hashlib.md5(input_str.encode()).hexdigest()
        
        # 生成召回集哈希
        refs_str = ",".join([r["pmid"] for r in result["references"]])
        refs_hash = hashlib.md5(refs_str.encode()).hexdigest()
        
        # 创建记录
        wiw_record = WiWResult(
            input_pmid=pmid,
            input_doi=doi,
            input_title=title,
            input_fingerprint=input_fingerprint,
            top_k=top_k,
            strategy_version=strategy_version,
            template_version=template_version,
            model_version=result["meta"]["model_version"],
            language=language,
            card_content=result["card"],
            references=result["references"],
            references_hash=refs_hash,
            top_journal_recommendations=result["top_journal_recommendations"],
            meta=result["meta"]
        )
        
        session.add(wiw_record)
        await session.commit()
        
        print(f"✅ WiW结果已保存到数据库 (PMID: {pmid})")
        
    except Exception as e:
        print(f"⚠️  保存WiW结果失败: {e}")
        await session.rollback()
