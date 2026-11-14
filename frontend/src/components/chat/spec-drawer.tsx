"use client";

import { Check, Copy, ExternalLink, FileText, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { Button } from "@/components/ui/button";
import { cleanMarkdown, markdownComponents } from "@/components/markdown/markdown";
import { getSpecContent, type SpecContent } from "@/lib/api";

interface SpecDrawerProps {
  specId: string | null;
  onClose: () => void;
}

export function SpecDrawer({ specId, onClose }: SpecDrawerProps) {
  const [data, setData] = useState<SpecContent | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!specId) {
      setData(null);
      setError(null);
      return;
    }

    setLoading(true);
    setError(null);
    getSpecContent(specId)
      .then((res) => {
        setData(res);
        setLoading(false);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : String(err));
        setLoading(false);
      });
  }, [specId]);

  if (!specId) return null;

  const copyContent = () => {
    if (!data?.content) return;
    navigator.clipboard.writeText(data.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const isApproved = data?.status.toUpperCase() === "APPROVED";

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/50 backdrop-blur-xs transition-opacity animate-in fade-in"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Drawer Container */}
      <aside
        className="relative z-50 flex h-full w-full max-w-3xl flex-col border-l border-border bg-background shadow-2xl animate-in slide-in-from-right duration-200"
        aria-label={`Chi tiết tài liệu ${specId}`}
      >
        {/* Header */}
        <header className="flex items-center justify-between border-b border-border px-4 py-3 bg-muted/20">
          <div className="flex items-center gap-2.5 overflow-hidden">
            <div className="flex size-7 shrink-0 items-center justify-center rounded-sm bg-muted border border-border text-muted-foreground">
              <FileText className="size-3.5" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-mono text-xs font-semibold text-foreground">{specId}</span>
                {data && (
                  <span
                    className={`rounded-sm px-1.5 py-0.2 font-mono text-[10px] font-medium border ${
                      isApproved
                        ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-500"
                        : "border-amber-500/30 bg-amber-500/10 text-amber-500"
                    }`}
                  >
                    {isApproved ? "Approved" : data.status}
                  </span>
                )}
              </div>
              <h2 className="truncate text-xs font-medium text-muted-foreground">
                {data?.title || specId}
              </h2>
            </div>
          </div>

          <div className="flex items-center gap-1.5">
            {data && (
              <>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-7 gap-1 px-2 text-xs font-mono rounded-sm border-border"
                  onClick={copyContent}
                  title="Sao chép toàn bộ Markdown"
                >
                  {copied ? <Check className="size-3 text-emerald-500" /> : <Copy className="size-3 text-muted-foreground" />}
                  <span>{copied ? "Đã chép" : "Sao chép"}</span>
                </Button>
                <Link
                  href={`/specs/${specId}`}
                  target="_blank"
                  className="inline-flex h-7 items-center gap-1 rounded-sm border border-border px-2 text-xs font-mono text-foreground hover:bg-muted"
                  title="Mở tab riêng"
                >
                  <ExternalLink className="size-3 text-muted-foreground" />
                  <span>Tab riêng</span>
                </Link>
              </>
            )}
            <Button variant="ghost" size="sm" className="size-7 p-0 rounded-sm" onClick={onClose} aria-label="Đóng">
              <X className="size-3.5" />
            </Button>
          </div>
        </header>

        {/* Content Body */}
        <div className="flex-1 overflow-y-auto px-6 py-5">
          {loading && (
            <div className="flex flex-col gap-3 py-10 text-center animate-pulse">
              <div className="h-4 w-1/3 rounded bg-muted mx-auto" />
              <div className="h-4 w-2/3 rounded bg-muted mx-auto" />
              <div className="h-4 w-1/2 rounded bg-muted mx-auto" />
            </div>
          )}

          {error && (
            <div className="rounded-lg border border-destructive/20 bg-destructive/10 p-4 text-xs text-destructive">
              <p className="font-semibold">Không thể tải nội dung tài liệu {specId}:</p>
              <p className="mt-1">{error}</p>
            </div>
          )}

          {data && (
            <div className="prose prose-sm dark:prose-invert max-w-none space-y-4">
              {data.owner && (
                <p className="text-xs text-muted-foreground">
                  <b>Tác giả:</b> {data.owner}
                </p>
              )}
              <div className="border-t border-border pt-3">
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                  {cleanMarkdown(data.content)}
                </ReactMarkdown>
              </div>
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}
