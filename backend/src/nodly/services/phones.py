"""Phone numbers: parsing and E.164 normalisation with libphonenumber.

There is no default country (CLAUDE.md principle 5): a number without a leading + needs a
region the user picked. https://github.com/daviddrysdale/python-phonenumbers
"""

import phonenumbers

from nodly.errors import InvalidInputError


class InvalidPhoneError(InvalidInputError):
    code = "invalid_phone"
    title = "Invalid phone number"


def parse_phone(raw: str, region: str | None = None) -> phonenumbers.PhoneNumber:
    """Parse and check a number is valid (a real, assigned range). Raises InvalidPhoneError."""
    text = raw.strip()
    if not text.startswith("+") and region is None:
        raise InvalidPhoneError(
            "Add the country code (starting with +) or choose the number's country."
        )
    try:
        number = phonenumbers.parse(text, region)
    except phonenumbers.NumberParseException as exc:
        raise InvalidPhoneError(f"This doesn't look like a phone number ({exc}).") from exc
    if not phonenumbers.is_valid_number(number):
        raise InvalidPhoneError("This phone number isn't valid.")
    return number


def normalize_e164(raw: str, region: str | None = None) -> str:
    """'+91 98765 43210' -> '+919876543210'."""
    return phonenumbers.format_number(parse_phone(raw, region), phonenumbers.PhoneNumberFormat.E164)


def phone_region(number: phonenumbers.PhoneNumber) -> str | None:
    """The number's country (ISO alpha-2), or None for non-geographic numbers."""
    region = phonenumbers.region_code_for_number(number)
    return region if region and region != phonenumbers.UNKNOWN_REGION else None
