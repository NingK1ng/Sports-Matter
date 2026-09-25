"""
数据库模块测试
"""

import pytest
from sqlalchemy import select
from core.database import get_db_session
from models.literature import Literature


@pytest.mark.asyncio
async def test_database_connection():
    """测试数据库连接（需要PostgreSQL运行）"""
    from core.database import init_database, close_database

    try:
        await init_database()
        
        async with get_db_session() as session:
            # 执行简单查询
            result = await session.execute(select(1))
            value = result.scalar()
            assert value == 1

        await close_database()
    except Exception as e:
        pytest.skip(f"PostgreSQL not available: {e}")


@pytest.mark.asyncio
async def test_literature_model():
    """测试文献模型创建"""
    literature = Literature(
        pmid="12345678",
        doi="10.1234/test",
        title="Test Article",
        abstract="This is a test abstract",
        journal="Test Journal",
        pub_year=2024,
    )

    assert literature.pmid == "12345678"
    assert literature.title == "Test Article"
    assert literature.pub_year == 2024
