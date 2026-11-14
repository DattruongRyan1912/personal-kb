"""The graph store contract (PoC-A2, #297): revisions, provenance and validity, whatever the backend.

Each test's ids carry its `tag`.
"""

import asyncio
from datetime import timedelta

import pytest

from personal_kb.services.graph_models import Edge, GraphExtraction, Node
from personal_kb.services.memory_ports import DeleteResult, StaleRevisionError
from personal_kb.services.provenance import SourceRevision
from tests.contract.conftest import T1, T2, T3


def graph(tag: str, feature: str, spec: str) -> GraphExtraction:
    return GraphExtraction(
        nodes=[
            Node(id=f"spec:{spec}", label="Spec"),
            Node(id=f"feature:{tag}_{feature}", label="Feature"),
            Node(id=f"db_table:{tag}_users", label="Database_Table"),
        ],
        edges=[
            Edge(source_id=f"spec:{spec}", target_id=f"feature:{tag}_{feature}", relation_type="DEFINES"),
            Edge(source_id=f"feature:{tag}_{feature}", target_id=f"db_table:{tag}_users", relation_type="MODIFIES"),
        ],
    )


async def apply(store, tag, extraction=None, *, source="SPC-1", key="k1", removed=(), kept=(), at=T1):
    """One revision of the source `<tag>-<source>`: `extraction` stated under `key` (if given), `removed` retracted."""
    added = {key: extraction} if extraction is not None else {}
    revision = SourceRevision(f"{tag}-{source}", "1", "hash")
    return await store.apply_revision(revision, added=added, removed=set(removed), kept=set(kept), observed_at=at)


def modifies(tag, feature="login") -> tuple[str, str, str]:
    """The (src, type, dst) of a feature's MODIFIES relation to the users table."""
    return f"feature:{tag}_{feature}", "MODIFIES", f"db_table:{tag}_users"


async def test_applying_the_same_chunk_twice_creates_nothing_new(graph_store, graph_probe, tag):
    extraction = graph(tag, "login", f"{tag}_spc_1")

    first = await apply(graph_store, tag, extraction)
    again = await apply(graph_store, tag, extraction, at=T2)

    assert (first.opened, again.opened) == (2, 0)
    assert await graph_probe.counts(tag) == (3, 2)  # spec, feature, table; DEFINES and MODIFIES


async def test_features_of_different_specs_share_one_table_node(graph_store, graph_probe, tag):
    for spec, feature in (("SPC-1", "login"), ("SPC-2", "checkout"), ("SPC-3", "register")):
        await apply(graph_store, tag, graph(tag, feature, f"{tag}_{spec.lower().replace('-', '_')}"), source=spec)

    for feature in ("login", "checkout", "register"):
        assert await graph_probe.intervals(*modifies(tag, feature)) == [(T1, None)]
    assert await graph_probe.counts(tag) == (7, 6)  # 3 specs, 3 features and one shared table
    assert await graph_probe.node_spec_ids(f"db_table:{tag}_users") == [f"{tag}-SPC-1", f"{tag}-SPC-2", f"{tag}-SPC-3"]


async def test_relationships_record_the_specs_that_state_them(graph_store, graph_probe, tag):
    extraction = graph(tag, "login", f"{tag}_spc_1")

    await apply(graph_store, tag, extraction)
    await apply(graph_store, tag, extraction, source="SPC-5", key="k9")

    assert await graph_probe.relation_spec_ids(*modifies(tag)) == [f"{tag}-SPC-1", f"{tag}-SPC-5"]
    assert await graph_probe.relation_asserted_by(*modifies(tag)) == [f"{tag}-SPC-1#k1", f"{tag}-SPC-5#k9"]


async def test_a_removed_chunk_closes_the_relationships_only_it_stated(graph_store, graph_probe, tag):
    extraction = graph(tag, "login", f"{tag}_spc_1")
    await apply(graph_store, tag, extraction, key="k1")
    await apply(graph_store, tag, extraction, source="SPC-5", key="k9")

    still_stated = await apply(graph_store, tag, removed={"k1"}, at=T2)
    gone = await apply(graph_store, tag, source="SPC-5", removed={"k9"}, at=T3)

    assert (still_stated.closed, gone.closed) == (0, 2)
    assert await graph_probe.intervals(*modifies(tag)) == [(T1, T3)]
    feature = f"feature:{tag}_login"
    assert await graph_probe.node_spec_ids(feature) == []  # closed at T3
    # who stated it last, kept for questions about the past
    assert await graph_probe.node_spec_ids(feature, as_of=T3 - timedelta(microseconds=1)) == [f"{tag}-SPC-5"]


