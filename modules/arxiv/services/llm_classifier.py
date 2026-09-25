"""
LLM分类服务
提供运动科学相关度判断、4类分类、中文翻译功能
"""
import json
import logging
from typing import Dict, List, Optional, Tuple
from openai import OpenAI

from core.external.deepseek import DEEPSEEK_V4_FLASH_MODEL, THINKING_DISABLED

logger = logging.getLogger(__name__)


class ArxivLLMClassifier:
    """arXiv文章LLM分类器"""

    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com/v1"):
        """
        初始化LLM分类器

        Args:
            api_key: DeepSeek API密钥
            base_url: API基础URL
        """
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = DEEPSEEK_V4_FLASH_MODEL

    def judge_relevance(self, title: str, abstract: str) -> Tuple[float, str]:
        """
        判断文章与运动科学的相关度

        Args:
            title: 文章标题
            abstract: 文章摘要（最多500字符）

        Returns:
            (relevance, reason): 相关度分数0.0-1.0和理由
        """
        prompt = f"""你是运动科学专家。根据标题和摘要判断该论文与运动科学（sports science）、体育工程（sports engineering）、运动医学（sports medicine）、运动训练（exercise training）的相关度。

标题：{title}
摘要：{abstract[:500]}

返回JSON格式：
{{
    "relevance": 0.0-1.0的浮点数,
    "reason": "简要中文理由（20字以内）"
}}

只返回JSON，不要其他内容。"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                temperature=0.3,
                extra_body={"thinking": THINKING_DISABLED},
            )

            content = response.choices[0].message.content.strip()
            # 尝试解析JSON
            result = json.loads(content)
            relevance = float(result.get("relevance", 0.0))
            reason = result.get("reason", "未知")

            return relevance, reason

        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {content}, 错误: {e}")
            return 0.0, "JSON解析失败"
        except Exception as e:
            logger.error(f"相关度判断失败: {e}")
            return 0.0, f"API调用失败: {str(e)}"

    def classify_category(self, title: str, abstract: str) -> Tuple[str, float]:
        """
        将文章分类到4大运动科学类别之一

        Args:
            title: 文章标题
            abstract: 文章摘要（最多500字符）

        Returns:
            (category, confidence): 分类key和置信度
        """
        prompt = f"""你是运动科学专家。将该论文分类到以下4个体育科学类别之一：

1. technology（体育工程与技术）- AI+运动、可穿戴设备、运动数据分析、视频分析
2. training（运动训练）- 训练方法、技术战术、表现优化
3. science（运动基础学科）- 生理学、生物力学、心理学、营养学
4. medicine（运动医学与康复）- 损伤预防、康复、疲劳、过度训练

标题：{title}
摘要：{abstract[:500]}

返回JSON格式：
{{
    "category": "technology" | "training" | "science" | "medicine",
    "confidence": 0.0-1.0的浮点数
}}

只返回JSON，不要其他内容。"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                temperature=0.3,
                extra_body={"thinking": THINKING_DISABLED},
            )

            content = response.choices[0].message.content.strip()
            result = json.loads(content)
            category = result.get("category", "science")
            confidence = float(result.get("confidence", 0.5))

            # 验证分类key
            valid_categories = ["technology", "training", "science", "medicine"]
            if category not in valid_categories:
                logger.warning(f"无效分类: {category}，默认为science")
                category = "science"

            return category, confidence

        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {content}, 错误: {e}")
            return "science", 0.5
        except Exception as e:
            logger.error(f"分类失败: {e}")
            return "science", 0.5

    def translate_to_chinese(self, text: str, text_type: str = "title") -> str:
        """
        将英文文本翻译为中文

        Args:
            text: 英文文本
            text_type: 文本类型（title/abstract）

        Returns:
            中文翻译
        """
        if not text or not text.strip():
            return ""

        prompt = f"""请将以下英文{text_type}翻译为中文，保持专业术语准确：

{text}

只返回翻译结果，不要其他内容。"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000 if text_type == "abstract" else 200,
                temperature=0.3,
                extra_body={"thinking": THINKING_DISABLED},
            )

            translation = response.choices[0].message.content.strip()
            return translation

        except Exception as e:
            logger.error(f"翻译失败: {e}")
            return ""

    def process_batch(
        self,
        articles: List[Dict[str, str]],
        threshold: float = 0.5,
        *,
        translate: bool = True,
        classify: bool = False,
    ) -> List[Dict]:
        """
        批量处理文章：默认只做相关度判断，可选是否做4类分类 + 翻译

        Args:
            articles: 文章列表，每个包含title和abstract
            threshold: 相关度阈值，默认0.5

        Returns:
            处理后的文章列表（只包含相关度>threshold的文章）
        """
        processed = []

        for article in articles:
            title = article.get("title", "")
            abstract = article.get("abstract", "")

            # 步骤1：相关度判断
            relevance, reason = self.judge_relevance(title, abstract)

            if relevance < threshold:
                logger.info(f"文章相关度{relevance:.2f}低于阈值{threshold}，跳过: {title[:50]}")
                continue

            # 步骤2：可选4类分类（默认关闭，降低成本）
            category = None
            confidence = None
            if classify:
                category, confidence = self.classify_category(title, abstract)

            # 步骤3：翻译标题和摘要（可关闭以降低成本）
            if translate:
                title_zh = self.translate_to_chinese(title, "title")
                abstract_zh = self.translate_to_chinese(abstract[:1000], "abstract") if abstract else ""
            else:
                title_zh = ""
                abstract_zh = ""

            processed.append(
                {
                    **article,  # 保留原始字段
                    "sport_relevance": relevance,
                    "relevance_reason": reason,
                    "sport_category": category,
                    "category_confidence": confidence,
                    "title_zh": title_zh,
                    "abstract_zh": abstract_zh,
                }
            )

        return processed
