"""add arxiv tables

Revision ID: 202411180000
Revises: 202411130000
Create Date: 2025-11-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '202411180000'
down_revision: Union[str, None] = '202411130000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 创建arxiv_articles表
    op.create_table(
        'arxiv_articles',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('arxiv_id', sa.String(length=20), nullable=False, comment='arXiv ID（去版本号）'),
        sa.Column('version', sa.Integer(), nullable=True, comment='版本号'),
        sa.Column('source', sa.String(length=20), nullable=False, comment='来源：arxiv/biorxiv'),
        sa.Column('title', sa.Text(), nullable=False, comment='标题'),
        sa.Column('title_zh', sa.Text(), nullable=True, comment='中文标题'),
        sa.Column('abstract', sa.Text(), nullable=True, comment='摘要'),
        sa.Column('abstract_zh', sa.Text(), nullable=True, comment='中文摘要'),
        sa.Column('primary_category', sa.String(length=50), nullable=True, comment='主分类'),
        sa.Column('categories', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='所有分类数组'),
        sa.Column('sport_category', sa.String(length=50), nullable=True, comment='运动科学分类'),
        sa.Column('sport_relevance', sa.DECIMAL(precision=3, scale=2), nullable=True, comment='运动科学相关度'),
        sa.Column('authors', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='作者列表'),
        sa.Column('published_date', sa.Date(), nullable=True, comment='首次发布日期'),
        sa.Column('updated_date', sa.Date(), nullable=True, comment='最后更新日期'),
        sa.Column('submitted_date', sa.Date(), nullable=True, comment='提交日期'),
        sa.Column('pdf_url', sa.String(length=500), nullable=True, comment='PDF下载地址'),
        sa.Column('abs_url', sa.String(length=500), nullable=True, comment='摘要页地址'),
        sa.Column('title_vector', postgresql.TSVECTOR(), nullable=True, comment='标题向量'),
        sa.Column('abstract_vector', postgresql.TSVECTOR(), nullable=True, comment='摘要向量'),
        sa.Column('crawled_at', sa.DateTime(), nullable=True, comment='爬取时间'),
        sa.Column('updated_at', sa.DateTime(), nullable=True, comment='更新时间'),
        sa.Column('is_deleted', sa.Boolean(), nullable=True, comment='软删除标记'),
        sa.Column('created_at', sa.DateTime(), nullable=True, comment='创建时间'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('arxiv_id')
    )

    # 创建索引
    op.create_index('idx_arxiv_id', 'arxiv_articles', ['arxiv_id'], unique=True)
    op.create_index('idx_arxiv_sport_category', 'arxiv_articles', ['sport_category'],
                    postgresql_where=sa.text('sport_category IS NOT NULL'))
    op.create_index('idx_arxiv_submitted_date', 'arxiv_articles', [sa.text('submitted_date DESC')])
    op.create_index('idx_arxiv_title_fts', 'arxiv_articles', ['title_vector'], postgresql_using='gin')
    op.create_index('idx_arxiv_abstract_fts', 'arxiv_articles', ['abstract_vector'], postgresql_using='gin')
    op.create_index('idx_arxiv_source', 'arxiv_articles', ['source'])
    op.create_index('idx_arxiv_categories_gin', 'arxiv_articles', ['categories'], postgresql_using='gin')

    # 创建arxiv_crawl_log表
    op.create_table(
        'arxiv_crawl_log',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('task_type', sa.String(length=50), nullable=False, comment='任务类型'),
        sa.Column('source', sa.String(length=20), nullable=False, comment='来源'),
        sa.Column('date_from', sa.Date(), nullable=True, comment='起始日期'),
        sa.Column('date_to', sa.Date(), nullable=True, comment='结束日期'),
        sa.Column('batch_number', sa.Integer(), nullable=True, comment='批次号'),
        sa.Column('status', sa.String(length=20), nullable=False, comment='状态'),
        sa.Column('total_fetched', sa.Integer(), nullable=True, comment='L1召回数'),
        sa.Column('llm_processed', sa.Integer(), nullable=True, comment='L2处理数'),
        sa.Column('new_inserted', sa.Integer(), nullable=True, comment='新增入库数'),
        sa.Column('updated_count', sa.Integer(), nullable=True, comment='更新数'),
        sa.Column('error_message', sa.Text(), nullable=True, comment='错误信息'),
        sa.Column('started_at', sa.DateTime(), nullable=False, comment='开始时间'),
        sa.Column('finished_at', sa.DateTime(), nullable=True, comment='结束时间'),
        sa.Column('created_at', sa.DateTime(), nullable=True, comment='创建时间'),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_index('idx_crawl_log_status', 'arxiv_crawl_log', ['status', sa.text('started_at DESC')])
    op.create_index('idx_crawl_log_source', 'arxiv_crawl_log', ['source', sa.text('started_at DESC')])

    # 创建arxiv_category_config表
    op.create_table(
        'arxiv_category_config',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('category_key', sa.String(length=50), nullable=False, comment='分类key'),
        sa.Column('display_name', sa.String(length=100), nullable=False, comment='显示名称'),
        sa.Column('description', sa.Text(), nullable=True, comment='描述'),
        sa.Column('doc_count', sa.Integer(), nullable=True, comment='文档数量'),
        sa.Column('last_updated', sa.DateTime(), nullable=True, comment='最后更新时间'),
        sa.Column('display_order', sa.Integer(), nullable=True, comment='显示顺序'),
        sa.Column('is_enabled', sa.Boolean(), nullable=True, comment='是否启用'),
        sa.Column('created_at', sa.DateTime(), nullable=True, comment='创建时间'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('category_key')
    )

    # 插入4大分类初始数据
    op.execute("""
        INSERT INTO arxiv_category_config (category_key, display_name, description, display_order, is_enabled) VALUES
        ('technology', '体育工程与技术', 'AI+运动、可穿戴设备、运动数据分析、视频分析', 1, true),
        ('training', '运动训练', '训练方法、技术战术、表现优化', 2, true),
        ('science', '运动基础学科', '生理学、生物力学、心理学、营养学', 3, true),
        ('medicine', '运动医学与康复', '损伤预防、康复、疲劳、过度训练', 4, true)
    """)

    # 创建触发器函数：自动更新title_vector和abstract_vector
    op.execute("""
        CREATE OR REPLACE FUNCTION arxiv_update_vectors()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.title_vector := to_tsvector('english', COALESCE(NEW.title, ''));
            NEW.abstract_vector := to_tsvector('english', COALESCE(NEW.abstract, ''));
            NEW.updated_at := NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # 创建触发器
    op.execute("""
        CREATE TRIGGER arxiv_vectors_update
            BEFORE INSERT OR UPDATE OF title, abstract
            ON arxiv_articles
            FOR EACH ROW
            EXECUTE FUNCTION arxiv_update_vectors();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS arxiv_vectors_update ON arxiv_articles")
    op.execute("DROP FUNCTION IF EXISTS arxiv_update_vectors()")
    op.drop_table('arxiv_category_config')
    op.drop_table('arxiv_crawl_log')
    op.drop_index('idx_arxiv_categories_gin', table_name='arxiv_articles')
    op.drop_index('idx_arxiv_source', table_name='arxiv_articles')
    op.drop_index('idx_arxiv_abstract_fts', table_name='arxiv_articles')
    op.drop_index('idx_arxiv_title_fts', table_name='arxiv_articles')
    op.drop_index('idx_arxiv_submitted_date', table_name='arxiv_articles')
    op.drop_index('idx_arxiv_sport_category', table_name='arxiv_articles')
    op.drop_index('idx_arxiv_id', table_name='arxiv_articles')
    op.drop_table('arxiv_articles')
