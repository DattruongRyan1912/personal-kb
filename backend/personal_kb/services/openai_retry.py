"""One retry policy for OpenAI calls: exponential backoff on rate limits and transient errors.

Clients are built with max_retries=0, so this is the only retry layer.
"""

from collections.abc import Awaitable, Callable
from typing import TypeVar

import openai
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_random_exponential
from tenacity.wait import wait_base

RETRYABLE = (openai.RateLimitError, openai.APITimeoutError, openai.APIConnectionError, openai.InternalServerError)


def is_transient(exc: BaseException) -> bool:
    # 501: the server does not implement the request (a local model without structured output); retrying cannot help
    return isinstance(exc, RETRYABLE) and getattr(exc, "status_code", None) != 501


T = TypeVar("T")


def _caused_by_transient(exc: BaseException | None) -> bool:
    """A transient error, or an error raised from one: a library between us and the SDK may wrap it (Ragas calls its
    judge through instructor, which re-raises an OpenAI rate limit as its own exception)."""
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        if is_transient(exc):
            return True
        seen.add(id(exc))
        exc = exc.__cause__
    return False


def openai_retrying(
    wait: wait_base | None = None, max_attempts: int = 6, *, through_wrappers: bool = False
) -> AsyncRetrying:
    return AsyncRetrying(
        retry=retry_if_exception(_caused_by_transient if through_wrappers else is_transient),
        wait=wait or wait_random_exponential(multiplier=1, max=30),
        stop=stop_after_attempt(max_attempts),
        reraise=True,
    )


async def call_with_retries(retrying: AsyncRetrying, request: Callable[[], Awaitable[T]]) -> T:
    """Await `request()` under the retry policy.

    SDK methods such as `chat.completions.create` are plain functions returning a coroutine; handed to tenacity
    directly, the coroutine would come back un-awaited. Awaiting inside the attempt avoids that. Each call iterates a
    copy of the policy: iterating keeps the attempt state on the instance, which concurrent calls would share.
    """
    async for attempt in retrying.copy():
        with attempt:
            result = await request()
    return result
