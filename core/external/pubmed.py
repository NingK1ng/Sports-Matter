"""
PubMed E-utilities API客户端

提供PubMed文献检索、元数据获取功能
包含完整弹性策略：Redis缓存、指数退避、熔断
"""

from typing import List, Dict, Any, Optional, Tuple
import asyncio
import os
import re
import xml.etree.ElementTree as ET

from core.config import settings
from core.external.base import BaseAPIClient
from core.external.rate_limiter import get_pubmed_rate_limiter


class PubMedClient(BaseAPIClient):
    """PubMed API客户端（支持多API密钥轮询）"""

    _DOI_PATTERN = re.compile(r"\b10\.\d{4,9}/[^\s\"<>]+", re.IGNORECASE)

    def __init__(self):
        super().__init__(
            base_url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
            timeout=30,  # 增加到30秒，处理大型XML响应
            enable_cache=True,
            cache_ttl=86400,  # 24小时缓存
        )

        self.email = settings.pubmed_email
        self.tool = settings.pubmed_tool_name
        
        # 多API密钥支持（轮询以突破速率限制）
        self.api_keys = self._load_api_keys()
        self.current_key_index = 0
        
        # 速率限制器：根据可用API Key数量动态调整QPS
        # PubMed 官方建议：单 Key 最高 ~10 QPS，我们这里为每个 Key 预留 9 QPS，并做上限保护
        effective_keys = len([k for k in self.api_keys if k])
        if effective_keys <= 1:
            rate = 9
        else:
            rate = min(9 * effective_keys, 30)  # 最多 30 QPS，避免过于激进
        self.rate_limiter = get_pubmed_rate_limiter(rate=rate)

    @classmethod
    def _extract_doi(cls, doc: Dict[str, Any]) -> Optional[str]:
        """从 esummary 文档中提取 DOI（优先 articleids，其次 elocationid 文本）。"""
        for item in doc.get("articleids") or []:
            try:
                if (item.get("idtype") or "").lower() == "doi":
                    doi = (item.get("value") or "").strip()
                    if doi:
                        return doi
            except Exception:
                continue

        elocationid = (doc.get("elocationid") or "").strip()
        if not elocationid:
            return None

        match = cls._DOI_PATTERN.search(elocationid)
        if match:
            doi = match.group(0).strip().rstrip(").,;")
            return doi or None

        cleaned = re.sub(r"^doi:\\s*", "", elocationid, flags=re.IGNORECASE).strip()
        if cleaned and len(cleaned) <= 100:
            return cleaned

        return None
    
    def _load_api_keys(self) -> List[str]:
        """加载所有可用的API密钥"""
        keys = []
        
        # 方式1：从 PUBMED_API_KEYS 环境变量（逗号分隔）
        if hasattr(settings, 'pubmed_api_keys') and settings.pubmed_api_keys:
            keys_str = settings.pubmed_api_keys.strip()
            if keys_str:
                keys.extend([k.strip() for k in keys_str.split(',') if k.strip()])
        
        # 方式2：从单独的环境变量 PUBMED_API_KEY_1, PUBMED_API_KEY_2, ...
        for i in range(1, 10):  # 最多支持9个
            key_attr = f'pubmed_api_key_{i}'
            if hasattr(settings, key_attr):
                key = getattr(settings, key_attr)
                if key and key.strip():
                    keys.append(key.strip())
        
        # 方式3：兼容旧配置 PUBMED_API_KEY
        if not keys and hasattr(settings, 'pubmed_api_key') and settings.pubmed_api_key:
            keys.append(settings.pubmed_api_key.strip())
        
        return keys if keys else [None]  # 至少返回一个None（无密钥模式）
    
    def _get_next_api_key(self) -> Optional[str]:
        """轮询获取下一个API密钥"""
        if not self.api_keys:
            return None
        key = self.api_keys[self.current_key_index]
        self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
        return key

    async def search(
        self,
        query: str,
        retmax: int = 100,
        retstart: int = 0,
        use_cache: bool = True,
        return_count: bool = False,
    ) -> List[str] | tuple[List[str], int]:
        """
        检索文献PMID列表

        Args:
            query: 检索词（支持布尔运算）
            retmax: 返回最大数量
            retstart: 起始位置
            use_cache: 是否使用缓存
            return_count: 是否返回总命中数

        Returns:
            List[str]: PMID列表
            Tuple[List[str], int]: 当 return_count=True 时返回 (PMID列表, 总命中数)

        Example:
            client = PubMedClient()
            pmids = await client.search("basketball[Title] AND 2024[DP]", retmax=20)
        """
        params = {
            "db": "pubmed",
            "term": query,
            "retmax": retmax,
            "retstart": retstart,
            "retmode": "json",
            "email": self.email,
            "tool": self.tool,
        }

        # 轮询使用API密钥
        api_key = self._get_next_api_key()
        if api_key:
            params["api_key"] = api_key

        # 速率限制
        await self.rate_limiter.acquire()
        
        # 如果query太长(>1500字符)，使用POST避免414错误
        # PubMed URL长度限制约2000字符，留些余量
        if len(query) > 1500:
            print(f"⚠️  查询式过长({len(query)}字符)，使用POST请求")
            response = await self.post("/esearch.fcgi", data=params, use_cache=use_cache)
        else:
            response = await self.get("/esearch.fcgi", params=params, use_cache=use_cache)

        # 解析PMID列表
        result = response.get("esearchresult", {})
        pmids = result.get("idlist", [])
        total_count_raw = result.get("count", len(pmids))
        try:
            total_count = int(total_count_raw)
        except (TypeError, ValueError):
            total_count = len(pmids) if pmids else 0

        print(f"📚 PubMed检索: {len(pmids)}篇文献 (query: {query[:50]}...)")
        if return_count:
            return pmids, total_count
        return pmids

    async def search_all_pmids(
        self,
        query: str,
        *,
        batch_size: Optional[int] = None,
    ) -> List[str]:
        """
        获取“全部”命中 PMID（突破 PubMed ESearch 9,999 的 idlist/retstart 限制）。

        说明：
        - 使用 ESearch(usehistory=y) 将结果集存入 History Server，返回 WebEnv + QueryKey
        - 再用 EFetch(rettype=uilist, retmode=text) 按 retstart/retmax 分批拉取 PMID 列表

        注意：
        - History Server 的 WebEnv 有时效，不做缓存（避免复用过期 WebEnv）
        """
        webenv, query_key, total_count = await self._esearch_history(query)
        if total_count <= 0:
            print(f"📚 PubMed检索(HISTORY): 0篇文献 (query: {query[:50]}...)")
            return []

        pmids = await self._efetch_uilist_from_history(
            webenv=webenv,
            query_key=query_key,
            total_count=total_count,
            batch_size=batch_size,
        )
        print(f"📚 PubMed检索(HISTORY): {len(pmids)}篇文献 (query: {query[:50]}...)")
        return pmids

    async def _esearch_history(self, query: str) -> Tuple[str, str, int]:
        """ESearch + usehistory=y，返回 (WebEnv, QueryKey, total_count)。"""
        params = {
            "db": "pubmed",
            "term": query,
            "usehistory": "y",
            "retmax": 0,
            "retstart": 0,
            "retmode": "json",
            "email": self.email,
            "tool": self.tool,
        }

        api_key = self._get_next_api_key()
        if api_key:
            params["api_key"] = api_key

        await self.rate_limiter.acquire()

        # WebEnv 有时效，禁止缓存
        if len(query) > 1500:
            response = await self.post("/esearch.fcgi", data=params, use_cache=False)
        else:
            response = await self.get("/esearch.fcgi", params=params, use_cache=False)

        result = (response or {}).get("esearchresult", {})
        webenv = result.get("webenv") or result.get("WebEnv")
        query_key = result.get("querykey") or result.get("query_key") or result.get("QueryKey")

        total_count_raw = result.get("count", 0)
        try:
            total_count = int(total_count_raw)
        except (TypeError, ValueError):
            total_count = 0

        if not webenv or not query_key:
            raise RuntimeError("PubMed ESearch(usehistory=y) missing WebEnv/querykey")

        return str(webenv), str(query_key), total_count

    async def _efetch_uilist_from_history(
        self,
        *,
        webenv: str,
        query_key: str,
        total_count: int,
        batch_size: Optional[int] = None,
    ) -> List[str]:
        """EFetch + rettype=uilist 从 History Server 拉取 PMID 列表。"""
        if total_count <= 0:
            return []

        if batch_size is None:
            try:
                batch_size = int(os.getenv("PUBMED_EFETCH_UILIST_BATCH_SIZE", "10000"))
            except Exception:
                batch_size = 10000
        if batch_size <= 0:
            batch_size = 10000

        pmids: List[str] = []
        retstart = 0
        while retstart < total_count:
            retmax = min(batch_size, total_count - retstart)
            params = {
                "db": "pubmed",
                "query_key": query_key,
                "WebEnv": webenv,
                "rettype": "uilist",
                "retmode": "text",
                "retstart": retstart,
                "retmax": retmax,
                "email": self.email,
                "tool": self.tool,
            }

            api_key = self._get_next_api_key()
            if api_key:
                params["api_key"] = api_key

            backoff = 1.0
            text_payload: Optional[str] = None
            for attempt in range(3):
                await self.rate_limiter.acquire()
                resp = await self.client.get(
                    "/efetch.fcgi",
                    params=params,
                    headers={"Accept": "text/plain"},
                    timeout=60,
                )

                status = resp.status_code
                if status == 429:
                    retry_after = int(resp.headers.get("Retry-After", "2") or 2)
                    print(f"⚠️  速率限制！等待{retry_after}秒...")
                    await asyncio.sleep(retry_after)
                    continue

                if 500 <= status < 600:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 8)
                    continue

                resp.raise_for_status()
                text_payload = resp.text or ""
                if not text_payload.strip():
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 8)
                    continue
                break

            if not text_payload:
                raise RuntimeError("PubMed EFetch(uilist) empty response")

            batch_pmids = [token.strip() for token in text_payload.split() if token.strip().isdigit()]
            pmids.extend(batch_pmids)
            retstart += retmax

        # 去重（保持顺序）
        return list(dict.fromkeys(pmids))

    async def fetch_summary(
        self,
        pmids: List[str],
        use_cache: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        获取文献摘要信息

        Args:
            pmids: PMID列表
            use_cache: 是否使用缓存

        Returns:
            List[Dict]: 文献元数据列表

        Example:
            summaries = await client.fetch_summary(["38123456", "38123457"])
        """
        if not pmids:
            return []

        # 如果PMID数量太多，分批处理避免414错误
        # 每批最多50个PMID（经验值，避免URL过长）
        if len(pmids) > 50:
            print(f"⚠️  PMID数量过多({len(pmids)}个)，分批处理（每批50个）")
            all_articles = []
            for i in range(0, len(pmids), 50):
                batch = pmids[i:i+50]
                batch_articles = await self.fetch_summary(batch, use_cache)
                all_articles.extend(batch_articles)
                # 避免API限流
                import asyncio
                await asyncio.sleep(0.5)
            return all_articles

        params = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "json",
            "email": self.email,
            "tool": self.tool,
        }

        # 轮询使用API密钥
        api_key = self._get_next_api_key()
        if api_key:
            params["api_key"] = api_key

        # 速率限制
        await self.rate_limiter.acquire()
        
        # 使用POST避免URL过长
        response = await self.post(
            "/esummary.fcgi", data=params, use_cache=use_cache
        )

        # 解析结果
        result = response.get("result", {})
        articles = []

        for pmid in pmids:
            if pmid in result:
                doc = result[pmid]
                doi = self._extract_doi(doc)
                # DB 字段为 VARCHAR(100)；超长值会导致写库失败
                if doi and len(doi) > 100:
                    doi = None
                title = (doc.get("title") or "").strip()
                # PubMed 的 book/guideline 记录可能没有 title 字段（为空字符串）
                # 常见备选字段：booktitle / sorttitle
                if not title:
                    title = (doc.get("booktitle") or "").strip()
                if not title:
                    title = (doc.get("sorttitle") or "").strip()
                articles.append(
                    {
                        "pmid": pmid,
                        "title": title,
                        "authors": [
                            author.get("name", "")
                            for author in doc.get("authors", [])
                        ],
                        "source": doc.get("source", ""),
                        "pubdate": doc.get("pubdate", ""),
                        "doi": doi or "",
                    }
                )

        print(f"✅ 获取{len(articles)}篇文献元数据")
        return articles

    async def fetch_abstract(
        self,
        pmid: str,
        use_cache: bool = True,
    ) -> Optional[str]:
        """
        获取文献摘要全文

        Args:
            pmid: PMID
            use_cache: 是否使用缓存

        Returns:
            Optional[str]: 摘要文本

        Example:
            abstract = await client.fetch_abstract("38123456")
        """
        abstract, _, _ = await self.fetch_abstract_and_types(pmid, use_cache)
        return abstract
    
    async def fetch_abstract_and_types(
        self,
        pmid: str,
        use_cache: bool = True,
    ) -> tuple[Optional[str], list[str], list[str]]:
        """
        获取文献摘要、PublicationType和MeSH主题词

        Args:
            pmid: PMID
            use_cache: 是否使用缓存

        Returns:
            (摘要文本, PublicationType列表, MeSH主题词列表)

        Example:
            abstract, pub_types, mesh_terms = await client.fetch_abstract_and_types("38123456")
        """
        params = {
            "db": "pubmed",
            "id": pmid,
            "retmode": "xml",
            "email": self.email,
            "tool": self.tool,
        }

        # 轮询使用API密钥
        api_key = self._get_next_api_key()
        if api_key:
            params["api_key"] = api_key

        # 尝试多次抓取（处理HTML错误页/暂时性异常）
        backoff = 1.0
        text_payload: Optional[str] = None
        for attempt in range(3):
            # 速率限制
            await self.rate_limiter.acquire()
            resp = await self.client.get(
                "/efetch.fcgi",
                params=params,
                headers={"Accept": "application/xml"},
            )

            status = resp.status_code
            # 429处理（PubMed返回Retry-After秒）
            if status == 429:
                retry_after = int(resp.headers.get("Retry-After", "2") or 2)
                print(f"⚠️  速率限制！等待{retry_after}秒...")
                import asyncio as _asyncio
                await _asyncio.sleep(retry_after)
                continue

            if 500 <= status < 600:
                import asyncio as _asyncio
                await _asyncio.sleep(backoff)
                backoff = min(backoff * 2, 8)
                continue

            text_payload = resp.text or ""
            # 非XML（HTML/空响应）
            if not text_payload or not text_payload.lstrip().startswith("<"):
                import asyncio as _asyncio
                await _asyncio.sleep(backoff)
                backoff = min(backoff * 2, 8)
                continue
            break

        if not text_payload:
            return None, [], []

        # 解析XML
        try:
            root = ET.fromstring(text_payload)

            # 获取所有AbstractText元素（包含结构化段落），用 itertext() 抓取子节点文本
            abstract_elems = root.findall(".//AbstractText")
            abstract = None

            if abstract_elems:
                parts: list[str] = []
                for elem in abstract_elems:
                    label = elem.get('Label') or elem.get('label') or ''
                    text_content = ''.join(elem.itertext()).strip()
                    if not text_content:
                        continue
                    if label:
                        parts.append(f"{label}: {text_content}")
                    else:
                        parts.append(text_content)
                if parts:
                    abstract = ' '.join(parts)
            
            # 部分文章使用 OtherAbstract 节点
            if not abstract:
                other_elems = root.findall(".//OtherAbstract/AbstractText")
                parts2: list[str] = []
                for elem in other_elems:
                    parts2.append(''.join(elem.itertext()).strip())
                if parts2:
                    abstract = ' '.join([p for p in parts2 if p])
            
            # 获取PublicationType
            pub_type_elems = root.findall(".//PublicationType")
            pub_types = [elem.text for elem in pub_type_elems if elem.text]
            
            # 获取MeSH主题词
            mesh_elems = root.findall(".//MeshHeading/DescriptorName")
            mesh_terms = [elem.text for elem in mesh_elems if elem.text]
            
            return abstract, pub_types, mesh_terms
            
        except ET.ParseError as e:
            print(f"⚠️  解析摘要失败 (PMID: {pmid}): {e}")

        return None, [], []

    async def fetch_abstract_and_types_batch(
        self,
        pmids: List[str],
        use_cache: bool = True,
    ) -> Dict[str, tuple[Optional[str], list[str], list[str]]]:
        """
        批量获取文献摘要、PublicationType和MeSH主题词（单次/少量 efetch 请求）

        说明：
        - PubMed 的 /efetch.fcgi 支持一次请求多个 PMID（id 逗号分隔）
        - 相比逐条 efetch，可显著减少网络往返与解析开销

        Args:
            pmids: PMID列表
            use_cache: 预留参数（当前不对 efetch XML 做缓存）

        Returns:
            Dict[pmid] -> (abstract, pub_types, mesh_terms)
        """
        if not pmids:
            return {}

        # 每次请求的 PMID 数，避免 XML 过大；可用环境变量覆盖
        try:
            max_per_request = int(os.getenv("PUBMED_EFETCH_BATCH_SIZE", "50"))
        except Exception:
            max_per_request = 50
        if max_per_request <= 0:
            max_per_request = 50

        results: Dict[str, tuple[Optional[str], list[str], list[str]]] = {}
        for i in range(0, len(pmids), max_per_request):
            chunk = pmids[i : i + max_per_request]
            chunk_results = await self._fetch_abstract_and_types_batch_once(chunk)
            results.update(chunk_results)

        return results

    async def _fetch_abstract_and_types_batch_once(
        self,
        pmids: List[str],
    ) -> Dict[str, tuple[Optional[str], list[str], list[str]]]:
        """单次 efetch 获取多个 PMID，并解析为映射。"""
        if not pmids:
            return {}

        def _extract_abstract(container: ET.Element) -> Optional[str]:
            abstract_elems = container.findall(".//AbstractText")
            abstract: Optional[str] = None
            if abstract_elems:
                parts: list[str] = []
                for elem in abstract_elems:
                    label = elem.get("Label") or elem.get("label") or ""
                    text_content = "".join(elem.itertext()).strip()
                    if not text_content:
                        continue
                    if label:
                        parts.append(f"{label}: {text_content}")
                    else:
                        parts.append(text_content)
                if parts:
                    abstract = " ".join(parts)

            if not abstract:
                other_elems = container.findall(".//OtherAbstract/AbstractText")
                parts2: list[str] = []
                for elem in other_elems:
                    text_content = "".join(elem.itertext()).strip()
                    if text_content:
                        parts2.append(text_content)
                if parts2:
                    abstract = " ".join(parts2)

            return abstract

        params = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
            "email": self.email,
            "tool": self.tool,
        }

        api_key = self._get_next_api_key()
        if api_key:
            params["api_key"] = api_key

        backoff = 1.0
        text_payload: Optional[str] = None
        for attempt in range(3):
            await self.rate_limiter.acquire()
            resp = await self.client.get(
                "/efetch.fcgi",
                params=params,
                headers={"Accept": "application/xml"},
                timeout=60,
            )

            status = resp.status_code
            if status == 429:
                retry_after = int(resp.headers.get("Retry-After", "2") or 2)
                print(f"⚠️  速率限制！等待{retry_after}秒...")
                await asyncio.sleep(retry_after)
                continue

            if 500 <= status < 600:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 8)
                continue

            text_payload = resp.text or ""
            if not text_payload or not text_payload.lstrip().startswith("<"):
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 8)
                continue

            break

        if not text_payload:
            return {}

        try:
            root = ET.fromstring(text_payload)
        except ET.ParseError:
            return {}

        out: Dict[str, tuple[Optional[str], list[str], list[str]]] = {}

        # 常规 PubmedArticle
        for item in root.findall(".//PubmedArticle"):
            pmid = (item.findtext(".//MedlineCitation/PMID") or "").strip()
            if not pmid:
                continue
            abstract = _extract_abstract(item)
            pub_types = [e.text for e in item.findall(".//PublicationType") if e.text]
            mesh_terms = [e.text for e in item.findall(".//MeshHeading/DescriptorName") if e.text]
            out[pmid] = (abstract, pub_types, mesh_terms)

        # PubmedBookArticle（如 GeneReviews 等）
        for item in root.findall(".//PubmedBookArticle"):
            pmid = (
                (item.findtext(".//BookDocument/PMID") or item.findtext(".//PMID") or "").strip()
            )
            if not pmid:
                continue
            abstract = _extract_abstract(item)
            pub_types = [e.text for e in item.findall(".//PublicationType") if e.text]
            mesh_terms = [e.text for e in item.findall(".//MeshHeading/DescriptorName") if e.text]
            out[pmid] = (abstract, pub_types, mesh_terms)

        return out

    async def fetch_articles_xml(
        self,
        pmids: List[str],
        use_cache: bool = True,
    ) -> str:
        """
        批量获取文献完整XML（用于回填日期）

        Args:
            pmids: PMID列表
            use_cache: 是否使用缓存

        Returns:
            str: PubmedArticleSet XML（包含所有请求的 PMID）

        Example:
            xml = await client.fetch_articles_xml(["12345", "67890"])
        """
        if not pmids:
            return ""

        params = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
            "email": self.email,
            "tool": self.tool,
        }

        # 轮询使用API密钥
        api_key = self._get_next_api_key()
        if api_key:
            params["api_key"] = api_key

        # 速率限制
        await self.rate_limiter.acquire()

        # 直接请求XML
        resp = await self.client.get(
            "/efetch.fcgi",
            params=params,
            headers={"Accept": "application/xml"}
        )
        resp.raise_for_status()
        return resp.text or ""

    async def fetch_nbib(
        self,
        pmids: list[str],
        use_cache: bool = True,
    ) -> str:
        """
        批量导出NBIB文本

        Args:
            pmids: PMID列表
            use_cache: 是否使用缓存

        Returns:
            str: NBIB格式文本（多条拼接）
        """
        if not pmids:
            return ""

        params = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "text",
            "rettype": "medline",
            "email": self.email,
            "tool": self.tool,
        }

        # 轮询使用API密钥
        api_key = self._get_next_api_key()
        if api_key:
            params["api_key"] = api_key

        # 速率限制
        await self.rate_limiter.acquire()

        # 直接请求文本
        resp = await self.client.get("/efetch.fcgi", params=params)
        resp.raise_for_status()
        return resp.text or ""

    async def elink(
        self,
        pmid: str,
        retmax: int = 50,
        use_cache: bool = True,
    ) -> List[str]:
        """
        获取相似文献PMID列表（基于PubMed官方ELink算法）
        
        Args:
            pmid: 输入文献的PMID
            retmax: 返回最大数量（默认50）
            use_cache: 是否使用缓存（默认True，TTL=48h）
        
        Returns:
            List[str]: 相似文献的PMID列表（按相似度排序）
        
        Example:
            client = PubMedClient()
            related_pmids = await client.elink("39609566", retmax=50)
        """
        params = {
            "dbfrom": "pubmed",
            "db": "pubmed",
            "id": pmid,
            "cmd": "neighbor",  # 获取相关文献
            "retmax": retmax,
            "email": self.email,
            "tool": self.tool,
        }
        
        # 轮询使用API密钥
        api_key = self._get_next_api_key()
        if api_key:
            params["api_key"] = api_key
        
        # 尝试从缓存读取
        if self.enable_cache and use_cache:
            import hashlib
            import json
            from core.cache import cache_get, cache_set
            
            params_str = json.dumps(params, sort_keys=True)
            params_hash = hashlib.md5(params_str.encode()).hexdigest()[:8]
            cache_key = f"api:PubMedClient:elink:{params_hash}"
            cached_data = await cache_get(cache_key)
            if cached_data is not None:
                print(f"✅ 缓存命中: {cache_key}")
                return cached_data
        
        # 速率限制
        await self.rate_limiter.acquire()
        
        # 直接调用httpx客户端获取XML响应（因为BaseAPIClient期望JSON）
        try:
            response = await self.client.get("/elink.fcgi", params=params)
            response.raise_for_status()
            xml_text = response.text
            
            # 解析XML
            root = ET.fromstring(xml_text)
            
            # 提取LinkSetDb中的Id列表
            # XML结构: <eLinkResult><LinkSet><LinkSetDb><Link><Id>PMID</Id></Link>...</LinkSetDb></LinkSet></eLinkResult>
            pmid_list = []
            for link_elem in root.findall(".//LinkSetDb/Link/Id"):
                if link_elem.text:
                    pmid_list.append(link_elem.text)
            
            print(f"✅ ELink召回{len(pmid_list)}篇相似文献 (输入PMID: {pmid})")
            
            # 写入缓存（TTL=48小时）
            if self.enable_cache and use_cache:
                from core.cache import cache_set
                await cache_set(cache_key, pmid_list, ttl=172800)  # 48小时
            
            return pmid_list
            
        except ET.ParseError as e:
            print(f"⚠️  解析ELink响应失败 (PMID: {pmid}): {e}")
            return []
        except Exception as e:
            print(f"⚠️  ELink调用失败 (PMID: {pmid}): {e}")
            return []


def map_pub_types_to_lit_types(
    pub_types: list[str],
    mesh_terms: list[str] = None,
    title: str = "",
    abstract: str = "",
) -> list[str]:
    """
    将PubMed的PublicationType和MeSH主题词映射到文献类型（规则优先）

    判断顺序（从高到低）：
    0. 明确的非研究类文献（editorial / comment / letter / news / erratum...）→ non_research
    1. Meta分析 & 系统综述 → meta_analysis
    2. 综述（叙述性/非系统） → review
    3. 指南/共识/Protocol → guideline
    4. 原创研究（兜底） → original

    Args:
        pub_types: PubMed的PublicationType列表
        mesh_terms: MeSH主题词列表（可选）
        title: 文献标题（可选）
        abstract: 文献摘要（可选，用于动物关键词匹配）

    Returns:
        文献类型列表（当前仅返回单个主类型）
    """
    pub_types = pub_types or []
    mesh_terms = mesh_terms or []

    pub_types_lower = [pt.lower() for pt in pub_types]
    title_lower = (title or "").lower()

    # 0️⃣ 先识别明显的非研究类文献（规则过滤用）
    # 这些类型基本不包含原创研究设计，直接标为 non_research
    non_research_pub_types = {
        "editorial",
        "comment",
        "letter",
        "news",
        "newspaper article",
        "biography",
        "interview",
        "historical article",
        "address",
        "legal case",
        "legislation",
        "published erratum",
        "corrigendum",
        "retraction of publication",
        "retracted publication",
        "expression of concern",
        "duplicate publication",
    }
    if any(pt in non_research_pub_types for pt in pub_types_lower):
        return ["non_research"]

    # 1️⃣ Meta分析 & 系统综述
    # PublicationType + 标题关键词
    meta_pub_types = [
        "meta-analysis",
        "systematic review",
        "review, systematic",
        "scoping review",
    ]
    meta_title_keywords = [
        "meta-analysis",
        "meta analysis",
        "metaanalysis",
        "systematic review and meta-analysis",
        "systematic review",
    ]

    if any(pt in pub_types_lower for pt in meta_pub_types) or any(
        kw in title_lower for kw in meta_title_keywords
    ):
        return ["meta_analysis"]

    # 2️⃣ 综述（叙述性/非系统）
    # Review[pt]，排除系统综述/指南/Protocol
    if "review" in pub_types_lower:
        # 排除系统综述相关标题
        systematic_review_titles = [
            "systematic review",
            "scoping review",
            "umbrella review",
            "meta-analysis",
            "meta-analyses",
            "metaanalysis",
            "network meta-analysis",
            "network meta-analyses",
            "overview of reviews",
        ]
        if any(keyword in title_lower for keyword in systematic_review_titles):
            return ["meta_analysis"]

        # 排除指南/共识/Protocol标题
        guideline_titles = [
            "clinical practice guideline",
            "practice guideline",
            "consensus statement",
            "position statement",
            "recommendation statement",
            "best practice guideline",
            "cpg",
            "study protocol",
            "trial protocol",
            "systematic review and meta-analysis",
        ]
        if any(keyword in title_lower for keyword in guideline_titles):
            # 是指南/Protocol，跳过review判断
            pass
        else:
            return ["review"]

    # 3️⃣ 指南/共识/Protocol
    guideline_pub_types = [
        "practice guideline",
        "guideline",
        "consensus development conference",
        "consensus development conference, nih",
        "clinical protocols",
    ]

    guideline_title_keywords = [
        "clinical practice guideline",
        "practice guideline",
        "consensus statement",
        "position statement",
        "recommendation statement",
        "best practice guideline",
        "cpg",
        "study protocol",
        "trial protocol",
        "expert consensus",
        "best practice",
    ]

    if any(pt in guideline_pub_types for pt in pub_types_lower) or any(
        keyword in title_lower for keyword in guideline_title_keywords
    ):
        return ["guideline"]

    # 4️⃣ 原创研究（兜底）
    # 动物 vs 人体/理论的细分交给后续 LLM；这里只打一个通用标记
    return ["original"]


# 全局单例
_pubmed_client: Optional[PubMedClient] = None


def get_pubmed_client() -> PubMedClient:
    """
    获取PubMed客户端（单例）

    Returns:
        PubMedClient: PubMed客户端实例
    """
    global _pubmed_client
    if _pubmed_client is None:
        _pubmed_client = PubMedClient()
    return _pubmed_client
