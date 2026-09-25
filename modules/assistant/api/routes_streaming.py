"""
真流式实现 - 方案A优化
立即推送DeepSeek生成的token，无需等待全部完成
"""
import asyncio
import time
import json
import logging
import re
from typing import List, Dict, Any, Optional
from fastapi import HTTPException

from modules.assistant.models.candidate import CandidateArticle
from modules.assistant.prompts.citation_prompt import (
    build_citation_prompt,
    build_json_fallback_prompt
)
from core.cache import cache_set
from core.external.deepseek import DEEPSEEK_V4_FLASH_MODEL

logger = logging.getLogger(__name__)

JSON_SYSTEM_PROMPT = (
    "You must always respond with a valid JSON object that satisfies the user's schema. "
    "Do not return an empty string. If evidence is limited you must still output a full JSON object "
    "and include a sentence that states the limitation with an appropriate citation. "
    "Never include markdown or plain text outside the JSON object."
)


async def generate_streaming_response(
    query: str,
    candidates: List[CandidateArticle],
    deepseek_client,
    lang: str = "zh",
    max_reference_idx: int = 8,
    model: str = DEEPSEEK_V4_FLASH_MODEL,
    conversation_summary: Optional[str] = None,
    session_id: Optional[str] = None,
):
    """
    真流式生成 - 按规格实现
    
    流程：
    1. 实时推送DeepSeek生成的token
    2. 生成完成后校验引用
    3. 发送citations
    4. 如果是reasoner模型，发送推理链
    5. 发送done
    
    Args:
        model: 模型选择 deepseek-v4-flash；兼容旧 deepseek-chat / deepseek-reasoner 入参
    
    Yields:
        Dict[str, Any]: SSE事件数据
    """
    gen_start = time.time()
    all_chunks = []
    reasoning_content = None  # 推理链内容
    full_text = ""  # 初始化full_text
    
    # ✅ 使用统一的综述风格prompt，但要求直接输出文本而非JSON
    effective_candidates = candidates[:max_reference_idx]
    
    streaming_prompt = f"""你是该领域的资深专家。请基于下列文献撰写一篇小综述回答用户问题。

**关键要求**：
⚠️ 必须使用{"中文" if lang == "zh" else "英文"}撰写
⚠️ 直接输出带引用的文本，不要JSON格式

**角色定位**：
你是研究该问题多年的领域专家，熟悉相关研究脉络和前沿进展。请用专家的视角和语气撰写综述性回答。

**写作风格**：
- 采用综述性叙述，可以有起承转合、背景铺垫、趋势总结
- 可以对多篇文献进行横向对比、纵向梳理
- 可以指出研究的异同点、争议、不足或未来方向
- 语言要流畅自然，像专家在讲述而非机械罗列
- 篇幅：8-15句话，根据内容需要自由调整

**引用规则**：
- 每句话末尾必须标注引用[n]，n为参考文献编号（1-{max_reference_idx}）
- 如果文献提供了具体数据，可以引用
- 如果仅有标题和期刊，可描述研究方向和发表情况
- 可以多篇文献一起引用，如"多项研究表明..."[1,3,5]

**参考文献**：
"""
    for idx, c in enumerate(effective_candidates, start=1):
        abstract_preview = c.abstract[:300] + "..." if len(c.abstract) > 300 else (c.abstract or "（摘要缺失）")
        streaming_prompt += f"\n[{idx}] {c.title}\n期刊：{c.journal_name or 'N/A'} | 年份：{c.publication_year or 'N/A'}\n摘要：{abstract_preview}\n"
    
    if conversation_summary:
        streaming_prompt += f"""

**会话上下文摘要**：
{conversation_summary}
"""

    streaming_prompt += f"""

**用户问题**：
{query}

**请直接开始撰写综述性回答**（每句话末尾带引用编号）：
"""

    messages = [
        {"role": "user", "content": streaming_prompt}
    ]
    
    logger.info(f"Starting DeepSeek generation | model={model}, query={query}")
    
    try:
        # 旧 reasoner 入参保留为“v4-flash thinking”兼容路径；默认使用 v4-flash 非思考流式输出
        if model == "deepseek-reasoner":
            # ✅ 兼容旧Reasoner路径: 使用JSON格式（直接文本输出支持不稳定）
            json_prompt = build_citation_prompt(
                query=query,
                candidates=effective_candidates,
                lang=lang
            )
            json_messages = [
                {"role": "system", "content": JSON_SYSTEM_PROMPT},
                {"role": "user", "content": json_prompt}
            ]
            
            response_data = await deepseek_client.chat(
                messages=json_messages,
                model=DEEPSEEK_V4_FLASH_MODEL,
                temperature=0.3,
                max_tokens=2400,
                response_format={"type": "json_object"},
                return_message=True,
                disable_thinking=False,
            )
            
            raw_json = response_data.get("content", "")
            reasoning_content = response_data.get("reasoning", "")
            
            # 解析JSON并逐句推送
            if not raw_json or raw_json.strip() == "":
                logger.error("Reasoner returned empty content")
                yield {"type": "error", "code": "E_EMPTY_CONTENT", "message": "推理模型返回空内容"}
                return
            
            try:
                import json as json_lib
                result = json_lib.loads(raw_json)
                sentences = result.get("sentences", [])
                
                if not sentences:
                    logger.error("Reasoner JSON has no sentences")
                    yield {"type": "error", "code": "E_NO_SENTENCES", "message": "推理模型未返回有效句子"}
                    return
                
                # 逐句推送（纯文本+引用）
                text_parts = []
                for sent in sentences:
                    text = sent.get("text", "")
                    citations = sent.get("citations", []) or sent.get("citation_ids", [])
                    # 格式化为带引用的文本
                    if citations:
                        citation_str = "[" + ",".join(str(c) for c in citations) + "]"
                        formatted = f"{text}{citation_str}"
                    else:
                        formatted = text
                    
                    text_parts.append(formatted)
                    yield {"type": "token", "text": formatted + "\n"}
                
                # 组装完整文本用于后续解析
                full_text = "\n".join(text_parts)
                
            except json_lib.JSONDecodeError as json_err:
                logger.error(f"Failed to parse reasoner JSON: {json_err}, raw={raw_json[:200]}")
                yield {"type": "error", "code": "E_JSON_PARSE", "message": "推理模型返回格式错误"}
                return
            except Exception as parse_err:
                logger.error(f"Failed to process reasoner output: {parse_err}")
                yield {"type": "error", "code": "E_PARSE_ERROR", "message": str(parse_err)}
                return
            
        else:
            # ✅ Chat: 真流式推送
            sentence_buffer = ""
            sentence_endings = "。！？.!?"
            
            async for chunk in deepseek_client.chat_stream(
                messages=messages,
                model=DEEPSEEK_V4_FLASH_MODEL,
                temperature=0.3,
                max_tokens=2400  # ✅ 提升到2400，支持更长的综述回答
            ):
                all_chunks.append(chunk)
                sentence_buffer += chunk
                
                # 当遇到句号时推送整句（后面加换行便于阅读）
                if any(ending in chunk for ending in sentence_endings):
                    yield {"type": "token", "text": sentence_buffer + "\n"}
                    sentence_buffer = ""
            
            # 推送剩余内容
            if sentence_buffer:
                yield {"type": "token", "text": sentence_buffer + "\n"}
            
            full_text = "".join(all_chunks)
        gen_duration = time.time() - gen_start
        logger.info(f"DeepSeek generation completed in {gen_duration:.2f}s, length={len(full_text)}")
        
        # 解析和对齐引用
        citations_result = await _parse_and_validate_citations(
            full_text, 
            candidates[:max_reference_idx]
        )
        
        if citations_result["success"]:
            yield {
                "type": "citations",
                "items": citations_result["citations"]
            }
        else:
            # 对齐失败，尝试JSON回退
            logger.warning(f"Citation alignment failed, trying JSON fallback: {citations_result['errors']}")
            yield {"type": "status", "text": "引用对齐失败，尝试重新生成..."}
            
            fallback_result = await _json_fallback_generation(
                query,
                candidates[:max_reference_idx],
                deepseek_client,
                lang
            )
            
            if fallback_result["success"]:
                # 发送修正后的文本和引用
                yield {"type": "correction", "text": fallback_result["text"]}
                yield {"type": "citations", "items": fallback_result["citations"]}
            else:
                # 最终失败
                yield {
                    "type": "error",
                    "code": "E_CITATION_ALIGN",
                    "message": "引用生成失败，请重试",
                    "errors": fallback_result["errors"]
                }
                return
        
        # 如果是reasoner模型且有推理链，推送推理链
        if reasoning_content:
            logger.info(f"Sending reasoning chain, length={len(reasoning_content)}")
            yield {
                "type": "reasoning",
                "content": reasoning_content
            }
        
        try:
            if session_id:
                prev = conversation_summary or ""
                fragments = re.split(r"(?<=[。．.!！？?])\s+", full_text.strip()) if full_text else []
                first_sent = fragments[0] if fragments else (full_text[:200] if full_text else "")
                new_summary = (prev + " | Q: " + query.strip() + " | A: " + first_sent).strip()
                if len(new_summary) > 1000:
                    new_summary = new_summary[-1000:]
                await cache_set(f"assistant:session:summary:{session_id}", new_summary, ttl=604800)
        except Exception:
            pass

        # 成功完成
        yield {"type": "status", "text": "✅ 已生成回答"}
        yield {"type": "done"}
        
    except Exception as e:
        logger.error(f"Streaming generation error: {e}", exc_info=True)
        yield {
            "type": "error",
            "code": "E_GENERATION_FAILED",
            "message": str(e)
        }


