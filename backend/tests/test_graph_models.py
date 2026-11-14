import pytest
from pydantic import ValidationError

from personal_kb.services.graph_models import Edge, GraphExtraction, Node, normalize_id, spec_node_id


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("db_table:users", "db_table:users"),
        ("db_table:Users Table", "db_table:users_table"),
        ("api:POST /api/v1/auth/login", "api:post_api_v1_auth_login"),
        ("feature:Đăng nhập", "feature:dang_nhap"),
        ("Role: Admin", "role:admin"),
    ],
)
def test_ids_are_normalized_to_prefix_and_snake_case(raw, expected):
    assert normalize_id(raw) == expected


def test_spec_node_id_comes_from_the_spec_id():
    assert spec_node_id("SPC-1") == "spec:spc_1"


def test_node_id_is_normalized():
    assert Node(id="db_table:Users", label="Database_Table").id == "db_table:users"


def test_node_with_a_prefix_that_does_not_match_its_label_is_refused():
    with pytest.raises(ValidationError, match="db_table"):
        Node(id="api:users", label="Database_Table")


def test_node_label_outside_the_ontology_is_refused():
    with pytest.raises(ValidationError):
        Node(id="service:mailer", label="Service")


def test_relation_outside_the_ontology_is_refused():
    with pytest.raises(ValidationError):
        Edge(source_id="feature:a", target_id="db_table:b", relation_type="WRITES")


def test_edge_endpoints_must_be_listed_nodes():
    with pytest.raises(ValidationError, match="db_table:orders"):
        GraphExtraction(
            nodes=[Node(id="feature:checkout", label="Feature")],
            edges=[Edge(source_id="feature:checkout", target_id="db_table:orders", relation_type="MODIFIES")],
        )


def test_extraction_merges_duplicate_nodes_after_normalization():
    graph = GraphExtraction(
        nodes=[
            Node(id="db_table:users", label="Database_Table"),
            Node(id="db_table:Users", label="Database_Table"),
            Node(id="feature:login", label="Feature"),
        ],
        edges=[Edge(source_id="feature:login", target_id="db_table:Users", relation_type="MODIFIES")],
    )

    assert [n.id for n in graph.nodes] == ["db_table:users", "feature:login"]
    assert graph.edges[0].target_id == "db_table:users"


def test_extraction_json_schema_is_strict():
    schema = GraphExtraction.model_json_schema()

    for definition in [schema, *schema["$defs"].values()]:
        assert definition["additionalProperties"] is False
        assert set(definition["required"]) == set(definition["properties"])
