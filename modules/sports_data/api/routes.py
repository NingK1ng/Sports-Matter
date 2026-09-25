"""Sports Data API routes

V1: dataset search via Tavily Search API (English-only keywords).
"""
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
import asyncio
import hashlib
import io
import json
import os
import tempfile
import time
import uuid
import zipfile

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File

from core.config import settings
from modules.literature_pool.api.auth import require_weekly_quota

router = APIRouter(prefix="/sports-data", tags=["sports-data"])

# Lazy import Tavily to avoid import errors when library not installed
try:
    from tavily import TavilyClient
except Exception:  # pragma: no cover - tavily may not be installed in some envs
    TavilyClient = None  # type: ignore

try:
    from core.cache import cache_get, cache_set
except Exception:  # pragma: no cover - cache optional in some envs
    cache_get = None  # type: ignore[assignment]
    cache_set = None  # type: ignore[assignment]


_TAVILY_CACHE_VERSION = "v2"
_TAVILY_CACHE_TTL_SECONDS = 14 * 24 * 60 * 60
_TAVILY_MAX_RESULTS = 20


def _normalize_query(q: str) -> str:
    return " ".join((q or "").strip().split())


def _tavily_cache_key(mode: str, query: str) -> str:
    q_norm = _normalize_query(query).lower()
    digest = hashlib.md5(q_norm.encode("utf-8")).hexdigest()
    return f"api:sports_data:tavily:{_TAVILY_CACHE_VERSION}:{mode}:{digest}"


async def _tavily_cache_get(key: str) -> Optional[List[Dict[str, Any]]]:
    if cache_get is None:
        return None
    try:
        cached = await cache_get(key)
    except Exception:
        return None
    if isinstance(cached, list):
        return cached  # type: ignore[return-value]
    return None


async def _tavily_cache_set(key: str, value: List[Dict[str, Any]]) -> None:
    if cache_set is None:
        return
    try:
        await cache_set(key, value, ttl=_TAVILY_CACHE_TTL_SECONDS)
    except Exception:
        return


def _canonicalize_url(url: str) -> str:
    parsed = urlparse(url)
    scheme = (parsed.scheme or "https").lower()
    netloc = (parsed.netloc or "").lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path or ""
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return f"{scheme}://{netloc}{path}"


def _tavily_max_results(limit: int) -> int:
    try:
        limit_int = int(limit)
    except Exception:
        limit_int = 10
    if limit_int <= 0:
        limit_int = 10
    return min(_TAVILY_MAX_RESULTS, max(limit_int, min(_TAVILY_MAX_RESULTS, limit_int * 2)))


def _get_tavily_client() -> "TavilyClient":
    """Create a Tavily client or raise 500 if not configured.

    We keep this very small on purpose; V1 only needs basic search.
    """
    if TavilyClient is None:
        raise HTTPException(status_code=500, detail="Tavily client library is not installed")

    api_key = getattr(settings, "tavily_api_key", None)
    if not api_key:
        raise HTTPException(status_code=500, detail="TAVILY_API_KEY is not configured on the server")

    # TavilyClient accepts the API key as the first positional argument
    return TavilyClient(api_key)  # type: ignore[arg-type]


_DATASET_DOMAINS: List[str] = [
    # General scientific/open data platforms
    "physionet.org",
    "figshare.com",
    "osf.io",
    "zenodo.org",
    "kaggle.com",
    "openneuro.org",
    "datadryad.org",
    "data.mendeley.com",
    "dataverse.harvard.edu",
    "openml.org",
    "registry.opendata.aws",
    "data.world",
    # Sports-specific open data portals (best-effort, may be sparse)
    "statsbomb.com",
    "openpowerlifting.org",
    # Code / mixed repos that经常托管数据或分析脚本
    "github.com",
]


_CODE_DOMAINS: List[str] = [
    "github.com",
    "gitlab.com",
    "bitbucket.org",
    "huggingface.co",
    "paperswithcode.com",
    "osf.io",
]


def _infer_code_kind(source: str, url: str) -> str:
    """Best-effort classification of code search results.

    Returns one of "code", "model" or "project" for UI badges.
    """
    src = (source or "").lower()
    href = (url or "").lower()

    if "huggingface.co" in src or "huggingface.co" in href:
        return "model"
    if "paperswithcode.com" in src or "paperswithcode.com" in href:
        return "project"
    if "github.com" in src or "gitlab.com" in src or "bitbucket.org" in src:
        return "code"
    return "project"


_REPORT_DOMAINS: List[str] = [
    "github.com",
    "github.io",
    "shinyapps.io",
    "rpubs.com",
    "streamlit.app",
    "figshare.com",
    "osf.io",
    "kaggle.com",
    "public.tableau.com",
    "lookerstudio.google.com",
    "app.powerbi.com",
    "observablehq.com",
]


