"""Reads the IANA tz project's data files shipped in the `tzdata` package.

- zone.tab: one row per (country, zone) — the zones people pick from, with their country.
- iso3166.tab: ISO 3166-1 alpha-2 codes with English names.
- tzdata.zi: compiled source; its "L target link" lines map old names to current ones.

Format docs: https://data.iana.org/time-zones/tz-link.html and the header of each file.
"""

from dataclasses import dataclass
from functools import cache
from importlib.resources import files


@dataclass(frozen=True)
class ZoneRow:
    country_code: str
    zone_id: str
    comment: str | None


def _read(name: str) -> list[str]:
    text = (files("tzdata") / "zoneinfo" / name).read_text(encoding="utf-8")
    return [line for line in text.splitlines() if line and not line.startswith("#")]


@cache
def zone_rows() -> tuple[ZoneRow, ...]:
    rows = []
    for line in _read("zone.tab"):
        fields = line.split("\t")
        # country code, coordinates, zone id, optional comment
        comment = fields[3] if len(fields) > 3 and fields[3] else None
        rows.append(ZoneRow(country_code=fields[0], zone_id=fields[2], comment=comment))
    return tuple(rows)


@cache
def country_names() -> dict[str, str]:
    names = {}
    for line in _read("iso3166.tab"):
        code, name = line.split("\t", 1)
        names[code] = name
    return names


@cache
def links() -> dict[str, str]:
    """Old or alternative zone name -> the name it links to."""
    mapping = {}
    for line in _read("tzdata.zi"):
        if line.startswith("L "):
            _, target, link = line.split()
            mapping[link] = target
    return mapping
