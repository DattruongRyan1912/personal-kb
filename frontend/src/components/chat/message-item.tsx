"use client";

import { Check, Copy, Terminal } from "lucide-react";
import { memo, useState } from "react";

import { RenderGuard } from "@/components/chat/render-guard";
import { Markdown, withoutBrokenLink } from "@/components/markdown/markdown";
import { answerText, type ChatMessage } from "@/lib/transport";

export const MessageItem = memo(function MessageItem({ message, streaming = false }: { message: ChatMessage; streaming?: boolean }) {
  const [copied, setCopied] = useState(false);
  const text = answerText(message);

  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-md bg-muted/80 border border-border px-3.5 py-2 text-sm text-foreground shadow-xs">
          {text}
        </div>
      </div>
    );
  }

  const shown = message.metadata?.stopped ? withoutBrokenLink(text) : text;

  const copyAnswer = async () => {
    try {
      await navigator.clipboard.writeText(shown);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback
    }
  };

  return (
    <div className="flex items-start gap-3 min-w-0 py-1">
      <div className="flex size-6 shrink-0 items-center justify-center rounded-sm bg-muted border border-border text-muted-foreground mt-0.5 shadow-xs" title="Personal KB Engine">
        <Terminal className="size-3 text-muted-foreground" />
      </div>
      <div className="min-w-0 flex-1 space-y-1.5">
        <RenderGuard text={shown}>
          <Markdown text={shown} streaming={streaming} />
        </RenderGuard>

        {/* Action bar and status */}
        <div className="flex items-center gap-3 pt-1 text-xs text-muted-foreground">
          {!streaming && shown.trim().length > 0 && (
            <button
              type="button"
              onClick={copyAnswer}
              aria-label="Sao chép câu trả lời"
              title="Sao chép câu trả lời"
              className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              {copied ? (
                <>
                  <Check className="size-3 text-emerald-500" />
                  <span className="text-emerald-500 font-medium text-[11px]">Đã sao chép</span>
                </>
              ) : (
                <>
                  <Copy className="size-3" />
                  <span className="text-[11px]">Sao chép</span>
                </>
              )}
            </button>
          )}
          {message.metadata?.stopped && <p className="text-xs text-muted-foreground">Đã dừng</p>}
        </div>
      </div>
    </div>
  );
});
