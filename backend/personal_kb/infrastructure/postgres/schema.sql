-- The memory of the Postgres backend (PoC-A2, #297), spec section 5. The extensions live in public (one per database);
-- the tables have no schema prefix: ensure_schema() creates the schema and runs this file with search_path = <schema>,
-- public. {dimensions} is EMBEDDING_DIMENSIONS. Every statement is IF NOT EXISTS: running it again changes nothing.
-- Two deviations from spec section 5 (PoC-A2 review): the foreign keys do not cascade, so a delete racing another
-- source's revision fails instead of silently dropping that source's rows (delete_source removes children itself);
-- and the assertions get full indexes on their fact, since the open-only ones cannot serve a past time or a delete.
CREATE EXTENSION IF NOT EXISTS vector SCHEMA public;
CREATE EXTENSION IF NOT EXISTS pg_trgm SCHEMA public;
CREATE EXTENSION IF NOT EXISTS unaccent SCHEMA public;

-- immutable helper function for generated tsv column (array_to_string is stable, not immutable)
CREATE OR REPLACE FUNCTION chunks_generate_tsv(headings text[], content text)
RETURNS tsvector AS $$
BEGIN
    RETURN to_tsvector('simple', coalesce(array_to_string(headings, ' '), '') || ' ' || coalesce(content, ''));
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- unaccent with its dictionary named, so it can be IMMUTABLE: "luong" finds "lương" (chunks_tsv and the keyword query)
CREATE OR REPLACE FUNCTION kb_unaccent(text) RETURNS text AS $$
    SELECT public.unaccent('public.unaccent'::regdictionary, $1)
$$ LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT;

CREATE OR REPLACE FUNCTION chunks_tsv(headings text[], content text)
RETURNS tsvector AS $$
    SELECT to_tsvector('simple', kb_unaccent(coalesce(array_to_string(headings, ' '), '') || ' ' || coalesce(content, '')))
$$ LANGUAGE sql IMMUTABLE SET search_path FROM CURRENT;  -- finds kb_unaccent whatever the writer's search_path

-- vector memory
CREATE TABLE IF NOT EXISTS chunks (
    id          bigserial PRIMARY KEY,
    spec_id     text        NOT NULL,
    chunk_key   text        NOT NULL,
    revision    text        NOT NULL,       -- the spec's revision when the chunk was first written
    headings    text[]      NOT NULL,
    content     text        NOT NULL,
    status      text        NOT NULL,
    chunk_index integer     NOT NULL,
    embedding   vector({dimensions}) NOT NULL,
    valid_from  timestamptz NOT NULL,
    valid_to    timestamptz,
    project_id  text        NOT NULL DEFAULT 'Personal-KB',
    tsv         tsvector    GENERATED ALWAYS AS (chunks_tsv(headings, content)) STORED
);

-- idempotent column migrations for pre-existing tables before indexes are defined
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'chunks' AND column_name = 'project_id'
    ) THEN
        ALTER TABLE chunks ADD COLUMN project_id text NOT NULL DEFAULT 'Personal-KB';
    END IF;

    -- a tsv missing, or still generated without unaccent, is (re)built; its index is created again below
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'chunks' AND column_name = 'tsv'
          AND generation_expression LIKE '%chunks_tsv(%'
    ) THEN
        ALTER TABLE chunks DROP COLUMN IF EXISTS tsv;
        ALTER TABLE chunks ADD COLUMN tsv tsvector GENERATED ALWAYS AS (chunks_tsv(headings, content)) STORED;
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS chunks_open_key ON chunks (spec_id, chunk_key) WHERE valid_to IS NULL;
CREATE INDEX IF NOT EXISTS chunks_spec ON chunks (spec_id);
CREATE INDEX IF NOT EXISTS chunks_project_lower ON chunks (lower(project_id));
CREATE INDEX IF NOT EXISTS chunks_embedding ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_tsv_idx ON chunks USING gin (tsv);

CREATE TABLE IF NOT EXISTS documents (
    spec_id    text PRIMARY KEY,
    title      text NOT NULL,
    content    text NOT NULL,
    project_id text NOT NULL DEFAULT 'Personal-KB'
);

-- graph: identities
CREATE TABLE IF NOT EXISTS entities (
    id    text PRIMARY KEY,                 -- e.g. "db_table:users"
    label text NOT NULL,                    -- ontology label (Spec, Feature, Database_Table, API_Endpoint, Role)
    name  text NOT NULL
);
CREATE INDEX IF NOT EXISTS entities_name_trgm ON entities USING gin (name gin_trgm_ops);

CREATE TABLE IF NOT EXISTS relations (
    id   bigserial PRIMARY KEY,
    src  text NOT NULL REFERENCES entities (id),
    type text NOT NULL,                     -- DEFINES, CALLS, MODIFIES, DEPENDS_ON
    dst  text NOT NULL REFERENCES entities (id),
    UNIQUE (src, type, dst)
);
CREATE INDEX IF NOT EXISTS relations_dst ON relations (dst);

-- graph: assertions, one row per (fact, source, chunk) for each interval of validity
CREATE TABLE IF NOT EXISTS entity_assertions (
    entity_id  text        NOT NULL REFERENCES entities (id),
    source_id  text        NOT NULL,
    chunk_key  text        NOT NULL,
    valid_from timestamptz NOT NULL,
    valid_to   timestamptz
);
CREATE UNIQUE INDEX IF NOT EXISTS entity_assertions_open
    ON entity_assertions (entity_id, source_id, chunk_key) WHERE valid_to IS NULL;
CREATE INDEX IF NOT EXISTS entity_assertions_source ON entity_assertions (source_id, chunk_key);
CREATE INDEX IF NOT EXISTS entity_assertions_entity ON entity_assertions (entity_id);

CREATE TABLE IF NOT EXISTS relation_assertions (
    relation_id bigint      NOT NULL REFERENCES relations (id),
    source_id   text        NOT NULL,
    chunk_key   text        NOT NULL,
    valid_from  timestamptz NOT NULL,
    valid_to    timestamptz
);
CREATE UNIQUE INDEX IF NOT EXISTS relation_assertions_open
    ON relation_assertions (relation_id, source_id, chunk_key) WHERE valid_to IS NULL;
CREATE INDEX IF NOT EXISTS relation_assertions_source ON relation_assertions (source_id, chunk_key);
CREATE INDEX IF NOT EXISTS relation_assertions_relation ON relation_assertions (relation_id);

CREATE TABLE IF NOT EXISTS graph_sources (
    id           text PRIMARY KEY,
    revision     text        NOT NULL,
    content_hash text        NOT NULL,
    observed_at  timestamptz NOT NULL,
    chunk_keys   text[]      NOT NULL       -- the chunks with an extraction (PoC-A's (:Source))
);

CREATE TABLE IF NOT EXISTS worklog_entries (
    id         bigserial   PRIMARY KEY,
    project    text        NOT NULL,
    kind       text        NOT NULL,
    summary    text        NOT NULL,
    next_steps text        NOT NULL DEFAULT '',
    agent      text        NOT NULL DEFAULT '',
    session_id text        NOT NULL DEFAULT '',
    branch     text        NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS worklog_entries_project_created ON worklog_entries (project, created_at DESC);
