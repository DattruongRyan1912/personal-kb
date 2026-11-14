import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockListCatalog = vi.fn();
const mockGetStorageTopology = vi.fn();
const mockGetDocumentChunks = vi.fn();
const mockReindexSpec = vi.fn();
const mockDeleteDocument = vi.fn();
const mockRunConsistencyAudit = vi.fn();
const mockTestRetrieval = vi.fn();
const mockGetSpecContent = vi.fn();

vi.mock("@/lib/api", () => ({
  listCatalog: (...args: unknown[]) => mockListCatalog(...args),
  getStorageTopology: (...args: unknown[]) => mockGetStorageTopology(...args),
  getDocumentChunks: (...args: unknown[]) => mockGetDocumentChunks(...args),
  reindexSpec: (...args: unknown[]) => mockReindexSpec(...args),
  deleteDocument: (...args: unknown[]) => mockDeleteDocument(...args),
  runConsistencyAudit: (...args: unknown[]) => mockRunConsistencyAudit(...args),
  testRetrieval: (...args: unknown[]) => mockTestRetrieval(...args),
  uploadDocument: vi.fn(),
  getSpecContent: (...args: unknown[]) => mockGetSpecContent(...args),
}));

const { default: DataManagementHubPage } = await import("@/app/data/page");

afterEach(cleanup);

