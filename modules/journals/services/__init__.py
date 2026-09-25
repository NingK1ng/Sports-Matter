"""
顶刊追踪模块服务层
"""

from modules.journals.services.crossref_client import CrossrefJournalClient
from modules.journals.services.openalex_client import OpenAlexClient
from modules.journals.services.label_calculator import LabelCalculator
from modules.journals.services.abstract_fetcher import AbstractFetcher
from modules.journals.services.text_cleaner import clean_jats_abstract

__all__ = [
    "CrossrefJournalClient",
    "OpenAlexClient",
    "LabelCalculator",
    "AbstractFetcher",
    "clean_jats_abstract",
]
