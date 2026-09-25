"""IANA timezones: validation, the picker list, and suggestions (CLAUDE.md §5).

Every user and elder picks a timezone; we only suggest. The selectable zones are those in
IANA's zone.tab (real places, one row per country) plus Etc/UTC. Old or alternative names
(Asia/Calcutta, US/Eastern, UTC) are accepted and stored as the zone they link to.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from functools import cache
from zoneinfo import ZoneInfo

from phonenumbers import timezone as phone_timezones

from nodly.clock import utcnow
from nodly.errors import InvalidInputError
from nodly.services import iana
from nodly.services.countries import country_name
from nodly.services.phones import parse_phone, phone_region

UTC_ZONE = "Etc/UTC"
# Zero-offset, no-DST zones that aren't in zone.tab; devices (e.g. emulators) report these.
_UTC_EQUIVALENTS = frozenset({"Etc/UTC", "Etc/GMT"})


class InvalidTimezoneError(InvalidInputError):
    code = "invalid_timezone"
    title = "Unknown timezone"


class SuggestionReason(StrEnum):
    device = "device"  # the phone's own timezone setting
    phone_number = "phone_number"  # the number's area (e.g. +1 212 -> New York)
    phone_country = "phone_country"  # other zones in the number's country


@dataclass(frozen=True)
class Timezone:
    id: str
    label: str  # "Kolkata, India" (English; apps may localise the country from country_code)
    country_code: str | None
    description: str | None  # zone.tab comment for countries with several zones
    utc_offset: str  # "+05:30" at the time asked about
    offset_minutes: int


@dataclass(frozen=True)
class TimezoneSuggestion:
    timezone: Timezone
    reason: SuggestionReason


@cache
def _selectable() -> dict[str, iana.ZoneRow | None]:
    zones: dict[str, iana.ZoneRow | None] = {row.zone_id: row for row in iana.zone_rows()}
    zones[UTC_ZONE] = None
    return zones


@cache
def _zones_by_country() -> dict[str, tuple[str, ...]]:
    by_country: dict[str, list[str]] = {}
    for row in iana.zone_rows():
        by_country.setdefault(row.country_code, []).append(row.zone_id)
    return {code: tuple(zones) for code, zones in by_country.items()}


def canonical_timezone(name: str) -> str | None:
    """The selectable zone id for `name`, following IANA links; None if it isn't one."""
    zone = name.strip()
    selectable = _selectable()
    links = iana.links()
    seen: set[str] = set()
    while zone not in selectable and zone in links and zone not in seen:
        seen.add(zone)
        zone = links[zone]
    if zone in _UTC_EQUIVALENTS:
        return UTC_ZONE
    return zone if zone in selectable else None


def validate_timezone(name: str) -> str:
    """Return the canonical zone id, or raise InvalidTimezoneError."""
    zone = canonical_timezone(name)
    if zone is None:
        raise InvalidTimezoneError(f"{name!r} is not a timezone you can pick.")
    return zone


def _format_offset(minutes: int) -> str:
    sign = "+" if minutes >= 0 else "-"
    hours, mins = divmod(abs(minutes), 60)
    return f"{sign}{hours:02d}:{mins:02d}"


def describe_timezone(zone_id: str, at: datetime | None = None) -> Timezone:
    zone_id = validate_timezone(zone_id)
    moment = at or utcnow()
    offset = moment.astimezone(ZoneInfo(zone_id)).utcoffset()
    assert offset is not None
    minutes = int(offset.total_seconds() // 60)
    row = _selectable()[zone_id]
    if row is None:
        label, country, description = "Coordinated Universal Time (UTC)", None, None
    else:
        city = zone_id.rsplit("/", 1)[-1].replace("_", " ")
        label = f"{city}, {country_name(row.country_code)}"
        country, description = row.country_code, row.comment
    return Timezone(
        id=zone_id,
        label=label,
        country_code=country,
        description=description,
        utc_offset=_format_offset(minutes),
        offset_minutes=minutes,
    )


def list_timezones(at: datetime | None = None) -> list[Timezone]:
    """Every selectable zone with its offset at `at` (default now), sorted by offset then name."""
    moment = at or utcnow()
    zones = [describe_timezone(zone_id, moment) for zone_id in _selectable()]
    return sorted(zones, key=lambda zone: (zone.offset_minutes, zone.label))


def suggest_timezones(
    *,
    device_timezone: str | None = None,
    phone: str | None = None,
    phone_country: str | None = None,
    at: datetime | None = None,
) -> list[TimezoneSuggestion]:
    """Ordered, de-duplicated suggestions. Never a default: no inputs means no suggestions.

    1. the device's own timezone (ignored if it isn't a pickable zone),
    2. zones for the phone number's area,
    3. the other zones of the phone number's country.
    `phone_country` is only a parsing hint for numbers typed without +. An invalid phone
    number raises InvalidPhoneError.
    """
    moment = at or utcnow()
    ordered: dict[str, SuggestionReason] = {}

    def add(zones: Iterable[str], reason: SuggestionReason) -> None:
        for name in zones:
            zone = canonical_timezone(name)
            if zone is not None and zone not in ordered:
                ordered[zone] = reason

    if device_timezone:
        add([device_timezone], SuggestionReason.device)
    if phone:
        number = parse_phone(phone, phone_country)
        # Unknown areas come back as "Etc/Unknown", which canonical_timezone() drops.
        add(phone_timezones.time_zones_for_number(number), SuggestionReason.phone_number)
        region = phone_region(number)
        if region:
            add(_zones_by_country().get(region, ()), SuggestionReason.phone_country)

    return [
        TimezoneSuggestion(timezone=describe_timezone(zone, moment), reason=reason)
        for zone, reason in ordered.items()
    ]
