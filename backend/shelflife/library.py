"""Use Reclaimerr's configured clients; never handle media paths ourselves."""

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.service_manager import service_manager
from backend.database.models import (
    Movie,
    MovieVersion,
    Season,
    Series,
    SeriesArrRef,
    SeriesServiceRef,
)
from backend.enums import Service
from backend.services.jellyfin import JellyfinService
from backend.shelflife.models import RetentionEntry
from backend.shelflife.policy import (
    NOTICE_PREFIX,
    replace_notice,
    season_is_complete,
    utc,
)


def jellyfin() -> JellyfinService:
    client = service_manager.main_media_server
    if not isinstance(client, JellyfinService):
        raise RuntimeError("Select Jellyfin as the main media server in Settings")
    return client


def seerr():
    clients = service_manager.seerr_clients()
    if len(clients) != 1:
        raise RuntimeError("Shelflife requires exactly one enabled Seerr connection")
    return next(iter(clients.items()))


async def read_items(client, **params) -> list[dict]:
    """A failed or incomplete inventory is never interpreted as an empty one."""
    items: list[dict] = []
    expected_total = None
    seen: set[str] = set()
    while True:
        data = await client._make_request(
            "Items",
            params={**params, "StartIndex": len(items), "Limit": 200},
            timeout=30,
        )
        if not isinstance(data, dict) or not isinstance(data.get("Items"), list):
            raise RuntimeError("Jellyfin returned an invalid item inventory")
        total = data.get("TotalRecordCount")
        page = data["Items"]
        if (
            type(total) is not int
            or total < 0
            or not all(isinstance(i, dict) and i.get("Id") for i in page)
        ):
            raise RuntimeError("Jellyfin returned an incomplete item inventory")
        if expected_total is not None and total != expected_total:
            raise RuntimeError("Jellyfin inventory changed during pagination")
        expected_total = total
        for item in page:
            if str(item["Id"]) in seen:
                raise RuntimeError("Jellyfin repeated an inventory page")
            seen.add(str(item["Id"]))
        items.extend(page)
        if len(items) > total:
            raise RuntimeError("Jellyfin returned an inconsistent inventory count")
        if len(items) == total:
            return items
        if not page:
            raise RuntimeError(
                "Jellyfin pagination stopped before the inventory completed"
            )


