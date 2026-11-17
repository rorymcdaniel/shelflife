"""Durable request retention, independent of cleanup candidate rescans."""
from alembic import op
import sqlalchemy as sa

revision = "sl0001"
down_revision = "a3c8e1f5b920"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("shelflife_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("enabled_at", sa.DateTime()),
        sa.Column("paused", sa.Boolean(), nullable=False),
        sa.Column("preview", sa.Boolean(), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("seerr_public_url", sa.String(1024), nullable=False),
        sa.Column("jellyfin_public_url", sa.String(1024), nullable=False),
        sa.Column("last_checked_at", sa.DateTime()),
        sa.Column("last_error", sa.Text()))
    op.create_table("shelflife_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("tmdb_id", sa.Integer(), nullable=False),
        sa.Column("season_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("days", sa.Integer(), nullable=False),
        sa.Column("permanent", sa.Boolean(), nullable=False),
        sa.Column("requested_at", sa.DateTime()),
        sa.Column("request_ids", sa.JSON(), nullable=False),
        sa.Column("available_at", sa.DateTime()),
        sa.Column("expires_at", sa.DateTime()),
        sa.Column("deleted_at", sa.DateTime()),
        sa.Column("jellyfin_ids", sa.JSON(), nullable=False),
        sa.Column("movie_id", sa.Integer(), sa.ForeignKey("movies.id", ondelete="SET NULL")),
        sa.Column("series_id", sa.Integer(), sa.ForeignKey("series.id", ondelete="SET NULL")),
        sa.Column("season_id", sa.Integer(), sa.ForeignKey("seasons.id", ondelete="SET NULL")),
        sa.Column("candidate_id", sa.Integer(), sa.ForeignKey("reclaim_candidates.id", ondelete="SET NULL")),
        sa.Column("protection_id", sa.Integer(), sa.ForeignKey("protected_media.id", ondelete="SET NULL")),
        sa.Column("last_error", sa.Text()),
        sa.UniqueConstraint("kind", "tmdb_id", "season_number", name="uq_shelflife_scope"))
    op.create_table("shelflife_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entry_id", sa.Integer(), sa.ForeignKey("shelflife_entries.id"), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("actor", sa.String(160), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("deadline", sa.DateTime()))
    op.create_index("ix_shelflife_events_entry_id", "shelflife_events", ["entry_id"])


def downgrade():
    op.drop_table("shelflife_events")
    op.drop_table("shelflife_entries")
    op.drop_table("shelflife_config")
