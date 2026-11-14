"""The contract every agent tool follows (issue 2.2).

A tool declares `name`, `description` (at least 10 words: the model decides from it when to call the tool) and
`args_schema`; a missing or terse description fails pydantic validation when the app starts. `execute()` never raises:
bad arguments, an unreachable store, a timeout or a bug come back as text starting with "Lỗi:", which the agent reads
and turns into an answer, so one failing tool never crashes a chat.
"""

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from personal_kb.core.exceptions import DependencyUnavailableError

log = logging.getLogger(__name__)

MIN_DESCRIPTION_WORDS = 10


@dataclass(frozen=True)
class ToolContext:
    """Services a tool may use, injected per call."""

    retriever: Any  # services.retrieval.HybridRetriever
    documents: Any  # services.memory_ports.DocumentStore
    worklog: Any = None  # services.worklog.WorklogStore; None on backends without one
    projects: frozenset[str] = frozenset()  # project names of the project map


class BaseAgentTool(BaseModel):
    # validate_default: tools declare name and description as class defaults, which pydantic skips otherwise
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True, validate_default=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    description: str
    args_schema: type[BaseModel]
    timeout_seconds: float = 30
    # what the chat shows while the tool runs (issue 3.1); {argument} placeholders are filled from the call
    status: str = "⚙️ Đang chạy công cụ {tool}..."

    @field_validator("description")
    @classmethod
    def _enough_words(cls, value: str) -> str:
        if len(value.split()) < MIN_DESCRIPTION_WORDS:
            raise ValueError(
                f"a tool description needs at least {MIN_DESCRIPTION_WORDS} words: the model reads it to decide "
                "when to call the tool"
            )
        return value

    async def run(self, args: Any, ctx: ToolContext) -> str:
        raise NotImplementedError

    def status_text(self, args: dict) -> str:
        """The status with the call's arguments filled in; a placeholder the call lacks is left empty."""
        values = defaultdict(str, {k: v for k, v in args.items() if isinstance(v, str | int | float)}, tool=self.name)
        return self.status.format_map(values)

    async def execute(self, raw_args: dict, ctx: ToolContext) -> str:
        try:
            args = self.args_schema.model_validate(raw_args)
        except ValidationError as exc:
            first = exc.errors()[0]
            where = ".".join(str(p) for p in first["loc"]) or "arguments"
            return f"Lỗi: tham số không hợp lệ cho {self.name} ({where}: {first['msg']}). Hãy gọi lại với tham số đúng."
        try:
            return await asyncio.wait_for(self.run(args, ctx), timeout=self.timeout_seconds)
        except DependencyUnavailableError as exc:
            log.warning("[Tool %s] %s unavailable: %s", self.name, exc.dependency, exc)
            return (
                f"Lỗi: hiện không kết nối được kho dữ liệu SDD ({exc.dependency}). Hãy báo người dùng rằng hệ thống "
                "tra cứu tạm thời không khả dụng và thử lại sau."
            )
        except TimeoutError:
            log.warning("[Tool %s] timed out after %s s", self.name, self.timeout_seconds)
            return (
                f"Lỗi: công cụ {self.name} chạy quá thời gian ({self.timeout_seconds:g} s). "
                "Hãy báo người dùng thử lại sau."
            )
        except Exception:
            log.exception("[Tool %s] failed", self.name)
            return f"Lỗi: công cụ {self.name} gặp sự cố nội bộ. Hãy báo người dùng thử lại sau."
