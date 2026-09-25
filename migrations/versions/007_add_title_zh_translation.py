"""add title_zh translation fields

Revision ID: 007_add_title_zh
Revises: 006_add_literature_pool
Create Date: 2025-11-14 14:30:00

为 literature 和 journal_articles 表添加中文标题翻译字段
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '007_add_title_zh'
down_revision = 'b2165822fad3'  # add_representative_terms_to_community（最新的迁移）
branch_labels = None
depends_on = None


def upgrade():
    # 为 literature 表添加翻译字段
    op.add_column('literature', sa.Column('title_zh', sa.Text(), nullable=True, comment='中文标题'))

    # 为 journal_articles 表添加翻译字段
    op.add_column('journal_articles', sa.Column('title_zh', sa.Text(), nullable=True, comment='中文标题'))

    # 创建索引（提升查询性能）
    op.create_index(
        'idx_lit_title_zh',
        'literature',
        ['title_zh'],
        postgresql_where=sa.text('title_zh IS NOT NULL')
    )
    op.create_index(
        'idx_journal_title_zh',
        'journal_articles',
        ['title_zh'],
        postgresql_where=sa.text('title_zh IS NOT NULL')
    )


def downgrade():
    # 删除索引
    op.drop_index('idx_journal_title_zh', table_name='journal_articles')
    op.drop_index('idx_lit_title_zh', table_name='literature')

    # 删除列
    op.drop_column('journal_articles', 'title_zh')
    op.drop_column('literature', 'title_zh')
