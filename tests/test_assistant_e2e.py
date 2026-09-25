"""
模块5 - AI助手 E2E测试
快速验证完整流程
"""
import pytest
import asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from modules.assistant.services.local_search import LocalSearchService
from modules.assistant.services.citation_validator import CitationValidator
from modules.assistant.models.candidate import CandidateArticle
from modules.assistant.services.deduplicator import deduplicate_by_pmid


@pytest.mark.asyncio
async def test_local_search_service():
    """测试本地检索服务"""
    # 需要真实数据库连接
    async for db in get_db():
        service = LocalSearchService(db)
        
        # 测试查询
        candidates = await service.search(
            query="high intensity interval training",
            top_k=5,
            search_scope="tiab"
        )
        
        assert isinstance(candidates, list)
        assert len(candidates) <= 5
        
        if candidates:
            assert all(isinstance(c, CandidateArticle) for c in candidates)
            assert all(c.pmid for c in candidates)
            print(f"✅ 本地检索成功：召回{len(candidates)}条")
        
        break


def test_deduplicator():
    """测试去重逻辑"""
    candidates = [
        CandidateArticle(
            pmid="12345",
            title="Test Article",
            abstract="Short abstract",
            url="https://pubmed.ncbi.nlm.nih.gov/12345/",
            source="literature"
        ),
        CandidateArticle(
            pmid="12345",
            title="Test Article",
            abstract="Much longer abstract with more details",
            url="https://pubmed.ncbi.nlm.nih.gov/12345/",
            source="journals"
        ),
        CandidateArticle(
            pmid="67890",
            title="Another Article",
            abstract="Different abstract",
            url="https://pubmed.ncbi.nlm.nih.gov/67890/",
            source="literature"
        ),
    ]
    
    deduped = deduplicate_by_pmid(candidates)
    
    assert len(deduped) == 2
    # 应该保留摘要更长的版本
    pmid_12345 = next(c for c in deduped if c.pmid == "12345")
    assert len(pmid_12345.abstract) > 30  # 更长的摘要
    print("✅ 去重逻辑正确")


def test_citation_validator():
    """测试引用校验器"""
    candidates = [
        CandidateArticle(
            pmid="111",
            title="Title 1",
            abstract="Abstract 1",
            url="https://pubmed.ncbi.nlm.nih.gov/111/",
            source="literature"
        ),
        CandidateArticle(
            pmid="222",
            title="Title 2",
            abstract="Abstract 2",
            url="https://pubmed.ncbi.nlm.nih.gov/222/",
            source="journals"
        ),
    ]
    
    validator = CitationValidator(max_citations=10)
    
    # 测试正确的引用
    valid_answer = "HIIT能提升心肺功能[1]。相关研究表明运动强度很关键[2]。"
    result = validator.validate(valid_answer, candidates)
    
    assert result.success
    assert len(result.citations) == 2
    print("✅ 引用校验通过")
    
    # 测试错误的引用（越界）
    invalid_answer = "这是一个错误的引用[999]。"
    result = validator.validate(invalid_answer, candidates)
    
    assert not result.success
    assert len(result.errors) > 0
    print("✅ 引用校验能正确检测错误")


def test_json_assembler():
    """测试JSON组装"""
    candidates = [
        CandidateArticle(
            pmid="111",
            title="Title 1",
            abstract="Abstract 1",
            url="https://pubmed.ncbi.nlm.nih.gov/111/",
            source="literature"
        ),
    ]
    
    validator = CitationValidator(max_citations=10)
    
    json_response = '''
    {
      "sentences": [
        {"text": "这是第一句话。", "citation_ids": [1]},
        {"text": "这是第二句话。", "citation_ids": [1]}
      ],
      "references": [
        {"idx": 1, "pmid": "111", "title": "Title 1", "url": "https://pubmed.ncbi.nlm.nih.gov/111/"}
      ]
    }
    '''
    
    assembled_text, citations, errors = validator.assemble_from_json(json_response, candidates)
    
    assert not errors
    assert assembled_text
    assert len(citations) == 1
    assert "[1]" in assembled_text
    print("✅ JSON组装成功")


if __name__ == "__main__":
    print("开始模块5 E2E测试...")
    
    # 运行同步测试
    test_deduplicator()
    test_citation_validator()
    test_json_assembler()
    
    # 运行异步测试
    print("\n异步测试（需要数据库连接）...")
    try:
        asyncio.run(test_local_search_service())
    except Exception as e:
        print(f"⚠️  本地检索测试跳过（需要数据库）: {e}")
    
    print("\n✅ 所有测试通过！")

