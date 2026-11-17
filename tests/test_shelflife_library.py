import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.shelflife import library
from backend.shelflife.models import RetentionEntry


def test_favorite_season_uses_api_key_compatible_parent_lookup(monkeypatch):
    async def run():
        async def get(path, params=None, **kwargs):
            if path == "Users":
                return [{"Id": "user", "Policy": {}}]
            if path == "Items" and params.get("Ids"):
                return {
                    "Items": [{"Id": "parent", "ProviderIds": {"Tmdb": "603"}}],
                    "TotalRecordCount": 1,
                }
            if path == "Items":
                return {
                    "Items": [
                        {
                            "Id": "season",
                            "Type": "Season",
                            "SeriesId": "parent",
                            "IndexNumber": 2,
                        }
                    ],
                    "TotalRecordCount": 1,
                }
            raise AssertionError(
                "Unscoped /Items/id cannot be used with a server API key"
            )

        monkeypatch.setattr(
            library, "jellyfin", lambda: SimpleNamespace(_make_request=get)
        )
        assert await library.Library().favorites() == {("series", 603, 2)}

    asyncio.run(run())


def test_notice_update_reads_full_metadata_in_admin_context_and_preserves_fields(
    monkeypatch,
):
    async def run():
        item = {
            "Id": "movie",
            "Overview": "Original synopsis",
            "LockedFields": ["Name"],
            "Genres": ["Drama"],
            "ProviderIds": {"Tmdb": "603"},
        }

        async def get(path, params=None, **kwargs):
            if path == "Users":
                return [{"Id": "admin", "Policy": {"IsAdministrator": True}}]
            assert path == "Items/movie" and params["userId"] == "admin"
            return dict(item)

        post = AsyncMock(return_value=SimpleNamespace(raise_for_status=lambda: None))
        monkeypatch.setattr(
            library,
            "jellyfin",
            lambda: SimpleNamespace(
                _make_request=get,
                service_url="http://jellyfin",
                session=SimpleNamespace(post=post),
            ),
        )
        entry = RetentionEntry(kind="movie", tmdb_id=603, jellyfin_ids=["movie"])
        await library.Library().publish(
            entry, "Library retention: Kept permanently.\n\n"
        )
        sent = post.call_args.kwargs["json"]
        assert (
            sent["LockedFields"] == item["LockedFields"]
            and sent["Genres"] == item["Genres"]
            and sent["ProviderIds"] == item["ProviderIds"]
        )
        assert sent["Overview"].endswith("Original synopsis")

    asyncio.run(run())
