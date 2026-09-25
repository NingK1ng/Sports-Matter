"""
期刊过滤器
处理顶刊开关和黑名单过滤
"""
from typing import List, Dict, Any
from .loader import ConfigLoader


class JournalFilter:
    """期刊过滤器"""
    
    def __init__(self, config_loader: ConfigLoader):
        self.config = config_loader
        self.filters = config_loader.load_journal_filters()
    
    def apply_top_journal_filter(self, issns: List[str]) -> List[str]:
        """应用顶刊过滤（仅保留5本顶刊）"""
        top_issns = set(self.filters['top_journals'])
        return [issn for issn in issns if issn in top_issns]
    
    def apply_blacklist_filter(self, issns: List[str]) -> List[str]:
        """应用黑名单过滤（排除66本4区）"""
        blacklist_issns = set(self.filters['blacklist'])
        return [issn for issn in issns if issn not in blacklist_issns]
    
    def build_sql_filter(
        self,
        enable_top_journals: bool = False,
        enable_blacklist: bool = False
    ) -> str:
        """
        构建SQL过滤条件
        
        Args:
            enable_top_journals: 启用顶刊过滤
            enable_blacklist: 启用黑名单过滤
            
        Returns:
            SQL WHERE子句（不含WHERE关键字）
        """
        conditions = []
        
        if enable_top_journals:
            top_issns = self.filters['top_journals']
            issns_str = "', '".join(top_issns)
            conditions.append(f"journal_issn IN ('{issns_str}')")
        
        if enable_blacklist:
            blacklist_issns = self.filters['blacklist']
            issns_str = "', '".join(blacklist_issns)
            conditions.append(f"journal_issn NOT IN ('{issns_str}')")
        
        return " AND ".join(conditions) if conditions else "TRUE"
