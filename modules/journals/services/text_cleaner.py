"""
文本清洗工具
任务1.7: 摘要JATS清洗（JATS → 纯文本）
"""
import re
from typing import Optional


def clean_jats_abstract(abstract: Optional[str]) -> Optional[str]:
    """
    清洗Crossref返回的JATS格式摘要，转换为纯文本
    
    Args:
        abstract: 原始摘要（可能包含JATS标签）
    
    Returns:
        清洗后的纯文本摘要
    
    Examples:
        >>> clean_jats_abstract("<jats:p>This is abstract.</jats:p>")
        'This is abstract.'
        
        >>> clean_jats_abstract("<jats:title>Background</jats:title><jats:p>Text</jats:p>")
        'Background Text'
    """
    if not abstract:
        return None
    
    # 移除所有JATS标签（如<jats:p>, <jats:title>, <jats:italic>等）
    # 保留标签内的文本内容
    cleaned = re.sub(r'<jats:[^>]+>', '', abstract)
    cleaned = re.sub(r'</jats:[^>]+>', ' ', cleaned)
    
    # 移除其他HTML标签
    cleaned = re.sub(r'<[^>]+>', '', cleaned)
    
    # 清理多余空格
    cleaned = re.sub(r'\s+', ' ', cleaned)
    cleaned = cleaned.strip()
    
    return cleaned if cleaned else None


def highlight_search_terms(text: str, query: str, max_length: int = 300) -> str:
    """
    高亮搜索关键词（可选功能，用于前端展示）
    
    Args:
        text: 原文本
        query: 搜索查询
        max_length: 最大返回长度
    
    Returns:
        高亮后的文本片段
    """
    if not text or not query:
        return text[:max_length] if text else ""
    
    # 简单实现：查找第一个匹配位置，返回周围文本
    query_lower = query.lower()
    text_lower = text.lower()
    
    pos = text_lower.find(query_lower)
    if pos == -1:
        return text[:max_length]
    
    # 返回匹配位置前后的文本
    start = max(0, pos - 100)
    end = min(len(text), pos + len(query) + 200)
    
    snippet = text[start:end]
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    
    return snippet