async def _parse_and_validate_citations(
    text: str,
    candidates: List[CandidateArticle]
) -> Dict[str, Any]:
    """
    解析并校验引用
    
    Returns:
        {"success": bool, "citations": List[Dict], "errors": List[str]}
    """
    import re
    
    errors = []
    
    # 提取所有引用编号
    citation_pattern = r'\[(\d+(?:\s*,\s*\d+)*)\]'
    matches = re.findall(citation_pattern, text)
    
    if not matches:
        return {
            "success": False,
            "citations": [],
            "errors": ["未找到任何引用编号[n]"]
        }
    
    # 解析所有引用编号
    all_cited_ids = set()
    for match in matches:
        ids = [int(x.strip()) for x in match.split(',')]
        all_cited_ids.update(ids)
    
    # 校验范围
    max_idx = len(candidates)
    for cid in all_cited_ids:
        if cid < 1 or cid > max_idx:
            errors.append(f"引用编号[{cid}]越界（有效范围1-{max_idx}）")
    
    if errors:
        return {
            "success": False,
            "citations": [],
            "errors": errors
        }
    
    # ✅ 构建引用列表：返回所有候选文献，不仅仅是被引用的
    citations = []
    for idx, c in enumerate(candidates, start=1):
        citations.append({
            "idx": idx,
            "pmid": c.pmid,
            "title": c.title,
            "url": c.url,
            "journal_name": c.journal_name,
            "publication_year": c.publication_year,
            "cited": idx in all_cited_ids  # ✅ 标注是否被引用
        })
    
    return {
        "success": True,
        "citations": citations,
        "errors": []
    }


