"""
批量翻译服务（使用DeepSeek v4-flash）
专为文献标题翻译优化，成本极低
"""
import os
import json
import logging
from typing import List, Dict, Optional
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, or_, select, update

from modules.literature_stream.models.literature import Literature
from modules.journals.models.journal import JournalArticle
from modules.arxiv.models.arxiv_article import ArxivArticle
from core.external.deepseek import DEEPSEEK_V4_FLASH_MODEL, THINKING_DISABLED, normalize_deepseek_model

logger = logging.getLogger(__name__)


class BatchTranslator:
    """DeepSeek批量翻译器"""

    def __init__(self):
        self.api_key = (
            os.getenv("DS_API_KEY")
            or os.getenv("DEEPSEEK_API_KEY")
            or os.getenv("OPENAI_API_KEY")
        )
        if not self.api_key:
            raise ValueError("Missing DeepSeek API key. Set DS_API_KEY in .env")

        raw_base = (
            os.getenv("DS_API_BASE")
            or os.getenv("DEEPSEEK_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
            or "https://api.deepseek.com"
        )
        self.base_url = self._normalize_api_base(raw_base)

        self.model = normalize_deepseek_model(
            os.getenv("DS_MODEL")
            or os.getenv("DEEPSEEK_MODEL")
            or DEEPSEEK_V4_FLASH_MODEL
        )
        logger.info(f"BatchTranslator initialized: model={self.model}, base={self.base_url}")

    def _normalize_api_base(self, base: str) -> str:
        """规范化API base URL"""
        b = (base or "").strip().rstrip("/")
        if not b:
            b = "https://api.deepseek.com"
        if not b.endswith("/v1"):
            b = f"{b}/v1"
        return b

    async def translate_titles_for_literature(
        self,
        pmids: List[str],
        db: AsyncSession
    ) -> Dict[str, str]:
        """
        批量翻译文献标题（literature表）

        Args:
            pmids: PMID列表（最多50个）
            db: 数据库session

        Returns:
            {pmid: title_zh} 映射
        """
        if not pmids or len(pmids) == 0:
            return {}

        # 限制批量大小
        pmids = pmids[:50]

        missing_title_zh = or_(
            Literature.title_zh.is_(None),
            func.length(func.trim(Literature.title_zh)) == 0,
        )

        # 查询未翻译的文献（包含 title_zh 为空字符串的脏数据）
        query = select(Literature).where(
            Literature.pmid.in_(pmids),
            missing_title_zh,
        )
        result = await db.execute(query)
        papers = result.scalars().all()

        if not papers:
            logger.info(f"All {len(pmids)} papers already translated (cache hit)")
            # 返回已缓存的翻译
            cached_query = select(Literature.pmid, Literature.title_zh).where(
                Literature.pmid.in_(pmids),
                Literature.title_zh.is_not(None),
                func.length(func.trim(Literature.title_zh)) > 0,
            )
            cached_result = await db.execute(cached_query)
            return {row.pmid: row.title_zh for row in cached_result}

        logger.info(f"Translating {len(papers)} papers (cache miss)")

        # 构造标题列表
        titles_to_translate = []
        pmid_to_paper = {}
        for paper in papers:
            if paper.title and paper.title.strip():
                titles_to_translate.append({
                    "index": len(titles_to_translate) + 1,
                    "pmid": paper.pmid,
                    "title": paper.title.strip()
                })
                pmid_to_paper[paper.pmid] = paper

        if not titles_to_translate:
            return {}

        # 调用DeepSeek批量翻译
        try:
            translations = await self._call_deepseek_batch(titles_to_translate)
        except Exception as e:
            logger.error(f"DeepSeek translation failed: {e!r}")
            raise

        # 写回数据库
        result_map = {}
        for item in translations:
            pmid = item.get("pmid")
            title_zh = item.get("title_zh", "").strip()

            if pmid and title_zh and pmid in pmid_to_paper:
                # 更新数据库
                paper = pmid_to_paper[pmid]
                paper.title_zh = title_zh
                db.add(paper)
                result_map[pmid] = title_zh

        await db.commit()
        logger.info(f"Successfully translated and cached {len(result_map)} titles")

        return result_map

    async def translate_titles_for_journals(
        self,
        article_ids: List[int],
        db: AsyncSession
    ) -> Dict[int, str]:
        """
        批量翻译期刊文章标题（journal_articles表）

        Args:
            article_ids: 文章ID列表（最多50个）
            db: 数据库session

        Returns:
            {article_id: title_zh} 映射
        """
        if not article_ids or len(article_ids) == 0:
            return {}

        # 限制批量大小
        article_ids = article_ids[:50]

        missing_title_zh = or_(
            JournalArticle.title_zh.is_(None),
            func.length(func.trim(JournalArticle.title_zh)) == 0,
        )

        # 查询未翻译的文章（包含 title_zh 为空字符串的脏数据）
        query = select(JournalArticle).where(
            JournalArticle.id.in_(article_ids),
            missing_title_zh,
        )
        result = await db.execute(query)
        articles = result.scalars().all()

        if not articles:
            logger.info(f"All {len(article_ids)} articles already translated (cache hit)")
            # 返回已缓存的翻译
            cached_query = select(JournalArticle.id, JournalArticle.title_zh).where(
                JournalArticle.id.in_(article_ids),
                JournalArticle.title_zh.is_not(None),
                func.length(func.trim(JournalArticle.title_zh)) > 0,
            )
            cached_result = await db.execute(cached_query)
            return {row.id: row.title_zh for row in cached_result}

        logger.info(f"Translating {len(articles)} articles (cache miss)")

        # 构造标题列表
        titles_to_translate = []
        id_to_article = {}
        for article in articles:
            if article.title and article.title.strip():
                titles_to_translate.append({
                    "index": len(titles_to_translate) + 1,
                    "id": article.id,
                    "title": article.title.strip()
                })
                id_to_article[article.id] = article

        if not titles_to_translate:
            return {}

        # 调用DeepSeek批量翻译
        try:
            translations = await self._call_deepseek_batch(titles_to_translate, id_field="id")
        except Exception as e:
            logger.error(f"DeepSeek translation failed: {e!r}")
            raise

        # 写回数据库
        result_map = {}
        for item in translations:
            article_id = item.get("id")
            title_zh = item.get("title_zh", "").strip()

            if article_id and title_zh and article_id in id_to_article:
                # 更新数据库
                article = id_to_article[article_id]
                article.title_zh = title_zh
                db.add(article)
                result_map[article_id] = title_zh

        await db.commit()
        logger.info(f"Successfully translated and cached {len(result_map)} article titles")

        return result_map

    async def translate_titles_for_arxiv(
        self,
        article_ids: List[int],
        db: AsyncSession,
    ) -> Dict[int, str]:
        """
        批量翻译预印本文章标题（arxiv_articles表）

        Args:
            article_ids: 文章ID列表（最多50个）
            db: 数据库session

        Returns:
            {article_id: title_zh} 映射
        """
        if not article_ids or len(article_ids) == 0:
            return {}

        # 限制批量大小
        article_ids = article_ids[:50]

        missing_title_zh = or_(
            ArxivArticle.title_zh.is_(None),
            func.length(func.trim(ArxivArticle.title_zh)) == 0,
        )

        # 查询未翻译的文章（包含 title_zh 为空字符串的脏数据）
        query = select(ArxivArticle).where(
            ArxivArticle.id.in_(article_ids),
            missing_title_zh,
        )
        result = await db.execute(query)
        articles = result.scalars().all()

        if not articles:
            logger.info(
                "All %d arxiv_articles already translated (cache hit)",
                len(article_ids),
            )
            cached_query = select(ArxivArticle.id, ArxivArticle.title_zh).where(
                ArxivArticle.id.in_(article_ids),
                ArxivArticle.title_zh.is_not(None),
                func.length(func.trim(ArxivArticle.title_zh)) > 0,
            )
            cached_result = await db.execute(cached_query)
            return {row.id: row.title_zh for row in cached_result}

        logger.info("Translating %d arxiv_articles (cache miss)", len(articles))

        titles_to_translate = []
        id_to_article = {}
        for article in articles:
            if article.title and article.title.strip():
                titles_to_translate.append(
                    {
                        "index": len(titles_to_translate) + 1,
                        "id": int(article.id),
                        "title": article.title.strip(),
                    }
                )
                id_to_article[int(article.id)] = article

        if not titles_to_translate:
            return {}

        try:
            translations = await self._call_deepseek_batch(
                titles_to_translate,
                id_field="id",
            )
        except Exception as e:
            logger.error(f"DeepSeek translation failed: {e!r}")
            raise

        result_map: Dict[int, str] = {}
        for item in translations:
            article_id = item.get("id")
            title_zh = item.get("title_zh", "").strip()

            if article_id and title_zh and int(article_id) in id_to_article:
                article = id_to_article[int(article_id)]
                article.title_zh = title_zh
                db.add(article)
                result_map[int(article_id)] = title_zh

        await db.commit()
        logger.info("Successfully translated and cached %d arxiv titles", len(result_map))

        return result_map

    async def translate_abstract(
        self,
        identifier: str,
        abstract: str,
        db: AsyncSession,
        source_type: str = "literature"  # "literature" or "journal"
    ) -> str:
        """
        翻译单篇文献摘要（按需翻译，带数据库缓存）

        Args:
            identifier: PMID（literature）或 article_id（journal）
            abstract: 英文摘要
            db: 数据库session
            source_type: "literature" 或 "journal"

        Returns:
            中文摘要
        """
        if not abstract or not abstract.strip():
            return ""

        # 先检查缓存
        if source_type == "literature":
            query = select(Literature.abstract_zh).where(
                Literature.pmid == identifier,
                Literature.abstract_zh.is_not(None)
            )
            result = await db.execute(query)
            cached = result.scalar_one_or_none()

            if cached:
                logger.info(f"Abstract translation cache hit for PMID {identifier}")
                return cached

            # 获取完整记录以便更新
            paper_query = select(Literature).where(Literature.pmid == identifier)
            paper_result = await db.execute(paper_query)
            paper = paper_result.scalar_one_or_none()

            if not paper:
                raise ValueError(f"Literature with PMID {identifier} not found")

        else:  # journal
            try:
                article_id = int(identifier)
            except ValueError:
                raise ValueError(f"Invalid article_id: {identifier}")

            query = select(JournalArticle.abstract_zh).where(
                JournalArticle.id == article_id,
                JournalArticle.abstract_zh.is_not(None)
            )
            result = await db.execute(query)
            cached = result.scalar_one_or_none()

            if cached:
                logger.info(f"Abstract translation cache hit for article {article_id}")
                return cached

            # 获取完整记录以便更新
            article_query = select(JournalArticle).where(JournalArticle.id == article_id)
            article_result = await db.execute(article_query)
            paper = article_result.scalar_one_or_none()

            if not paper:
                raise ValueError(f"Article with ID {article_id} not found")

        # 调用DeepSeek翻译
        logger.info(f"Translating abstract for {source_type} {identifier}")
        abstract_zh = await self._call_deepseek_single(abstract)

        # 写入数据库缓存
        paper.abstract_zh = abstract_zh
        db.add(paper)
        await db.commit()

        logger.info(f"Successfully translated and cached abstract for {source_type} {identifier}")
        return abstract_zh

    async def _call_deepseek_single(self, text: str) -> str:
        """
        调用DeepSeek API翻译单个摘要

        Args:
            text: 英文摘要

        Returns:
            中文摘要
        """
        prompt = f"""将以下英文文献摘要翻译为中文。

要求：
1. 保持学术性和专业性
2. 专业术语使用标准中文翻译
3. 保持原文的段落结构
4. 准确传达原文含义

英文摘要：
{text}

请输出中文翻译（纯文本，不要JSON格式）："""

        # 调用DeepSeek API
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.1,
                        "max_tokens": 2000,
                        "thinking": THINKING_DISABLED,
                    }
                )
                response.raise_for_status()

                content = response.json()["choices"][0]["message"]["content"]
                return content.strip()

            except httpx.HTTPStatusError as e:
                logger.error(f"DeepSeek API error: {e.response.status_code} - {e.response.text}")
                raise
            except Exception as e:
                logger.error(f"Translation error: {e!r}")
                raise

    async def _call_deepseek_batch(
        self,
        titles: List[Dict],
        id_field: str = "pmid"
    ) -> List[Dict]:
        """
        调用DeepSeek API批量翻译标题

        Args:
            titles: [{"index": 1, "pmid"/"id": "...", "title": "..."}]
            id_field: 标识字段名（"pmid" 或 "id"）

        Returns:
            [{"pmid"/"id": "...", "title_zh": "..."}]
        """
        # 构造prompt
        titles_text = "\n".join([
            f"{item['index']}. {item['title']}"
            for item in titles
        ])

        prompt = f"""将以下{len(titles)}篇英文文献标题翻译为中文。

要求：
1. 保持学术性和专业性
2. 专业术语使用标准中文翻译（例如：ACL→前交叉韧带，HRV→心率变异性）
3. 简洁准确，避免冗余

输入标题：
{titles_text}

输出JSON数组格式（严格遵守）：
[
  {{"index": 1, "title_zh": "中文翻译"}},
  {{"index": 2, "title_zh": "中文翻译"}},
  ...
]

请输出JSON："""

        # 调用DeepSeek API
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.1,  # 低温度保证一致性
                        "max_tokens": 2000,
                        "response_format": {"type": "json_object"},
                        "thinking": THINKING_DISABLED,
                    }
                )
                response.raise_for_status()

                content = response.json()["choices"][0]["message"]["content"]

                # 解析JSON
                text = content.strip()
                if text.startswith("```"):
                    text = text.replace("```json", "").replace("```", "").strip()

                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    # 尝试提取数组
                    start = text.find("[")
                    end = text.rfind("]")
                    if start != -1 and end != -1 and end > start:
                        data = json.loads(text[start:end+1])
                    else:
                        raise ValueError(f"Invalid JSON response: {text[:200]}")

                # 如果data是字典且包含数组字段，提取数组
                if isinstance(data, dict):
                    for key in ["translations", "results", "data"]:
                        if key in data and isinstance(data[key], list):
                            data = data[key]
                            break

                if not isinstance(data, list):
                    raise ValueError(f"Expected array, got: {type(data)}")

                # 映射回原始ID
                result = []
                for item in data:
                    idx = item.get("index")
                    title_zh = item.get("title_zh", "").strip()

                    if idx and title_zh and 1 <= idx <= len(titles):
                        original = titles[idx - 1]
                        result.append({
                            id_field: original[id_field],
                            "title_zh": title_zh
                        })

                return result

            except httpx.HTTPStatusError as e:
                logger.error(f"DeepSeek API error: {e.response.status_code} - {e.response.text}")
                raise
            except Exception as e:
                logger.error(f"Translation error: {e!r}")
                raise
