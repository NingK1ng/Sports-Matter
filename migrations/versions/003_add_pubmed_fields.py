"""add pubmed enrichment fields

Revision ID: 003_pubmed_enrichment
Revises: 002_journals_tracking
Create Date: 2025-11-05

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '003_pubmed_enrichment'
down_revision = '002_journals_tracking'
branch_labels = None
depends_on = None


def upgrade():
    # 添加PMID列
    op.add_column(
        'journal_articles',
        sa.Column('pmid', sa.String(length=20), nullable=True, comment='PubMed PMID')
    )
    
    # 唯一约束（允许NULL）
    op.create_unique_constraint('uq_journal_articles_pmid', 'journal_articles', ['pmid'])
    
    # 索引
    op.create_index('idx_articles_pmid', 'journal_articles', ['pmid'])


def downgrade():
    # 回滚索引与列
    op.drop_index('idx_articles_pmid', table_name='journal_articles')
    op.drop_constraint('uq_journal_articles_pmid', 'journal_articles', type_='unique')
    op.drop_column('journal_articles', 'pmid')

