async def _json_fallback_generation(
    query: str,
    candidates: List[CandidateArticle],
    deepseek_client,
    lang: str
) -> Dict[str, Any]:
    """
    JSON回退生成（非流式）
    
    Returns:
        {"success": bool, "text": str, "citations": List[Dict], "errors": List[str]}
    """
    fallback_prompt = build_json_fallback_prompt(query, candidates, lang)
    fallback_messages = [
        {"role": "system", "content": JSON_SYSTEM_PROMPT},
        {"role": "user", "content": fallback_prompt}
    ]
    
    try:
        fallback_raw = await deepseek_client.chat(
            messages=fallback_messages,
            model=DEEPSEEK_V4_FLASH_MODEL,
            temperature=0.2,
            max_tokens=1024,
            response_format={"type": "json_object"}
        )
        
        if not fallback_raw:
            return {
                "success": False,
                "text": "",
                "citations": [],
                "errors": ["回退生成返回空内容"]
            }
        
        # 解析JSON
        import json as json_module
        fallback_json = json_module.loads(fallback_raw)
        
        # 组装文本
        sentences = []
        all_cited_ids = set()
        
        for sent_obj in fallback_json.get("sentences", []):
            text = sent_obj.get("text", "")
            citation_ids = sent_obj.get("citation_ids", sent_obj.get("citations", []))
            
            if not isinstance(citation_ids, list):
                citation_ids = [citation_ids]
            
            citation_ids = [int(cid) for cid in citation_ids if isinstance(cid, (int, str))]
            
            if not citation_ids:
                continue
            
            all_cited_ids.update(citation_ids)
            citation_str = "[" + ", ".join(map(str, citation_ids)) + "]"
            sentences.append(f"{text}{citation_str}")
        
        assembled_text = "\n".join(sentences)
        
        # 构建引用列表
        citations = []
        for idx in sorted(all_cited_ids):
            if 1 <= idx <= len(candidates):
                c = candidates[idx - 1]
                citations.append({
                    "idx": idx,
                    "pmid": c.pmid,
                    "title": c.title,
                    "url": c.url,
                    "journal_name": c.journal_name,
                    "publication_year": c.publication_year
                })
        
        return {
            "success": True,
            "text": assembled_text,
            "citations": citations,
            "errors": []
        }
        
    except Exception as e:
        logger.error(f"JSON fallback failed: {e}", exc_info=True)
        return {
            "success": False,
            "text": "",
            "citations": [],
            "errors": [str(e)]
        }
