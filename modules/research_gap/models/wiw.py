"""
WiW (What is What) 结果表模型

存储研究空白分析结果
"""

from sqlalchemy import Column, String, Integer, TIMESTAMP, text, Index
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime

from models.base import Base


class WiWResult(Base):
    """WiW生成结果表"""
    
    __tablename__ = "wiw_results"
    
    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    
    # 输入信息
    input_pmid = Column(String(20), nullable=False, index=True, comment="输入文献PMID")
    input_doi = Column(String(200), nullable=True, comment="输入文献DOI（如果通过DOI输入）")
    input_title = Column(String(500), nullable=True, comment="输入文献标题（如果通过标题输入）")
    input_fingerprint = Column(String(32), nullable=False, index=True, comment="输入指纹（MD5，用于去重和缓存）")
    
    # 生成参数
    top_k = Column(Integer, nullable=False, default=10, comment="召回文献数量（5/10/15）")
    strategy_version = Column(String(10), nullable=False, default="v1", comment="召回策略版本")
    template_version = Column(String(10), nullable=False, default="v1", comment="Prompt模板版本")
    model_version = Column(String(50), nullable=False, default="deepseek-v4-flash", comment="LLM模型版本")
    language = Column(String(5), nullable=False, default="zh", comment="生成语言（zh/en）")
    
    # WiW卡片内容（JSONB格式）
    card_content = Column(JSONB, nullable=False, comment="WiW卡片内容：{focus, next_questions, conflicts, gaps}")
    
    # 召回文献列表
    references = Column(JSONB, nullable=False, comment="召回文献列表（PMID+标题+DOI+相似度）")
    references_hash = Column(String(32), nullable=False, comment="召回集哈希（用于缓存键）")
    
    # 顶刊推荐
    top_journal_recommendations = Column(JSONB, nullable=True, comment="顶刊推荐列表（来自模块2的13本期刊）")
    
    # 元数据
    meta = Column(JSONB, nullable=False, comment="元数据：{recall_mode, dedup_count, elapsed_ms, degradation}")
    
    # 时间戳
    created_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        comment="创建时间"
    )
    updated_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=datetime.now,
        comment="更新时间"
    )
    
    # 索引
    __table_args__ = (
        Index("idx_wiw_input_fingerprint", "input_fingerprint"),
        Index("idx_wiw_created_at", "created_at"),
        Index("idx_wiw_input_pmid", "input_pmid"),
    )
    
    def __repr__(self):
        return f"<WiWResult(id={self.id}, input_pmid={self.input_pmid}, top_k={self.top_k})>"
