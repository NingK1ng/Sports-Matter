"""
Assistant API Routes
任务4: API路由与SSE流式输出
"""
import asyncio
import time
import json
import logging
import uuid
import re
from dataclasses import asdict
from pathlib import Path
from datetime import datetime
from typing import AsyncGenerator, Dict, Any, List, Awaitable, Callable, Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.external.deepseek import DEEPSEEK_V4_FLASH_MODEL, get_deepseek_client, DeepSeekClient
from core.config import settings
from core.cache import cache_get, cache_set
from modules.assistant.api.schemas import (
    AssistantChatRequest,
    AssistantChatResponse,
    Citation,
    ExportNbibRequest
)
from modules.assistant.services.local_search import LocalSearchService
from modules.assistant.services.citation_validator import CitationValidator
from modules.assistant.services.query_translator import QueryTranslator  # ✅ 恢复：中文用户必须翻译
# from modules.assistant.services.reranker import DeepSeekReranker  # ❌ 保持移除（Out of Scope）
from modules.assistant.prompts.citation_prompt import (
    build_citation_prompt,
    build_json_fallback_prompt
)
from modules.assistant.models.query_log import AssistantQueryLog
from modules.assistant.tools.pubmed_toolkit import PubMedToolkit
from core.external.pubmed import PubMedClient
from modules.assistant.api.routes_streaming import generate_streaming_response
from modules.literature_pool.api.auth import get_current_user, is_member_user, require_weekly_quota
from modules.literature_pool.models.user import User as PoolUser
from modules.literature_pool.services.usage_limit_service import UsageLimitService

logger = logging.getLogger(__name__)

JSON_SYSTEM_PROMPT = (
    "You must always respond with a valid JSON object that satisfies the user's schema. "
    "Do not return an empty string. If evidence is limited you must still output a full JSON object "
    "and include a sentence that states the limitation with an appropriate citation. "
    "Never include markdown or plain text outside the JSON object."
)

LLM_LOG_ENABLED = settings.assistant_log_llm
LLM_LOG_PATH = Path("/tmp/deepseek_chat.log")


def log_llm_event(event: str, payload: Dict[str, Any]) -> None:
    if not LLM_LOG_ENABLED:
        return
    try:
        entry = {
            "ts": datetime.utcnow().isoformat(),
            "event": event,
            **payload,
        }
        LLM_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LLM_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as log_err:
        logger.warning(f"LLM log failed: {log_err}")


def _parse_json_sentences(
    payload: Dict[str, Any],
    max_reference_idx: int,
    *,
    min_sentences: int = 4,
    max_sentences: int = 8,
) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ValueError("JSON结构必须为对象")
    sentences_raw = payload.get("sentences")
    if not isinstance(sentences_raw, list):
        raise ValueError("JSON缺少有效的sentences数组")

    results: List[Dict[str, Any]] = []
    for item in sentences_raw:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text:
            continue

        citations_field = item.get("citations")
        if citations_field is None:
            citations_field = item.get("citation_ids")

        citation_list: list[int] = []
        if isinstance(citations_field, (list, tuple)):
            for cite in citations_field:
                try:
                    citation_list.append(int(cite))
                except (TypeError, ValueError):
                    continue
        elif citations_field is not None:
            try:
                citation_list.append(int(citations_field))
            except (TypeError, ValueError):
                citation_list = []

        valid_ids = [cid for cid in citation_list if 1 <= cid <= max_reference_idx]
        if not valid_ids:
            raise ValueError("句子缺少有效引用")

        results.append({"text": text, "citations": sorted(set(valid_ids))})

    if not results:
        raise ValueError("未解析到有效句子")

    if len(results) < min_sentences:
        raise ValueError(f"句子数量不足: {len(results)}")

    if len(results) > max_sentences:
        results = results[:max_sentences]

    return results


def _align_text_output(
    raw_text: str,
    max_reference_idx: int,
    *,
    max_sentences: int = 8,
) -> List[Dict[str, Any]]:
    if not raw_text:
        return []

    normalised = re.sub(r"[ \t]+", " ", raw_text.strip())
    normalised = re.sub(r"\s*\n\s*", " ", normalised)
    normalised = re.sub(r"(?m)(^|\s)[\u2022\-•‣▪▫●○\d]+\.\s*", " ", normalised)

    raw_sentences = re.split(r"(?<=[。．.!！？?])\s+", normalised)
    sentences: List[Dict[str, Any]] = []
    citation_pattern = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")

    for raw_sentence in raw_sentences:
        sentence = raw_sentence.strip()
        if not sentence:
            continue

        matches = citation_pattern.findall(sentence)
        if not matches:
            continue

        citation_ids: List[int] = []
        for group in matches:
            parts = [part.strip() for part in group.split(",")]
            for part in parts:
                if not part:
                    continue
                try:
                    cid = int(part)
                except ValueError:
                    continue
                if 1 <= cid <= max_reference_idx:
                    citation_ids.append(cid)

        if not citation_ids:
            continue

        text_without_citations = citation_pattern.sub("", sentence).strip()
        if not text_without_citations:
            continue

        sentences.append(
            {
                "text": text_without_citations,
                "citations": sorted(set(citation_ids)),
            }
        )

        if len(sentences) >= max_sentences:
            break

    return sentences