async def test_a_fact_stated_again_after_it_closed_opens_a_new_interval(graph_store, graph_probe, tag):
    extraction = graph(tag, "login", f"{tag}_spc_1")
    await apply(graph_store, tag, extraction, key="k1", at=T1)
    await apply(graph_store, tag, removed={"k1"}, at=T2)

    reopened = await apply(graph_store, tag, extraction, key="k2", at=T3)

    assert reopened.opened == 2
    assert await graph_probe.intervals(*modifies(tag)) == [(T1, T2), (T3, None)]


async def test_a_fact_moved_to_another_chunk_in_one_revision_stays_open(graph_store, graph_probe, tag):
    extraction = graph(tag, "login", f"{tag}_spc_1")
    await apply(graph_store, tag, extraction, key="k1", at=T1)

    result = await graph_store.apply_revision(
        SourceRevision(f"{tag}-SPC-1", "2", "hash2"),
        added={"k2": extraction},
        removed={"k1"},
        kept=set(),
        observed_at=T2,
    )

    assert (result.opened, result.closed) == (0, 0)
    assert await graph_probe.intervals(*modifies(tag)) == [(T1, None)]


async def test_the_source_remembers_the_chunk_keys_it_holds(graph_store, tag):
    await apply(graph_store, tag, graph(tag, "login", f"{tag}_spc_1"), key="k1")
    await apply(graph_store, tag, graph(tag, "logout", f"{tag}_spc_1"), key="k2", kept={"k1"}, at=T2)
    await apply(graph_store, tag, removed={"k1"}, kept={"k2"}, at=T3)

    assert await graph_store.known_chunk_keys(f"{tag}-SPC-1") == {"k2"}
    assert await graph_store.known_chunk_keys(f"{tag}-SPC-404") == set()


async def test_two_concurrent_revisions_of_one_source_leave_one_open_row_per_key(
    graph_store, graph_probe, tag, request
):
    extraction = graph(tag, "login", f"{tag}_spc_1")

    await asyncio.gather(
        apply(graph_store, tag, extraction, key="k1", at=T1),
        apply(graph_store, tag, extraction, key="k1", at=T1 + timedelta(seconds=1)),
    )

    assert await graph_probe.relation_asserted_by(*modifies(tag)) == [f"{tag}-SPC-1#k1"]
    [(start, end)] = await graph_probe.intervals(*modifies(tag))  # whichever run took the lock first opened it
    assert start in (T1, T1 + timedelta(seconds=1)) and end is None
    assert await graph_store.known_chunk_keys(f"{tag}-SPC-1") == {"k1"}


def writes_to(tag: str, table: str) -> GraphExtraction:
    checkout = f"api:{tag}_post_checkout"
    return GraphExtraction(
        nodes=[Node(id=checkout, label="API_Endpoint"), Node(id=f"db_table:{tag}_{table}", label="Database_Table")],
        edges=[Edge(source_id=checkout, target_id=f"db_table:{tag}_{table}", relation_type="MODIFIES")],
    )


async def test_neighborhoods_describe_matched_nodes_with_their_one_hop_links(graph_store, tag):
    email = f"api:{tag}_post_notifications_email"
    register = f"api:{tag}_post_auth_register"
    extraction = GraphExtraction(
        nodes=[
            Node(id=email, label="API_Endpoint"),
            Node(id=register, label="API_Endpoint"),
            Node(id=f"db_table:{tag}_email_outbox", label="Database_Table"),
        ],
        edges=[
            Edge(source_id=register, target_id=email, relation_type="CALLS"),
            Edge(source_id=email, target_id=f"db_table:{tag}_email_outbox", relation_type="MODIFIES"),
        ],
    )
    await apply(graph_store, tag, extraction, source="SPC-3")

    facts = await graph_store.neighborhoods([f"{tag}_post_notifications", "nothing_matches_this"])

    assert [f.node_id for f in facts] == [email]
    assert facts[0].spec_ids == [f"{tag}-SPC-3"]
    # readable for a Vietnamese query (the re-ranker scored this form 0.65 against 0.19 for "A -[MODIFIES]-> B")
    assert facts[0].text == (
        f"API {tag.upper()} /post/notifications/email:\n"
        f"- ghi vào bảng {tag}_email_outbox (MODIFIES)\n"
        f"- được gọi bởi API {tag.upper()} /post/auth/register (CALLS)"
    )


