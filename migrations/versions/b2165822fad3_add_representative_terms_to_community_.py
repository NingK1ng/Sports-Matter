"""add representative_terms to community_snapshots

Revision ID: b2165822fad3
Revises: fe12ab34cdef
Create Date: 2025-11-09 05:05:25.674761

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2165822fad3'
down_revision: Union[str, None] = 'fe12ab34cdef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 检查表和字段是否存在
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    
    # 如果表不存在，跳过
    if 'community_snapshots' not in inspector.get_table_names():
        return
    
    # 检查字段是否已存在
    columns = [col['name'] for col in inspector.get_columns('community_snapshots')]
    
    # 添加缺失的字段
    if 'representative_terms' not in columns:
        op.add_column('community_snapshots', 
            sa.Column('representative_terms', sa.dialects.postgresql.JSONB(), nullable=False, 
                     server_default='[]', comment='代表性关键词（≤10）: [{term, score}]'))
    
    if 'top_papers' not in columns:
        op.add_column('community_snapshots', 
            sa.Column('top_papers', sa.dialects.postgresql.JSONB(), nullable=False, 
                     server_default='[]', comment='Top10文献: [{pmid, title, abstract, score, pub_date}]'))
    
    if 'summary' not in columns:
        op.add_column('community_snapshots', 
            sa.Column('summary', sa.String(1000), nullable=True, comment='社区摘要（LLM生成）'))
    
    if 'graph_data' not in columns:
        op.add_column('community_snapshots', 
            sa.Column('graph_data', sa.dialects.postgresql.JSONB(), nullable=True, 
                     comment='社区子图数据: {nodes: [...], edges: [...]}（可选）'))
    
    if 'metrics' not in columns:
        op.add_column('community_snapshots', 
            sa.Column('metrics', sa.dialects.postgresql.JSONB(), nullable=False, 
                     server_default='{}', comment='社区指标: {modularity, density, coverage, keywords_coverage, detector, degraded}'))


def downgrade() -> None:
    # 检查表是否存在
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    
    if 'community_snapshots' not in inspector.get_table_names():
        return
    
    # 删除添加的字段
    columns = [col['name'] for col in inspector.get_columns('community_snapshots')]
    
    if 'metrics' in columns:
        op.drop_column('community_snapshots', 'metrics')
    if 'graph_data' in columns:
        op.drop_column('community_snapshots', 'graph_data')
    if 'summary' in columns:
        op.drop_column('community_snapshots', 'summary')
    if 'top_papers' in columns:
        op.drop_column('community_snapshots', 'top_papers')
    if 'representative_terms' in columns:
        op.drop_column('community_snapshots', 'representative_terms')
