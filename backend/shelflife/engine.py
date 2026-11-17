"""Durable retention decisions, using Reclaimerr for every actual deletion."""

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.logger import LOG
from backend.core.workflow_locks import candidate_workflow_lock
from backend.database import async_db
from backend.database.models import (
    Movie,
    ProtectedMedia,
    ReclaimCandidate,
    Season,
    Series,
)
from backend.enums import MediaType, SeerrRequestStatus
from backend.shelflife.library import Library
from backend.shelflife.models import RetentionConfig, RetentionEntry, RetentionEvent
from backend.shelflife.policy import extend_deadline, notice, utc, validate_days


async def config(db: AsyncSession) -> RetentionConfig:
    row = await db.get(RetentionConfig, 1)
    if row is None:
        row = RetentionConfig()
        db.add(row)
        await db.flush()
    return row


async def entry_for(
    db: AsyncSession, kind: str, tmdb_id: int, season: int = -1
) -> RetentionEntry:
    if (
        kind not in {"movie", "series"}
        or tmdb_id <= 0
        or season < -1
        or (kind == "movie" and season != -1)
    ):
        raise ValueError("Invalid retention scope")
    row = await db.scalar(
        select(RetentionEntry).where(
            RetentionEntry.kind == kind,
            RetentionEntry.tmdb_id == tmdb_id,
            RetentionEntry.season_number == season,
        )
    )
    if row is None:
        row = RetentionEntry(kind=kind, tmdb_id=tmdb_id, season_number=season)
        db.add(row)
        await db.flush()
    return row


async def event(
    db: AsyncSession, entry: RetentionEntry, action: str, actor: str, now: datetime
) -> None:
    db.add(
        RetentionEvent(
            entry_id=entry.id,
            action=action,
            actor=actor,
            occurred_at=now,
            deadline=entry.expires_at,
        )
    )


async def mirror_protection(db: AsyncSession, entry: RetentionEntry) -> None:
    if not (entry.movie_id or entry.series_id) or entry.deleted_at:
        return
    if entry.kind == "series" and entry.season_number >= 0 and not entry.season_id:
        return
    protection = (
        await db.get(ProtectedMedia, entry.protection_id)
        if entry.protection_id
        else None
    )
    if protection is None:
        protection = ProtectedMedia(
            media_type=MediaType.MOVIE if entry.kind == "movie" else MediaType.SERIES,
            movie_id=entry.movie_id,
            series_id=entry.series_id,
            season_id=entry.season_id,
            source="shelflife",
            reason="Shelflife retention",
        )
        db.add(protection)
        await db.flush()
        entry.protection_id = protection.id
    protection.permanent = entry.permanent or entry.expires_at is None
    protection.expires_at = None if protection.permanent else entry.expires_at


async def keep(
    db: AsyncSession,
    entry: RetentionEntry,
    days: int | None,
    *,
    actor: str,
    now: datetime,
    preference: bool = False,
) -> None:
    validate_days(days)
    if entry.deleted_at:
        raise ValueError(
            "This item has already left the library; request it again in Seerr"
        )
    if entry.kind == "series" and entry.season_number >= 0:
        umbrella = await db.scalar(
            select(RetentionEntry).where(
                RetentionEntry.kind == "series",
                RetentionEntry.tmdb_id == entry.tmdb_id,
                RetentionEntry.season_number == -1,
                RetentionEntry.permanent.is_(True),
            )
        )
        if umbrella:
            days = None
    if entry.permanent:
        return
    if days is None:
        entry.permanent = True
        entry.expires_at = None
    else:
        entry.days = max(entry.days, days)
        if (
            entry.available_at
            or not preference
            and not entry.requested_at
            or (entry.kind == "series" and entry.season_number == -1)
        ):
            entry.expires_at = extend_deadline(
                entry.expires_at,
                days,
                utc(entry.available_at) if preference and entry.available_at else now,
            )
    await mirror_protection(db, entry)
    await event(db, entry, "kept_forever" if days is None else "extended", actor, now)
    # A whole-show keep includes every enrolled season and future requests.
    if entry.kind == "series" and entry.season_number == -1:
        children = (
            await db.scalars(
                select(RetentionEntry).where(
                    RetentionEntry.kind == "series",
                    RetentionEntry.tmdb_id == entry.tmdb_id,
                    RetentionEntry.season_number >= 0,
                    RetentionEntry.deleted_at.is_(None),
                )
            )
        ).all()
        for child in children:
            await keep(db, child, days, actor=actor, now=now, preference=preference)


