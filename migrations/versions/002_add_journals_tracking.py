"""add journals tracking module

Revision ID: 002_journals_tracking
Revises: 001_literature_stream
Create Date: 2025-01-04

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '002_journals_tracking'
down_revision = '001_literature_stream'
branch_labels = None
depends_on = None


def upgrade():
    """创建顶刊追踪模块的所有表和索引"""
    
    # 启用unaccent扩展（用于字符标准化）
    op.execute('CREATE EXTENSION IF NOT EXISTS unaccent')
    
    # 1. 创建journal_metadata_tracked表（避免与模块1同名表冲突）
    op.create_table(
        'journal_metadata_tracked',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('issn_l', sa.String(length=20), nullable=False, comment='ISSN-L（主键）'),
        sa.Column('issn_print', sa.String(length=20), nullable=True, comment='Print ISSN'),
        sa.Column('issn_electronic', sa.String(length=20), nullable=True, comment='Electronic ISSN'),
        sa.Column('full_name', sa.String(length=300), nullable=False, comment='期刊全名'),
        sa.Column('short_name', sa.String(length=100), nullable=True, comment='期刊简称'),
        sa.Column('display_name', sa.String(length=100), nullable=False, comment='显示名称'),
        sa.Column('category', sa.String(length=50), nullable=False, comment='期刊分类：sports_science|cns'),
        sa.Column('estimated_if', sa.Numeric(precision=5, scale=2), nullable=True, comment='估计影响因子'),
        sa.Column('publisher', sa.String(length=200), nullable=True, comment='出版商'),
        sa.Column('website_url', sa.String(length=500), nullable=True, comment='期刊网站'),
        sa.Column('last_crawled_until', sa.TIMESTAMP(timezone=True), nullable=True, comment='最后爬取截止时间'),
        sa.Column('article_count', sa.Integer(), nullable=False, server_default=sa.text('0'), comment='文章总数'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id'),
        comment='期刊元数据表（13本，顶刊追踪）'
    )
    op.create_index('idx_journal_tracked_issn_l', 'journal_metadata_tracked', ['issn_l'], unique=True)
    op.create_index('idx_journal_tracked_category', 'journal_metadata_tracked', ['category'])
    
    # 2. 创建journal_articles表
    op.create_table(
        'journal_articles',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('doi', sa.String(length=100), nullable=False, comment='DOI（唯一标识，归一化：小写、去空格）'),
        sa.Column('title', sa.Text(), nullable=False, comment='文章标题'),
        sa.Column('abstract', sa.Text(), nullable=True, comment='摘要（可能为空）'),
        sa.Column('abstract_source', sa.String(length=20), nullable=False, server_default=sa.text("'crossref'"), comment='摘要来源：crossref|none'),
        sa.Column('authors', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='作者数组（JSONB格式）'),
        sa.Column('published_at_precise', sa.TIMESTAMP(timezone=True), nullable=False, comment='发表时间（精确到秒）'),
        sa.Column('publication_date', sa.Date(), nullable=False, comment='发表日期（派生字段）'),
        sa.Column('indexed_at', sa.TIMESTAMP(timezone=True), nullable=True, comment='Crossref收录时间'),
        sa.Column('journal_issn', sa.String(length=20), nullable=False, comment='期刊ISSN-L'),
        sa.Column('journal_name', sa.String(length=200), nullable=True, comment='期刊名称'),
        sa.Column('category', sa.String(length=50), nullable=False, comment='期刊分类：sports_science|cns'),
        sa.Column('openalex_id', sa.String(length=100), nullable=True, comment='OpenAlex作品ID'),
        sa.Column('cited_by_count', sa.Integer(), nullable=True, comment='被引次数'),
        sa.Column('cited_by_percentile_year', sa.Numeric(precision=5, scale=2), nullable=True, comment='年度被引分位数'),
        sa.Column('labels', postgresql.ARRAY(sa.String(length=20)), nullable=True, comment='标签数组'),
        sa.Column('first_seen_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()'), comment='首次爬取时间'),
        sa.Column('last_citation_update_at', sa.TIMESTAMP(timezone=True), nullable=True, comment='最后被引更新时间'),
        sa.Column('title_vector', postgresql.TSVECTOR(), nullable=True, comment='标题搜索向量'),
        sa.Column('abstract_vector', postgresql.TSVECTOR(), nullable=True, comment='摘要搜索向量'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('doi', name='uq_journal_articles_doi'),
        comment='期刊文章主表'
    )
    
    # 创建索引
    op.create_index('idx_articles_doi', 'journal_articles', ['doi'], unique=True)
    op.create_index('idx_articles_pub_date', 'journal_articles', [sa.text('publication_date DESC')])
    op.create_index('idx_articles_category_date', 'journal_articles', ['category', sa.text('publication_date DESC')])
    op.create_index('idx_articles_issn_date', 'journal_articles', ['journal_issn', sa.text('publication_date DESC')])
    op.create_index('idx_articles_labels', 'journal_articles', ['labels'], postgresql_using='gin')
    op.create_index('idx_articles_title_fts', 'journal_articles', ['title_vector'], postgresql_using='gin')
    op.create_index('idx_articles_abstract_fts', 'journal_articles', ['abstract_vector'], postgresql_using='gin')
    op.create_index('idx_articles_citations', 'journal_articles', [sa.text('cited_by_count DESC NULLS LAST')])
    
    # 3. 创建触发器函数（自动更新搜索向量）
    op.execute("""
        CREATE OR REPLACE FUNCTION update_journal_article_search_vectors()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.title_vector := to_tsvector('english', unaccent(COALESCE(NEW.title, '')));
            NEW.abstract_vector := to_tsvector('english', unaccent(COALESCE(NEW.abstract, '')));
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    
    # 4. 创建触发器
    op.execute("""
        CREATE TRIGGER tsvector_update_trigger_journals
        BEFORE INSERT OR UPDATE OF title, abstract
        ON journal_articles
        FOR EACH ROW
        EXECUTE FUNCTION update_journal_article_search_vectors();
    """)
    
    # 5. 创建journal_crawl_state表
    op.create_table(
        'journal_crawl_state',
        sa.Column('issn_l', sa.String(length=20), nullable=False, comment='期刊ISSN-L'),
        sa.Column('last_crawled_until', sa.TIMESTAMP(timezone=True), nullable=True, comment='最后成功爬取的截止时间（UTC）'),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()'), comment='更新时间'),
        sa.PrimaryKeyConstraint('issn_l'),
        comment='期刊爬取状态表（断点续传）'
    )
    
    # 6. 创建crawl_task_log_journals表
    op.create_table(
        'crawl_task_log_journals',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('task_type', sa.String(length=50), nullable=False, comment='任务类型：incremental|cold_start|citation_update'),
        sa.Column('issn_l', sa.String(length=20), nullable=True, comment='期刊ISSN-L（null表示全部）'),
        sa.Column('window_from', sa.TIMESTAMP(timezone=True), nullable=True, comment='时间窗口起始（UTC）'),
        sa.Column('window_until', sa.TIMESTAMP(timezone=True), nullable=True, comment='时间窗口结束（UTC）'),
        sa.Column('status', sa.String(length=20), nullable=False, comment='状态：running|success|failed'),
        sa.Column('total_fetched', sa.Integer(), nullable=False, server_default=sa.text('0'), comment='总获取数'),
        sa.Column('new_inserted', sa.Integer(), nullable=False, server_default=sa.text('0'), comment='新增数'),
        sa.Column('updated_count', sa.Integer(), nullable=False, server_default=sa.text('0'), comment='更新数'),
        sa.Column('retries', sa.Integer(), nullable=False, server_default=sa.text('0'), comment='重试次数'),
        sa.Column('error_message', sa.Text(), nullable=True, comment='错误信息'),
        sa.Column('started_at', sa.TIMESTAMP(timezone=True), nullable=False, comment='开始时间（UTC）'),
        sa.Column('finished_at', sa.TIMESTAMP(timezone=True), nullable=True, comment='完成时间（UTC）'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint("status IN ('running', 'success', 'failed')", name='check_status_valid_journals'),
        comment='爬取任务日志表（顶刊追踪）'
    )
    op.create_index('idx_crawl_log_status', 'crawl_task_log_journals', ['status', sa.text('started_at DESC')])
    op.create_index('idx_crawl_log_issn', 'crawl_task_log_journals', ['issn_l', sa.text('started_at DESC')])


def downgrade():
    """回滚：删除所有表和索引"""
    
    # 删除触发器
    op.execute('DROP TRIGGER IF EXISTS tsvector_update_trigger_journals ON journal_articles')
    op.execute('DROP FUNCTION IF EXISTS update_journal_article_search_vectors()')
    
    # 删除表
    op.drop_table('crawl_task_log_journals')
    op.drop_table('journal_crawl_state')
    op.drop_table('journal_articles')
    op.drop_table('journal_metadata_tracked')
    
    # 注意：不删除unaccent扩展，因为可能被其他模块使用
