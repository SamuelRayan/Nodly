"""Where moment files live, and short-lived signed links to them (CLAUDE.md §9).

For now this is a local-disk store (MEDIA_DIR) whose files the API serves itself behind
HMAC-signed links that expire (MEDIA_URL_TTL_SECONDS). A Supabase Storage store (private
bucket, its own signed URLs) can replace it behind the same functions (D73).
"""

import hashlib
import hmac
import time
from pathlib import Path
from urllib.parse import quote

from nodly.config import Settings

SIGNING_DOMAIN = b"nodly-media-url|"


def _root(settings: Settings) -> Path:
    return Path(settings.media_dir).resolve()


def path_for(settings: Settings, key: str) -> Path:
    """The file for a storage key, refusing keys that would escape the media folder."""
    root = _root(settings)
    path = (root / key).resolve()
    if root not in path.parents:
        raise ValueError(f"Bad media key: {key!r}")
    return path


def exists(settings: Settings, key: str) -> bool:
    return path_for(settings, key).is_file()


def _signature(settings: Settings, key: str, expires: int) -> str:
    secret = settings.code_hash_secret.get_secret_value().encode()
    message = SIGNING_DOMAIN + f"{key}|{expires}".encode()
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def signed_path(settings: Settings, key: str, *, now: float | None = None) -> str:
    """A link the app can open without auth for a few minutes: /v1/media/<key>?exp=&sig=.
    Relative, so each app prefixes the API address it already uses."""
    expires = int((now if now is not None else time.time()) + settings.media_url_ttl_seconds)
    signature = _signature(settings, key, expires)
    return f"/v1/media/{quote(key)}?exp={expires}&sig={signature}"


def check_signature(
    settings: Settings, key: str, expires: int, signature: str, *, now: float | None = None
) -> bool:
    if expires < (now if now is not None else time.time()):
        return False
    return hmac.compare_digest(_signature(settings, key, expires), signature)
