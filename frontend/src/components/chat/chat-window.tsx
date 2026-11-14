"use client";

import { useChat } from "@ai-sdk/react";
import { useEffect, useMemo, useState } from "react";

import { ChatInput } from "@/components/chat/chat-input";
import { MessageItem } from "@/components/chat/message-item";
import { useSessions } from "@/components/chat/sessions-context";
import { SpecDrawer } from "@/components/chat/spec-drawer";
import { StatusIndicator } from "@/components/chat/status-indicator";
import { useAutoScroll } from "@/hooks/use-auto-scroll";
import { listCatalog, type CatalogItem } from "@/lib/api";
import { answerText, PersonalKBChatTransport, type ChatMessage } from "@/lib/transport";

// shown the moment a question is sent, before the API's first status arrives (issue 3.4)
const SENDING = "🔄 Đang tìm kiếm trong kho Spec...";

/** One session: the API streams the answer (issue 3.1) into useChat; the session id is the chat id. */
export function ChatWindow({ sessionId, initialMessages }: { sessionId: string; initialMessages: ChatMessage[] }) {
  const { refresh, handleError } = useSessions();
  const transport = useMemo(() => new PersonalKBChatTransport(), []);
  const { viewport, content, scrollToBottom } = useAutoScroll();
  const [catalog, setCatalog] = useState<CatalogItem[]>([]);
  const [activeDrawerSpecId, setActiveDrawerSpecId] = useState<string | null>(null);

  useEffect(() => {
    listCatalog()
      .then((res) => setCatalog(res.items || []))
      .catch(() => {});
  }, []);

  const { messages, setMessages, sendMessage, status, stop, error } = useChat<ChatMessage>({
    id: sessionId,
    messages: initialMessages,
    transport,
    throttle: 40, // batch token updates into frames: smooth text, no re-render per token
    onError: handleError,
    onFinish: ({ message, isAbort }) => {
      if (isAbort) {
        setMessages((all) => all.map((m) => (m.id === message.id ? { ...m, metadata: { stopped: true } } : m)));
      }
      void refresh();
    },
  });
  const busy = status === "submitted" || status === "streaming";
  const last = messages.at(-1);
  const waiting = busy && (last?.role !== "assistant" || !answerText(last));
  const status_ = last?.role === "assistant" ? last.parts.findLast((p) => p.type === "data-status")?.data.message : undefined;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div ref={viewport} className="min-h-0 flex-1 overflow-y-auto">
        <div ref={content} className="mx-auto flex max-w-4xl flex-col gap-6 px-4 py-6">
          {messages.length === 0 && (
            <div className="flex flex-col gap-4 py-2">
              {/* System Metadata Header */}
              <div className="rounded-lg border border-border bg-card p-4">
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/60 pb-3">
                  <div>
                    <h2 className="text-xs font-semibold tracking-tight text-foreground uppercase font-mono">
                      Kho Tri Thức & Hệ Thống Đặc Tả (SDD)
                    </h2>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      PostgreSQL 17 (pgvector) kết hợp Full-Text Search BM25 (Hybrid RRF).
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="inline-flex items-center gap-1.5 rounded border border-border bg-muted/30 px-2 py-0.5 font-mono text-[11px] text-muted-foreground">
                      <span className="size-1.5 rounded-full bg-emerald-500" />
                      <span>PostgreSQL: 5433</span>
                    </span>
                    <span className="inline-flex items-center gap-1.5 rounded border border-border bg-muted/30 px-2 py-0.5 font-mono text-[11px] text-muted-foreground">
                      <span className="size-1.5 rounded-full bg-emerald-500" />
                      <span>MCP Protocol: Active</span>
                    </span>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3 pt-3 sm:grid-cols-4">
                  <div>
                    <span className="text-[10px] uppercase tracking-wider text-muted-foreground/70 font-mono">Dung lượng quản lý</span>
                    <p className="mt-0.5 font-mono text-sm font-semibold text-foreground">
                      {catalog.length} <span className="text-xs font-normal text-muted-foreground">tài liệu</span>
                    </p>
                  </div>
                  <div>
                    <span className="text-[10px] uppercase tracking-wider text-muted-foreground/70 font-mono">Tổng số Chunks</span>
                    <p className="mt-0.5 font-mono text-sm font-semibold text-foreground">
                      {catalog.reduce((acc, c) => acc + (c.chunk_count || 0), 0)} <span className="text-xs font-normal text-muted-foreground">đoạn</span>
                    </p>
                  </div>
                  <div>
                    <span className="text-[10px] uppercase tracking-wider text-muted-foreground/70 font-mono">Embedding Model</span>
                    <p className="mt-0.5 font-mono text-xs font-medium text-foreground">text-embedding-3-small</p>
                  </div>
                  <div>
                    <span className="text-[10px] uppercase tracking-wider text-muted-foreground/70 font-mono">Chiến lược tra cứu</span>
                    <p className="mt-0.5 font-mono text-xs font-medium text-foreground">Dense + Sparse Hybrid</p>
                  </div>
                </div>
              </div>

              {/* Specs Catalog Table */}
              <div className="rounded-lg border border-border bg-card overflow-hidden">
                <div className="flex items-center justify-between border-b border-border/80 px-3 py-2 bg-muted/20">
                  <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground font-mono">
                    Danh mục Tài liệu Đặc tả ({catalog.length})
                  </span>
                  <span className="text-[11px] text-muted-foreground font-mono">Nhấn &quot;Xem Spec&quot; để đọc tài liệu gốc</span>
                </div>

                <div className="max-h-[360px] overflow-y-auto">
                  <table className="w-full text-left border-collapse text-xs">
                    <thead>
                      <tr className="border-b border-border/60 bg-muted/10 font-mono text-[11px] text-muted-foreground">
                        <th className="py-2 px-3 font-medium">Mã Spec</th>
                        <th className="py-2 px-3 font-medium">Tiêu đề tài liệu đặc tả</th>
                        <th className="py-2 px-3 font-medium text-right">Chunks</th>
                        <th className="py-2 px-3 font-medium text-center">Vector DB</th>
                        <th className="py-2 px-3 font-medium text-right">Thao tác</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border/40">
                      {catalog.map((item) => (
                        <tr key={item.spec_id} className="hover:bg-muted/30 transition-colors">
                          <td className="py-2 px-3 font-mono font-medium text-foreground">
                            <span className="rounded bg-muted/60 px-1.5 py-0.5 border border-border/80 text-[11px]">
                              {item.spec_id}
                            </span>
                          </td>
                          <td className="py-2 px-3 text-foreground font-medium truncate max-w-[280px]">
                            {item.title || item.spec_id}
                          </td>
                          <td className="py-2 px-3 text-right font-mono text-muted-foreground text-[11px]">
                            {item.chunk_count ?? "—"}
                          </td>
                          <td className="py-2 px-3 text-center">
                            <span className="inline-flex items-center gap-1 font-mono text-[10px] text-muted-foreground">
                              <span className="size-1 rounded-full bg-emerald-500" />
                              <span>synced</span>
                            </span>
                          </td>
                          <td className="py-2 px-3 text-right space-x-1.5 whitespace-nowrap">
                            <button
                              type="button"
                              onClick={() => setActiveDrawerSpecId(item.spec_id)}
                              className="inline-flex items-center gap-1 rounded border border-border bg-background px-2 py-0.5 text-[11px] font-medium text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
                            >
                              Xem Spec
                            </button>
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => {
                                scrollToBottom();
                                void sendMessage({ text: `Tra cứu tài liệu đặc tả ${item.spec_id}: ${item.title}` });
                              }}
                              className="inline-flex items-center gap-1 rounded border border-border bg-foreground text-background px-2 py-0.5 text-[11px] font-medium transition-opacity hover:opacity-90 disabled:opacity-30"
                            >
                              Tra cứu
                            </button>
                          </td>
                        </tr>
                      ))}
                      {catalog.length === 0 && (
                        <tr>
                          <td colSpan={5} className="py-8 text-center text-xs text-muted-foreground font-mono">
                            Đang tải danh mục đặc tả từ kho lưu trữ...
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}
          {messages.map((m, i) => (
            <MessageItem key={m.id} message={m} streaming={busy && i === messages.length - 1} />
          ))}
          {waiting && <StatusIndicator message={status_ ?? SENDING} />}
          {error && !busy && (
            <p role="alert" className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm text-destructive">
              Không nhận được câu trả lời: {error.message}
            </p>
          )}
        </div>
      </div>
      <div className="mx-auto w-full max-w-4xl px-4 pb-4">
        <ChatInput
          busy={busy}
          onStop={stop}
          onSend={(text) => {
            scrollToBottom();
            void sendMessage({ text });
          }}
        />
      </div>
      <SpecDrawer specId={activeDrawerSpecId} onClose={() => setActiveDrawerSpecId(null)} />
    </div>
  );
}