def _infer_study_type(title: str) -> str:
    lower = (title or "").lower()
    if "meta-analysis" in lower and "systematic review" in lower:
        return "系统综述与荟萃分析"
    if "systematic review" in lower:
        return "系统综述"
    if "scoping review" in lower:
        return "综述"
    if "randomized" in lower or "randomised" in lower or "trial" in lower:
        return "随机对照研究"
    if "case report" in lower or "case-series" in lower:
        return "病例报告"
    if "guideline" in lower or "consensus" in lower:
        return "指南"
    return "研究"


def _extract_numeric_fact(text: str) -> str | None:
    if not text:
        return None
    patterns = [
        r"(\d+(?:\.\d+)?\s*[%％])",
        r"(\d+(?:\.\d+)?\s*(?:名|例|人|例患者|studies|patients|participants|subjects))",
        r"(\d+(?:\.\d+)?\s*(?:年|years|月|months|周|weeks|天|days))",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _extract_sentence_with_numeric(text: str) -> str | None:
    if not text:
        return None
    fragments = re.split(r"(?<=[。\.！？!？])\s+", text.strip())
    for fragment in fragments:
        fragment = fragment.strip()
        if not fragment:
            continue
        if re.search(r"\d", fragment):
            return fragment
    return None


def _build_metadata_sentences(
    candidates: List[Any],
    *,
    max_sentences: int = 4,
) -> List[Dict[str, Any]]:
    base_candidates = candidates[:max_sentences]
    if not base_candidates:
        return []

    sentences: List[Dict[str, Any]] = []
    missing_info_used = False
    for idx, cand in enumerate(base_candidates, start=1):
        year = f"{getattr(cand, 'publication_year', None)}年" if getattr(cand, "publication_year", None) else "近年"
        journal = getattr(cand, "journal_name", None) or "未注明期刊"
        study_type = _infer_study_type(getattr(cand, "title", ""))
        abstract = getattr(cand, "abstract", None)
        abstract_sentence = _extract_sentence_with_numeric(abstract)
        numeric = _extract_numeric_fact(abstract)

        logger.debug(
            "Metadata fallback candidate pmid=%s title=%s sentence=%s numeric=%s",
            getattr(cand, "pmid", ""),
            (getattr(cand, "title", "")[:60] if getattr(cand, "title", "") else ""),
            (abstract_sentence[:60] + "…") if abstract_sentence and len(abstract_sentence) > 60 else abstract_sentence,
            numeric,
        )

        if abstract_sentence:
            fact_clause = f"报道：{abstract_sentence}"
        elif numeric:
            fact_clause = f"报告{numeric}等数据，提供量化证据。"
        elif not missing_info_used:
            fact_clause = "指出提供的研究未给出具体量化数据，需要继续验证。"
            missing_info_used = True
        else:
            fact_clause = "概述关键要点但仍缺乏明确的量化结果。"

        title = getattr(cand, "title", "") or ""
        title_short = title if len(title) <= 36 else title[:33] + "…"
        text = f"{year}{journal}发表的{study_type}《{title_short}》{fact_clause}"
        if len(text) > 100:
            text = text[:99] + "…"
        sentences.append({"text": text, "citations": [idx]})

    while len(sentences) < max_sentences and base_candidates:
        sentences.append(
            {
                "text": f"{getattr(base_candidates[0], 'publication_year', None) or '近年'}年文献强调持续梳理证据，但实践仍需更多量化验证。",
                "citations": [1],
            }
        )

    return sentences[:max_sentences]


def _normalise_reasoning(reasoning: Any) -> List[str]:
    if reasoning is None:
        return []

    steps: List[str] = []

    def _collect(text: Any) -> None:
        if not isinstance(text, str):
            text = str(text) if text is not None else ""
        cleaned = text.strip()
        if not cleaned:
            return
        cleaned = re.sub(r"^\s*(?:[-•·‣▪▫●○]+\s*|\d+[\.\)]\s*)", "", cleaned)
        steps.append(cleaned)

    if isinstance(reasoning, str):
        for line in reasoning.replace("\r", "\n").split("\n"):
            _collect(line)
    elif isinstance(reasoning, list):
        for item in reasoning:
            if isinstance(item, dict):
                for key in ("content", "text", "thought", "value", "message"):
                    if isinstance(item.get(key), str):
                        _collect(item[key])
                        break
            else:
                _collect(item)
    elif isinstance(reasoning, dict):
        if "steps" in reasoning:
            return _normalise_reasoning(reasoning["steps"])
        for key in ("content", "text", "thought"):
            if key in reasoning:
                return _normalise_reasoning(reasoning[key])

    return steps


def _sse_payload(data: Dict[str, Any], *, event: str = "message") -> bytes:
    return (
        f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")
    )


router = APIRouter(prefix="/assistant", tags=["AI Assistant"])


async def _chat_logic(
    request: AssistantChatRequest,
    db: AsyncSession = Depends(get_db),
    deepseek: DeepSeekClient = Depends(get_deepseek_client),
    progress_callback: Optional[Callable[[str], Awaitable[None]]] = None,
):
    """
    AI助手聊天（非流式）核心逻辑
    """
    start_time = time.time()
    # reranker = DeepSeekReranker(deepseek)  # ❌ 移除：违反规格Out of Scope
    runtime_steps: List[str] = []

    async def _record_step(step: str) -> None:
        runtime_steps.append(step)
        if progress_callback:
            try:
                await progress_callback(step)
                # 强制让出控制权，让 generate() 能立即 yield
                await asyncio.sleep(0)
            except Exception:  # pylint: disable=broad-except
                logger.debug("Progress callback failed", exc_info=True)

    def _unwrap_response(raw: Any) -> tuple[str, List[str]]:
        if isinstance(raw, dict):
            content = raw.get("content") or ""
            reasoning = _normalise_reasoning(raw.get("reasoning"))
            return str(content), reasoning
        if raw is None:
            return "", []
        return str(raw), []
    try:
        # 1. 检索候选文献（本地 or Agent）
        search_start = time.time()
        
        if request.use_agent:
            # Agent模式：在线PubMed全库检索
            # sports_gate=false时使用原生查询，不限领域
            # sports_gate=true时才加运动科学限定
            logger.info(f"Using Agent mode: sports_gate={request.sports_gate}, query='{request.query}'")
            pubmed_toolkit = PubMedToolkit(PubMedClient())
            candidates = await pubmed_toolkit.run_agent_pipeline(
                query=request.query,  # 直接使用用户原始查询
                sports_gate=request.sports_gate,
                top_k=request.top_k,
                timeout=30  # 30秒超时保护
            )
            plan_result = getattr(pubmed_toolkit, "last_plan", None)
            if plan_result:
                try:
                    log_llm_event(
                        "planner_plan",
                        {
                            "query": request.query,
                            "sports_gate": request.sports_gate,
                            "plan": asdict(plan_result),
                        },
                    )
                except Exception:  # pylint: disable=broad-except
                    logger.debug("Planner logging failed", exc_info=True)
            await _record_step(
                f"在线模式（PubMed）召回文献 {len(candidates)} 篇"
            )
        else:
            # 本地模式：查询模块1+2数据库（包含运动科学+CNS综合顶刊）
            logger.info(f"Using local search mode, query='{request.query}'")
            
            # ✅ 智能翻译：仅对中文查询翻译为英文关键词
            # 数据库是英文文献，中文查询必须翻译
            import re
            has_chinese = bool(re.search(r'[\u4e00-\u9fff]', request.query))
            
            if has_chinese:
                translator = QueryTranslator(deepseek)
                search_query = await translator.translate_query(request.query)
                logger.info(f"中文查询已翻译: '{request.query}' -> '{search_query}'")
                await _record_step(f"翻译查询：{search_query}")
            else:
                search_query = request.query
                logger.info(f"英文查询直接使用: '{search_query}'")
                await _record_step(f"检索文献中...")
            
            local_search = LocalSearchService(db)
            candidates = await local_search.search(
                query=search_query,
                top_k=request.top_k,
                search_scope="tiab",
                source=request.local_source,
            )
            source_label = {
                "stream": "文献上新",
                "journals": "顶刊追踪",
                "both": "文献上新及顶刊追踪",
            }.get(request.local_source, request.local_source)
            await _record_step(f"本地检索（{source_label}）命中文献 {len(candidates)} 篇")
        
        search_duration_ms = int((time.time() - search_start) * 1000)
        
        if not candidates:
            # 根据检索模式给出智能提示（不再提示 Sports Gate）
            if request.use_agent:
                error_msg = "未找到相关文献。建议：1) 简化查询词 2) 使用更通用的关键词 3) 切换到本地模式尝试"
            else:
                error_msg = "本地库未找到相关文献，建议切换到在线模式（PubMed 全库）"
            
            raise HTTPException(
                status_code=404,
                detail={
                    "error_code": "E_NO_RESULTS",
                    "message": error_msg
                }
            )

        # 1.5 ✅ 使用数据库相关性排序（移除LLM重排，节省2-4分钟）
        # PostgreSQL ts_rank已提供相关性排序，无需额外LLM调用
        # try:
        #     reranked = await reranker.rerank(request.query, candidates)
        #     if reranked:
        #         candidates = reranked[: request.top_k]
        # except Exception:  # pylint: disable=broad-except
        #     logger.debug("Rerank failed", exc_info=True)
        
        # ✅ 使用用户设置的top_k，但限制上限为20（避免回答过长）
        max_reference_slots = min(len(candidates), max(4, min(request.top_k, 20)))
        effective_candidates = candidates[:max_reference_slots]
        if not effective_candidates:
            raise HTTPException(status_code=500, detail="缺少可用文献候选")

        max_reference_idx = len(effective_candidates)
        fallback_used = False
        candidate_reasoning: List[str] = []
        final_reasoning: List[str] = []
        await _record_step(
            f"选取前 {max_reference_idx} 篇候选文献用于生成回答"
        )

        # 解析/对齐工具函数复用全局实现

        context_summary = None
        if request.session_id:
            try:
                context_summary = await cache_get(f"assistant:session:summary:{request.session_id}")
            except Exception:
                context_summary = None

        async def _run_json_fallback(reason: str) -> tuple[List[Dict[str, Any]], List[str]]:
            nonlocal fallback_used
            fallback_used = True
            await _record_step("触发JSON回退生成带引用回答")
            fallback_prompt = build_json_fallback_prompt(request.query, effective_candidates, request.lang)
            fallback_messages = [
                {"role": "system", "content": JSON_SYSTEM_PROMPT},
                {"role": "user", "content": fallback_prompt},
            ]
            fallback_id = f"{llm_request_id}-fallback"
            log_llm_event(
                "deepseek_request",
                {
                    "id": fallback_id,
                    "mode": "chat_fallback",
                    "query": request.query,
                    "use_agent": request.use_agent,
                    "sports_gate": request.sports_gate,
                    "top_k": request.top_k,
                    "lang": request.lang,
                    "candidate_pmids": [c.pmid for c in effective_candidates],
                    "prompt": fallback_prompt,
                    "reason": reason,
                },
            )
            try:
                # JSON Fallback 使用 v4-flash 非思考模式，避免JSON mode空content
                fallback_raw = await deepseek.chat(
                    messages=fallback_messages,
                    model=DEEPSEEK_V4_FLASH_MODEL,
                    temperature=0.2,
                    max_tokens=1024,
                    response_format={"type": "json_object"},
                    return_message=False,
                )
            except Exception as fallback_exc:  # pylint: disable=broad-except
                log_llm_event(
                    "deepseek_error",
                    {
                        "id": fallback_id,
                        "mode": "chat_fallback",
                        "error": str(fallback_exc),
                    },
                )
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error_code": "E_CITATION_ALIGN",
                        "message": "LLM在回退阶段仍未生成带引用的答案",
                        "errors": [f"fallback_llm_error: {fallback_exc}", f"primary_reason: {reason}"],
                    },
                ) from fallback_exc

            # chat 模型返回字符串
            fallback_text = fallback_raw if isinstance(fallback_raw, str) else str(fallback_raw or "")
            fallback_reasoning = []
            if not fallback_text or not fallback_text.strip():
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error_code": "E_CITATION_ALIGN",
                        "message": "LLM回退输出为空",
                        "errors": [f"primary_reason: {reason}"],
                    },
                )

            log_llm_event(
                "deepseek_response",
                {
                    "id": fallback_id,
                    "mode": "chat_fallback",
                    "raw": fallback_text,
                    "reasoning": fallback_reasoning,
                },
            )

            try:
                fallback_json = json.loads(fallback_text)
                sentences = _parse_json_sentences(
                    fallback_json,
                    max_reference_idx=max_reference_idx,
                )
                return sentences, fallback_reasoning
            except Exception as parse_err:  # pylint: disable=broad-except
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error_code": "E_CITATION_ALIGN",
                        "message": "回退输出无法解析或对齐引用",
                        "errors": [str(parse_err), fallback_text[:200]],
                    },
                ) from parse_err

        async def _metadata_fallback_sentences(max_sentences: int = 4) -> List[Dict[str, Any]]:
            nonlocal fallback_used
            fallback_used = True
            await _record_step("采用候选元数据拼装回答草稿")
            base_candidates = effective_candidates if effective_candidates else candidates
            return _build_metadata_sentences(base_candidates, max_sentences=max_sentences)

        # 2. 构建Prompt并生成（Primary阶段）
        prompt = build_citation_prompt(request.query, effective_candidates, request.lang)
        messages = [
            {"role": "system", "content": JSON_SYSTEM_PROMPT},
        ]
        if context_summary:
            messages.append({"role": "system", "content": f"Conversation context summary: {context_summary}"})
        messages.append({"role": "user", "content": prompt})
        llm_request_id = str(uuid.uuid4())
        log_llm_event(
            "deepseek_request",
            {
                "id": llm_request_id,
                "mode": "chat",
                "query": request.query,
                "use_agent": request.use_agent,
                "sports_gate": request.sports_gate,
                "top_k": request.top_k,
                "lang": request.lang,
                "candidate_pmids": [c.pmid for c in effective_candidates],
                "prompt": prompt,
            },
        )

        gen_start = time.time()
        answer_text: str | None = None
        sentences_payload: List[Dict[str, Any]] | None = None
        align_failure_reason: str | None = None

        try:
            await _record_step("调用DeepSeek生成JSON回答")
            # 直接用 v4-flash 非思考模式生成 JSON，避免thinking占用输出导致content为空
            answer_raw = await deepseek.chat(
                messages=messages,
                model=DEEPSEEK_V4_FLASH_MODEL,
                temperature=0.3,
                max_tokens=1024,  # 增加 tokens 以容纳完整 JSON
                response_format={"type": "json_object"},
                return_message=False,  # chat 模型不需要 return_message
            )
            # chat 模型返回字符串,不是 dict
            answer_text = answer_raw if isinstance(answer_raw, str) else str(answer_raw or "")
            candidate_reasoning = []  # chat 模型无 reasoning
            logger.debug(
                "Primary raw output stats | length=%s stripped=%s preview=%s",
                len(answer_text) if answer_text else 0,
                len(answer_text.strip()) if answer_text else 0,
                (answer_text[:200] if answer_text else ""),
            )
        except Exception as primary_exc:
            logger.warning("DeepSeek primary call failed, retrying: %s", primary_exc)
            log_llm_event(
                "deepseek_error",
                {
                    "id": llm_request_id,
                    "mode": "chat",
                    "stage": "primary",
                    "error": str(primary_exc),
                },
            )
            try:
                # Retry 也用 v4-flash 非思考模式
                answer_raw = await deepseek.chat(
                    messages=messages,
                    model=DEEPSEEK_V4_FLASH_MODEL,
                    temperature=0.25,
                    max_tokens=1024,
                    response_format={"type": "json_object"},
                    return_message=False,
                )
                answer_text = answer_raw if isinstance(answer_raw, str) else str(answer_raw or "")
                candidate_reasoning = []
                logger.debug(
                    "Primary retry output stats | length=%s stripped=%s preview=%s",
                    len(answer_text) if answer_text else 0,
                    len(answer_text.strip()) if answer_text else 0,
                    (answer_text[:200] if answer_text else ""),
                )
            except Exception as retry_exc:
                logger.error("DeepSeek retry failed: %s", retry_exc)
                log_llm_event(
                    "deepseek_error",
                    {
                        "id": llm_request_id,
                        "mode": "chat",
                        "stage": "retry",
                        "error": str(retry_exc),
                    },
                )
                align_failure_reason = f"primary_error:{retry_exc}"
        if answer_text:
            log_llm_event(
                "deepseek_response",
                {
                    "id": llm_request_id,
                    "mode": "chat",
                    "raw": answer_text,
                    "reasoning": candidate_reasoning,
                },
            )
            await _record_step("Primary模型返回内容，尝试解析JSON结构")
            parsed_json: Dict[str, Any] | None = None
            try:
                parsed_json = json.loads(answer_text)
            except json.JSONDecodeError:
                parsed_json = None

            if isinstance(parsed_json, dict):
                try:
                    sentences_payload = _parse_json_sentences(
                        parsed_json,
                        max_reference_idx=max_reference_idx,
                    )
                    if sentences_payload:
                        final_reasoning = candidate_reasoning
                        await _record_step("Primary输出通过JSON校验")
                except Exception as json_parse_err:  # pylint: disable=broad-except
                    logger.warning("Primary JSON payload解析失败: %s", json_parse_err)
                    align_failure_reason = f"json_parse:{json_parse_err}"
                    sentences_payload = None

            if sentences_payload is None:
                aligned_sentences = _align_text_output(
                    answer_text,
                    max_reference_idx=max_reference_idx,
                )
                if len(aligned_sentences) < 4:
                    logger.warning("Primary alignment produced %s sentences, raw preview: %s", len(aligned_sentences), answer_text[:400])
                    align_failure_reason = f"align_count_{len(aligned_sentences)}"
                    sentences_payload = None
                else:
                    sentences_payload = aligned_sentences
                    final_reasoning = candidate_reasoning
                    await _record_step("Primary输出通过文本对齐提取引用")
        else:
            logger.warning("Primary generation returned empty content; reason=%s", align_failure_reason)
            align_failure_reason = align_failure_reason or "primary_empty"
            await _record_step("Primary模型返回空内容，准备重试或回退")

        # Reinforce格式要求（若未通过）
        if sentences_payload is None:
            reinforce_prompt = (
                prompt
                + "\n\n请重新输出答案正文，确保至少4个句子，每句结尾使用标准的引用编号格式如[1]或[2, 4]，不得省略或合并编号区间。"
            )
            reinforce_messages = [
                {"role": "system", "content": JSON_SYSTEM_PROMPT},
                {"role": "user", "content": reinforce_prompt},
            ]
            reinforce_id = f"{llm_request_id}-reinforce"
            log_llm_event(
                "deepseek_request",
                {
                    "id": reinforce_id,
                    "mode": "chat_reinforce",
                    "query": request.query,
                    "use_agent": request.use_agent,
                    "sports_gate": request.sports_gate,
                    "top_k": request.top_k,
                    "lang": request.lang,
                    "candidate_pmids": [c.pmid for c in effective_candidates],
                    "prompt": reinforce_prompt,
                    "reason": align_failure_reason,
                },
            )
            try:
                # Reinforce 也用 v4-flash 非思考模式
                answer_raw = await deepseek.chat(
                    messages=reinforce_messages,
                    model=DEEPSEEK_V4_FLASH_MODEL,
                    temperature=0.25,
                    max_tokens=1024,
                    response_format={"type": "json_object"},
                    return_message=False,
                )
                answer_text = answer_raw if isinstance(answer_raw, str) else str(answer_raw or "")
                candidate_reasoning = []
                logger.debug(
                    "Reinforce raw output stats | length=%s stripped=%s preview=%s",
                    len(answer_text) if answer_text else 0,
                    len(answer_text.strip()) if answer_text else 0,
                    (answer_text[:200] if answer_text else ""),
                )
            except Exception as reinforce_exc:  # pylint: disable=broad-except
                logger.error("DeepSeek reinforce call failed: %s", reinforce_exc)
                log_llm_event(
                    "deepseek_error",
                    {
                        "id": reinforce_id,
                        "mode": "chat_reinforce",
                        "error": str(reinforce_exc),
                    },
                )
                align_failure_reason = align_failure_reason or f"reinforce_error:{reinforce_exc}"
            else:
                if answer_text:
                    log_llm_event(
                        "deepseek_response",
                        {
                            "id": reinforce_id,
                            "mode": "chat_reinforce",
                            "raw": answer_text,
                            "reasoning": candidate_reasoning,
                        },
                    )
                    parsed_json = None
                    try:
                        parsed_json = json.loads(answer_text)
                    except json.JSONDecodeError:
                        parsed_json = None

                    if isinstance(parsed_json, dict):
                        try:
                            sentences_payload = _parse_json_sentences(
                                parsed_json,
                                max_reference_idx=max_reference_idx,
                            )
                            if sentences_payload:
                                final_reasoning = candidate_reasoning
                        except Exception as reinforce_parse_err:  # pylint: disable=broad-except
                            logger.warning("Reinforce JSON解析失败: %s", reinforce_parse_err)
                            align_failure_reason = align_failure_reason or f"reinforce_json:{reinforce_parse_err}"
                            sentences_payload = None

                    if sentences_payload is None:
                        aligned_sentences = _align_text_output(
                            answer_text,
                            max_reference_idx=max_reference_idx,
                        )
                        if len(aligned_sentences) < 4:
                            logger.warning("Reinforce alignment produced %s sentences, raw preview: %s", len(aligned_sentences), answer_text[:400])
                            align_failure_reason = align_failure_reason or f"reinforce_align_{len(aligned_sentences)}"
                            sentences_payload = None
                        else:
                            sentences_payload = aligned_sentences
                            final_reasoning = candidate_reasoning
                else:
                    logger.warning("Reinforce generation returned empty content; reason=%s", align_failure_reason)
                    align_failure_reason = align_failure_reason or "reinforce_empty"

        if sentences_payload is None:
            logger.warning(
                "All alignment attempts failed; raw primary text preview: %s",
                (answer_text[:400] if answer_text else "<empty>"),
            )
            logger.info(
                "Triggering JSON fallback | reason=%s fallback_used=%s",
                align_failure_reason,
                fallback_used,
            )
            try:
                sentences_payload, fallback_reasoning = await _run_json_fallback(align_failure_reason or "align_failed")
                if sentences_payload:
                    final_reasoning = fallback_reasoning or final_reasoning
                    await _record_step("回退模型生成带引用回答成功")
            except HTTPException as http_exc:
                detail = http_exc.detail if isinstance(http_exc.detail, dict) else {}
                if detail.get("error_code") == "E_CITATION_ALIGN":
                    logger.warning("Fallback JSON失败，尝试元数据拼装: %s", detail)
                    sentences_payload = await _metadata_fallback_sentences()
                else:
                    raise

        generation_duration_ms = int((time.time() - gen_start) * 1000)

        if not sentences_payload:
            sentences_payload = await _metadata_fallback_sentences()
            if sentences_payload and not final_reasoning:
                final_reasoning = candidate_reasoning
        if not sentences_payload:
            raise HTTPException(
                status_code=422,
                detail={
                    "error_code": "E_CITATION_ALIGN",
                    "message": "未能生成有效的句子与引用",
                },
            )

        assembled_sentences: list[str] = []
        all_citation_ids: List[int] = []
        for entry in sentences_payload:
            text = entry["text"]
            citation_ids = entry["citations"]
            citation_str = "[" + ", ".join(str(c) for c in citation_ids) + "]"
            assembled_sentences.append(f"{text}{citation_str}")
            all_citation_ids.extend(citation_ids)

        answer_text = "\n".join(assembled_sentences)
        unique_citation_ids = sorted(set(all_citation_ids))
        citations = [
            Citation(
                idx=idx,
                pmid=effective_candidates[idx - 1].pmid,
                title=effective_candidates[idx - 1].title,
                url=effective_candidates[idx - 1].url,
                journal_name=effective_candidates[idx - 1].journal_name,
                publication_year=effective_candidates[idx - 1].publication_year,
            )
            for idx in unique_citation_ids
        ]
        logger.info(
            "Assembled %s sentences with %s citations (fallback_used=%s)",
            len(assembled_sentences),
            len(citations),
            fallback_used,
        )
        await _record_step(
            f"最终组合回答 {len(assembled_sentences)} 句，引用 {len(citations)} 篇文献"
        )
        
        if request.session_id:
            try:
                prev = context_summary or ""
                fragments = re.split(r"(?<=[。．.!！？?])\s+", answer_text.strip()) if answer_text else []
                first_sent = fragments[0] if fragments else (answer_text[:200] if answer_text else "")
                new_summary = (prev + " | Q: " + request.query.strip() + " | A: " + first_sent).strip()
                if len(new_summary) > 1000:
                    new_summary = new_summary[-1000:]
                await cache_set(f"assistant:session:summary:{request.session_id}", new_summary, ttl=604800)
            except Exception:
                pass

        # 5. 记录日志
        total_duration_ms = int((time.time() - start_time) * 1000)
        
        log = AssistantQueryLog(
            query=request.query,
            sports_gate=request.sports_gate,
            use_agent=request.use_agent,
            top_k=request.top_k,
            lang=request.lang,
            literature_recall_count=sum(1 for c in candidates if c.source == "literature"),
            journals_recall_count=sum(1 for c in candidates if c.source == "journals"),
            pubmed_agent_count=sum(1 for c in candidates if c.source == "pubmed_agent"),
            pmid_valid_count=len(candidates),
            final_candidate_count=len(candidates),
            search_duration_ms=search_duration_ms,
            generation_duration_ms=generation_duration_ms,
            total_duration_ms=total_duration_ms,
            status="success",
            citation_count=len(citations)
        )
        try:
            db.add(log)
            await db.commit()
        except Exception as log_exc:
            # 日志写入失败不应影响对用户的回答（例如迁移未执行导致表缺失）。
            logger.warning(
                "Failed to persist assistant_query_log: %s", log_exc, exc_info=True
            )
            try:
                await db.rollback()
            except Exception:
                pass
        
        combined_reasoning = runtime_steps.copy()
        if final_reasoning:
            combined_reasoning.extend(final_reasoning)
        elif candidate_reasoning:
            combined_reasoning.extend(candidate_reasoning)

        return AssistantChatResponse(
            answer=answer_text,
            citations=citations,
            recall_stats={
                "literature_count": sum(1 for c in candidates if c.source == "literature"),
                "journals_count": sum(1 for c in candidates if c.source == "journals"),
                "pubmed_agent_count": sum(1 for c in candidates if c.source == "pubmed_agent"),
                "final_count": len(candidates)
            },
            performance={
                "search_duration_ms": search_duration_ms,
                "generation_duration_ms": generation_duration_ms,
                "total_duration_ms": total_duration_ms
            },
            reasoning=combined_reasoning or None,
            stream_token_type="token",
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat", response_model=AssistantChatResponse)
async def chat(
    request: AssistantChatRequest,
    db: AsyncSession = Depends(get_db),
    deepseek: DeepSeekClient = Depends(get_deepseek_client),
    _user=Depends(require_weekly_quota("assistant_chat", 3)),
):
    """
    AI助手聊天（非流式）
    """
    return await _chat_logic(request, db, deepseek)


@router.post("/chat-stream")
async def chat_stream(
    request: AssistantChatRequest,
    db: AsyncSession = Depends(get_db),
    deepseek: DeepSeekClient = Depends(get_deepseek_client),
    _user=Depends(require_weekly_quota("assistant_chat", 3)),
):
    """
    AI助手聊天（SSE真流式）- 方案A优化
    
    流程：
    1. 检索候选文献（2-5秒）
    2. 立即开始流式生成（实时推送token）
    3. 生成完成后校验引用并发送citations
    """

    async def generate():
        search_start = time.time()
        
        logger.info(
            "✅ SSE真流式 | query=%s use_agent=%s top_k=%s",
            request.query,
            request.use_agent,
            request.top_k,
        )
        
        # 初始状态
        yield _sse_payload({"type": "status", "text": "检索文献中..."})
        yield _sse_payload({"type": "meta", "stream_token_type": "token"})
        
        try:
            # ========== 阶段1: 快速检索（2-5秒） ==========
            if request.use_agent:
                yield _sse_payload({"type": "status", "text": "Agent模式：在线检索PubMed..."})
                pubmed_toolkit = PubMedToolkit(PubMedClient())
                candidates = await pubmed_toolkit.run_agent_pipeline(
                    query=request.query,
                    sports_gate=request.sports_gate,
                    top_k=request.top_k,
                    timeout=30  # 30秒超时保护
                )
            else:
                yield _sse_payload({"type": "status", "text": "本地模式：查询数据库..."})
                
                # ✅ 智能翻译：中文查询翻译为英文
                import re
                has_chinese = bool(re.search(r'[\u4e00-\u9fff]', request.query))
                
                if has_chinese:
                    yield _sse_payload({"type": "status", "text": "翻译中文查询..."})
                    translator = QueryTranslator(deepseek)
                    search_query = await translator.translate_query(request.query)
                    logger.info(f"中文查询已翻译: '{request.query}' -> '{search_query}'")
                    yield _sse_payload({"type": "status", "text": f"查询关键词: {search_query}"})
                else:
                    search_query = request.query
                
                local_search = LocalSearchService(db)
                candidates = await local_search.search(
                    query=search_query,
                    top_k=request.top_k,
                    search_scope="tiab",
                    source=request.local_source,
                )
            
            search_duration = time.time() - search_start
            logger.info(f"检索完成 {len(candidates)}篇文献，耗时{search_duration:.2f}s")
            
            if not candidates:
                # 根据检索模式给出智能提示（不再提示 Sports Gate）
                if request.use_agent:
                    error_msg = "未找到相关文献。建议：1) 简化查询词 2) 使用更通用的关键词 3) 切换到本地模式尝试"
                else:
                    error_msg = "本地库未找到相关文献，建议切换到在线模式（PubMed 全库）"
                
                yield _sse_payload({
                    "type": "error",
                    "code": "E_NO_RESULTS",
                    "message": error_msg
                })
                return
            
            yield _sse_payload({
                "type": "status", 
                "text": f"已召回{len(candidates)}篇文献，DeepSeek生成中..."
            })
            
            # ========== 阶段2: 真流式生成（实时推送） ==========
            # ✅ 使用用户设置的top_k，但限制上限为20
            max_reference_idx = min(len(candidates), max(4, min(request.top_k, 20)))
            session_summary = None
            if request.session_id:
                try:
                    session_summary = await cache_get(f"assistant:session:summary:{request.session_id}")
                except Exception:
                    session_summary = None

            async for event in generate_streaming_response(
                query=request.query,
                candidates=candidates,
                deepseek_client=deepseek,
                lang=request.lang,
                max_reference_idx=max_reference_idx,
                model=request.model,
                conversation_summary=session_summary,
                session_id=request.session_id
            ):
                yield _sse_payload(event)
            
        except HTTPException as http_exc:
            detail = http_exc.detail
            if isinstance(detail, dict):
                payload = {
                    "type": "error",
                    "code": detail.get("error_code", "E_STREAM_HTTP"),
                    "message": detail.get("message", str(detail)),
                }
            else:
                payload = {
                    "type": "error",
                    "code": "E_STREAM_HTTP",
                    "message": str(detail),
                }
            yield _sse_payload(payload, event="error")
            return
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Stream generation error: %s", exc, exc_info=True)
            yield _sse_payload(
                {
                    "type": "error",
                    "code": "E_STREAM_EXCEPTION",
                    "message": str(exc),
                },
                event="error",
            )
            return

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/chat-stream")
async def chat_stream_get(
    query: str,
    sports_gate: bool = False,
    use_agent: bool = False,
    top_k: int = 10,
    lang: str = "zh",
    model: str = DEEPSEEK_V4_FLASH_MODEL,
    session_id: Optional[str] = None,
    local_source: str = "both",
    db: AsyncSession = Depends(get_db),
    deepseek: DeepSeekClient = Depends(get_deepseek_client),
    current_user: PoolUser = Depends(get_current_user),
):
    """
    AI助手聊天（SSE流式，GET 兼容 EventSource）
    """
    if not is_member_user(current_user):
        limiter = UsageLimitService(db)
        result = await limiter.consume_weekly_quota(
            user_id=current_user.id,
            feature_key="assistant_chat",
            limit=3,
        )
        if not result.allowed:
            async def _deny():
                yield _sse_payload(
                    {
                        "type": "error",
                        "code": "WEEKLY_LIMIT_EXCEEDED",
                        "message": f"本功能每周最多 {result.limit} 次（本周已用 {result.used} 次）",
                        "detail": {
                            "feature": result.feature_key,
                            "week_start": result.week_start.isoformat(),
                            "week_end": result.week_end.isoformat(),
                            "limit": result.limit,
                            "used": result.used,
                            "remaining": result.remaining,
                        },
                    },
                    event="error",
                )
                yield _sse_payload({"type": "done"}, event="done")

            return StreamingResponse(
                _deny(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )

    # 仅在本地模式下使用本地数据源选项；为空时回退为 both
    effective_local_source = local_source or "both"
    req = AssistantChatRequest(
        query=query,
        sports_gate=sports_gate,
        use_agent=use_agent,
        top_k=top_k,
        lang=lang,
        model=model,
        session_id=session_id,
        local_source=effective_local_source,
    )
    return await chat_stream(req, db, deepseek)


@router.get("/test-sse")
async def test_sse():
    """测试 SSE 流式响应"""
    async def generate():
        for i in range(5):
            yield f"event: message\ndata: {json.dumps({'index': i, 'text': f'测试消息 {i}'})}\n\n".encode('utf-8')
            await asyncio.sleep(0.5)
        yield b"event: message\ndata: {\"type\": \"done\"}\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/export-nbib")
async def export_nbib(request: ExportNbibRequest):
    """
    导出引用为NBIB格式（PubMed标准格式）
    """
    try:
        if not request.pmids:
            raise HTTPException(status_code=400, detail="pmids不能为空")
        client = PubMedClient()
        nbib_text = await client.fetch_nbib(request.pmids)
        if not nbib_text:
            raise HTTPException(status_code=404, detail="未获取到NBIB内容")
        headers = {
            "Content-Type": "text/plain; charset=utf-8",
            "Content-Disposition": "attachment; filename=records.nbib",
        }
        return StreamingResponse(iter([nbib_text]), headers=headers, media_type="text/plain")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"export_nbib error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
