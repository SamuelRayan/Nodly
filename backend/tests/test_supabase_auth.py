"""Supabase access-token verification and the JWKS cache."""

import base64
import hashlib
import hmac
import json
import time
import uuid
from collections.abc import AsyncIterator

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from nodly.auth.supabase import (
    AuthUnavailableError,
    InvalidTokenError,
    JWKSCache,
    SupabaseTokenVerifier,
    TokenExpiredError,
)
from nodly.config import Settings
from tests.fake_supabase import ISSUER, JWKS_URL, FakeSupabase, public_jwk


@pytest.fixture
async def verifier(
    settings: Settings, fake_supabase: FakeSupabase
) -> AsyncIterator[SupabaseTokenVerifier]:
    async with httpx.AsyncClient(transport=fake_supabase.transport()) as http:
        yield SupabaseTokenVerifier(settings, http)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


# ---------------------------------------------------------------- accepted


async def test_valid_token(verifier: SupabaseTokenVerifier, fake_supabase: FakeSupabase) -> None:
    user_id = uuid.uuid4()
    claims = await verifier.verify(fake_supabase.token(sub=user_id, email="priya@example.com"))
    assert (claims.user_id, claims.email) == (user_id, "priya@example.com")


async def test_rs256_keys_work_too(settings: Settings) -> None:
    supabase = FakeSupabase(signing_key=rsa.generate_private_key(65537, 2048), kid="rsa-1")
    async with httpx.AsyncClient(transport=supabase.transport()) as http:
        verifier = SupabaseTokenVerifier(settings, http)
        claims = await verifier.verify(supabase.token(algorithm="RS256"))
    assert claims.email == "user@example.com"


async def test_small_clock_skew_is_tolerated(
    verifier: SupabaseTokenVerifier, fake_supabase: FakeSupabase
) -> None:
    await verifier.verify(fake_supabase.token(iat=int(time.time()) + 10))


# ---------------------------------------------------------------- rejected


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _forge(fake_supabase: FakeSupabase, alg: str) -> tuple[str, str]:
    """Header and payload segments of a valid-looking token with a chosen `alg`."""
    payload = jwt.decode(fake_supabase.token(), options={"verify_signature": False})
    header = {"alg": alg, "kid": fake_supabase.kid, "typ": "JWT"}
    return _b64(json.dumps(header).encode()), _b64(json.dumps(payload).encode())


def forged_alg_none(fake_supabase: FakeSupabase) -> str:
    header, payload = _forge(fake_supabase, "none")
    return f"{header}.{payload}."


def forged_hs256_with_public_key(fake_supabase: FakeSupabase) -> str:
    """The classic confusion attack: HMAC-sign with the (public) verification key. Built by
    hand because PyJWT itself refuses to produce it."""
    public_pem = fake_supabase.signing_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    header, payload = _forge(fake_supabase, "HS256")
    signature = hmac.new(public_pem, f"{header}.{payload}".encode(), hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64(signature)}"


@pytest.mark.parametrize(
    ("make_token", "error"),
    [
        (lambda s: s.token(lifetime=-120), TokenExpiredError),
        (lambda s: s.token(iat=int(time.time()) + 600), InvalidTokenError),  # issued in the future
        (lambda s: s.token(iss="https://other.supabase.co/auth/v1"), InvalidTokenError),
        (lambda s: s.token(aud="anon"), InvalidTokenError),
        (lambda s: s.token(role="anon"), InvalidTokenError),
        (lambda s: s.token(role="service_role"), InvalidTokenError),
        (lambda s: s.token(is_anonymous=True), InvalidTokenError),
        (lambda s: s.token(sub="not-a-uuid"), InvalidTokenError),
        (lambda s: s.token(exp=None), InvalidTokenError),
        (lambda s: s.token(iat=None), InvalidTokenError),
        (lambda s: s.token(key=ec.generate_private_key(ec.SECP256R1())), InvalidTokenError),
        (lambda s: s.token(kid="unknown-kid"), InvalidTokenError),
        (forged_alg_none, InvalidTokenError),
        (forged_hs256_with_public_key, InvalidTokenError),
        (lambda s: "not.a.jwt", InvalidTokenError),
        (lambda s: "garbage", InvalidTokenError),
    ],
    ids=[
        "expired",
        "future-iat",
        "wrong-issuer",
        "wrong-audience",
        "anon-role",
        "service-role",
        "anonymous-user",
        "bad-sub",
        "no-exp",
        "no-iat",
        "wrong-key",
        "unknown-kid",
        "alg-none",
        "hs256-confusion",
        "malformed",
        "garbage",
    ],
)
async def test_rejected_tokens(
    verifier: SupabaseTokenVerifier, fake_supabase: FakeSupabase, make_token, error
) -> None:
    with pytest.raises(error):
        await verifier.verify(make_token(fake_supabase))


