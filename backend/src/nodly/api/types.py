"""Reusable request field types backed by the services, so bad input becomes a normal 422
validation error with a specific `type` (invalid_timezone, invalid_country...)."""

from collections.abc import Callable
from typing import Annotated

from pydantic import AfterValidator, Field, StringConstraints
from pydantic_core import PydanticCustomError

from nodly.errors import InvalidInputError
from nodly.models.base import LOCALE_PATTERN
from nodly.services.countries import normalize_country_code
from nodly.services.phones import normalize_e164
from nodly.services.timezones import validate_timezone


def _as_validation_error(normalize: Callable[[str], str]) -> Callable[[str], str]:
    def validator(value: str) -> str:
        try:
            return normalize(value)
        except InvalidInputError as exc:
            raise PydanticCustomError(exc.code, exc.detail or exc.title) from exc

    return validator


TimezoneName = Annotated[
    str,
    Field(max_length=64, examples=["Asia/Kolkata"], description="IANA timezone the person picked"),
    AfterValidator(_as_validation_error(validate_timezone)),
]

CountryCode = Annotated[
    str,
    Field(max_length=3, examples=["IN"], description="ISO 3166-1 alpha-2 country code"),
    AfterValidator(_as_validation_error(normalize_country_code)),
]

DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]

LanguageTag = Annotated[
    str,
    StringConstraints(max_length=35, pattern=LOCALE_PATTERN),
    Field(examples=["hi-IN"], description="BCP 47 language tag, e.g. hi, en-GB"),
]

PhoneInput = Annotated[
    str,
    Field(max_length=32, examples=["+91 98765 43210"], description="Any format; stored as E.164"),
]


def normalize_phone_field(phone: str | None, country: str | None) -> str | None:
    """E.164 for a model validator; `country` is the parsing hint for numbers without +."""
    if phone is None:
        return None
    try:
        return normalize_e164(phone, country)
    except InvalidInputError as exc:
        raise PydanticCustomError(exc.code, exc.detail or exc.title) from exc
