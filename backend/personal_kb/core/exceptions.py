"""Errors the API maps to fixed responses, so callers can rely on status codes and error names."""

import logging

import openai
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from personal_kb.core.auth import AuthenticationError, unauthenticated_response

log = logging.getLogger(__name__)


class DependencyUnavailableError(Exception):
    """A backing service (Postgres, Redis, the re-ranker, the model API) cannot be reached."""

    def __init__(self, dependency: str, detail: str = "") -> None:
        super().__init__(f"{dependency} unavailable: {detail}".rstrip(": "))
        self.dependency = dependency


class CollectionMismatchError(Exception):
    """An existing vector collection does not match the configured embedding size."""


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AuthenticationError)
    async def unauthenticated(_: Request, exc: AuthenticationError) -> JSONResponse:
        return unauthenticated_response(exc)

    @app.exception_handler(CollectionMismatchError)
    async def collection_mismatch(_: Request, exc: CollectionMismatchError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"error": "COLLECTION_MISMATCH", "message": str(exc)})

    @app.exception_handler(DependencyUnavailableError)
    async def dependency_unavailable(_: Request, exc: DependencyUnavailableError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"error": f"{exc.dependency.upper()}_UNAVAILABLE", "message": str(exc)},
        )

    @app.exception_handler(RedisConnectionError)
    @app.exception_handler(RedisTimeoutError)
    async def redis_unavailable(_: Request, exc: Exception) -> JSONResponse:
        # the chat's session memory (issue 2.1): without it a turn can neither read its history nor be saved
        log.error("Redis unavailable: %s", type(exc).__name__)
        return JSONResponse(
            status_code=503, content={"error": "REDIS_UNAVAILABLE", "message": "the session memory is unavailable"}
        )

    @app.exception_handler(openai.APIError)
    async def openai_failed(_: Request, exc: openai.APIError) -> JSONResponse:
        # the upstream message can quote part of the API key: log the type and status only, never echo it
        log.error(
            "OpenAI call failed after retries: %s (status %s)", type(exc).__name__, getattr(exc, "status_code", "-")
        )
        return JSONResponse(
            status_code=503, content={"error": "OPENAI_UNAVAILABLE", "message": "the language model service failed"}
        )
