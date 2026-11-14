"""Dev sign-in for the chat UI without a Supabase project (issue 3.2). Mounted only when DEV_LOGIN is on, which
settings allow only against a local Supabase URL and JWT secret."""

from fastapi import APIRouter, Request
from pydantic import BaseModel

from personal_kb.core.dev_tokens import mint_dev_token

router = APIRouter(prefix="/api/v1/dev", tags=["dev"])
TOKEN_MINUTES = 60


class DevToken(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


@router.post("/token")
async def dev_token(request: Request) -> DevToken:
    token = mint_dev_token(request.app.state.settings, minutes=TOKEN_MINUTES)
    return DevToken(access_token=token, expires_in=TOKEN_MINUTES * 60)
