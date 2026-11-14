import { AuthError, getAccessToken } from "@/lib/auth";
import { API_URL } from "@/lib/config";

export type SessionSummary = { session_id: string; title: string; updated_at: number };
export type TranscriptMessage = { role: "user" | "assistant"; content: string; stopped: boolean };
export type SpecCard = { spec_id: string; title: string; owner: string | null; status: string };

/** fetch() against the API as the signed-in user; a missing or refused token is an AuthError. */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const token = await getAccessToken();
  if (!token) throw new AuthError("Chưa đăng nhập");
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { ...init.headers, Authorization: `Bearer ${token}` },
  });
  if (response.status === 401) throw new AuthError("Phiên đăng nhập đã hết hạn");
  return response;
}

/** The API's error message: {"message"} from its handlers, {"detail"} from FastAPI's validation. */
export async function errorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json();
    return body.message ?? body.detail?.[0]?.msg ?? body.detail ?? `HTTP ${response.status}`;
  } catch {
    return `HTTP ${response.status}`;
  }
}

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) throw new Error(await errorMessage(response));
  return (await response.json()) as T;
}

const sessionPath = (id: string) => `/api/v1/chat/sessions/${encodeURIComponent(id)}`;

export async function listSessions(): Promise<SessionSummary[]> {
  return (await json<{ sessions: SessionSummary[] }>(await apiFetch("/api/v1/chat/sessions"))).sessions;
}

export async function getTranscript(id: string): Promise<TranscriptMessage[]> {
  return (await json<{ messages: TranscriptMessage[] }>(await apiFetch(`${sessionPath(id)}/transcript`))).messages;
}

export async function deleteSession(id: string): Promise<void> {
  const response = await apiFetch(sessionPath(id), { method: "DELETE" });
  if (!response.ok) throw new Error(await errorMessage(response));
}

const specCards = new Map<string, Promise<SpecCard>>();

/** A spec's card for a citation badge (issue 3.4), fetched once per page; a failed fetch is retried next time. */
export function getSpecCard(specId: string): Promise<SpecCard> {
  let card = specCards.get(specId);
  if (!card) {
    card = apiFetch(`/api/v1/specs/${encodeURIComponent(specId)}`).then((r) => json<SpecCard>(r));
    card.catch(() => specCards.delete(specId));
    specCards.set(specId, card);
  }
  return card;
}

export interface SpecContent {
  spec_id: string;
  title: string;
  owner: string | null;
  status: string;
  content: string;
  content_hash: string;
}

const specContents = new Map<string, Promise<SpecContent>>();

/** Fetch full spec markdown content and metadata for slide-over drawer and deep links. */
export function getSpecContent(specId: string): Promise<SpecContent> {
  let doc = specContents.get(specId);
  if (!doc) {
    doc = apiFetch(`/api/v1/specs/${encodeURIComponent(specId)}/content`).then((r) => json<SpecContent>(r));
    doc.catch(() => specContents.delete(specId));
    specContents.set(specId, doc);
  }
  return doc;
}

export interface KnowledgeProposal {
  id: string;
  spec_id: string;
  title: string;
  action: "UPDATE_SECTION" | "CREATE_DOCUMENT" | "REPLACE_DOCUMENT";
  section: string;
  proposed_content: string;
  rationale: string;
  base_hash?: string | null;
  status: "PENDING" | "APPROVED" | "REJECTED";
  conflict_detected?: boolean;
  conflict_rule_id?: string | null;
  conflict_reason?: string | null;
  created_at: string;
  reviewed_at?: string | null;
  reviewed_by?: string | null;
  review_note?: string | null;
}

export async function listProposals(status?: "PENDING" | "APPROVED" | "REJECTED"): Promise<KnowledgeProposal[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  return await json<KnowledgeProposal[]>(await apiFetch(`/api/v1/proposals${query}`));
}

export async function getProposal(id: string): Promise<KnowledgeProposal> {
  return await json<KnowledgeProposal>(await apiFetch(`/api/v1/proposals/${encodeURIComponent(id)}`));
}

