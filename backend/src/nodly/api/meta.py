"""Read-only reference data for the apps: timezones and countries. No auth needed."""

from dataclasses import asdict
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel

from nodly.api.types import CountryCode
from nodly.clock import utcnow
from nodly.services.countries import list_countries
from nodly.services.timezones import SuggestionReason, list_timezones, suggest_timezones

router = APIRouter(prefix="/v1/meta", tags=["meta"])


class TimezoneOut(BaseModel):
    id: str
    label: str
    country_code: str | None
    description: str | None
    utc_offset: str
    offset_minutes: int


class TimezoneListOut(BaseModel):
    at: datetime
    timezones: list[TimezoneOut]


class TimezoneSuggestionOut(TimezoneOut):
    reason: SuggestionReason


class TimezoneSuggestionsOut(BaseModel):
    suggestions: list[TimezoneSuggestionOut]


class CountryOut(BaseModel):
    code: str
    name: str
    flag: str


class CountryListOut(BaseModel):
    countries: list[CountryOut]


@router.get("/timezones")
async def timezones() -> TimezoneListOut:
    """Every pickable timezone with its current UTC offset, sorted by offset."""
    at = utcnow()
    return TimezoneListOut(
        at=at, timezones=[TimezoneOut(**asdict(zone)) for zone in list_timezones(at)]
    )


@router.get("/timezones/suggest")
async def timezone_suggestions(
    device_timezone: Annotated[
        str | None, Query(max_length=64, description="The phone's timezone setting")
    ] = None,
    phone: Annotated[str | None, Query(max_length=32, examples=["+919876543210"])] = None,
    phone_country: Annotated[
        CountryCode | None, Query(description="Country for a number typed without +")
    ] = None,
) -> TimezoneSuggestionsOut:
    """Suggestions to show above the picker, most likely first. Never auto-select one."""
    suggestions = suggest_timezones(
        device_timezone=device_timezone, phone=phone, phone_country=phone_country
    )
    return TimezoneSuggestionsOut(
        suggestions=[
            TimezoneSuggestionOut(**asdict(s.timezone), reason=s.reason) for s in suggestions
        ]
    )


@router.get("/countries")
async def countries() -> CountryListOut:
    """ISO 3166-1 alpha-2 countries with English names and flag emoji."""
    return CountryListOut(countries=[CountryOut(**asdict(c)) for c in list_countries()])
