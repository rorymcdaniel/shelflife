"""Trusted-user keep controls and same-origin bridges for existing clients."""

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import niquests
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, StrictInt
from sqlalchemy import func, select

from backend.core.auth import get_current_user, require_admin
from backend.core.workflow_locks import candidate_workflow_lock
from backend.database import async_db
from backend.database.models import User
from backend.shelflife import engine
from backend.shelflife.library import Library, jellyfin, seerr
from backend.shelflife.models import RetentionEntry, RetentionEvent
from backend.shelflife.policy import utc, validate_days

router = APIRouter(prefix="/api/retention", tags=["Shelflife"])
UserDep = Annotated[User, Depends(get_current_user)]
AdminDep = Annotated[User, Depends(require_admin)]


class KeepRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    days: StrictInt | None


class SettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enable: bool = True
    paused: bool = False
    preview: bool = True
    timezone: str = "UTC"
    seerr_public_url: str
    jellyfin_public_url: str


def intent(request: Request) -> None:
    if request.headers.get("x-shelflife-intent") != "keep":
        raise HTTPException(403, "Missing Shelflife request intent")


def valid_days(days: int | None) -> int | None:
    try:
        return validate_days(days)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def payload(entry: RetentionEntry) -> dict:
    return {
        "id": entry.id,
        "kind": entry.kind,
        "tmdb_id": entry.tmdb_id,
        "season_number": entry.season_number,
        "title": entry.title,
        "permanent": entry.permanent,
        "enrolled": entry.requested_at is not None,
        "days": entry.days,
        "requested_at": utc(entry.requested_at).isoformat()
        if entry.requested_at
        else None,
        "available_at": utc(entry.available_at).isoformat()
        if entry.available_at
        else None,
        "expires_at": utc(entry.expires_at).isoformat() if entry.expires_at else None,
        "deleted_at": utc(entry.deleted_at).isoformat() if entry.deleted_at else None,
        "last_error": entry.last_error,
    }


def config_payload(row) -> dict:
    return {
        "enabled_at": utc(row.enabled_at).isoformat() if row.enabled_at else None,
        "paused": row.paused,
        "preview": row.preview,
        "timezone": row.timezone,
        "seerr_public_url": row.seerr_public_url,
        "jellyfin_public_url": row.jellyfin_public_url,
        "last_checked_at": utc(row.last_checked_at).isoformat()
        if row.last_checked_at
        else None,
        "last_error": row.last_error,
    }


@router.get("")
async def overview(_user: UserDep, page: int = Query(1, ge=1)):
    async with async_db() as db:
        settings = await engine.config(db)
        total = await db.scalar(select(func.count()).select_from(RetentionEntry))
        entries = (
            await db.scalars(
                select(RetentionEntry)
                .order_by(
                    RetentionEntry.permanent,
                    RetentionEntry.expires_at,
                    RetentionEntry.id,
                )
                .limit(100)
                .offset((page - 1) * 100)
            )
        ).all()
        await db.commit()
        return {
            "settings": config_payload(settings),
            "items": [payload(e) for e in entries],
            "total": total,
        }


