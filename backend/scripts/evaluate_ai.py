"""Evaluate the agent on the golden dataset with Ragas (issue 4.2): is a change smarter or dumber than before?

Usage (from ai/backend, the dev stack up and the specs ingested):
  uv run --group eval --env-file ../.env python scripts/evaluate_ai.py [--limit N] [--dataset CSV] [--output CSV]

Each question of qa_golden_dataset.csv (Question, Expected_Answer_Logic, Source_Spec_ID) is answered in-process by the
chat agent, from scratch and without a session; the contexts are what its tools returned (search results one by one,
specs read whole). A judge model then scores, from 0.0 to 1.0:
- Context Precision: are the relevant contexts among those retrieved, ranked first? (against the expected logic)
- Faithfulness: is every claim of the answer backed by the contexts, nothing invented?

The judge is set by EVAL_LLM_MODEL (default gpt-4o-mini), EVAL_BASE_URL (empty: OpenAI), EVAL_API_KEY (empty:
OPENAI_API_KEY), EVAL_REASONING_EFFORT ("none" turns qwen3's thinking off), EVAL_MAX_TOKENS, EVAL_DELAY_SECONDS.
Questions run one at a time; rate limits and transient errors are retried with backoff. The report goes to
evaluation_report.csv; the summary to the terminal. Exit code 0 when the means pass Context Precision > 0.85 and
Faithfulness > 0.90 with every question scored, 1 otherwise, 2 when the dataset or the setup is wrong.
"""

import argparse
import asyncio
import csv
import itertools
import logging
import math
import re
import sys
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

if __package__ in (None, ""):  # run as `python scripts/evaluate_ai.py`, not only with -m
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.messages import BaseMessage, ToolMessage  # noqa: E402
from pydantic import SecretStr, field_validator  # noqa: E402
from pydantic_settings import BaseSettings, SettingsConfigDict  # noqa: E402
from tenacity.wait import wait_base  # noqa: E402

from personal_kb.services.citations import NOT_EVIDENCE  # noqa: E402
from personal_kb.services.openai_retry import call_with_retries, openai_retrying  # noqa: E402

log = logging.getLogger("evaluate_ai")

BACKEND = Path(__file__).resolve().parents[1]
COLUMNS = ("Question", "Expected_Answer_Logic", "Source_Spec_ID")
MIN_PRECISION, MIN_FAITHFULNESS = 0.85, 0.90
_SEARCH_RESULT = re.compile(r"^(?=\[\d+\] \()", re.MULTILINE)  # "[1] (SPC-3 «…», graph, 0.79)" starts a result


class DatasetError(ValueError):
    pass


@dataclass(frozen=True)
class Question:
    question: str
    expected: str  # the facts a right answer states, written from the specs
    spec_ids: list[str]


@dataclass
class Result:
    question: Question
    answer: str = ""
    contexts: list[str] = field(default_factory=list)
    context_precision: float | None = None
    faithfulness: float | None = None
    latency_s: float = 0.0
    error: str = ""


class Judge(Protocol):
    async def context_precision(self, question: str, reference: str, contexts: list[str]) -> float: ...

    async def faithfulness(self, question: str, answer: str, contexts: list[str]) -> float: ...


