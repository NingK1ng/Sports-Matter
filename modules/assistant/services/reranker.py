from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Dict, List, Optional, Tuple

import numpy as np

from core.external.deepseek import DEEPSEEK_V4_FLASH_MODEL, DeepSeekClient
from core.services.embedding_service import get_embedding_service
from modules.assistant.models.candidate import CandidateArticle

logger = logging.getLogger(__name__)


class DeepSeekReranker:
    """使用DeepSeek v4-flash进行0-10分相关性重排"""

    def __init__(
        self,
        deepseek_client: DeepSeekClient,
        max_llm_items: int = 10,
        llm_concurrency: int = 4,
    ):
        self.deepseek = deepseek_client
        self.max_llm_items = max(1, max_llm_items)
        self.llm_concurrency = max(1, min(llm_concurrency, self.max_llm_items))
        self.embedding_service = get_embedding_service()

    async def rerank(self, query: str, candidates: List[CandidateArticle]) -> List[CandidateArticle]:
        if not candidates:
            return []

        query_embedding = self.embedding_service.generate_embedding(query)
        base_scores = self._compute_base_scores(query_embedding, candidates)

        llm_scores = await self._score_with_llm(query, candidates, base_scores)

        combined_scores: Dict[int, float] = {}
        for idx in range(len(candidates)):
            llm_component = llm_scores.get(idx)
            base_component = base_scores.get(idx)

            if base_component is not None:
                base_norm = (base_component + 1.0) / 2.0  # map [-1,1] -> [0,1]
            else:
                base_norm = None

            if llm_component is None and base_norm is None:
                combined_scores[idx] = -1.0
            elif llm_component is None:
                combined_scores[idx] = base_norm * 10.0  # scale to 0-10
            elif base_norm is None:
                combined_scores[idx] = llm_component
            else:
                combined_scores[idx] = 0.7 * llm_component + 0.3 * (base_norm * 10.0)

        # 排序
        sorted_indices = sorted(
            combined_scores.keys(),
            key=lambda idx: (combined_scores[idx], base_scores.get(idx, -1.0)),
            reverse=True,
        )

        reranked = [candidates[idx] for idx in sorted_indices]
        logger.debug(
            "Rerank scores: %s",
            {idx: round(combined_scores[idx], 2) for idx in sorted_indices[:10]},
        )
        return reranked

    def _compute_base_scores(
        self,
        query_embedding: Optional[List[float]],
        candidates: List[CandidateArticle],
    ) -> Dict[int, float]:
        scores: Dict[int, float] = {}
        if not query_embedding:
            return scores

        query_vec = np.array(query_embedding, dtype=np.float32)
        query_norm = np.linalg.norm(query_vec) + 1e-8

        for idx, candidate in enumerate(candidates):
            candidate_embedding = self.embedding_service.generate_from_title_abstract(
                candidate.title,
                candidate.abstract,
            )
            if not candidate_embedding:
                continue
            cand_vec = np.array(candidate_embedding, dtype=np.float32)
            denom = (np.linalg.norm(cand_vec) + 1e-8) * query_norm
            if denom <= 0:
                continue
            scores[idx] = float(np.dot(query_vec, cand_vec) / denom)
        return scores

    async def _score_with_llm(
        self,
        query: str,
        candidates: List[CandidateArticle],
        base_scores: Dict[int, float],
    ) -> Dict[int, float]:
        if not candidates:
            return {}

        # 根据向量相似度选择前max_llm_items个进行打分
        sorted_indices = sorted(
            range(len(candidates)),
            key=lambda idx: base_scores.get(idx, 0.0),
            reverse=True,
        )
        top_indices = sorted_indices[: self.max_llm_items]

        scores: Dict[int, float] = {}
        if not top_indices:
            return scores

        semaphore = asyncio.Semaphore(self.llm_concurrency)

        async def _worker(idx: int) -> Tuple[int, Optional[float]]:
            async with semaphore:
                try:
                    score = await self._score_single(query, candidates[idx].title)
                except Exception as exc:  # pylint: disable=broad-except
                    logger.warning("DeepSeek rerank单项评分失败 idx=%s: %s", idx, exc)
                    return idx, None
                return idx, score

        tasks = [_worker(idx) for idx in top_indices]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logger.warning("DeepSeek rerank并发任务异常: %s", result)
                continue
            idx, score = result
            if score is not None:
                scores[idx] = score
            else:
                logger.debug("LLM rerank score missing for idx=%s", idx)
        return scores

    async def _score_single(self, query: str, title: str) -> Optional[float]:
        prompt = (
            "你是一名科研文献检索评估助手。请根据用户需求判断文献标题的相关性，并返回0-10之间的整数分数。\n"
            "请使用JSON格式输出，字段命名为score。\n"
            "示例：{\"score\": 8}\n"
            f"用户问题：{query}\n"
            f"候选标题：{title}\n"
            "只输出JSON，严禁包含额外文本。"
        )
        try:
            raw = await self.deepseek.chat(
                messages=[{"role": "user", "content": prompt}],
                model=DEEPSEEK_V4_FLASH_MODEL,
                temperature=0.0,
                max_tokens=10,
                response_format={"type": "json_object"},
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("DeepSeek rerank请求失败: %s", exc)
            return None

        try:
            data = json.loads(raw)
            score = data.get("score")
            if score is None:
                raise ValueError("missing score field")
            score_val = float(score)
            return max(0.0, min(10.0, score_val))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            logger.warning("DeepSeek rerank解析失败: %s", exc)
            match = re.search(r"(-?\d+(?:\.\d+)?)", raw)
            if not match:
                return None
            try:
                score_val = float(match.group(1))
            except ValueError:
                return None
            return max(0.0, min(10.0, score_val))