describe("DataManagementHubPage (/data)", () => {
  const dummyCatalog = {
    total_specs: 2,
    total_chunks: 12,
    storage_backend: "PostgreSQL 17 + pgvector",
    items: [
      {
        spec_id: "PKB-01",
        title: "Kiến trúc Tổng thể Personal-KB",
        file_name: "PKB-01.md",
        file_size_bytes: 4096,
        chunk_count: 8,
        in_vector_db: true,
        in_documents: true,
        last_modified: "2026-10-20T00:00:00Z",
      },
      {
        spec_id: "PKB-02",
        title: "Chính sách Bảo mật & Access Control",
        file_name: "PKB-02.md",
        file_size_bytes: 2048,
        chunk_count: 4,
        in_vector_db: false,
        in_documents: true,
        last_modified: "2026-10-20T01:00:00Z",
      },
    ],
  };

  const dummyTopology = {
    storage_backend: "PostgreSQL 17 + pgvector",
    embedding_model: "text-embedding-3-small",
    embedding_dimensions: 1536,
    tiers: [
      {
        name: "Tier 1: Document Storage",
        engine: "PostgreSQL 17",
        status: "HEALTHY",
        metrics: { total_documents: 2, size_mb: 0.1 },
      },
      {
        name: "Tier 2: Vector Memory",
        engine: "pgvector HNSW",
        status: "HEALTHY",
        metrics: { total_vectors: 12, index_type: "hnsw" },
      },
    ],
    timestamp: "2026-10-20T10:00:00Z",
  };

  beforeEach(() => {
    vi.clearAllMocks();
    mockListCatalog.mockResolvedValue(dummyCatalog);
    mockGetStorageTopology.mockResolvedValue(dummyTopology);
    mockGetDocumentChunks.mockResolvedValue({
      spec_id: "PKB-01",
      chunks: [
        {
          chunk_id: 1,
          chunk_key: "chunk-1",
          chunk_index: 0,
          headings: ["# 1. Giới thiệu"],
          content: "Nội dung giới thiệu PKB",
          token_estimate: 42,
        },
      ],
    });
    mockGetSpecContent.mockResolvedValue({
      spec_id: "PKB-01",
      title: "Kiến trúc Tổng thể Personal-KB",
      owner: "Ryan Truong",
      status: "APPROVED",
      content: "# PKB-01 Spec Markdown Content",
      content_hash: "hash_pkb_01",
    });
  });

  it("loads and displays catalog items and metrics", async () => {
    render(<DataManagementHubPage />);

    expect(await screen.findByText("Kiến trúc Tổng thể Personal-KB")).toBeTruthy();
    expect(screen.getByText("Chính sách Bảo mật & Access Control")).toBeTruthy();
    expect(screen.getAllByText("(2)").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("8 chunks")).toBeTruthy();
  });

  it("filters catalog items using search input", async () => {
    render(<DataManagementHubPage />);

    await screen.findByText("Kiến trúc Tổng thể Personal-KB");

    const searchInput = screen.getByPlaceholderText("Tìm theo mã spec, tiêu đề...");
    fireEvent.change(searchInput, { target: { value: "Bảo mật" } });

    expect(screen.queryByText("Kiến trúc Tổng thể Personal-KB")).toBeNull();
    expect(screen.getByText("Chính sách Bảo mật & Access Control")).toBeTruthy();
  });

  it("opens SpecDrawer on spec code click without any alert popup", async () => {
    const alertSpy = vi.spyOn(window, "alert");

    render(<DataManagementHubPage />);

    await screen.findByText("Kiến trúc Tổng thể Personal-KB");

    // Click on PKB-01 spec code
    const specBtns = screen.getAllByTitle("Bấm để xem nội dung markdown");
    fireEvent.click(specBtns[0]);

    // SpecDrawer should open seamlessly
    expect(await screen.findByLabelText("Chi tiết tài liệu PKB-01")).toBeTruthy();
    expect(screen.getByText("PKB-01 Spec Markdown Content")).toBeTruthy();

    // Verify zero alerts were triggered
    expect(alertSpy).not.toHaveBeenCalled();
  });

  it("runs consistency audit on Topology tab", async () => {
    mockRunConsistencyAudit.mockResolvedValueOnce({
      total_disk_files: 2,
      total_db_specs: 2,
      missing_in_db: [],
      orphan_in_db: [],
      consistency_percentage: 100,
      audit_passed: true,
      timestamp: "2026-10-20T10:05:00Z",
    });

    render(<DataManagementHubPage />);

    await screen.findByText("Kiến trúc Tổng thể Personal-KB");

    // Switch to Topology tab
    fireEvent.click(screen.getByText("2. Phân Bổ Lưu Trữ (Topology)"));

    expect(await screen.findByText("Hiện Trạng Hạ Tầng Lưu Trữ Đa Tầng")).toBeTruthy();
    expect(screen.getByText("PostgreSQL 17")).toBeTruthy();

    // Click Run Audit button
    const auditBtn = screen.getByText("Chạy Đối Soát Nhất Quán (Audit)");
    fireEvent.click(auditBtn);

    expect(mockRunConsistencyAudit).toHaveBeenCalled();
    expect(await screen.findByText(/Điểm nhất quán 100%/i)).toBeTruthy();
  });

  it("tests retrieval sandbox on Chunks tab", async () => {
    mockTestRetrieval.mockResolvedValueOnce({
      query: "kiến trúc hệ thống",
      took_ms: 15.4,
      results: [
        {
          spec_ids: ["PKB-01"],
          headings: ["# 1. Giới thiệu"],
          source: "vector",
          score: 0.895,
          text_preview: "Nội dung trích đoạn liên quan đến kiến trúc.",
        },
      ],
    });

    render(<DataManagementHubPage />);

    await screen.findByText("Kiến trúc Tổng thể Personal-KB");

    // Switch to Chunks & Sandbox tab
    fireEvent.click(screen.getByText("3. Khám Phá Chunks & Sandbox"));

    expect(await screen.findByText(/Retrieval Testing Sandbox/i)).toBeTruthy();

    const queryInput = screen.getByPlaceholderText("Nhập câu hỏi test: vd. 'Quy trình Ingestion hoạt động ra sao?'");
    fireEvent.change(queryInput, { target: { value: "kiến trúc hệ thống" } });

    const submitBtn = screen.getByText("Test Truy Hồi");
    fireEvent.click(submitBtn);

    expect(mockTestRetrieval).toHaveBeenCalledWith("kiến trúc hệ thống", 5);
    expect(await screen.findByText("Nội dung trích đoạn liên quan đến kiến trúc.")).toBeTruthy();
    expect(screen.getByText(/Score: 89.5%/i)).toBeTruthy();
  });

  it("supports multi-project segmented filter tabs and displays project badges", async () => {
    mockListCatalog.mockResolvedValueOnce({
      total_specs: 2,
      total_chunks: 10,
      storage_backend: "PostgreSQL 17 + pgvector",
      projects: ["Personal-KB", "Demo-Core"],
      project_counts: { "Personal-KB": 1, "Demo-Core": 1 },
      items: [
        {
          spec_id: "PKB-01",
          title: "Kiến trúc Tổng thể Personal-KB",
          project_id: "Personal-KB",
          file_name: "PKB-01.md",
          file_size_bytes: 4096,
          chunk_count: 5,
          in_vector_db: true,
          in_documents: true,
          last_modified: "2026-10-20T00:00:00Z",
        },
        {
          spec_id: "HR-M04",
          title: "Đặc tả Tính lương HRM",
          project_id: "Demo-Core",
          file_name: "HR-M04.md",
          file_size_bytes: 2048,
          chunk_count: 5,
          in_vector_db: true,
          in_documents: true,
          last_modified: "2026-10-20T01:00:00Z",
        },
      ],
    });

    render(<DataManagementHubPage />);

    expect(await screen.findByText("Kiến trúc Tổng thể Personal-KB")).toBeTruthy();
    expect(screen.getAllByText("Demo-Core").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("Đặc tả Tính lương HRM")).toBeTruthy();

    // Verify project badges exist
    const pkbBadges = screen.getAllByText("Personal-KB");
    expect(pkbBadges.length).toBeGreaterThanOrEqual(1);

    // Click project tab "Demo-Core"
    const hrmTab = screen.getByRole("button", { name: /Demo-Core/i });
    fireEvent.click(hrmTab);
    expect(mockListCatalog).toHaveBeenCalledWith("Demo-Core");
  });

  it("deletes a document only after confirming in the in-app dialog", async () => {
    const nativeConfirm = vi.spyOn(window, "confirm");
    mockDeleteDocument.mockResolvedValueOnce({ message: "Đã xoá PKB-01" });

    render(<DataManagementHubPage />);
    await screen.findByText("Kiến trúc Tổng thể Personal-KB");

    fireEvent.click(screen.getAllByTitle("Xoá tài liệu")[0]);
    const dialog = screen.getByRole("alertdialog");
    expect(dialog.textContent).toContain("PKB-01");
    expect(mockDeleteDocument).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole("button", { name: /^Xoá tài liệu$/ }));

    expect(nativeConfirm).not.toHaveBeenCalled();
    expect(mockDeleteDocument).toHaveBeenCalledWith("PKB-01");
    expect(await screen.findByText("Đã xoá PKB-01")).toBeTruthy();
  });
});
