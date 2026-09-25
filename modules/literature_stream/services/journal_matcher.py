"""
期刊匹配服务
优先ISSN匹配，回退NLM缩写
"""
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from modules.literature_stream.models.literature import JournalMetadata


class JournalMatcher:
    """期刊匹配器"""
    
    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        self._cache = {}  # 简单内存缓存
    
    async def match_journal(
        self,
        issn: Optional[str],
        journal_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        匹配期刊，获取IF和分区信息
        
        Args:
            issn: 期刊ISSN
            journal_name: 期刊名称（用于NLM缩写匹配）
            
        Returns:
            期刊信息字典
        """
        # 缓存键
        cache_key = f"{issn}:{journal_name}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        journal_info = {}
        
        # 优先ISSN匹配
        if issn:
            result = await self.db.execute(
                select(JournalMetadata).where(JournalMetadata.issn == issn)
            )
            journal = result.scalar_one_or_none()
            
            if journal:
                journal_info = {
                    'issn': journal.issn,  # 返回ISSN用于回填
                    'nlm_abbr': journal.nlm_abbr,
                    'if_5y': float(journal.if_5y) if journal.if_5y else None,
                    'citescore': float(journal.citescore) if journal.citescore else None,
                    'zone': journal.cas_zone,
                    'is_top': journal.is_top_journal,
                    'is_blacklist': journal.is_blacklisted,
                }
                
                self._cache[cache_key] = journal_info
                return journal_info
        
        # 回退：基于期刊名称的模糊匹配（NLM缩写或全名）
        if journal_name:
            # 尝试NLM缩写精确匹配（可能有多个ISSN，取第一个）
            result = await self.db.execute(
                select(JournalMetadata).where(JournalMetadata.nlm_abbr == journal_name).limit(1)
            )
            journal = result.scalar_one_or_none()

            if journal:
                journal_info = {
                    'issn': journal.issn,  # 从NLM缩写匹配回填ISSN
                    'nlm_abbr': journal.nlm_abbr,
                    'if_5y': float(journal.if_5y) if journal.if_5y else None,
                    'citescore': float(journal.citescore) if journal.citescore else None,
                    'zone': journal.cas_zone,
                    'is_top': journal.is_top_journal,
                    'is_blacklist': journal.is_blacklisted,
                }
                
                self._cache[cache_key] = journal_info
                return journal_info
            
            # 尝试期刊全名精确匹配（大小写不敏感，可能有多个ISSN，取第一个）
            result = await self.db.execute(
                select(JournalMetadata).where(
                    JournalMetadata.full_name.ilike(journal_name)
                ).limit(1)
            )
            journal = result.scalar_one_or_none()

            if journal:
                journal_info = {
                    'issn': journal.issn,  # 从期刊名精确匹配回填ISSN
                    'nlm_abbr': journal.nlm_abbr,
                    'if_5y': float(journal.if_5y) if journal.if_5y else None,
                    'citescore': float(journal.citescore) if journal.citescore else None,
                    'zone': journal.cas_zone,
                    'is_top': journal.is_top_journal,
                    'is_blacklist': journal.is_blacklisted,
                }
                
                self._cache[cache_key] = journal_info
                return journal_info
            
            # 最后才尝试模糊匹配，但必须只匹配一个结果
            result = await self.db.execute(
                select(JournalMetadata).where(
                    JournalMetadata.full_name.ilike(f'%{journal_name}%')
                )
            )
            journals = result.all()
            
            # 只有唯一匹配时才使用模糊匹配结果
            if journals and len(journals) == 1:
                journal = journals[0][0]  # 从tuple中取出
                journal_info = {
                    'issn': journal.issn,  # 从期刊名模糊匹配回填ISSN
                    'nlm_abbr': journal.nlm_abbr,
                    'if_5y': float(journal.if_5y) if journal.if_5y else None,
                    'citescore': float(journal.citescore) if journal.citescore else None,
                    'zone': journal.cas_zone,
                    'is_top': journal.is_top_journal,
                    'is_blacklist': journal.is_blacklisted,
                }
                
                self._cache[cache_key] = journal_info
                return journal_info
        
        # 未匹配到期刊
        journal_info = {
            'issn': None,
            'nlm_abbr': None,
            'if_5y': None,
            'citescore': None,
            'zone': None,
            'is_top': False,
            'is_blacklist': False,
        }
        
        self._cache[cache_key] = journal_info
        return journal_info
