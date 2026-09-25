"""
配置模块测试
"""

import pytest
from core.config import get_settings


def test_get_settings():
    """测试配置加载"""
    settings = get_settings()

    assert settings.app_name == "Sports Matter"
    assert settings.database_url.startswith("postgresql")
    assert settings.pubmed_email is not None


def test_allowed_origins_list():
    """测试CORS配置解析"""
    settings = get_settings()
    origins = settings.allowed_origins_list

    assert isinstance(origins, list)
    assert len(origins) > 0
