import pytest

from personal_kb.services.graph_text import display_name, graph_fact, relation_line


@pytest.mark.parametrize(
    ("label", "name", "expected"),
    [
        ("API_Endpoint", "post_api_v1_notifications_email", "API POST /api/v1/notifications/email"),
        ("API_Endpoint", "patch_api_v1_users_me", "API PATCH /api/v1/users/me"),
        ("Database_Table", "email_outbox", "bảng email_outbox"),
        ("Feature", "account_registration", "tính năng account registration"),
        ("Role", "admin", "vai trò admin"),
        ("Spec", "spc_3", "spec SPC-3"),
    ],
)
def test_nodes_read_as_people_name_them(label, name, expected):
    assert display_name(label, name) == expected


@pytest.mark.parametrize(
    ("relation", "outgoing", "expected"),
    [
        ("MODIFIES", True, "- ghi vào bảng email_outbox (MODIFIES)"),
        ("MODIFIES", False, "- bị ghi bởi bảng email_outbox (MODIFIES)"),
        ("CALLS", False, "- được gọi bởi bảng email_outbox (CALLS)"),
        ("DEPENDS_ON", True, "- phụ thuộc vào bảng email_outbox (DEPENDS_ON)"),
        ("DEFINES", False, "- được định nghĩa trong bảng email_outbox (DEFINES)"),
    ],
)
def test_relations_read_as_vietnamese_with_their_ontology_tag(relation, outgoing, expected):
    assert relation_line(relation, outgoing, "bảng email_outbox") == expected


def test_a_graph_fact_lists_a_node_and_its_links_as_the_neo4j_store_did():
    # the record Neo4jService.neighborhoods builds for the API of tests/test_neo4j_service.py's first neighborhood
    record = {
        "id": "api:t1_post_notifications_email",
        "label": "API_Endpoint",
        "name": "t1_post_notifications_email",
        "spec_ids": ["SPC-3"],
        "links": [
            {
                "type": "MODIFIES",
                "outgoing": True,
                "other_label": "Database_Table",
                "other_name": "t1_email_outbox",
                "spec_ids": ["SPC-3"],
            },
            {
                "type": "CALLS",
                "outgoing": False,
                "other_label": "API_Endpoint",
                "other_name": "t1_post_auth_register",
                "spec_ids": ["SPC-3", "SPC-9"],
            },
        ],
    }

    fact = graph_fact(record)

    assert fact.node_id == "api:t1_post_notifications_email"
    assert fact.text == (
        "API T1 /post/notifications/email:\n"
        "- ghi vào bảng t1_email_outbox (MODIFIES)\n"
        "- được gọi bởi API T1 /post/auth/register (CALLS)"
    )
    assert fact.spec_ids == ["SPC-3", "SPC-9"]
