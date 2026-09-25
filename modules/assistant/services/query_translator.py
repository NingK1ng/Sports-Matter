"""
中文查询翻译服务
将中文查询转换为英文关键词用于搜索（多同义词+MeSH提示）
"""
from core.external.deepseek import DEEPSEEK_V4_FLASH_MODEL, DeepSeekClient
from core.cache import cache_get, cache_set
import logging
import re
import hashlib
import json
from typing import Dict, List

logger = logging.getLogger(__name__)


class QueryTranslator:
    """查询翻译器"""
    
    def __init__(self, deepseek_client: DeepSeekClient):
        self.deepseek = deepseek_client
    
    async def translate_query(self, query: str) -> str:
        """
        将中文查询转换为英文关键词（兼容旧接口）
        
        Args:
            query: 用户查询（中文或英文）
            
        Returns:
            英文关键词字符串
        """
        result = await self.translate_with_synonyms(query)
        return result.get("primary", query)
    
    async def translate_with_synonyms(self, query: str) -> Dict:
        """
        将中文查询转换为多同义词结构（支持PubMed优化）
        
        Args:
            query: 用户查询（中文或英文）
            
        Returns:
            {
                "primary": "主要英文术语",
                "synonyms": ["同义词1", "同义词2"],
                "mesh_terms": ["MeSH Terms"],
                "abbreviations": ["缩写"],
                "confidence": 0.95
            }
        """
        # 如果查询主要是英文，返回简单结构
        if self._is_mainly_english(query):
            return {
                "primary": query,
                "synonyms": [],
                "mesh_terms": [],
                "abbreviations": [],
                "confidence": 1.0
            }
        
        # 检查缓存（90天TTL）
        cache_key = f"query_trans:v2:{hashlib.md5(query.encode()).hexdigest()}"
        cached = await cache_get(cache_key)
        if cached:
            logger.info(f"translator: cache hit for '{query}'")
            return cached
        
        # 使用DeepSeek生成多同义词结构
        prompt = f"""你是医学文献检索专家。将中文术语翻译为英文，并提供PubMed检索所需的同义词和MeSH提示。

输出JSON格式（严格遵守格式）：
{{
  "primary": "主要英文术语（完整拼写，标准医学用语）",
  "synonyms": ["同义词1", "同义词2", "同义词3"],
  "mesh_terms": ["可能的MeSH Terms完整名称"],
  "abbreviations": ["常用缩写"],
  "confidence": 0.95
}}

要求：
1. primary：使用标准医学术语（如"myocardial infarction"而非"heart attack"）
2. synonyms：包含3-5个变体（美英拼写、复数形式、同义表达）
3. mesh_terms：使用PubMed官方MeSH Headings（如"Myocardial Infarction"[MeSH]）
4. abbreviations：学界公认缩写（如MI、AMI）
5. confidence：翻译准确度（0-1），不确定时<0.7

示例1：
输入：心肌梗死
输出：
{{
  "primary": "myocardial infarction",
  "synonyms": ["heart attack", "cardiac infarction", "MI"],
  "mesh_terms": ["Myocardial Infarction"],
  "abbreviations": ["MI", "AMI"],
  "confidence": 0.98
}}

示例2：
输入：跑步损伤
输出：
{{
  "primary": "running injury",
  "synonyms": ["runner's injury", "jogging injury", "running-related injury"],
  "mesh_terms": ["Athletic Injuries", "Running"],
  "abbreviations": ["RRI"],
  "confidence": 0.92
}}

中文术语：{query}

请输出JSON："""

        # 调用DeepSeek生成多同义词结构
        try:
            response = await self.deepseek.chat(
                messages=[{"role": "user", "content": prompt}],
                model=DEEPSEEK_V4_FLASH_MODEL,
                temperature=0.2,  # 稍高温度增加同义词多样性
                max_tokens=300,
                response_format={"type": "json_object"}
            )
            
            if response:
                result = json.loads(response)
                
                # 验证必需字段
                if "primary" not in result:
                    raise ValueError("Missing primary field")
                
                # 补充默认值
                result.setdefault("synonyms", [])
                result.setdefault("mesh_terms", [])
                result.setdefault("abbreviations", [])
                result.setdefault("confidence", 0.8)
                
                # 缓存结果（90天）
                await cache_set(cache_key, result, ttl=7776000)
                
                logger.info(
                    f"translator: '{query}' -> primary='{result['primary']}', "
                    f"synonyms={len(result['synonyms'])}, mesh={len(result['mesh_terms'])}"
                )
                return result
                
        except json.JSONDecodeError as e:
            logger.error(f"translator: JSON parse error for '{query}': {e}")
        except Exception as e:
            logger.error(f"translator: LLM error for '{query}': {e}")
        
        # 翻译失败，返回简单结构
        logger.warning(f"translator: failed, returning simple structure for '{query}'")
        return {
            "primary": query,
            "synonyms": [],
            "mesh_terms": [],
            "abbreviations": [],
            "confidence": 0.3
        }
    
    def _is_mainly_english(self, text: str) -> bool:
        """检测文本是否主要是英文"""
        # 统计中文字符数量
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        total_chars = len(text.replace(' ', ''))
        
        # 如果中文字符少于20%，认为是英文
        if total_chars == 0:
            return True
        
        return (chinese_chars / total_chars) < 0.2

    
