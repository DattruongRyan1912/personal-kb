# Prompt dictionary

The prompts the AI core sends to a model live in `backend/prompts/*.yaml`, so a PO or SA can read and change them
without touching code; a few short texts stay in code next to the logic that sends them ([texts in code](#texts-in-code)).
Each file has:

- a `#` comment block at the top: what the prompt is for and its placeholders;
- `system:` the instructions (the model's role and rules);
- `user_template:` the message sent with each call, with `$placeholders` the code fills in (empty for the persona,
  whose user message is the chat itself).

The loader is `personal_kb/core/prompts.py` (`load_prompt(name)`). A placeholder the code does not provide raises an
error, so do not add or rename `$placeholders` without a developer.

## At a glance

| File | Used for | Called from | Model | Output |
|---|---|---|---|---|
| `agent_persona.yaml` | The chat agent: role, how to use the tools, hard rules | `services/agent.py` (every chat turn) | `LLM_MODEL`, then `LLM_MODEL_THOROUGH` | Free text in Markdown with `[Title](SPEC_ID)` citations |
| `spec_selection.yaml` | Pick the specs a question needs from the catalog | `services/spec_selector.py` (first tool round of a question about the specs) | `LLM_MODEL` | JSON `spec_choice`: `{"spec_ids": [...]}` |
| `query_entities.yaml` | Turn a question into search terms for the knowledge graph | `services/query_entities.py` (every search) | `LLM_MODEL` | JSON `query_terms`: `{"terms": [...]}` |
| `session_summary.yaml` | Fold older chat turns into one summary | `services/summarizer.py` (when a session passes 3,000 tokens) | `LLM_MODEL` | Free text (the summary) |
| `graph_extraction.yaml` | Turn a spec section into graph nodes and edges | `services/graph_extraction.py` (`scripts.ingest_sdd_to_graph`) | `LLM_MODEL` | JSON `graph_extraction`: nodes and edges (`services/graph_models.py`) |

The JSON outputs are enforced by a schema in code (structured output): the prompt explains meaning and naming, not the
format.

## agent_persona.yaml

- **Purpose:** the system prompt of the LangGraph agent: a Principal Solution Architect who answers only from the SDD
  specs, through the tools, in the user's language.
- **Sections:** role; the three SDD tools and when to call each; how to handle multi-part questions and scenarios;
  that earlier answers and the session summary are context, not a source; when to use tools beyond the SDD ones; small
  talk; the **hard rules** (issue 2.4):
  never invent system facts, cite every technical statement as `[Tên tài liệu](ID)`, take error codes, HTTP codes,
  statuses, APIs and table names from the specs or say "spec không quy định".
- **Placeholders:** none (`user_template` is empty).
- **Safe to edit:** the tone and wording of the role; the explanations of when to use each tool (keep the tool names
  exact); adding a rule.
- **Do not remove:** the hard rules and the citation syntax `[Tên tài liệu](SPEC_ID)`: the chat UI renders citations
  from it and the code checks them (`services/citations.py`, `services/grounding.py`).
- **Adding a tool:** nothing to change here: the persona tells the agent to call any other tool whose description
  matches the request, without searching the specs first ([add a tool](add-a-tool.md)). Add a rule only for a tool
  that needs one.

## spec_selection.yaml

- **Purpose:** given the question and the catalog (`- SPC-1: Luồng đăng nhập` per line), return the specs to read
  whole, at most `$limit`. A scenario across several flows should get the spec of every flow it touches, plus the
  data dictionary when tables or columns matter.
- **Placeholders:** `$question`, `$catalog`, `$limit`.
- **Safe to edit:** the guidance on which specs a question needs (e.g. always include a data dictionary).
- **Effect of a mistake:** too few specs and the agent answers from searches only; too many and the answer is slower
  and Context Precision drops.

## query_entities.yaml

- **Purpose:** extract the terms to look up in the Neo4j graph from a question: table names (`users`,
  `email_outbox`), endpoints (`post_api_v1_auth_login`), features (`login`), roles (`admin`), in the graph's naming
  (English, lowercase snake_case).
- **Placeholders:** `$query`.
- **Safe to edit:** examples of names, when the specs bring new kinds of entities.
- **Keep in step with:** `graph_extraction.yaml`, which names the nodes these terms must match.

## session_summary.yaml

- **Purpose:** fold the older part of a chat into a short summary so follow-ups ("Ai là người viết nó?") keep their
  context without resending the whole history.
- **Placeholders:** `$previous_summary`, `$transcript` (what the user asked and which specs were named; the code never
  passes the answers' text).
- **Rule:** keep what was asked, not what was answered. A wrong answer kept in a summary was repeated by later turns.
- **Safe to edit:** length and what to keep about the questions.

## graph_extraction.yaml

- **Purpose:** used at ingestion only: turn one section of a spec into nodes (`Spec`, `Feature`, `API_Endpoint`,
  `Database_Table`, `Role`) and edges (`DEFINES`, `CALLS`, `MODIFIES`, `DEPENDS_ON`) for Neo4j.
- **Placeholders:** `$spec_id`, `$spec_node_id`, `$headings`, `$content`.
- **Safe to edit:** naming conventions and examples; after a change, run the ingestion again
  (`scripts.ingest_sdd_to_graph`) so the graph follows.
- **Keep in step with:** `query_entities.yaml`, and the allowed labels and relations in `services/graph_models.py`.

## Texts in code

Short instructions the agent adds in specific situations, in `backend/personal_kb/services/agent.py`; change them with
a developer, since tests check the behaviour they drive.

| Constant | Sent to the model when | Purpose |
|---|---|---|
| `SUMMARY_NOTICE` | the session has a summary | labels the summary as context, not a source |
| `SPECS_READ` | specs were read whole this turn | reminds a small model, right before the question, to answer from them |
| `CORRECTION` | an answer cites a spec no tool returned | asks for the answer again (issue 2.4) |
| `GROUNDING` | an answer names a code, status, API or table no spec read states | asks for a rewrite without them |

The tools' own `description` texts (in `backend/personal_kb/tools/*.py`) are shown to the model too: they decide when it
calls a tool ([add a tool](add-a-tool.md)). Texts the user sees but the model never does (the status line, the
guardrail's `REFUSAL`, `NO_SPEC_ANSWER`, the "⚠️ Chưa kiểm chứng" note) are in `agent.py` and `guardrails.py`.

## Checking a change

1. Edit the YAML. In development the backend reloads; on a server, rebuild: `docker compose up -d --build ai-backend`.
2. Try a few questions in the chat, or one tool: `docker compose exec backend python -m scripts.run_tool …`.
3. Run the evaluation before and after, and compare the two `evaluation_report.csv`
   (`cd backend && uv run --group eval --env-file ../.env python scripts/evaluate_ai.py`): a prompt change must
   not lower Context Precision or Faithfulness.
4. With Langfuse on, open a trace to see the exact prompt the model received.
