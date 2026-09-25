import pytest

from nodly.services.countries import (
    InvalidCountryError,
    country_name,
    flag_emoji,
    list_countries,
    normalize_country_code,
)
from nodly.services.phones import InvalidPhoneError, normalize_e164, parse_phone, phone_region

# ---------------------------------------------------------------- countries


@pytest.mark.parametrize(
    ("code", "flag"),
    [("IN", "🇮🇳"), ("GB", "🇬🇧"), ("US", "🇺🇸"), ("AU", "🇦🇺"), ("gb", "🇬🇧"), ("XK", "🇽🇰")],
)
def test_flag_emoji(code: str, flag: str) -> None:
    assert flag_emoji(code) == flag


@pytest.mark.parametrize("bad", ["UK", "ZZ", "IND", "", "1N", "EU"])
def test_unknown_codes_are_rejected(bad: str) -> None:
    with pytest.raises(InvalidCountryError):
        normalize_country_code(bad)
    with pytest.raises(InvalidCountryError):
        flag_emoji(bad)


def test_codes_are_normalised() -> None:
    assert normalize_country_code(" in ") == "IN"
    assert country_name("in") == "India"


def test_country_list() -> None:
    countries = list_countries()
    codes = [c.code for c in countries]
    assert len(codes) == len(set(codes)) == 250  # 249 ISO 3166-1 codes + XK
    assert [c.name for c in countries] == sorted(c.name for c in countries)
    india = next(c for c in countries if c.code == "IN")
    assert (india.name, india.flag) == ("India", "🇮🇳")


# ---------------------------------------------------------------- phones


@pytest.mark.parametrize(
    ("raw", "region", "e164"),
    [
        ("+91 98765 43210", None, "+919876543210"),
        ("+44 (0)20 7946 0958", None, "+442079460958"),
        ("020 7946 0958", "GB", "+442079460958"),
        ("(212) 555-0123", "US", "+12125550123"),
        ("+61 2 9374 4000", None, "+61293744000"),
        ("+61 412 345 678", "IN", "+61412345678"),  # a + number ignores the region hint
    ],
)
def test_normalize_e164(raw: str, region: str | None, e164: str) -> None:
    assert normalize_e164(raw, region) == e164


@pytest.mark.parametrize(
    ("raw", "region"),
    [
        ("2125550123", None),  # no + and no country: we never assume one
        ("+44 12", None),
        ("hello", "GB"),
        ("+999 1234 5678", None),
        ("", "GB"),
    ],
)
def test_invalid_numbers(raw: str, region: str | None) -> None:
    with pytest.raises(InvalidPhoneError):
        normalize_e164(raw, region)


def test_phone_region() -> None:
    assert phone_region(parse_phone("+1 416 555 0123")) == "CA"
    assert phone_region(parse_phone("+1 212 555 0123")) == "US"
    assert phone_region(parse_phone("+383 44 123 456")) == "XK"
