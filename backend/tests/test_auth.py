import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from jwt import PyJWK

from personal_kb.core.auth import AuthenticationError, SupabaseJwtVerifier

SUPABASE_URL = "https://project.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"
SECRET = "test-jwt-secret-at-least-32-bytes-long!!"
EC_KEY = ec.generate_private_key(ec.SECP256R1())


class FakeJwks:
    """Stands in for PyJWKClient: the project's published public key."""

    def get_signing_key_from_jwt(self, token):
        return PyJWK.from_dict(
            {**jwt.algorithms.ECAlgorithm.to_jwk(EC_KEY.public_key(), as_dict=True), "alg": "ES256", "kid": "k1"}
        )


def claims(**overrides) -> dict:
    now = int(time.time())
    return {
        "sub": "7b1e0000-0000-4000-8000-000000000001",
        "email": "an.nguyen@example.com",
        "role": "authenticated",
        "aud": "authenticated",
        "iss": ISSUER,
        "iat": now,
        "exp": now + 3600,
    } | overrides


def es256(**overrides) -> str:
    return jwt.encode(claims(**overrides), EC_KEY, algorithm="ES256", headers={"kid": "k1"})


def hs256(secret=SECRET, **overrides) -> str:
    return jwt.encode(claims(**overrides), secret, algorithm="HS256")


def verifier(secret: str | None = SECRET) -> SupabaseJwtVerifier:
    return SupabaseJwtVerifier(supabase_url=SUPABASE_URL, jwt_secret=secret, jwks_client=FakeJwks())


async def test_an_asymmetric_token_is_verified_against_the_projects_jwks():
    user = await verifier(secret=None).verify(es256())

    assert user.id == "7b1e0000-0000-4000-8000-000000000001"
    assert user.email == "an.nguyen@example.com"


async def test_a_legacy_hs256_token_is_verified_with_the_jwt_secret():
    assert (await verifier().verify(hs256())).id.startswith("7b1e")


@pytest.mark.parametrize(
    ("make_token", "reason"),
    [
        (lambda: es256(exp=int(time.time()) - 10), "expired"),
        (lambda: es256(aud="anon"), "anon key style audience"),
        (lambda: hs256(aud=None, role="service_role"), "service role key style token"),
        (lambda: es256(iss="https://other.supabase.co/auth/v1"), "another project"),
        (lambda: hs256(secret="another-secret-that-is-also-32-bytes!!"), "wrong secret"),
        (lambda: es256()[:-4] + "AAAA", "tampered signature"),
        (lambda: jwt.encode(claims(), None, algorithm="none"), "unsigned"),
        (lambda: "not-a-jwt", "garbage"),
        (lambda: es256(sub=None), "no subject"),
    ],
)
async def test_bad_tokens_are_refused(make_token, reason):
    with pytest.raises(AuthenticationError):
        await verifier().verify(make_token())


async def test_an_hs256_token_is_refused_when_no_secret_is_configured():
    with pytest.raises(AuthenticationError, match="SUPABASE_JWT_SECRET"):
        await verifier(secret=None).verify(hs256())


async def test_a_unique_token_id_does_not_matter():
    assert await verifier().verify(hs256(jti=str(uuid.uuid4())))
