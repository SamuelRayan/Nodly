from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from nodly.services import iana
from nodly.services.phones import InvalidPhoneError
from nodly.services.timezones import (
    UTC_ZONE,
    InvalidTimezoneError,
    SuggestionReason,
    list_timezones,
    suggest_timezones,
    validate_timezone,
)

JANUARY = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
JULY = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------- validation


@pytest.mark.parametrize(
    ("given", "stored"),
    [
        ("Asia/Kolkata", "Asia/Kolkata"),
        ("Asia/Calcutta", "Asia/Kolkata"),  # old name, still sent by libphonenumber and old phones
        ("US/Eastern", "America/New_York"),
        ("Europe/Kiev", "Europe/Kyiv"),
        ("  Europe/London ", "Europe/London"),
        ("UTC", UTC_ZONE),
        ("Etc/UTC", UTC_ZONE),
        ("GMT", UTC_ZONE),
        ("Australia/Lord_Howe", "Australia/Lord_Howe"),
    ],
)
def test_valid_timezones_are_canonicalised(given: str, stored: str) -> None:
    assert validate_timezone(given) == stored


@pytest.mark.parametrize(
    "bad",
    ["", "Mars/Olympus_Mons", "asia/kolkata", "Etc/GMT+5", "Factory", "../../etc/passwd", "IST"],
)
def test_invalid_timezones_are_rejected(bad: str) -> None:
    with pytest.raises(InvalidTimezoneError):
        validate_timezone(bad)


def test_every_zone_tab_zone_is_loadable() -> None:
    for row in iana.zone_rows():
        ZoneInfo(row.zone_id)


# ---------------------------------------------------------------- the picker list


def test_list_has_every_place_once_with_labels_and_offsets() -> None:
    zones = list_timezones(JANUARY)
    ids = [zone.id for zone in zones]
    assert len(ids) == len(set(ids))
    assert "Asia/Calcutta" not in ids
    assert UTC_ZONE in ids
    kolkata = next(zone for zone in zones if zone.id == "Asia/Kolkata")
    assert (kolkata.label, kolkata.country_code, kolkata.utc_offset) == (
        "Kolkata, India",
        "IN",
        "+05:30",
    )
    assert [zone.offset_minutes for zone in zones] == sorted(zone.offset_minutes for zone in zones)


@pytest.mark.parametrize(
    ("zone_id", "january", "july"),
    [
        ("Europe/London", "+00:00", "+01:00"),  # DST in the northern summer
        ("Australia/Sydney", "+11:00", "+10:00"),  # DST in the southern summer
        ("Asia/Kathmandu", "+05:45", "+05:45"),
        ("America/St_Johns", "-03:30", "-02:30"),
        ("Etc/UTC", "+00:00", "+00:00"),
    ],
)
def test_offsets_follow_dst(zone_id: str, january: str, july: str) -> None:
    def offset_at(at: datetime) -> str:
        return next(zone.utc_offset for zone in list_timezones(at) if zone.id == zone_id)

    assert (offset_at(JANUARY), offset_at(JULY)) == (january, july)


# ---------------------------------------------------------------- suggestions


def ids_and_reasons(**kwargs: str) -> list[tuple[str, SuggestionReason]]:
    return [(s.timezone.id, s.reason) for s in suggest_timezones(at=JANUARY, **kwargs)]


def test_no_inputs_means_no_suggestions() -> None:
    assert suggest_timezones() == []


def test_india_plus_91() -> None:
    # libphonenumber says Asia/Calcutta; we suggest the current name.
    assert ids_and_reasons(phone="+91 98765 43210") == [
        ("Asia/Kolkata", SuggestionReason.phone_number)
    ]


def test_uk_plus_44() -> None:
    assert ids_and_reasons(phone="+44 20 7946 0958") == [
        ("Europe/London", SuggestionReason.phone_number)
    ]


def test_us_plus_1_suggests_the_area_first_then_the_rest_of_the_country() -> None:
    suggestions = ids_and_reasons(phone="+1 212 555 0123")
    assert suggestions[0] == ("America/New_York", SuggestionReason.phone_number)
    rest = suggestions[1:]
    assert {reason for _, reason in rest} == {SuggestionReason.phone_country}
    assert ("America/Los_Angeles", SuggestionReason.phone_country) in rest
    assert all(zone.startswith(("America/", "Pacific/Honolulu")) for zone, _ in rest)
    assert "America/Toronto" not in [zone for zone, _ in rest]  # +1 is shared; this is a US number


def test_canada_plus_1() -> None:
    suggestions = ids_and_reasons(phone="+1 416 555 0123")
    assert suggestions[0] == ("America/Toronto", SuggestionReason.phone_number)
    assert ("America/Vancouver", SuggestionReason.phone_country) in suggestions
    assert "America/New_York" not in [zone for zone, _ in suggestions]


def test_australia_plus_61_landline() -> None:
    suggestions = ids_and_reasons(phone="+61 2 9374 4000")
    assert suggestions[0] == ("Australia/Sydney", SuggestionReason.phone_number)
    assert ("Australia/Perth", SuggestionReason.phone_country) in suggestions
    assert len(suggestions) == len({zone for zone, _ in suggestions})


def test_australia_plus_61_mobile_is_not_tied_to_one_area() -> None:
    suggestions = ids_and_reasons(phone="+61 412 345 678")
    phone_zones = [zone for zone, reason in suggestions if reason == SuggestionReason.phone_number]
    assert {"Australia/Sydney", "Australia/Perth", "Australia/Brisbane"} <= set(phone_zones)


def test_device_timezone_comes_first_and_is_canonicalised() -> None:
    assert ids_and_reasons(device_timezone="Asia/Calcutta", phone="+44 20 7946 0958") == [
        ("Asia/Kolkata", SuggestionReason.device),
        ("Europe/London", SuggestionReason.phone_number),
    ]


def test_device_and_phone_agreeing_are_not_repeated() -> None:
    assert ids_and_reasons(device_timezone="Europe/London", phone="+44 20 7946 0958") == [
        ("Europe/London", SuggestionReason.device)
    ]


def test_unpickable_device_timezone_is_ignored() -> None:
    assert ids_and_reasons(device_timezone="Etc/GMT+5") == []


def test_number_without_plus_uses_the_chosen_country() -> None:
    assert ids_and_reasons(phone="098765 43210", phone_country="IN") == [
        ("Asia/Kolkata", SuggestionReason.phone_number)
    ]


def test_invalid_phone_is_an_error() -> None:
    with pytest.raises(InvalidPhoneError):
        suggest_timezones(phone="+44 12")
