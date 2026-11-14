"use client";

import {
  AlertCircle,
  ArrowLeft,
  Check,
  CheckCircle2,
  Clock,
  Database,
  ExternalLink,
  FileEdit,
  FilePlus,
  FileText,
  Filter,
  Plus,
  RefreshCw,
  Search,
  ShieldAlert,
  ShieldCheck,
  X,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Markdown } from "@/components/markdown/markdown";
import { ThemeToggle } from "@/components/theme-toggle";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  approveProposal,
  createProposal,
  listProposals,
  rejectProposal,
  type KnowledgeProposal,
} from "@/lib/api";
import { cn } from "@/lib/utils";

type FilterTab = "ALL" | "PENDING" | "APPROVED" | "REJECTED";

export default function ApprovalsPage() {
  const [proposals, setProposals] = useState<KnowledgeProposal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<FilterTab>("ALL");
  const [searchQuery, setSearchQuery] = useState("");

  // Modal view detail
  const [selectedProposal, setSelectedProposal] = useState<KnowledgeProposal | null>(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [rejectModalOpen, setRejectModalOpen] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [approveTarget, setApproveTarget] = useState<KnowledgeProposal | null>(null);
  const [forceApprove, setForceApprove] = useState(false);

  // Modal create proposal
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [newSpecId, setNewSpecId] = useState("HR-M04");
  const [newTitle, setNewTitle] = useState("");
  const [newSection, setNewSection] = useState("");
  const [newAction, setNewAction] = useState<"UPDATE_SECTION" | "CREATE_DOCUMENT" | "REPLACE_DOCUMENT">(
    "UPDATE_SECTION",
  );
  const [newRationale, setNewRationale] = useState("");
  const [newContent, setNewContent] = useState("");
  const [createLoading, setCreateLoading] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // Toast Notification
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" | "info" } | null>(null);

  const showToast = (message: string, type: "success" | "error" | "info" = "info") => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 4000);
  };

  const fetchProposals = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listProposals();
      setProposals(data);
      if (selectedProposal) {
        const updated = data.find((p) => p.id === selectedProposal.id);
        if (updated) setSelectedProposal(updated);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchProposals();
  }, []);

  // Metrics
  const counts = useMemo(() => {
    const total = proposals.length;
    const pending = proposals.filter((p) => p.status === "PENDING").length;
    const approved = proposals.filter((p) => p.status === "APPROVED").length;
    const rejected = proposals.filter((p) => p.status === "REJECTED").length;
    return { total, pending, approved, rejected };
  }, [proposals]);

  // Filtered list
  const filteredProposals = useMemo(() => {
    return proposals.filter((p) => {
      const matchesTab = activeTab === "ALL" || p.status === activeTab;
      const q = searchQuery.toLowerCase().trim();
      const matchesQuery =
        !q ||
        p.id.toLowerCase().includes(q) ||
        p.spec_id.toLowerCase().includes(q) ||
        p.title.toLowerCase().includes(q) ||
        p.rationale.toLowerCase().includes(q);
      return matchesTab && matchesQuery;
    });
  }, [proposals, activeTab, searchQuery]);

  // Handle Approve
  const openApproveConfirm = (proposal: KnowledgeProposal) => {
    setApproveTarget(proposal);
    setForceApprove(false);
  };

  const closeApproveConfirm = useCallback(() => setApproveTarget(null), []);

  const handleApproveSubmit = async () => {
    if (!approveTarget) return;
    // force is only sent when the reviewer explicitly overrides a flagged conflict.
    const force = Boolean(approveTarget.conflict_detected) && forceApprove;
    setActionLoading(true);
    try {
      const updated = await approveProposal(approveTarget.id, "Ryan Truong", force);
      setProposals((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
      if (selectedProposal?.id === updated.id) setSelectedProposal(updated);
      setApproveTarget(null);
      showToast(`Đã phê duyệt ${updated.id} cho ${updated.spec_id}.`, "success");
    } catch (err) {
      showToast(`Lỗi phê duyệt: ${err instanceof Error ? err.message : String(err)}`, "error");
    } finally {
      setActionLoading(false);
    }
  };

  // Handle Reject
  const handleRejectSubmit = async () => {
    if (!selectedProposal) return;
    if (!rejectReason.trim()) {
      showToast("Vui lòng nhập lý do từ chối đề xuất.", "error");
      return;
    }
    setActionLoading(true);
    try {
      const updated = await rejectProposal(selectedProposal.id, "Ryan Truong", rejectReason.trim());
      setProposals((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
      setSelectedProposal(updated);
      setRejectModalOpen(false);
      setRejectReason("");
      showToast("Đã từ chối đề xuất cập nhật tri thức.", "info");
    } catch (err) {
      showToast(`Lỗi: ${err instanceof Error ? err.message : String(err)}`, "error");
    } finally {
      setActionLoading(false);
    }
  };

  // Handle Create Proposal Submit
  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newSpecId.trim() || !newTitle.trim() || !newRationale.trim() || !newContent.trim()) {
      setCreateError("Vui lòng điền đầy đủ các trường bắt buộc.");
      return;
    }
    setCreateLoading(true);
    setCreateError(null);
    try {
      const created = await createProposal({
        spec_id: newSpecId.trim(),
        title: newTitle.trim(),
        section: newSection.trim(),
        action: newAction,
        rationale: newRationale.trim(),
        proposed_content: newContent.trim(),
      });
      setProposals((prev) => [created, ...prev]);
      setCreateModalOpen(false);
      setNewTitle("");
      setNewSection("");
      setNewRationale("");
      setNewContent("");
      setActiveTab("PENDING");
      setSelectedProposal(created);
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : String(err));
    } finally {
      setCreateLoading(false);
    }
  };

  const statusBadge = (status: KnowledgeProposal["status"]) => {
    switch (status) {
      case "PENDING":
        return (
          <span className="inline-flex items-center gap-1 rounded-sm border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.2 font-mono text-[10px] text-amber-500 font-medium">
            <Clock className="size-2.5" /> Chờ duyệt
          </span>
        );
      case "APPROVED":
        return (
          <span className="inline-flex items-center gap-1 rounded-sm border border-emerald-500/30 bg-emerald-500/10 px-1.5 py-0.2 font-mono text-[10px] text-emerald-500 font-medium">
            <CheckCircle2 className="size-2.5" /> Đã duyệt
          </span>
        );
      case "REJECTED":
        return (
          <span className="inline-flex items-center gap-1 rounded-sm border border-rose-500/30 bg-rose-500/10 px-1.5 py-0.2 font-mono text-[10px] text-rose-500 font-medium">
            <XCircle className="size-2.5" /> Đã từ chối
          </span>
        );
    }
  };

  return (
    <div className="flex h-screen w-full flex-col bg-background text-foreground overflow-hidden">
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
            <ShieldCheck className="size-4 text-foreground" />
            <h1 className="text-xs font-semibold tracking-tight text-foreground font-mono">Personal KB — Phê duyệt Tri thức</h1>
          </div>
          <div className="h-4 w-px bg-border hidden sm:block" />
          <Link href="/data" className="hidden sm:inline-flex">
            <Button variant="ghost" size="sm" className="h-7 gap-1.5 px-2 text-xs font-mono rounded-sm text-muted-foreground hover:text-foreground">
              <Database className="size-3.5 text-muted-foreground" />
              <span>Quản lý Dữ liệu</span>
            </Button>
          </Link>
        </div>

        <div className="flex items-center gap-2">
          <ThemeToggle />
          <Button
            variant="outline"
            size="sm"
            onClick={fetchProposals}
            disabled={loading}
            className="h-7 gap-1.5 px-2 text-xs font-mono rounded-sm border-border"
            title="Làm mới dữ liệu"
          >
            <RefreshCw className={`size-3 ${loading ? "animate-spin" : ""}`} />
            <span className="hidden sm:inline">Làm mới</span>
          </Button>
          <Button
            size="sm"
            onClick={() => setCreateModalOpen(true)}
            className="h-7 gap-1.5 px-2.5 text-xs font-mono rounded-sm bg-foreground text-background hover:bg-foreground/90 shadow-2xs"
          >
            <Plus className="size-3.5" />
            <span>Tạo đề xuất mới</span>
          </Button>
        </div>
      </header>

      {/* Main Body */}
      <main className="flex-1 overflow-y-auto p-4 lg:p-6 space-y-4">
        {/* Metric Cards (Monochrome Engineering) */}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:gap-3">
          <div
            onClick={() => setActiveTab("ALL")}
            className={cn(
              "cursor-pointer rounded-md border p-3.5 transition-colors shadow-2xs",
              activeTab === "ALL"
                ? "border-foreground/50 bg-muted/40"
                : "border-border bg-card hover:border-foreground/30"
            )}
          >
            <div className="text-[11px] font-mono font-medium text-muted-foreground uppercase tracking-wide">Tổng số đề xuất</div>
            <div className="mt-1 text-xl font-bold font-mono text-foreground">{counts.total}</div>
          </div>

          <div
            onClick={() => setActiveTab("PENDING")}
            className={cn(
              "cursor-pointer rounded-md border p-3.5 transition-colors shadow-2xs",
              activeTab === "PENDING"
                ? "border-amber-500/60 bg-amber-500/10"
                : "border-border bg-card hover:border-foreground/30"
            )}
          >
            <div className="flex items-center justify-between text-[11px] font-mono font-medium text-amber-500 uppercase tracking-wide">
              <span>Chờ duyệt</span>
              <Clock className="size-3" />
            </div>
            <div className="mt-1 text-xl font-bold font-mono text-amber-500">{counts.pending}</div>
          </div>

          <div
            onClick={() => setActiveTab("APPROVED")}
            className={cn(
              "cursor-pointer rounded-md border p-3.5 transition-colors shadow-2xs",
              activeTab === "APPROVED"
                ? "border-emerald-500/60 bg-emerald-500/10"
                : "border-border bg-card hover:border-foreground/30"
            )}
          >
            <div className="flex items-center justify-between text-[11px] font-mono font-medium text-emerald-500 uppercase tracking-wide">
              <span>Đã phê duyệt</span>
              <CheckCircle2 className="size-3" />
            </div>
            <div className="mt-1 text-xl font-bold font-mono text-emerald-500">{counts.approved}</div>
          </div>

          <div
            onClick={() => setActiveTab("REJECTED")}
            className={cn(
              "cursor-pointer rounded-md border p-3.5 transition-colors shadow-2xs",
              activeTab === "REJECTED"
                ? "border-rose-500/60 bg-rose-500/10"
                : "border-border bg-card hover:border-foreground/30"
            )}
          >
            <div className="flex items-center justify-between text-[11px] font-mono font-medium text-rose-500 uppercase tracking-wide">
              <span>Đã từ chối</span>
              <XCircle className="size-3" />
            </div>
            <div className="mt-1 text-xl font-bold font-mono text-rose-500">{counts.rejected}</div>
          </div>
        </div>

        {/* Filter bar and search */}
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
          <div className="inline-flex p-0.5 rounded-md border border-border bg-muted/40 font-mono text-xs">
            <button
              onClick={() => setActiveTab("ALL")}
              className={cn(
                "rounded-sm px-2.5 py-1 text-xs transition-colors",
                activeTab === "ALL" ? "bg-background text-foreground shadow-2xs font-medium border border-border" : "text-muted-foreground hover:text-foreground border border-transparent"
              )}
            >
              Tất cả ({counts.total})
            </button>
            <button
              onClick={() => setActiveTab("PENDING")}
              className={cn(
                "rounded-sm px-2.5 py-1 text-xs transition-colors",
                activeTab === "PENDING" ? "bg-background text-foreground shadow-2xs font-medium border border-border" : "text-muted-foreground hover:text-foreground border border-transparent"
              )}
            >
              Chờ duyệt ({counts.pending})
            </button>
            <button
              onClick={() => setActiveTab("APPROVED")}
              className={cn(
                "rounded-sm px-2.5 py-1 text-xs transition-colors",
                activeTab === "APPROVED" ? "bg-background text-foreground shadow-2xs font-medium border border-border" : "text-muted-foreground hover:text-foreground border border-transparent"
              )}
            >
              Đã duyệt ({counts.approved})
            </button>
            <button
              onClick={() => setActiveTab("REJECTED")}
              className={cn(
                "rounded-sm px-2.5 py-1 text-xs transition-colors",
                activeTab === "REJECTED" ? "bg-background text-foreground shadow-2xs font-medium border border-border" : "text-muted-foreground hover:text-foreground border border-transparent"
              )}
            >
              Từ chối ({counts.rejected})
            </button>
          </div>

          <div className="relative min-w-[240px]">
            <Search className="absolute left-2.5 top-2 size-3.5 text-muted-foreground" />
            <input
              type="text"
              placeholder="Tìm theo ID, Spec, tiêu đề..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full rounded-sm border border-border bg-background py-1.5 pl-8 pr-3 text-xs font-mono outline-none focus:border-foreground/40 focus:ring-1 focus:ring-ring"
            />
          </div>
        </div>

        {/* Proposal List */}
        {error ? (
          <div className="rounded-md border border-destructive/40 bg-destructive/10 p-5 text-center text-xs font-mono text-destructive">
            <AlertCircle className="mx-auto size-6 mb-2 text-destructive" />
            <p className="font-semibold">Lỗi tải dữ liệu đề xuất</p>
            <p className="mt-1">{error}</p>
          </div>
        ) : loading && proposals.length === 0 ? (
          <div className="space-y-2.5">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-24 animate-pulse rounded-md border border-border bg-muted/20" />
            ))}
          </div>
        ) : filteredProposals.length === 0 ? (
          <div className="rounded-md border border-dashed border-border py-12 text-center font-mono">
            <FileText className="mx-auto size-8 text-muted-foreground/40 mb-2" />
            <p className="text-xs font-medium text-foreground">Không tìm thấy đề xuất tri thức nào</p>
            <p className="text-[11px] text-muted-foreground mt-0.5">
              {searchQuery ? "Thử tìm kiếm với từ khóa khác" : "Chưa có đề xuất nào trong danh mục này."}
            </p>
          </div>
        ) : (
          <div className="grid gap-2.5">
            {filteredProposals.map((prop) => (
              <div
                key={prop.id}
                className="group relative flex flex-col justify-between rounded-md border border-border bg-card p-3.5 shadow-2xs transition-colors hover:border-foreground/30 md:flex-row md:items-center"
              >
                <div className="space-y-1.5 pr-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs font-semibold text-muted-foreground">{prop.id}</span>
                    <span className="rounded-sm bg-muted/60 px-1.5 py-0.5 border border-border/80 font-mono text-[11px] font-medium text-foreground">
                      {prop.spec_id}
                    </span>
                    {prop.section && (
                      <span className="rounded-sm bg-muted/40 px-1.5 py-0.5 border border-border/50 text-[10px] font-mono text-muted-foreground">
                        Mục: {prop.section}
                      </span>
                    )}
                    {prop.conflict_detected && (
                      <span className="rounded-sm bg-amber-500/10 px-1.5 py-0.5 border border-amber-500/40 text-[10px] font-mono font-medium text-amber-500 flex items-center gap-1">
                        <ShieldAlert className="size-2.5" />
                        <span>Conflict: {prop.conflict_rule_id}</span>
                      </span>
                    )}
                    {statusBadge(prop.status)}
                  </div>

                  <h3 className="text-xs font-semibold text-foreground">
                    {prop.title}
                  </h3>

                  <p className="text-xs text-muted-foreground line-clamp-2">
                    <span className="font-medium text-foreground">Lý do:</span> {prop.rationale}
                  </p>

                  <div className="flex items-center gap-4 text-[10px] font-mono text-muted-foreground/80 pt-0.5">
                    <span>Tạo lúc: {new Date(prop.created_at).toLocaleString("vi-VN")}</span>
                    {prop.reviewed_by && (
                      <span>
                        {prop.status === "APPROVED" ? "Người duyệt:" : "Người từ chối:"} {prop.reviewed_by}
                      </span>
                    )}
                  </div>
                </div>

                <div className="mt-3 flex shrink-0 items-center gap-1.5 md:mt-0">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setSelectedProposal(prop)}
                    className="h-7 gap-1 px-2 text-xs font-mono rounded-sm border-border"
                  >
                    <FileText className="size-3 text-muted-foreground" />
                    <span>Chi tiết</span>
                  </Button>
                  {prop.status === "PENDING" && (
                    <Button
                      size="sm"
                      onClick={() => openApproveConfirm(prop)}
                      disabled={actionLoading}
                      className="h-7 gap-1 px-2.5 text-xs font-mono rounded-sm bg-foreground text-background hover:bg-foreground/90 shadow-2xs"
                    >
                      <Check className="size-3" />
                      <span>Duyệt</span>
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </main>

      {/* Modal View Detail & Approval */}
      {selectedProposal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-xs">
          <div className="relative flex max-h-[90vh] w-full max-w-3xl flex-col rounded-md border border-border bg-background shadow-2xl">
            {/* Modal Header */}
            <div className="flex items-center justify-between border-b border-border px-5 py-3.5 bg-muted/20">
              <div className="space-y-0.5">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs text-muted-foreground">{selectedProposal.id}</span>
                  <span className="rounded-sm bg-muted/60 px-1.5 py-0.5 border border-border/80 font-mono text-[11px] font-medium text-foreground">
                    {selectedProposal.spec_id}
                  </span>
                  {statusBadge(selectedProposal.status)}
                </div>
                <h2 className="text-sm font-semibold text-foreground">{selectedProposal.title}</h2>
              </div>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setSelectedProposal(null)}
                className="size-7 rounded-sm text-muted-foreground hover:text-foreground"
              >
                <X className="size-3.5" />
              </Button>
            </div>

            {/* Modal Content */}
            <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3.5">
              {/* Conflict Warning Banner if detected */}
              {selectedProposal.conflict_detected && (
                <div className="rounded-sm border border-amber-500/60 bg-amber-950/20 p-3.5 text-xs font-mono text-amber-300 space-y-1.5 shadow-sm">
                  <div className="font-bold flex items-center gap-1.5 text-amber-400">
                    <ShieldAlert className="size-4" />
                    <span>CẢNH BÁO XUNG ĐỘT QUY TẮC CẤM (ANTI-COLLISION ALERT) [{selectedProposal.conflict_rule_id}]</span>
                  </div>
                  <p className="text-amber-200/90 leading-relaxed font-sans">{selectedProposal.conflict_reason}</p>
                  <p className="text-[11px] text-amber-400/80 italic pt-0.5">
                    ⚠️ Đề xuất vi phạm Negative Constraint. Hệ thống sẽ chặn phê duyệt trừ khi kiến trúc sư trưởng cố ý bật force=True.
                  </p>
                </div>
              )}

              {/* Rationale Box */}
              <div className="rounded-sm border border-border bg-muted/20 p-3 text-xs space-y-1 font-mono">
                <div className="font-semibold text-foreground flex items-center gap-1.5">
                  <AlertCircle className="size-3.5 text-muted-foreground" />
                  <span>Căn cứ & Lý do đề xuất:</span>
                </div>
                <p className="text-muted-foreground leading-relaxed font-sans">{selectedProposal.rationale}</p>
              </div>

              {selectedProposal.review_note && (
                <div className="rounded-sm border border-rose-500/30 bg-rose-500/5 p-3 text-xs space-y-1 font-mono">
                  <div className="font-semibold text-rose-500 flex items-center gap-1.5">
                    <ShieldAlert className="size-3.5" />
                    <span>Ghi chú từ chối (bởi {selectedProposal.reviewed_by}):</span>
                  </div>
                  <p className="text-muted-foreground leading-relaxed font-sans">{selectedProposal.review_note}</p>
                </div>
              )}

              {/* Proposed Content Preview */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-mono font-semibold text-muted-foreground uppercase tracking-wider">
                    Nội dung Markdown Đề xuất {selectedProposal.section ? `(Mục: ${selectedProposal.section})` : ""}
                  </span>
                  <Link
                    href={`/specs/${selectedProposal.spec_id}`}
                    target="_blank"
                    className="flex items-center gap-1 text-xs font-mono text-muted-foreground hover:text-foreground"
                  >
                    <span>Xem spec gốc</span>
                    <ExternalLink className="size-3" />
                  </Link>
                </div>

                <div className="rounded-sm border border-border bg-muted/20 p-3.5 max-h-96 overflow-y-auto text-xs font-mono">
                  <Markdown text={selectedProposal.proposed_content} />
                </div>
              </div>
            </div>

            {/* Modal Footer */}
            <div className="flex items-center justify-between border-t border-border px-5 py-3 bg-muted/20">
              <div className="text-[11px] font-mono text-muted-foreground">
                Tạo lúc: {new Date(selectedProposal.created_at).toLocaleString("vi-VN")}
              </div>

              <div className="flex items-center gap-2">
                <Button variant="outline" size="sm" onClick={() => setSelectedProposal(null)} className="h-7 rounded-sm border-border font-mono text-xs">
                  Đóng
                </Button>

                {selectedProposal.status === "PENDING" && (
                  <>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setRejectModalOpen(true)}
                      disabled={actionLoading}
                      className="h-7 gap-1 px-2.5 rounded-sm border-border text-rose-500 hover:bg-rose-500/10 hover:text-rose-600 font-mono text-xs"
                    >
                      <XCircle className="size-3.5" />
                      <span>Từ chối</span>
                    </Button>
                    <Button
                      size="sm"
                      onClick={() => openApproveConfirm(selectedProposal)}
                      disabled={actionLoading}
                      className="h-7 gap-1 px-2.5 rounded-sm bg-foreground text-background hover:bg-foreground/90 font-mono text-xs shadow-2xs"
                    >
                      <CheckCircle2 className="size-3.5" />
                      <span>Phê duyệt đề xuất</span>
                    </Button>
                  </>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Approve Confirm Dialog */}
      {approveTarget && (
        <ConfirmDialog
          open
          title="Phê duyệt đề xuất"
          icon={<CheckCircle2 className="size-4" />}
          confirmLabel="Xác nhận duyệt"
          loading={actionLoading}
          confirmDisabled={approveTarget.conflict_detected && !forceApprove}
          onConfirm={handleApproveSubmit}
          onCancel={closeApproveConfirm}
        >
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs font-mono">
              <dt className="text-muted-foreground">ID</dt>
              <dd className="text-foreground break-all">{approveTarget.id}</dd>
              <dt className="text-muted-foreground">Spec</dt>
              <dd className="text-foreground">{approveTarget.spec_id}</dd>
              <dt className="text-muted-foreground">Tiêu đề</dt>
              <dd className="text-foreground break-words">{approveTarget.title}</dd>
            </dl>
            <p className="text-xs text-muted-foreground font-mono">
              Nội dung sẽ được ghi vào spec gốc và ingest lại vào kho tri thức.
            </p>
            {approveTarget.conflict_detected && (
              <div className="rounded-sm border border-amber-500/60 bg-amber-950/20 p-2.5 text-xs font-mono text-amber-300 space-y-2">
                <div className="flex items-center gap-1.5 font-semibold text-amber-400">
                  <ShieldAlert className="size-3.5" />
                  <span>Xung đột {approveTarget.conflict_rule_id}</span>
                </div>
                <p className="font-sans text-amber-200/90">{approveTarget.conflict_reason}</p>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={forceApprove}
                    onChange={(e) => setForceApprove(e.target.checked)}
                    className="size-3.5 accent-amber-500"
                  />
                  <span>Ép buộc duyệt (force), bỏ qua quy tắc cấm</span>
                </label>
              </div>
            )}
        </ConfirmDialog>
      )}

      {/* Reject Reason Dialog */}
      {rejectModalOpen && (
        <div className="fixed inset-0 z-60 flex items-center justify-center bg-black/70 p-4">
          <div className="w-full max-w-md rounded-md border border-border bg-card p-5 shadow-xl space-y-3">
            <div className="flex items-center gap-2 text-rose-500">
              <XCircle className="size-4" />
              <h3 className="font-semibold text-xs font-mono uppercase tracking-wide">Từ chối đề xuất cập nhật</h3>
            </div>
            <p className="text-xs text-muted-foreground font-mono">
              Vui lòng nêu rõ lý do từ chối để thông báo cho người đề xuất / AI Agent điều chỉnh lại.
            </p>
            <textarea
              rows={3}
              placeholder="Nhập lý do từ chối..."
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              className="w-full rounded-sm border border-border bg-background p-2.5 text-xs font-mono outline-none focus:border-foreground/40 focus:ring-1 focus:ring-ring"
            />
            <div className="flex justify-end gap-2 pt-2 border-t border-border">
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setRejectModalOpen(false);
                  setRejectReason("");
                }}
                className="h-7 rounded-sm border-border font-mono text-xs"
              >
                Hủy
              </Button>
              <Button
                variant="destructive"
                size="sm"
                onClick={handleRejectSubmit}
                disabled={actionLoading}
                className="h-7 rounded-sm font-mono text-xs"
              >
                Xác nhận từ chối
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Create Proposal Modal */}
      {createModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-xs">
          <div className="relative flex max-h-[90vh] w-full max-w-2xl flex-col rounded-md border border-border bg-background shadow-2xl">
            <div className="flex items-center justify-between border-b border-border px-5 py-3.5 bg-muted/20">
              <div className="flex items-center gap-2">
                <FilePlus className="size-4 text-foreground" />
                <h2 className="text-xs font-semibold font-mono uppercase tracking-wide">Gửi Đề xuất Cập nhật Tri thức Mới</h2>
              </div>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setCreateModalOpen(false)}
                className="size-7 rounded-sm text-muted-foreground hover:text-foreground"
              >
                <X className="size-3.5" />
              </Button>
            </div>

            <form onSubmit={handleCreateSubmit} className="flex flex-col flex-1 overflow-hidden">
              <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3.5">
                {createError && (
                  <div className="rounded-sm border border-destructive/40 bg-destructive/10 p-2.5 text-xs font-mono text-destructive">
                    {createError}
                  </div>
                )}

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div className="space-y-1">
                    <label className="text-xs font-mono font-medium text-muted-foreground">Tài liệu Spec liên quan *</label>
                    <input
                      type="text"
                      required
                      placeholder="VD: HR-M04, HR-M01..."
                      value={newSpecId}
                      onChange={(e) => setNewSpecId(e.target.value)}
                      className="w-full rounded-sm border border-border bg-background px-3 py-1.5 text-xs font-mono outline-none focus:border-foreground/40 focus:ring-1 focus:ring-ring"
                    />
                  </div>

                  <div className="space-y-1">
                    <label className="text-xs font-mono font-medium text-muted-foreground">Tên mục / Heading (tuỳ chọn)</label>
                    <input
                      type="text"
                      placeholder="VD: Chế độ làm thêm giờ, Phụ cấp..."
                      value={newSection}
                      onChange={(e) => setNewSection(e.target.value)}
                      className="w-full rounded-sm border border-border bg-background px-3 py-1.5 text-xs font-mono outline-none focus:border-foreground/40 focus:ring-1 focus:ring-ring"
                    />
                  </div>
                </div>

                <div className="space-y-1">
                  <label className="text-xs font-mono font-medium text-muted-foreground">Tiêu đề đề xuất *</label>
                  <input
                    type="text"
                    required
                    placeholder="Tóm tắt ngắn gọn nội dung cập nhật..."
                    value={newTitle}
                    onChange={(e) => setNewTitle(e.target.value)}
                    className="w-full rounded-sm border border-border bg-background px-3 py-1.5 text-xs font-mono outline-none focus:border-foreground/40 focus:ring-1 focus:ring-ring"
                  />
                </div>

                <div className="space-y-1">
                  <label className="text-xs font-mono font-medium text-muted-foreground">Lý do đề xuất (Rationale) *</label>
                  <textarea
                    required
                    rows={2}
                    placeholder="Tại sao cần cập nhật? Căn cứ theo thông tư, quyết định nào?..."
                    value={newRationale}
                    onChange={(e) => setNewRationale(e.target.value)}
                    className="w-full rounded-sm border border-border bg-background p-2.5 text-xs font-mono outline-none focus:border-foreground/40 focus:ring-1 focus:ring-ring"
                  />
                </div>

                <div className="space-y-1">
                  <label className="text-xs font-mono font-medium text-muted-foreground">Nội dung Markdown mới *</label>
                  <textarea
                    required
                    rows={6}
                    placeholder="Nhập nội dung markdown chuẩn của quy tắc, bảng biểu, quy trình..."
                    value={newContent}
                    onChange={(e) => setNewContent(e.target.value)}
                    className="w-full font-mono rounded-sm border border-border bg-background p-2.5 text-xs outline-none focus:border-foreground/40 focus:ring-1 focus:ring-ring"
                  />
                </div>
              </div>

              <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-3 bg-muted/20">
                <Button type="button" variant="outline" size="sm" onClick={() => setCreateModalOpen(false)} className="h-7 rounded-sm border-border font-mono text-xs">
                  Hủy
                </Button>
                <Button type="submit" size="sm" disabled={createLoading} className="h-7 gap-1 px-3 rounded-sm bg-foreground text-background hover:bg-foreground/90 font-mono text-xs shadow-2xs">
                  <FilePlus className="size-3.5" />
                  <span>{createLoading ? "Đang gửi..." : "Gửi Đề xuất"}</span>
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
