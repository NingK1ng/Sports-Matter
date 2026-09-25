"""
Daily check-in models.

Stores per-user streak/unlock state and daily check-in events for calendar display.
"""

from sqlalchemy import Column, Date, ForeignKey, Integer, TIMESTAMP, UniqueConstraint, text

from models.base import Base


class UserCheckin(Base):
    __tablename__ = "user_checkins"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, comment="用户ID")
    last_checkin_date = Column(Date, nullable=True, comment="最后签到日期（Asia/Shanghai）")
    streak_days = Column(Integer, nullable=False, server_default=text("0"), comment="连续签到天数")
    unlocked_count = Column(Integer, nullable=False, server_default=text("0"), comment="已解锁图标数量（0-30）")
    selected_cursor_id = Column(Integer, nullable=True, comment="当前选择的鼠标图标ID（1-30）")
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))


class UserCheckinEvent(Base):
    __tablename__ = "user_checkin_events"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, comment="用户ID")
    checkin_date = Column(Date, nullable=False, comment="签到日期（Asia/Shanghai）")
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    __table_args__ = (
        UniqueConstraint("user_id", "checkin_date", name="uq_user_checkin_user_date"),
    )

