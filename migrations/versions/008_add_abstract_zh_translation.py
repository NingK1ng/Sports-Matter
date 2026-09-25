"""add abstract_zh translation fields

Revision ID: 008_add_abstract_zh
Revises: 007_add_title_zh_translation
Create Date: 2025-11-14

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '008_add_abstract_zh'
down_revision = '007_add_title_zh'  # Fixed: use actual revision ID
branch_labels = None
depends_on = None


def upgrade():
    # 添加 abstract_zh 列到 literature 表
    op.add_column(
        'literature',
        sa.Column('abstract_zh', sa.Text(), nullable=True, comment='中文摘要（DeepSeek翻译）')
    )

    # 添加 abstract_zh 列到 journal_articles 表
    op.add_column(
        'journal_articles',
        sa.Column('abstract_zh', sa.Text(), nullable=True, comment='中文摘要（DeepSeek翻译）')
    )

    # 创建部分索引以优化已翻译内容的查询
    op.create_index(
        'idx_lit_abstract_zh',
        'literature',
        ['abstract_zh'],
        postgresql_where=sa.text('abstract_zh IS NOT NULL')
    )

    op.create_index(
        'idx_journal_abstract_zh',
        'journal_articles',
        ['abstract_zh'],
        postgresql_where=sa.text('abstract_zh IS NOT NULL')
    )


def downgrade():
    # 删除索引
    op.drop_index('idx_journal_abstract_zh', table_name='journal_articles')
    op.drop_index('idx_lit_abstract_zh', table_name='literature')

    # 删除列
    op.drop_column('journal_articles', 'abstract_zh')
    op.drop_column('literature', 'abstract_zh')
