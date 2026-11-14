"""Supabase-style user tokens signed with the local SUPABASE_JWT_SECRET, for development only (decision 3 on #266).

An API configured with that same secret accepts them. Use a local secret, never a real project's: settings refuse
DEV_LOGIN unless SUPABASE_URL is local.
"""

import time
import uuid

import jwt

from personal_kb.core.auth import AUDIENCE
from personal_kb.core.config import Settings

DEV_USER_ID = str(uuid.UUID(int=1))
DEV_EMAIL = "dev@example.com"


def mint_dev_token(
    settings: Settings, *, user_id: str = DEV_USER_ID, email: str | None = DEV_EMAIL, minutes: int = 60
) -> str:
    if settings.supabase_jwt_secret is None:
        raise ValueError("SUPABASE_JWT_SECRET is not set: dev tokens need a local JWT secret")
    now = int(time.time())
    claims = {
        "sub": user_id,
        "email": email,
        "role": "authenticated",
        "aud": AUDIENCE,
        "iss": f"{settings.supabase_url.rstrip('/')}/auth/v1",
        "iat": now,
        "exp": now + minutes * 60,
    }
    return jwt.encode(claims, settings.supabase_jwt_secret.get_secret_value(), algorithm="HS256")
