"""
知识图谱 WiW 生成服务

为单个社区生成基于 Top 文献摘要的中文小综述。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import httpx

from core.config import settings
from core.external.deepseek import DEEPSEEK_V4_FLASH_MODEL, THINKING_DISABLED, normalize_deepseek_model

logger = logging.getLogger(__name__)


class KGWiWGenerator:
    """知识图谱社区级 WiW 生成器"""

    def __init__(
        self,
        model: Optional[str] = None,
        timeout: float = 180.0,
    ) -> None:
        api_key = (
            settings.deepseek_api_key
            or os.getenv("DS_API_KEY")
            or os.getenv("DEEPSEEK_API_KEY")
            or os.getenv("OPENAI_API_KEY")
        )
        if not api_key:
            raise ValueError("Missing DeepSeek API key for KG WiW")
        self.api_key = api_key
        # settings.deepseek_base_url 已包含 /v1
        base = settings.deepseek_base_url or "https://api.deepseek.com/v1"
        self.base_url = base.rstrip("/")
        # WiW 小综述使用 v4-flash 非思考模式，自由生成中文段落
        self.model = normalize_deepseek_model(model or os.getenv("KG_WIW_MODEL") or DEEPSEEK_V4_FLASH_MODEL)
        self.timeout = timeout

    def _build_system_prompt(self, language: str = "zh") -> str:
        # 目前只支持中文输出
        return (
            "你是一名运动科学与运动医学领域的综述写作专家，"
            "擅长阅读多篇英文论文的标题和摘要，用流畅、专业的中文写出结构清晰的小综述。"
            "你的分析必须严谨、基于文献事实，不能凭空捏造研究结论。"
        )

    def _trim(self, text: Optional[str], max_chars: int = 1200) -> str:
        if not text:
            return "（无摘要）"
        t = text.strip()
        if len(t) <= max_chars:
            return t
        return t[: max_chars - 3] + "..."

    def _build_user_prompt(
        self,
        community_label: str,
        representative_terms: List[str],
        papers: List[Dict[str, Any]],
        window: str,
        as_of: str,
        language: str = "zh",
    ) -> str:
        """构建用户提示词：基于社区信息 + Top 文献摘要生成中文小综述。"""
        label = community_label.strip() if community_label else "（未提供）"
        terms_str = "；".join(representative_terms) if representative_terms else "（未提供）"

        window_map = {
            "1d": "最近1天",
            "7d": "最近7天",
            "30d": "最近30天",
            "180d": "最近半年",
        }
        window_desc = window_map.get(window, f"最近一段时间（窗口={window}）")

        refs_blocks: List[str] = []
        for idx, p in enumerate(papers, 1):
            title = (p.get("title") or "").strip()
            abstract = self._trim(p.get("abstract"))
            pmid = (p.get("pmid") or "").strip()
            refs_blocks.append(
                f"[文献{idx}] PMID: {pmid or 'N/A'}\n标题: {title or '（无标题）'}\n摘要: {abstract}"
            )
        refs_text = "\n\n".join(refs_blocks)

        return (
            "请你阅读下面给出的英文文献标题和摘要，并用中文写一篇短篇综述。\n\n"
            "# 社区信息\n"
            f"主题标签: {label}\n"
            f"代表性术语: {terms_str}\n\n"
            f"时间范围: {window_desc}，快照截止日期为 {as_of}。所有文献都属于这一时间窗口内的最新研究。\n\n"
            "# 代表性文献（按重要度排序，最多10篇）\n"
            f"{refs_text}\n\n"
            "# 写作任务\n"
            "1. 用 **中文** 写一段 300–500 字的小综述，面向科研工作者。\n"
            "2. 需要综合所有文献，概括该研究社区的核心主题、主要研究对象（人群/运动类型/疾病）、关键方法或指标，以及重要发现。\n"
            "3. 不要按文献逐条罗列，不要写成清单或标题列表，而是 1–2 个连贯自然段。\n"
            "4. 可以适度指出当前研究的局限和未来值得关注的方向，但避免空泛套话。\n"
            "5. 在综述正文中，当某个句子主要依据一篇或几篇上面给出的文献时，请在该句末尾添加引用标记，例如“……。[文献1][文献3]”。\n"
            "   - 引用时必须使用上面列出的编号，不要创造新的编号。\n"
            "   - 综述性或背景性句子可以不加引用。\n"
            "6. 不要在文末单独写“参考文献”段落，也不要罗列完整的文献信息；我们会在系统中单独渲染参考文献列表。\n"
            "7. 不要使用“近年来”“目前研究表明”“本文”“本综述”等模板化或写作过程相关的句式，直接从研究内容本身切入，例如“在截至上述时间窗口内的研究中，……”。\n"
            "8. 只输出中文正文，不要 JSON，不要 markdown 代码块标记。\n\n"
            "请直接开始写作，输出中文正文。"
        )

    async def generate_for_community(
        self,
        community_label: str,
        representative_terms: List[Dict[str, Any]],
        top_papers: List[Dict[str, Any]],
        window: str,
        as_of: str,
        language: str = "zh",
    ) -> str:
        """
        为单个社区生成 WiW 文本（中文小综述）。

        Args:
            community_label: 社区主标签（可为空）
            representative_terms: 代表性术语列表 [{term, score}, ...]
            top_papers: Top 文献列表（期望长度≤10），每项包含 title/abstract 等
            language: 输出语言，目前仅支持 "zh"
        """
        if not top_papers:
            # 没有文献，无法生成高质量综述
            return ""

        # 只取前10篇文献
        papers = top_papers[:10]
        terms = []
        for t in representative_terms or []:
            term = ""
            if isinstance(t, str):
                term = t
            elif isinstance(t, dict):
                term = str(t.get("term") or "")
            term = term.strip()
            if term:
                terms.append(term)
        # 去重保持顺序
        seen = set()
        dedup_terms: List[str] = []
        for t in terms:
            if t not in seen:
                seen.add(t)
                dedup_terms.append(t)

        user_prompt = self._build_user_prompt(
            community_label=community_label,
            representative_terms=dedup_terms[:8],
            papers=papers,
            window=window,
            as_of=as_of,
            language=language,
        )
        system_prompt = self._build_system_prompt(language=language)

        logger.info("KG WiW 调用 DeepSeek 模型=%s，用文献数=%d", self.model, len(papers))

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.4,
                    "max_tokens": 900,
                    "thinking": THINKING_DISABLED,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            try:
                message = data["choices"][0]["message"]
                content = message.get("content") or ""
            except Exception:
                logger.warning("KG WiW: DeepSeek 响应结构异常: %s", data)
                raise

        text = (content or "").strip()
        if not text:
            logger.warning("KG WiW: DeepSeek 返回空内容")
            return ""
        # 去掉可能的 markdown 包裹
        if text.startswith("```"):
            text = text.replace("```markdown", "").replace("```text", "").replace("```", "").strip()
        return text
