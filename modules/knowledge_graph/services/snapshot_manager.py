"""
快照管理服务 - 生成和管理图谱快照
"""
import asyncio
import hashlib
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional
import networkx as nx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, text
import re

from modules.knowledge_graph.models.snapshot import GraphSnapshot, CommunitySnapshot
from modules.knowledge_graph.services.data_loader import DataLoader
from modules.knowledge_graph.services.graph_builder import GraphBuilder
from modules.knowledge_graph.services.comm_detector import CommunityDetector
from modules.knowledge_graph.services.keyword_extractor import KeywordExtractor
from modules.knowledge_graph.services.llm_clusterer import LLMClusterer

logger = logging.getLogger(__name__)


class SnapshotManager:
    """快照管理器"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.data_loader = DataLoader(db)
        self.graph_builder = GraphBuilder()
        self.comm_detector = CommunityDetector()
        # 关键词抽取器（如果无API Key，则内部方法会降级到本地规则）
        try:
            self.kw_extractor = KeywordExtractor()
        except Exception:
            self.kw_extractor = None
        # 社区命名 LLM 聚类器（deepseek-v4-flash）
        try:
            self.llm_clusterer = LLMClusterer()
        except Exception:
            self.llm_clusterer = None
        # 术语过滤集合（与GraphBuilder/Extractor保持一致）
        self._stopwords = {
            "a","an","the","and","or","of","to","in","on","for","with","without","by","from","as","at","is","are","was","were","be","been","being",
            "this","that","these","those","it","its","their","his","her","we","you","they","our","my","your","not","no","yes",
            "what","why","how","current","future","past","new","novel","more","less","many","various","several","impact","effect","effects","role","study","studies",
            "research","analysis","methods","approach","approaches","factors","outcomes","population","participants","care","healthcare","professional","professionals","training",
            "patient","patients","male","female","men","women","home","case","cases","group","groups","trial","trials",
            # 社区命名禁用：避免出现无意义/非专业的社区名
            "community","communities","other","others","unclustered","other unclustered","misc","miscellaneous","unknown"
        }
        self._banned = {
            "systematic review","meta-analysis","scoping review","narrative review","review","randomized controlled trial","randomised controlled trial",
            "clinical trial","pilot study","case report","retrospective study","prospective study","cohort study","cross-sectional study","protocol"
        }

    def _ensure_full_coverage_for_1d(self, communities: dict[str, list[str]], graph: nx.Graph) -> dict[str, list[str]]:
        """
        1d 快照需要覆盖“当日入库的全部文献”，但基于相似度的图可能包含大量孤立点（无边）。
        社区检测阶段会过滤 size<2 的社区，导致这些孤立点在前端“今日热点”里不可见。

        这里为 1d 补齐孤立点：按每篇论文的“主关键词”做分桶（同一关键词的孤立点聚为一类），
        避免产生大量 singleton 社区，也确保社区划分覆盖全部节点。
        """
        if not graph or graph.number_of_nodes() == 0:
            return communities

        assigned: set[str] = set()
        for nodes in (communities or {}).values():
            assigned.update(nodes or [])

        missing = [n for n in graph.nodes() if n not in assigned]
        if not missing:
            return communities

        import os

        def _get_main_kw(node: str) -> str:
            kws = graph.nodes[node].get("keywords_json") or []
            best_term = ""
            best_score = -1.0
            best_any = ""
            best_any_score = -1.0
            for kw in kws:
                if isinstance(kw, dict):
                    term = (kw.get("term") or "").strip()
                    try:
                        score = float(kw.get("score", 0.0) or 0.0)
                    except Exception:
                        score = 0.0
                else:
                    term = str(kw or "").strip()
                    score = 0.0
                term_norm = self._normalize_term(term)
                if not term_norm:
                    continue
                # best_any：软兜底（避免 pick 到 stopwords/无意义词）
                if term_norm not in self._stopwords and not term_norm.isdigit():
                    if score > best_any_score:
                        best_any_score = score
                        best_any = term_norm
                if not self._is_valid_term(term_norm):
                    continue
                if score > best_score:
                    best_score = score
                    best_term = term_norm
            return best_term or best_any

        # 1d 的孤立点分桶参数：
        # - 单桶最少 1 篇：保证 1d 覆盖当日全部文献；关键词门禁在后续代表术语阶段处理
        # - 不创建 other/unclustered 桶（避免出现非专业社区名）
        try:
            max_buckets = max(1, int(os.getenv("KG_1D_ISOLATE_MAX_BUCKETS", "500")))
        except Exception:
            max_buckets = 500
        try:
            min_bucket_size = max(1, int(os.getenv("KG_1D_ISOLATE_MIN_BUCKET_SIZE", "1")))
        except Exception:
            min_bucket_size = 1

        buckets: dict[str, list[str]] = {}
        for node in missing:
            key = _get_main_kw(node)
            if not key:
                key = "emerging research"
            buckets.setdefault(key, []).append(node)

        sorted_buckets = sorted(buckets.items(), key=lambda kv: len(kv[1]), reverse=True)

        # 记录预设标签，后续跳过 LLM 命名（避免“混合桶”导致标签跑偏）
        isolate_labels: dict[str, str] = {}

        next_idx = 1
        while f"i{next_idx}" in communities:
            next_idx += 1

        for term, nodes in sorted_buckets:
            if len(nodes) < min_bucket_size:
                continue
            cid = f"i{next_idx}"
            next_idx += 1
            communities[cid] = nodes
            isolate_labels[cid] = term
        # 说明：不再创建 i_other/other 桶，避免出现“other / unclustered”等非专业社区名。
        # 关键词门禁在 representative_terms 阶段统一处理；这里优先保证覆盖与可追溯性。

        try:
            graph.graph.setdefault("isolate_labels", {}).update(isolate_labels)
            graph.graph["isolate_nodes_count"] = len(missing)
        except Exception:
            pass

        logger.info(
            "1d coverage fix: %s missing nodes bucketed into %s groups",
            len(missing),
            len(isolate_labels),
        )
        return communities

    async def _ensure_keywords_in_memory(self, papers: list[dict], persist_to_db: bool = True) -> list[dict]:
        """
        确保每篇paper都有keywords_json
        
        Args:
            papers: 文献列表
            persist_to_db: 是否将抽取的keywords持久化到数据库（默认True）
        
        Returns:
            补全keywords后的文献列表
        """
        enriched = []
        updated_records = []
        
        # 分批并发处理（并发可由环境变量覆盖）
        try:
            import os
            batch_size = max(1, int(os.getenv("KG_KW_CONCURRENCY", "10")))
        except Exception:
            batch_size = 10  # 回退到默认
        try:
            import os
            persist_flush = max(50, int(os.getenv("KG_KW_PERSIST_FLUSH", "500")))
        except Exception:
            persist_flush = 500
        total = len(papers)
        
        for batch_start in range(0, total, batch_size):
            batch_end = min(batch_start + batch_size, total)
            batch = papers[batch_start:batch_end]
            
            logger.info(f"🔄 抽取关键词进度: {batch_start}/{total} -> {batch_end}/{total}")
            
            # 并发抽取当前批次
            tasks = []
            for p in batch:
                tasks.append(self._extract_keywords_for_paper(p))
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 处理结果
            for p, result in zip(batch, results):
                if isinstance(result, Exception):
                    logger.error(f"抽取失败 PMID={p.get('pmid')}: {result!r}")
                    # 禁用回退：不写入关键词
                    p["keywords_json"] = []
                else:
                    p["keywords_json"] = result
                    
                    if persist_to_db and result:
                        updated_records.append({
                            "pmid": p.get("pmid"),
                            "doi": p.get("doi"),
                            "source": p.get("source"),
                            "keywords_json": result
                        })
                
                enriched.append(p)

            # 分段落库，避免大窗口一次性持久化导致内存峰值过高/中途失败丢进度
            if persist_to_db and len(updated_records) >= persist_flush:
                chunk = updated_records
                updated_records = []
                await self._persist_keywords_to_db(chunk)
                logger.info(f"✅ 持久化 {len(chunk)} 条keywords到数据库 (flush)")
        
        # 批量持久化到数据库
        if persist_to_db and updated_records:
            await self._persist_keywords_to_db(updated_records)
            logger.info(f"✅ 持久化 {len(updated_records)} 条keywords到数据库")
        
        return enriched
    
    async def _extract_keywords_for_paper(self, paper: dict) -> list[dict]:
        """为单篇文献抽取关键词"""
        title = paper.get("title", "") or ""
        abstract = paper.get("abstract") or ""
        pmid = paper.get("pmid")

        kws = paper.get("keywords_json") or []
        if kws:
            # 质量门禁：如果现有关键词有效术语过少或劣质占比高，则尝试重抽
            eff = self._filter_valid_terms(kws)
            if len(eff) >= 3 and len(eff) >= max(3, int(0.5 * len(kws))):
                return eff
            # 尝试重抽
            new_kws = await self._try_extract_with_llm(paper)
            if new_kws:
                return new_kws
            # 否则返回过滤后的旧词（不为空则至少是干净子集）
            return eff

        # LLM-only：没有关键词时必须走 LLM 抽取（不允许规则fallback）
        if self.kw_extractor is None:
            raise RuntimeError("KeywordExtractor is not available (missing API key/config)")
        return await self._try_extract_with_llm(paper)

    async def _try_extract_with_llm(self, paper: dict) -> list[dict]:
        title = paper.get("title", "") or ""
        abstract = paper.get("abstract") or ""
        kws = await self.kw_extractor.extract_keywords(title, abstract)
        seen = set()
        merged: list[dict] = []
        for kw in (kws or []):
            if not isinstance(kw, dict):
                continue
            term = (kw.get("term") or "").strip().lower()
            if term and term not in seen:
                merged.append(
                    {
                        "term": term,
                        "source": kw.get("source", "llm_tiab"),
                        "score": float(kw.get("score", 0.8)),
                    }
                )
                seen.add(term)
        return merged[:15]

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

    def _sanitize_llm_label(self, main_label: str, candidates: list[str], fallback_terms: list[dict] | None = None) -> tuple[str, list[str]]:
        """清洗社区主标签，避免出现 community/other/unclustered 等无意义命名。

        规则：
        - 优先使用 LLM main_label（若通过 _is_valid_term）
        - 否则尝试 candidates 中第一个有效术语
        - 仍无则回退到 TF-IDF top_terms 中第一个有效术语
        """
        label_norm = self._normalize_term(main_label or "")
        cand_norms: list[str] = []
        for c in (candidates or []):
            s = self._normalize_term(str(c or ""))
            if s:
                cand_norms.append(s)

        final_label = label_norm if self._is_valid_term(label_norm) else ""

        if not final_label:
            for c in cand_norms:
                if self._is_valid_term(c):
                    final_label = c
                    break

        if not final_label:
            for t in (fallback_terms or []):
                s = self._normalize_term(str((t or {}).get("term", "") or ""))
                if self._is_valid_term(s):
                    final_label = s
                    break

        # candidates：去重 + 过滤无效项 + 排除主标签
        final_candidates: list[str] = []
        seen: set[str] = set()
        for c in cand_norms:
            if not c or c == final_label:
                continue
            if c in seen:
                continue
            if not self._is_valid_term(c):
                continue
            seen.add(c)
            final_candidates.append(c)

        return final_label, final_candidates

    def _filter_valid_terms(self, kws: list[dict]) -> list[dict]:
        result = []
        seen = set()
        for kw in (kws or []):
            term = self._normalize_term((kw.get("term") if isinstance(kw, dict) else str(kw)) or "")
            if not term or term in seen:
                continue
            if not self._is_valid_term(term):
                continue
            seen.add(term)
            result.append({
                "term": term,
                "source": (kw.get("source") if isinstance(kw, dict) else "title") or "title",
                "score": float((kw.get("score") if isinstance(kw, dict) else 0.8) or 0.8)
            })
        return result
    
    async def _persist_keywords_to_db(self, records: list[dict]):
        """将抽取的keywords批量写入数据库（批量UPDATE，避免逐条SELECT/UPDATE的性能瓶颈）"""
        if not records:
            return

        try:
            import os
            db_chunk = max(50, int(os.getenv("KG_KW_DB_CHUNK", "200")))
        except Exception:
            db_chunk = 200

        # 归一化并分桶
        lit_rows: list[tuple[str, str]] = []
        lit_doi_rows: list[tuple[str, str]] = []
        j_doi_rows: list[tuple[str, str]] = []
        j_pmid_rows: list[tuple[str, str]] = []

        for record in records:
            try:
                source = (record.get("source") or "").strip()
                pmid = record.get("pmid")
                doi = (record.get("doi") or "").strip().lower() or None
                keywords = record.get("keywords_json") or []
                if not keywords:
                    continue

                payload = json.dumps(keywords, ensure_ascii=False)

                if source == "literature":
                    if pmid:
                        lit_rows.append((str(pmid), payload))
                    elif doi:
                        lit_doi_rows.append((doi, payload))
                else:
                    if doi:
                        j_doi_rows.append((doi, payload))
                    elif pmid:
                        j_pmid_rows.append((str(pmid), payload))
            except Exception as e:
                logger.warning(f"持久化keywords预处理失败 PMID={record.get('pmid')} DOI={record.get('doi')}: {e!r}")

        async def _bulk_update(table: str, key_col: str, rows: list[tuple[str, str]]):
            if not rows:
                return
            for start in range(0, len(rows), db_chunk):
                chunk = rows[start : start + db_chunk]
                values_sql = ", ".join([f"(:k{i}, :v{i})" for i in range(len(chunk))])
                params = {}
                for i, (k, v) in enumerate(chunk):
                    params[f"k{i}"] = k
                    params[f"v{i}"] = v
                sql = f"""
                UPDATE {table} AS t
                SET keywords_json = v.keywords_json::jsonb
                FROM (VALUES {values_sql}) AS v({key_col}, keywords_json)
                WHERE t.{key_col} = v.{key_col}
                """
                await self.db.execute(text(sql), params)
                await self.db.commit()

        # 文献流：优先 PMID；DOI 作为兜底
        await _bulk_update("literature", "pmid", lit_rows)
        await _bulk_update("literature", "doi", lit_doi_rows)
        # 顶刊/CNS：优先 DOI；PMID 作为兜底
        await _bulk_update("journal_articles", "doi", j_doi_rows)
        await _bulk_update("journal_articles", "pmid", j_pmid_rows)
    
    def generate_snapshot_id(self, source: str, window: str, as_of: str) -> str:
        """生成快照唯一ID"""
        key = f"{source}:{window}:{as_of}"
        return hashlib.md5(key.encode()).hexdigest()[:16]
    
    async def create_or_get_snapshot(
        self,
        source: str,
        window: str,
        as_of: datetime
    ) -> Optional[GraphSnapshot]:
        """
        创建或获取快照
        
        Args:
            source: 数据源 (literature|sports_journals|cns)
            window: 时间窗口 (1d|7d|30d|180d)
            as_of: 截止日期
            
        Returns:
            GraphSnapshot对象
        """
        snapshot_id = self.generate_snapshot_id(source, window, as_of.date().isoformat())
        
        # 检查是否已存在
        query = select(GraphSnapshot).where(GraphSnapshot.snapshot_id == snapshot_id)
        result = await self.db.execute(query)
        existing = result.scalar_one_or_none()
        
        # 可选强制重建
        import os
        force_rebuild = os.getenv("KG_FORCE_REBUILD", "0").lower() in ("1", "true", "yes")
        allow_empty = os.getenv("KG_ALLOW_EMPTY_SNAPSHOT", "0").lower() in ("1", "true", "yes")
        # 1d：允许生成空快照（避免因“最小社区/关键词门禁”导致接口 404）
        allow_empty = allow_empty or window == "1d"
        if existing and not force_rebuild:
            logger.info(f"Snapshot {snapshot_id} already exists")
            return existing
        elif existing and force_rebuild:
            logger.info(f"Forcing rebuild of snapshot {snapshot_id}")
            # 先删除旧记录
            await self.db.execute(delete(CommunitySnapshot).where(CommunitySnapshot.snapshot_id == snapshot_id))
            await self.db.execute(delete(GraphSnapshot).where(GraphSnapshot.snapshot_id == snapshot_id))
            await self.db.commit()
        
        # 创建新快照
        logger.info(f"Creating new snapshot: source={source}, window={window}, as_of={as_of.date()}")
        
        # 1. 加载数据
        if source == "literature":
            papers = await self.data_loader.load_literature_data(window, as_of)
        elif source == "sports_journals":
            papers = await self.data_loader.load_sports_journals_data(window, as_of)
        elif source == "cns":
            papers = await self.data_loader.load_cns_data(window, as_of)
        else:
            logger.error(f"Invalid source: {source}")
            return None
        
        if not papers:
            logger.warning(f"No papers found for {source}/{window}/{as_of.date()}")
            if allow_empty:
                meta = {
                    "node_count": 0,
                    "edge_count": 0,
                    "community_count": 0,
                    "keywords_coverage": 0.0,
                    "detector": "none",
                    "degraded": True,
                }
                snapshot = GraphSnapshot(
                    snapshot_id=snapshot_id,
                    source=source,
                    window=window,
                    as_of=as_of.date(),
                    meta=meta,
                    communities_summary=[]
                )
                self.db.add(snapshot)
                await self.db.commit()
                await self.db.refresh(snapshot)
                logger.info(f"✅ Empty snapshot {snapshot_id} created (no papers)")
                return snapshot
            return None
        
        # 2. 确保关键字（LLM-only，并持久化到数据库）
        papers = await self._ensure_keywords_in_memory(papers, persist_to_db=True)

        # 2.5 调整图构建阈值（小样本/短窗口降低阈值）
        try:
            import os
            tau_default = float(os.getenv("KG_TAU_DEFAULT", "0.20"))
            # 1d 需要更稠密的边以避免大量孤立点（否则今日热点看起来“只用到了几篇”）
            tau_small = float(os.getenv("KG_TAU_SMALL", "0.04"))
        except Exception:
            tau_default = 0.20
            tau_small = 0.04
        use_tau = tau_default
        # 1d 的样本通常较小且关键词重叠弱，使用更低阈值避免出现“有节点但无边”的空社区结果
        if window == "1d" or len(papers) < 300 or (source in ("sports_journals", "cns") and window in ("7d", "30d")):
            use_tau = tau_small
        self.graph_builder.tau = use_tau

        # 3. 构建图
        graph = self.graph_builder.build_graph(papers)
        
        if graph.number_of_nodes() == 0:
            logger.warning("Empty graph generated")
            if allow_empty:
                meta = {
                    "node_count": 0,
                    "edge_count": 0,
                    "community_count": 0,
                    "keywords_coverage": round(graph.graph.get('keywords_coverage', 0.0), 3) if isinstance(graph.graph.get('keywords_coverage', 0.0), (int, float)) else 0.0,
                    "detector": self.comm_detector.detector_name,
                    "degraded": True,
                }
                snapshot = GraphSnapshot(
                    snapshot_id=snapshot_id,
                    source=source,
                    window=window,
                    as_of=as_of.date(),
                    meta=meta,
                    communities_summary=[]
                )
                self.db.add(snapshot)
                await self.db.commit()
                await self.db.refresh(snapshot)
                logger.info(f"✅ Empty snapshot {snapshot_id} created (empty graph)")
                return snapshot
            return None
        
        # 4. 检测社区
        communities = self.comm_detector.detect_communities(graph)

        # 1d：补齐孤立点，确保“当日上新”图谱覆盖全部文献
        if window == "1d":
            # sports_journals 小样本（<=20）已有 singleton 兜底展示，不必额外分桶
            if not (source == "sports_journals" and len(papers) <= 20):
                communities = self._ensure_full_coverage_for_1d(communities, graph)

        # 社区门禁：默认过滤 size<2；但 1d 需要覆盖“当日入库的全部文献”，因此保留 singleton 社区
        # （关键词门禁在 representative_terms / 关键词面板阶段统一处理）
        if window != "1d":
            communities = {cid: nodes for cid, nodes in (communities or {}).items() if len(nodes or []) >= 2}
        else:
            communities = {cid: nodes for cid, nodes in (communities or {}).items() if nodes}

        if not communities:
            logger.warning("No communities detected")
            if allow_empty:
                keywords_coverage = graph.graph.get('keywords_coverage', 0.0)
                meta = {
                    "node_count": graph.number_of_nodes(),
                    "edge_count": graph.number_of_edges(),
                    "community_count": 0,
                    "keywords_coverage": round(keywords_coverage if isinstance(keywords_coverage, (int, float)) else 0.0, 3),
                    "detector": self.comm_detector.detector_name,
                    "degraded": True,
                }
                snapshot = GraphSnapshot(
                    snapshot_id=snapshot_id,
                    source=source,
                    window=window,
                    as_of=as_of.date(),
                    meta=meta,
                    communities_summary=[]
                )
                self.db.add(snapshot)
                await self.db.commit()
                await self.db.refresh(snapshot)
                logger.info(f"✅ Empty snapshot {snapshot_id} created (no communities)")
                return snapshot
            else:
                return None
        
        # 5. 计算全局指标
        keywords_coverage = graph.graph.get('keywords_coverage', 0.0)
        modularity = self.comm_detector.compute_modularity(communities, graph)
        
        meta = {
            "node_count": graph.number_of_nodes(),
            "edge_count": graph.number_of_edges(),
            "community_count": len(communities),
            "keywords_coverage": round(keywords_coverage, 3),
            "detector": self.comm_detector.detector_name,
            "degraded": keywords_coverage < 0.5
        }
        
        # 6. 生成社区摘要（TF-IDF代表术语 + LLM 聚类命名）
        communities_summary = []
        # 按社区规模降序，优先为大的社区生成标签 / 摘要
        sorted_items = sorted(communities.items(), key=lambda kv: len(kv[1]), reverse=True)
        # 1d：尽量返回更多社区，避免“当日上新只显示一小部分”。
        # 其他窗口仍限制 top50，避免快照/前端过重。
        limit_n = 50
        if window == "1d":
            try:
                import os
                limit_n = max(50, int(os.getenv("KG_1D_COMMUNITY_LIMIT", "200")))
            except Exception:
                limit_n = 200
        limited_items = sorted_items[:limit_n]

        isolate_labels = graph.graph.get("isolate_labels") if isinstance(graph.graph, dict) else None
        isolate_labels = isolate_labels or {}

        # 并发执行 LLM 标注（全局并发可由环境覆盖）
        import os
        try:
            global_cc = int(os.getenv("KG_LLM_CONCURRENCY", "64"))
        except Exception:
            global_cc = 64
        # 为综合顶刊（CNS）使用通用顶刊提示词，其余使用sports
        profile = "general_top" if source == "cns" else "sports"
        # 仅调用一次：对全量 communities 打标签（避免 top50 与 detail 重复打标）
        items_to_label = [(cid, nodes) for cid, nodes in communities.items() if cid not in isolate_labels]
        labels = await self._label_communities_with_llm(
            items_to_label, graph, window, as_of.date().isoformat(), concurrency=global_cc, profile=profile
        )
        for cid, term in isolate_labels.items():
            labels[cid] = {
                "insufficient_signal": True,
                "main_label": term,
                "candidates": [],
                "rationale": "",
                "evidence_map": [],
            }

        for comm_id, nodes in limited_items:
            # 代表论文（供前端展示）- 放宽同年限制，确保能返回足够多的文献
            top_papers = self.comm_detector.extract_top_papers(nodes, graph, top_k=10, same_year_limit=10)
            activity = self.graph_builder.compute_activity(nodes, graph, as_of.date().isoformat(), window)

            # 基础代表术语：始终基于TF-IDF前若干关键词（即使LLM不可用）
            raw_terms = self._collect_top_terms_for_community(nodes, graph, top_k=10) or []
            # 关键词门禁：每个关键词至少命中 2 篇 top_papers（避免“关键词下无文章/仅1篇”）
            support: dict[str, int] = {}
            for p in top_papers or []:
                seen = set()
                for kw in p.get("keywords") or []:
                    tn = self._normalize_term(str(kw or ""))
                    if tn:
                        seen.add(tn)
                for tn in seen:
                    support[tn] = support.get(tn, 0) + 1

            llm_res = labels.get(comm_id, {}) if isinstance(labels, dict) else {}
            main_label_raw = (llm_res.get("main_label") or "").strip()
            candidates_raw = llm_res.get("candidates") or []
            rationale = (llm_res.get("rationale") or "").strip()

            main_label, candidates = self._sanitize_llm_label(
                main_label_raw,
                [str(c) for c in candidates_raw if c is not None],
                fallback_terms=raw_terms,
            )

            # representative_terms：基于 LLM 抽取的关键词（keywords_json）做社区内汇总，
            # 并强制每个关键词至少命中 2 篇 top_papers。
            rep_terms: list[dict] = []
            eligible = []
            for t in raw_terms:
                term = self._normalize_term(str((t or {}).get("term", "") or ""))
                df = int((t or {}).get("df") or 0)
                if not term or df < 2:
                    continue
                if support.get(term, 0) < 2:
                    continue
                if not self._is_valid_term(term):
                    continue
                try:
                    tfidf = float((t or {}).get("tfidf") or 0.0)
                except Exception:
                    tfidf = 0.0
                eligible.append((term, tfidf))
            # 去重并按 TF-IDF 排序
            seen_terms: set[str] = set()
            eligible_sorted = []
            for term, tfidf in sorted(eligible, key=lambda x: x[1], reverse=True):
                if term in seen_terms:
                    continue
                eligible_sorted.append((term, tfidf))
                seen_terms.add(term)
                if len(eligible_sorted) >= 6:
                    break
            max_tfidf = max((tfidf for _, tfidf in eligible_sorted), default=1.0) or 1.0
            for term, tfidf in eligible_sorted:
                rep_terms.append({"term": term, "score": round(min(1.0, tfidf / max_tfidf), 3)})

            # 摘要：仅使用 LLM rationale，避免用低质量单词拼接
            summary_text = rationale or None

            communities_summary.append({
                "community_id": comm_id,
                "size": len(nodes),
                "activity": round(activity, 3),
                "representative_terms": rep_terms,
                "llm_label": main_label,
                "llm_candidates": candidates,
                "top_papers": top_papers,
                # 精简版摘要：随快照固定，不每天变动
                "summary": summary_text,
            })
        
        # 7. 保存快照到数据库
        snapshot = GraphSnapshot(
            snapshot_id=snapshot_id,
            source=source,
            window=window,
            as_of=as_of.date(),
            meta=meta,
            communities_summary=communities_summary
        )
        
        self.db.add(snapshot)
        
        # 8. 保存社区详情（含 LLM 标签与摘要）
        for comm_id, nodes in communities.items():
            top_papers = self.comm_detector.extract_top_papers(nodes, graph, top_k=15, same_year_limit=15)
            activity = self.graph_builder.compute_activity(nodes, graph, as_of.date().isoformat(), window)
            llm_res = labels.get(comm_id, {}) if isinstance(labels, dict) else {}
            main_label_raw = (llm_res.get("main_label") or "").strip()
            candidates_raw = (llm_res.get("candidates") or [])
            rationale = (llm_res.get("rationale") or "").strip()

            main_label, candidates = self._sanitize_llm_label(
                main_label_raw,
                [str(c) for c in candidates_raw if c is not None],
                fallback_terms=None,
            )
            if not main_label:
                raw_terms = self._collect_top_terms_for_community(nodes, graph, top_k=10) or []
                main_label, candidates = self._sanitize_llm_label(
                    main_label_raw,
                    [str(c) for c in candidates_raw if c is not None],
                    fallback_terms=raw_terms,
                )

            # 详情页关键词：同样做“至少 2 篇命中”门禁
            raw_terms = self._collect_top_terms_for_community(nodes, graph, top_k=20) or []
            support: dict[str, int] = {}
            for p in top_papers or []:
                seen = set()
                for kw in p.get("keywords") or []:
                    tn = self._normalize_term(str(kw or ""))
                    if tn:
                        seen.add(tn)
                for tn in seen:
                    support[tn] = support.get(tn, 0) + 1
            eligible = []
            for t in raw_terms:
                term = self._normalize_term(str((t or {}).get("term", "") or ""))
                df = int((t or {}).get("df") or 0)
                if not term or df < 2:
                    continue
                if support.get(term, 0) < 2:
                    continue
                if not self._is_valid_term(term):
                    continue
                try:
                    tfidf = float((t or {}).get("tfidf") or 0.0)
                except Exception:
                    tfidf = 0.0
                eligible.append((term, tfidf))
            seen_terms: set[str] = set()
            eligible_sorted = []
            for term, tfidf in sorted(eligible, key=lambda x: x[1], reverse=True):
                if term in seen_terms:
                    continue
                eligible_sorted.append((term, tfidf))
                seen_terms.add(term)
                if len(eligible_sorted) >= 10:
                    break
            max_tfidf = max((tfidf for _, tfidf in eligible_sorted), default=1.0) or 1.0
            rep_terms = [{"term": term, "score": round(min(1.0, tfidf / max_tfidf), 3)} for term, tfidf in eligible_sorted]

            comm_snapshot = CommunitySnapshot(
                snapshot_id=snapshot_id,
                community_id=comm_id,
                size=len(nodes),
                activity=round(activity, 3),
                representative_terms=rep_terms,
                top_papers=top_papers,
                # 完整版摘要：优先LLM rationale；若缺失则保持为空
                summary=rationale or None,
                graph_data=None,
                metrics={
                    "modularity": modularity,
                    "density": round(nx.density(graph.subgraph(nodes)), 3),
                    "coverage": round(len(nodes) / max(graph.number_of_nodes(), 1), 3),
                    "keywords_coverage": round(keywords_coverage, 3),
                    "detector": self.comm_detector.detector_name,
                    "degraded": keywords_coverage < 0.5
                }
            )
            self.db.add(comm_snapshot)
        
        await self.db.commit()
        await self.db.refresh(snapshot)
        
        logger.info(f"✅ Snapshot {snapshot_id} created successfully with {len(communities)} communities")
        
        return snapshot

    async def _label_communities_with_llm(self, items: list[tuple[str, list[str]]], graph: nx.Graph, window: str, as_of: str, concurrency: int = 64, profile: str = "sports") -> dict:
        """使用 LLM 为社区打标签（并发限制）。返回 {community_id: result_dict}。
        profile: sports | general_top
        """
        if not items or self.llm_clusterer is None:
            return {}

        # 预先计算每个社区的 top_terms + sample_titles
        prepared: dict[str, dict] = {}
        for comm_id, nodes in items:
            top_terms = self._collect_top_terms_for_community(nodes, graph, top_k=80)
            sample_titles = self._collect_sample_titles(nodes, graph, m=10)
            prepared[comm_id] = {"terms": top_terms, "titles": sample_titles}

        sem = asyncio.Semaphore(max(1, int(concurrency)))
        results: dict[str, dict] = {}

        async def _run(comm_id: str):
            async with sem:
                payload = prepared.get(comm_id) or {"terms": [], "titles": []}
                try:
                    res = await self.llm_clusterer.cluster_for_community(payload["terms"], payload["titles"], window, as_of, profile=profile)
                except Exception:
                    res = {"insufficient_signal": True, "main_label": "", "candidates": [], "rationale": "error", "evidence_map": []}
                results[comm_id] = res

        await asyncio.gather(*[_run(cid) for cid, _ in items])
        return results

    def _collect_top_terms_for_community(self, community_nodes: list[str], graph: nx.Graph, top_k: int = 80) -> list[dict]:
        """统计社区内术语的 TF-IDF 加权与社区内文档频次（df_comm）。
        注意：为遵循“聚类阶段不使用黑名单”的要求，这里不做停用词/禁用词过滤，仅做规范化与最小长度校验。
        """
        builder = graph.graph.get('builder')
        idf_cache = getattr(builder, 'idf_cache', {}) if builder is not None else {}
        term_scores: dict[str, float] = {}
        term_df_comm: dict[str, int] = {}

        for node in community_nodes:
            seen_terms = set()
            for kw in graph.nodes[node].get("keywords_json", []) or []:
                if isinstance(kw, dict) and "term" in kw:
                    t = (kw["term"] or "").strip().lower()
                    if not t:
                        continue
                    # 仅规范化（不做停用词/禁用词过滤）
                    t_norm = self._normalize_term(t)
                    if not t_norm or len(t_norm) < 3:
                        continue
                    term_scores[t_norm] = term_scores.get(t_norm, 0.0) + float(idf_cache.get(t_norm, 1.0))
                    if t_norm not in seen_terms:
                        term_df_comm[t_norm] = term_df_comm.get(t_norm, 0) + 1
                        seen_terms.add(t_norm)

        items = sorted(term_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        return [
            {"term": term, "df": int(term_df_comm.get(term, 0)), "tfidf": round(score, 6)}
            for term, score in items
        ]

    def _collect_sample_titles(self, community_nodes: list[str], graph: nx.Graph, m: int = 10) -> list[str]:
        titles = []
        for node in community_nodes:
            t = graph.nodes[node].get("title")
            if t:
                titles.append(t)
            if len(titles) >= m:
                break
        return titles
