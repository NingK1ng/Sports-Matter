"""
LLM关键词抽取服务（DeepSeek）
从摘要和标题中抽取关键词，用于知识图谱构建
"""
import asyncio
import os
import json
import logging
from typing import List, Dict, Optional
import httpx
from dotenv import load_dotenv
from pathlib import Path
import re
import sqlite3
import hashlib

from core.external.deepseek import DEEPSEEK_V4_FLASH_MODEL, THINKING_DISABLED, normalize_deepseek_model

load_dotenv()
logger = logging.getLogger(__name__)


class KeywordExtractor:
    """LLM关键词抽取器"""
    
    def __init__(self, api_key: str = None):
        """
        初始化抽取器
        
        Args:
            api_key: DeepSeek API密钥
        """
        # 尝试多种命名读取 .env（兼容 DS_* / DEEPSEEK_* / OPENAI_*）
        # 优先级：显式参数 > DS_* > DEEPSEEK_* > OPENAI_*
        self._ensure_dotenv_loaded()
        self.api_key = (
            api_key
            or os.getenv("DS_API_KEY")
            or os.getenv("DEEPSEEK_API_KEY")
            or os.getenv("OPENAI_API_KEY")  # DeepSeek 也支持 OpenAI 兼容
        )
        if not self.api_key:
            raise ValueError("未找到 DeepSeek API Key，请在 .env 设置 DS_API_KEY 或 DEEPSEEK_API_KEY（或 OPENAI_API_KEY）")
        
        raw_base = (
            os.getenv("DS_API_BASE")
            or os.getenv("DEEPSEEK_BASE_URL")
            or os.getenv("DEEPSEEK_API_BASE")
            or os.getenv("OPENAI_BASE_URL")
            or "https://api.deepseek.com"
        )
        self.base_url = self._normalize_api_base(raw_base)
        
        self.model = normalize_deepseek_model(
            os.getenv("DS_MODEL")
            or os.getenv("DEEPSEEK_MODEL")
            or os.getenv("OPENAI_MODEL")
            or DEEPSEEK_V4_FLASH_MODEL
        )
        logger.info(f"KeywordExtractor using model='{self.model}', base='{self.base_url}'")
        self._client: httpx.AsyncClient | None = None
        # 本地缓存（避免重复调用同一标题）
        self.cache_path = Path(os.getenv("KG_KW_CACHE_DB", Path(__file__).resolve().parents[3] / "data" / "kg_kw_cache.sqlite3"))
        self._ensure_cache_db()
        # 术语过滤集合（与构图阶段保持一致的最小必要集）
        self._stopwords = {
            "a","an","the","and","or","of","to","in","on","for","with","without","by","from","as","at","is","are","was","were","be","been","being",
            "this","that","these","those","it","its","their","his","her","we","you","they","our","my","your","not","no","yes",
            "what","why","how","current","future","past","new","novel","more","less","many","various","several","impact","effect","effects","role","study","studies",
            "research","analysis","methods","approach","approaches","factors","outcomes","population","participants","care","healthcare","professional","professionals","training",
            "patient","patients","male","female","men","women","home","case","cases","group","groups","trial","trials",
            "lesson","lessons","learned","insight","insights"
        }
        self._banned = {
            "systematic review","meta-analysis","scoping review","narrative review","review","randomized controlled trial","randomised controlled trial",
            "clinical trial","pilot study","case report","retrospective study","prospective study","cohort study","cross-sectional study","protocol",
            "case series","editorial","commentary","perspective","viewpoint","opinion","consensus statement","position statement","guideline","guidelines","letter"
        }

    def _ensure_dotenv_loaded(self) -> None:
        """
        确保在常见位置加载 .env（运行目录/项目根目录）
        """
        # 已在模块顶部 load_dotenv()，此处再次尝试项目根
        # 兼容从子目录/worker启动的情况
        try:
            repo_root = Path(__file__).resolve().parents[3]  # .../Sports-Matter/modules/...
            # 优先加载 .env.local（不覆盖已存在变量），再加载 .env
            load_dotenv(dotenv_path=repo_root / ".env.local", override=False)
            load_dotenv(dotenv_path=repo_root / ".env", override=False)
        except Exception:
            pass

    def _normalize_api_base(self, base: str) -> str:
        """
        将 base 规范化为包含 /v1 的前缀，避免重复斜杠
        """
        b = (base or "").strip().rstrip("/")
        if not b:
            b = "https://api.deepseek.com"
        # 如果末尾不包含 /v1，则补上
        if not b.endswith("/v1"):
            b = f"{b}/v1"
        return b

    # ---- 缓存工具 ----
    def _ensure_cache_db(self) -> None:
        try:
            if not self.cache_path.parent.exists():
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.cache_path)
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS cache (
                    k TEXT PRIMARY KEY,
                    v TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            conn.commit()
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _make_title_key(self, title: str) -> str:
        payload = {"model": self.model, "title": (title or "").strip()}
        s = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(s.encode("utf-8")).hexdigest()

    def _make_tiab_key(self, title: str, abstract: str | None) -> str:
        payload = {
            "model": self.model,
            "title": (title or "").strip(),
            "abstract": (abstract or "").strip(),
        }
        s = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(s.encode("utf-8")).hexdigest()

    def _cache_get(self, k: str) -> Optional[List[Dict]]:
        try:
            conn = sqlite3.connect(self.cache_path)
            cur = conn.cursor()
            cur.execute("SELECT v FROM cache WHERE k=?", (k,))
            row = cur.fetchone()
            if not row:
                return None
            return json.loads(row[0])
        except Exception:
            return None
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _cache_set(self, k: str, v: List[Dict]) -> None:
        try:
            from time import time
            now = int(time())
            conn = sqlite3.connect(self.cache_path)
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO cache(k,v,created_at,updated_at) VALUES(?,?,?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v, updated_at=excluded.updated_at",
                (k, json.dumps(v, ensure_ascii=False), now, now),
            )
            conn.commit()
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass
    
    def _normalize_term(self, term: str) -> str:
        t = (term or "").strip().lower()
        t = re.sub(r"[_\-/]+", " ", t)
        t = re.sub(r"[^\w\s\+]+", "", t)
        t = re.sub(r"\s+", " ", t).strip()
        synonyms = {
            "acl": "anterior cruciate ligament",
            "vo2 max": "vo2max",
            "hrv": "heart rate variability",
            "emg": "electromyography",
            "rct": "randomized controlled trial",
        }
        return synonyms.get(t, t)

    def _is_valid_term(self, t: str) -> bool:
        if not t or len(t) < 3:
            return False
        if t.isdigit():
            return False
        if t in self._stopwords:
            return False
        for banned in self._banned:
            if t == banned or banned in t:
                return False
        if t in {"and","or","the","of","to","in","on","for","with","without","by"}:
            return False
        return True

    def _build_tiab_prompt(self, title: str, abstract: str | None) -> str:
        """
        TIAB（title+abstract）关键词抽取 prompt：只允许输出 JSON 数组。
        """
        abs_text = (abstract or "").strip()
        return (
            "Extract 8-12 key academic terms from the following scientific paper.\n"
            "- Use ONLY information from Title + Abstract.\n"
            "- Terms must be specific noun phrases (2-6 words), not generic words.\n"
            "- Avoid generic terms like: study, effect, results, analysis, training, participants.\n"
            "- Output JSON array only. Each item: {\"term\": string, \"score\": number 0-1}.\n"
            "\n"
            f"Title: {title.strip()}\n"
            f"Abstract: {abs_text}\n"
        )

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            limits = httpx.Limits(max_keepalive_connections=50, max_connections=100)
            self._client = httpx.AsyncClient(timeout=120.0, limits=limits)
        return self._client

    async def _call_llm(self, prompt: str) -> str:
        max_retries = 5
        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                client = self._get_client()
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.2,
                        "max_tokens": 500,
                        "thinking": THINKING_DISABLED,
                    },
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
            except httpx.HTTPStatusError as e:
                last_exc = e
                if attempt < max_retries - 1 and e.response is not None and e.response.status_code in {429, 500, 502, 503, 504}:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                raise
            except httpx.RequestError as e:
                last_exc = e
                if attempt < max_retries - 1:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                raise
        raise last_exc or RuntimeError("LLM request failed")

    def _parse_llm_json_array(self, content: str) -> list[dict]:
        text = (content or "").replace("```json", "").replace("```", "").strip()
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
        except Exception:
            pass
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            data = json.loads(text[start : end + 1])
            if isinstance(data, list):
                return data
        raise ValueError("LLM response is not a JSON array")

    async def extract_keywords(
        self,
        title: str,
        abstract: Optional[str] = None,
    ) -> List[Dict[str, any]]:
        """
        LLM-only：从 TIAB（title + abstract）抽取关键词（不使用任何规则fallback）。
        """
        if not title or len(title) < 5:
            return []

        ck = self._make_tiab_key(title, abstract)
        cached = self._cache_get(ck)
        if cached:
            return cached[:15]

        prompt = self._build_tiab_prompt(title, abstract)
        content = await self._call_llm(prompt)

        kws = self._parse_llm_json_array(content)

        seen = set()
        result: list[dict] = []
        for kw in kws:
            if not isinstance(kw, dict):
                continue
            term = self._normalize_term(kw.get("term"))
            if not term or term in seen:
                continue
            if not self._is_valid_term(term):
                continue
            seen.add(term)
            try:
                score = float(kw.get("score", 0.8))
            except Exception:
                score = 0.8
            result.append({"term": term, "score": max(0.0, min(1.0, score)), "source": "llm_tiab"})
        result = result[:15]

        try:
            self._cache_set(ck, result)
        except Exception:
            pass
        return result