async def test_neighborhoods_rank_nodes_matching_more_terms_first_and_respect_the_limit(graph_store, tag):
    nodes = [Node(id=f"db_table:{tag}_{name}", label="Database_Table") for name in ("users", "user_roles", "orders")]
    await apply(graph_store, tag, GraphExtraction(nodes=nodes, edges=[]), source="SPC-5")

    facts = await graph_store.neighborhoods([f"{tag}_user", f"{tag}_user_roles"], limit=2)

    assert [f.node_id for f in facts] == [f"db_table:{tag}_user_roles", f"db_table:{tag}_users"]


async def test_no_terms_means_no_neighborhoods(graph_store):
    assert await graph_store.neighborhoods([]) == []


async def test_a_term_with_like_wildcards_matches_literally(graph_store, tag):
    nodes = [Node(id=f"db_table:{tag}_{name}", label="Database_Table") for name in ("users", "user_roles")]
    await apply(graph_store, tag, GraphExtraction(nodes=nodes, edges=[]), source="SPC-5")

    assert [f.node_id for f in await graph_store.neighborhoods([f"{tag}_user_"])] == [f"db_table:{tag}_user_roles"]
    assert await graph_store.neighborhoods([f"{tag}_u%s"]) == []
    assert await graph_store.neighborhoods([f"{tag}\\_users"]) == []


async def test_neighborhoods_answer_for_now_or_for_a_past_time(graph_store, tag):
    await apply(graph_store, tag, writes_to(tag, "payments"), key="k1", at=T1)
    await graph_store.apply_revision(
        SourceRevision(f"{tag}-SPC-2", "2", "hash2"),
        added={"k2": writes_to(tag, "payment_transactions")},
        removed=set(),
        kept=set(),
        observed_at=T2,
    )
    await apply(graph_store, tag, removed={"k1"}, at=T2)

    now = await graph_store.neighborhoods([f"{tag}_post_checkout"])
    then = await graph_store.neighborhoods([f"{tag}_post_checkout"], as_of=T1 + timedelta(hours=1))
    before = await graph_store.neighborhoods([f"{tag}_post_checkout"], as_of=T1 - timedelta(hours=1))

    assert f"{tag}_payment_transactions (MODIFIES)" in now[0].text
    assert f"{tag}_payments (MODIFIES)" not in now[0].text
    assert f"{tag}_payments (MODIFIES)" in then[0].text
    assert f"{tag}_payment_transactions" not in then[0].text
    assert before == []


async def test_at_the_revision_time_the_new_version_is_valid_and_the_old_is_not(graph_store, tag):
    await apply(graph_store, tag, writes_to(tag, "payments"), key="k1", at=T1)
    await graph_store.apply_revision(
        SourceRevision(f"{tag}-SPC-1", "2", "hash2"),
        added={"k2": writes_to(tag, "payment_transactions")},
        removed={"k1"},
        kept=set(),
        observed_at=T2,
    )

    [at] = await graph_store.neighborhoods([f"{tag}_post_checkout"], as_of=T2)
    [just_before] = await graph_store.neighborhoods([f"{tag}_post_checkout"], as_of=T2 - timedelta(microseconds=1))

    assert f"{tag}_payment_transactions (MODIFIES)" in at.text and f"{tag}_payments (MODIFIES)" not in at.text
    assert f"{tag}_payments (MODIFIES)" in just_before.text and f"{tag}_payment_transactions" not in just_before.text


async def test_a_past_question_cites_the_specs_that_stated_the_fact_then(graph_store, tag, request):
    extraction = graph(tag, "login", f"{tag}_spc_1")
    await apply(graph_store, tag, extraction, key="k1", at=T1)
    await apply(graph_store, tag, extraction, source="SPC-5", key="k9", at=T3)

    [fact] = await graph_store.neighborhoods([f"{tag}_login"], as_of=T1 + timedelta(hours=1))

    assert fact.spec_ids == [f"{tag}-SPC-1"]


