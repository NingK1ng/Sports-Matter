"""
图谱构建服务 - 基于keywords的TF-IDF Jaccard算法
"""
import logging
import math
from typing import List, Dict, Tuple
from collections import defaultdict
import networkx as nx
import re

logger = logging.getLogger(__name__)


class GraphBuilder:
    """图谱构建器（基于关键词共现）"""
    
    def __init__(
        self,
        topk_candidates: int = 200,  # 候选集大小
        topk_edges: int = 15,        # 每个节点保留Top-K边
        tau: float = 0.20            # 边权重阈值（与规范一致的默认阈值）
    ):
        self.topk_candidates = topk_candidates
        self.topk_edges = topk_edges
        self.tau = tau
        self.idf_cache = {}  # IDF缓存
        # 术语过滤（与社区检测保持一致的最小集合）
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
    
    def _build_inverted_index(self, papers: List[Dict]) -> Dict[str, List[int]]:
        """
        构建倒排索引：term -> [paper_indices]
        
        Args:
            papers: 文献列表
            
        Returns:
            倒排索引字典
        """
        inverted_index = defaultdict(list)
        
        for idx, paper in enumerate(papers):
            keywords = paper.get("keywords_json", [])
            if not keywords:
                continue
            
            # 提取term列表
            terms = set()
            for kw in keywords:
                if isinstance(kw, dict) and "term" in kw:
                    norm = self._normalize_term(kw["term"]) 
                    if self._is_valid_term(norm):
                        terms.add(norm)
            
            # 添加到倒排索引
            for term in terms:
                inverted_index[term].append(idx)
        
        logger.info(f"倒排索引构建完成: {len(inverted_index)} 个关键词")
        return dict(inverted_index)
    
    def _compute_idf(self, papers: List[Dict]) -> Dict[str, float]:
        """
        计算IDF值：log(N / df)
        
        Args:
            papers: 文献列表
            
        Returns:
            term -> IDF分数
        """
        n_docs = len(papers)
        doc_freq = defaultdict(int)
        
        # 统计文档频率
        for paper in papers:
            keywords = paper.get("keywords_json", [])
            if not keywords:
                continue
            
            seen_terms = set()
            for kw in keywords:
                if isinstance(kw, dict) and "term" in kw:
                    term = self._normalize_term(kw["term"])
                    if self._is_valid_term(term) and term not in seen_terms:
                        doc_freq[term] += 1
                        seen_terms.add(term)
        
        # 计算IDF（添加平滑）
        idf = {}
        for term, df in doc_freq.items():
            # 使用 log((N+1)/(df+1)) + 1 平滑，避免IDF=0
            idf[term] = math.log((n_docs + 1) / (df + 1)) + 1.0
        
        logger.info(f"IDF计算完成: {len(idf)} 个关键词")
        return idf
    
    def _get_top_candidates(
        self,
        paper_idx: int,
        papers: List[Dict],
        inverted_index: Dict[str, List[int]],
        idf: Dict[str, float],
    ) -> List[int]:
        """
        获取TopK候选文献（共现频次排序）
        
        Args:
            paper_idx: 当前文献索引
            papers: 文献列表
            inverted_index: 倒排索引
            
        Returns:
            候选文献索引列表
        """
        paper = papers[paper_idx]
        keywords = paper.get("keywords_json", [])
        
        if not keywords:
            return []
        
        # 提取当前文献的terms
        current_terms = set()
        for kw in keywords:
            if isinstance(kw, dict) and "term" in kw:
                term = self._normalize_term(kw["term"])
                if self._is_valid_term(term):
                    current_terms.add(term)
        
        # 统计候选文献的共现频次
        candidate_scores = defaultdict(float)
        
        for term in current_terms:
            if term in inverted_index:
                weight = idf.get(term, 0.0)
                for cand_idx in inverted_index[term]:
                    if cand_idx != paper_idx:  # 排除自己
                        candidate_scores[cand_idx] += weight
        
        # 按共现频次排序
        sorted_candidates = sorted(
            candidate_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        # 返回TopK
        return [idx for idx, _ in sorted_candidates[:self.topk_candidates]]
    
    def _compute_tfidf_jaccard(
        self,
        paper1: Dict,
        paper2: Dict,
        idf: Dict[str, float]
    ) -> float:
        """
        计算TF-IDF加权Jaccard相似度
        
        Args:
            paper1: 文献1
            paper2: 文献2
            idf: IDF字典
            
        Returns:
            相似度分数 [0, 1]
        """
        # 提取关键词集合
        terms1 = set()
        terms2 = set()
        
        for kw in paper1.get("keywords_json", []):
            if isinstance(kw, dict) and "term" in kw:
                t = self._normalize_term(kw["term"])
                if self._is_valid_term(t):
                    terms1.add(t)
        
        for kw in paper2.get("keywords_json", []):
            if isinstance(kw, dict) and "term" in kw:
                t = self._normalize_term(kw["term"])
                if self._is_valid_term(t):
                    terms2.add(t)
        
        if not terms1 or not terms2:
            return 0.0
        
        # 计算TF-IDF加权Jaccard
        shared_terms = terms1 & terms2
        union_terms = terms1 | terms2
        
        # 加权求和
        shared_idf_sum = sum(idf.get(term, 0.0) for term in shared_terms)
        union_idf_sum = sum(idf.get(term, 0.0) for term in union_terms)
        
        if union_idf_sum == 0:
            return 0.0
        
        return shared_idf_sum / union_idf_sum
    
    def build_graph(self, papers: List[Dict]) -> nx.Graph:
        """
        构建Paper-Paper图（基于关键词共现）
        
        Args:
            papers: 文献列表，每项包含 pmid, keywords_json
            
        Returns:
            NetworkX图对象
        """
        if not papers:
            logger.warning("No papers provided for graph construction")
            return nx.Graph()
        
        logger.info(f"Building graph with {len(papers)} papers...")
        
        # 1. 统计keywords覆盖率
        papers_with_kw = [p for p in papers if p.get("keywords_json")]
        kw_coverage = len(papers_with_kw) / len(papers) if papers else 0
        logger.info(f"Keywords coverage: {kw_coverage:.2%}")
        
        # 2. 构建倒排索引
        inverted_index = self._build_inverted_index(papers)
        
        # 3. 计算IDF
        idf = self._compute_idf(papers)
        self.idf_cache = idf
        
        # 4. 初始化图
        G = nx.Graph()
        
        # 5. 添加节点
        for paper in papers:
            G.add_node(
                paper["pmid"],
                title=paper.get("title", ""),
                abstract=paper.get("abstract", ""),
                pub_date=paper.get("publication_date") or paper.get("pub_date"),  # 兼容两种字段名
                keywords_json=paper.get("keywords_json", []),
                source=paper.get("source", "unknown")
            )
        
        # 6. 计算边
        edges_data = []
        
        for i, paper1 in enumerate(papers):
            if i % 100 == 0:
                logger.info(f"Processing paper {i}/{len(papers)}...")
            
            # 获取TopK候选
            candidates = self._get_top_candidates(i, papers, inverted_index, idf)
            
            # 计算相似度
            similarities = []
            for j in candidates:
                if j <= i:  # 避免重复
                    continue
                
                paper2 = papers[j]
                sim = self._compute_tfidf_jaccard(paper1, paper2, idf)
                
                if sim >= self.tau:
                    similarities.append((j, sim))
            
            # 排序并保留Top-K
            similarities.sort(key=lambda x: x[1], reverse=True)
            top_k = similarities[:self.topk_edges]
            
            # 添加边
            for j, sim in top_k:
                edges_data.append((paper1["pmid"], papers[j]["pmid"], sim))
        
        # 7. 批量添加边
        for src, dst, weight in edges_data:
            G.add_edge(src, dst, weight=weight)
        
        logger.info(f"✅ Graph built: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
        
        # 附加元数据
        G.graph['keywords_coverage'] = kw_coverage
        G.graph['topk_candidates'] = self.topk_candidates
        G.graph['topk_edges'] = self.topk_edges
        G.graph['tau'] = self.tau
        G.graph['builder'] = self  # 供代表性关键词抽取访问 idf_cache
        
        return G
    
    def compute_activity(
        self,
        community_nodes: List[str],
        graph: nx.Graph,
        as_of: str,
        window: str
    ) -> float:
        """
        计算社区活跃度
        
        Args:
            community_nodes: 社区节点列表（PMID）
            graph: 原始图
            as_of: 截止日期
            window: 时间窗口
            
        Returns:
            活跃度分数 [0, 1]
        """
        from datetime import datetime, timedelta
        
        # 计算活跃窗口（最近30天或window的较小值）
        window_days = {"1d": 1, "7d": 7, "30d": 30, "180d": 180}
        days = min(30, window_days.get(window, 30))
        
        as_of_date = datetime.fromisoformat(as_of).date() if isinstance(as_of, str) else as_of
        activity_start = as_of_date - timedelta(days=days)
        
        # 统计活跃期内的文献数
        active_count = 0
        for node in community_nodes:
            pub_date_str = graph.nodes[node].get("pub_date")
            if pub_date_str:
                try:
                    pub_date = datetime.fromisoformat(pub_date_str).date()
                    if pub_date >= activity_start:
                        active_count += 1
                except:
                    pass
        
        # 计算活跃度
        activity = active_count / max(len(community_nodes), 1)
        return activity
