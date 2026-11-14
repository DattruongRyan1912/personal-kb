"""PgWorklogStore: append-only worklog on Postgres."""

from personal_kb.infrastructure.postgres.pg_worklog_store import PgWorklogStore
from personal_kb.services.worklog import NewWorklogEntry


def make_store(pg_pool, pg_schema) -> PgWorklogStore:
    return PgWorklogStore(pg_pool, schema=pg_schema, dimensions=4)


def entry(summary: str, *, project: str = "Personal-KB", kind: str = "progress") -> NewWorklogEntry:
    return NewWorklogEntry(
        project=project, kind=kind, summary=summary, next_steps="n", agent="a", session_id="s", branch="b"
    )


async def test_add_then_recent_returns_newest_first(pg_pool, pg_schema):
    store = make_store(pg_pool, pg_schema)
    await store.ensure()
    for summary in ("one", "two", "three"):
        await store.add(entry(summary))

    rows = await store.recent("Personal-KB", limit=2)

    assert [r.summary for r in rows] == ["three", "two"]
    assert all(r.id > 0 and r.created_at is not None for r in rows)
    assert rows[0].next_steps == "n" and rows[0].agent == "a" and rows[0].session_id == "s" and rows[0].branch == "b"


async def test_recent_filters_by_project_and_kind(pg_pool, pg_schema):
    store = make_store(pg_pool, pg_schema)
    await store.add(entry("p1"))
    await store.add(entry("d1", kind="decision"))
    await store.add(entry("other", project="MyNotch"))

    assert [r.summary for r in await store.recent("Personal-KB")] == ["d1", "p1"]
    assert [r.summary for r in await store.recent("Personal-KB", kind="decision")] == ["d1"]
    assert [r.summary for r in await store.recent("MyNotch")] == ["other"]
    assert [r.summary for r in await store.recent("")] == ["other", "d1", "p1"]
    assert [r.summary for r in await store.recent()] == ["other", "d1", "p1"]


async def test_ensure_is_idempotent(pg_pool, pg_schema):
    store = make_store(pg_pool, pg_schema)
    await store.ensure()
    await store.ensure()

    assert await store.recent("Personal-KB") == []


async def test_first_add_creates_table_without_explicit_ensure(pg_pool, pg_schema):
    store = make_store(pg_pool, pg_schema)

    saved = await store.add(entry("first"))

    assert saved.id > 0 and saved.summary == "first"


async def test_every_entry_round_trips_through_a_backup(pg_pool, pg_schema):
    # the worklog is the only data not rebuilt from knowledge/: a backup must restore ids, times and every field
    source = make_store(pg_pool, pg_schema)
    await source.ensure()
    for summary in ("one", "two"):
        await source.add(entry(summary, project="MyNotch"))
    backup = await source.all_entries()
    await pg_pool.execute("TRUNCATE worklog_entries")

    restored = await source.restore(backup)

    assert restored == 2
    assert await source.all_entries() == backup


async def test_restoring_twice_adds_nothing_and_new_entries_get_fresh_ids(pg_pool, pg_schema):
    store = make_store(pg_pool, pg_schema)
    await store.ensure()
    await store.add(entry("one"))
    backup = await store.all_entries()
    await pg_pool.execute("TRUNCATE worklog_entries")
    await store.restore(backup)

    assert await store.restore(backup) == 0
    added = await store.add(entry("after restore"))
    assert added.id > backup[-1].id


async def test_restoring_over_entries_written_after_a_reset_refuses_instead_of_dropping_them(pg_pool, pg_schema):
    # after a volume reset an agent can log_progress before the restore runs: its new rows take ids 1..k, and
    # ON CONFLICT DO NOTHING silently skipped the backed-up entries with those ids (review, 2026-10-26)
    import pytest

    from personal_kb.infrastructure.postgres.pg_worklog_store import WorklogRestoreConflict

    store = make_store(pg_pool, pg_schema)
    await store.ensure()
    await store.add(entry("historical"))
    backup = await store.all_entries()
    await pg_pool.execute("TRUNCATE worklog_entries RESTART IDENTITY")
    await store.add(entry("written before the restore"))

    with pytest.raises(WorklogRestoreConflict, match=str(backup[0].id)):
        await store.restore(backup)
    assert [e.summary for e in await store.all_entries()] == ["written before the restore"]


async def test_an_entry_masked_by_the_backup_still_counts_as_the_one_stored(pg_pool, pg_schema):
    # the backup masks secrets an old entry kept (#5): restoring it over the same database must skip, not refuse
    import dataclasses

    store = make_store(pg_pool, pg_schema)
    await store.ensure()
    await store.add(entry("used OPENAI_API_KEY=sk-abcdefghijklmnopqrstu"))
    [stored] = await store.all_entries()
    masked = dataclasses.replace(stored, summary="used OPENAI_API_KEY=[REDACTED]")

    assert await store.restore([masked]) == 0
