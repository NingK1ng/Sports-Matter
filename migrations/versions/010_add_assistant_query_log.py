"""add assistant query log table

Revision ID: 010_add_assistant_query_log
Revises: 009_add_arxiv_tables
Create Date: 2025-12-20

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "010_add_assistant_query_log"
down_revision: Union[str, None] = "009_add_arxiv_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "assistant_query_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("query", sa.Text(), nullable=False, comment="用户查询"),
        sa.Column("sports_gate", sa.Boolean(), nullable=False, comment="Sports Gate开关状态"),
        sa.Column("use_agent", sa.Boolean(), nullable=False, comment="是否使用Agent模式"),
        sa.Column("top_k", sa.Integer(), nullable=False, comment="召回文献数量"),
        sa.Column("lang", sa.String(length=10), nullable=False, comment="语言: zh|en"),
        sa.Column("literature_recall_count", sa.Integer(), server_default="0", comment="模块1召回数"),
        sa.Column("journals_recall_count", sa.Integer(), server_default="0", comment="模块2召回数"),
        sa.Column("pubmed_agent_count", sa.Integer(), server_default="0", comment="Agent在线召回数"),
        sa.Column("pmid_valid_count", sa.Integer(), server_default="0", comment="有效PMID数"),
        sa.Column("final_candidate_count", sa.Integer(), server_default="0", comment="去重后候选数"),
        sa.Column("search_duration_ms", sa.Integer(), nullable=True, comment="检索耗时(ms)"),
        sa.Column("generation_duration_ms", sa.Integer(), nullable=True, comment="生成耗时(ms)"),
        sa.Column("total_duration_ms", sa.Integer(), nullable=True, comment="总耗时(ms)"),
        sa.Column("input_tokens", sa.Integer(), server_default="0", comment="输入Token数"),
        sa.Column("output_tokens", sa.Integer(), server_default="0", comment="输出Token数"),
        sa.Column("estimated_cost_cny", sa.Numeric(precision=8, scale=4), nullable=True, comment="估算成本(CNY)"),
        sa.Column("agent_steps", postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment="Agent执行步骤JSON"),
        sa.Column("agent_fallback", sa.Boolean(), server_default="FALSE", comment="是否触发回退"),
        sa.Column("status", sa.String(length=20), nullable=False, comment="状态: success|failed|timeout|no_results"),
        sa.Column("error_code", sa.String(length=30), nullable=True, comment="错误码（如果失败）"),
        sa.Column("error_message", sa.Text(), nullable=True, comment="错误信息"),
        sa.Column("citation_count", sa.Integer(), server_default="0", comment="引用数量"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            server_default=sa.text("NOW()"),
            nullable=False,
            comment="创建时间",
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="AI助手查询日志表",
    )

    op.create_index(
        "idx_assistant_query_log_created_at",
        "assistant_query_log",
        [sa.text("created_at DESC")],
    )
    op.create_index(
        "idx_assistant_query_log_status",
        "assistant_query_log",
        ["status", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_assistant_query_log_status", table_name="assistant_query_log")
    op.drop_index("idx_assistant_query_log_created_at", table_name="assistant_query_log")
    op.drop_table("assistant_query_log")
