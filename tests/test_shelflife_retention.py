import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.database import Base
from backend.database.models import Movie, ProtectedMedia, ReclaimCandidate
from backend.enums import MediaType, SeerrRequestStatus
from backend.models.services.seerr import SeerrRequest, SeerrRequestedSeason
from backend.shelflife import engine, routes
from backend.shelflife.models import RetentionConfig, RetentionEntry, RetentionEvent
from backend.shelflife.policy import utc

NOW = datetime(2026, 11, 17, tzinfo=UTC)


@asynccontextmanager
async def database(monkeypatch):
    connection = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(connection.sync_engine, "connect")
    def foreign_keys(db, _):
        db.execute("PRAGMA foreign_keys=ON")

    async with connection.begin() as db:
        await db.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(connection, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(engine, "async_db", factory)
    monkeypatch.setattr(routes, "async_db", factory)
    monkeypatch.setattr(engine, "candidate_workflow_lock", asyncio.Lock())
    monkeypatch.setattr(
        routes, "candidate_workflow_lock", engine.candidate_workflow_lock
    )
    try:
        yield factory
    finally:
        await connection.dispose()


def request(id=1, *, created=NOW, kind=MediaType.MOVIE, seasons=()):
    return SeerrRequest(
        id=id,
        status=SeerrRequestStatus.APPROVED,
        media_id=10,
        media_type=kind,
        tmdb_id=603,
        created_at=created,
        requested_by_id=2,
        is_4k=False,
        requested_seasons=tuple(SeerrRequestedSeason(s, created) for s in seasons),
    )


class Library:
    def __init__(self, *, ready=True):
        self.ready = ready
        self.requests = AsyncMock(return_value=(1, [request()]))
        self.favorites = AsyncMock(return_value=set())
        self.publish = AsyncMock()
        self.publish_series = AsyncMock()
        self.collections = AsyncMock()
        self.delete = AsyncMock(
            return_value=SimpleNamespace(succeeded=1, failed=0, deferrals={})
        )

    async def resolve(self, db, entry, now):
        if entry.kind == "movie":
            movie = await db.scalar(select(Movie).where(Movie.tmdb_id == entry.tmdb_id))
            if movie is None:
                movie = Movie(title="The Matrix", year=1999, tmdb_id=entry.tmdb_id)
                db.add(movie)
                await db.flush()
            entry.movie_id, entry.title = movie.id, movie.title
        entry.jellyfin_ids = ["a" * 32]
        return self.ready


async def enable(factory, *, preview=True, paused=False):
    async with factory() as db:
        db.add(RetentionConfig(enabled_at=NOW, preview=preview, paused=paused))
        await db.commit()


def test_clock_starts_on_availability_and_survives_rescan_restart(monkeypatch):
    async def run():
        async with database(monkeypatch) as factory:
            await enable(factory)
            library = Library(ready=False)
            await engine.cycle(library, now=NOW)
            async with factory() as db:
                entry = await db.scalar(select(RetentionEntry))
                assert entry.expires_at is None
                assert (await db.get(ProtectedMedia, entry.protection_id)).permanent
            library.ready = True
            available = NOW + timedelta(days=5)
            await engine.cycle(library, now=available)
            await engine.cycle(Library(), now=available + timedelta(days=20))
            async with factory() as db:
                entry = await db.scalar(select(RetentionEntry))
                assert utc(entry.expires_at) == available + timedelta(days=60)
                assert entry.request_ids == ["1:1"]
            library.publish.assert_not_awaited()
            library.delete.assert_not_awaited()

    asyncio.run(run())


def test_old_requests_and_unidentified_tv_seasons_never_enroll(monkeypatch):
    async def run():
        async with database(monkeypatch) as factory, factory() as db:
            await engine.enroll(
                db,
                1,
                [
                    request(created=NOW - timedelta(seconds=1)),
                    request(kind=MediaType.SERIES),
                ],
                NOW,
                NOW,
            )
            assert await db.scalar(select(RetentionEntry)) is None
            await engine.enroll(
                db, 1, [request(kind=MediaType.SERIES, seasons=(2, 3))], NOW, NOW
            )
            assert {
                e.season_number
                for e in (await db.scalars(select(RetentionEntry))).all()
            } == {2, 3}

    asyncio.run(run())


def test_any_keep_is_monotonic_and_unfavorite_does_not_reverse_it(monkeypatch):
    async def run():
        async with database(monkeypatch) as factory:
            await enable(factory)
            library = Library()
            await engine.cycle(library, now=NOW)
            async with factory() as db:
                entry = await db.scalar(select(RetentionEntry))
                await engine.keep(db, entry, 365, actor="different user", now=NOW)
                await engine.keep(db, entry, 60, actor="requester", now=NOW)
                assert utc(entry.expires_at) == NOW + timedelta(days=365)
                await db.commit()
            library.favorites.return_value = {("movie", 603, -1)}
            await engine.cycle(library, now=NOW + timedelta(days=1))
            library.favorites.return_value = set()
            await engine.cycle(library, now=NOW + timedelta(days=500))
            async with factory() as db:
                entry = await db.scalar(select(RetentionEntry))
                assert entry.permanent and entry.expires_at is None
                assert (await db.get(ProtectedMedia, entry.protection_id)).permanent
            library.delete.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize(
    "preview,paused,ready,failure,deletes",
    [
        (True, False, True, None, False),
        (False, True, True, None, False),
        (False, False, False, None, False),
        (False, False, True, "favorites", False),
        (False, False, True, "publish", False),
        (False, False, True, "collections", False),
        (False, False, True, None, True),
    ],
)
def test_due_cleanup_requires_live_verified_unpaused_media(
    monkeypatch, preview, paused, ready, failure, deletes
):
    async def run():
        async with database(monkeypatch) as factory:
            await enable(factory, preview=preview, paused=paused)
            library = Library()
            await engine.cycle(library, now=NOW)
            library.ready = ready
            if failure:
                getattr(library, failure).side_effect = ConnectionError("offline")
            await engine.cycle(library, now=NOW + timedelta(days=61))
            assert bool(library.delete.await_count) is deletes
            async with factory() as db:
                entry = await db.scalar(select(RetentionEntry))
                assert bool(entry.deleted_at) is deletes
                if deletes:
                    assert await db.scalar(
                        select(RetentionEvent).where(RetentionEvent.action == "deleted")
                    )

    asyncio.run(run())


def test_last_second_favorite_prevents_deletion_and_survives_notice_failure(
    monkeypatch,
):
    async def run():
        async with database(monkeypatch) as factory:
            await enable(factory, preview=False)
            library = Library()
            await engine.cycle(library, now=NOW)
            library.favorites.side_effect = [set(), {("movie", 603, -1)}]
            await engine.cycle(library, now=NOW + timedelta(days=61))
            library.delete.assert_not_awaited()
            async with factory() as db:
                assert (await db.scalar(select(RetentionEntry))).permanent

    asyncio.run(run())


def test_rerequest_preserves_longer_preference_and_has_fresh_window(monkeypatch):
    async def run():
        async with database(monkeypatch) as factory:
            await enable(factory, preview=False)
            library = Library()
            await engine.cycle(library, now=NOW)
            await engine.cycle(library, now=NOW + timedelta(days=61))
            async with factory() as db:
                entry = await db.scalar(select(RetentionEntry))
                entry.days = 180  # Preference durably saved by the request bridge.
                await db.commit()
            library.requests.return_value = (
                1,
                [request(), request(2, created=NOW + timedelta(days=70))],
            )
            await engine.cycle(library, now=NOW + timedelta(days=70))
            async with factory() as db:
                entry = await db.scalar(select(RetentionEntry))
                assert entry.deleted_at is None
                assert utc(entry.expires_at) == NOW + timedelta(days=250)
                assert len(entry.request_ids) == 2

    asyncio.run(run())


def test_whole_show_keep_covers_existing_and_future_requested_seasons(monkeypatch):
    async def run():
        async with database(monkeypatch) as factory, factory() as db:
            await engine.enroll(
                db, 1, [request(kind=MediaType.SERIES, seasons=(1,))], NOW, NOW
            )
            umbrella = await engine.entry_for(db, "series", 603)
            await engine.keep(db, umbrella, None, actor="Roku", now=NOW)
            await engine.enroll(
                db, 1, [request(2, kind=MediaType.SERIES, seasons=(2,))], NOW, NOW
            )
            assert all(
                e.permanent for e in (await db.scalars(select(RetentionEntry))).all()
            )

    asyncio.run(run())


def test_timed_whole_show_keep_expires_and_does_not_apply_to_later_requests(
    monkeypatch,
):
    async def run():
        async with database(monkeypatch) as factory, factory() as db:
            umbrella = await engine.entry_for(db, "series", 603)
            await engine.keep(db, umbrella, 180, actor="browser", now=NOW)
            assert utc(umbrella.expires_at) == NOW + timedelta(days=180)
            await engine.enroll(
                db,
                1,
                [request(kind=MediaType.SERIES, seasons=(1,))],
                NOW,
                NOW + timedelta(days=200),
            )
            entry = await engine.entry_for(db, "series", 603, 1)
            assert entry.days == 60

    asyncio.run(run())


def test_other_cleanup_routes_cannot_bypass_new_favorite_without_local_ids(monkeypatch):
    async def run():
        async with database(monkeypatch) as factory, factory() as db:
            db.add(RetentionConfig(enabled_at=NOW, preview=False))
            movie = Movie(title="The Matrix", tmdb_id=603, year=1999)
            db.add(movie)
            await db.flush()
            candidate = ReclaimCandidate(
                media_type=MediaType.MOVIE,
                movie_id=movie.id,
                matched_rule_ids=[],
                matched_criteria={},
                reason="Another rule",
            )
            db.add(candidate)
            await db.commit()
            library = Library()
            library.favorites.return_value = {("movie", 603, -1)}
            monkeypatch.setattr(engine, "Library", lambda: library)
            assert await engine.deletion_gate(db, [candidate]) == []
            library.favorites.return_value = set()
            assert await engine.deletion_gate(db, [candidate]) == []

    asyncio.run(run())


def test_keep_queued_during_scan_commits_before_due_deletion(monkeypatch):
    async def run():
        async with database(monkeypatch) as factory:
            await enable(factory, preview=False)
            library = Library()
            await engine.cycle(library, now=NOW)
            publishing, release = asyncio.Event(), asyncio.Event()

            async def publish(*args):
                publishing.set()
                await release.wait()

            library.publish.side_effect = publish
            scan = asyncio.create_task(
                engine.cycle(library, now=NOW + timedelta(days=61))
            )
            await publishing.wait()

            async def keep_from_browser():
                async with engine.candidate_workflow_lock, factory() as db:
                    entry = await db.scalar(select(RetentionEntry))
                    await engine.keep(
                        db, entry, None, actor="friend", now=NOW + timedelta(days=61)
                    )
                    await db.commit()

            keep = asyncio.create_task(keep_from_browser())
            await asyncio.sleep(0)
            release.set()
            await asyncio.gather(scan, keep)
            library.delete.assert_not_awaited()

    asyncio.run(run())


def test_partial_cleanup_does_not_claim_the_title_was_fully_removed(monkeypatch):
    async def run():
        async with database(monkeypatch) as factory:
            await enable(factory, preview=False)
            library = Library()
            await engine.cycle(library, now=NOW)
            library.delete.return_value = SimpleNamespace(
                succeeded=1, failed=1, deferrals={}
            )
            await engine.cycle(library, now=NOW + timedelta(days=61))
            async with factory() as db:
                entry = await db.scalar(select(RetentionEntry))
                assert entry.deleted_at is None and entry.last_error

    asyncio.run(run())