def load_dataset(path: Path) -> list[Question]:
    """The golden dataset; a file saved from Excel (UTF-8 with BOM) reads the same. Several spec ids: SPC-1;SPC-5."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise DatasetError(f"{path}: thiếu cột {', '.join(missing)} (cần {', '.join(COLUMNS)})")
        questions = []
        for line, row in enumerate(reader, start=2):
            values = {c: (row.get(c) or "").strip() for c in COLUMNS}
            if not all(values.values()):
                raise DatasetError(f"{path}:{line}: ô trống")
            ids = [i.strip() for i in re.split(r"[;,]", values["Source_Spec_ID"]) if i.strip()]
            questions.append(Question(values["Question"], values["Expected_Answer_Logic"], ids))
    if not 30 <= len(questions) <= 50:
        log.warning("%s has %d questions; the issue asks for 30 to 50", path, len(questions))
    return questions


def contexts_of(messages: Sequence[BaseMessage]) -> list[str]:
    """What the agent's tools returned: each search result, each spec read whole. Not the catalog (it lists specs,
    it does not say what they contain) nor errors and "not found" answers."""
    contexts: list[str] = []
    for message in messages:
        if not isinstance(message, ToolMessage) or message.name in NOT_EVIDENCE:
            continue
        text = str(message.content).strip()
        if not text or text.startswith(("Lỗi:", "Không tìm thấy")):
            continue
        if _SEARCH_RESULT.search(text):
            contexts += [part.strip() for part in _SEARCH_RESULT.split(text)[1:] if part.strip()]
        else:
            contexts.append(text)
    return contexts


async def retried(request: Callable[[], Awaitable[Any]], wait: wait_base | None = None) -> Any:
    """A judge call under the OpenAI retry policy: backoff on rate limits and transient errors, also when Ragas'
    instructor layer wraps them."""
    return await call_with_retries(openai_retrying(wait=wait, through_wrappers=True), request)


def _score(value: Any) -> float:
    score = float(value)
    if math.isnan(score):
        raise ValueError("the judge returned no score")
    return score


async def evaluate(
    questions: Sequence[Question],
    answer: Callable[[str], Awaitable[tuple[str, list[str]]]],
    judge: Judge,
    delay: float = 0.0,
    output_path: Path | None = None,
) -> list[Result]:
    """Answers and scores the questions one at a time; a question that fails is reported, not scored."""
    results = []
    file_handle = None
    csv_writer = None
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        file_handle = open(output_path, "w", encoding="utf-8-sig", newline="")  # noqa: ASYNC230
        csv_writer = csv.writer(file_handle)
        csv_writer.writerow(
            [
                "Question",
                "Source_Spec_ID",
                "Context_Precision",
                "Faithfulness",
                "Answer",
                "Contexts",
                "Latency_s",
                "Error",
            ]
        )
        file_handle.flush()

    try:
        for n, question in enumerate(questions, start=1):
            if n > 1 and delay:
                await asyncio.sleep(delay)
            result, started = Result(question), time.perf_counter()
            try:
                result.answer, result.contexts = await answer(question.question)
                result.latency_s = time.perf_counter() - started
                if not result.contexts:
                    raise ValueError("no context: the agent's tools returned nothing to judge against")
                result.context_precision = _score(
                    await judge.context_precision(question.question, question.expected, result.contexts)
                )
                faithfulness = await judge.faithfulness(question.question, result.answer, result.contexts)
                result.faithfulness = _score(faithfulness)
            except Exception as error:
                result.context_precision = result.faithfulness = None
                result.error = f"{type(error).__name__}: {error}"
            log.info(
                "[%d/%d] CP %s  F %s  %.0f s  %s%s",
                n,
                len(questions),
                _fmt(result.context_precision) or "-",
                _fmt(result.faithfulness) or "-",
                result.latency_s,
                question.question[:70],
                f"  ERROR {result.error}" if result.error else "",
            )
            results.append(result)
            if csv_writer and file_handle:
                csv_writer.writerow(
                    [
                        result.question.question,
                        ";".join(result.question.spec_ids),
                        _fmt(result.context_precision),
                        _fmt(result.faithfulness),
                        result.answer,
                        "\n---\n".join(result.contexts),
                        f"{result.latency_s:.1f}",
                        result.error,
                    ]
                )
                file_handle.flush()
    finally:
        if file_handle is not None:
            file_handle.close()
    return results


def _fmt(score: float | None) -> str:
    return "" if score is None else f"{score:.3f}"


def write_report(results: Sequence[Result], path: Path) -> None:
    """evaluation_report.csv: one row per question, scores 0.0-1.0; UTF-8 with BOM so Excel reads it right."""
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "Question",
                "Source_Spec_ID",
                "Context_Precision",
                "Faithfulness",
                "Answer",
                "Contexts",
                "Latency_s",
                "Error",
            ]
        )
        for r in results:
            writer.writerow(
                [
                    r.question.question,
                    ";".join(r.question.spec_ids),
                    _fmt(r.context_precision),
                    _fmt(r.faithfulness),
                    r.answer,
                    "\n---\n".join(r.contexts),
                    f"{r.latency_s:.1f}",
                    r.error,
                ]
            )


def summarize(
    results: Sequence[Result], min_precision: float = MIN_PRECISION, min_faithfulness: float = MIN_FAITHFULNESS
) -> tuple[str, bool]:
    """The means over the scored questions and whether they pass; a question left unscored fails the run."""
    scored = [r for r in results if not r.error and r.context_precision is not None and r.faithfulness is not None]
    failed = len(results) - len(scored)
    lines = [f"Đánh giá {len(results)} câu: {len(scored)} câu được chấm, {failed} câu lỗi"]
    if not scored:
        return "\n".join([*lines, "Không có câu nào được chấm: FAIL"]), False
    precision = sum(r.context_precision for r in scored) / len(scored)
    faithfulness = sum(r.faithfulness for r in scored) / len(scored)
    ok_precision, ok_faithfulness = precision > min_precision, faithfulness > min_faithfulness
    verdict = {True: "PASS", False: "FAIL"}
    lines += [
        f"Context Precision  {precision:.3f}  (ngưỡng > {min_precision:.2f})  {verdict[ok_precision]}",
        f"Faithfulness       {faithfulness:.3f}  (ngưỡng > {min_faithfulness:.2f})  {verdict[ok_faithfulness]}",
    ]
    if failed:
        lines.append(f"{failed} câu lỗi chưa được chấm (xem cột Error): FAIL")
    return "\n".join(lines), ok_precision and ok_faithfulness and not failed


class EvalSettings(BaseSettings):
    """The judge model, from EVAL_* variables (default: gpt-4o-mini on OpenAI)."""

    model_config = SettingsConfigDict(env_prefix="EVAL_", extra="ignore")

    llm_model: str = "gpt-4o-mini"
    base_url: str | None = None
    api_key: SecretStr | None = None  # empty: OPENAI_API_KEY
    reasoning_effort: str | None = None
    max_tokens: int = 4096
    delay_seconds: float = 0.0

    @field_validator("base_url", "api_key", "reasoning_effort", mode="before")
    @classmethod
    def _empty_means_unset(cls, value):
        return value or None

    @field_validator("llm_model", mode="before")
    @classmethod
    def _empty_means_the_default(cls, value):
        # .env.example leaves EVAL_LLM_MODEL= empty: an empty model name would fail every question
        return value or cls.model_fields["llm_model"].default


class RagasJudge:
    """Ragas' Context Precision (with reference) and Faithfulness, scored by the EVAL_* judge model."""

    def __init__(self, settings: EvalSettings, fallback_api_key: str) -> None:
        from openai import AsyncOpenAI
        from ragas.llms import llm_factory
        from ragas.metrics.collections import ContextPrecision, Faithfulness

        api_key = settings.api_key.get_secret_value() if settings.api_key else fallback_api_key
        client = AsyncOpenAI(api_key=api_key, base_url=settings.base_url, max_retries=0)
        options: dict[str, Any] = {"max_tokens": settings.max_tokens}
        if settings.reasoning_effort:
            options["reasoning_effort"] = settings.reasoning_effort
        llm = llm_factory(settings.llm_model, client=client, **options)
        self._precision, self._faithfulness = ContextPrecision(llm=llm), Faithfulness(llm=llm)

    async def context_precision(self, question: str, reference: str, contexts: list[str]) -> float:
        result = await retried(
            lambda: self._precision.ascore(user_input=question, reference=reference, retrieved_contexts=contexts)
        )
        return result.value

    async def faithfulness(self, question: str, answer: str, contexts: list[str]) -> float:
        result = await retried(
            lambda: self._faithfulness.ascore(user_input=question, response=answer, retrieved_contexts=contexts)
        )
        return result.value


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, default=BACKEND / "qa_golden_dataset.csv")
    parser.add_argument("--output", type=Path, default=BACKEND / "evaluation_report.csv")
    parser.add_argument("--limit", type=int, default=0, help="only the first N questions (a quick check)")
    parser.add_argument("--min-precision", type=float, default=MIN_PRECISION)
    parser.add_argument("--min-faithfulness", type=float, default=MIN_FAITHFULNESS)
    return parser.parse_args(argv)


