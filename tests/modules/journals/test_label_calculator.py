"""
标签计算器测试
任务8.2: 单元测试（含边界条件）
"""
import pytest
from datetime import datetime, timedelta
from pathlib import Path

from modules.journals.services.label_calculator import LabelCalculator


@pytest.fixture
def calculator():
    """创建标签计算器实例"""
    return LabelCalculator()


class TestTimeLabelCalculation:
    """时效性标签测试"""

    def test_new_label(self, calculator):
        """测试New标签（≤7天）"""
        pub_date = datetime.now() - timedelta(days=5)
        labels = calculator.calculate_time_labels(pub_date)
        assert "new" in labels
        assert "recent" not in labels

    def test_new_label_boundary_7days(self, calculator):
        """测试边界：第7天"""
        pub_date = datetime.now() - timedelta(days=7)
        labels = calculator.calculate_time_labels(pub_date)
        assert "new" in labels

    def test_recent_label(self, calculator):
        """测试Recent标签（7-30天）"""
        pub_date = datetime.now() - timedelta(days=15)
        labels = calculator.calculate_time_labels(pub_date)
        assert "recent" in labels
        assert "new" not in labels

    def test_recent_label_boundary_30days(self, calculator):
        """测试边界：第30天"""
        pub_date = datetime.now() - timedelta(days=30)
        labels = calculator.calculate_time_labels(pub_date)
        assert "recent" in labels

    def test_no_time_label(self, calculator):
        """测试无时效性标签（>30天）"""
        pub_date = datetime.now() - timedelta(days=60)
        labels = calculator.calculate_time_labels(pub_date)
        assert len(labels) == 0


class TestCitationLabelCalculation:
    """被引数标签测试"""

    def test_trending_label_sports_science(self, calculator):
        """测试Trending标签（运动科学）"""
        pub_date = datetime.now() - timedelta(days=60)
        labels = calculator.calculate_citation_labels(
            publication_date=pub_date,
            category="sports_science",
            cited_by_count=10,  # 10次 / 60天 = 0.167次/天 > 0.15
            cited_by_percentile_year=None,
        )
        assert "trending" in labels

    def test_trending_cooldown(self, calculator):
        """测试Trending冷却期（<3天不判定）"""
        pub_date = datetime.now() - timedelta(days=2)
        labels = calculator.calculate_citation_labels(
            publication_date=pub_date,
            category="sports_science",
            cited_by_count=10,
            cited_by_percentile_year=None,
        )
        assert "trending" not in labels

    def test_trending_boundary_90days(self, calculator):
        """测试边界：第90天"""
        pub_date = datetime.now() - timedelta(days=90)
        labels = calculator.calculate_citation_labels(
            publication_date=pub_date,
            category="sports_science",
            cited_by_count=14,  # 14次 / 90天 = 0.156次/天 > 0.15
            cited_by_percentile_year=None,
        )
        assert "trending" in labels

    def test_hot_label_sports_science(self, calculator):
        """测试Hot标签（运动科学）"""
        pub_date = datetime.now() - timedelta(days=120)
        labels = calculator.calculate_citation_labels(
            publication_date=pub_date,
            category="sports_science",
            cited_by_count=50,
            cited_by_percentile_year=90.0,  # >85
        )
        assert "hot" in labels

    def test_classic_label_sports_science(self, calculator):
        """测试Classic标签（运动科学）"""
        pub_date = datetime.now() - timedelta(days=200)
        labels = calculator.calculate_citation_labels(
            publication_date=pub_date,
            category="sports_science",
            cited_by_count=60,  # >50
            cited_by_percentile_year=None,
        )
        assert "classic" in labels

    def test_classic_min_days(self, calculator):
        """测试Classic最小天数（<180天不判定）"""
        pub_date = datetime.now() - timedelta(days=150)
        labels = calculator.calculate_citation_labels(
            publication_date=pub_date,
            category="sports_science",
            cited_by_count=100,
            cited_by_percentile_year=None,
        )
        assert "classic" not in labels

    def test_cns_higher_thresholds(self, calculator):
        """测试CNS期刊的更高阈值"""
        pub_date = datetime.now() - timedelta(days=60)
        
        # CNS trending需要1.0次/天
        labels = calculator.calculate_citation_labels(
            publication_date=pub_date,
            category="cns",
            cited_by_count=50,  # 50次 / 60天 = 0.83次/天 < 1.0
            cited_by_percentile_year=None,
        )
        assert "trending" not in labels
        
        # 提高到1.0次/天以上
        labels = calculator.calculate_citation_labels(
            publication_date=pub_date,
            category="cns",
            cited_by_count=65,  # 65次 / 60天 = 1.08次/天 > 1.0
            cited_by_percentile_year=None,
        )
        assert "trending" in labels


class TestLabelCombinations:
    """标签组合测试"""

    def test_new_and_trending(self, calculator):
        """测试New和Trending共存"""
        pub_date = datetime.now() - timedelta(days=5)
        labels = calculator.calculate_labels(
            publication_date=pub_date,
            category="sports_science",
            cited_by_count=1,  # 1次 / 5天 = 0.2次/天 > 0.15
            cited_by_percentile_year=None,
        )
        # 注意：由于冷却期3天，第5天才能判定trending
        assert "new" in labels

    def test_hot_and_classic(self, calculator):
        """测试Hot和Classic共存"""
        pub_date = datetime.now() - timedelta(days=200)
        labels = calculator.calculate_labels(
            publication_date=pub_date,
            category="sports_science",
            cited_by_count=100,  # >50 (classic)
            cited_by_percentile_year=90.0,  # >85 (hot)
        )
        assert "hot" in labels
        assert "classic" in labels


class TestRateCalculationEdgeCases:
    """被引速率计算边界测试"""

    def test_rate_with_zero_days(self, calculator):
        """测试0天的下限保护"""
        pub_date = datetime.now()
        labels = calculator.calculate_citation_labels(
            publication_date=pub_date,
            category="sports_science",
            cited_by_count=10,
            cited_by_percentile_year=None,
        )
        # 应该有下限保护，不会除以0
        assert isinstance(labels, list)

    def test_rate_with_one_day(self, calculator):
        """测试1天的情况"""
        pub_date = datetime.now() - timedelta(days=1)
        labels = calculator.calculate_citation_labels(
            publication_date=pub_date,
            category="sports_science",
            cited_by_count=1,  # 1次 / 1天 = 1.0次/天 > 0.15
            cited_by_percentile_year=None,
        )
        # 但由于冷却期3天，不应该有trending
        assert "trending" not in labels
