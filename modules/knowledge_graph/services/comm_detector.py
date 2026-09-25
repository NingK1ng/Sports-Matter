"""
社区检测服务 - 基于图结构进行社区发现
"""
import logging
from typing import Dict, List, Set
import networkx as nx
from networkx.algorithms import community
import re

logger = logging.getLogger(__name__)


class CommunityDetector:
    """社区检测器"""
    
    def __init__(self, min_community_size: int = 2):
        """
        初始化社区检测器
        
        Args:
            min_community_size: 最小社区大小（过滤小社区）
        """
        self.min_community_size = min_community_size
        self.detector_name = "louvain"  # 使用的检测器名称
        # 基础停用词（英文常见停用 + 一些泛化弱区分词）
        self.stopwords = {
            "a","an","the","and","or","of","to","in","on","for","with","without","by","from","as","at","is","are","was","were","be","been","being",
            "this","that","these","those","it","its","their","his","her","we","you","they","our","my","your","not","no","yes",
            "what","why","how","current","future","past","new","novel","more","less","many","various","several","impact","effect","effects","role","study","studies",
            "research","analysis","methods","approach","approaches","factors","outcomes","population","participants","care","healthcare","professional","professionals","training",
            "patient","patients","male","female","men","women","home","case","cases","group","groups","trial","trials",
            "lesson","lessons","learned","insight","insights"}
        # 文章类型等应剔除的短语
        self.banned_terms = {
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

    def _is_valid_term(self, term: str) -> bool:
        if not term or len(term) < 3:
            return False
        if term.isdigit():
            return False
        # 滤去纯字母但极短或通用词
        if term in self.stopwords:
            return False
        for banned in self.banned_terms:
            if term == banned or banned in term:
                return False
        # 连词/介词等片段
        if term in {"and","or","the","of","to","in","on","for","with","without","by"}:
            return False
        return True
    
    def detect_communities(self, graph: nx.Graph) -> Dict[str, List[str]]:
        """
        检测图中的社区
        
        Args:
            graph: NetworkX图对象
            
        Returns:
            社区字典 {community_id: [node1, node2, ...]}
        """
        if graph.number_of_nodes() == 0:
            logger.warning("Empty graph provided for community detection")
            return {}
        
        logger.info(f"Detecting communities in graph with {graph.number_of_nodes()} nodes...")
        
        try:
            # 使用Louvain算法进行社区检测
            communities_generator = community.louvain_communities(
                graph,
                weight='weight',
                resolution=1.0,
                seed=42
            )
            
            # 转换为字典格式
            communities = {}
            for i, comm_nodes in enumerate(communities_generator):
                if len(comm_nodes) >= self.min_community_size:
                    community_id = f"c{i+1}"
                    communities[community_id] = list(comm_nodes)
            
            logger.info(f"✅ Detected {len(communities)} communities (Louvain algorithm)")
            self.detector_name = "louvain"
            
            return communities
        
        except Exception as e:
            logger.error(f"Community detection failed: {e}")
            
            # 降级：使用连通分量
            logger.warning("Falling back to connected components...")
            return self._fallback_detection(graph)
    
    def _fallback_detection(self, graph: nx.Graph) -> Dict[str, List[str]]:
        """
        降级检测：使用连通分量
        
        Args:
            graph: NetworkX图对象
            
        Returns:
            社区字典
        """
        communities = {}
        
        for i, component in enumerate(nx.connected_components(graph)):
            if len(component) >= self.min_community_size:
                community_id = f"c{i+1}"
                communities[community_id] = list(component)
        
        logger.info(f"✅ Detected {len(communities)} communities (fallback: connected components)")
        self.detector_name = "fallback"
        
        return communities
    
    def extract_representative_terms(
        self,
        community_nodes: List[str],
        graph: nx.Graph,
        top_k: int = 10
    ) -> List[Dict[str, any]]:
        """
        提取社区的代表性关键词（TF-IDF加权）
        
        Args:
            community_nodes: 社区节点列表
            graph: 原始图
            top_k: 返回Top-K个关键词
            
        Returns:
            关键词列表 [{term: str, score: float}]
        """
        # 统计关键词的TF-IDF加权频次
        term_tfidf = {}
        
        # 从graph获取IDF（如果graph_builder缓存了）
        builder = graph.graph.get('builder')
        idf_cache = getattr(builder, 'idf_cache', {}) if builder is not None else {}
        
        for node in community_nodes:
            keywords_json = graph.nodes[node].get("keywords_json", [])
            for kw in keywords_json:
                if isinstance(kw, dict) and "term" in kw:
                    term = kw["term"]
                    norm = self._normalize_term(term)
                    if not self._is_valid_term(norm):
                        continue
                    idf_weight = idf_cache.get(norm, idf_cache.get(norm.replace(" ", ""), 1.0))
                    term_tfidf[norm] = term_tfidf.get(norm, 0) + idf_weight
        
        if not term_tfidf:
            return []
        
        # 排序并归一化分数
        max_score = max(term_tfidf.values()) if term_tfidf else 1.0
        sorted_terms = sorted(term_tfidf.items(), key=lambda x: x[1], reverse=True)[:top_k]
        
        # 转换为标准格式
        result = [
            {
                "term": term,
                "score": round(score / max_score, 3)
            }
            for term, score in sorted_terms
        ]
        
        return result
    
    def extract_top_papers(
        self,
        community_nodes: List[str],
        graph: nx.Graph,
        top_k: int = 10,
        same_year_limit: int = 3,
        same_journal_limit: int = 2
    ) -> List[Dict[str, any]]:
        """
        提取社区的Top-K论文（带多样性约束）
        
        Args:
            community_nodes: 社区节点列表
            graph: 原始图
            top_k: 返回Top-K篇论文
            same_year_limit: 同年论文数量上限
            same_journal_limit: 同刊论文数量上限（暂未实现）
            
        Returns:
            论文列表 [{pmid, title, abstract, score, pub_date}]
        """
        # 计算每个节点的PageRank分数（作为重要性指标）
        try:
            pagerank_scores = nx.pagerank(
                graph.subgraph(community_nodes),
                weight='weight'
            )
        except:
            # 降级：使用度中心性
            pagerank_scores = nx.degree_centrality(graph.subgraph(community_nodes))
        
        # 按分数排序
        sorted_nodes = sorted(
            pagerank_scores.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        # 应用多样性约束
        selected_papers = []
        year_counter = {}
        
        for node, score in sorted_nodes:
            if len(selected_papers) >= top_k:
                break
            
            # 获取论文信息
            node_data = graph.nodes[node]
            pub_date = node_data.get("pub_date", "")
            year = pub_date[:4] if pub_date and len(pub_date) >= 4 else "unknown"
            
            # 检查同年约束
            if year != "unknown" and year_counter.get(year, 0) >= same_year_limit:
                continue
            
            # 添加论文
            keywords = []
            try:
                for kw in (node_data.get("keywords_json") or [])[:20]:
                    if isinstance(kw, dict) and "term" in kw:
                        term = (kw.get("term") or "").strip()
                        if term:
                            keywords.append(term)
                    elif isinstance(kw, str):
                        term = kw.strip()
                        if term:
                            keywords.append(term)
            except Exception:
                keywords = []
            selected_papers.append({
                "pmid": node,
                "title": node_data.get("title", ""),
                "abstract": node_data.get("abstract", "")[:300],  # 限制摘要长度
                "keywords": keywords[:10],
                "score": round(score, 3),
                "pub_date": pub_date
            })
            
            # 更新计数器
            if year != "unknown":
                year_counter[year] = year_counter.get(year, 0) + 1
        
        return selected_papers
    
    def compute_modularity(
        self,
        communities: Dict[str, List[str]],
        graph: nx.Graph
    ) -> float:
        """
        计算模块度（衡量社区划分质量）
        
        Args:
            communities: 社区字典
            graph: 原始图
            
        Returns:
            模块度分数 [-0.5, 1]
        """
        if not communities or graph.number_of_edges() == 0:
            return 0.0
        
        try:
            # 转换为NetworkX社区格式
            community_list = [set(nodes) for nodes in communities.values()]
            modularity_score = community.modularity(graph, community_list, weight='weight')
            return round(modularity_score, 3)
        except Exception as e:
            logger.warning(f"Failed to compute modularity: {e}")
            return 0.0
