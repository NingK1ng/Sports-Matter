"""update literature fts: add title/abstract vectors, unaccent, trigger, indexes

Revision ID: 004_update_literature_fts
Revises: 003_add_pubmed_fields
Create Date: 2025-11-05 04:05:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '004_update_literature_fts'
down_revision: Union[str, None] = '003_pubmed_enrichment'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ensure unaccent extension
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")

    # Add TSVECTOR columns
    op.add_column('literature', sa.Column('title_vector', postgresql.TSVECTOR(), nullable=True))
    op.add_column('literature', sa.Column('abstract_vector', postgresql.TSVECTOR(), nullable=True))

    # Create function to update vectors
    op.execute(
        """
        CREATE OR REPLACE FUNCTION update_literature_search_vectors() RETURNS TRIGGER AS $$
        BEGIN
            NEW.title_vector := to_tsvector('english', unaccent(COALESCE(NEW.title, '')));
            NEW.abstract_vector := to_tsvector('english', unaccent(COALESCE(NEW.abstract, '')));
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    # Create trigger
    op.execute(
        """
        DROP TRIGGER IF EXISTS trigger_update_lit_vectors ON literature;
        CREATE TRIGGER trigger_update_lit_vectors
        BEFORE INSERT OR UPDATE ON literature
        FOR EACH ROW EXECUTE FUNCTION update_literature_search_vectors();
        """
    )

    # Create indexes
    op.execute("CREATE INDEX IF NOT EXISTS idx_lit_title_fts ON literature USING GIN(title_vector)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_lit_abstract_fts ON literature USING GIN(abstract_vector)")

    # Backfill existing rows
    op.execute(
        """
        UPDATE literature
        SET
            title_vector = to_tsvector('english', unaccent(COALESCE(title, ''))),
            abstract_vector = to_tsvector('english', unaccent(COALESCE(abstract, '')))
        """
    )


def downgrade() -> None:
    # Drop indexes
    op.execute("DROP INDEX IF EXISTS idx_lit_title_fts")
    op.execute("DROP INDEX IF EXISTS idx_lit_abstract_fts")

    # Drop trigger and function
    op.execute("DROP TRIGGER IF EXISTS trigger_update_lit_vectors ON literature")
    op.execute("DROP FUNCTION IF EXISTS update_literature_search_vectors")

    # Drop columns
    op.drop_column('literature', 'abstract_vector')
    op.drop_column('literature', 'title_vector')


