"""
Literature Pool API Schemas
"""
from modules.literature_pool.schemas.auth import (
    WeChatLoginResponse,
    WeChatCallbackRequest,
    TokenResponse,
)
from modules.literature_pool.schemas.subscription import (
    SubscriptionCreate,
    SubscriptionUpdate,
    SubscriptionResponse,
    SubscriptionListResponse,
)
from modules.literature_pool.schemas.feed import (
    FeedResponse,
    WiWCardResponse,
    ArticleResponse,
)

__all__ = [
    "WeChatLoginResponse",
    "WeChatCallbackRequest",
    "TokenResponse",
    "SubscriptionCreate",
    "SubscriptionUpdate",
    "SubscriptionResponse",
    "SubscriptionListResponse",
    "FeedResponse",
    "WiWCardResponse",
    "ArticleResponse",
]
