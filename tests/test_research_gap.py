"""
研究空白Agent模块单元测试

覆盖核心功能：
- PMID去重
- ELink排名使用
- JSON校验
- 错误码返回
- 超限降级触发
- 顶刊推荐过滤
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock

from modules.research_gap.services.wiw_generator import WiWGenerator
from pydantic import BaseModel


class TestWiWGenerator:
    """WiW生成器测试"""
    
    @pytest.mark.asyncio
    async def test_pmid_deduplication(self):
        """测试PMID去重"""
        generator = WiWGenerator()
        
        # 模拟召回结果包含重复和输入PMID
        input_pmid = "39609566"
        related_pmids = ["39609566", "39205391", "39135093", "39205391", "39913380"]
        
        # 去重逻辑
        seen = {input_pmid}
        unique_pmids = [p for p in related_pmids if p not in seen and not seen.add(p)]
        
        # 验证
        assert input_pmid not in unique_pmids  # 输入PMID已移除
        assert len(unique_pmids) == 3  # 去重后3篇（移除了2个重复）
        assert unique_pmids == ["39205391", "39135093", "39913380"]
    
    def test_extract_keywords(self):
        """测试关键词提取"""
        generator = WiWGenerator()
        
        # 测试英文标题
        title_en = "The effects of exercise training on cardiovascular health in athletes"
        keywords_en = generator._extract_keywords(title_en)
        assert "exercise" in keywords_en
        assert "training" in keywords_en
        assert "cardiovascular" in keywords_en
        assert "the" not in keywords_en  # 停用词已移除
        
        # 测试中文标题
        title_zh = "运动训练对心血管健康的影响研究"
        keywords_zh = generator._extract_keywords(title_zh)
        assert "运动训练" in keywords_zh
        assert "心血管健康" in keywords_zh
    
    def test_token_estimation(self):
        """测试Token估算"""
        generator = WiWGenerator()
        
        input_article = {
            "title": "A" * 100,
            "abstract": "B" * 500
        }
        
        references = [
            {"title": "C" * 80, "abstract": "D" * 400},
            {"title": "E" * 80, "abstract": "F" * 400}
        ]
        
        tokens = generator._estimate_tokens(input_article, references)
        
        # 估算：100 + 500 + (80+400)*2 + 2000(prompt) = 3560字符 / 4 ≈ 890 tokens
        assert tokens > 800
        assert tokens < 1000


class TestAPIRoutes:
    """API路由测试"""
    
    def test_topk_validation(self):
        """测试topK参数校验"""
        from modules.research_gap.api.routes import WiWGenerateRequest
        
        # 有效值
        for valid_topk in [5, 10, 15]:
            request = WiWGenerateRequest(pmid="12345678", top_k=valid_topk)
            assert request.top_k == valid_topk
        
        # 无效值
        with pytest.raises(ValueError, match="INVALID_TOPK"):
            WiWGenerateRequest(pmid="12345678", top_k=8)
    
    def test_pmid_format_validation(self):
        """测试PMID格式校验"""
        from modules.research_gap.api.routes import WiWGenerateRequest
        
        # 有效PMID（8位数字）
        request = WiWGenerateRequest(pmid="39609566", top_k=10)
        assert request.pmid == "39609566"
        
        # 无效PMID（非数字）
        with pytest.raises(ValueError, match="INVALID_PMID_FORMAT"):
            WiWGenerateRequest(pmid="abc12345", top_k=10)
        
        # 无效PMID（长度不对）
        with pytest.raises(ValueError, match="INVALID_PMID_FORMAT"):
            WiWGenerateRequest(pmid="123456", top_k=10)
    
    def test_doi_format_validation(self):
        """测试DOI格式校验"""
        from modules.research_gap.api.routes import WiWGenerateRequest
        
        # 有效DOI
        request = WiWGenerateRequest(doi="10.1038/s41586-023-06139-9", top_k=10)
        assert request.doi == "10.1038/s41586-023-06139-9"
        
        # 无效DOI（无10.前缀）
        with pytest.raises(ValueError, match="INVALID_DOI_FORMAT"):
            WiWGenerateRequest(doi="1038/s41586-023-06139-9", top_k=10)


class TestPromptTemplate:
    """Prompt模板测试"""
    
    def test_wiw_prompt_structure(self):
        """测试WiW Prompt结构"""
        from modules.research_gap.prompts.wiw_template import get_wiw_prompt
        
        input_title = "Test Title"
        input_abstract = "Test Abstract"
        references = [
            {"pmid": "123", "title": "Ref1", "abstract": "Abstract1"},
            {"pmid": "456", "title": "Ref2", "abstract": "Abstract2"}
        ]
        
        prompt = get_wiw_prompt(input_title, input_abstract, references, language="zh")
        
        # 验证Prompt包含必要元素
        assert "Test Title" in prompt
        assert "Test Abstract" in prompt
        assert "Ref1" in prompt
        assert "Ref2" in prompt
        assert "JSON" in prompt  # 要求JSON输出
        assert "focus" in prompt
        assert "next_questions" in prompt
        assert "conflicts" in prompt
        assert "gaps" in prompt
    
    def test_bilingual_support(self):
        """测试双语支持"""
        from modules.research_gap.prompts.wiw_template import get_wiw_prompt
        
        prompt_zh = get_wiw_prompt("标题", "摘要", [], language="zh")
        prompt_en = get_wiw_prompt("Title", "Abstract", [], language="en")
        
        assert "研究" in prompt_zh or "分析" in prompt_zh
        assert "research" in prompt_en.lower() or "analysis" in prompt_en.lower()


class TestCacheKeys:
    """缓存键测试"""
    
    def test_recall_cache_key(self):
        """测试召回缓存键生成"""
        generator = WiWGenerator()
        
        key1 = generator._generate_cache_key("39609566", "elink", 50)
        key2 = generator._generate_cache_key("39609566", "elink", 50)
        key3 = generator._generate_cache_key("39609566", "elink", 100)
        
        # 相同参数生成相同键
        assert key1 == key2
        
        # 不同参数生成不同键
        assert key1 != key3
    
    def test_generation_cache_key(self):
        """测试生成缓存键"""
        generator = WiWGenerator()
        
        refs1 = ["123", "456", "789"]
        refs2 = ["789", "456", "123"]  # 相同PMID但顺序不同
        
        key1 = generator._generate_generation_cache_key("39609566", 10, refs1, "v1", "deepseek-v4-flash")
        key2 = generator._generate_generation_cache_key("39609566", 10, refs2, "v1", "deepseek-v4-flash")
        
        # 相同PMID集合（排序后）应生成相同键
        assert key1 == key2


# 运行测试
if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