# ---------------------------------------------------------------- JWKS cache


def cache_for(supabase: FakeSupabase, http: httpx.AsyncClient, clock: Clock) -> JWKSCache:
    return JWKSCache(JWKS_URL, http, ttl=600, min_refresh_interval=30, clock=clock)


async def test_keys_are_cached_until_the_ttl(fake_supabase: FakeSupabase) -> None:
    clock = Clock()
    async with httpx.AsyncClient(transport=fake_supabase.transport()) as http:
        cache = cache_for(fake_supabase, http, clock)
        for _ in range(5):
            await cache.get(fake_supabase.kid)
        assert fake_supabase.jwks_requests == 1
        clock.now += 600
        await cache.get(fake_supabase.kid)
        assert fake_supabase.jwks_requests == 2


async def test_rotated_in_key_is_fetched_early_but_not_too_often(
    fake_supabase: FakeSupabase,
) -> None:
    clock = Clock()
    async with httpx.AsyncClient(transport=fake_supabase.transport()) as http:
        cache = cache_for(fake_supabase, http, clock)
        await cache.get(fake_supabase.kid)

        new_key = ec.generate_private_key(ec.SECP256R1())
        fake_supabase.published.append(public_jwk(new_key, "kid-2"))
        clock.now += 31
        await cache.get("kid-2")  # unknown -> early refresh finds it
        assert fake_supabase.jwks_requests == 2

        with pytest.raises(InvalidTokenError):
            await cache.get("kid-3")  # unknown again, within 30s: no refetch
        assert fake_supabase.jwks_requests == 2


async def test_outage_keeps_cached_keys(fake_supabase: FakeSupabase) -> None:
    clock = Clock()
    async with httpx.AsyncClient(transport=fake_supabase.transport()) as http:
        cache = cache_for(fake_supabase, http, clock)
        await cache.get(fake_supabase.kid)
        fake_supabase.down = True
        clock.now += 700  # past the TTL
        assert await cache.get(fake_supabase.kid)  # stale but usable
        assert await cache.get(fake_supabase.kid)  # and no retry storm
        assert fake_supabase.jwks_requests == 2


async def test_outage_without_keys_is_503(fake_supabase: FakeSupabase) -> None:
    fake_supabase.down = True
    async with httpx.AsyncClient(transport=fake_supabase.transport()) as http:
        cache = cache_for(fake_supabase, http, Clock())
        with pytest.raises(AuthUnavailableError):
            await cache.get(fake_supabase.kid)


async def test_symmetric_keys_in_the_jwks_are_ignored(fake_supabase: FakeSupabase) -> None:
    fake_supabase.published[:] = [{"kty": "oct", "kid": "legacy", "k": "c2VjcmV0", "alg": "HS256"}]
    async with httpx.AsyncClient(transport=fake_supabase.transport()) as http:
        cache = cache_for(fake_supabase, http, Clock())
        with pytest.raises(AuthUnavailableError):
            await cache.get("legacy")


def test_issuer_and_jwks_url_come_from_the_project_url(settings: Settings) -> None:
    assert settings.supabase_issuer == ISSUER
    assert settings.supabase_jwks_url == JWKS_URL
