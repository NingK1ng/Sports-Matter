"""
标签计算器
任务4.1-4.4: 两阶段标签系统（时效性 + 被引数）
"""
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
import yaml
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class LabelCalculator:
    """标签计算器"""

    def __init__(self, config_path: Optional[Path] = None):
        """
        初始化标签计算器
        
        Args:
            config_path: 阈值配置文件路径
        """
        if config_path is None:
            config_path = Path(__file__).parent.parent.parent.parent / "config" / "journals-tracking" / "thresholds.yaml"
        
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
        
        self.sports_science_config = self.config["sports_science"]
        self.cns_config = self.config["cns"]
        self.label_rules = self.config["label_rules"]

    def _to_utc(self, dt: datetime) -> datetime:
        """
        归一化时间为UTC时区，避免naive/aware相减报错。
        """
        if dt is None:
            return datetime.now(timezone.utc)
        try:
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            return dt

    def calculate_labels(
        self,
        publication_date: datetime,
        category: str,
        cited_by_count: Optional[int] = None,
        cited_by_percentile_year: Optional[float] = None,
    ) -> List[str]:
        """
        计算文章的所有标签
        
        Args:
            publication_date: 发表日期
            category: 期刊分类（sports_science|cns）
            cited_by_count: 被引次数
            cited_by_percentile_year: 年度被引分位数
        
        Returns:
            标签列表
        """
        labels = []
        
        # 阶段1: 时效性标签
        time_labels = self.calculate_time_labels(publication_date)
        labels.extend(time_labels)
        
        # 阶段2: 被引数标签（如果有被引数据）
        if cited_by_count is not None:
            citation_labels = self.calculate_citation_labels(
                publication_date=publication_date,
                category=category,
                cited_by_count=cited_by_count,
                cited_by_percentile_year=cited_by_percentile_year,
            )
            labels.extend(citation_labels)
        
        return labels

    def calculate_time_labels(self, publication_date: datetime) -> List[str]:
        """
        计算时效性标签
        
        Args:
            publication_date: 发表日期
        
        Returns:
            时效性标签列表（new|recent）
        """
        now = datetime.now(timezone.utc)
        pub = self._to_utc(publication_date)
        days_since_pub = (now - pub).days
        
        new_threshold = self.label_rules["time_labels"]["new"]
        recent_threshold = self.label_rules["time_labels"]["recent"]
        
        if days_since_pub <= new_threshold:
            return ["new"]
        elif days_since_pub <= recent_threshold:
            return ["recent"]
        else:
            return []

    def calculate_citation_labels(
        self,
        publication_date: datetime,
        category: str,
        cited_by_count: int,
        cited_by_percentile_year: Optional[float] = None,
    ) -> List[str]:
        """
        计算被引数标签
        
        Args:
            publication_date: 发表日期
            category: 期刊分类
            cited_by_count: 被引次数
            cited_by_percentile_year: 年度被引分位数
        
        Returns:
            被引数标签列表（trending|hot|classic）
        """
        labels = []
        
        # 选择配置
        config = self.sports_science_config if category == "sports_science" else self.cns_config
        
        now = datetime.now(timezone.utc)
        pub = self._to_utc(publication_date)
        days_since_pub = (now - pub).days
        
        # Trending标签（早期趋势）
        trending_config = config["trending"]
        if (trending_config["min_days"] <= days_since_pub <= trending_config["max_days"] and
            days_since_pub >= trending_config["cooldown_days"]):
            # 计算被引速率
            rate = cited_by_count / max(days_since_pub, 1)
            if rate > trending_config["rate_threshold"]:
                labels.append("trending")
        
        # Hot标签（热点）
        hot_config = config["hot"]
        if days_since_pub >= hot_config["min_days"]:
            if cited_by_percentile_year and cited_by_percentile_year > hot_config["percentile_threshold"]:
                labels.append("hot")
        
        # Classic标签（经典）
        classic_config = config["classic"]
        if days_since_pub >= classic_config["min_days"]:
            if cited_by_count > classic_config["count_threshold"]:
                labels.append("classic")
        
        return labels

    def get_label_emoji(self, label: str) -> str:
        """
        获取标签对应的emoji
        
        Args:
            label: 标签名称
        
        Returns:
            emoji字符
        """
        emoji_map = {
            "new": "🆕",
            "recent": "📅",
            "trending": "📈",
            "hot": "🔥",
            "classic": "🏆",
        }
        return emoji_map.get(label, "")

    def get_label_display_name(self, label: str) -> str:
        """
        获取标签显示名称
        
        Args:
            label: 标签名称
        
        Returns:
            显示名称
        """
        display_map = {
            "new": "New",
            "recent": "Recent",
            "trending": "Trending",
            "hot": "Hot",
            "classic": "Classic",
        }
        return display_map.get(label, label.capitalize())
