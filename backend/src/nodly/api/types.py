"""Reusable request field types backed by the services, so bad input becomes a normal 422
validation error with a specific `type` (invalid_timezone, invalid_country...)."""

from collections.abc import Callable
from typing import Annotated

from pydantic import AfterValidator, Field
from pydantic_core import PydanticCustomError

from nodly.errors import InvalidInputError
from nodly.services.countries import normalize_country_code
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
