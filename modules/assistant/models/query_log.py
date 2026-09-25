"""
AssistantQueryLog数据库模型
基于 openspec/changes/add-ai-assistant/DATABASE_SCHEMA.md
"""
from datetime import datetime
from sqlalchemy import (
    Column,
    BigInteger,
    Integer,
    String,
    Text,
    Boolean,
    Numeric,
    TIMESTAMP,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from models.base import Base


class AssistantQueryLog(Base):
    """AI助手查询日志表"""
    
    __tablename__ = "assistant_query_log"
    
    # 主键
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    
    # 请求参数
    query = Column(Text, nullable=False, comment="用户查询")
    sports_gate = Column(Boolean, nullable=False, comment="Sports Gate开关状态")
    use_agent = Column(Boolean, nullable=False, comment="是否使用Agent模式")
    top_k = Column(Integer, nullable=False, comment="召回文献数量")
    lang = Column(String(10), nullable=False, comment="语言: zh|en")
    
    # 召回统计
    literature_recall_count = Column(Integer, server_default=text("0"), comment="模块1召回数")
    journals_recall_count = Column(Integer, server_default=text("0"), comment="模块2召回数")
    pubmed_agent_count = Column(Integer, server_default=text("0"), comment="Agent在线召回数")
    pmid_valid_count = Column(Integer, server_default=text("0"), comment="有效PMID数")
    final_candidate_count = Column(Integer, server_default=text("0"), comment="去重后候选数")
    
    # 性能指标
    search_duration_ms = Column(Integer, nullable=True, comment="检索耗时(ms)")
    generation_duration_ms = Column(Integer, nullable=True, comment="生成耗时(ms)")
    total_duration_ms = Column(Integer, nullable=True, comment="总耗时(ms)")
    
    # 成本记录
    input_tokens = Column(Integer, server_default=text("0"), comment="输入Token数")
    output_tokens = Column(Integer, server_default=text("0"), comment="输出Token数")
    estimated_cost_cny = Column(Numeric(8, 4), nullable=True, comment="估算成本(CNY)")
    
    # Agent步骤（仅Agent模式）
    agent_steps = Column(JSONB, nullable=True, comment="Agent执行步骤JSON")
    agent_fallback = Column(Boolean, server_default=text("FALSE"), comment="是否触发回退")
    
    # 结果
    status = Column(
        String(20), 
        nullable=False, 
        comment="状态: success|failed|timeout|no_results"
    )
    error_code = Column(String(30), nullable=True, comment="错误码（如果失败）")
    error_message = Column(Text, nullable=True, comment="错误信息")
    citation_count = Column(Integer, server_default=text("0"), comment="引用数量")
    
    # 审计字段
    created_at = Column(
        TIMESTAMP, 
        nullable=False, 
        server_default=text("NOW()"), 
        comment="创建时间"
    )
    
    __table_args__ = (
        {"comment": "AI助手查询日志表"},
    )