def _infer_report_kind(source: str, url: str) -> str:
    """Classify report/dashboard style resources for UI badges."""
    src = (source or "").lower()
    href = (url or "").lower()

    if "tableau" in src or "shiny" in href or "dashboard" in href:
        return "dashboard"
    if href.endswith(".rmd") or "rmarkdown" in href or href.endswith(".ipynb"):
        return "template"
    return "report"


_SCALE_DOMAINS: List[str] = [
    "ncbi.nlm.nih.gov",  # PubMed 量表原始论文
    "osf.io",
    "figshare.com",
    "who.int",
    "nih.gov",
]


def _infer_scale_kind(source: str, url: str, title: str) -> str:
    """Classify instruments into scale vs questionnaire."""
    text = f"{source} {url} {title}".lower()
    if "questionnaire" in text or "survey" in text:
        return "questionnaire"
    return "scale"


@router.get("/datasets")
async def search_datasets(
    q: str = Query(..., description="English keywords describing the sports dataset you are looking for"),
    limit: int = Query(10, ge=1, le=15, description="Maximum number of results to return (5/10/15 recommended)"),
    _user=Depends(require_weekly_quota("sports_data_search", 5)),
):
    """Search for public sports-related datasets using Tavily.

    V1 behaviour:
    - English-only query (frontend will提示这一点)。
    - Restrict search to a curated list of open data & code platforms via include_domains.
    - Use basic search depth to keep costs predictable.
    - Return a simplified JSON payload for the frontend to render as cards.
    """
    q_clean = _normalize_query(q)
    if not q_clean:
        raise HTTPException(status_code=400, detail="Query must not be empty")

    cache_key = _tavily_cache_key("datasets", q_clean)
    cached = await _tavily_cache_get(cache_key)
    if cached is not None:
        return {
            "query": q_clean,
            "total": min(len(cached), limit),
            "results": cached[:limit],
        }

    client = _get_tavily_client()

    try:
        q_lower = q_clean.lower()
        extras: List[str] = []
        if "dataset" not in q_lower and "data" not in q_lower:
            extras.append("dataset")
        extras.append("open data")
        if not any(
            kw in q_lower
            for kw in (
                "sport",
                "athlet",
                "exercise",
                "physical activity",
                "training",
            )
        ):
            extras.append("sport")
        effective_query = f"{q_clean} {' '.join(extras)}".strip()
        tavily_resp = await asyncio.to_thread(
            client.search,
            query=effective_query,
            search_depth="basic",
            max_results=_tavily_max_results(limit),
            include_domains=_DATASET_DOMAINS,
            topic="general",
            include_answer=False,
        )
    except Exception as e:  # pragma: no cover - network / external service
        raise HTTPException(status_code=502, detail=f"Tavily search failed: {type(e).__name__}: {e}")

    # Tavily returns a dict-like structure; we defensively read from it.
    raw_results = tavily_resp.get("results") if isinstance(tavily_resp, dict) else None
    if not isinstance(raw_results, list):
        raw_results = []

    items: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for r in raw_results:
        if not isinstance(r, dict):
            continue
        url = (r.get("url") or "").strip()
        if not url:
            continue
        if not (url.startswith("http://") or url.startswith("https://")):
            continue
        canonical = _canonicalize_url(url)
        if canonical in seen:
            continue
        seen.add(canonical)
        title = (r.get("title") or "").strip() or url
        snippet = (r.get("content") or r.get("snippet") or "").strip()
        parsed = urlparse(url)
        source = parsed.netloc or ""
        items.append(
            {
                "title": title,
                "url": url,
                "snippet": snippet,
                "source": source,
            }
        )

    await _tavily_cache_set(cache_key, items)

    return {
        "query": q_clean,
        "total": min(len(items), limit),
        "results": items[:limit],
    }


