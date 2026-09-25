"""arXiv模块数据模型"""
from modules.arxiv.models.arxiv_article import ArxivArticle
from modules.arxiv.models.arxiv_crawl_log import ArxivCrawlLog
from modules.arxiv.models.arxiv_category_config import ArxivCategoryConfig

__all__ = ["ArxivArticle", "ArxivCrawlLog", "ArxivCategoryConfig"]