async def test_deleting_a_source_purges_what_only_it_stated_and_keeps_shared_facts(graph_store, graph_probe, tag):
    shared = graph(tag, "login", f"{tag}_spc_1")
    only_spc_5 = GraphExtraction(
        nodes=[
            Node(id=f"db_table:{tag}_users", label="Database_Table"),
            Node(id=f"db_table:{tag}_audit", label="Database_Table"),
        ],
        edges=[Edge(source_id=f"db_table:{tag}_audit", target_id=f"db_table:{tag}_users", relation_type="DEPENDS_ON")],
    )
    await apply(graph_store, tag, shared, key="k1")
    await apply(graph_store, tag, shared, source="SPC-5", key="k9")
    await apply(graph_store, tag, only_spc_5, source="SPC-5", key="k8", kept={"k9"})

    result = await graph_store.delete_source(f"{tag}-SPC-5", observed_at=T2)

    assert (result.relationships, result.nodes) == (1, 1)  # DEPENDS_ON and the audit table
    assert await graph_probe.mentions(f"{tag}-SPC-5") == 0
    assert await graph_probe.counts(tag) == (3, 2)
    assert await graph_probe.intervals(*modifies(tag)) == [(T1, None)]
    assert await graph_probe.relation_spec_ids(*modifies(tag)) == [f"{tag}-SPC-1"]
    assert await graph_probe.node_spec_ids(f"db_table:{tag}_users") == [f"{tag}-SPC-1"]
    assert await graph_store.known_chunk_keys(f"{tag}-SPC-5") == set()


async def test_deleting_a_source_keeps_the_history_other_sources_wrote(graph_store, graph_probe, tag):
    extraction = graph(tag, "login", f"{tag}_spc_1")
    await apply(graph_store, tag, extraction, key="k1", at=T1)
    await apply(graph_store, tag, removed={"k1"}, at=T2)
    await apply(graph_store, tag, extraction, source="SPC-5", key="k9", at=T3)

    await graph_store.delete_source(f"{tag}-SPC-5", observed_at=T3 + timedelta(days=1))

    assert await graph_probe.intervals(*modifies(tag)) == [(T1, T2)]


async def test_deleting_a_source_leaves_a_shared_fact_valid_only_while_the_other_source_stated_it(
    graph_store, graph_probe, tag, request
):
    extraction = graph(tag, "login", f"{tag}_spc_1")
    await apply(graph_store, tag, extraction, key="k1", at=T1)
    await apply(graph_store, tag, extraction, source="SPC-5", key="k9", at=T1)
    await apply(graph_store, tag, removed={"k1"}, at=T2)  # SPC-1 stops; SPC-5 alone keeps it open

    await graph_store.delete_source(f"{tag}-SPC-5", observed_at=T3 + timedelta(days=1))

    # without SPC-5 the fact held only while SPC-1 stated it
    assert await graph_probe.intervals(*modifies(tag)) == [(T1, T2)]


async def test_deleting_an_unknown_source_deletes_nothing(graph_store, tag):
    assert await graph_store.delete_source(f"{tag}-SPC-404", observed_at=T1) == DeleteResult(0, 0)


async def test_a_revision_planned_from_chunk_keys_another_run_changed_is_refused(graph_store, tag, request):
    await graph_store.apply_revision(
        SourceRevision(f"{tag}-SPC-1", "1", "h1"),
        added={"k1": graph(tag, "login", f"{tag}_spc_1"), "k2": graph(tag, "logout", f"{tag}_spc_1")},
        removed=set(),
        kept=set(),
        observed_at=T1,
    )
    # two runs both planned from {k1, k2}; the extraction takes minutes, so the second applies after the first
    await apply(graph_store, tag, graph(tag, "signup", f"{tag}_spc_1"), key="k3", removed={"k2"}, kept={"k1"}, at=T2)

    with pytest.raises(StaleRevisionError):
        await apply(graph_store, tag, graph(tag, "reset", f"{tag}_spc_1"), key="k4", removed={"k1"}, kept={"k2"}, at=T3)

    assert await graph_store.known_chunk_keys(f"{tag}-SPC-1") == {"k1", "k3"}
