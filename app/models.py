from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ChapterProgress(Base):
    __tablename__ = "chapter_progress"
    __table_args__ = (UniqueConstraint("member", "chapter", name="uq_member_chapter"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    member: Mapped[str] = mapped_column(String(50), index=True)
    chapter: Mapped[int] = mapped_column(Integer)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChapterNote(Base):
    __tablename__ = "chapter_note"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    member: Mapped[str] = mapped_column(String(50), index=True)
    chapter: Mapped[int] = mapped_column(Integer, index=True)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Activity(Base):
    __tablename__ = "activity_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    member: Mapped[str] = mapped_column(String(50), index=True)
    chapter: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(20))  # complete | note
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
