"""add_graph_snapshot_tables

Revision ID: de4a3e2e5765
Revises: c8f6b27e3a3f
Create Date: 2025-11-08 00:41:20.629328

创建知识图谱快照表：
1. graph_snapshots - 图谱快照元数据
2. community_snapshots - 社区详情快照
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'de4a3e2e5765'
down_revision: Union[str, None] = 'c8f6b27e3a3f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建快照表"""
    
    # 1. 创建graph_snapshots表
    op.create_table(
        'graph_snapshots',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False, comment='主键ID'),
        sa.Column('snapshot_id', sa.String(64), nullable=False, comment='快照唯一标识'),
        sa.Column('source', sa.String(50), nullable=False, comment='数据源: literature|sports_journals|cns'),
        sa.Column('window', sa.String(10), nullable=False, comment='时间窗口: 1d|7d|30d|180d'),
        sa.Column('as_of', sa.Date(), nullable=False, comment='快照日期（UTC）'),
        sa.Column('meta', postgresql.JSONB, nullable=False, comment='图谱元数据'),
        sa.Column('communities_summary', postgresql.JSONB, nullable=False, comment='社区摘要列表'),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('NOW()'), nullable=False, comment='创建时间'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('snapshot_id', name='uq_graph_snapshots_snapshot_id'),
        sa.UniqueConstraint('source', 'window', 'as_of', name='uq_graph_snapshots_source_window_date'),
        comment='图谱快照元数据表'
    )
    
    # 索引
    op.create_index('idx_graph_snapshots_snapshot_id', 'graph_snapshots', ['snapshot_id'])
    op.create_index('idx_graph_snapshots_source_window', 'graph_snapshots', ['source', 'window'])
    op.create_index('idx_graph_snapshots_as_of', 'graph_snapshots', ['as_of'])
    
    # 2. 创建community_snapshots表
    op.create_table(
        'community_snapshots',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False, comment='主键ID'),
        sa.Column('snapshot_id', sa.String(64), nullable=False, comment='关联的图谱快照ID'),
        sa.Column('community_id', sa.String(50), nullable=False, comment='社区ID'),
        sa.Column('size', sa.Integer(), nullable=False, comment='社区文献数量'),
        sa.Column('activity', sa.Integer(), nullable=False, comment='活跃度'),
        sa.Column('rep_mesh', postgresql.JSONB, nullable=False, comment='代表性MeSH术语'),
        sa.Column('top_papers', postgresql.JSONB, nullable=False, comment='Top10文献'),
        sa.Column('summary', sa.String(1000), nullable=True, comment='社区摘要（LLM生成）'),
        sa.Column('graph_data', postgresql.JSONB, nullable=True, comment='社区子图数据'),
        sa.Column('metrics', postgresql.JSONB, nullable=False, comment='社区指标'),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('NOW()'), nullable=False, comment='创建时间'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('snapshot_id', 'community_id', name='uq_community_snapshots_snapshot_community'),
        comment='社区详情快照表'
    )
    
    # 索引
    op.create_index('idx_community_snapshots_snapshot', 'community_snapshots', ['snapshot_id'])
    
    print("✅ Graph snapshot tables created successfully")


def downgrade() -> None:
    """删除快照表"""
    
    op.drop_table('community_snapshots')
    op.drop_table('graph_snapshots')
    
    print("✅ Graph snapshot tables dropped")
