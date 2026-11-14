import asyncio

import httpx2
import openai
import pytest
from tenacity import wait_fixed

from personal_kb.services.openai_retry import call_with_retries, openai_retrying

_REQUEST = httpx2.Request("POST", "https://api.openai.com/v1/embeddings")


def flaky(failures: int):
    """A request that is rate-limited `failures` times, then answers; counts its attempts."""
    state = {"attempts": 0}

    async def request():
        state["attempts"] += 1
        await asyncio.sleep(0)
        if state["attempts"] <= failures:
            raise openai.RateLimitError("slow down", response=httpx2.Response(429, request=_REQUEST), body=None)
        return "ok"

    return request, state


async def test_concurrent_calls_sharing_one_policy_keep_separate_attempt_counts():
    retrying = openai_retrying(wait=wait_fixed(0.01), max_attempts=3)
    calls = [flaky(failures=2) for _ in range(5)]

    results = await asyncio.gather(*(call_with_retries(retrying, request) for request, _ in calls))

    assert results == ["ok"] * 5
    assert [state["attempts"] for _, state in calls] == [3] * 5


async def test_a_server_that_does_not_implement_the_feature_is_not_retried():
    attempts = {"n": 0}

    async def request():
        attempts["n"] += 1
        response = httpx2.Response(501, request=_REQUEST)
        raise openai.InternalServerError("structured output is unavailable", response=response, body=None)

    with pytest.raises(openai.InternalServerError):
        await call_with_retries(openai_retrying(wait=wait_fixed(0)), request)
    assert attempts["n"] == 1