async def _fetch_markdown_via_mineru(file: UploadFile) -> str:
    token = getattr(settings, "mineru_api_token", None)
    if not token:
        raise HTTPException(status_code=500, detail="MINERU_API_TOKEN is not configured on the server")

    filename = file.filename or "document.pdf"
    try:
        content = await file.read()
    except Exception as e:  # pragma: no cover - UploadFile edge cases
        raise HTTPException(status_code=400, detail=f"Failed to read uploaded file: {type(e).__name__}: {e}")

    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        batch_payload = {
            "files": [
                {"name": filename, "data_id": str(uuid.uuid4())},
            ],
            "model_version": "vlm",
        }
        try:
            batch_resp = await client.post(
                "https://mineru.net/api/v4/file-urls/batch",
                headers=headers,
                json=batch_payload,
            )
        except httpx.HTTPError as e:  # pragma: no cover - network
            raise HTTPException(status_code=502, detail=f"MinerU batch request failed: {type(e).__name__}: {e}")

        try:
            batch_data = batch_resp.json()
        except Exception as e:  # pragma: no cover - unexpected payload
            raise HTTPException(status_code=502, detail=f"MinerU batch response is not JSON: {type(e).__name__}: {e}")

        if batch_data.get("code") != 0:
            msg = batch_data.get("msg") or "MinerU returned non-zero code"
            raise HTTPException(status_code=502, detail=f"MinerU batch error: {msg}")

        inner = batch_data.get("data") or {}
        batch_id = inner.get("batch_id")
        file_urls = inner.get("file_urls") or []
        if not batch_id or not file_urls:
            raise HTTPException(status_code=502, detail="MinerU batch response missing batch_id or file_urls")

        upload_url = str(file_urls[0])

        try:
            upload_resp = await client.put(
                upload_url,
                content=content,
            )
        except httpx.HTTPError as e:  # pragma: no cover - network
            raise HTTPException(status_code=502, detail=f"MinerU upload failed: {type(e).__name__}: {e}")

        if upload_resp.status_code >= 400:
            snippet = ""
            try:
                snippet = (upload_resp.text or "")[:200]
            except Exception:
                snippet = ""
            raise HTTPException(
                status_code=502,
                detail=f"MinerU upload failed with HTTP {upload_resp.status_code}: {snippet}",
            )

        extract_url = f"https://mineru.net/api/v4/extract-results/batch/{batch_id}"
        max_wait = 120.0
        poll_interval = 3.0
        start = time.time()
        full_zip_url: Optional[str] = None
        last_state: Optional[str] = None

        while time.time() - start < max_wait:
            try:
                status_resp = await client.get(
                    extract_url,
                    headers={"Authorization": f"Bearer {token}"},
                )
            except httpx.HTTPError as e:  # pragma: no cover - network
                raise HTTPException(status_code=502, detail=f"MinerU status request failed: {type(e).__name__}: {e}")

            try:
                status_data = status_resp.json()
            except Exception as e:  # pragma: no cover - unexpected payload
                raise HTTPException(status_code=502, detail=f"MinerU status response is not JSON: {type(e).__name__}: {e}")

            if status_data.get("code") != 0:
                msg = status_data.get("msg") or "MinerU returned non-zero code"
                raise HTTPException(status_code=502, detail=f"MinerU status error: {msg}")

            data_block = status_data.get("data") or {}
            results = data_block.get("extract_result") or []
            if results:
                item = results[0]
                state = str(item.get("state") or "")
                last_state = state
                if state == "done":
                    full_zip_url = item.get("full_zip_url")
                    break
                if state == "failed":
                    err_msg = item.get("err_msg") or "MinerU extraction failed"
                    raise HTTPException(status_code=502, detail=err_msg)

            await asyncio.sleep(poll_interval)

        if not full_zip_url:
            raise HTTPException(
                status_code=504,
                detail=f"MinerU extraction timeout; last state={last_state!r}",
            )

        try:
            zip_resp = await client.get(full_zip_url)
        except httpx.HTTPError as e:  # pragma: no cover - network
            raise HTTPException(status_code=502, detail=f"Failed to download MinerU result: {type(e).__name__}: {e}")

        if zip_resp.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"Downloading MinerU result failed with HTTP {zip_resp.status_code}")

        zip_bytes = zip_resp.content

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            md_name = None
            for name in names:
                lower = name.lower()
                if lower.endswith(".md") and "markdown" in lower:
                    md_name = name
                    break
            if md_name is None:
                for name in names:
                    if name.lower().endswith(".md"):
                        md_name = name
                        break
            if md_name is None:
                raise HTTPException(status_code=502, detail="MinerU result archive does not contain a markdown (.md) file")

            raw = zf.read(md_name)
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("utf-8", errors="ignore")
    except HTTPException:
        raise
    except Exception as e:  # pragma: no cover - corrupt archive
        raise HTTPException(status_code=502, detail=f"Failed to read MinerU result archive: {type(e).__name__}: {e}")

    return text


