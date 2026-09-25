import os
import json
import httpx
import sqlite3
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional

from core.external.deepseek import DEEPSEEK_V4_FLASH_MODEL, THINKING_DISABLED, normalize_deepseek_model


class LLMClusterer:
    def __init__(self, api_key: str | None = None, model: str | None = None, base_url: str | None = None, timeout: float = 120.0):
        self.api_key = api_key or os.getenv("DS_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("Missing DeepSeek API key")
        self.base_url = self._normalize_api_base(base_url or os.getenv("DS_API_BASE") or os.getenv("DEEPSEEK_BASE_URL") or os.getenv("OPENAI_BASE_URL") or "https://api.deepseek.com")
        self.model = normalize_deepseek_model(model or os.getenv("DS_MODEL") or DEEPSEEK_V4_FLASH_MODEL)
        self.timeout = timeout
        # 模型版本标识（用于缓存失效）
        self.model_version = os.getenv("DS_MODEL_VERSION", "v1.0")
        # 输出控制：避免社区命名输出过长导致成本飙升/截断
        try:
            self.max_tokens = int(os.getenv("KG_CLUSTER_MAX_TOKENS", "400"))
        except Exception:
            self.max_tokens = 400
        self.max_tokens = max(120, min(800, self.max_tokens))
        try:
            self.rationale_max_chars = int(os.getenv("KG_CLUSTER_RATIONALE_MAX_CHARS", "200"))
        except Exception:
            self.rationale_max_chars = 200
        self.rationale_max_chars = max(0, self.rationale_max_chars)
        try:
            self.candidates_max = int(os.getenv("KG_CLUSTER_CANDIDATES_MAX", "8"))
        except Exception:
            self.candidates_max = 8
        self.candidates_max = max(0, min(8, self.candidates_max))
        try:
            self.evidence_max = int(os.getenv("KG_CLUSTER_EVIDENCE_MAX", "8"))
        except Exception:
            self.evidence_max = 8
        self.evidence_max = max(0, min(8, self.evidence_max))
        # cache db
        self.cache_path = Path(os.getenv("KG_LLM_CACHE_DB", Path(__file__).resolve().parents[3] / "data" / "kg_llm_cache.sqlite3"))
        self._ensure_cache_db()

    def _normalize_api_base(self, base: str) -> str:
        b = (base or "").strip().rstrip("/")
        if not b:
            b = "https://api.deepseek.com"
        if not b.endswith("/v1"):
            b = f"{b}/v1"
        return b

    # ---------------- Cache helpers -----------------
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

    def _make_cache_key(self, top_terms: List[Dict[str, Any]], sample_titles: List[str], window: str, as_of: str, profile: str) -> str:
        payload = {
            "model": self.model,
            "model_version": self.model_version,  # 新增：模型版本
            "window": window,
            "as_of": as_of,
            "profile": profile,
            "top_terms": top_terms,
            "sample_titles": sample_titles,
        }
        s = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(s.encode("utf-8")).hexdigest()

    def _cache_get(self, k: str) -> Optional[Dict[str, Any]]:
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

    def _cache_set(self, k: str, v: Dict[str, Any]) -> None:
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

    def _build_system_prompt(self, profile: str = "sports") -> str:
        if profile == "general_top":
            return (
                "你是一名跨学科的学术术语归纳专家（综合顶刊，如 Nature/Science/Cell 等）。"
                "接收一个社区的关键词候选与代表论文标题，产出该社区的主学术短语标签和候选同义术语。"
                "要求：输出的每个标签必须是严谨的学术可指称对象（方法/技术、测量指标、模型/通路、材料/器件、疾病/病理、实验范式等）。"
                "避免输出研究类型/综述/试验设计、泛化词（如 benefits、effects、lessons、insights）、"
                "群体/性别、场景词、连词/介词、空泛形容词。仅输出JSON，不要解释。"
            )
        return (
            "你是一名运动科学与运动医学领域的术语归纳专家。"
            "接收一个社区的关键词候选与代表论文标题，产出该社区的主学术短语标签和候选同义术语。"
            "要求：输出的每个标签必须是学术可指称的对象（解剖结构、病理/病症、测量指标、方法/技术、干预/康复方案、"
            "生物力学/生理指标、测试量表、影像/诊断项）。禁止输出研究类型/综述/试验设计、泛化词（如benefits、effects、lessons、insights等）、"
            "群体/性别、场景词（home、group）、连词/介词、空泛形容词（novel、new等）。仅输出最终JSON，不要输出解释性文本。"
        )

    def _build_user_prompt(self, top_terms: List[Dict[str, Any]], sample_titles: List[str], window: str, as_of: str, profile: str = "sports") -> str:
        schema = {
            "type": "object",
            "properties": {
                "insufficient_signal": {"type": "boolean"},
                "main_label": {"type": "string"},
                "candidates": {"type": "array", "items": {"type": "string"}, "minItems": 0, "maxItems": self.candidates_max},
                "rationale": {"type": "string"},
                "evidence_map": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "term": {"type": "string"},
                            "relation": {"type": "string", "enum": [
                                "synonym","alias","subtype","measurement","outcome","technique","structure","pathology","biomechanics","physiology","diagnosis","scale","other"
                            ]},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1}
                        },
                        "required": ["term","relation","confidence"]
                    },
                    "minItems": 0, "maxItems": self.evidence_max
                }
            },
            "required": ["insufficient_signal","main_label","candidates","rationale","evidence_map"],
            "additionalProperties": False
        }
        # 将动态输入压缩成 TSV / 行文本，显著减少 prompt tokens（降低输入成本）
        term_rows: list[str] = []
        for kw in (top_terms or []):
            if not isinstance(kw, dict):
                continue
            term = str(kw.get("term", "") or "").strip()
            if not term:
                continue
            term = term.replace("\t", " ").replace("\r", " ").replace("\n", " ")
            df = kw.get("df", "")
            tfidf = kw.get("tfidf", "")
            term_rows.append(f"{term}\t{df}\t{tfidf}")
        top_terms_tsv = "\n".join(term_rows)

        title_rows: list[str] = []
        for t in (sample_titles or []):
            s = str(t or "").strip()
            if not s:
                continue
            s = s.replace("\r", " ").replace("\n", " ").strip()
            title_rows.append(s)
        titles_text = "\n".join(title_rows)

        # 为提升 DeepSeek prompt cache 命中率：先输出“长且稳定”的规则+schema，再附上动态输入（top_terms / titles）。
        # DeepSeek 缓存以 prefix block 计费；把动态内容放后面可显著降低输入成本。
        return (
            "请对输入社区进行术语聚类与命名，并严格输出 JSON 对象（不要 Markdown/解释）。\n"
            "输出规则：\n"
            "- main_label：学术短语（2-5词为宜），必须可指称（方法/技术/指标/病理/结构/模型等）；不得包含研究类型/综述/试验设计/泛化词/群体场景词。\n"
            f"- candidates：同义/近义术语，最多 {self.candidates_max} 个。\n"
            f"- rationale：必须极短（不超过 {self.rationale_max_chars} 字，1句即可）。\n"
            f"- evidence_map：可为空，最多 {self.evidence_max} 条。\n"
            "若证据不足：insufficient_signal=true，main_label 仍需给出（可为空），candidates ≤2。\n"
            f"JSON Schema: {json.dumps(schema, ensure_ascii=False)}\n"
            "\n"
            "INPUT:\n"
            f"profile: {profile}\n"
            f"window: {window}\n"
            f"as_of: {as_of}\n"
            "top_terms_tsv (term\\tdf\\ttfidf):\n"
            f"{top_terms_tsv}\n"
            "sample_titles (one per line):\n"
            f"{titles_text}\n"
        )

    def _normalize_result(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """强制输出约束：压缩rationale并限制列表长度，避免成本与截断风险。"""
        if not isinstance(data, dict):
            data = {}

        insufficient_signal = bool(data.get("insufficient_signal", False))
        main_label = (data.get("main_label") or "").strip()

        candidates_raw = data.get("candidates") or []
        candidates: list[str] = []
        if isinstance(candidates_raw, list):
            for item in candidates_raw:
                s = (str(item) if item is not None else "").strip()
                if s:
                    candidates.append(s)
        candidates = candidates[: self.candidates_max]

        rationale = (data.get("rationale") or "").strip()
        if self.rationale_max_chars > 0 and len(rationale) > self.rationale_max_chars:
            rationale = rationale[: self.rationale_max_chars].strip()

        evidence_raw = data.get("evidence_map") or []
        evidence_map: list[dict] = []
        if isinstance(evidence_raw, list):
            for item in evidence_raw:
                if not isinstance(item, dict):
                    continue
                term = (item.get("term") or "").strip()
                relation = (item.get("relation") or "").strip()
                try:
                    confidence = float(item.get("confidence", 0.0))
                except Exception:
                    confidence = 0.0
                if not term or not relation:
                    continue
                evidence_map.append({"term": term, "relation": relation, "confidence": max(0.0, min(1.0, confidence))})
        evidence_map = evidence_map[: self.evidence_max]

        return {
            "insufficient_signal": insufficient_signal,
            "main_label": main_label,
            "candidates": candidates,
            "rationale": rationale,
            "evidence_map": evidence_map,
        }

    async def cluster_for_community(self, top_terms: List[Dict[str, Any]], sample_titles: List[str], window: str, as_of: str, profile: str = "sports") -> Dict[str, Any]:
        if not top_terms:
            return {"insufficient_signal": True, "main_label": "", "candidates": [], "rationale": "no terms", "evidence_map": []}
        # cache check
        ck = self._make_cache_key(top_terms, sample_titles, window, as_of, profile)
        cached = self._cache_get(ck)
        if cached:
            return self._normalize_result(cached)
        system = self._build_system_prompt(profile)
        user = self._build_user_prompt(top_terms, sample_titles, window, as_of, profile)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user}
                    ],
                    "temperature": 0.2,
                    "response_format": {"type": "json_object"},
                    "max_tokens": self.max_tokens,
                    "thinking": THINKING_DISABLED,
                }
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            text = content.strip()
            if text.startswith("```"):
                text = text.replace("```json", "").replace("```", "").strip()
            try:
                data = json.loads(text)
            except Exception:
                # 尝试提取第一个大括号JSON
                start = text.find("{")
                end = text.rfind("}")
                if start != -1 and end != -1 and end > start:
                    data = json.loads(text[start:end+1])
                else:
                    raise
            data = self._normalize_result(data)
            # save cache
            try:
                self._cache_set(ck, data)
            except Exception:
                pass
            return data
