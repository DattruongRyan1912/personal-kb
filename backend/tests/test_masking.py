from collections.abc import Mapping

from personal_kb.core.masking import make_mask

# fake secrets built by concatenation, so no secret scanner mistakes them for real ones
OPENAI_KEY = "sk-" + "proj-" + "a1B2" * 10
LANGFUSE_KEY = "sk-" + "lf-" + "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0"
JWT = "eyJ" + "hbGciOiJIUzI1NiJ9" + "." + "eyJzdWIiOiJ1In0" + "." + "c2lnbmF0dXJlLXNpZ24"


def test_keys_tokens_env_lines_and_url_credentials_are_masked_in_text():
    text = (
        f"key {OPENAI_KEY}, lf {LANGFUSE_KEY}, Authorization: Bearer {JWT}\n"
        f"NEO4J_PASSWORD=hunter2-secret\nOPENAI_API_KEY: '{OPENAI_KEY}'\n"
        "postgres://admin:pa55word@db:5432/x"
    )

    out = make_mask([])(data=text)

    for secret in (OPENAI_KEY, LANGFUSE_KEY, JWT, "hunter2-secret", "pa55word"):
        assert secret not in out
    assert "NEO4J_PASSWORD=***" in out and "postgres://admin:***@db:5432/x" in out


def test_a_vietnamese_password_and_a_url_password_without_user_are_masked():
    text = "mật khẩu: Hunter2024!\nMật khẩu = abc12345\nredis://:r3dis-pass@memory-redis:6379/0"

    out = make_mask([])(data=text)

    for secret in ("Hunter2024!", "abc12345", "r3dis-pass"):
        assert secret not in out
    assert "redis://:***@memory-redis:6379/0" in out


def test_values_under_secret_key_names_are_masked():
    data = {"secret_key": "a" * 10, "jwt_secret_key": "b" * 10, "service_role_key": "c" * 10, "partition_key": "d"}

    out = make_mask([])(data=data)

    assert out == {"secret_key": "***", "jwt_secret_key": "***", "service_role_key": "***", "partition_key": "d"}


def test_values_under_secret_keys_are_masked_but_token_counts_are_kept():
    data = {
        "password": "x",
        "access_token": "y",
        "headers": {"Authorization": "Basic z"},
        "usage": {"prompt_tokens": 12, "max_tokens": 50},
        "spec_id": "SPC-1",
    }

    out = make_mask([])(data=data)

    assert out["password"] == "***" and out["access_token"] == "***" and out["headers"]["Authorization"] == "***"
    assert out["usage"] == {"prompt_tokens": 12, "max_tokens": 50} and out["spec_id"] == "SPC-1"


def test_this_deployments_own_secrets_are_masked_wherever_they_appear():
    out = make_mask(["n3o4j-pass-123", "short", None])(data=["ok", ("the n3o4j-pass-123 leaked", {"note": "short"})])

    assert out == ["ok", ("the *** leaked", {"note": "short"})]  # a value under 8 characters is too common to mask


def test_spec_text_is_left_alone():
    spec = "Refresh token (sống 7 ngày) lưu trong cookie HttpOnly; mật khẩu băm Argon2id; 401 INVALID_CREDENTIALS."

    assert make_mask([])(data=spec) == spec


def test_the_mask_never_raises():
    class Broken(Mapping):
        def __getitem__(self, key):
            raise RuntimeError

        def __iter__(self):
            raise RuntimeError

        def __len__(self):
            return 1

    mask = make_mask([])

    assert mask(data=Broken()) == "[masked]"
    assert mask(data=42) == 42
