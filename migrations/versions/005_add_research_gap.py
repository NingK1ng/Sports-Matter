"""add research gap agent module

Revision ID: 005_research_gap
Revises: 004_update_literature_fts
Create Date: 2025-01-04

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '005_research_gap'
down_revision = '004_update_literature_fts'
branch_labels = None
depends_on = None


def upgrade():
    """创建研究空白Agent模块的表和索引"""
    
    # 创建wiw_results表
    op.create_table(
        'wiw_results',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True, comment='主键ID'),
        
        # 输入信息
        sa.Column('input_pmid', sa.String(length=20), nullable=False, comment='输入文献PMID'),
        sa.Column('input_doi', sa.String(length=200), nullable=True, comment='输入文献DOI（如果通过DOI输入）'),
        sa.Column('input_title', sa.String(length=500), nullable=True, comment='输入文献标题（如果通过标题输入）'),
        sa.Column('input_fingerprint', sa.String(length=32), nullable=False, comment='输入指纹（MD5，用于去重和缓存）'),
        
        # 生成参数
        sa.Column('top_k', sa.Integer(), nullable=False, server_default=sa.text('10'), comment='召回文献数量（5/10/15）'),
        sa.Column('strategy_version', sa.String(length=10), nullable=False, server_default=sa.text("'v1'"), comment='召回策略版本'),
        sa.Column('template_version', sa.String(length=10), nullable=False, server_default=sa.text("'v1'"), comment='Prompt模板版本'),
        sa.Column('model_version', sa.String(length=50), nullable=False, server_default=sa.text("'deepseek-v4-flash'"), comment='LLM模型版本'),
        sa.Column('language', sa.String(length=5), nullable=False, server_default=sa.text("'zh'"), comment='生成语言（zh/en）'),
        
        # WiW卡片内容（JSONB格式）
        sa.Column('card_content', postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment='WiW卡片内容：{focus, next_questions, conflicts, gaps}'),
        
        # 召回文献列表
        sa.Column('references', postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment='召回文献列表（PMID+标题+DOI+相似度）'),
        sa.Column('references_hash', sa.String(length=32), nullable=False, comment='召回集哈希（用于缓存键）'),
        
        # 顶刊推荐
        sa.Column('top_journal_recommendations', postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment='顶刊推荐列表（来自模块2的13本期刊）'),
        
        # 元数据
        sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), nullable=False, comment='元数据：{recall_mode, dedup_count, elapsed_ms, degradation}'),
        
        # 时间戳
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'), comment='创建时间'),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'), comment='更新时间'),
        
        sa.PrimaryKeyConstraint('id'),
        comment='WiW生成结果表'
    )
    
    # 创建索引
    op.create_index('idx_wiw_input_fingerprint', 'wiw_results', ['input_fingerprint'])
    op.create_index('idx_wiw_created_at', 'wiw_results', ['created_at'])
    op.create_index('idx_wiw_input_pmid', 'wiw_results', ['input_pmid'])
    
    print("✅ 研究空白Agent模块表创建完成")


def downgrade():
    """回滚：删除研究空白Agent模块的表"""
    op.drop_index('idx_wiw_input_pmid', table_name='wiw_results')
    op.drop_index('idx_wiw_created_at', table_name='wiw_results')
    op.drop_index('idx_wiw_input_fingerprint', table_name='wiw_results')
    op.drop_table('wiw_results')
    
    print("✅ 研究空白Agent模块表已删除")
