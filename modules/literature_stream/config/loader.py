"""
配置文件加载器
加载YAML/CSV配置文件
"""
import csv
import yaml
from pathlib import Path
from typing import Dict, List, Any
from functools import lru_cache


class ConfigLoader:
    """配置文件加载器"""
    
    def __init__(self, config_dir: Path):
        self.config_dir = Path(config_dir)
        
    @lru_cache(maxsize=1)
    def load_journal_list(self) -> List[Dict[str, Any]]:
        """加载期刊列表CSV"""
        csv_path = self.config_dir / "JOURNAL_LIST.csv"
        journals = []
        
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not row.get('ISSN'):
                    continue
                
                # 解析5年IF
                if_5y_str = row.get('5年IF', '').strip()
                if_5y = None if if_5y_str == '-' or not if_5y_str else float(if_5y_str)
                
                # 解析CiteScore
                citescore_str = row.get('CiteScore', '').strip()
                citescore = None if not citescore_str or citescore_str == '-' else float(citescore_str)
                
                journals.append({
                    'issn': row['ISSN'].strip(),
                    'name': row['期刊名称'].strip(),
                    'if_5y': if_5y,
                    'citescore': citescore,
                    'zone': row.get('中科院分区', '').strip() or None,
                })
        
        return journals
    
    @lru_cache(maxsize=1)
    def load_journal_filters(self) -> Dict[str, Any]:
        """加载期刊过滤配置（顶刊和黑名单）"""
        yaml_path = self.config_dir / "journal_filters.yaml"
        
        with open(yaml_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        return {
            'top_journals': [j['issn'] for j in config.get('top_journals', [])],
            'top_journals_full': config.get('top_journals', []),
            'blacklist': [j['issn'] for j in config.get('blacklist', [])],
            'blacklist_full': config.get('blacklist', []),
        }
    
    def load_subject_categories(self) -> Dict[str, Dict[str, str]]:
        """
        加载学科分类检索式
        从数据库读取SubjectCategoryConfig表
        """
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import Session
        from core.config import settings
        from modules.literature_stream.models.literature import SubjectCategoryConfig
        
        # 创建同步引擎
        sync_url = settings.database_url.replace('+asyncpg', '').replace('postgresql+asyncpg', 'postgresql')
        engine = create_engine(sync_url, pool_pre_ping=True)
        
        categories = {}
        with Session(engine) as session:
            result = session.execute(select(SubjectCategoryConfig))
            for cat in result.scalars():
                categories[cat.category_key] = {
                    'display_name': cat.display_name,
                    'pubmed_query': cat.pubmed_query,
                    'category_key': cat.category_key
                }
        
        return categories
    
    def get_journal_by_issn(self, issn: str) -> Dict[str, Any]:
        """根据ISSN获取期刊信息"""
        journals = self.load_journal_list()
        for journal in journals:
            if journal['issn'] == issn:
                return journal
        return {}
    
    def is_top_journal(self, issn: str) -> bool:
        """判断是否顶刊"""
        filters = self.load_journal_filters()
        return issn in filters['top_journals']
    
    def is_blacklisted(self, issn: str) -> bool:
        """判断是否黑名单"""
        filters = self.load_journal_filters()
        return issn in filters['blacklist']
