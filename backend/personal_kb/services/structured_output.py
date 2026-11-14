"""One chat completion constrained to a Pydantic model through OpenAI Structured Outputs (strict JSON Schema)."""

import json
from typing import Any, TypeVar

import openai
from pydantic import BaseModel, ValidationError
from tenacity import AsyncRetrying

from personal_kb.services.openai_retry import call_with_retries

M = TypeVar("M", bound=BaseModel)


class InvalidModelOutput(Exception):
    """The model refused, or answered something that does not validate against the output model."""


def response_format(output_model: type[BaseModel], name: str) -> dict:
    return {
        "type": "json_schema",
        "json_schema": {"name": name, "strict": True, "schema": output_model.model_json_schema()},
    }


async def structured_completion(
    client: Any,
    retrying: AsyncRetrying,
    *,
    model: str,
    system: str,
    user: str,
    output_model: type[M],
    name: str,
    reasoning_effort: str | None = None,
) -> M:
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    params = {"model": model, "temperature": 0, "response_format": response_format(output_model, name)}
    if reasoning_effort:  # only when configured: "none" turns thinking off on Ollama; gpt-4o-mini refuses the field
        params["reasoning_effort"] = reasoning_effort
    try:
        completion = await call_with_retries(
            retrying, lambda: client.chat.completions.create(messages=messages, **params)
        )
    except openai.BadRequestError as exc:
        if "response_format" in str(exc) or "unavailable" in str(exc):
            fallback_params = dict(params)
            fallback_params["response_format"] = {"type": "json_object"}
            schema_json = json.dumps(output_model.model_json_schema())
            fallback_prompt = (
                f"{system}\n\nStrict output requirement: Output a single valid JSON object "
                f"strictly matching this schema: {schema_json}"
            )
            fallback_messages = [{"role": "system", "content": fallback_prompt}, {"role": "user", "content": user}]
            completion = await call_with_retries(
                retrying,
                lambda: client.chat.completions.create(messages=fallback_messages, **fallback_params),
            )
        else:
            raise
    message = completion.choices[0].message
    if getattr(message, "refusal", None):
        raise InvalidModelOutput(f"the model refused ({message.refusal})")
    try:
        return output_model.model_validate_json(message.content or "")
    except ValidationError as exc:
        raise InvalidModelOutput(f"invalid output ({exc.error_count()} errors)") from exc
