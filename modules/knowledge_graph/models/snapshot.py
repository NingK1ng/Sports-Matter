"""
知识图谱快照数据模型
"""
from datetime import datetime
import sqlalchemy as sa
from sqlalchemy import (
    Column,
    BigInteger,
    Integer,
    String,
    Date,
    TIMESTAMP,
    Index,
    text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

from models.base import Base


class GraphSnapshot(Base):
    """图谱快照元数据表"""
    
    __tablename__ = "graph_snapshots"
    
    # 主键
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    
    # 快照唯一标识（hash(source, window, as_of)）
    snapshot_id = Column(String(64), nullable=False, unique=True, index=True, comment="快照唯一标识")
    
    # 数据源与时间窗口
    source = Column(String(50), nullable=False, comment="数据源: literature|sports_journals|cns")
    window = Column(String(10), nullable=False, comment="时间窗口: 1d|7d|30d|180d")
    as_of = Column(Date, nullable=False, comment="快照日期（UTC）")
    
    # 元数据
    meta = Column(JSONB, nullable=False, comment="图谱元数据: {node_count, edge_count, community_count, keywords_coverage, detector, degraded}")
    
    # 社区列表（轻量级，用于列表接口）
    communities_summary = Column(JSONB, nullable=False, comment="社区摘要列表: [{community_id, size, activity, representative_terms, top_papers}]")
    
    # 时间戳
    created_at = Column(TIMESTAMP, nullable=False, server_default=text("NOW()"), comment="创建时间")
    
    # 索引
    __table_args__ = (
        UniqueConstraint("source", "window", "as_of", name="uq_graph_snapshots_source_window_date"),
        Index("idx_graph_snapshots_source_window", "source", "window"),
        Index("idx_graph_snapshots_as_of", "as_of"),
        {"comment": "图谱快照元数据表"},
    )


class CommunitySnapshot(Base):
    """社区详情快照表"""
    
    __tablename__ = "community_snapshots"
    
    # 主键
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    
    # 关联快照
    snapshot_id = Column(String(64), nullable=False, index=True, comment="关联的图谱快照ID")
    community_id = Column(String(50), nullable=False, comment="社区ID")
    
    # 社区基本信息
    size = Column(Integer, nullable=False, comment="社区文献数量")
    activity = Column(
        sa.Float().with_variant(sa.Float(precision=24), "postgresql"),
        nullable=False,
        comment="活跃度（0-1）",
    )
    
    # 社区特征
    representative_terms = Column(JSONB, nullable=False, comment="代表性关键词（≤10）: [{term, score}]")
    top_papers = Column(JSONB, nullable=False, comment="Top10文献: [{pmid, title, abstract, score, pub_date}]")
    
    # LLM生成的摘要
    summary = Column(String(1000), nullable=True, comment="社区摘要（LLM生成）")
    
    # 社区图结构（可选，用于前端可视化）
    graph_data = Column(JSONB, nullable=True, comment="社区子图数据: {nodes: [...], edges: [...]}（可选）")
    
    # 社区指标
    metrics = Column(JSONB, nullable=False, comment="社区指标: {modularity, density, coverage, keywords_coverage, detector, degraded}")
    
    # 时间戳
    created_at = Column(TIMESTAMP, nullable=False, server_default=text("NOW()"), comment="创建时间")
    
    # 索引
    __table_args__ = (
        UniqueConstraint("snapshot_id", "community_id", name="uq_community_snapshots_snapshot_community"),
        Index("idx_community_snapshots_snapshot", "snapshot_id"),
        {"comment": "社区详情快照表"},
    )