export async function createProposal(data: {
  spec_id: string;
  title: string;
  proposed_content: string;
  rationale: string;
  section?: string;
  action?: "UPDATE_SECTION" | "CREATE_DOCUMENT" | "REPLACE_DOCUMENT";
}): Promise<KnowledgeProposal> {
  const response = await apiFetch("/api/v1/proposals", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  return await json<KnowledgeProposal>(response);
}

export async function approveProposal(id: string, reviewer = "Admin", force = false): Promise<KnowledgeProposal> {
  const response = await apiFetch(`/api/v1/proposals/${encodeURIComponent(id)}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reviewer, force }),
  });
  return await json<KnowledgeProposal>(response);
}

export async function rejectProposal(id: string, reviewer = "Admin", note?: string): Promise<KnowledgeProposal> {
  const response = await apiFetch(`/api/v1/proposals/${encodeURIComponent(id)}/reject`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reviewer, note }),
  });
  return await json<KnowledgeProposal>(response);
}

// --- Data Hub APIs (/api/v1/data) ---

export type CatalogItem = {
  spec_id: string;
  title: string;
  project_id?: string;
  file_name: string;
  file_size_bytes: number;
  chunk_count: number;
  in_vector_db: boolean;
  in_documents: boolean;
  last_modified: string;
};

export type CatalogResponse = {
  total_specs: number;
  total_chunks: number;
  storage_backend: string;
  projects?: string[];
  project_counts?: Record<string, number>;
  items: CatalogItem[];
};

export type StorageTierStats = {
  name: string;
  engine: string;
  status: string;
  metrics: Record<string, any>;
};

export type TopologyResponse = {
  storage_backend: string;
  embedding_model: string;
  embedding_dimensions: number;
  tiers: StorageTierStats[];
  timestamp: string;
};

export type ConsistencyAuditResult = {
  total_disk_files: number;
  total_db_specs: number;
  missing_in_db: string[];
  orphan_in_db: string[];
  consistency_percentage: number;
  audit_passed: boolean;
  timestamp: string;
};

export type ChunkItem = {
  chunk_id: number | string;
  chunk_key: string;
  chunk_index: number;
  headings: string[];
  content: string;
  token_estimate: number;
  status: string;
  valid_from: string | null;
};

export type ChunksListResponse = {
  spec_id: string;
  total_chunks: number;
  chunks: ChunkItem[];
};

export type RetrievalHitItem = {
  spec_ids: string[];
  headings: string[];
  source: string;
  score: number;
  text_preview: string;
  project_id?: string;
};

export type RetrievalTestResponse = {
  query: string;
  took_ms: number;
  total_hits: number;
  results: RetrievalHitItem[];
};

export async function listCatalog(project?: string): Promise<CatalogResponse> {
  const query = project && project !== "ALL" ? `?project=${encodeURIComponent(project)}` : "";
  return await json<CatalogResponse>(await apiFetch(`/api/v1/data/catalog${query}`));
}

export async function getStorageTopology(): Promise<TopologyResponse> {
  return await json<TopologyResponse>(await apiFetch("/api/v1/data/topology"));
}

export async function runConsistencyAudit(): Promise<ConsistencyAuditResult> {
  const response = await apiFetch("/api/v1/data/audit", { method: "POST" });
  return await json<ConsistencyAuditResult>(response);
}

export async function getDocumentChunks(specId: string): Promise<ChunksListResponse> {
  return await json<ChunksListResponse>(await apiFetch(`/api/v1/data/documents/${encodeURIComponent(specId)}/chunks`));
}

export async function uploadDocument(
  file: File,
  projectId?: string
): Promise<{ status: string; spec_id: string; project_id?: string; message: string }> {
  const token = await getAccessToken();
  const formData = new FormData();
  formData.append("file", file);
  if (projectId) {
    formData.append("project_id", projectId);
  }

  const response = await fetch(`${API_URL}/api/v1/data/upload`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: formData,
  });
  return await json(response);
}

export async function reindexSpec(specId: string): Promise<{ status: string; spec_id: string; message: string }> {
  const response = await apiFetch(`/api/v1/data/reindex/${encodeURIComponent(specId)}`, { method: "POST" });
  return await json(response);
}

export async function deleteDocument(specId: string): Promise<{ status: string; spec_id: string; message: string }> {
  const response = await apiFetch(`/api/v1/data/documents/${encodeURIComponent(specId)}`, { method: "DELETE" });
  return await json(response);
}

export async function testRetrieval(query: string, limit = 5, projectId?: string): Promise<RetrievalTestResponse> {
  const payload: Record<string, any> = { query, limit };
  if (projectId && projectId !== "ALL") {
    payload.project_id = projectId;
  }
  const response = await apiFetch("/api/v1/data/sandbox/retrieve", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return await json<RetrievalTestResponse>(response);
}