async def enroll(
    db: AsyncSession, config_id: int, requests, cutoff: datetime, now: datetime
) -> None:
    for request in requests:
        if utc(request.created_at) < utc(cutoff) or request.status not in {
            SeerrRequestStatus.PENDING,
            SeerrRequestStatus.APPROVED,
            SeerrRequestStatus.COMPLETED,
        }:
            continue
        kind = "movie" if request.media_type == MediaType.MOVIE else "series"
        seasons = (
            [-1]
            if kind == "movie"
            else [s.season_number for s in request.requested_seasons]
        )
        # Missing TV season identifiers never broadens to whole-series deletion.
        for season in seasons:
            entry = await entry_for(db, kind, request.tmdb_id, season)
            identity = f"{config_id}:{request.id}"
            if identity in entry.request_ids:
                continue
            if entry.deleted_at:
                if utc(request.created_at) <= utc(entry.deleted_at):
                    continue
                entry.deleted_at = entry.available_at = entry.expires_at = None
                entry.candidate_id = None
                entry.requested_at = request.created_at
                entry.last_error = None
            elif (
                entry.available_at
                and utc(request.created_at) > utc(entry.available_at)
                and not entry.permanent
            ):
                # A new request can follow a manual removal outside Shelflife.
                # Give that request a new availability observation and full window.
                entry.available_at = entry.expires_at = None
            entry.request_ids = [*entry.request_ids, identity]
            entry.requested_at = entry.requested_at or request.created_at
            await event(db, entry, "enrolled", "seerr", now)
            if kind == "series":
                umbrella = await db.scalar(
                    select(RetentionEntry).where(
                        RetentionEntry.kind == kind,
                        RetentionEntry.tmdb_id == request.tmdb_id,
                        RetentionEntry.season_number == -1,
                    )
                )
                if umbrella and (
                    umbrella.permanent
                    or (umbrella.expires_at and utc(umbrella.expires_at) > now)
                ):
                    await keep(
                        db,
                        entry,
                        None if umbrella.permanent else umbrella.days,
                        actor="series keep",
                        now=now,
                        preference=True,
                    )


def matches_favorite(
    entry: RetentionEntry, favorites: set[tuple[str, int, int]]
) -> bool:
    return (entry.kind, entry.tmdb_id, entry.season_number) in favorites or (
        entry.kind,
        entry.tmdb_id,
        -1,
    ) in favorites


async def capture_favorites(
    db: AsyncSession, favorites: set[tuple[str, int, int]], now: datetime
) -> None:
    # Keep the whole-show umbrella even before any of its future seasons exist.
    for kind, tmdb_id, season in favorites:
        entry = await entry_for(db, kind, tmdb_id, season)
        if not entry.deleted_at:
            await keep(db, entry, None, actor="Jellyfin Favorite", now=now)


async def cycle(library: Library | None = None, *, now: datetime | None = None) -> None:
    library = library or Library()
    now = now or datetime.now(UTC)
    async with candidate_workflow_lock:
        async with async_db() as db:
            settings = await config(db)
            if settings.enabled_at is None:
                await db.commit()
                return
            try:
                source_id, requests = await library.requests()
                favorites = await library.favorites()  # No stale-cache fallback.
                await enroll(db, source_id, requests, settings.enabled_at, now)
                await capture_favorites(db, favorites, now)
                await db.commit()
                entries = list(
                    (
                        await db.scalars(
                            select(RetentionEntry).where(
                                RetentionEntry.deleted_at.is_(None)
                            )
                        )
                    ).all()
                )
                due: list[int] = []
                leaving: list[RetentionEntry] = []
                for entry in entries:
                    if (
                        not entry.requested_at
                        and not entry.permanent
                        and not entry.expires_at
                    ):
                        continue
                    try:
                        ready = await library.resolve(db, entry, now)
                        if ready and entry.requested_at and not entry.available_at:
                            entry.available_at = now
                            if not entry.permanent:
                                entry.expires_at = now + timedelta(days=entry.days)
                            await event(db, entry, "available", "system", now)
                        await mirror_protection(db, entry)
                        if (
                            not settings.preview
                            and entry.jellyfin_ids
                            and (entry.requested_at or entry.permanent)
                        ):
                            await library.publish(
                                entry,
                                notice(
                                    permanent=entry.permanent,
                                    deadline=entry.expires_at,
                                    timezone=settings.timezone,
                                    days=entry.days,
                                ),
                            )
                        entry.last_error = (
                            "Media is not fully available; cleanup deferred"
                            if entry.requested_at and not ready and entry.available_at
                            else None
                        )
                        if (
                            entry.expires_at
                            and not entry.permanent
                            and utc(entry.expires_at) <= now + timedelta(days=7)
                        ):
                            leaving.append(entry)
                        if (
                            ready
                            and entry.requested_at
                            and entry.expires_at
                            and not entry.permanent
                            and utc(entry.expires_at) <= now
                            and not settings.preview
                            and not settings.paused
                        ):
                            due.append(entry.id)
                    except Exception as exc:
                        # A metadata/source failure defers this item, never guesses readiness.
                        entry.last_error = (
                            type(exc).__name__
                            + ": media verification or notice update failed"
                        )
                        LOG.warning(
                            f"Shelflife deferred entry {entry.id}: {type(exc).__name__}"
                        )
                if not settings.preview:
                    await library.publish_series(db, entries, settings.timezone)
                    await library.collections(leaving)
                settings.last_checked_at, settings.last_error = now, None
                await db.commit()
            except Exception as exc:
                await db.rollback()
                settings = await config(db)
                settings.last_error = (
                    type(exc).__name__
                    + ": source verification failed; cleanup deferred"
                )
                await db.commit()
                LOG.warning(f"Shelflife cycle deferred: {type(exc).__name__}")
                return
    # Let keeps queued during the scan commit before any deletion is claimed.
    for entry_id in due:
        async with candidate_workflow_lock:
            # Re-read both the ledger and favorites immediately before each operation.
            async with async_db() as db:
                entry = await db.get(RetentionEntry, entry_id)
                settings = await config(db)
                if (
                    entry is None
                    or entry.permanent
                    or entry.deleted_at
                    or not entry.expires_at
                    or utc(entry.expires_at) > now
                    or settings.preview
                    or settings.paused
                    or entry.last_error
                ):
                    continue
                try:
                    fresh = await library.favorites()
                    await capture_favorites(db, fresh, now)
                except Exception:
                    entry.last_error = (
                        "Favorites could not be verified; deletion deferred"
                    )
                    await db.commit()
                    continue
                if entry.permanent:
                    await db.commit()
                    continue
                candidate = (
                    await db.get(ReclaimCandidate, entry.candidate_id)
                    if entry.candidate_id
                    else None
                )
                if candidate is None:
                    candidate = ReclaimCandidate(
                        media_type=MediaType.MOVIE
                        if entry.kind == "movie"
                        else MediaType.SERIES,
                        matched_rule_ids=[],
                        matched_criteria={"shelflife_entry_id": entry.id},
                        reason="Shelflife retention deadline reached",
                        movie_id=entry.movie_id,
                        series_id=entry.series_id,
                        season_id=entry.season_id,
                        approved_for_deletion=True,
                    )
                    db.add(candidate)
                    await db.flush()
                    entry.candidate_id = candidate.id
                candidate_id = candidate.id
                await db.commit()
            result = await library.delete(candidate_id)
            async with async_db() as db:
                entry = await db.get(RetentionEntry, entry_id)
                if entry is None:
                    continue
                if result.succeeded and not result.failed and not result.deferrals:
                    entry.deleted_at = now
                    entry.candidate_id = None
                    await event(db, entry, "deleted", "system", now)
                else:
                    entry.last_error = (
                        "Deletion deferred by Reclaimerr; see Candidates for details"
                    )
                await db.commit()