async def _fetch_markdown_via_pymupdf(file: UploadFile) -> str:
    try:
        import fitz  # type: ignore[import]
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Direct PDF mode requires the 'pymupdf' package (import fitz failed: {type(e).__name__}: {e}).",
        )

    try:
        content = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read uploaded file: {type(e).__name__}: {e}")

    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        doc = fitz.open(tmp_path)
        lines: List[str] = []
        for page_num in range(doc.page_count):
            page = doc.load_page(page_num)
            text = page.get_text()
            lines.append(f"## Page {page_num + 1}")
            if text and text.strip():
                lines.append(text.strip())
            lines.append("")
        doc.close()

        markdown_text = "\n".join(lines).strip()
        if not markdown_text:
            raise HTTPException(status_code=502, detail="PyMuPDF did not return any text from the PDF")
        return markdown_text
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"PyMuPDF failed to extract text from PDF: {type(e).__name__}: {e}")
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _extract_abstract_from_markdown(markdown_text: str) -> str:
    """Best-effort extraction of an abstract/summary section from markdown.

    We look for headings like "Abstract" / "Summary" / "摘要" and take the
    lines until the next heading. If none found, fall back to the first ~40
    lines (or ~1500 characters) as a pseudo-abstract.
    """
    lines = markdown_text.splitlines()
    abstract_lines: List[str] = []
    start_idx: Optional[int] = None

    for idx, line in enumerate(lines):
        stripped = line.strip().lstrip("#").strip().lower()
        if stripped in ("abstract", "summary", "摘要"):
            start_idx = idx + 1
            break

    if start_idx is not None:
        for line in lines[start_idx:]:
            if line.strip().startswith("#"):
                break
            abstract_lines.append(line)
    else:
        for line in lines:
            if line.strip().startswith("#") and abstract_lines:
                break
            abstract_lines.append(line)
            if len(abstract_lines) >= 40:
                break

    abstract_text = "\n".join(abstract_lines).strip()
    if len(abstract_text) > 1500:
        abstract_text = abstract_text[:1500]
    return abstract_text


def _has_numeric_content(metrics: List[dict], tables: List[dict]) -> bool:
    """Check whether parsed metrics/tables contain any numeric signal."""

    def _value_has_digit(val: Any) -> bool:
        if isinstance(val, (int, float)):
            return True
        if isinstance(val, str):
            return any(ch.isdigit() for ch in val)
        return False

    for item in metrics:
        if not isinstance(item, dict):
            continue
        for key in ("value", "raw_text", "context", "name", "dimension", "category"):
            if _value_has_digit(item.get(key)):
                return True

    for tbl in tables:
        if not isinstance(tbl, dict):
            continue
        rows = tbl.get("rows")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            for val in row.values():
                if _value_has_digit(val):
                    return True
    return False


def _normalize_section(section: str) -> str:
    """Map free-text section label to abstract/methods/results buckets."""
    sec = (section or "").lower()
    if "abstract" in sec or "摘要" in sec or "summary" in sec:
        return "abstract"
    if "method" in sec or "方法" in sec or "materials" in sec:
        return "methods"
    if "result" in sec or "结果" in sec or "finding" in sec or "outcome" in sec:
        return "results"
    return "results"


def _infer_table_section(title: str) -> str:
    """Infer section group for LLM tables based on title text."""
    t = (title or "").lower()
    if "abstract" in t or "摘要" in t or "summary" in t:
        return "abstract"
    if "method" in t or "方法" in t or "materials" in t:
        return "methods"
    if "result" in t or "结果" in t or "finding" in t or "outcome" in t:
        return "results"
    return "results"


def _build_section_tables(metrics: List[dict], extra_tables: List[dict]) -> List[Dict[str, Any]]:
    """Construct 3 canonical tables (abstract/methods/results) from metrics."""
    columns = [
        {"id": "label", "label": "指标"},
        {"id": "value", "label": "数值"},
        {"id": "group_time", "label": "组别/时间点"},
        {"id": "section", "label": "章节"},
        {"id": "context", "label": "上下文"},
    ]
    rows_by_section: Dict[str, List[Dict[str, str]]] = {"abstract": [], "methods": [], "results": []}

    for m in metrics:
        if not isinstance(m, dict):
            continue
        sec_key = _normalize_section(str(m.get("section") or ""))
        label = m.get("name") or m.get("dimension") or m.get("category") or "-"
        value = " ".join([str(x) for x in [m.get("value"), m.get("unit")] if x]) or "-"
        group_time = " · ".join([str(x) for x in [m.get("group"), m.get("timepoint")] if x]) or "-"
        context = m.get("context") or m.get("raw_text") or ""
        rows_by_section.setdefault(sec_key, []).append(
            {
                "label": str(label),
                "value": str(value),
                "group_time": str(group_time),
                "section": m.get("section") or "",
                "context": str(context),
            }
        )

    titled = {
        "abstract": "摘要数值",
        "methods": "方法数值",
        "results": "结果数值",
    }

    canonical_tables: List[Dict[str, Any]] = []
    for key in ("abstract", "methods", "results"):
        canonical_tables.append(
            {
                "id": f"{key}-metrics",
                "title": titled[key],
                "description": "",
                "columns": columns,
                "rows": rows_by_section.get(key, []),
                "section_group": key,
            }
        )

    # Attach section grouping to LLM-provided tables and append
    processed_extra: List[Dict[str, Any]] = []
    for tbl in extra_tables:
        if not isinstance(tbl, dict):
            continue
        title = str(tbl.get("title") or "")
        tbl = dict(tbl)
        tbl["section_group"] = _infer_table_section(title)
        processed_extra.append(tbl)

    return canonical_tables + processed_extra


