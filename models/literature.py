"""
兼容层：为历史测试与引用提供 models.literature 接口

说明：
- 当前工程的ORM模型位于 modules.literature_stream.models.literature。
- 为避免与现行ORM重复声明同名表（literature）导致的SQLAlchemy冲突，
  这里提供一个轻量的占位类，满足测试用例对字段的简单断言需求。
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Literature:
    pmid: Optional[str] = None
    doi: Optional[str] = None
    title: Optional[str] = None
    abstract: Optional[str] = None
    journal: Optional[str] = None
    pub_year: Optional[int] = None


__all__ = ["Literature"]
