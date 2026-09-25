"""
检索式构建器
根据学科类、文献类型构建PubMed检索式
按照SUBJECT_CATEGORIES.md完整实现
"""
from typing import List, Optional


class SubjectQueryBuilder:
    """学科检索式构建器"""
    
    # 通用闸门检索式（用户不选学科类时的fallback）- 完整版本
    GENERAL_GATE = """(
  "Sports"[mh] OR
  "Athletes"[mh] OR
  "Athletic Performance"[mh] OR
  "Sports Medicine"[mh] OR
  "Athletic Injuries"[mh] OR
  "Physical Education and Training"[mh] OR
  "Athletic Equipment"[mh] OR
  "Olympic Games"[mh] OR
  sport*[tiab] OR
  athlet*[tiab] OR
  "physical education"[tiab] OR
  "phys ed"[tiab] OR
  "sport pedagogy"[tiab] OR
  "sports pedagogy"[tiab] OR
  Paralympic*[tiab] OR
  Olympic*[tiab] OR
  interscholastic[tiab] OR
  intercollegiate[tiab] OR
  (
    ("Equipment Design"[mh] OR
     "Protective Devices"[mh] OR
     "Wearable Electronic Devices"[mh] OR
     "Motion Capture"[mh] OR
     "Biomechanical Phenomena"[mh])
    AND
    (sport*[tiab] OR athlet*[tiab] OR "physical education"[tiab])
  )
)"""
    
    # 文献类型检索式（完全按照SUBJECT_CATEGORIES.md定义）
    LITERATURE_TYPES = {
        # 1. Meta分析 & 系统综述
        'meta_analysis': '(Meta-Analysis[pt] OR Systematic Review[pt] OR (Review[pt] AND "systematic review"[ti]))',
        
        # 2.1 原创研究 - 人体
        'original_human': '(Humans[mh] OR Clinical Trial[pt] OR Randomized Controlled Trial[pt] OR Cohort Studies[mh] OR Cross-Sectional Studies[mh] OR Case-Control Studies[mh])',
        
        # 2.2 原创研究 - 动物
        'original_animal': '((Animals[mh] NOT Humans[mh]) OR Rats[mh] OR Mice[mh] OR Animal Experimentation[mh])',
        
        # 2.3 原创研究 - N/A（理论/社科，无生物对象）
        'original_na': '(NOT Humans[mh] AND NOT Animals[mh])',
        
        # 3. 综述（非系统性）
        'review': '(Review[pt] NOT (Meta-Analysis[pt] OR Systematic Review[pt]))',
        
        # 4. 指南/共识/Protocol
        'guideline': '(Practice Guideline[pt] OR Guideline[pt] OR Consensus Development Conference[pt] OR "consensus statement"[ti] OR "clinical practice guideline"[ti] OR Protocol[ti])'
    }
    
    def build_query(
        self,
        subject_queries: List[str],
        literature_types: List[str] = None,
        date_filter: str = None
    ) -> str:
        """
        构建完整的PubMed检索式
        
        逻辑（按照SUBJECT_CATEGORIES.md规范）:
        1. 如果用户选了学科类: 使用学科类检索式（多选用OR连接）
        2. 如果用户没选学科类: 使用通用闸门
        3. 如果用户选了文献类型: 在基础检索式后套文献类型检索式（AND连接）
        
        Args:
            subject_queries: 学科类检索式列表（可为空）
            literature_types: 文献类型列表（可为空）
            date_filter: 日期过滤 (格式: "YYYY/MM/DD:YYYY/MM/DD")
        
        Returns:
            完整的PubMed检索式
        """
        # 基础检索式: 学科类（可多选）OR 通用闸门
        if subject_queries and len(subject_queries) > 0:
            # 用户选了学科类（可多选，用OR连接）
            base_query = ' OR '.join(f'({q.strip()})' for q in subject_queries)
        else:
            # 用户没选学科类，使用通用闸门
            base_query = self.GENERAL_GATE.strip()
        
        # 文献类型过滤（在基础检索式后套AND）
        if literature_types and len(literature_types) > 0:
            type_queries = [self.LITERATURE_TYPES[t] for t in literature_types if t in self.LITERATURE_TYPES]
            if type_queries:
                type_query = ' OR '.join(type_queries)
                base_query = f'({base_query}) AND ({type_query})'
        
        # 日期过滤（使用PDAT发表日期而不是EDAT录入日期）
        if date_filter:
            # 支持相对日期如"last 30 days"或绝对日期范围
            base_query = f'({base_query}) AND {date_filter}'
        
        return base_query
    
    def build_date_filter(self, start_date: str, end_date: str = None) -> str:
        """
        构建日期过滤器
        
        Args:
            start_date: 开始日期 (YYYY/MM/DD HH:MM:SS)
            end_date: 结束日期 (YYYY/MM/DD HH:MM:SS)
        
        Returns:
            日期过滤字符串
        """
        if end_date:
            return f"{start_date}:{end_date}"
        return f"{start_date}:3000/12/31"
