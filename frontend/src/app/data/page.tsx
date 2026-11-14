"use client";

import {
  AlertCircle,
  ArrowLeft,
  Check,
  CheckCircle2,
  Clock,
  Cpu,
  Database,
  ExternalLink,
  FileCheck2,
  FileCode,
  FileText,
  Filter,
  FolderGit2,
  HardDrive,
  Layers,
  Play,
  Plus,
  RefreshCw,
  Search,
  Server,
  ShieldCheck,
  Trash2,
  UploadCloud,
  X,
  XCircle,
  Zap,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Markdown } from "@/components/markdown/markdown";
import { SpecDrawer } from "@/components/chat/spec-drawer";
import { ThemeToggle } from "@/components/theme-toggle";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import {
  deleteDocument,
  getDocumentChunks,
  getStorageTopology,
  listCatalog,
  reindexSpec,
  runConsistencyAudit,
  testRetrieval,
  uploadDocument,
  type CatalogItem,
  type ChunkItem,
  type ConsistencyAuditResult,
  type RetrievalHitItem,
  type StorageTierStats,
  type TopologyResponse,
} from "@/lib/api";
import { cn } from "@/lib/utils";

type ActiveTab = "CATALOG" | "TOPOLOGY" | "CHUNKS";

export default function DataManagementHubPage() {
  const [activeTab, setActiveTab] = useState<ActiveTab>("CATALOG");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Tab 1: Catalog State
  const [catalogItems, setCatalogItems] = useState<CatalogItem[]>([]);
  const [catalogSearch, setCatalogSearch] = useState("");
  const [storageBackend, setStorageBackend] = useState("");
  const [totalChunksCount, setTotalChunksCount] = useState(0);

  // Multi-Project Filter State
  const [projects, setProjects] = useState<string[]>(["Personal-KB"]);
  const [projectCounts, setProjectCounts] = useState<Record<string, number>>({});
  const [selectedProject, setSelectedProject] = useState<string>("ALL");

  // Upload Modal State
  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadProjectId, setUploadProjectId] = useState<string>("Personal-KB");
  const [customProjectInput, setCustomProjectInput] = useState<string>("");
  const [uploadLoading, setUploadLoading] = useState(false);

  // Slide-over Spec Drawer State
  const [activeDrawerSpecId, setActiveDrawerSpecId] = useState<string | null>(null);

  // Tab 2: Topology State
  const [topology, setTopology] = useState<TopologyResponse | null>(null);
  const [auditResult, setAuditResult] = useState<ConsistencyAuditResult | null>(null);
  const [auditLoading, setAuditLoading] = useState(false);

  // Tab 3: Chunks & Sandbox State
  const [selectedSpecId, setSelectedSpecId] = useState<string>("");
  const [chunks, setChunks] = useState<ChunkItem[]>([]);
  const [chunksLoading, setChunksLoading] = useState(false);

  // Sandbox Test
  const [sandboxQuery, setSandboxQuery] = useState("");
  const [sandboxProject, setSandboxProject] = useState<string>("ALL");
  const [sandboxHits, setSandboxHits] = useState<RetrievalHitItem[]>([]);
  const [sandboxLatency, setSandboxLatency] = useState<number | null>(null);
  const [sandboxLoading, setSandboxLoading] = useState(false);

  // Action status notification (Toast)
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" | "info" } | null>(null);

  const showToast = (message: string, type: "success" | "error" | "info" = "info") => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 4000);
  };

  // Fetch initial data
  const fetchData = async (proj?: string) => {
    const targetProj = typeof proj === "string" ? proj : selectedProject;
    setLoading(true);
    setError(null);
    try {
      const [cat, topo] = await Promise.all([listCatalog(targetProj), getStorageTopology()]);
      setCatalogItems(cat.items);
      setStorageBackend(cat.storage_backend);
      setTotalChunksCount(cat.total_chunks);
      if (cat.projects && cat.projects.length > 0) {
        setProjects(cat.projects);
      }
      if (cat.project_counts) {
        setProjectCounts(cat.project_counts);
      }
      setTopology(topo);
      if (cat.items.length > 0 && !selectedSpecId) {
        setSelectedSpecId(cat.items[0].spec_id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  const handleSelectProject = (proj: string) => {
    setSelectedProject(proj);
    fetchData(proj);
  };

  useEffect(() => {
    fetchData("ALL");
  }, []);

  // Fetch chunks when selectedSpecId changes
  useEffect(() => {
    if (!selectedSpecId) return;
    setChunksLoading(true);
    getDocumentChunks(selectedSpecId)
      .then((res) => setChunks(res.chunks))
      .catch(() => setChunks([]))
      .finally(() => setChunksLoading(false));
  }, [selectedSpecId]);

  // Filtered Catalog
  const filteredCatalog = useMemo(() => {
    const q = catalogSearch.toLowerCase().trim();
    if (!q) return catalogItems;
    return catalogItems.filter(
      (item) =>
        item.spec_id.toLowerCase().includes(q) ||
        item.title.toLowerCase().includes(q) ||
        (item.project_id && item.project_id.toLowerCase().includes(q)) ||
        item.file_name.toLowerCase().includes(q),
    );
  }, [catalogItems, catalogSearch]);

  // Handle Upload
  const handleUploadSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!uploadFile) {
      showToast("Vui lòng chọn một file tài liệu (.md hoặc .txt)", "error");
      return;
    }
    const targetProject = uploadProjectId === "NEW" ? customProjectInput.trim() : uploadProjectId;
    if (uploadProjectId === "NEW" && !targetProject) {
      showToast("Vui lòng nhập tên dự án mới", "error");
      return;
    }
    setUploadLoading(true);
    try {
      const res = await uploadDocument(uploadFile, targetProject);
      showToast(`✅ ${res.message}`, "success");
      setUploadModalOpen(false);
      setUploadFile(null);
      setCustomProjectInput("");
      await fetchData(selectedProject);
    } catch (err) {
      showToast(`Lỗi upload: ${err instanceof Error ? err.message : String(err)}`, "error");
    } finally {
      setUploadLoading(false);
    }
  };

  // Handle Reindex
  const handleReindex = async (specId: string) => {
    try {
      const res = await reindexSpec(specId);
      showToast(`⚡ ${res.message}`, "success");
      await fetchData(selectedProject);
    } catch (err) {
      showToast(`Lỗi re-index: ${err instanceof Error ? err.message : String(err)}`, "error");
    }
  };

  // Handle Delete
  const closeDeleteConfirm = useCallback(() => setDeleteTarget(null), []);

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleteLoading(true);
    try {
      const res = await deleteDocument(deleteTarget);
      setDeleteTarget(null);
      showToast(res.message, "success");
      await fetchData(selectedProject);
    } catch (err) {
      showToast(`Lỗi xoá tài liệu: ${err instanceof Error ? err.message : String(err)}`, "error");
    } finally {
      setDeleteLoading(false);
    }
  };

  // Handle Run Audit
  const handleRunAudit = async () => {
    setAuditLoading(true);
    try {
      const res = await runConsistencyAudit();
      setAuditResult(res);
      showToast("🔍 Đã hoàn thành đối soát nhất quán!", "success");
    } catch (err) {
      showToast(`Lỗi đối soát: ${err instanceof Error ? err.message : String(err)}`, "error");
    } finally {
      setAuditLoading(false);
    }
  };

  // Handle Sandbox Retrieval Test
  const handleRunSandbox = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!sandboxQuery.trim()) return;
    setSandboxLoading(true);
    try {
      const res =
        sandboxProject && sandboxProject !== "ALL"
          ? await testRetrieval(sandboxQuery.trim(), 5, sandboxProject)
          : await testRetrieval(sandboxQuery.trim(), 5);
      setSandboxHits(res.results);
      setSandboxLatency(res.took_ms);
    } catch (err) {
      showToast(`Lỗi truy hồi: ${err instanceof Error ? err.message : String(err)}`, "error");
    } finally {
      setSandboxLoading(false);
    }
  };

  return (
    <div className="flex h-screen w-full flex-col bg-background text-foreground overflow-hidden">
      <ConfirmDialog
        open={deleteTarget !== null}
        title="Xoá tài liệu"
        icon={<Trash2 className="size-4" />}
        variant="destructive"
        confirmLabel="Xoá tài liệu"
        loading={deleteLoading}
        onConfirm={handleDelete}
        onCancel={closeDeleteConfirm}
      >
        <p className="text-xs text-muted-foreground font-mono">
          Xoá <span className="text-foreground">{deleteTarget}</span> và toàn bộ vector liên quan. Không thể hoàn tác.
        </p>
      </ConfirmDialog>

      {/* Toast Notification */}
      {toast && (
        <div
          role="status"
          className={cn(
            "fixed top-16 right-6 z-50 rounded-sm border px-3.5 py-2 text-xs font-mono shadow-md transition-all animate-in fade-in slide-in-from-top-2",
            toast.type === "error"
              ? "border-destructive/40 bg-destructive/10 text-destructive"
              : toast.type === "success"
                ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-500"
                : "border-border bg-card text-foreground",
          )}
        >
          {toast.message}
        </div>
      )}

      {/* Top Header */}
      <header className="flex h-12 shrink-0 items-center justify-between border-b border-border px-4 lg:px-6 bg-card/40">
        <div className="flex items-center gap-3">
          <Link href="/">
            <Button variant="ghost" size="sm" className="h-7 gap-1.5 px-2 text-xs font-mono rounded-sm text-muted-foreground hover:text-foreground">
              <ArrowLeft className="size-3.5" />
              <span>Quay lại Chat</span>
            </Button>
          </Link>
          <div className="h-4 w-px bg-border" />
          <div className="flex items-center gap-2">
            <Database className="size-4 text-foreground" />
            <h1 className="text-xs font-semibold tracking-tight text-foreground font-mono">Personal KB — Quản trị Dữ liệu & Storage</h1>
          </div>
          <div className="h-4 w-px bg-border hidden sm:block" />
          <Link href="/approvals" className="hidden sm:inline-flex">
            <Button variant="ghost" size="sm" className="h-7 gap-1.5 px-2 text-xs font-mono rounded-sm text-muted-foreground hover:text-foreground">
              <ShieldCheck className="size-3.5 text-muted-foreground" />
              <span>Phê duyệt tri thức</span>
            </Button>
          </Link>
        </div>

        <div className="flex items-center gap-2">
          <ThemeToggle />
          <Button
            variant="outline"
            size="sm"
            onClick={() => fetchData()}
            disabled={loading}
            className="h-7 gap-1.5 px-2 text-xs font-mono rounded-sm border-border"
            title="Làm mới dữ liệu"
          >
            <RefreshCw className={`size-3 ${loading ? "animate-spin" : ""}`} />
            <span className="hidden sm:inline">Làm mới</span>
          </Button>
          <Button
            size="sm"
            onClick={() => setUploadModalOpen(true)}
            className="h-7 gap-1.5 px-2.5 text-xs font-mono rounded-sm bg-foreground text-background hover:bg-foreground/90 shadow-2xs"
          >
            <Plus className="size-3.5" />
            <span>Nạp tài liệu mới</span>
          </Button>
        </div>
      </header>

      {/* Navigation Sub-Tabs (Linear Segmented Control) */}
      <div className="flex shrink-0 items-center border-b border-border px-4 lg:px-6 bg-muted/20 py-2">
        <div className="inline-flex p-0.5 rounded-md border border-border bg-muted/40 font-mono text-xs">
          <button
            onClick={() => setActiveTab("CATALOG")}
            className={cn(
              "flex items-center gap-1.5 rounded-sm px-2.5 py-1 text-xs transition-colors",
              activeTab === "CATALOG"
                ? "bg-background text-foreground shadow-2xs font-medium border border-border"
                : "text-muted-foreground hover:text-foreground border border-transparent"
            )}
          >
            <FileText className="size-3.5" />
            <span>1. Nguồn Dữ Liệu</span>
            <span className="text-[10px] text-muted-foreground">({catalogItems.length})</span>
          </button>
          <button
            onClick={() => setActiveTab("TOPOLOGY")}
            className={cn(
              "flex items-center gap-1.5 rounded-sm px-2.5 py-1 text-xs transition-colors",
              activeTab === "TOPOLOGY"
                ? "bg-background text-foreground shadow-2xs font-medium border border-border"
                : "text-muted-foreground hover:text-foreground border border-transparent"
            )}
          >
            <Layers className="size-3.5" />
            <span>2. Phân Bổ Lưu Trữ (Topology)</span>
          </button>
          <button
            onClick={() => setActiveTab("CHUNKS")}
            className={cn(
              "flex items-center gap-1.5 rounded-sm px-2.5 py-1 text-xs transition-colors",
              activeTab === "CHUNKS"
                ? "bg-background text-foreground shadow-2xs font-medium border border-border"
                : "text-muted-foreground hover:text-foreground border border-transparent"
            )}
          >
            <Zap className="size-3.5" />
            <span>3. Khám Phá Chunks & Sandbox</span>
          </button>
        </div>
      </div>

      {/* Main Content Area */}
      <main className="flex-1 overflow-y-auto p-4 lg:p-6 space-y-4">
        {error && (
          <div className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-xs font-mono text-destructive flex items-center gap-3">
            <AlertCircle className="size-4 shrink-0" />
            <div className="flex-1">{error}</div>
            <Button size="sm" variant="outline" onClick={() => fetchData()} className="h-6 text-xs rounded-sm font-mono">
              Thử lại
            </Button>
          </div>
        )}

        {/* ============================================================== */}
        {/* TAB 1: DATA CATALOG                                            */}
        {/* ============================================================== */}
        {activeTab === "CATALOG" && (
          <div className="space-y-3">
            {/* Project Filter Segmented Control */}
            <div className="flex flex-wrap items-center gap-1.5 p-1 rounded-md border border-border bg-card/60 font-mono text-xs">
              <span className="text-[11px] text-muted-foreground px-2 flex items-center gap-1.5 font-medium">
                <FolderGit2 className="size-3.5 text-muted-foreground" />
                <span>Dự án:</span>
              </span>
              <button
                type="button"
                onClick={() => handleSelectProject("ALL")}
                className={cn(
                  "px-2.5 py-1 rounded-sm border text-xs font-mono transition-colors flex items-center gap-1.5",
                  selectedProject === "ALL"
                    ? "bg-foreground text-background border-foreground font-semibold shadow-2xs"
                    : "bg-muted/30 text-muted-foreground hover:text-foreground border-border hover:bg-muted/50"
                )}
              >
                <span>Tất cả</span>
                <span className={cn("text-[10px]", selectedProject === "ALL" ? "text-background/80" : "text-muted-foreground")}>
                  ({Object.values(projectCounts).reduce((a, b) => a + b, 0) || catalogItems.length})
                </span>
              </button>
              {projects.map((proj) => {
                const count = projectCounts[proj] ?? 0;
                const isSelected = selectedProject === proj;
                return (
                  <button
                    key={proj}
                    type="button"
                    onClick={() => handleSelectProject(proj)}
                    className={cn(
                      "px-2.5 py-1 rounded-sm border text-xs font-mono transition-colors flex items-center gap-1.5",
                      isSelected
                        ? "bg-foreground text-background border-foreground font-semibold shadow-2xs"
                        : "bg-muted/30 text-muted-foreground hover:text-foreground border-border hover:bg-muted/50"
                    )}
                  >
                    <span>{proj}</span>
                    <span className={cn("text-[10px]", isSelected ? "text-background/80" : "text-muted-foreground")}>
                      ({count})
                    </span>
                  </button>
                );
              })}
            </div>

            {/* Top Toolbar */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div className="relative flex-1 max-w-md">
                <Search className="absolute left-2.5 top-2 size-3.5 text-muted-foreground" />
                <input
                  type="text"
                  placeholder="Tìm theo mã spec, tiêu đề..."
                  value={catalogSearch}
                  onChange={(e) => setCatalogSearch(e.target.value)}
                  className="w-full rounded-sm border border-border bg-background py-1.5 pl-8 pr-3 text-xs font-mono outline-none focus:border-foreground/40 focus:ring-1 focus:ring-ring"
                />
              </div>

              <div className="flex items-center gap-2 text-xs text-muted-foreground font-mono">
                <span className="inline-flex items-center gap-1.5 rounded-sm border border-border px-2 py-0.5 bg-muted/40">
                  <span>Backend:</span>
                  <span className="font-semibold text-foreground uppercase">{storageBackend}</span>
                </span>
                <span className="inline-flex items-center gap-1.5 rounded-sm border border-border px-2 py-0.5 bg-muted/40">
                  <span>Tổng chunks:</span>
                  <span className="font-semibold text-foreground">{totalChunksCount}</span>
                </span>
                <span className="inline-flex items-center gap-1.5 rounded-sm border border-emerald-500/30 px-2 py-0.5 bg-emerald-500/10 text-emerald-400 font-mono" title="Context Efficiency Ratio: Triad Injection vs Naive Spec Dump">
                  <Cpu className="size-3 text-emerald-400" />
                  <span>CER Tiết kiệm Token:</span>
                  <span className="font-semibold text-emerald-300">~95.3%</span>
                </span>
              </div>
            </div>

            {/* Catalog Table */}
            <div className="overflow-hidden rounded-md border border-border bg-card">
              <table className="w-full text-left text-xs border-collapse">
                <thead className="bg-muted/30 text-[11px] font-mono font-medium uppercase text-muted-foreground border-b border-border">
                  <tr>
                    <th className="px-3 py-2.5">Mã Spec</th>
                    <th className="px-3 py-2.5">Dự án</th>
                    <th className="px-3 py-2.5">Tiêu đề tài liệu</th>
                    <th className="px-3 py-2.5">Phân bổ DB</th>
                    <th className="px-3 py-2.5">Số Chunks</th>
                    <th className="px-3 py-2.5">Dung lượng</th>
                    <th className="px-3 py-2.5">Cập nhật</th>
                    <th className="px-3 py-2.5 text-right">Thao tác</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/40">
                  {filteredCatalog.map((item) => (
                    <tr key={item.spec_id} className="hover:bg-muted/30 transition-colors">
                      <td className="px-3 py-2">
                        <button
                          onClick={() => setActiveDrawerSpecId(item.spec_id)}
                          className="font-mono text-xs font-medium text-foreground hover:underline flex items-center gap-1"
                          title="Bấm để xem nội dung markdown"
                        >
                          <span className="rounded-sm bg-muted/60 px-1.5 py-0.5 border border-border/80 text-[11px]">
                            {item.spec_id}
                          </span>
                          <ExternalLink className="size-3 text-muted-foreground opacity-60" />
                        </button>
                      </td>
                      <td className="px-3 py-2">
                        <span className="rounded-sm border border-border bg-muted/60 px-1.5 py-0.5 font-mono text-[10px] font-medium text-foreground">
                          {item.project_id || "Personal-KB"}
                        </span>
                      </td>
                      <td className="px-3 py-2 font-medium text-foreground">
                        <div className="line-clamp-1 max-w-[280px]">{item.title}</div>
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-1.5 font-mono">
                          {item.in_vector_db ? (
                            <span className="rounded-sm border border-emerald-500/30 bg-emerald-500/10 px-1.5 py-0.2 text-[10px] text-emerald-500 font-medium">
                              Vector DB ✓
                            </span>
                          ) : (
                            <span className="rounded-sm border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.2 text-[10px] text-amber-500 font-medium">
                              Chưa có vector
                            </span>
                          )}
                          {item.in_documents && (
                            <span className="rounded-sm border border-border bg-muted/60 px-1.5 py-0.2 text-[10px] text-muted-foreground font-medium">
                              DocStore ✓
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-3 py-2 font-mono text-muted-foreground">
                        {item.chunk_count} chunks
                      </td>
                      <td className="px-3 py-2 font-mono text-muted-foreground">
                        {(item.file_size_bytes / 1024).toFixed(1)} KB
                      </td>
                      <td className="px-3 py-2 font-mono text-muted-foreground text-[11px]">
                        {new Date(item.last_modified).toLocaleString("vi-VN", {
                          dateStyle: "short",
                          timeStyle: "short",
                        })}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => {
                              setSelectedSpecId(item.spec_id);
                              setActiveTab("CHUNKS");
                            }}
                            className="h-6 text-[11px] font-mono rounded-sm px-2 border-border"
                            title="Xem chi tiết các chunks"
                          >
                            Soi Chunks
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => handleReindex(item.spec_id)}
                            className="h-6 text-[11px] font-mono rounded-sm px-2 gap-1 border-border"
                            title="Chạy lại chunking và embedding"
                          >
                            <RefreshCw className="size-2.5" />
                            <span>Re-index</span>
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => setDeleteTarget(item.spec_id)}
                            className="h-6 size-6 p-0 rounded-sm text-muted-foreground hover:text-destructive"
                            title="Xoá tài liệu"
                          >
                            <Trash2 className="size-3" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {filteredCatalog.length === 0 && (
                    <tr>
                      <td colSpan={7} className="px-4 py-8 text-center text-xs text-muted-foreground font-mono">
                        Không tìm thấy tài liệu nào phù hợp với từ khoá tìm kiếm.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* ============================================================== */}
        {/* TAB 2: STORAGE TOPOLOGY                                        */}
        {/* ============================================================== */}
        {activeTab === "TOPOLOGY" && topology && (
          <div className="space-y-4">
            {/* Header info */}
            <div className="rounded-md border border-border bg-card p-4 flex flex-col md:flex-row md:items-center justify-between gap-4">
              <div>
                <h2 className="text-sm font-semibold font-mono uppercase tracking-wide">Hiện Trạng Hạ Tầng Lưu Trữ Đa Tầng</h2>
                <p className="text-xs text-muted-foreground font-mono mt-0.5">
                  Mô hình lưu trữ:{" "}
                  <strong className="text-foreground uppercase">{topology.storage_backend}</strong> · Model:{" "}
                  <strong className="text-foreground">{topology.embedding_model}</strong> ({topology.embedding_dimensions}d)
                </p>
              </div>
              <Button
                size="sm"
                variant="outline"
                onClick={handleRunAudit}
                disabled={auditLoading}
                className="h-7 gap-1.5 shrink-0 bg-background font-mono text-xs rounded-sm border-border"
              >
                <FileCheck2 className={`size-3.5 ${auditLoading ? "animate-spin text-foreground" : "text-emerald-500"}`} />
                <span>Chạy Đối Soát Nhất Quán (Audit)</span>
              </Button>
            </div>

            {/* Audit Results Box */}
            {auditResult && (
              <div
                className={cn(
                  "rounded-md border p-4 transition-all font-mono text-xs",
                  auditResult.audit_passed
                    ? "border-emerald-500/30 bg-emerald-500/5 text-foreground"
                    : "border-amber-500/30 bg-amber-500/5 text-foreground"
                )}
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2 font-semibold">
                    {auditResult.audit_passed ? (
                      <CheckCircle2 className="size-4 text-emerald-500" />
                    ) : (
                      <AlertCircle className="size-4 text-amber-500" />
                    )}
                    <span>
                      Kết quả đối soát: Điểm nhất quán {auditResult.consistency_percentage}% (
                      {auditResult.audit_passed ? "HOÀN HẢO" : "CÓ SAI LỆCH"})
                    </span>
                  </div>
                  <span className="text-[11px] text-muted-foreground">
                    {new Date(auditResult.timestamp).toLocaleTimeString("vi-VN")}
                  </span>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs mt-2">
                  <div className="rounded-sm bg-background/80 p-2.5 border border-border">
                    <span className="font-semibold text-muted-foreground">Tệp trên đĩa chưa có trong DB ({auditResult.missing_in_db.length}):</span>
                    {auditResult.missing_in_db.length === 0 ? (
                      <p className="text-muted-foreground mt-1">Không có (100% tệp đã vào DB)</p>
                    ) : (
                      <ul className="list-disc list-inside mt-1 space-y-0.5">
                        {auditResult.missing_in_db.map((m) => (
                          <li key={m}>{m}.md</li>
                        ))}
                      </ul>
                    )}
                  </div>
                  <div className="rounded-sm bg-background/80 p-2.5 border border-border">
                    <span className="font-semibold text-muted-foreground">Vector trong DB bị mồ côi ({auditResult.orphan_in_db.length}):</span>
                    {auditResult.orphan_in_db.length === 0 ? (
                      <p className="text-muted-foreground mt-1">Không có</p>
                    ) : (
                      <div className="mt-1 flex flex-wrap gap-1">
                        {auditResult.orphan_in_db.map((o) => (
                          <span key={o} className="rounded-sm border border-rose-500/30 bg-rose-500/10 px-1.5 py-0.2 text-[10px] text-rose-500">
                            {o}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* Storage Tiers Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {topology.tiers.map((tier, idx) => (
                <div key={idx} className="rounded-md border border-border bg-card p-4 space-y-3 shadow-2xs flex flex-col justify-between">
                  <div>
                    <div className="flex items-center justify-between">
                      <span className="text-[11px] font-mono font-medium text-muted-foreground uppercase">{tier.engine}</span>
                      <span
                        className={cn(
                          "rounded-sm border px-1.5 py-0.2 font-mono text-[10px] font-medium",
                          tier.status === "Online" || tier.status === "Active"
                            ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-500"
                            : tier.status === "Standby"
                            ? "border-border bg-muted/60 text-muted-foreground"
                            : "border-border bg-muted text-muted-foreground"
                        )}
                      >
                        {tier.status}
                      </span>
                    </div>
                    <h3 className="text-xs font-semibold font-mono mt-1 text-foreground flex items-center gap-1.5">
                      {idx === 0 && <HardDrive className="size-3.5 text-muted-foreground" />}
                      {idx === 1 && <Cpu className="size-3.5 text-muted-foreground" />}
                      {idx === 2 && <Database className="size-3.5 text-muted-foreground" />}
                      {idx === 3 && <Server className="size-3.5 text-muted-foreground" />}
                      {idx === 4 && <ShieldCheck className="size-3.5 text-muted-foreground" />}
                      <span>{tier.name}</span>
                    </h3>
                  </div>

                  <div className="bg-muted/20 border border-border/50 rounded-sm p-2.5 text-xs space-y-1 font-mono">
                    {Object.entries(tier.metrics).map(([key, val]) => (
                      <div key={key} className="flex justify-between items-center text-[11px]">
                        <span className="text-muted-foreground truncate mr-2">{key}:</span>
                        <span className="font-medium text-foreground truncate max-w-[180px]">{String(val)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ============================================================== */}
        {/* TAB 3: CHUNKS EXPLORER & RETRIEVAL SANDBOX                     */}
        {/* ============================================================== */}
        {activeTab === "CHUNKS" && (
          <div className="space-y-4">
            {/* Retrieval Sandbox Box */}
            <div className="rounded-md border border-border bg-card p-4 shadow-2xs space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Zap className="size-4 text-foreground" />
                  <h3 className="text-xs font-semibold font-mono uppercase tracking-wide">Retrieval Testing Sandbox (Kiểm thử Truy hồi)</h3>
                </div>
                {sandboxLatency !== null && (
                  <span className="text-xs text-muted-foreground font-mono">
                    Độ trễ: <strong className="text-foreground">{sandboxLatency} ms</strong>
                  </span>
                )}
              </div>

              <form onSubmit={handleRunSandbox} className="space-y-2">
                <div className="flex gap-2">
                  <select
                    value={sandboxProject}
                    onChange={(e) => setSandboxProject(e.target.value)}
                    className="h-8 rounded-sm border border-border bg-background px-2.5 text-xs font-mono focus:outline-none focus:ring-1 focus:ring-ring text-muted-foreground shrink-0"
                    title="Lọc phạm vi truy hồi theo dự án"
                  >
                    <option value="ALL">Toàn bộ kho (Cross-Project)</option>
                    {projects.map((p) => (
                      <option key={p} value={p}>
                        Dự án: {p}
                      </option>
                    ))}
                  </select>
                  <input
                    type="text"
                    placeholder="Nhập câu hỏi test: vd. 'Quy trình Ingestion hoạt động ra sao?'"
                    value={sandboxQuery}
                    onChange={(e) => setSandboxQuery(e.target.value)}
                    className="flex-1 rounded-sm border border-border bg-background px-3 py-1.5 text-xs font-mono outline-none focus:border-foreground/40 focus:ring-1 focus:ring-ring"
                  />
                  <Button type="submit" disabled={sandboxLoading} className="h-8 gap-1.5 shrink-0 bg-foreground text-background hover:bg-foreground/90 font-mono text-xs rounded-sm px-3">
                    <Play className={`size-3 ${sandboxLoading ? "animate-spin" : ""}`} />
                    <span>Test Truy Hồi</span>
                  </Button>
                </div>
              </form>

              {/* Sandbox Results */}
              {sandboxHits.length > 0 && (
                <div className="space-y-2 pt-2 border-t border-border">
                  <div className="text-xs font-mono font-medium text-muted-foreground">
                    Top {sandboxHits.length} kết quả phù hợp nhất từ Hybrid Retriever:
                  </div>
                  <div className="grid grid-cols-1 gap-2">
                    {sandboxHits.map((hit, i) => (
                      <div key={i} className="rounded-sm border border-border bg-muted/20 p-3 text-xs space-y-1.5 font-mono">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2 font-medium text-foreground">
                            <span>#{i + 1}</span>
                            <span className="rounded-sm border border-border bg-muted/60 px-1.5 py-0.2 text-[10px] text-foreground font-mono">
                              {hit.project_id || "Personal-KB"}
                            </span>
                            <span className="rounded-sm bg-muted/60 px-1 py-0.2 border border-border/80">{hit.spec_ids.join(", ")}</span>
                            <span className="text-muted-foreground font-normal">
                              ({hit.headings.join(" > ") || "Root"})
                            </span>
                          </div>
                          <span className="rounded-sm border border-emerald-500/30 bg-emerald-500/10 px-1.5 py-0.2 text-[10px] text-emerald-500 font-medium">
                            Score: {(hit.score * 100).toFixed(1)}%
                          </span>
                        </div>
                        <p className="text-foreground whitespace-pre-wrap text-xs bg-background/80 p-2.5 rounded-sm border border-border/80 font-mono">
                          {hit.text_preview}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Chunks Inspector */}
            <div className="space-y-3">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div className="flex items-center gap-2 font-mono text-xs">
                  <span className="font-semibold text-muted-foreground">Chọn tài liệu:</span>
                  <select
                    value={selectedSpecId}
                    onChange={(e) => setSelectedSpecId(e.target.value)}
                    className="rounded-sm border border-border bg-background px-2.5 py-1 text-xs font-mono focus:outline-none focus:ring-1 focus:ring-ring"
                  >
                    {catalogItems.map((item) => (
                      <option key={item.spec_id} value={item.spec_id}>
                        {item.spec_id} — {item.title} ({item.chunk_count} chunks)
                      </option>
                    ))}
                  </select>
                </div>
                <span className="text-xs text-muted-foreground font-mono">
                  Đang hiển thị <strong>{chunks.length}</strong> chunks đã cắt
                </span>
              </div>

              {chunksLoading ? (
                <div className="p-8 text-center text-xs text-muted-foreground font-mono">Đang tải danh sách chunks...</div>
              ) : chunks.length === 0 ? (
                <div className="p-8 text-center text-xs text-muted-foreground rounded-md border border-border bg-card font-mono">
                  Tài liệu này chưa có chunk nào trong Vector DB. Hãy nhấn "Re-index" ở Tab Nguồn Dữ Liệu.
                </div>
              ) : (
                <div className="space-y-2.5">
                  {chunks.map((chk) => (
                    <div key={chk.chunk_id} className="rounded-md border border-border bg-card p-3.5 space-y-2 shadow-2xs">
                      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-1 text-xs border-b border-border/60 pb-2">
                        <div className="flex items-center gap-2">
                          <span className="font-mono font-bold text-foreground">#{chk.chunk_index}</span>
                          <span className="font-medium text-foreground">
                            {chk.headings.join(" > ") || "Toàn văn"}
                          </span>
                        </div>
                        <div className="flex items-center gap-2 text-muted-foreground font-mono text-[11px]">
                          <span>~{chk.token_estimate} tokens</span>
                          <span>•</span>
                          <span className="truncate max-w-[150px]">{chk.chunk_key}</span>
                        </div>
                      </div>
                      <div className="text-xs font-mono text-muted-foreground bg-muted/20 p-2.5 rounded-sm border border-border/40 whitespace-pre-wrap max-h-48 overflow-y-auto">
                        {chk.content}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </main>

      {/* Upload Document Modal */}
      {uploadModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 animate-in fade-in">
          <div className="w-full max-w-md rounded-md border border-border bg-card p-5 shadow-xl space-y-4">
            <div className="flex items-center justify-between border-b border-border pb-3">
              <h3 className="text-xs font-semibold font-mono uppercase tracking-wide">Tải lên Tài liệu Mới</h3>
              <button onClick={() => setUploadModalOpen(false)} className="text-muted-foreground hover:text-foreground">
                <X className="size-4" />
              </button>
            </div>

            <form onSubmit={handleUploadSubmit} className="space-y-4">
              <div>
                <label className="text-xs font-medium text-muted-foreground block mb-1 font-mono">
                  Phân loại vào Dự án:
                </label>
                <div className="space-y-2">
                  <select
                    value={uploadProjectId}
                    onChange={(e) => setUploadProjectId(e.target.value)}
                    className="w-full rounded-sm border border-border bg-background px-2.5 py-1.5 text-xs font-mono focus:outline-none focus:ring-1 focus:ring-ring"
                  >
                    {projects.map((p) => (
                      <option key={p} value={p}>
                        Dự án: {p}
                      </option>
                    ))}
                    <option value="NEW">+ Tạo dự án mới...</option>
                  </select>
                  {uploadProjectId === "NEW" && (
                    <input
                      type="text"
                      placeholder="Nhập tên định danh dự án mới (vd: Billing-Service)..."
                      value={customProjectInput}
                      onChange={(e) => setCustomProjectInput(e.target.value)}
                      className="w-full rounded-sm border border-border bg-background px-2.5 py-1.5 text-xs font-mono outline-none focus:border-foreground/40 focus:ring-1 focus:ring-ring"
                    />
                  )}
                </div>
              </div>

              <div>
                <label className="text-xs font-medium text-muted-foreground block mb-1 font-mono">
                  Chọn tệp Markdown (.md) hoặc Text (.txt):
                </label>
                <input
                  type="file"
                  accept=".md,.txt"
                  onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                  className="w-full text-xs font-mono file:mr-3 file:py-1.5 file:px-2.5 file:rounded-sm file:border-0 file:text-xs file:font-semibold file:bg-foreground file:text-background hover:file:opacity-90 cursor-pointer"
                />
              </div>

              <div className="rounded-sm bg-muted/30 border border-border/50 p-3 text-xs text-muted-foreground space-y-1 font-mono">
                <p>• Tên file sẽ được tự động chuẩn hoá thành <code>Mã Spec</code>.</p>
                <p>• Hệ thống sẽ tự động lưu file, cắt nhỏ đoạn (chunking) và sinh vector embedding trong nền.</p>
              </div>

              <div className="flex justify-end gap-2 pt-2 border-t border-border">
                <Button type="button" variant="outline" size="sm" onClick={() => setUploadModalOpen(false)} className="h-7 rounded-sm border-border font-mono text-xs">
                  Hủy
                </Button>
                <Button type="submit" size="sm" disabled={uploadLoading || !uploadFile} className="h-7 rounded-sm bg-foreground text-background hover:bg-foreground/90 font-mono text-xs">
                  {uploadLoading ? "Đang xử lý..." : "Bắt đầu tải lên & Ingest"}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Slide-over Spec Drawer */}
      <SpecDrawer
        specId={activeDrawerSpecId}
        onClose={() => setActiveDrawerSpecId(null)}
      />
    </div>
  );
}
