"""
配置管理模块

使用Pydantic Settings从环境变量加载配置
"""

from functools import lru_cache
from typing import List, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ==========================================
    # 应用配置
    # ==========================================
    app_name: str = Field(default="Sports Matter", alias="APP_NAME")
    app_version: str = Field(default="1.0.0", alias="APP_VERSION")
    app_env: str = Field(default="development", alias="APP_ENV")
    debug: bool = Field(default=False, alias="DEBUG")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # CORS配置
    allowed_origins: str = Field(
        default=(
            "http://localhost:3000,"
            "http://localhost:8000,"
            "http://localhost:8080,"
            "http://localhost:5173,"
            "http://127.0.0.1:5173"
        ),
        alias="ALLOWED_ORIGINS",
    )

    @property
    def allowed_origins_list(self) -> List[str]:
        """将CORS配置转换为列表"""
        return [origin.strip() for origin in self.allowed_origins.split(",")]

    # ==========================================
    # 数据库配置
    # ==========================================
    database_url: str = Field(..., alias="DATABASE_URL")
    database_pool_size: int = Field(default=20, alias="DATABASE_POOL_SIZE")
    database_max_overflow: int = Field(default=40, alias="DATABASE_MAX_OVERFLOW")
    database_pool_timeout: int = Field(default=30, alias="DATABASE_POOL_TIMEOUT")
    database_pool_recycle: int = Field(default=3600, alias="DATABASE_POOL_RECYCLE")

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        """验证数据库URL格式"""
        if not v.startswith("postgresql"):
            raise ValueError("DATABASE_URL must start with 'postgresql'")
        return v

    # ==========================================
    # Redis配置
    # ==========================================
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    redis_password: Optional[str] = Field(default=None, alias="REDIS_PASSWORD")
    redis_max_connections: int = Field(default=50, alias="REDIS_MAX_CONNECTIONS")

    # ==========================================
    # RabbitMQ配置
    # ==========================================
    rabbitmq_url: str = Field(
        default="amqp://guest:guest@localhost:5672//", alias="RABBITMQ_URL"
    )

    # ==========================================
    # Celery配置
    # ==========================================
    celery_broker_url: str = Field(..., alias="CELERY_BROKER_URL")
    celery_result_backend: str = Field(default="rpc://", alias="CELERY_RESULT_BACKEND")
    celery_task_always_eager: bool = Field(
        default=False, alias="CELERY_TASK_ALWAYS_EAGER"
    )

    # ==========================================
    # 外部API配置
    # ==========================================
    pubmed_email: str = Field(..., alias="PUBMED_EMAIL")
    pubmed_api_key: Optional[str] = Field(default=None, alias="PUBMED_API_KEY")
    pubmed_api_keys: Optional[str] = Field(default=None, alias="PUBMED_API_KEYS")  # 多个密钥（逗号分隔）
    pubmed_api_key_1: Optional[str] = Field(default=None, alias="PUBMED_API_KEY_1")
    pubmed_api_key_2: Optional[str] = Field(default=None, alias="PUBMED_API_KEY_2")
    pubmed_api_key_3: Optional[str] = Field(default=None, alias="PUBMED_API_KEY_3")
    pubmed_tool_name: str = Field(default="sports-matter", alias="PUBMED_TOOL_NAME")

    crossref_email: Optional[str] = Field(default=None, alias="CROSSREF_EMAIL")
    openalex_email: Optional[str] = Field(default=None, alias="OPENALEX_EMAIL")

    deepseek_api_key: Optional[str] = Field(default=None, alias="DEEPSEEK_API_KEY")
    deepseek_base_url: str = Field(
        default="https://api.deepseek.com/v1", alias="DEEPSEEK_BASE_URL"
    )

    # Tavily Web search API（Sports Data 模块使用）
    tavily_api_key: Optional[str] = Field(default=None, alias="TAVILY_API_KEY")
    mineru_api_token: Optional[str] = Field(default=None, alias="MINERU_API_TOKEN")
    
    # 微信登录配置（模块4 - 文献池）
    wechat_app_id: Optional[str] = Field(None, alias="WECHAT_APP_ID")
    wechat_app_secret: Optional[str] = Field(None, alias="WECHAT_APP_SECRET")
    wechat_redirect_uri: Optional[str] = Field(None, alias="WECHAT_REDIRECT_URI")

    # QQ登录配置（模块4 - 文献池，QQ互联OAuth2）
    qq_app_id: Optional[str] = Field(None, alias="QQ_APP_ID")
    qq_app_key: Optional[str] = Field(None, alias="QQ_APP_KEY")
    qq_redirect_uri: Optional[str] = Field(None, alias="QQ_REDIRECT_URI")

    # ==========================================
    # 支付配置（YunGouOS / 支付宝）
    # ==========================================
    yungouos_api_base_url: str = Field(
        default="https://api.pay.yungouos.com", alias="YUNGOUOS_API_BASE_URL"
    )
    yungouos_mch_id: Optional[str] = Field(None, alias="YUNGOUOS_MCH_ID")
    yungouos_pay_key: Optional[str] = Field(None, alias="YUNGOUOS_PAY_KEY")
    yungouos_notify_url: Optional[str] = Field(None, alias="YUNGOUOS_NOTIFY_URL")
    yungouos_return_url: Optional[str] = Field(None, alias="YUNGOUOS_RETURN_URL")
    yungouos_alipay_app_id: Optional[str] = Field(None, alias="YUNGOUOS_ALIPAY_APP_ID")

    # 支付优惠券（前端邀请码输入框复用）
    payment_coupon_half_enabled: bool = Field(default=True, alias="PAYMENT_COUPON_HALF_ENABLED")
    payment_coupon_half_code: str = Field(default="", alias="PAYMENT_COUPON_HALF_CODE")

    # ==========================================
    # 模块2：顶刊追踪（Journals Tracking）
    # ==========================================
    journals_disable_llm_filter_issns: Optional[str] = Field(
        default=None, alias="JOURNALS_DISABLE_LLM_FILTER_ISSNS"
    )
    journals_disable_title_translation_issns: Optional[str] = Field(
        default=None, alias="JOURNALS_DISABLE_TITLE_TRANSLATION_ISSNS"
    )
    journals_title_translation_from_date: Optional[str] = Field(
        default=None, alias="JOURNALS_TITLE_TRANSLATION_FROM_DATE"
    )

    # ==========================================
    # 邀请码（运营开关）
    # ==========================================
    invite_lifetime_enabled: bool = Field(default=False, alias="INVITE_LIFETIME_ENABLED")
    invite_lifetime_code: str = Field(default="", alias="INVITE_LIFETIME_CODE")

    invite_week_enabled: bool = Field(default=False, alias="INVITE_WEEK_ENABLED")
    invite_week_code: str = Field(default="", alias="INVITE_WEEK_CODE")
    invite_week_days: int = Field(default=7, alias="INVITE_WEEK_DAYS")

    @field_validator("pubmed_email")
    @classmethod
    def validate_pubmed_email(cls, v: str) -> str:
        """验证PubMed邮箱"""
        if "@" not in v:
            raise ValueError("PUBMED_EMAIL must be a valid email address")
        return v

    # ==========================================
    # 缓存配置
    # ==========================================
    cache_literature_ttl: int = Field(default=300, alias="CACHE_LITERATURE_TTL")
    cache_category_config_ttl: int = Field(
        default=3600, alias="CACHE_CATEGORY_CONFIG_TTL"
    )
    cache_journal_metadata_ttl: int = Field(
        default=3600, alias="CACHE_JOURNAL_METADATA_TTL"
    )

    # ==========================================
    # 定时任务配置
    # ==========================================
    crawl_schedule_cron: str = Field(default="0 18 * * *", alias="CRAWL_SCHEDULE_CRON")
    crawl_warm_start_enabled: bool = Field(
        default=True, alias="CRAWL_WARM_START_ENABLED"
    )
    crawl_warm_start_from: str = Field(
        default="2024-01-01", alias="CRAWL_WARM_START_FROM"
    )

    # ==========================================
    # 安全配置
    # ==========================================
    secret_key: str = Field(..., alias="SECRET_KEY")
    jwt_secret_key: str = Field(..., alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    jwt_access_token_expire_minutes: int = Field(
        default=30, alias="JWT_ACCESS_TOKEN_EXPIRE_MINUTES"
    )

    # ==========================================
    # 监控配置
    # ==========================================
    sentry_dsn: Optional[str] = Field(default=None, alias="SENTRY_DSN")
    logfire_token: Optional[str] = Field(default=None, alias="LOGFIRE_TOKEN")

    # ==========================================
    # 其他配置
    # ==========================================
    max_workers: int = Field(default=4, alias="MAX_WORKERS")
    timezone: str = Field(default="Asia/Shanghai", alias="TIMEZONE")
    assistant_log_llm: bool = Field(default=False, alias="ASSISTANT_LOG_LLM")


@lru_cache
def get_settings() -> Settings:
    """
    获取配置实例（单例模式）

    Returns:
        Settings: 配置实例

    Example:
        >>> from core.config import get_settings
        >>> settings = get_settings()
        >>> print(settings.app_name)
    """
    return Settings()


# 导出便捷访问
settings = get_settings()
