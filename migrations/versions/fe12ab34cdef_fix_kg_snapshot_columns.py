"""fix_kg_snapshot_columns

Revision ID: fe12ab34cdef
Revises: ed24a28ab7e4
Create Date: 2025-11-08 17:05:00

修复知识图谱快照表字段：
1) community_snapshots.rep_mesh → representative_terms
2) community_snapshots.activity 从 Integer → DOUBLE PRECISION
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'fe12ab34cdef'
down_revision: Union[str, None] = 'ed24a28ab7e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) 重命名列 rep_mesh → representative_terms（若存在）
    conn = op.get_bind()
    insp = sa.inspect(conn)
    cols = [c['name'] for c in insp.get_columns('community_snapshots')]
    if 'rep_mesh' in cols and 'representative_terms' not in cols:
        op.alter_column('community_snapshots', 'rep_mesh', new_column_name='representative_terms', existing_type=postgresql.JSONB)

    # 2) activity 改为 DOUBLE PRECISION
    op.alter_column(
        'community_snapshots',
        'activity',
        type_=sa.Float(precision=24),
        postgresql_using='activity::double precision',
        existing_nullable=False,
    )


def downgrade() -> None:
    # 回滚 activity 类型
    op.alter_column(
        'community_snapshots',
        'activity',
        type_=sa.Integer(),
        postgresql_using='round(activity)',
        existing_nullable=False,
    )

    # 回滚列名 representative_terms → rep_mesh（若适用）
    conn = op.get_bind()
    insp = sa.inspect(conn)
    cols = [c['name'] for c in insp.get_columns('community_snapshots')]
    if 'representative_terms' in cols and 'rep_mesh' not in cols:
        op.alter_column('community_snapshots', 'representative_terms', new_column_name='rep_mesh', existing_type=postgresql.JSONB)

