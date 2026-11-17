from datetime import UTC, datetime, timedelta

import pytest

from backend.shelflife.policy import (
    extend_deadline,
    notice,
    replace_notice,
    season_is_complete,
    validate_days,
)

NOW = datetime(2026, 11, 17, tzinfo=UTC)


@pytest.mark.parametrize("value", [True, False, 0, -1, 59, 36501, 60.5, "60"])
def test_invalid_duration(value):
    with pytest.raises(ValueError):
        validate_days(value)


@pytest.mark.parametrize("value", [None, 60, 180, 36500])
def test_valid_duration(value):
    assert validate_days(value) == value


def test_extension_never_shortens_and_normalizes_database_time():
    existing = (NOW + timedelta(days=365)).replace(tzinfo=None)
    assert extend_deadline(existing, 60, NOW) == NOW + timedelta(days=365)
    assert extend_deadline(NOW, 60, NOW) == NOW + timedelta(days=60)


@pytest.mark.parametrize(
    "change,ended,complete",
    [
        ({}, False, False),
        ({}, True, True),
        ({"finaleType": "season"}, False, True),
        ({"finaleType": "series"}, False, True),
        ({"hasFile": False}, True, False),
        ({"airDateUtc": "2027-01-01T00:00:00Z"}, True, False),
        ({"airDateUtc": None}, True, False),
    ],
)
def test_complete_season_requires_files_airing_and_finale_evidence(
    change, ended, complete
):
    episode = {"hasFile": True, "airDateUtc": "2026-01-01T00:00:00Z", **change}
    assert season_is_complete([episode], NOW, ended=ended) is complete
    assert not season_is_complete([], NOW, ended=True)


def test_notices_are_idempotent_and_preserve_updated_synopsis():
    first = notice(permanent=False, deadline=NOW, timezone="America/New_York")
    assert "Nov 16, 2026" in first
    assert "Favorite on Roku" in first
    changed = first + "New synopsis from provider."
    kept = notice(permanent=True, deadline=None)
    assert replace_notice(changed, kept) == kept + "New synopsis from provider."
    assert (
        replace_notice(replace_notice("Synopsis", first), first) == first + "Synopsis"
    )
    assert "180-day" in notice(permanent=False, deadline=None, days=180)
