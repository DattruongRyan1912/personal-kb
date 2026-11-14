"""Mint a short-lived Supabase-style user token for local testing of the API (decision 3 on #266).

It is signed HS256 with SUPABASE_JWT_SECRET, so it is accepted only by an API configured with that same secret: use a
local secret in ai/.env, never a real project's. Against a real project, sign in through the app and use its token.

Usage:  TOKEN=$(docker compose exec -T ai-backend python -m scripts.dev_token)
        curl -H "Authorization: Bearer $TOKEN" ...
"""

import argparse

from personal_kb.core.config import Settings, get_settings
from personal_kb.core.dev_tokens import DEV_EMAIL, DEV_USER_ID, mint_dev_token


def mint(settings: Settings, *, user_id: str, email: str | None, minutes: int) -> str:
    try:
        return mint_dev_token(settings, user_id=user_id, email=email, minutes=minutes)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--user-id", default=DEV_USER_ID)
    parser.add_argument("--email", default=DEV_EMAIL)
    parser.add_argument("--minutes", type=int, default=60)
    args = parser.parse_args()
    print(mint(get_settings(), user_id=args.user_id, email=args.email, minutes=args.minutes))
