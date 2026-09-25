"""Invite/pairing codes and elder device tokens: generation, normalisation, hashing.

Codes use Crockford's base32 alphabet (no I, L, O, U), so they read well aloud and on screen,
and typing is forgiving: case, spaces and dashes are ignored and O/I/L are read as 0/1/1.
Codes are stored as HMAC-SHA256 with a server secret, namespaced by kind; device tokens
(256 random bits) are stored as plain SHA-256.
"""

import hashlib
import hmac
import secrets
from enum import StrEnum

CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_LOOKALIKES = str.maketrans({"O": "0", "I": "1", "L": "1"})
_SEPARATORS = str.maketrans("", "", " -_")

DEVICE_TOKEN_PREFIX = "ndt_"
_DEVICE_TOKEN_BYTES = 32  # 256 bits


class CodeKind(StrEnum):
    invite = "invite"  # 10 characters (50 bits), lives 48 hours, usually sent as a link
    pairing = "pairing"  # 8 characters (40 bits), lives 15 minutes, may be typed on the phone


CODE_LENGTHS = {CodeKind.invite: 10, CodeKind.pairing: 8}


def generate_code(kind: CodeKind) -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTHS[kind]))


def format_code(code: str) -> str:
    """'7KQ4M2XD' -> '7KQ4-M2XD'; 10-character codes split 5-5."""
    half = len(code) // 2
    return f"{code[:half]}-{code[half:]}"


def normalize_code(raw: str, kind: CodeKind) -> str | None:
    """The canonical code, or None if `raw` can't be a code of this kind."""
    code = raw.upper().translate(_SEPARATORS).translate(_LOOKALIKES)
    if len(code) != CODE_LENGTHS[kind] or any(c not in CODE_ALPHABET for c in code):
        return None
    return code


def hash_code(code: str, kind: CodeKind, secret: str) -> str:
    message = f"{kind}:{code}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def generate_device_token() -> str:
    return DEVICE_TOKEN_PREFIX + secrets.token_urlsafe(_DEVICE_TOKEN_BYTES)


def hash_device_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def is_device_token(token: str) -> bool:
    return token.startswith(DEVICE_TOKEN_PREFIX)
