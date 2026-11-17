import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from test_shelflife_retention import NOW, database

from backend.core.auth import get_current_user
from backend.enums import UserRole
from backend.shelflife import engine, routes
from backend.shelflife.library import read_items
from backend.shelflife.models import RetentionConfig, RetentionEntry


def app_for(user=None):
    app = FastAPI()
    app.include_router(routes.router)
    if user:
        app.dependency_overrides[get_current_user] = lambda: user
    return app


def test_ordinary_user_can_keep_without_approval_but_cannot_change_settings(
    monkeypatch,
):
    async def run():
        async with database(monkeypatch) as factory:
            async with factory() as db:
                entry = await engine.entry_for(db, "movie", 603)
                await db.commit()
                entry_id = entry.id
            user = SimpleNamespace(
                username="friend", role=UserRole.USER, is_active=True
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app_for(user)), base_url="http://test"
            ) as client:
                path = f"/api/retention/{entry_id}/keep"
                assert (await client.post(path, json={"days": None})).status_code == 403
                headers = {"X-Shelflife-Intent": "keep"}
                assert (
                    await client.post(path, json={"days": True}, headers=headers)
                ).status_code == 422
                result = await client.post(path, json={"days": None}, headers=headers)
                assert result.status_code == 200 and result.json()["permanent"]
                result = await client.put(
                    "/api/retention/settings",
                    headers=headers,
                    json={
                        "seerr_public_url": "http://seerr",
                        "jellyfin_public_url": "http://jellyfin",
                    },
                )
                assert result.status_code == 403

    asyncio.run(run())


def test_unauthenticated_keep_is_rejected():
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app_for()), base_url="http://test"
        ) as client:
            result = await client.post(
                "/api/retention/1/keep",
                json={"days": None},
                headers={"X-Shelflife-Intent": "keep"},
            )
            assert result.status_code == 401

    asyncio.run(run())


class Session:
    def __init__(self, *args, **kwargs):
        self.calls = []
        self.status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        body = {"id": 3} if url.endswith("/auth/me") else {"ok": True}
        return SimpleNamespace(
            status_code=self.status, json=lambda: body, content=b"{}", raw=None
        )

    async def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return SimpleNamespace(status_code=self.status, content=b'{"id":42}', raw=None)

    async def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return SimpleNamespace(status_code=200, content=b"{}", raw=None)


def test_seerr_choice_is_durable_before_forward_and_uses_only_caller_session(
    monkeypatch,
):
    async def run():
        async with database(monkeypatch) as factory:
            async with factory() as db:
                db.add(
                    RetentionConfig(
                        enabled_at=NOW, seerr_public_url="http://requests.test"
                    )
                )
                await db.commit()
            session = Session()
            original = session.post

            async def post(url, **kwargs):
                async with factory() as db:
                    assert (await db.scalar(select(RetentionEntry))).permanent
                return await original(url, **kwargs)

            session.post = post
            monkeypatch.setattr(routes.niquests, "AsyncSession", lambda **kw: session)
            monkeypatch.setattr(
                routes,
                "seerr",
                lambda: (
                    1,
                    SimpleNamespace(base_url="http://seerr", api_key="ADMIN-KEY"),
                ),
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app_for()),
                base_url="http://requests.test",
            ) as client:
                headers = {
                    "Origin": "http://requests.test",
                    "Cookie": "connect.sid=friend",
                    "X-Shelflife-Intent": "keep",
                    "X-Api-Key": "must-not-forward",
                }
                body = {"mediaType": "movie", "mediaId": 603, "shelflifeDays": None}
                assert (
                    await client.post(
                        "/api/retention/seerr/request",
                        json=body,
                        headers={**headers, "Origin": "http://evil.test"},
                    )
                ).status_code == 403
                assert not session.calls
                response = await client.post(
                    "/api/retention/seerr/request", json=body, headers=headers
                )
                assert response.status_code == 200
                method, _, sent = session.calls[-1]
                assert method == "POST" and sent["json"] == {
                    "mediaType": "movie",
                    "mediaId": 603,
                }
                assert sent["headers"]["cookie"] == "connect.sid=friend"
                assert "x-api-key" not in sent["headers"]
                async with factory() as db:
                    entry = await db.scalar(select(RetentionEntry))
                    assert (
                        entry.requested_at is None
                    )  # Enrollment requires confirmed Seerr inventory.

    asyncio.run(run())


def test_roku_unfavorite_leaves_keep_even_when_favorite_cannot_be_polled(monkeypatch):
    async def run():
        async with database(monkeypatch) as factory:
            async with factory() as db:
                db.add(RetentionConfig(enabled_at=NOW))
                await db.commit()
            session = Session()
            monkeypatch.setattr(routes.niquests, "AsyncSession", lambda **kw: session)
            monkeypatch.setattr(
                routes,
                "jellyfin",
                lambda: SimpleNamespace(service_url="http://jellyfin"),
            )
            monkeypatch.setattr(
                routes,
                "jellyfin_identity",
                AsyncMock(
                    return_value=(
                        {"Id": "user"},
                        {"Authorization": "user token"},
                        "movie",
                        603,
                        -1,
                        "The Matrix",
                    )
                ),
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app_for()), base_url="http://test"
            ) as client:
                url = "/api/retention/roku/favorite/" + "a" * 32
                assert (await client.post(url)).status_code == 200
                assert (await client.delete(url)).status_code == 200
                assert [c[0] for c in session.calls] == ["POST", "DELETE"]
                async with factory() as db:
                    assert (await db.scalar(select(RetentionEntry))).permanent

    asyncio.run(run())


@pytest.mark.parametrize(
    "pages",
    [
        [{"Items": [], "TotalRecordCount": 1}],
        [
            {"Items": [{"Id": "a"}], "TotalRecordCount": 2},
            {"Items": [{"Id": "a"}], "TotalRecordCount": 2},
        ],
        [
            {"Items": [{"Id": "a"}], "TotalRecordCount": 2},
            {"Items": [{"Id": "b"}], "TotalRecordCount": 3},
        ],
        [{"Items": [{"Id": "a"}], "TotalRecordCount": 0}],
        [{"Items": [], "TotalRecordCount": "0"}],
    ],
)
def test_incomplete_favorite_inventory_never_becomes_empty_success(pages):
    async def run():
        client = SimpleNamespace(_make_request=AsyncMock(side_effect=pages))
        with pytest.raises(RuntimeError):
            await read_items(client)

    asyncio.run(run())
