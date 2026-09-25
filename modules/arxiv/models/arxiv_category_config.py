"""
arXiv分类配置模型
"""
from datetime import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    Boolean,
)
from models.base import Base


class ArxivCategoryConfig(Base):
    """arXiv分类配置表（4大运动科学分类）"""

    __tablename__ = "arxiv_category_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    category_key = Column(String(50), nullable=False, unique=True, comment="分类key")
    display_name = Column(String(100), nullable=False, comment="显示名称")
    description = Column(Text, comment="描述")

    # 统计
    doc_count = Column(Integer, default=0, comment="文档数量")
    last_updated = Column(DateTime, comment="最后更新时间")

    # 排序
    display_order = Column(Integer, comment="显示顺序")
    is_enabled = Column(Boolean, default=True, comment="是否启用")

    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
