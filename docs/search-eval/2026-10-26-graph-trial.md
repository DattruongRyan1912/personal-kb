# Graph search trial (2026-10-26)

Graph ingestion (`scripts/ingest_sdd_to_graph.py`, DeepSeek) on PKB-03, PKB-02, AGY-01, CYBEROS-01: 42 chunks,
14 s, 53 entities and 64 relations (49 DEFINES, 13 DEPENDS_ON, 2 CALLS).

| | GRAPH_SEARCH=false | GRAPH_SEARCH=true |
|---|---|---|
| Eval, 56 cases | 56/56, MRR 0.964 | 56/56, MRR 0.955 |
| 4 relational questions: answer terms in the top 5 | 13/16 | 14/16 |
| Median search latency | 1.68 s | 2.58 s |
| Cost per search | none | one LLM call (query terms) |

Decision: graph search stays off. These specs state their relations in prose, so the vector and keyword sides
already return them; the graph added one term to one question for +0.9 s and an LLM call per search. The graph code
and the trial facts are kept: worth measuring again when the knowledge base holds technical specs whose relations
(API → table) span several documents.

Relational questions used: "auto rotator daemon phụ thuộc những thành phần nào" (AGY-Remote-Hub), "feed tab gọi
những API nào" (AGY-Remote-Hub), "memory fabric lưu dữ liệu vào những bảng nào" (CyberOS), "quy trình ingestion gồm
những bước phụ thuộc nào" (Personal-KB).