async def deletion_gate(
    db: AsyncSession, candidates: list[ReclaimCandidate]
) -> list[ReclaimCandidate]:
    """Enforce retention even when another Reclaimerr workflow initiates deletion."""
    settings = await db.get(RetentionConfig, 1)
    if settings is None or settings.enabled_at is None or not candidates:
        return candidates
    now = datetime.now(UTC)
    library = Library()
    # Resolve scope by stable TMDB identity too: a new Favorite may arrive
    # before the next inventory scan has connected its local foreign keys.
    movies = {
        m.id: m.tmdb_id
        for m in (
            await db.scalars(
                select(Movie).where(
                    Movie.id.in_([c.movie_id for c in candidates if c.movie_id])
                )
            )
        ).all()
    }
    shows = {
        s.id: s.tmdb_id
        for s in (
            await db.scalars(
                select(Series).where(
                    Series.id.in_([c.series_id for c in candidates if c.series_id])
                )
            )
        ).all()
    }
    seasons = {
        s.id: s.season_number
        for s in (
            await db.scalars(
                select(Season).where(
                    Season.id.in_([c.season_id for c in candidates if c.season_id])
                )
            )
        ).all()
    }
    try:
        await capture_favorites(db, await library.favorites(), now)
        await db.flush()
    except Exception:
        for candidate in candidates:
            candidate.last_delete_error = "Shelflife could not verify current favorites"
        await db.commit()
        return []
    entries = list(
        (
            await db.scalars(
                select(RetentionEntry).where(RetentionEntry.deleted_at.is_(None))
            )
        ).all()
    )
    allowed = []
    for candidate in candidates:
        affected = [
            e
            for e in entries
            if (
                candidate.movie_id
                and e.kind == "movie"
                and e.tmdb_id == movies.get(candidate.movie_id)
            )
            or (
                candidate.series_id
                and e.kind == "series"
                and e.tmdb_id == shows.get(candidate.series_id)
                and (
                    candidate.season_id is None
                    or e.season_number == -1
                    or seasons.get(candidate.season_id) == e.season_number
                )
            )
        ]
        blocked = affected and (
            settings.preview
            or settings.paused
            or any(
                e.permanent
                or not e.expires_at
                or utc(e.expires_at) > now
                or e.last_error
                for e in affected
            )
        )
        # Never broaden a season lease into whole-series deletion.
        blocked = blocked or (
            affected and candidate.series_id and candidate.season_id is None
        )
        if affected and not blocked:
            try:
                for entry in affected:
                    if entry.requested_at and not await library.resolve(db, entry, now):
                        blocked = True
                        break
            except Exception:
                blocked = True
        if blocked:
            candidate.last_delete_error = "Deferred by Shelflife retention policy"
        else:
            allowed.append(candidate)
    await db.commit()
    return allowed


async def run_loop() -> None:
    while True:
        try:
            await cycle()
        except Exception as exc:
            LOG.warning(f"Shelflife background cycle failed: {type(exc).__name__}")
        await asyncio.sleep(60)
