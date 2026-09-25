"""add_knowledge_graph_fields

Revision ID: c8f6b27e3a3f
Revises: 006_literature_pool
Create Date: 2025-11-08 00:37:15.494123

为知识图谱模块添加可选字段：
1) embedding 相关改动默认关闭（通过环境变量 KG_ENABLE_EMBEDDINGS=1 才启用）
2) journal_articles.extra_metadata JSONB 默认启用
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import os


# revision identifiers, used by Alembic.
revision: str = 'c8f6b27e3a3f'
down_revision: Union[str, None] = '006_literature_pool'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """添加知识图谱相关字段（embedding 默认关闭）"""
    enable_embeddings = os.getenv("KG_ENABLE_EMBEDDINGS", "0").lower() in ("1", "true", "yes")

    # 1) 可选：embedding 与向量索引（仅在启用开关时执行）
    if enable_embeddings:
        # 确保pgvector扩展已安装（注意：若实例未安装该扩展，此语句仍会失败）
        op.execute('CREATE EXTENSION IF NOT EXISTS vector')
        
        # literature/journal_articles 添加 embedding 列
        op.execute("""
            ALTER TABLE literature 
            ADD COLUMN IF NOT EXISTS embedding vector(384)
        """)
        op.execute("COMMENT ON COLUMN literature.embedding IS '语义向量(384维,all-MiniLM-L6-v2)'")
        
        op.execute("""
            ALTER TABLE journal_articles 
            ADD COLUMN IF NOT EXISTS embedding vector(384)
        """)
        op.execute("COMMENT ON COLUMN journal_articles.embedding IS '语义向量(384维,all-MiniLM-L6-v2)'")
        
        # HNSW向量索引（PostgreSQL 16 + pgvector 0.7）
        op.execute("""
            CREATE INDEX IF NOT EXISTS idx_literature_embedding 
            ON literature USING hnsw (embedding vector_cosine_ops) 
            WITH (m=16, ef_construction=64)
        """)
        op.execute("""
            CREATE INDEX IF NOT EXISTS idx_journal_articles_embedding 
            ON journal_articles USING hnsw (embedding vector_cosine_ops) 
            WITH (m=16, ef_construction=64)
        """)
        print("✅ Embedding columns & HNSW indexes created (KG_ENABLE_EMBEDDINGS=1)")
    else:
        print("ℹ️ Skip embedding columns & indexes (KG_ENABLE_EMBEDDINGS not enabled)")

    # 2) 默认启用：journal_articles.extra_metadata 及其索引
    with op.batch_alter_table('journal_articles') as batch_op:
        existing_cols = [c['name'] for c in sa.inspect(op.get_bind()).get_columns('journal_articles')]
        if 'extra_metadata' not in existing_cols:
            batch_op.add_column(
                sa.Column('extra_metadata', postgresql.JSONB, nullable=True, comment='额外元数据: mesh_terms, keywords等')
            )
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_journal_articles_extra_metadata 
        ON journal_articles USING gin (extra_metadata jsonb_path_ops)
    """)
    print("✅ journal_articles.extra_metadata: JSONB + GIN index")


def downgrade() -> None:
    """回滚知识图谱字段（根据实际存在性安全回滚）"""
    conn = op.get_bind()
    insp = sa.inspect(conn)

    # 索引
    op.execute('DROP INDEX IF EXISTS idx_literature_embedding')
    op.execute('DROP INDEX IF EXISTS idx_journal_articles_embedding')
    op.execute('DROP INDEX IF EXISTS idx_journal_articles_extra_metadata')

    # 列（存在才删除）
    if 'literature' in insp.get_table_names():
        lit_cols = [c['name'] for c in insp.get_columns('literature')]
        if 'embedding' in lit_cols:
            op.drop_column('literature', 'embedding')
    if 'journal_articles' in insp.get_table_names():
        ja_cols = [c['name'] for c in insp.get_columns('journal_articles')]
        if 'embedding' in ja_cols:
            op.drop_column('journal_articles', 'embedding')
        if 'extra_metadata' in ja_cols:
            op.drop_column('journal_articles', 'extra_metadata')
    print("✅ Knowledge graph fields rolled back (safe)")
