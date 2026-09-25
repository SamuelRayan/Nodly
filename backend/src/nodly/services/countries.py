"""ISO 3166-1 alpha-2 country codes and flag emoji (CLAUDE.md §5).

The list is IANA's iso3166.tab (from the pinned `tzdata` package) plus XK (Kosovo): a
user-assigned code that libphonenumber and Unicode CLDR use, so people there can pick it.
Names are English fallbacks; apps should localise from the code.
"""

from dataclasses import dataclass
from functools import cache

from nodly.errors import InvalidInputError
from nodly.services import iana

_EXTRA_COUNTRIES = {"XK": "Kosovo"}
_REGIONAL_INDICATOR_A = 0x1F1E6


class InvalidCountryError(InvalidInputError):
    code = "invalid_country"
    title = "Unknown country"


@dataclass(frozen=True)
class Country:
    code: str
    name: str
    flag: str


@cache
def _names() -> dict[str, str]:
    return {**iana.country_names(), **_EXTRA_COUNTRIES}


def is_country_code(code: str) -> bool:
    return code in _names()


def normalize_country_code(value: str) -> str:
    """'in ' -> 'IN'. Raises InvalidCountryError for anything that isn't a known code."""
    code = value.strip().upper()
    if not is_country_code(code):
        raise InvalidCountryError(f"{value!r} is not an ISO 3166-1 alpha-2 country code.")
    return code


def country_name(code: str) -> str:
    return _names()[normalize_country_code(code)]


def flag_emoji(code: str) -> str:
    """'IN' -> '🇮🇳': the two letters as Unicode regional indicator symbols."""
    code = normalize_country_code(code)
    return "".join(chr(_REGIONAL_INDICATOR_A + ord(letter) - ord("A")) for letter in code)


@cache
def list_countries() -> tuple[Country, ...]:
    return tuple(
        Country(code=code, name=name, flag=flag_emoji(code))
        for code, name in sorted(_names().items(), key=lambda item: item[1])
    )