@router.put("/settings")
async def update_settings(data: SettingsRequest, request: Request, _admin: AdminDep):
    intent(request)
    try:
        ZoneInfo(data.timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(422, "Choose a valid IANA time zone") from exc
    for value in [data.seerr_public_url, data.jellyfin_public_url]:
        url = urlsplit(value)
        if (
            url.scheme not in {"http", "https"}
            or not url.netloc
            or url.username
            or url.password
            or url.path not in {"", "/"}
            or url.query
            or url.fragment
        ):
            raise HTTPException(
                422, "Use an http(s) origin without credentials or a subpath"
            )
    if data.enable:
        jellyfin()
        seerr()
    async with candidate_workflow_lock, async_db() as db:
        row = await engine.config(db)
        now = datetime.now(UTC)
        if data.enable and row.enabled_at is None:
            row.enabled_at = now
        if row.preview and not data.preview:
            # A long preview must not cause immediate deletions on activation.
            for entry in (
                await db.scalars(
                    select(RetentionEntry).where(
                        RetentionEntry.deleted_at.is_(None),
                        RetentionEntry.permanent.is_(False),
                        RetentionEntry.available_at.is_not(None),
                    )
                )
            ).all():
                entry.expires_at = max(
                    utc(entry.expires_at) if entry.expires_at else now,
                    now + timedelta(days=entry.days),
                )
                await engine.mirror_protection(db, entry)
                await engine.event(
                    db, entry, "live_window_started", _admin.username, now
                )
        row.paused, row.preview, row.timezone = (
            data.paused or not data.enable,
            data.preview,
            data.timezone,
        )
        row.seerr_public_url, row.jellyfin_public_url = (
            data.seerr_public_url.rstrip("/"),
            data.jellyfin_public_url.rstrip("/"),
        )
        await db.commit()
        return config_payload(row)


@router.post("/sync")
async def sync_now(request: Request, _admin: AdminDep):
    intent(request)
    await engine.cycle()
    return {"ok": True}


@router.post("/{entry_id:int}/keep")
async def keep_entry(entry_id: int, data: KeepRequest, request: Request, user: UserDep):
    intent(request)
    async with candidate_workflow_lock, async_db() as db:
        entry = await db.get(RetentionEntry, entry_id)
        if entry is None:
            raise HTTPException(404, "Title not found")
        try:
            await engine.keep(
                db,
                entry,
                valid_days(data.days),
                actor=user.username,
                now=datetime.now(UTC),
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        await db.commit()
        return payload(entry)


@router.get("/{entry_id:int}/history")
async def history(entry_id: int, _admin: AdminDep):
    async with async_db() as db:
        events = (
            await db.scalars(
                select(RetentionEvent)
                .where(RetentionEvent.entry_id == entry_id)
                .order_by(RetentionEvent.id.desc())
                .limit(100)
            )
        ).all()
        return [
            {
                "action": e.action,
                "actor": e.actor,
                "at": utc(e.occurred_at).isoformat(),
                "deadline": utc(e.deadline).isoformat() if e.deadline else None,
            }
            for e in events
        ]


@router.get("/assets/{name}")
async def script(name: str):
    if name not in {"seerr.js", "jellyfin.js", "common.js"}:
        raise HTTPException(404)
    return FileResponse(
        Path(__file__).with_name("web") / name,
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},
    )


def user_token(request: Request) -> str:
    token = (
        request.headers.get("x-emby-token")
        or request.headers.get("x-mediabrowser-token")
        or request.query_params.get("api_key")
    )
    if not token:
        for name in ("authorization", "x-emby-authorization"):
            header = request.headers.get(name, "")
            match = re.search(r'(?:^|[,\s])Token="([^"]+)"', header, re.IGNORECASE)
            if match:
                token = match.group(1)
                break
    if not token or not re.fullmatch(r"[A-Za-z0-9._-]{16,512}", token):
        raise HTTPException(401, "Sign in to Jellyfin")
    return token


async def jellyfin_identity(
    request: Request, item_id: str, *, allow_unsupported: bool = False
):
    if not re.fullmatch(r"[a-fA-F0-9-]{32,36}", item_id):
        raise HTTPException(422, "Invalid Jellyfin item")
    client = jellyfin()
    headers = {"Authorization": f'MediaBrowser Token="{user_token(request)}"'}
    async with niquests.AsyncSession(timeout=30) as http:
        response = await http.get(
            f"{client.service_url}/Users/Me", headers=headers, allow_redirects=False
        )
        if response.status_code != 200:
            raise HTTPException(401, "Sign in to Jellyfin")
        user = response.json()
        if (
            not isinstance(user, dict)
            or not user.get("Id")
            or user.get("Policy", {}).get("IsDisabled")
        ):
            raise HTTPException(403, "Jellyfin account is disabled")
        result = await http.get(
            f"{client.service_url}/Items",
            params={"Ids": item_id, "userId": user["Id"], "Fields": "ProviderIds"},
            headers=headers,
            allow_redirects=False,
        )
        if result.status_code != 200:
            raise HTTPException(
                403, "This title is not accessible to your Jellyfin account"
            )
        items = result.json().get("Items", [])
        if len(items) != 1:
            raise HTTPException(404, "Title not found")
        item = items[0]
        kind = "movie" if item.get("Type") == "Movie" else "series"
        season = -1
        parent = item
        if item.get("Type") in {"Episode", "Season"}:
            season = (
                item.get("ParentIndexNumber")
                if item["Type"] == "Episode"
                else item.get("IndexNumber")
            )
            series_id = item.get("SeriesId", "")
            if type(season) is not int or not re.fullmatch(
                r"[a-fA-F0-9-]{32,36}", series_id
            ):
                raise HTTPException(422, "Cannot identify this season")
            result = await http.get(
                f"{client.service_url}/Items",
                params={
                    "Ids": series_id,
                    "userId": user["Id"],
                    "Fields": "ProviderIds",
                },
                headers=headers,
                allow_redirects=False,
            )
            result.raise_for_status()
            parents = result.json().get("Items", [])
            if len(parents) != 1:
                raise HTTPException(404, "Series not found")
            parent = parents[0]
        elif item.get("Type") not in {"Movie", "Series"}:
            if allow_unsupported:
                return user, headers, "", 0, -1, str(item.get("Name", "Title"))
            raise HTTPException(
                422, "Retention supports movies, shows, seasons and episodes"
            )
        tmdb_id = parent.get("ProviderIds", {}).get("Tmdb")
        if not str(tmdb_id).isdigit():
            if allow_unsupported:
                return user, headers, "", 0, -1, str(item.get("Name", "Title"))
            raise HTTPException(422, "This title has no TMDB identifier")
        return user, headers, kind, int(tmdb_id), season, str(item.get("Name", "Title"))


@router.get("/jellyfin/{item_id}")
async def jellyfin_status(item_id: str, request: Request):
    _, _, kind, tmdb_id, season, title = await jellyfin_identity(request, item_id)
    async with async_db() as db:
        entry = await db.scalar(
            select(RetentionEntry).where(
                RetentionEntry.kind == kind,
                RetentionEntry.tmdb_id == tmdb_id,
                RetentionEntry.season_number == season,
            )
        )
        result = (
            payload(entry)
            if entry
            else {
                "title": title,
                "permanent": False,
                "expires_at": None,
                "enrolled": False,
            }
        )
        if kind == "series" and season >= 0:
            umbrella = await db.scalar(
                select(RetentionEntry).where(
                    RetentionEntry.kind == "series",
                    RetentionEntry.tmdb_id == tmdb_id,
                    RetentionEntry.season_number == -1,
                    RetentionEntry.permanent.is_(True),
                )
            )
            if umbrella:
                result.update(permanent=True, expires_at=None)
        return result


@router.post("/jellyfin/{item_id}/keep")
async def jellyfin_keep(item_id: str, data: KeepRequest, request: Request):
    intent(request)
    user, _, kind, tmdb_id, season, title = await jellyfin_identity(request, item_id)
    async with candidate_workflow_lock, async_db() as db:
        entry = await engine.entry_for(db, kind, tmdb_id, season)
        entry.title = title
        try:
            await engine.keep(
                db,
                entry,
                valid_days(data.days),
                actor=f"Jellyfin user {user['Id']}",
                now=datetime.now(UTC),
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        await db.commit()
        return payload(entry)


@router.api_route("/roku/favorite/{item_id}", methods=["POST", "DELETE"])
async def roku_favorite(item_id: str, request: Request):
    user, headers, kind, tmdb_id, season, title = await jellyfin_identity(
        request, item_id, allow_unsupported=True
    )
    if request.method == "POST" and kind:
        # Persist before forwarding: a disconnect/restart must never lose a keep.
        async with candidate_workflow_lock, async_db() as db:
            settings = await engine.config(db)
            if settings.enabled_at:
                entry = await engine.entry_for(db, kind, tmdb_id, season)
                entry.title = title
                if not entry.deleted_at:
                    await engine.keep(
                        db,
                        entry,
                        None,
                        actor=f"Jellyfin Favorite ({user['Id']})",
                        now=datetime.now(UTC),
                    )
                await db.commit()
    # DELETE only removes the favorite; it never changes retention.
    async with niquests.AsyncSession(timeout=30) as http:
        upstream = await http.request(
            request.method,
            f"{jellyfin().service_url}/UserFavoriteItems/{item_id}",
            params={"userId": user["Id"]},
            headers=headers,
            allow_redirects=False,
        )
        return Response(
            content=upstream.content,
            status_code=upstream.status_code or 502,
            media_type="application/json",
        )


@router.api_route("/seerr/request", methods=["GET", "POST"])
async def seerr_request(request: Request):
    _, client = seerr()
    # Only the caller's session is forwarded. Never send the administrator API key.
    headers = {
        key: request.headers[key]
        for key in ("cookie", "x-csrf-token", "x-xsrf-token", "origin", "referer")
        if key in request.headers
    }
    headers["Accept"] = "application/json"
    async with niquests.AsyncSession(timeout=45) as http:
        if request.method == "GET":
            upstream = await http.get(
                f"{client.base_url}/api/v1/request",
                headers=headers,
                params=dict(request.query_params),
                allow_redirects=False,
            )
        else:
            intent(request)
            async with async_db() as db:
                settings = await engine.config(db)
                await db.commit()
                if not settings.enabled_at:
                    raise HTTPException(
                        503,
                        "Enable Shelflife preview before using this request gateway",
                    )
                if (
                    request.headers.get("origin", "").rstrip("/")
                    != settings.seerr_public_url
                ):
                    raise HTTPException(
                        403, "Request must originate from the configured Seerr address"
                    )
            identity = await http.get(
                f"{client.base_url}/api/v1/auth/me",
                headers=headers,
                allow_redirects=False,
            )
            if identity.status_code != 200:
                raise HTTPException(401, "Sign in to Seerr")
            user = identity.json()
            if not isinstance(user, dict) or type(user.get("id")) is not int:
                raise HTTPException(401, "Invalid Seerr session")
            body = await request.json()
            if not isinstance(body, dict):
                raise HTTPException(422, "Invalid request")
            days = valid_days(body.pop("shelflifeDays", 60))
            kind = "movie" if body.get("mediaType") == "movie" else "series"
            tmdb_id = body.get("mediaId")
            if (
                type(tmdb_id) is not int
                or tmdb_id < 1
                or body.get("mediaType") not in {"movie", "tv"}
            ):
                raise HTTPException(422, "Invalid media request")
            seasons = [-1] if kind == "movie" else body.get("seasons", [])
            if seasons == "all":
                details = await http.get(
                    f"{client.base_url}/api/v1/tv/{tmdb_id}",
                    headers=headers,
                    allow_redirects=False,
                )
                details.raise_for_status()
                seasons = [s["seasonNumber"] for s in details.json().get("seasons", [])]
            if (
                not isinstance(seasons, list)
                or not seasons
                or not all(
                    type(s) is int and (s >= 0 or kind == "movie" and s == -1)
                    for s in seasons
                )
            ):
                raise HTTPException(422, "Select the seasons to request")
            async with candidate_workflow_lock, async_db() as db:
                for season in seasons:
                    entry = await engine.entry_for(db, kind, tmdb_id, season)
                    if entry.deleted_at:
                        # A successful new upstream request will enroll a new window.
                        entry.days = days or 60
                        entry.permanent = days is None
                    else:
                        await engine.keep(
                            db,
                            entry,
                            days,
                            actor=f"Seerr user {user['id']}",
                            now=datetime.now(UTC),
                            preference=True,
                        )
                await db.commit()
            upstream = await http.post(
                f"{client.base_url}/api/v1/request",
                headers=headers,
                json=body,
                allow_redirects=False,
            )
        response = Response(
            content=upstream.content,
            status_code=upstream.status_code or 502,
            media_type="application/json",
        )
        if upstream.raw is not None:
            for cookie in upstream.raw.headers.getlist("Set-Cookie"):
                response.headers.append("Set-Cookie", cookie)
        return response
