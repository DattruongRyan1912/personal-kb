import pytest

from personal_kb.core.auth import SupabaseJwtVerifier
from scripts.dev_token import mint
from tests.conftest import JWT_SECRET, SUPABASE_URL, make_settings


async def test_a_dev_token_is_accepted_by_an_api_with_the_same_secret():
    token = mint(make_settings(), user_id="dev-user", email="dev@example.com", minutes=5)

    user = await SupabaseJwtVerifier(supabase_url=SUPABASE_URL, jwt_secret=JWT_SECRET).verify(token)

    assert (user.id, user.email) == ("dev-user", "dev@example.com")


def test_no_dev_token_without_a_local_jwt_secret():
    with pytest.raises(SystemExit, match="SUPABASE_JWT_SECRET"):
        mint(make_settings(supabase_jwt_secret=None), user_id="u", email=None, minutes=5)
