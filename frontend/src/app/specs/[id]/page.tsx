"use client";

import { ArrowLeft, Check, Copy, FileText } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { Button } from "@/components/ui/button";
import { cleanMarkdown, markdownComponents } from "@/components/markdown/markdown";
import { getSpecContent, type SpecContent } from "@/lib/api";

export default function SpecPage() {
  const params = useParams();
  const specId = Array.isArray(params?.id) ? params.id[0] : (params?.id as string);

  const [data, setData] = useState<SpecContent | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!specId) return;
    setLoading(true);
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

  const copyContent = () => {
    if (!data?.content) return;
    navigator.clipboard.writeText(data.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const isApproved = data?.status.toUpperCase() === "APPROVED";

  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* Top Navbar */}
      <header className="sticky top-0 z-40 border-b border-border bg-background/95 backdrop-blur-xs">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-2.5 sm:px-6">
          <div className="flex items-center gap-3">
            <Link
              href="/"
              className="inline-flex size-7 items-center justify-center rounded-sm border border-border text-muted-foreground hover:bg-muted hover:text-foreground"
              title="Quay lại Chat"
            >
              <ArrowLeft className="size-3.5" />
            </Link>
            <div className="flex items-center gap-2">
              <FileText className="size-3.5 text-muted-foreground" />
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
          </div>

          <div className="flex items-center gap-2">
            {data && (
              <Button variant="outline" size="sm" className="h-7 gap-1 px-2.5 rounded-sm border-border font-mono text-xs" onClick={copyContent}>
                {copied ? <Check className="size-3 text-emerald-500" /> : <Copy className="size-3 text-muted-foreground" />}
                <span>{copied ? "Đã chép" : "Sao chép Markdown"}</span>
              </Button>
            )}
          </div>
        </div>
      </header>

      {/* Main Container */}
      <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6">
        {loading && (
          <div className="flex flex-col gap-3 py-16 text-center animate-pulse font-mono text-xs text-muted-foreground">
            <div className="mx-auto h-5 w-1/3 rounded-sm bg-muted" />
            <div className="mx-auto h-3 w-1/2 rounded-sm bg-muted" />
            <div className="mx-auto h-96 w-full max-w-3xl rounded-sm bg-muted/40 mt-4" />
          </div>
        )}

        {error && (
          <div className="rounded-md border border-destructive/30 bg-destructive/10 p-5 text-destructive font-mono text-xs">
            <h2 className="font-semibold text-sm">Không tìm thấy tài liệu {specId}</h2>
            <p className="mt-1">{error}</p>
            <Link href="/" className="mt-3 inline-block font-medium underline">
              Quay lại trang chủ
            </Link>
          </div>
        )}

        {data && (
          <article className="space-y-6">
            <div className="border-b border-border pb-4">
              <h1 className="text-xl font-bold tracking-tight text-foreground sm:text-2xl">{data.title}</h1>
              {data.owner && (
                <p className="mt-1.5 font-mono text-xs text-muted-foreground">
                  <b>Tác giả / Phụ trách:</b> {data.owner}
                </p>
              )}
              {data.content_hash && (
                <p className="mt-1 font-mono text-[11px] text-muted-foreground/70">
                  SHA-256: {data.content_hash}
                </p>
              )}
            </div>

            <div className="prose prose-sm dark:prose-invert max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                {cleanMarkdown(data.content)}
              </ReactMarkdown>
            </div>
          </article>
        )}
      </main>
    </div>
  );
}
