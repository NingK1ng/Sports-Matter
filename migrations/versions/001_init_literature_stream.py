"""init literature stream module

Revision ID: 001_literature_stream
Revises: 
Create Date: 2025-01-01 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_literature_stream'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 创建literature表
    op.create_table(
        'literature',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('pmid', sa.String(length=20), nullable=False, comment='PubMed ID'),
        sa.Column('doi', sa.String(length=100), nullable=True, comment='Digital Object Identifier'),
        sa.Column('title', sa.Text(), nullable=False, comment='文献标题'),
        sa.Column('abstract', sa.Text(), nullable=True, comment='摘要'),
        sa.Column('authors', postgresql.ARRAY(sa.Text()), nullable=True, comment='作者数组'),
        sa.Column('publication_date', sa.Date(), nullable=False, comment='发表日期'),
        sa.Column('journal_name', sa.String(length=200), nullable=True, comment='期刊名称'),
        sa.Column('journal_issn', sa.String(length=20), nullable=True, comment='期刊ISSN - 用于匹配'),
        sa.Column('journal_nlm_abbr', sa.String(length=100), nullable=True, comment='NLM缩写 - 备用匹配'),
        sa.Column('journal_if_5y', sa.Numeric(precision=5, scale=2), nullable=True, comment='5年影响因子'),
        sa.Column('journal_citescore', sa.Numeric(precision=5, scale=2), nullable=True, comment='CiteScore备用指标'),
        sa.Column('journal_zone', sa.String(length=10), nullable=True, comment='中科院分区'),
        sa.Column('subject_categories', postgresql.ARRAY(sa.String(length=50)), nullable=True, 
                  comment="学科类别数组"),
        sa.Column('literature_types', postgresql.ARRAY(sa.String(length=50)), nullable=True,
                  comment="文献类型数组"),
        sa.Column('extra_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True,
                  comment='额外元数据'),
        sa.Column('crawled_at', sa.TIMESTAMP(), server_default=sa.text('NOW()'), nullable=False, comment='爬取时间'),
        sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.text('NOW()'), nullable=False, comment='更新时间'),
        sa.Column('is_deleted', sa.Boolean(), server_default=sa.text('FALSE'), nullable=False, comment='软删除标记'),
        sa.Column('searchable_text', postgresql.TSVECTOR(), nullable=True, comment='全文检索向量'),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('NOW()'), nullable=False, comment='创建时间'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('pmid'),
        comment='文献主表'
    )
    
    # 创建索引
    op.create_index('idx_lit_pmid', 'literature', ['pmid'], unique=True)
    op.create_index('idx_lit_subject_cats', 'literature', ['subject_categories'], postgresql_using='gin')
    op.create_index('idx_lit_lit_types', 'literature', ['literature_types'], postgresql_using='gin')
    op.create_index('idx_lit_pub_date', 'literature', [sa.text('publication_date DESC')])
    op.create_index('idx_lit_journal_issn', 'literature', ['journal_issn'], 
                    postgresql_where=sa.text('journal_issn IS NOT NULL'))
    op.create_index('idx_lit_searchable', 'literature', ['searchable_text'], postgresql_using='gin')
    op.create_index('idx_lit_extra_metadata', 'literature', ['extra_metadata'], postgresql_using='gin',
                    postgresql_ops={'extra_metadata': 'jsonb_path_ops'})
    
    # 创建触发器函数更新searchable_text
    op.execute("""
        CREATE OR REPLACE FUNCTION update_searchable_text() RETURNS TRIGGER AS $$
        BEGIN
            NEW.searchable_text := to_tsvector('english', 
                COALESCE(NEW.title, '') || ' ' || COALESCE(NEW.abstract, '')
            );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    
    op.execute("""
        CREATE TRIGGER trigger_update_searchable 
        BEFORE INSERT OR UPDATE ON literature
        FOR EACH ROW EXECUTE FUNCTION update_searchable_text();
    """)
    
    # 创建journal_metadata表
    op.create_table(
        'journal_metadata',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('issn', sa.String(length=20), nullable=False, comment='期刊ISSN'),
        sa.Column('nlm_abbr', sa.String(length=100), nullable=True, comment='NLM缩写'),
        sa.Column('full_name', sa.String(length=300), nullable=False, comment='期刊全名'),
        sa.Column('if_5y', sa.Numeric(precision=5, scale=2), nullable=True, comment='5年影响因子'),
        sa.Column('citescore', sa.Numeric(precision=5, scale=2), nullable=True, comment='CiteScore'),
        sa.Column('h_index', sa.Integer(), nullable=True, comment='h指数'),
        sa.Column('composite_score', sa.Numeric(precision=3, scale=1), nullable=True, comment='综合评分'),
        sa.Column('cas_zone', sa.String(length=10), nullable=True, comment='中科院分区'),
        sa.Column('is_top_journal', sa.Boolean(), server_default=sa.text('FALSE'), nullable=False, comment='是否5本顶刊'),
        sa.Column('is_blacklisted', sa.Boolean(), server_default=sa.text('FALSE'), nullable=False, comment='是否黑名单'),
        sa.Column('extra_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(), server_default=sa.text('NOW()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('issn'),
        comment='期刊元数据表（113本）'
    )
    
    op.create_index('idx_journal_issn_unique', 'journal_metadata', ['issn'], unique=True)
    op.create_index('idx_journal_nlm_abbr', 'journal_metadata', ['nlm_abbr'])
    op.create_index('idx_journal_top', 'journal_metadata', ['is_top_journal'],
                    postgresql_where=sa.text('is_top_journal = TRUE'))
    op.create_index('idx_journal_blacklist', 'journal_metadata', ['is_blacklisted'],
                    postgresql_where=sa.text('is_blacklisted = TRUE'))
    
    # 创建subject_category_config表
    op.create_table(
        'subject_category_config',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('category_key', sa.String(length=50), nullable=False, comment='分类键'),
        sa.Column('display_name', sa.String(length=100), nullable=False, comment='显示名称'),
        sa.Column('description', sa.Text(), nullable=True, comment='分类描述'),
        sa.Column('pubmed_query', sa.Text(), nullable=False, comment='完整的MeSH检索式'),
        sa.Column('doc_count', sa.Integer(), server_default=sa.text('0'), nullable=False, comment='当前文献数量'),
        sa.Column('last_updated', sa.TIMESTAMP(), nullable=True, comment='最后统计更新时间'),
        sa.Column('display_order', sa.Integer(), nullable=True, comment='显示顺序'),
        sa.Column('is_enabled', sa.Boolean(), server_default=sa.text('TRUE'), nullable=False, comment='是否启用'),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('NOW()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('category_key'),
        comment='学科分类配置表（8大类）'
    )
    
    op.create_index('idx_category_key', 'subject_category_config', ['category_key'], unique=True)
    op.create_index('idx_category_enabled', 'subject_category_config', ['is_enabled'])
    
    # 创建crawl_task_log表
    op.create_table(
        'crawl_task_log',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('task_type', sa.String(length=50), nullable=False, comment='任务类型'),
        sa.Column('category_key', sa.String(length=50), nullable=True, comment='针对哪个学科类'),
        sa.Column('query_params', postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment='执行参数JSON'),
        sa.Column('last_successful_edat', sa.TIMESTAMP(), nullable=True, comment='上次成功爬取的最后一篇文献EDAT'),
        sa.Column('retry_start_position', sa.Integer(), nullable=True, comment='断点位置'),
        sa.Column('status', sa.String(length=20), nullable=False, comment='状态'),
        sa.Column('total_fetched', sa.Integer(), server_default=sa.text('0'), nullable=False, comment='总获取数'),
        sa.Column('new_inserted', sa.Integer(), server_default=sa.text('0'), nullable=False, comment='新增数'),
        sa.Column('duplicates_skipped', sa.Integer(), server_default=sa.text('0'), nullable=False, comment='跳过数'),
        sa.Column('error_message', sa.Text(), nullable=True, comment='错误信息'),
        sa.Column('started_at', sa.TIMESTAMP(), nullable=False, comment='开始时间（UTC）'),
        sa.Column('finished_at', sa.TIMESTAMP(), nullable=True, comment='完成时间（UTC）'),
        sa.Column('duration_seconds', sa.Integer(), nullable=True, comment='执行时长（秒）'),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('NOW()'), nullable=False),
        sa.CheckConstraint("status IN ('running', 'success', 'failed')", name='check_status_valid'),
        sa.PrimaryKeyConstraint('id'),
        comment='爬取任务日志表'
    )
    
    op.create_index('idx_crawl_status', 'crawl_task_log', ['status', sa.text('started_at DESC')])
    op.create_index('idx_crawl_category', 'crawl_task_log', ['category_key', sa.text('started_at DESC')])
    op.create_index('idx_crawl_last_success', 'crawl_task_log', [sa.text('last_successful_edat DESC')],
                    postgresql_where=sa.text("status = 'success'"))


def downgrade() -> None:
    # 删除表（逆序）
    op.drop_table('crawl_task_log')
    op.drop_table('subject_category_config')
    op.drop_table('journal_metadata')
    
    # 删除触发器和函数
    op.execute("DROP TRIGGER IF EXISTS trigger_update_searchable ON literature;")
    op.execute("DROP FUNCTION IF EXISTS update_searchable_text();")
    
    op.drop_table('literature')
