"""add literature pool tables

Revision ID: 202411070000
Revises: 
Create Date: 2025-11-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '006_literature_pool'
down_revision: Union[str, None] = '005_research_gap'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 创建users表
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False, comment='用户ID'),
        sa.Column('wechat_openid', sa.String(length=64), nullable=False, comment='微信OpenID'),
        sa.Column('wechat_unionid', sa.String(length=64), nullable=True, comment='微信UnionID（可选）'),
        sa.Column('wechat_nickname', sa.String(length=100), nullable=True, comment='微信昵称'),
        sa.Column('wechat_avatar', sa.String(length=500), nullable=True, comment='微信头像URL'),
        sa.Column('login_source', sa.String(length=20), nullable=False, server_default='wechat_open', comment='登录来源：wechat_open/wechat_mp'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true', comment='账号是否激活'),
        sa.Column('last_login_at', sa.TIMESTAMP(timezone=True), nullable=True, comment='最后登录时间（用于活跃度判断）'),
        sa.Column('subscribe_status', sa.Boolean(), nullable=False, server_default='false', comment='是否关注公众号'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'), comment='创建时间'),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'), comment='更新时间'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('wechat_openid'),
    )
    op.create_index('ix_users_wechat_openid', 'users', ['wechat_openid'])
    op.create_index('ix_users_wechat_unionid', 'users', ['wechat_unionid'])
    
    # 创建pool_subscriptions表
    op.create_table(
        'pool_subscriptions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False, comment='订阅ID'),
        sa.Column('user_id', sa.Integer(), nullable=False, comment='用户ID'),
        sa.Column('title', sa.String(length=200), nullable=False, comment='订阅标题（用户自定义）'),
        sa.Column('query_text', sa.String(length=500), nullable=False, comment='原始查询文本（用户输入的关键词）'),
        sa.Column('is_active', sa.Integer(), nullable=False, server_default='1', comment='是否激活（1=激活，0=暂停）'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'), comment='创建时间'),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'), comment='更新时间'),
        sa.CheckConstraint('is_active IN (0, 1)', name='check_subscription_is_active'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_subscription_user_id', 'pool_subscriptions', ['user_id'])
    op.create_index('idx_subscription_created_at', 'pool_subscriptions', ['created_at'])
    
    # 创建pool_articles_stream表
    op.create_table(
        'pool_articles_stream',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False, comment='主键ID'),
        sa.Column('subscription_id', sa.Integer(), nullable=False, comment='订阅ID'),
        sa.Column('literature_id', sa.Integer(), nullable=False, comment='文献ID（关联模块1的literature表）'),
        sa.Column('pmid', sa.String(length=20), nullable=False, comment='PubMed ID'),
        sa.Column('title', sa.String(length=500), nullable=False, comment='文献标题'),
        sa.Column('added_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'), comment='添加时间'),
        sa.ForeignKeyConstraint(['subscription_id'], ['pool_subscriptions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['literature_id'], ['literature.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('subscription_id', 'literature_id', name='uq_subscription_literature'),
    )
    op.create_index('idx_pool_article_subscription_id', 'pool_articles_stream', ['subscription_id'])
    op.create_index('idx_pool_article_pmid', 'pool_articles_stream', ['pmid'])
    op.create_index('idx_pool_article_added_at', 'pool_articles_stream', ['added_at'])
    
    # 创建pool_wiw_cards表
    op.create_table(
        'pool_wiw_cards',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False, comment='主键ID'),
        sa.Column('subscription_id', sa.Integer(), nullable=False, comment='订阅ID'),
        sa.Column('track', sa.String(length=20), nullable=False, comment='轨道类型：stream（模块1）/ journals（模块2）'),
        sa.Column('wiw_result_id', sa.Integer(), nullable=False, comment='WiW结果ID（关联模块3的wiw_results表）'),
        sa.Column('source_pmid', sa.String(length=20), nullable=False, comment='源文献PMID'),
        sa.Column('generated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'), comment='生成时间'),
        sa.Column('expires_at', sa.TIMESTAMP(timezone=True), nullable=False, comment='过期时间（generated_at + 7天）'),
        sa.CheckConstraint("track IN ('stream', 'journals')", name='check_wiw_card_track'),
        sa.ForeignKeyConstraint(['subscription_id'], ['pool_subscriptions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['wiw_result_id'], ['wiw_results.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_wiw_card_subscription_id', 'pool_wiw_cards', ['subscription_id'])
    op.create_index('idx_wiw_card_track', 'pool_wiw_cards', ['track'])
    op.create_index('idx_wiw_card_wiw_result_id', 'pool_wiw_cards', ['wiw_result_id'])
    op.create_index('idx_wiw_card_expires_at', 'pool_wiw_cards', ['expires_at'])
    op.create_index('idx_wiw_card_subscription_track', 'pool_wiw_cards', ['subscription_id', 'track'])
    
    # 创建login_logs表
    op.create_table(
        'login_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False, comment='主键ID'),
        sa.Column('user_id', sa.Integer(), nullable=False, comment='用户ID'),
        sa.Column('ip', sa.String(length=45), nullable=True, comment='登录IP（IPv4/IPv6）'),
        sa.Column('user_agent', sa.String(length=500), nullable=True, comment='User Agent'),
        sa.Column('login_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'), comment='登录时间'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_login_log_user_id', 'login_logs', ['user_id'])
    op.create_index('idx_login_log_login_at', 'login_logs', ['login_at'])


def downgrade() -> None:
    # 删除表（逆序）
    op.drop_index('idx_login_log_login_at', table_name='login_logs')
    op.drop_index('idx_login_log_user_id', table_name='login_logs')
    op.drop_table('login_logs')
    
    op.drop_index('idx_wiw_card_subscription_track', table_name='pool_wiw_cards')
    op.drop_index('idx_wiw_card_expires_at', table_name='pool_wiw_cards')
    op.drop_index('idx_wiw_card_wiw_result_id', table_name='pool_wiw_cards')
    op.drop_index('idx_wiw_card_track', table_name='pool_wiw_cards')
    op.drop_index('idx_wiw_card_subscription_id', table_name='pool_wiw_cards')
    op.drop_table('pool_wiw_cards')
    
    op.drop_index('idx_pool_article_added_at', table_name='pool_articles_stream')
    op.drop_index('idx_pool_article_pmid', table_name='pool_articles_stream')
    op.drop_index('idx_pool_article_subscription_id', table_name='pool_articles_stream')
    op.drop_table('pool_articles_stream')
    
    op.drop_index('idx_subscription_created_at', table_name='pool_subscriptions')
    op.drop_index('idx_subscription_user_id', table_name='pool_subscriptions')
    op.drop_table('pool_subscriptions')
    
    op.drop_index('ix_users_wechat_unionid', table_name='users')
    op.drop_index('ix_users_wechat_openid', table_name='users')
    op.drop_table('users')
