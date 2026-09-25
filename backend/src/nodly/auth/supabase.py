"""Verifying Supabase Auth access tokens (family members).

Tokens are checked against the project's published signing keys (JWKS), never a shared secret:
- keys: {SUPABASE_URL}/auth/v1/.well-known/jwks.json, asymmetric only (ES256 / RS256)
- claims: iss = {SUPABASE_URL}/auth/v1, aud = "authenticated", exp/iat, role = "authenticated",
  sub = the user's UUID; anonymous sign-ins are refused.
https://supabase.com/docs/guides/auth/signing-keys
https://supabase.com/docs/guides/auth/jwt-fields
"""

import asyncio
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
import jwt

from nodly.config import Settings
from nodly.errors import ServiceUnavailableError, UnauthorizedError

logger = logging.getLogger(__name__)

# Asymmetric only. Symmetric (HS256 / "oct") keys are never accepted, so a token can't pick
# an algorithm that turns a public key into a shared secret.
ALLOWED_ALGORITHMS = frozenset({"ES256", "RS256"})
_ALLOWED_KEY_TYPES = frozenset({"EC", "RSA"})
JWKS_FETCH_TIMEOUT_SECONDS = 5.0


class InvalidTokenError(UnauthorizedError):
    code = "invalid_token"
    title = "Invalid access token"


class TokenExpiredError(UnauthorizedError):
    code = "token_expired"
    title = "Access token expired"


class AuthUnavailableError(ServiceUnavailableError):
    code = "auth_unavailable"
    title = "Sign-in is temporarily unavailable"


class AuthNotConfiguredError(ServiceUnavailableError):
    code = "auth_not_configured"
    title = "Sign-in isn't configured on this server"


@dataclass(frozen=True)
class SupabaseClaims:
    user_id: uuid.UUID
    email: str | None
    session_id: str | None
    claims: dict[str, Any]


class JWKSCache:
    """Signing keys by key id, refreshed every `ttl` seconds.

    A token naming an unknown key triggers an early refresh (Supabase key rotation). Fetches
    happen at most once per `min_refresh_interval`, so a Supabase outage doesn't make every
    request wait on it: keys already fetched keep working, and with no keys at all requests
    fail fast with 503 auth_unavailable.
    """

    def __init__(
        self,
        url: str,
        http: httpx.AsyncClient,
        *,
        ttl: float,
        min_refresh_interval: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.url = url
        self.http = http
        self.ttl = ttl
        self.min_refresh_interval = min_refresh_interval
        self.clock = clock
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at: float | None = None
        self._attempted_at: float | None = None
        self._lock = asyncio.Lock()

    async def get(self, kid: str) -> jwt.PyJWK:
        stale = self._fetched_at is None or self.clock() - self._fetched_at >= self.ttl
        if (stale or kid not in self._keys) and self._may_fetch():
            await self._refresh()
        if not self._keys:
            raise AuthUnavailableError("Couldn't load the sign-in keys.")
        key = self._keys.get(kid)
        if key is None:
            raise InvalidTokenError("The token was signed with an unknown key.")
        return key

    def _may_fetch(self) -> bool:
        return (
            self._attempted_at is None
            or self.clock() - self._attempted_at >= self.min_refresh_interval
        )

    async def _refresh(self) -> None:
        async with self._lock:
            if not self._may_fetch():  # another request refreshed while we waited
                return
            self._attempted_at = self.clock()
            try:
                response = await self.http.get(self.url, timeout=JWKS_FETCH_TIMEOUT_SECONDS)
                response.raise_for_status()
                keys = self._parse(response.json())
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("jwks refresh failed", extra={"error": repr(exc)})
                return  # keep using the keys we have, if any
            if not keys:
                logger.warning("jwks has no usable asymmetric keys", extra={"url": self.url})
            self._keys = keys
            self._fetched_at = self.clock()
            logger.info("jwks refreshed", extra={"kids": sorted(keys)})

    @staticmethod
    def _parse(document: Any) -> dict[str, jwt.PyJWK]:
        keys: dict[str, jwt.PyJWK] = {}
        for entry in document.get("keys", []) if isinstance(document, dict) else []:
            if not isinstance(entry, dict) or entry.get("kty") not in _ALLOWED_KEY_TYPES:
                continue
            try:
                key = jwt.PyJWK(entry)
            except jwt.PyJWTError:
                continue
            if key.key_id and key.algorithm_name in ALLOWED_ALGORITHMS:
                keys[key.key_id] = key
        return keys


class SupabaseTokenVerifier:
    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        assert settings.supabase_issuer and settings.supabase_jwks_url
        self.issuer = settings.supabase_issuer
        self.audience = settings.supabase_jwt_audience
        self.leeway = settings.jwt_leeway_seconds
        self.jwks = JWKSCache(
            settings.supabase_jwks_url,
            http,
            ttl=settings.jwks_cache_seconds,
            min_refresh_interval=settings.jwks_min_refresh_interval_seconds,
        )

    async def verify(self, token: str) -> SupabaseClaims:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise InvalidTokenError("The access token is malformed.") from exc
        algorithm, kid = header.get("alg"), header.get("kid")
        if algorithm not in ALLOWED_ALGORITHMS or not isinstance(kid, str):
            raise InvalidTokenError("The access token uses an unsupported signing algorithm.")

        key = await self.jwks.get(kid)
        if key.algorithm_name != algorithm:
            raise InvalidTokenError("The token's algorithm doesn't match its key.")
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=[algorithm],
                audience=self.audience,
                issuer=self.issuer,
                leeway=self.leeway,
                options={"require": ["exp", "iat", "sub", "iss", "aud"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise TokenExpiredError("The access token has expired; refresh the session.") from exc
        except jwt.PyJWTError as exc:
            raise InvalidTokenError(f"The access token was rejected ({exc}).") from exc

        if claims.get("role") != "authenticated":
            raise InvalidTokenError("Only signed-in users can use this API.")
        if claims.get("is_anonymous") is True:
            raise InvalidTokenError("Anonymous sign-ins can't use Nodly.")
        try:
            user_id = uuid.UUID(str(claims["sub"]))
        except ValueError as exc:
            raise InvalidTokenError("The token's subject isn't a user id.") from exc
        email = claims.get("email")
        return SupabaseClaims(
            user_id=user_id,
            email=email if isinstance(email, str) and email else None,
            session_id=claims.get("session_id"),
            claims=claims,
        )
