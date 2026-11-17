"""The retention contract. Time and external observations are explicit inputs."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

DEFAULT_DAYS = 60
MAX_DAYS = 36500
NOTICE_PREFIX = "Library retention: "


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def validate_days(days: int | None) -> int | None:
    if days is not None and (type(days) is not int or not 60 <= days <= MAX_DAYS):
        raise ValueError("Choose 60–36500 days, or keep forever")
    return days


def extend_deadline(current: datetime | None, days: int, now: datetime) -> datetime:
    """A timed keep guarantees at least this many days from now; never shortens."""
    proposed = utc(now) + timedelta(days=days)
    return max(utc(current), proposed) if current else proposed


def season_is_complete(episodes: list[dict], now: datetime, *, ended: bool) -> bool:
    """Require files for the entire known season and affirmative finale evidence."""
    if not episodes or not all(e.get("hasFile") is True for e in episodes):
        return False
    for episode in episodes:
        if not isinstance(episode.get("airDateUtc"), str):
            return False
        try:
            aired = utc(
                datetime.fromisoformat(episode["airDateUtc"].replace("Z", "+00:00"))
            )
        except (KeyError, TypeError, ValueError):
            return False
        if aired > utc(now):
            return False
    return ended or any(
        str(e.get("finaleType", "")).lower() in {"season", "series"} for e in episodes
    )


def notice(
    *,
    permanent: bool,
    deadline: datetime | None,
    timezone: str = "UTC",
    days: int = DEFAULT_DAYS,
) -> str:
    if permanent:
        return NOTICE_PREFIX + "Kept permanently.\n\n"
    if deadline is None:
        status = (
            f"{days}-day window starts when the requested media is fully available."
        )
    else:
        date = utc(deadline).astimezone(ZoneInfo(timezone)).strftime("%b %d, %Y (%Z)")
        status = f"Scheduled for deletion on {date}."
    return (
        NOTICE_PREFIX + status + "\n"
        "Keep forever: mark as Favorite on Roku. For more time, use Keep in your web browser.\n\n"
    )


def replace_notice(overview: str | None, prefix: str) -> str:
    """Replace only our leading paragraph; preserve the latest provider synopsis."""
    text = overview or ""
    if text.startswith(NOTICE_PREFIX):
        _, separator, remainder = text.partition("\n\n")
        if separator:
            text = remainder
    return prefix + text
