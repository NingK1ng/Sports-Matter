"""
arXiv爬取日志模型
"""
from datetime import datetime
from sqlalchemy import (
    Column,
    BigInteger,
    String,
    Text,
    Date,
    DateTime,
    Integer,
    Index,
)
from models.base import Base


class ArxivCrawlLog(Base):
    """arXiv爬取日志表"""

    __tablename__ = "arxiv_crawl_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    task_type = Column(String(50), nullable=False, comment="任务类型：incremental/backfill")
    source = Column(String(20), nullable=False, comment="来源：arxiv/biorxiv")

    # 执行参数
    date_from = Column(Date, comment="起始日期")
    date_to = Column(Date, comment="结束日期")
    batch_number = Column(Integer, comment="批次号1-8")

    # 执行结果
    status = Column(String(20), nullable=False, comment="状态：running/success/failed")
    total_fetched = Column(Integer, default=0, comment="L1召回数")
    llm_processed = Column(Integer, default=0, comment="L2处理数")
    new_inserted = Column(Integer, default=0, comment="新增入库数")
    updated_count = Column(Integer, default=0, comment="更新数")
    error_message = Column(Text, comment="错误信息")

    # 时间记录
    started_at = Column(DateTime, nullable=False, comment="开始时间")
    finished_at = Column(DateTime, comment="结束时间")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")


Index("idx_arxiv_crawl_log_status", ArxivCrawlLog.status, ArxivCrawlLog.started_at.desc())
Index("idx_arxiv_crawl_log_source", ArxivCrawlLog.source, ArxivCrawlLog.started_at.desc())