async def _rewind_upload_file(file: UploadFile) -> None:
    """Best-effort reset of UploadFile cursor for fallback extraction."""
    try:
        await file.seek(0)
    except Exception:
        try:
            file.file.seek(0)
        except Exception:
            pass


async def _extract_metrics_with_llm(markdown_text: str) -> dict:
    from core.external.deepseek import DEEPSEEK_V4_FLASH_MODEL, get_deepseek_client

    client = get_deepseek_client()

    system_prompt = (
        "你是一个专门为运动科学论文服务的定量数据抽取和解读助手。"
        "给你一篇论文的摘要和包含数字的正文内容，请从中抽取所有与研究主题清晰相关或对理解研究结果有直接支持作用的定量指标，"
        "并严格以 JSON 对象返回，不要输出任何多余的文字。"
        "JSON 顶层结构必须是 {\"metrics\": [...], \"summary\": \"...\", \"tables\": [...]}。"
        "metrics 是一个数组，其中每个元素是一个对象，包含但不限于以下字段："
        "value, unit, raw_text, section, category, name, dimension, group, timepoint, tags, context。"
        "当原文中存在按模型/组别/时间点排列的打分表或结果表（例如 mean±variance、mean±SD、均值 (方差) 形式的 3.96 ± 0.20、3.96 ± 0.20 (0.81) 等），"
        "你必须优先从这些表格中精确抄录每个模型/组别在各个指标上的原始数值，并放入 metrics 或 tables.rows 中，而不是用“Improved / Relatively good / Not specified”等文字评价去替代这些数字。"
        "你可以自定义 category/name/dimension/tags，不要局限在固定枚举；"
        "value 和 unit 必须来自原文；context 是包含该数值的原文句子或表格行。"
        "你必须优先根据摘要判断论文的大致研究主题，让自己先弄清楚这篇文章主要在回答什么问题，但不要仅仅按照摘要中的词语做机械过滤；"
        "summary 是一个不超过 300 字的中文自然语言总结，面向教练和科研工作者，"
        "开头 1~2 句话简介论文的核心问题、研究对象和整体干预/观察框架，"
        "随后用 1~2 句话用文字列出关键方法学数值（例如总样本量、分组情况、随访时间、主要测量指标等），"
        "最后用简洁的语言概括这些定量结果的大致含义（比如主要效果和显著性）。"
        "tables 是一个可选数组，用于把论文的主要定量结果整理成 1~5 张结构化表格，"
        "每个元素形如 {id, title, description, columns, rows}：columns 是列定义数组，"
        "每个列对象为 {id: 列ID, label: 列标题}；rows 是行对象数组，每个行对象用列ID作为键。"
        "在构建 tables 时，请优先使用 Results/Findings/Outcomes/结果 等章节中的核心数值结果（例如主要和次要结局指标、效应量、置信区间、p 值、变化率、Likert 量表打分等），"
        "并尽量把每个模型/组别/时间点/任务的主要结果都拆成若干行，让读者可以一眼看出不同模型或组别之间的差异。"
        "对于原文中以表格形式给出的数值（包括 mean±variance、mean±SD 等），应当原样作为字符串抄写进对应单元格，例如“3.96 ± 0.20 (0.81)”可以整体作为一个单元格文本，"
        "不要把这些数字改写成“Enhanced”“Relatively good”之类的纯文字描述；如需给出文字评价，可以额外增加一列或放入 summary，但不能替换掉原始数值。"
        "如果某些结果表格主要使用定性等级或文字描述（例如 Low / Improved / Relatively good / Not specified 等），"
        "也必须完整地映射到 tables.rows 中，不要因为缺少阿拉伯数字就忽略这些表格。"
        "关于研究设计、纳入标准、诊断或共识框架等信息（例如年龄范围、诊断 cut-off 的逻辑、专家和国家数量、所用模型数量、数据点总数等），"
        "通常不需要在 tables 中占据太多行，这类设计性计数更适合在 summary 或少量 metrics 中简要体现；只有当这些数值本身就是论文最核心的结论时，才把它们放入 tables，"
        "并且设计性计数类行数最好不要超过 tables 总行数的大约 20%。"
        "如果文中有足够丰富的结果数据，请尽量让 tables 中的总行数处在 15~60 行的区间内，"
        "覆盖主要结果、关键时间点和组别，而不要只给出寥寥几行。"
        "你必须在 tables 中至少给出 3 张表，建议命名为“摘要数值”“方法数值”“结果数值”，"
        "每张表的列可以自定义，但需要清晰呈现数值、组别/时间点、章节/上下文等信息。"
    )

    # 先粗略抽取摘要，用于定义研究主题
    abstract_text = _extract_abstract_from_markdown(markdown_text)

    # 只保留 Abstract / Methods / Results 这些与研究设计和结果直接相关的章节，
    # 并优先保留其中所有包含数字的行及其局部上下文，确保数值表格不会因为截断而丢失；
    # 同时在数值窗口之后附加整个章节文本，以保留定性结果表格和描述性上下文。
    lines = markdown_text.splitlines()
    section_labels: List[str] = []
    current_section = "other"
    for line in lines:
        stripped = line.strip()
        lower = stripped.lstrip("#").strip().lower()
        if stripped.startswith("#"):
            if "abstract" in lower:
                current_section = "abstract"
            elif "method" in lower:
                # 覆盖 methods / materials and methods / subjects and methods 等常见写法
                current_section = "methods"
            elif "result" in lower:
                current_section = "results"
            else:
                current_section = "other"
        section_labels.append(current_section)

    allowed_sections = {"abstract", "methods", "results"}
    has_allowed_sections = any(label in allowed_sections for label in section_labels)

    # 数值窗口：所有含数字行的前后若干行，优先保证这些内容被送入 LLM
    numeric_chunks: List[str] = []
    seen_chunks: set[str] = set()
    for idx, line in enumerate(lines):
        if has_allowed_sections and section_labels[idx] not in allowed_sections:
            continue
        if any(ch.isdigit() for ch in line):
            start = max(0, idx - 2)
            end = min(len(lines), idx + 3)
            chunk = "\n".join(lines[start:end])
            if chunk not in seen_chunks:
                numeric_chunks.append(chunk)
                seen_chunks.add(chunk)

    numeric_snippet = "\n\n".join(numeric_chunks).strip()

    # 完整章节文本：用于保留定性结果表格（即便没有数字）和描述性上下文
    allowed_lines: List[str] = []
    for idx, line in enumerate(lines):
        if section_labels[idx] in allowed_sections:
            allowed_lines.append(line)
    full_section_snippet = "\n".join(allowed_lines).strip()

    if numeric_snippet:
        combined = numeric_snippet + "\n\n" + full_section_snippet
    else:
        combined = full_section_snippet or markdown_text

    snippet = combined.strip()
    if len(snippet) > 20000:
        snippet = snippet[:20000]

    user_prompt = (
        "下面是一篇运动科学或医学论文的部分内容。首先是该论文的摘要（用于帮助你理解研究主题）：\n\n"
        + abstract_text
        + "\n\n接下来是包含大量数字的正文片段（Methods/Results/表格等）：\n\n"
        + snippet
        + "\n\n请重点提取与摘要所述研究主题相关或对理解研究结果有直接支持作用的定量数值（包括样本量、描述性统计、结果指标、百分比、p 值等）。"
        + "摘要只是为了帮助你理解主题，不要限制自己只能抽取摘要中出现过的名词；"
        + "如果在 Results/结果 等部分出现与该主题高度相关但摘要未提到的数值，同样要完整抽取。"
        + "同时可以少量保留与研究设计或诊断框架紧密相关的数字（例如诊断阈值、年龄分层、共识过程中的人数和国家数等），"
        + "但这些信息更适合在 summary 中用 1~2 句话概括，而不是主导 tables。"
        + "最后，请按照系统提示词给定的 JSON 结构返回。"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    raw = await client.chat(
        messages,
        model=DEEPSEEK_V4_FLASH_MODEL,
        temperature=0.2,
        max_tokens=4096,
        response_format={"type": "json_object"},
    )

    if not raw:
        return {"metrics": [], "summary": ""}

    try:
        parsed = json.loads(raw)
    except Exception:
        return {"metrics": [], "summary": ""}

    if not isinstance(parsed, dict):
        return {"metrics": [], "summary": ""}

    metrics = parsed.get("metrics")
    summary = parsed.get("summary") or ""
    tables_raw = parsed.get("tables")
    if not isinstance(metrics, list):
        metrics = []

    cleaned: List[dict] = []
    for item in metrics:
        if isinstance(item, dict):
            cleaned.append(item)

    tables: List[dict] = []
    if isinstance(tables_raw, list):
        for tbl in tables_raw:
            if isinstance(tbl, dict):
                tables.append(tbl)

    tables = _build_section_tables(cleaned, tables)

    return {
        "metrics": cleaned,
        "summary": str(summary) if summary is not None else "",
        "tables": tables,
    }


@router.post("/article-metrics")
async def extract_article_metrics(
    file: UploadFile = File(...),
    mode: str = Query(
        "direct",
        description="Extraction mode: 'direct' (default, use PyMuPDF locally and skip MinerU) or 'mineru' (use MinerU)",
    ),
    _user=Depends(require_weekly_quota("sports_data_article_metrics", 5)),
):
    if not file:
        raise HTTPException(status_code=400, detail="File is required")

    filename = (file.filename or "").lower()
    if not filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported in this version")

    mode_normalized = (mode or "direct").strip().lower()
    if mode_normalized not in {"mineru", "direct"}:
        raise HTTPException(status_code=400, detail="mode must be either 'mineru' or 'direct'")

    mineru_available = bool(getattr(settings, "mineru_api_token", None))
    used_mode = mode_normalized

    try:
        if mode_normalized == "direct":
            markdown_text = await _fetch_markdown_via_pymupdf(file)
        else:
            markdown_text = await _fetch_markdown_via_mineru(file)
    except HTTPException:
        if mode_normalized == "direct" and mineru_available:
            await _rewind_upload_file(file)
            markdown_text = await _fetch_markdown_via_mineru(file)
            used_mode = "mineru_fallback"
        else:
            raise

    llm_result = await _extract_metrics_with_llm(markdown_text)
    metrics = llm_result.get("metrics") or []
    summary = llm_result.get("summary") or ""
    tables = llm_result.get("tables") or []

    # 如果本地提取结果没有任何数字，自动切换到 MinerU 尝试再次解析
    if (
        mode_normalized == "direct"
        and mineru_available
        and used_mode == "direct"
        and not _has_numeric_content(metrics, tables)
    ):
        await _rewind_upload_file(file)
        try:
            markdown_text = await _fetch_markdown_via_mineru(file)
        except HTTPException:
            pass
        else:
            used_mode = "mineru_fallback"
            llm_result = await _extract_metrics_with_llm(markdown_text)
            metrics = llm_result.get("metrics") or []
            summary = llm_result.get("summary") or ""
            tables = llm_result.get("tables") or []

    return {
        "source": "upload",
        "extraction_mode": used_mode,
        "total": len(metrics),
        "metrics": metrics,
        "summary": summary,
        "tables": tables,
    }


@router.get("/reports")
async def search_reports(
    q: str = Query(
        ...,
        description="English keywords describing sports reports, dashboards or analysis templates",
    ),
    limit: int = Query(
        10,
        ge=1,
        le=15,
        description="Maximum number of results to return (5/10/15 recommended)",
    ),
    _user=Depends(require_weekly_quota("sports_data_search", 5)),
):
    """Search for open sports analytics reports and dashboards.

    聚焦比赛报告、训练负荷报表、Shiny/BI面板等资源，帮助教练/分析师直接上手。
    """
    q_clean = _normalize_query(q)
    if not q_clean:
        raise HTTPException(status_code=400, detail="Query must not be empty")

    cache_key = _tavily_cache_key("reports", q_clean)
    cached = await _tavily_cache_get(cache_key)
    if cached is not None:
        return {
            "query": q_clean,
            "total": min(len(cached), limit),
            "results": cached[:limit],
        }

    client = _get_tavily_client()

    try:
        effective_query = f"{q_clean} sports report dashboard Shiny Tableau template"
        tavily_resp = await asyncio.to_thread(
            client.search,
            query=effective_query,
            search_depth="basic",
            max_results=_tavily_max_results(limit),
            include_domains=_REPORT_DOMAINS,
            topic="general",
            include_answer=False,
        )
    except Exception as e:  # pragma: no cover - network / external service
        raise HTTPException(status_code=502, detail=f"Tavily search failed: {type(e).__name__}: {e}")

    raw_results = tavily_resp.get("results") if isinstance(tavily_resp, dict) else None
    if not isinstance(raw_results, list):
        raw_results = []

    items: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for r in raw_results:
        if not isinstance(r, dict):
            continue
        url = (r.get("url") or "").strip()
        if not url:
            continue
        if not (url.startswith("http://") or url.startswith("https://")):
            continue
        canonical = _canonicalize_url(url)
        if canonical in seen:
            continue
        seen.add(canonical)
        title = (r.get("title") or "").strip() or url
        snippet = (r.get("content") or r.get("snippet") or "").strip()
        parsed = urlparse(url)
        source = parsed.netloc or ""
        kind = _infer_report_kind(source, url)
        items.append(
            {
                "title": title,
                "url": url,
                "snippet": snippet,
                "source": source,
                "kind": kind,
            }
        )

    await _tavily_cache_set(cache_key, items)

    return {
        "query": q_clean,
        "total": min(len(items), limit),
        "results": items[:limit],
    }


@router.get("/scales")
async def search_scales(
    q: str = Query(
        ...,
        description="English keywords describing sports-related scales or questionnaires",
    ),
    limit: int = Query(
        10,
        ge=1,
        le=15,
        description="Maximum number of results to return (5/10/15 recommended)",
    ),
    _user=Depends(require_weekly_quota("sports_data_search", 5)),
):
    """Search for validated scales and questionnaires used in sports contexts.

    包括疲劳/睡眠/心理量表，以及运动相关问卷与调查工具。
    """
    q_clean = _normalize_query(q)
    if not q_clean:
        raise HTTPException(status_code=400, detail="Query must not be empty")

    cache_key = _tavily_cache_key("scales", q_clean)
    cached = await _tavily_cache_get(cache_key)
    if cached is not None:
        return {
            "query": q_clean,
            "total": min(len(cached), limit),
            "results": cached[:limit],
        }

    client = _get_tavily_client()

    try:
        effective_query = f"{q_clean} sport athlete questionnaire scale validation"
        tavily_resp = await asyncio.to_thread(
            client.search,
            query=effective_query,
            search_depth="basic",
            max_results=_tavily_max_results(limit),
            include_domains=_SCALE_DOMAINS,
            topic="general",
            include_answer=False,
        )
    except Exception as e:  # pragma: no cover - network / external service
        raise HTTPException(status_code=502, detail=f"Tavily search failed: {type(e).__name__}: {e}")

    raw_results = tavily_resp.get("results") if isinstance(tavily_resp, dict) else None
    if not isinstance(raw_results, list):
        raw_results = []

    items: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for r in raw_results:
        if not isinstance(r, dict):
            continue
        url = (r.get("url") or "").strip()
        if not url:
            continue
        if not (url.startswith("http://") or url.startswith("https://")):
            continue
        canonical = _canonicalize_url(url)
        if canonical in seen:
            continue
        seen.add(canonical)
        title = (r.get("title") or "").strip() or url
        snippet = (r.get("content") or r.get("snippet") or "").strip()
        parsed = urlparse(url)
        source = parsed.netloc or ""
        kind = _infer_scale_kind(source, url, title)
        items.append(
            {
                "title": title,
                "url": url,
                "snippet": snippet,
                "source": source,
                "kind": kind,
            }
        )

    await _tavily_cache_set(cache_key, items)

    return {
        "query": q_clean,
        "total": min(len(items), limit),
        "results": items[:limit],
    }


@router.get("/code")
async def search_code(
    q: str = Query(
        ...,
        description="English keywords describing the sports analytics code or model you are looking for",
    ),
    limit: int = Query(
        10,
        ge=1,
        le=15,
        description="Maximum number of results to return (5/10/15 recommended)",
    ),
    _user=Depends(require_weekly_quota("sports_data_search", 5)),
):
    """Search for open sports analytics code repositories and models.

    This endpoint focuses on GitHub / HuggingFace / Papers with Code 等代码平台，
    方便快速找到可复现的分析脚本和模型实现。
    """
    q_clean = _normalize_query(q)
    if not q_clean:
        raise HTTPException(status_code=400, detail="Query must not be empty")

    cache_key = _tavily_cache_key("code", q_clean)
    cached = await _tavily_cache_get(cache_key)
    if cached is not None:
        return {
            "query": q_clean,
            "total": min(len(cached), limit),
            "results": cached[:limit],
        }

    client = _get_tavily_client()

    try:
        effective_query = f"{q_clean} sports analytics code repository github"
        tavily_resp = await asyncio.to_thread(
            client.search,
            query=effective_query,
            search_depth="basic",
            max_results=_tavily_max_results(limit),
            include_domains=_CODE_DOMAINS,
            topic="general",
            include_answer=False,
        )
    except Exception as e:  # pragma: no cover - network / external service
        raise HTTPException(status_code=502, detail=f"Tavily search failed: {type(e).__name__}: {e}")

    raw_results = tavily_resp.get("results") if isinstance(tavily_resp, dict) else None
    if not isinstance(raw_results, list):
        raw_results = []

    items: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for r in raw_results:
        if not isinstance(r, dict):
            continue
        url = (r.get("url") or "").strip()
        if not url:
            continue
        if not (url.startswith("http://") or url.startswith("https://")):
            continue
        canonical = _canonicalize_url(url)
        if canonical in seen:
            continue
        seen.add(canonical)
        title = (r.get("title") or "").strip() or url
        snippet = (r.get("content") or r.get("snippet") or "").strip()
        parsed = urlparse(url)
        source = parsed.netloc or ""
        kind = _infer_code_kind(source, url)
        items.append(
            {
                "title": title,
                "url": url,
                "snippet": snippet,
                "source": source,
                "kind": kind,
            }
        )

    await _tavily_cache_set(cache_key, items)

    return {
        "query": q_clean,
        "total": min(len(items), limit),
        "results": items[:limit],
    }
