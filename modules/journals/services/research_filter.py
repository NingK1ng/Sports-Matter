"""
研究文章过滤器：使用LLM识别非研究杂项
用于增量爬取时过滤掉非研究文章（如编辑选择、新产品等）
"""
import asyncio
import os
import json
from typing import Tuple
import aiohttp
import logging
from dotenv import load_dotenv

from core.external.deepseek import DEEPSEEK_V4_FLASH_MODEL, THINKING_DISABLED, normalize_deepseek_model

load_dotenv()
logger = logging.getLogger(__name__)


class ResearchArticleFilter:
    """研究文章过滤器（单例模式）"""

    _instance = None
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, '_initialized'):
            self.api_key = os.getenv("LLM_API_KEY")
            if not self.api_key:
                raise ValueError("需要设置LLM_API_KEY环境变量")

            self.base_url = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
            self.model = normalize_deepseek_model(os.getenv("LLM_MODEL", DEEPSEEK_V4_FLASH_MODEL))
            self._initialized = True

    async def is_research_article(
        self,
        title: str,
        abstract: str,
        threshold: float = 0.8
    ) -> Tuple[bool, str, float]:
        """
        判断是否为研究文章

        Args:
            title: 文章标题
            abstract: 摘要
            threshold: 非研究置信度阈值（≥此值则判定为非研究，拒绝入库）

        Returns:
            (is_research, reason, confidence)
            - is_research: True=研究文章（允许入库），False=非研究杂项（拒绝入库）
            - reason: 判断理由
            - confidence: 置信度（对于非研究判断的置信度）
        """
        # 保守策略：如果摘要太短（<50字符），仅根据标题明显的非研究特征判断
        # 否则默认保留，避免误删研究文章
        if not abstract or len(abstract.strip()) < 50:
            # 摘要缺失或太短，检查标题是否明显的非研究类型
            non_research_keywords = [
                "New Products", "Editor's Choice", "Editors' Choice",
                "Books Received", "Book Review", "Correction", "Erratum",
                "Retraction", "Society News", "Meeting Announcement",
                "In Brief", "News at a Glance"
            ]

            for keyword in non_research_keywords:
                if keyword.lower() in title.lower():
                    logger.info(
                        f"🗑️  过滤非研究文章（标题匹配）: {title[:50]}..."
                    )
                    return False, f"标题包含非研究关键词：{keyword}", 0.95

            # 标题未匹配非研究特征，默认保留
            return True, "摘要缺失且标题无明显非研究特征，默认保留", 0.0

        prompt = f"""你是科学出版专家。请判断这篇文章是**正式研究文章**还是**非研究杂项**。

文章类型定义：
1. **正式研究文章（research）**：
   - 原创研究论文（original research）
   - 综述/系统综述（review, systematic review）
   - Meta分析
   - 技术报告（technical report）
   - 案例研究（case study）
   - 临床试验（clinical trial）
   - 方法学文章（methods）

2. **非研究杂项（non-research）**：
   - 编辑选择/编辑评论（Editor's Choice, Editorial, Commentary）
   - 新闻简讯（News, News at a Glance, In Brief）
   - 产品介绍（New Products）
   - 书评/书讯（Book Review, Books Received）
   - 更正/勘误（Correction, Erratum, Retraction）
   - 会议通知（Meeting Announcement）
   - 讣告（Obituary）
   - 致编辑的信（Letter to Editor - 除非是研究性质）

判断标准（保守策略）：
- **仅当标题明确显示非研究类型** 或 **摘要明确为评论/新闻/产品介绍** 时，才判定为non-research
- 如果标题明确显示是非研究类型（如包含"New Products"、"Editor's Choice"等），置信度应≥0.95
- 如果摘要包含研究方法、数据、结果、结论等研究要素，必须判断为research
- 如果信息不足无法确定，应判断为research（保守策略，避免误删）

标题: {title}

摘要: {abstract if abstract else '（无摘要）'}

请以JSON格式输出（分数精确到小数点后两位）：
{{
  "type": "research",  // "research" 或 "non-research"
  "confidence": 0.95,  // 0.0-1.0，对该判断的置信度
  "reason": "这是一篇关于...的原创研究论文"  // 50字以内的判断理由
}}
"""

        messages = [{"role": "user", "content": prompt}]

        max_retries = 2
        for retry in range(max_retries + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    response = await session.post(
                        f"{self.base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "model": self.model,
                            "messages": messages,
                            "temperature": 0.1,
                            "response_format": {"type": "json_object"},
                            "thinking": THINKING_DISABLED,
                        },
                        timeout=aiohttp.ClientTimeout(total=30)
                    )

                    response.raise_for_status()
                    data = await response.json()
                    content = data['choices'][0]['message']['content']
                    result = json.loads(content)

                    article_type = result.get('type', 'research')
                    confidence = float(result.get('confidence', 0.0))
                    reason = result.get('reason', '')

                    # 如果是非研究文章且置信度≥阈值，则拒绝入库
                    is_research = not (article_type == 'non-research' and confidence >= threshold)

                    if not is_research:
                        logger.info(
                            f"🗑️  过滤非研究文章: {title[:50]}... "
                            f"(type={article_type}, confidence={confidence:.2f})"
                        )

                    return is_research, reason, confidence

            except asyncio.TimeoutError:
                if retry < max_retries:
                    await asyncio.sleep((retry + 1) * 2)
                    continue
                else:
                    # 保守策略：超时时默认为研究文章，避免误删
                    logger.warning(f"⚠️  LLM API超时，默认保留文章: {title[:50]}...")
                    return True, "API超时，默认保留", 0.0

            except Exception as e:
                if retry < max_retries:
                    await asyncio.sleep((retry + 1) * 2)
                    continue
                else:
                    # 保守策略：错误时默认为研究文章，避免误删
                    logger.warning(f"⚠️  LLM API错误，默认保留文章: {title[:50]}... (错误: {e})")
                    return True, f"API错误: {type(e).__name__}", 0.0

    async def classify_non_research_titles_batch(
        self,
        titles: list[str],
        *,
        max_tokens: int = 256,
    ) -> list[bool]:
        """
        批量判断标题是否为非研究杂项（单次调用，极低成本）。

        返回值：
            List[bool]：True=non-research（应过滤），False=research（保留）

        注意：
            - 保守策略：仅当标题非常明确为 Editorial/Correction/Retraction 等时才标为 non-research
            - 出错/解析失败时默认全部保留（返回全 False）
        """
        if not titles:
            return []

        # 轻量化：裁剪过长标题，降低输入 token
        cleaned_titles: list[str] = []
        for t in titles:
            s = (t or "").strip().replace("\n", " ")
            if len(s) > 240:
                s = s[:240] + "…"
            cleaned_titles.append(s)

        # 用最短的 JSON 输出，减少输出 token
        title_lines = "\n".join([f"{i+1}. {t}" for i, t in enumerate(cleaned_titles)])
        prompt = (
            "你是科学出版编辑。请仅根据标题判断每条是否属于“非研究杂项”。\n"
            "非研究杂项包括：Editorial/Commentary/News/Book Review/Meeting Announcement/"
            "Correction/Erratum/Retraction/Obituary/Publisher Correction/Author Correction 等。\n"
            "规则（必须保守）：只有当标题非常明确指向上述非研究类型时才标记为 1，否则标记为 0。\n"
            "请严格输出 JSON：{\"nr\":[0,1,...]}，数组长度必须与输入一致；不要输出任何解释。\n"
            f"标题列表：\n{title_lines}\n"
        )

        messages = [{"role": "user", "content": prompt}]

        max_retries = 2
        for retry in range(max_retries + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    response = await session.post(
                        f"{self.base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": self.model,
                            "messages": messages,
                            "temperature": 0.0,
                            "max_tokens": max_tokens,
                            "response_format": {"type": "json_object"},
                            "thinking": THINKING_DISABLED,
                        },
                        timeout=aiohttp.ClientTimeout(total=40),
                    )

                    response.raise_for_status()
                    data = await response.json()
                    content = data["choices"][0]["message"]["content"]
                    result = json.loads(content)
                    flags = result.get("nr")
                    if not isinstance(flags, list):
                        raise ValueError("invalid_response: missing nr list")
                    if len(flags) != len(cleaned_titles):
                        raise ValueError("invalid_response: length mismatch")

                    out: list[bool] = []
                    for v in flags:
                        try:
                            out.append(int(v) == 1)
                        except Exception:
                            out.append(False)
                    return out

            except asyncio.TimeoutError:
                if retry < max_retries:
                    await asyncio.sleep((retry + 1) * 2)
                    continue
                logger.warning("⚠️  LLM batch filter 超时，默认全部保留")
                return [False] * len(cleaned_titles)

            except Exception as e:
                if retry < max_retries:
                    await asyncio.sleep((retry + 1) * 2)
                    continue
                logger.warning("⚠️  LLM batch filter 失败，默认全部保留: %s", e)
                return [False] * len(cleaned_titles)


# 全局单例
_filter_instance = None


def get_research_filter() -> ResearchArticleFilter:
    """获取研究文章过滤器实例（单例）"""
    global _filter_instance
    if _filter_instance is None:
        _filter_instance = ResearchArticleFilter()
    return _filter_instance
