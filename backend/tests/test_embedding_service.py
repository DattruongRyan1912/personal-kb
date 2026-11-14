from types import SimpleNamespace

import httpx2
import openai
import pytest
from tenacity import wait_none

from personal_kb.services.embedding import EmbeddingService

_REQUEST = httpx2.Request("POST", "https://api.openai.com/v1/embeddings")


def rate_limited() -> openai.RateLimitError:
    return openai.RateLimitError("rate limited", response=httpx2.Response(429, request=_REQUEST), body=None)


def bad_request() -> openai.BadRequestError:
    return openai.BadRequestError("bad input", response=httpx2.Response(400, request=_REQUEST), body=None)


class FakeEmbeddingsAPI:
    """Stands in for `AsyncOpenAI().embeddings`: fails with the queued errors, then answers."""

    def __init__(self, errors=(), wrong_size=False):
        self.errors = list(errors)
        self.wrong_size = wrong_size
        self.calls = []

    def create(self, **kwargs):
        # like the real SDK: a plain method that returns a coroutine, not an `async def`
        return self._create(**kwargs)

    async def _create(self, *, input, model):
        self.calls.append({"input": list(input), "model": model})
        if self.errors:
            raise self.errors.pop(0)
        # the API returns items carrying their input index; return them out of order on purpose
        items = [SimpleNamespace(index=i, embedding=[float(i), float(len(text))]) for i, text in enumerate(input)]
        if self.wrong_size:
            items[0].embedding = [0.0, 0.0, 0.0]
        return SimpleNamespace(data=list(reversed(items)))


def service(api: FakeEmbeddingsAPI, **kw) -> EmbeddingService:
    return EmbeddingService(
        SimpleNamespace(embeddings=api), model="text-embedding-3-small", dimensions=2, wait=wait_none(), **kw
    )


async def test_embed_returns_one_vector_per_text_in_input_order():
    api = FakeEmbeddingsAPI()

    vectors = await service(api).embed(["a", "bb", "ccc"])

    assert vectors == [[0.0, 1.0], [1.0, 2.0], [2.0, 3.0]]
    # no `dimensions` parameter: local OpenAI-compatible servers (Ollama, LM Studio) do not accept it
    assert api.calls == [{"input": ["a", "bb", "ccc"], "model": "text-embedding-3-small"}]


async def test_a_vector_of_the_wrong_size_is_refused_with_a_clear_message():
    with pytest.raises(ValueError, match="3 dimensions.*EMBEDDING_DIMENSIONS is 2"):
        await service(FakeEmbeddingsAPI(wrong_size=True)).embed(["a", "b"])


async def test_embed_retries_rate_limit_then_succeeds():
    api = FakeEmbeddingsAPI(errors=[rate_limited(), rate_limited()])

    vectors = await service(api).embed(["a"])

    assert vectors == [[0.0, 1.0]]
    assert len(api.calls) == 3


async def test_embed_gives_up_after_max_attempts():
    api = FakeEmbeddingsAPI(errors=[rate_limited()] * 5)

    with pytest.raises(openai.RateLimitError):
        await service(api, max_attempts=3).embed(["a"])
    assert len(api.calls) == 3


async def test_embed_does_not_retry_a_bad_request():
    api = FakeEmbeddingsAPI(errors=[bad_request()])

    with pytest.raises(openai.BadRequestError):
        await service(api).embed(["a"])
    assert len(api.calls) == 1


async def test_embed_of_nothing_makes_no_call():
    api = FakeEmbeddingsAPI()

    assert await service(api).embed([]) == []
    assert api.calls == []


async def test_embed_retries_a_transient_server_error():
    server_error = openai.InternalServerError("upstream", response=httpx2.Response(500, request=_REQUEST), body=None)
    api = FakeEmbeddingsAPI(errors=[server_error])

    assert await service(api).embed(["a"]) == [[0.0, 1.0]]
    assert len(api.calls) == 2
