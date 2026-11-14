"use client";

import { BookOpen, Database, LogOut, MessageSquare, Plus, ShieldCheck, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { useSessions } from "@/components/chat/sessions-context";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { ThemeToggle } from "@/components/theme-toggle";
import { deleteSession, listProposals } from "@/lib/api";
import { signOut } from "@/lib/auth";
import { cn } from "@/lib/utils";

function when(unixSeconds: number): string {
  return new Date(unixSeconds * 1000).toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "short" });
}

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { sessions, refresh, handleError } = useSessions();
  const { id: active } = useParams<{ id?: string }>();
  const pathname = usePathname();
  const router = useRouter();
  const [pendingCount, setPendingCount] = useState<number>(0);

  useEffect(() => {
    listProposals("PENDING")
      .then((proposals) => setPendingCount(proposals.length))
      .catch(() => {});
  }, [pathname]);

  const [removeTarget, setRemoveTarget] = useState<string | null>(null);
  const [removing, setRemoving] = useState(false);
  const closeRemoveConfirm = useCallback(() => setRemoveTarget(null), []);

  const remove = async () => {
    if (!removeTarget) return;
    const id = removeTarget;
    setRemoving(true);
    try {
      await deleteSession(id);
      setRemoveTarget(null);
      await refresh();
      if (id === active) router.push("/");
    } catch (error) {
      handleError(error);
    } finally {
      setRemoving(false);
    }
  };

  return (
    <nav aria-label="Lịch sử trò chuyện" className="flex h-full flex-col gap-2 bg-sidebar p-3 text-sidebar-foreground">
      <ConfirmDialog
        open={removeTarget !== null}
        title="Xoá cuộc trò chuyện"
        icon={<Trash2 className="size-4" />}
        variant="destructive"
        confirmLabel="Xoá"
        loading={removing}
        onConfirm={remove}
        onCancel={closeRemoveConfirm}
      >
        <p className="text-xs text-muted-foreground font-mono">Cuộc trò chuyện sẽ bị xoá khỏi lịch sử.</p>
      </ConfirmDialog>
      {/* Brand Header */}
      <div className="flex items-center gap-2.5 px-2 py-1.5 border-b pb-3 border-border">
        <div className="flex size-7 items-center justify-center rounded-sm bg-muted border border-border text-foreground font-mono text-xs font-semibold">
          KB
        </div>
        <div className="flex flex-col">
          <span className="text-xs font-semibold tracking-tight text-foreground font-mono">Personal KB</span>
          <span className="text-[10px] text-muted-foreground font-mono">Engineering Workspace</span>
        </div>
      </div>

      {/* Navigation links */}
      <div className="flex flex-col gap-1 pb-2 border-b border-border">
        <span className="px-2 pt-1 text-[10px] font-semibold tracking-wider text-muted-foreground/70 font-mono uppercase">
          Phân hệ quản trị
        </span>
        <Link
          href="/data"
          onClick={onNavigate}
          className={cn(
            "flex items-center justify-between rounded-sm px-2 py-1.5 text-xs transition-colors hover:bg-muted/70 border border-transparent",
            pathname === "/data" && "bg-muted font-medium text-foreground border-border",
          )}
        >
          <span className="flex items-center gap-2">
            <Database className="size-3.5 text-muted-foreground" />
            <span className="font-mono text-xs">Dữ liệu & Storage</span>
          </span>
        </Link>
        <Link
          href="/approvals"
          onClick={onNavigate}
          className={cn(
            "flex items-center justify-between rounded-sm px-2 py-1.5 text-xs transition-colors hover:bg-muted/70 border border-transparent",
            pathname === "/approvals" && "bg-muted font-medium text-foreground border-border",
          )}
        >
          <span className="flex items-center gap-2">
            <ShieldCheck className="size-3.5 text-muted-foreground" />
            <span className="font-mono text-xs">Phê duyệt Tri thức</span>
          </span>
          {pendingCount > 0 && (
            <span className="inline-flex items-center justify-center rounded-sm border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.2 font-mono text-[10px] font-medium text-amber-500">
              {pendingCount}
            </span>
          )}
        </Link>
      </div>

      <Button
        variant="outline"
        className="justify-start gap-2 rounded-sm border border-border bg-background hover:bg-muted/80 text-foreground font-mono text-xs py-1.5 h-8"
        onClick={() => (onNavigate?.(), router.push("/"))}
      >
        <Plus className="size-3.5 text-muted-foreground" /> <span className="font-sans">Cuộc trò chuyện mới</span>
      </Button>

      {/* Sessions list */}
      <div className="flex items-center justify-between px-2 pt-2">
        <span className="text-[10px] font-semibold tracking-wider text-muted-foreground/70 font-mono uppercase">
          Lịch sử trò chuyện
        </span>
        <span className="text-[10px] font-mono text-muted-foreground">
          {sessions.length}
        </span>
      </div>

      <ul className="-mx-1 flex-1 space-y-0.5 overflow-y-auto px-1">
        {sessions.map((s) => (
          <li key={s.session_id} className="group relative">
            <Link
              href={`/c/${s.session_id}`}
              onClick={onNavigate}
              className={cn(
                "flex flex-col rounded-sm px-2 py-1.5 pr-8 text-xs transition-colors hover:bg-muted/60 border border-transparent",
                s.session_id === active
                  ? "bg-muted font-medium text-foreground border-border"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              <span className="flex items-center gap-2 truncate">
                <MessageSquare className={cn("size-3 shrink-0", s.session_id === active ? "text-foreground opacity-100" : "opacity-60")} />
                <span className="truncate text-xs">{s.title || "Cuộc trò chuyện mới"}</span>
              </span>
              <span className="pl-5 text-[10px] font-mono text-muted-foreground/70">{when(s.updated_at)}</span>
            </Link>
            <button
              type="button"
              aria-label="Xoá"
              title="Xoá"
              onClick={() => setRemoveTarget(s.session_id)}
              className="absolute top-2 right-1.5 rounded-sm p-1 text-muted-foreground opacity-0 hover:text-destructive group-hover:opacity-100 focus:opacity-100 transition-opacity"
            >
              <Trash2 className="size-3.5" />
            </button>
          </li>
        ))}
        {sessions.length === 0 && (
          <li className="px-2 py-6 text-center text-xs text-muted-foreground/80 font-mono">
            Chưa có cuộc trò chuyện nào.
          </li>
        )}
      </ul>
      <div className="flex items-center justify-between border-t border-border pt-2 px-1">
        <Button
          variant="ghost"
          size="sm"
          className="justify-start gap-2 text-muted-foreground hover:text-foreground font-mono text-xs h-7 px-2"
          onClick={async () => {
            await signOut();
            router.replace("/login");
          }}
        >
          <LogOut className="size-3.5" /> <span className="font-sans">Đăng xuất</span>
        </Button>
        <ThemeToggle />
      </div>
    </nav>
  );
}
