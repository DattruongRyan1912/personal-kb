"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";

import { Button } from "@/components/ui/button";

/** In-app replacement for window.confirm: Esc or the backdrop cancels, the confirm button takes focus. */
export function ConfirmDialog({
  open,
  title,
  icon,
  children,
  confirmLabel,
  variant = "default",
  loading = false,
  confirmDisabled = false,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  icon?: ReactNode;
  children?: ReactNode;
  confirmLabel: string;
  variant?: "default" | "destructive";
  loading?: boolean;
  confirmDisabled?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const titleId = useId();
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    confirmRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !loading) onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, loading, onCancel]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-60 flex items-center justify-center bg-black/70 p-4"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !loading) onCancel();
      }}
    >
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="w-full max-w-md rounded-md border border-border bg-card p-5 shadow-xl space-y-3"
      >
        <div className={variant === "destructive" ? "flex items-center gap-2 text-rose-500" : "flex items-center gap-2 text-foreground"}>
          {icon}
          <h3 id={titleId} className="font-semibold text-xs font-mono uppercase tracking-wide">
            {title}
          </h3>
        </div>
        {children}
        <div className="flex justify-end gap-2 pt-2 border-t border-border">
          <Button
            variant="outline"
            size="sm"
            onClick={onCancel}
            disabled={loading}
            className="h-7 rounded-sm border-border font-mono text-xs"
          >
            Hủy
          </Button>
          <Button
            ref={confirmRef}
            variant={variant === "destructive" ? "destructive" : "default"}
            size="sm"
            onClick={onConfirm}
            disabled={loading || confirmDisabled}
            className={
              variant === "destructive"
                ? "h-7 rounded-sm font-mono text-xs"
                : "h-7 rounded-sm bg-foreground text-background hover:bg-foreground/90 font-mono text-xs"
            }
          >
            {loading ? "Đang xử lý..." : confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