class Library:
    def __init__(self):
        self._metadata_user: str | None = None

    async def item(self, item_id: str) -> dict:
        rows = await read_items(jellyfin(), Ids=item_id, Fields="ProviderIds")
        if (
            len(rows) != 1
            or str(rows[0]["Id"]).replace("-", "").lower()
            != item_id.replace("-", "").lower()
        ):
            raise RuntimeError("Cannot identify the requested Jellyfin item")
        return rows[0]

    async def requests(self):
        config_id, client = seerr()
        return config_id, await client.get_all_requests()

    async def favorites(self) -> set[tuple[str, int, int]]:
        client = jellyfin()
        users = await client._make_request("Users", timeout=30)
        if not isinstance(users, list) or not users:
            raise RuntimeError("Could not verify Jellyfin users and favorites")
        result: set[tuple[str, int, int]] = set()
        parents: dict[str, dict] = {}
        for user in users:
            if not isinstance(user, dict) or not user.get("Id"):
                raise RuntimeError("Jellyfin returned an invalid user directory")
            if user.get("Policy", {}).get("IsDisabled"):
                continue
            items = await read_items(
                client,
                userId=user["Id"],
                Recursive="true",
                IncludeItemTypes="Movie,Series,Season,Episode",
                IsFavorite="true",
                Fields="ProviderIds",
            )
            for item in items:
                item_type = item.get("Type")
                season = -1
                title = item
                if item_type in {"Season", "Episode"}:
                    series_id = item.get("SeriesId")
                    season = (
                        item.get("IndexNumber")
                        if item_type == "Season"
                        else item.get("ParentIndexNumber")
                    )
                    if not series_id or type(season) is not int:
                        raise RuntimeError(
                            "Cannot identify a favorited season or episode"
                        )
                    if series_id not in parents:
                        parents[series_id] = await self.item(str(series_id))
                    title = parents[series_id]
                tmdb = title.get("ProviderIds", {}).get("Tmdb")
                if str(tmdb).isdigit():
                    result.add(
                        (
                            "movie" if item_type == "Movie" else "series",
                            int(tmdb),
                            season,
                        )
                    )
        return result

    async def resolve(
        self, db: AsyncSession, entry: RetentionEntry, now: datetime
    ) -> bool:
        """Resolve exact movie/season scope, then verify it is actually available."""
        client = jellyfin()
        if entry.kind == "movie":
            movie = await db.scalar(select(Movie).where(Movie.tmdb_id == entry.tmdb_id))
            if movie is None:
                return False
            entry.movie_id, entry.title = movie.id, movie.title
            ids = list(
                (
                    await db.scalars(
                        select(MovieVersion.service_item_id).where(
                            MovieVersion.movie_id == movie.id,
                            MovieVersion.service == Service.JELLYFIN,
                        )
                    )
                ).all()
            )
            if not ids:
                return False
            items = await read_items(
                client, Ids=",".join(set(ids)), Fields="ProviderIds,Path,MediaSources"
            )
            entry.jellyfin_ids = [str(i["Id"]) for i in items]
            return bool(items) and all(
                i.get("Type") == "Movie" and i.get("Path") and not i.get("IsMissing")
                for i in items
            )
        series = await db.scalar(select(Series).where(Series.tmdb_id == entry.tmdb_id))
        if series is None:
            return False
        entry.series_id, entry.title = series.id, series.title
        if entry.season_number < 0:
            # A whole-show entry is a keep-only umbrella, never a deletion target.
            entry.jellyfin_ids = list(
                (
                    await db.scalars(
                        select(SeriesServiceRef.service_id).where(
                            SeriesServiceRef.series_id == series.id,
                            SeriesServiceRef.service == Service.JELLYFIN,
                        )
                    )
                ).all()
            )
            return False
        season = await db.scalar(
            select(Season).where(
                Season.series_id == series.id,
                Season.season_number == entry.season_number,
            )
        )
        if season is None or not season.jellyfin_season_id:
            return False
        entry.season_id = season.id
        entry.title = f"{series.title} · Season {entry.season_number}"
        items = await read_items(
            client, Ids=season.jellyfin_season_id, Fields="ProviderIds"
        )
        entry.jellyfin_ids = [str(i["Id"]) for i in items]
        refs = (
            await db.scalars(
                select(SeriesArrRef).where(SeriesArrRef.series_id == series.id)
            )
        ).all()
        if not items or not refs:
            return False
        expected: set[int] = set()
        for ref in refs:
            sonarr = service_manager.get_sonarr(ref.service_config_id)
            if sonarr is None:
                return False
            show = await sonarr.get_series(ref.arr_series_id)
            episodes = await sonarr.get_episodes(ref.arr_series_id, entry.season_number)
            # A later season confirms an earlier one is finished even when
            # the provider omitted finale markers. Missing files still block.
            later = any(s.season_number > entry.season_number for s in show.seasons)
            if not season_is_complete(
                episodes, now, ended=show.status == "ended" or later
            ):
                return False
            for episode in episodes:
                number = episode.get("episodeNumber")
                if type(number) is not int:
                    return False
                expected.add(number)
        actual = await read_items(
            client,
            ParentId=season.jellyfin_season_id,
            IncludeItemTypes="Episode",
            Recursive="true",
            Fields="Path",
        )
        present: set[int] = set()
        for item in actual:
            first = item.get("IndexNumber")
            last = item.get("IndexNumberEnd", first)
            if (
                item.get("Path")
                and not item.get("IsMissing")
                and type(first) is int
                and type(last) is int
                and 0 <= last - first < 1000
            ):
                present.update(range(first, last + 1))
        return expected.issubset(present)

    async def publish(self, entry: RetentionEntry, prefix: str) -> None:
        await self._publish_ids(entry.jellyfin_ids, prefix)

    async def _publish_ids(self, item_ids: list[str], prefix: str) -> None:
        client = jellyfin()
        if item_ids and self._metadata_user is None:
            users = await client._make_request("Users", timeout=30)
            if not isinstance(users, list):
                raise RuntimeError("Cannot verify a metadata editing context")
            self._metadata_user = next(
                (
                    str(user["Id"])
                    for user in users
                    if user.get("Id")
                    and user.get("Policy", {}).get("IsAdministrator")
                    and not user.get("Policy", {}).get("IsDisabled")
                ),
                None,
            )
            if self._metadata_user is None:
                raise RuntimeError(
                    "No enabled Jellyfin administrator for metadata verification"
                )
        for item_id in item_ids:
            item = await client._make_request(
                f"Items/{item_id}", params={"userId": self._metadata_user}, timeout=30
            )
            if not isinstance(item, dict) or str(item.get("Id", "")).replace(
                "-", ""
            ) != item_id.replace("-", ""):
                raise RuntimeError("Cannot update an unverified Jellyfin item")
            updated = replace_notice(item.get("Overview"), prefix)
            if updated == item.get("Overview"):
                continue
            item["Overview"] = updated
            response = await client.session.post(
                f"{client.service_url}/Items/{item_id}", json=item, timeout=30
            )
            response.raise_for_status()

    async def publish_series(
        self, db: AsyncSession, entries: list[RetentionEntry], timezone: str
    ) -> None:
        """Roku shows the series synopsis first, so show season deadlines there too."""
        groups: dict[int, list[RetentionEntry]] = {}
        for entry in entries:
            if (
                entry.kind == "series"
                and entry.series_id
                and entry.season_number >= 0
                and entry.requested_at
            ):
                groups.setdefault(entry.series_id, []).append(entry)
        for series_id, seasons in groups.items():
            ids = list(
                (
                    await db.scalars(
                        select(SeriesServiceRef.service_id).where(
                            SeriesServiceRef.series_id == series_id,
                            SeriesServiceRef.service == Service.JELLYFIN,
                        )
                    )
                ).all()
            )
            statuses = []
            for entry in sorted(seasons, key=lambda e: e.season_number):
                state = (
                    "kept permanently"
                    if entry.permanent
                    else (
                        "scheduled for deletion "
                        + utc(entry.expires_at)
                        .astimezone(ZoneInfo(timezone))
                        .strftime("%b %d, %Y (%Z)")
                        if entry.expires_at
                        else f"{entry.days} days once fully available"
                    )
                )
                statuses.append(f"Season {entry.season_number}: {state}")
            prefix = (
                NOTICE_PREFIX
                + "; ".join(statuses)
                + ".\nKeep this show forever: mark as Favorite on Roku. For more time, use Keep in your web browser.\n\n"
            )
            await self._publish_ids(ids, prefix)

    async def collections(self, entries: list[RetentionEntry]) -> None:
        client = jellyfin()
        movies = {i for e in entries if e.kind == "movie" for i in e.jellyfin_ids}
        series: set[str] = set()
        for entry in entries:
            if entry.kind != "series":
                continue
            for item_id in entry.jellyfin_ids:
                item = await self.item(item_id)
                if not isinstance(item, dict) or not item.get("SeriesId"):
                    raise RuntimeError("Cannot identify a Leaving Soon season")
                series.add(str(item["SeriesId"]))
        await client.sync_leaving_soon_collections(
            movie_title="Shelflife · Leaving Soon Movies",
            series_title="Shelflife · Leaving Soon Shows",
            movie_item_ids=movies,
            series_item_ids=series,
        )

    async def delete(self, candidate_id: int):
        from backend.tasks.cleanup import delete_specific_candidates

        return await delete_specific_candidates([candidate_id], approved_by="shelflife")
