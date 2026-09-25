"""Family PINs: short numeric secrets, stored with scrypt (Python standard library).

A PIN has little entropy, so the slow hash matters less than the attempt limits around it
(nodly.security.throttle); scrypt still keeps a leaked database from giving PINs away instantly.
Format: scrypt$<n>$<r>$<p>$<salt hex>$<hash hex>
"""

import hashlib
import hmac
import secrets

_N, _R, _P, _DKLEN = 2**14, 8, 1, 32


def hash_pin(pin: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(pin.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def verify_pin(pin: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, expected = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    digest = hashlib.scrypt(
        pin.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=_DKLEN
    )
    return hmac.compare_digest(digest.hex(), expected)
