"""
测试检索式构建器
"""
import pytest
from modules.literature_stream.config.queries import SubjectQueryBuilder


@pytest.fixture
def builder():
    return SubjectQueryBuilder()


def test_build_query_with_subject(builder):
    """测试带学科类的检索式"""
    query = builder.build_query(
        subject_queries=['("Sports Medicine"[mh] OR "Athletic Injuries"[mh])'],
        literature_types=['meta_analysis'],
        date_filter='2024/01/01:2024/12/31'
    )
    
    assert 'Sports Medicine' in query
    assert 'Meta-Analysis' in query
    assert '2024/01/01:2024/12/31' in query


def test_build_query_without_subject(builder):
    """测试无学科类（使用通用闸门）"""
    query = builder.build_query(
        subject_queries=[],
        literature_types=['review']
    )
    
    assert 'Sports' in query or 'Athletes' in query
    assert 'Review' in query


def test_build_date_filter(builder):
    """测试日期过滤器"""
    date_filter = builder.build_date_filter('2024/01/01 00:00:00', '2024/12/31 23:59:59')
    
    assert date_filter == '2024/01/01 00:00:00:2024/12/31 23:59:59'


def test_literature_types(builder):
    """测试文献类型定义"""
    assert 'meta_analysis' in builder.LITERATURE_TYPES
    assert 'original_human' in builder.LITERATURE_TYPES
    assert 'review' in builder.LITERATURE_TYPES
    assert 'guideline' in builder.LITERATURE_TYPES
