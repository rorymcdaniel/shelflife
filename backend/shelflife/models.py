from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class RetentionConfig(Base):
    __tablename__ = "shelflife_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    preview: Mapped[bool] = mapped_column(Boolean, default=True)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    seerr_public_url: Mapped[str] = mapped_column(String(1024), default="")
    jellyfin_public_url: Mapped[str] = mapped_column(String(1024), default="")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)


class RetentionEntry(Base):
    __tablename__ = "shelflife_entries"
    __table_args__ = (
        UniqueConstraint("kind", "tmdb_id", "season_number", name="uq_shelflife_scope"),
    )

    kind: Mapped[str] = mapped_column(String(16))
    tmdb_id: Mapped[int] = mapped_column(Integer)
    season_number: Mapped[int] = mapped_column(Integer, default=-1)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, init=False)
    title: Mapped[str] = mapped_column(String(512), default="Awaiting media")
    days: Mapped[int] = mapped_column(Integer, default=60)
    permanent: Mapped[bool] = mapped_column(Boolean, default=False)
    requested_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    request_ids: Mapped[list[str]] = mapped_column(JSON, default_factory=list)
    available_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    jellyfin_ids: Mapped[list[str]] = mapped_column(JSON, default_factory=list)
    movie_id: Mapped[int | None] = mapped_column(
        ForeignKey("movies.id", ondelete="SET NULL"), default=None
    )
    series_id: Mapped[int | None] = mapped_column(
        ForeignKey("series.id", ondelete="SET NULL"), default=None
    )
    season_id: Mapped[int | None] = mapped_column(
        ForeignKey("seasons.id", ondelete="SET NULL"), default=None
    )
    candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("reclaim_candidates.id", ondelete="SET NULL"), default=None
    )
    protection_id: Mapped[int | None] = mapped_column(
        ForeignKey("protected_media.id", ondelete="SET NULL"), default=None
    )
    last_error: Mapped[str | None] = mapped_column(Text, default=None)


class RetentionEvent(Base):
    __tablename__ = "shelflife_events"

    entry_id: Mapped[int] = mapped_column(
        ForeignKey("shelflife_entries.id"), index=True
    )
    action: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(160))
    occurred_at: Mapped[datetime] = mapped_column(DateTime)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, init=False)
    deadline: Mapped[datetime | None] = mapped_column(DateTime, default=None)
