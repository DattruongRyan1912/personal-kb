"""Supabase Auth access tokens (decision 3 on #266): every API call carries the user's Supabase JWT.

Projects on asymmetric signing keys publish them at {SUPABASE_URL}/auth/v1/.well-known/jwks.json (ES256, RS256);
projects on the legacy JWT secret sign HS256 and publish nothing, so that secret (SUPABASE_JWT_SECRET) is needed.
The algorithm only selects which allow-listed key to use; an HS256 token is never checked against a public key.
Only user sessions pass: the audience must be "authenticated", which the anon and service-role keys are not.
"""

import asyncio
from dataclasses import dataclass
from typing import Annotated, Any

import jwt
from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

ASYMMETRIC_ALGORITHMS = {"ES256", "RS256", "EdDSA"}
AUDIENCE = "authenticated"


class AuthenticationError(Exception):
    """The request carries no valid Supabase user token."""


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str | None


class SupabaseJwtVerifier:
    def __init__(self, *, supabase_url: str, jwt_secret: str | None, jwks_client: Any | None = None) -> None:
        self._issuer = f"{supabase_url.rstrip('/')}/auth/v1"
        self._secret = jwt_secret
        self._jwks = jwks_client or jwt.PyJWKClient(f"{self._issuer}/.well-known/jwks.json", lifespan=600)

    async def verify(self, token: str) -> CurrentUser:
        try:
            algorithm = jwt.get_unverified_header(token).get("alg")
            if algorithm == "HS256":
                if not self._secret:
                    raise AuthenticationError("HS256 tokens need SUPABASE_JWT_SECRET, which is not set")
                key: Any = self._secret
            elif algorithm in ASYMMETRIC_ALGORITHMS:
                # PyJWKClient fetches (and caches) the key set over blocking HTTP: keep it off the event loop
                key = (await asyncio.to_thread(self._jwks.get_signing_key_from_jwt, token)).key
            else:
                raise AuthenticationError(f"unsupported token algorithm {algorithm!r}")
            claims = jwt.decode(
                token,
                key,
                algorithms=[algorithm],
                audience=AUDIENCE,
                issuer=self._issuer,
                options={"require": ["exp", "sub", "aud", "iss"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationError(f"invalid token: {exc}") from exc
        return CurrentUser(id=claims["sub"], email=claims.get("email"))


_bearer = HTTPBearer(auto_error=False, description="Supabase access token of the signed-in user")


async def current_user(
    request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
) -> CurrentUser:
    if credentials is None:
        raise AuthenticationError("missing bearer token")
    return await request.app.state.auth.verify(credentials.credentials)


def unauthenticated_response(exc: AuthenticationError) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"error": "UNAUTHENTICATED", "message": str(exc)},
        headers={"WWW-Authenticate": "Bearer"},
    )
