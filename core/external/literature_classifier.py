#!/usr/bin/env python3
"""
集成的文献分类器
结合规则分类和LLM分类
"""
from typing import List, Dict, Any, Optional
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.external.pubmed import map_pub_types_to_lit_types
from modules.literature_stream.services.lit_type_classifier import get_lit_type_classifier


async def classify_literature_comprehensive(
    articles: List[Dict[str, Any]]
) -> List[List[str]]:
    """
    综合分类文献（规则 + LLM）
    
    Args:
        articles: 文献列表，每个包含：
            - title: 标题
            - abstract: 摘要
            - pub_types: PublicationType列表
            - mesh_terms: MeSH主题词列表
    
    Returns:
        每篇文献的分类结果列表
    """
    results = []
    original_research_articles = []  # 需要LLM分类的原创研究
    original_research_indices = []   # 对应的索引
    
    # 第一步：规则分类
    for idx, article in enumerate(articles):
        title = article.get('title', '')
        pub_types = article.get('pub_types', [])
        mesh_terms = article.get('mesh_terms', [])
        
        # 使用规则分类
        lit_types = map_pub_types_to_lit_types(pub_types, mesh_terms, title)
        
        # 如果是原创研究，需要LLM进一步分类
        if lit_types == ['original_research']:
            original_research_articles.append(article)
            original_research_indices.append(idx)
            results.append(['original_research'])  # 临时占位
        else:
            results.append(lit_types)
    
    # 第二步：LLM分类原创研究
    if original_research_articles:
        print(f"\n🤖 LLM分类 {len(original_research_articles)} 篇原创研究...")
        
        classifier = get_lit_type_classifier()
        llm_results = await classifier.classify_batch(original_research_articles)
        
        # 更新结果
        for i, llm_result in enumerate(llm_results):
            idx = original_research_indices[i]
            
            if llm_result.get('error'):
                # LLM分类失败，使用默认分类
                print(f"  ⚠️  文献 {idx+1} LLM分类失败，使用默认分类")
                results[idx] = ['original_na']  # 默认为理论研究
            else:
                lit_type = llm_result.get('type')
                if lit_type in ['original_human', 'original_animal', 'original_na']:
                    results[idx] = [lit_type]
                else:
                    print(f"  ⚠️  文献 {idx+1} LLM返回未知类型: {lit_type}，使用默认分类")
                    results[idx] = ['original_na']
    
    return results


async def classify_single_literature(
    title: str,
    abstract: str,
    pub_types: List[str],
    mesh_terms: List[str]
) -> List[str]:
    """
    分类单篇文献
    
    Args:
        title: 标题
        abstract: 摘要
        pub_types: PublicationType列表
        mesh_terms: MeSH主题词列表
    
    Returns:
        文献类型列表
    """
    article = {
        'title': title,
        'abstract': abstract,
        'pub_types': pub_types,
        'mesh_terms': mesh_terms
    }
    
    results = await classify_literature_comprehensive([article])
    return results[0] if results else ['original_na']
