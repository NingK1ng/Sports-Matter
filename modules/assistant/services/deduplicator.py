"""
候选文献去重服务
任务1.4: PMID去重与合并
"""
from typing import List
from modules.assistant.models.candidate import CandidateArticle


def deduplicate_by_pmid(candidates: List[CandidateArticle]) -> List[CandidateArticle]:
    """
    按PMID/DOI去重，保留摘要更完整的版本

    ✅ 修复：支持没有PMID但有DOI的文章（86.8%的journal文章）

    Args:
        candidates: 候选文献列表

    Returns:
        去重后的候选文献列表
    """
    if not candidates:
        return []

    pmid_map = {}
    doi_map = {}
    no_id_list = []

    for c in candidates:
        # 优先使用PMID去重
        if c.pmid:
            if c.pmid not in pmid_map:
                pmid_map[c.pmid] = c
            else:
                # 比较摘要长度，保留更完整的
                existing = pmid_map[c.pmid]
                if len(c.abstract) > len(existing.abstract):
                    pmid_map[c.pmid] = c
                # 如果摘要长度相同，优先保留literature源（数据更完整）
                elif len(c.abstract) == len(existing.abstract) and c.source == "literature":
                    pmid_map[c.pmid] = c
        # 如果没有PMID，使用DOI去重
        elif c.doi:
            # 标准化DOI（去除前缀）
            doi_normalized = c.doi.lower().replace('doi:', '').replace('https://doi.org/', '').strip()
            if doi_normalized not in doi_map:
                doi_map[doi_normalized] = c
            else:
                existing = doi_map[doi_normalized]
                if len(c.abstract) > len(existing.abstract):
                    doi_map[doi_normalized] = c
        else:
            # 既没有PMID也没有DOI，直接保留（理论上不应该出现）
            no_id_list.append(c)

    # 合并所有去重后的结果
    return list(pmid_map.values()) + list(doi_map.values()) + no_id_list

