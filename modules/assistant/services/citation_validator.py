"""
引用对齐校验器
任务2.3: 引用对齐校验逻辑
"""
import re
import json
from typing import List, Dict, Tuple, Optional
from pydantic import BaseModel
import logging

from modules.assistant.models.candidate import CandidateArticle

logger = logging.getLogger(__name__)


class CitationValidationResult(BaseModel):
    """校验结果"""
    success: bool
    answer_text: str
    citations: List[Dict]  # [{"idx": 1, "pmid": "...", "title": "...", "url": "..."}]
    errors: List[str] = []


class CitationValidator:
    """引用对齐校验器"""
    
    def __init__(self, max_citations: int = 10):
        self.max_citations = max_citations
    
    def validate(
        self,
        answer_text: str,
        candidates: List[CandidateArticle]
    ) -> CitationValidationResult:
        """
        校验回答文本的引用对齐
        
        Args:
            answer_text: DeepSeek生成的回答文本
            candidates: 候选文献列表
        
        Returns:
            CitationValidationResult
        """
        errors = []
        
        # 提取所有引用编号
        citation_pattern = r'\[(\d+(?:\s*,\s*\d+)*)\]'
        matches = re.findall(citation_pattern, answer_text)
        
        if not matches:
            errors.append("回答中未找到任何引用编号[n]")
            return CitationValidationResult(
                success=False,
                answer_text=answer_text,
                citations=[],
                errors=errors
            )
        
        # 解析所有引用编号
        all_cited_ids = set()
        for match in matches:
            ids = [int(x.strip()) for x in match.split(',')]
            all_cited_ids.update(ids)
        
        # 校验规则1: 引用编号不得越界
        max_idx = len(candidates)
        for cid in all_cited_ids:
            if cid < 1 or cid > max_idx:
                errors.append(f"引用编号[{cid}]越界（有效范围1-{max_idx}）")
        
        # 校验规则2: 检查是否有孤儿引用（引用了但候选中不存在）
        # （已在规则1中覆盖）
        
        # 校验规则3: 每句至少1个引用
        # 按句号、问号、感叹号分句（支持中英文标点）
        sentences = re.split(r'[。！？.!?]', answer_text)
        sentences = [s.strip() for s in sentences if s.strip() and len(s) > 5]  # 忽略太短的片段
        
        for sent in sentences:
            if not re.search(citation_pattern, sent):
                errors.append(f"句子未标注引用：{sent[:50]}...")
                logger.warning(f"Missing citation in sentence: {sent}")
        
        if errors:
            return CitationValidationResult(
                success=False,
                answer_text=answer_text,
                citations=[],
                errors=errors
            )
        
        # 构建引用列表（按照cited_ids）
        citations = []
        for idx in sorted(all_cited_ids):
            if 1 <= idx <= len(candidates):
                c = candidates[idx - 1]
                citations.append({
                    "idx": idx,
                    "pmid": c.pmid,
                    "title": c.title,
                    "url": c.url,
                    "journal_name": c.journal_name,
                    "publication_year": c.publication_year
                })
        
        return CitationValidationResult(
            success=True,
            answer_text=answer_text,
            citations=citations,
            errors=[]
        )
    
    def assemble_from_json(
        self,
        json_response: str,
        candidates: List[CandidateArticle]
    ) -> Tuple[Optional[str], Optional[List[Dict]], List[str]]:
        """
        从JSON回退响应中组装文本
        
        Args:
            json_response: LLM返回的JSON字符串
            candidates: 候选文献列表
        
        Returns:
            (assembled_text, citations, errors)
        """
        errors = []
        
        try:
            # 移除markdown代码块（如果有）
            json_str = json_response.strip()
            if json_str.startswith("```json"):
                json_str = json_str[7:]
            if json_str.startswith("```"):
                json_str = json_str[3:]
            if json_str.endswith("```"):
                json_str = json_str[:-3]
            json_str = json_str.strip()
            
            data = json.loads(json_str)
            
            if "sentences" not in data or "references" not in data:
                errors.append("JSON缺少必需字段: sentences 或 references")
                return None, None, errors
            
            # 组装文本
            assembled_sentences = []
            all_cited_ids = set()
            
            for sent_obj in data["sentences"]:
                text = sent_obj.get("text", "")
                citation_ids = sent_obj.get("citation_ids", [])
                
                if not citation_ids:
                    errors.append(f"句子缺少引用：{text[:50]}...")
                    continue
                
                # 校验citation_ids范围
                for cid in citation_ids:
                    if cid < 1 or cid > len(candidates):
                        errors.append(f"引用编号[{cid}]越界")
                
                all_cited_ids.update(citation_ids)
                
                # 拼接引用标记
                citation_str = "[" + ", ".join(map(str, citation_ids)) + "]"
                assembled_sentences.append(f"{text}{citation_str}")
            
            assembled_text = "".join(assembled_sentences)
            
            # 构建引用列表
            citations = []
            for idx in sorted(all_cited_ids):
                if 1 <= idx <= len(candidates):
                    c = candidates[idx - 1]
                    citations.append({
                        "idx": idx,
                        "pmid": c.pmid,
                        "title": c.title,
                        "url": c.url,
                        "journal_name": c.journal_name,
                        "publication_year": c.publication_year
                    })
            
            if errors:
                return None, None, errors
            
            return assembled_text, citations, []
            
        except json.JSONDecodeError as e:
            errors.append(f"JSON解析失败: {e}")
            return None, None, errors
        except Exception as e:
            errors.append(f"组装失败: {e}")
            return None, None, errors

