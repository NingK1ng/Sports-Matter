from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
import re

from core.external.deepseek import DeepSeekClient
from core.external.deepseek import DEEPSEEK_V4_FLASH_MODEL
from core.external.pubmed import PubMedClient
from modules.assistant.services.query_translator import QueryTranslator

logger = logging.getLogger(__name__)


@dataclass
class PlannedQuery:
    priority: int
    query: str
    reason: str
    raw: Dict[str, Any] = field(default_factory=dict)
    final_query: str = ""
    hit_count: int = 0
    pmids: List[str] = field(default_factory=list)


@dataclass
class PlanResult:
    request_id: str
    prompt: str
    raw_response: str
    original_query: str
    queries: List[PlannedQuery]
    fallback: bool = False
    sports_gate_applied: bool = False
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class QueryPlanner:
    """基于DeepSeek的PubMed检索规划器"""

    def __init__(self, deepseek_client: DeepSeekClient, pubmed_client: PubMedClient):
        self.deepseek = deepseek_client
        self.pubmed = pubmed_client
        self.translator = QueryTranslator(deepseek_client)

    async def plan(
        self,
        query: str,
        *,
        sports_gate: bool = False,
        sports_gate_clause: Optional[str] = None,
        max_candidates: int = 4,
        retmax: int = 25,
    ) -> PlanResult:
        request_id = str(uuid.uuid4())

        # 对“RAG/检索增强”等方法论问题，LLM规划器容易误解缩写导致跑偏；
        # 这里直接走确定性fallback（仍然会调用 PubMed 真实命中校验）。
        normalized = (query or "").lower()
        rag_like = (
            bool(re.search(r"(?i)(?:^|[^A-Za-z0-9])rag(?:$|[^A-Za-z0-9])", query or ""))
            or "retrieval augmented generation" in normalized
            or "retrieval-augmented generation" in normalized
            or ("检索增强" in (query or ""))
        )
        if rag_like:
            logger.info("QueryPlanner: rag-like query detected, bypassing primary planner")
            return await self._fallback_plan(
                query,
                request_id=request_id,
                sports_gate=sports_gate,
                sports_gate_clause=sports_gate_clause,
                retmax=retmax,
                raw_response="",
                error="rag_like_shortcut",
            )

        prompt = self._build_prompt(query, max_candidates)
        messages = [
            {
                "role": "system",
                "content": (
                    "You are an expert PubMed search strategist for sports science and medicine. "
                    "Always think in English and respond in strict JSON."
                ),
            },
            {"role": "user", "content": prompt},
        ]

        try:
            raw_response = await self.deepseek.chat(
                messages=messages,
                model=DEEPSEEK_V4_FLASH_MODEL,
                temperature=0.2,
                max_tokens=900,
                response_format={"type": "json_object"},
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("QueryPlanner primary call failed: %s", exc)
            return await self._fallback_plan(
                query,
                request_id=request_id,
                sports_gate=sports_gate,
                sports_gate_clause=sports_gate_clause,
                retmax=retmax,
                error=str(exc),
            )

        try:
            data = json.loads(raw_response)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("QueryPlanner JSON解析失败: %s", exc)
            return await self._fallback_plan(
                query,
                request_id=request_id,
                sports_gate=sports_gate,
                sports_gate_clause=sports_gate_clause,
                retmax=retmax,
                raw_response=raw_response,
                error=f"json_decode_error:{exc}",
            )

        if isinstance(data, dict):
            queries = data.get("queries") or data.get("searches") or data.get("items") or []
            if not queries and data.get("query"):
                queries = [data]
        elif isinstance(data, list):
            queries = data
        else:
            logger.warning("QueryPlanner JSON结构异常: %s", type(data).__name__)
            return await self._fallback_plan(
                query,
                request_id=request_id,
                sports_gate=sports_gate,
                sports_gate_clause=sports_gate_clause,
                retmax=retmax,
                raw_response=raw_response,
                error=f"unexpected_json_type:{type(data).__name__}",
            )

        planned_queries: List[PlannedQuery] = []

        for idx, item in enumerate(queries[:max_candidates], start=1):
            if isinstance(item, str):
                item = {"query": item, "reason": "LLM returned a bare query string"}
            if not isinstance(item, dict):
                logger.debug("QueryPlanner跳过非对象检索项: %r", item)
                continue

            raw_query = (
                item.get("query")
                or item.get("pubmed_query")
                or item.get("search_query")
                or item.get("term")
                or ""
            ).strip()
            if not raw_query:
                continue

            try:
                priority = int(item.get("priority") or idx)
            except (TypeError, ValueError):
                priority = idx
            reason = (item.get("reason") or "").strip()
            final_query = raw_query

            if sports_gate and sports_gate_clause:
                final_query = f"({sports_gate_clause}) AND ({raw_query})"

            pmids, count = await self._safe_search(final_query, retmax)
            planned_queries.append(
                PlannedQuery(
                    priority=priority,
                    query=raw_query,
                    reason=reason,
                    raw=item,
                    final_query=final_query,
                    hit_count=count,
                    pmids=pmids,
                )
            )

        planned_queries.sort(key=lambda x: x.priority)
        filtered = [item for item in planned_queries if item.pmids]

        if not filtered:
            logger.info("QueryPlanner: 无有效命中，回退到传统翻译逻辑")
            return await self._fallback_plan(
                query,
                request_id=request_id,
                sports_gate=sports_gate,
                sports_gate_clause=sports_gate_clause,
                retmax=retmax,
                raw_response=raw_response,
                error="no_valid_hits",
            )

        return PlanResult(
            request_id=request_id,
            prompt=prompt,
            raw_response=raw_response,
            original_query=query,
            queries=filtered,
            fallback=False,
            sports_gate_applied=sports_gate,
        )

    async def _fallback_plan(
        self,
        query: str,
        *,
        request_id: str,
        sports_gate: bool,
        sports_gate_clause: Optional[str],
        retmax: int,
        raw_response: Optional[str] = None,
        error: Optional[str] = None,
    ) -> PlanResult:
        # 动态近年窗口（避免硬编码年份导致新年份无命中）
        current_year = datetime.now(timezone.utc).year
        start_year = max(1900, current_year - 6)  # 覆盖近6年（含今年）

        def _contains_year_hint(text: str) -> bool:
            # 若用户已显式给出年份/区间，则不再强行加默认时间窗
            return bool(re.search(r"\b(19|20)\d{2}\b", text))

        def _maybe_add_pdat(q: str) -> str:
            if _contains_year_hint(query):
                return q
            return f"({q}) AND ({start_year}:{current_year}[pdat])"

        # 特殊场景：方法论/AI检索（如 RAG）经常与领域词相交为0，先保证能召回方法类文献。
        normalized = query.lower()
        rag_like = (
            bool(re.search(r"(?i)(?:^|[^A-Za-z0-9])rag(?:$|[^A-Za-z0-9])", query))
            or "retrieval augmented generation" in normalized
            or "retrieval-augmented generation" in normalized
            or ("检索增强" in query)
        )
        if rag_like:
            # 仅使用“retrieval augmented generation”相关短语，避免 RAG 缩写与生物学/器械等领域缩写冲突。
            rag_clause = (
                '("retrieval augmented generation"[tiab] '
                'OR "retrieval-augmented generation"[tiab] '
                'OR (retrieval[tiab] AND augmented[tiab] AND generation[tiab]))'
            )

            # 先尝试与运动领域词相交（若用户问题明显带运动语义），无命中则回退到方法词本身
            wants_sports = sports_gate or ("运动" in query) or ("sport" in normalized) or ("exercise" in normalized) or ("athlet" in normalized)
            # tuple: (base_query, reason, apply_sports_gate)
            candidate_queries: list[tuple[str, str, bool]] = []
            if wants_sports:
                sports_clause = "(sport*[tiab] OR exercise[tiab] OR athlet*[tiab])"
                candidate_queries.append(
                    (
                        _maybe_add_pdat(f"({rag_clause}) AND {sports_clause}"),
                        "RAG method papers within sports/exercise context",
                        True,
                    )
                )
            # broad: 即使 sports_gate=true 也允许回退到方法论论文（否则会长期0命中，用户体验为“不可用”）
            candidate_queries.append((_maybe_add_pdat(rag_clause), "RAG method papers (broad)", False))

            for base_query, reason, apply_gate in candidate_queries:
                final_query = base_query
                if apply_gate and sports_gate and sports_gate_clause:
                    final_query = f"({sports_gate_clause}) AND ({base_query})"
                pmids, count = await self._safe_search(final_query, retmax)
                if pmids:
                    planned = PlannedQuery(
                        priority=1,
                        query=base_query,
                        reason=reason,
                        raw={"fallback": True, "pattern": "rag_like"},
                        final_query=final_query,
                        hit_count=count,
                        pmids=pmids,
                    )
                    return PlanResult(
                        request_id=request_id,
                        prompt=self._build_prompt(query, 1),
                        raw_response=raw_response or "",
                        original_query=query,
                        queries=[planned],
                        fallback=True,
                        sports_gate_applied=sports_gate,
                        error=error,
                    )

        translated = await self.translator.translate_query(query)

        heuristic_terms: List[str] = []

        if "acl" in normalized:
            heuristic_terms.append("(ACL[tiab] OR \"Anterior Cruciate Ligament\"[tiab])")
        if "重建" in query:
            heuristic_terms.append("reconstruction[tiab]")
        if "负重" in query:
            heuristic_terms.append("\"weight-bearing\"[tiab]")
        if "早期" in query:
            heuristic_terms.append("(early[tiab] OR accelerated[tiab])")
        if "延" in query:
            heuristic_terms.append("(delayed[tiab] OR late[tiab])")
        if "指南" in query or "综述" in query:
            heuristic_terms.append("(systematic review[pt] OR meta-analysis[pt] OR guideline[pt])")
        if "长新冠" in query or "long covid" in normalized or "pasc" in normalized or "post-covid" in normalized:
            heuristic_terms.extend([
                "(\"Post-Acute COVID-19 Syndrome\"[MeSH] OR \"Post-COVID-19 Syndrome\"[MeSH] OR \"Long COVID\"[tiab] OR PASC[tiab])",
                "(\"exercise therapy\"[MeSH] OR \"aerobic exercise\"[tiab] OR \"aerobic training\"[tiab] OR \"cardiorespiratory exercise\"[tiab] OR \"physical training\"[tiab])",
            ])
            extra_clauses: List[str] = []
            if "安全" in query or "safety" in normalized or "风险" in query:
                extra_clauses.append("(safety[tiab] OR adverse events[tiab] OR \"post-exertional malaise\"[tiab])")
            if "益处" in query or "作用" in query or "benefit" in normalized or "效果" in query:
                extra_clauses.append("(benefit[tiab] OR outcome[tiab] OR improvement[tiab] OR efficacy[tiab])")
            if extra_clauses:
                if len(extra_clauses) == 1:
                    heuristic_terms.append(extra_clauses[0])
                else:
                    heuristic_terms.append("(" + " OR ".join(extra_clauses) + ")")

        words = translated.split()

        if heuristic_terms:
            base_query = " AND ".join(heuristic_terms)
        else:
            if len(words) == 1:
                base_query = f"{translated}[tiab]"
            elif 1 < len(words) <= 4:
                base_query = " AND ".join(f"{w}[tiab]" for w in words)
            else:
                base_query = f'"{translated}"[tiab]'

        if _contains_year_hint(query):
            pass  # 用户已指明时间窗口
        else:
            # 默认关注近6年文献（含今年）
            base_query = f"({base_query}) AND ({start_year}:{current_year}[pdat])"

        final_query = base_query
        if sports_gate and sports_gate_clause:
            final_query = f"({sports_gate_clause}) AND ({base_query})"

        pmids, count = await self._safe_search(final_query, retmax)

        planned = PlannedQuery(
            priority=1,
            query=base_query,
            reason="Fallback keywords generated by QueryTranslator",
            raw={"fallback": True, "translated_keywords": translated},
            final_query=final_query,
            hit_count=count,
            pmids=pmids,
        )

        return PlanResult(
            request_id=request_id,
            prompt=self._build_prompt(query, 1),
            raw_response=raw_response or "",
            original_query=query,
            queries=[planned] if pmids else [],
            fallback=True,
            sports_gate_applied=sports_gate,
            error=error,
        )

    async def _safe_search(self, query: str, retmax: int) -> tuple[List[str], int]:
        try:
            pmids, total_count = await self.pubmed.search(
                query=query,
                retmax=retmax,
                retstart=0,
                use_cache=True,
                return_count=True,
            )
            return pmids or [], total_count or (len(pmids) if pmids else 0)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("QueryPlanner PubMed search failed for '%s': %s", query, exc)
            return [], 0

    def _build_prompt(self, query: str, max_candidates: int) -> str:
        exemplar_section = (
            "示例：\n"
            "1) 问题：ACL重建后早期负重与延迟负重的差异\n"
            "   可行检索：\n"
            "   - (\"Anterior Cruciate Ligament Reconstruction\"[MeSH] AND (early weight-bearing[tiab] OR accelerated rehabilitation[tiab]) AND randomized[tiab])\n"
            "   - (ACL[tiab] AND (\"early loading\"[tiab] OR \"immediate weight-bearing\"[tiab]) AND (\"delayed weight-bearing\"[tiab] OR control[tiab]) AND clinical trial[pt])\n"
            "2) 问题：跑步膝指南\n"
            "   可行检索：\n"
            "   - (\"Iliotibial Band Syndrome\"[MeSH] OR iliotibial band friction syndrome[tiab]) AND (guideline[pt] OR consensus[tiab] OR \"clinical practice guideline\"[tiab]) AND (2019:2025[pdat])\n"
        )

        return (
            f"请针对如下科研问题生成PubMed检索计划，并使用JSON格式回复：\n\n"
            f"问题：{query}\n\n"
            "总体原则：\n"
            "- 输出的检索式必须符合PubMed语法，包含字段限定（[mh]、[MeSH Terms]、[tiab]、[pt]、[pdat]等）\n"
            "- 覆盖不同角度：优先给出综述/指南、核心干预或比较、关键人群/风险因素等子检索\n"
            "- 每条检索应明确限定时间窗（近5年）或研究类型（guideline、systematic review、RCT等）\n"
            "- 引入MeSH与同义词，如: 疾病/干预的标准词、常用缩写、主要变量\n"
            "- 对于中文问题，自动翻译并挑选英文检索表达\n\n"
            f"{exemplar_section}\n"
            "输出格式要求：\n"
            f"1. 生成2-4条检索式（不超过{max_candidates}条），按优先级从高到低排列；如问题极窄可少于2条。\n"
            "2. JSON字段：priority (int)、query (string)、reason (string)、focus (string，可选说明如'guideline'/'RCT')。\n"
            "3. reason 应说明检索式覆盖的角度、限制条件。\n"
            "4. 只输出JSON正文，不要额外文字。\n"
        )
