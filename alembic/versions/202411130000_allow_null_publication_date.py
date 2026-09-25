"""allow NULL publication_date in literature

Revision ID: 202411130000
Revises: 202411080000
Create Date: 2025-11-13 00:00:00.000000

Rationale:
- Prevent default 'today' pollution when PubMed date parsing fails
- Allow NULL to indicate parse failure, enabling targeted backfill
- Maintain data integrity while improving debugging visibility
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '202411130000'
down_revision: Union[str, None] = '202411070001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Allow publication_date to be NULL in literature table."""
    # ALTER COLUMN to allow NULL
    op.alter_column(
        'literature',
        'publication_date',
        existing_type=sa.Date(),
        nullable=True,
        comment='发表日期（解析失败时为NULL）'
    )
    
    print("✅ Migration complete: publication_date can now be NULL")
    print("   Next: Run backfill script to fix misdated records")


def downgrade() -> None:
    """Revert to NOT NULL constraint (requires data cleanup first)."""
    # NOTE: This will FAIL if any NULL values exist
    # Must backfill all NULL values before downgrade
    op.alter_column(
        'literature',
        'publication_date',
        existing_type=sa.Date(),
        nullable=False,
        comment='发表日期'
    )
