"""A stand-in for Supabase Auth: a real P-256 signing key, its JWKS served through a mocked
httpx transport, and tokens shaped like Supabase's (see docs/guides/auth/jwt-fields)."""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from jwt.algorithms import ECAlgorithm, RSAAlgorithm

TEST_SUPABASE_URL = "https://test-ref.supabase.co"
ISSUER = f"{TEST_SUPABASE_URL}/auth/v1"
JWKS_URL = f"{ISSUER}/.well-known/jwks.json"


def public_jwk(private_key: Any, kid: str) -> dict[str, Any]:
    if isinstance(private_key, rsa.RSAPrivateKey):
        data = RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
        alg = "RS256"
    else:
        data = ECAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
        alg = "ES256"
    return {**data, "kid": kid, "alg": alg, "use": "sig"}  # type: ignore[dict-item]


@dataclass
class FakeSupabase:
    signing_key: Any = field(default_factory=lambda: ec.generate_private_key(ec.SECP256R1()))
    kid: str = "kid-1"
    published: list[dict[str, Any]] = field(default_factory=list)
    jwks_requests: int = 0
    down: bool = False

    def __post_init__(self) -> None:
        if not self.published:
            self.published.append(public_jwk(self.signing_key, self.kid))

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if str(request.url) != JWKS_URL:
            return httpx.Response(404)
        self.jwks_requests += 1
        if self.down:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, json={"keys": self.published})

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def token(
        self,
        *,
        sub: uuid.UUID | str | None = None,
        email: str | None = "user@example.com",
        key: Any = None,
        kid: str | None = None,
        algorithm: str = "ES256",
        lifetime: int = 3600,
        **claims: Any,
    ) -> str:
        """A signed access token. Pass a claim as None to leave it out."""
        now = int(time.time())
        payload: dict[str, Any] = {
            "iss": ISSUER,
            "aud": "authenticated",
            "sub": str(sub or uuid.uuid4()),
            "role": "authenticated",
            "email": email,
            "phone": "",
            "aal": "aal1",
            "session_id": str(uuid.uuid4()),
            "is_anonymous": False,
            "iat": now,
            "exp": now + lifetime,
            **claims,
        }
        payload = {name: value for name, value in payload.items() if value is not None}
        return jwt.encode(
            payload, key or self.signing_key, algorithm=algorithm, headers={"kid": kid or self.kid}
        )


@dataclass
class SupabaseUser:
    """A person signed in to the fake Supabase; `headers` makes a fresh token each time."""

    supabase: FakeSupabase
    email: str
    auth_id: uuid.UUID = field(default_factory=uuid.uuid4)

    @property
    def headers(self) -> dict[str, str]:
        token = self.supabase.token(sub=self.auth_id, email=self.email)
        return {"Authorization": f"Bearer {token}"}
