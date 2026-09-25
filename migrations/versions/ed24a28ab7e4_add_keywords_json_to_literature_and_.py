"""add_keywords_json_to_literature_and_journals

Revision ID: ed24a28ab7e4
Revises: de4a3e2e5765
Create Date: 2025-11-08 16:15:35.043997

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'ed24a28ab7e4'
down_revision: Union[str, None] = 'de4a3e2e5765'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 添加literature.keywords_json
    op.add_column(
        'literature',
        sa.Column(
            'keywords_json',
            JSONB,
            nullable=True,
            comment='LLM抽取的关键词: [{term: str, source: abstract|title, score: float}]'
        )
    )
    
    # 添加journal_articles.keywords_json
    op.add_column(
        'journal_articles',
        sa.Column(
            'keywords_json',
            JSONB,
            nullable=True,
            comment='LLM抽取的关键词: [{term: str, source: abstract|title, score: float}]'
        )
    )
    
    # 创建索引以提升查询性能
    op.create_index(
        'ix_literature_keywords_json',
        'literature',
        ['keywords_json'],
        postgresql_using='gin'
    )
    op.create_index(
        'ix_journal_articles_keywords_json',
        'journal_articles',
        ['keywords_json'],
        postgresql_using='gin'
    )


def downgrade() -> None:
    # 删除索引
    op.drop_index('ix_journal_articles_keywords_json', table_name='journal_articles')
    op.drop_index('ix_literature_keywords_json', table_name='literature')
    
    # 删除字段
    op.drop_column('journal_articles', 'keywords_json')
    op.drop_column('literature', 'keywords_json')