async def main(argv: Sequence[str] | None = None) -> int:
    args = _arguments(argv)
    try:
        questions = load_dataset(args.dataset)
    except (DatasetError, OSError) as error:
        print(f"Dataset không dùng được: {error}")
        return 2
    if args.limit:
        questions = questions[: args.limit]

    from personal_kb.bootstrap import build_chat_agent, services
    from personal_kb.core.config import get_settings
    from personal_kb.core.prompts import load_prompt
    from personal_kb.tools.registry import ToolRegistry

    settings, judge_settings = get_settings(), EvalSettings()
    try:
        judge = RagasJudge(judge_settings, settings.openai_api_key.get_secret_value())
    except ImportError as error:
        print(f"Thiếu thư viện chấm điểm ({error.name}): chạy với `uv run --group eval ...`")
        return 2
    print(f"Giám khảo: {judge_settings.llm_model} @ {judge_settings.base_url or 'OpenAI'}; {len(questions)} câu")

    run = time.strftime("eval-%Y%m%d-%H%M%S")
    numbers = itertools.count(1)
    async with services(settings) as built:
        agent = build_chat_agent(built, settings, ToolRegistry.discover(), load_prompt("agent_persona").system)

        async def answer(question: str) -> tuple[str, list[str]]:
            messages = await agent.run_once("eval", f"{run}-{next(numbers)}", question, built.tool_context)
            return str(messages[-1].content), contexts_of(messages)

        results = await evaluate(questions, answer, judge, delay=judge_settings.delay_seconds, output_path=args.output)

    write_report(results, args.output)
    text, passed = summarize(results, args.min_precision, args.min_faithfulness)
    print(f"\n{text}\nBáo cáo: {args.output}")
    return 0 if passed else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log.setLevel(logging.INFO)
    sys.exit(asyncio.run(main()))
