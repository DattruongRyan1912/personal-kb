"use client";

import { ArrowUp, Square } from "lucide-react";
import { useRef, useState, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/button";

const MAX_QUESTION_LENGTH = 4000; // the API's limit (ChatRequest.message)
const MAX_HEIGHT_PX = 200;

/** Enter sends, Shift+Enter breaks the line, the box grows with its text; while an answer streams, Stop replaces Send.
 * Enter while an input method is composing (Vietnamese Telex/VNI) only confirms the word. */
export function ChatInput({ busy, onSend, onStop }: { busy: boolean; onSend: (text: string) => void; onStop: () => void }) {
  const [text, setText] = useState("");
  const box = useRef<HTMLTextAreaElement>(null);

  const resize = () => {
    const el = box.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT_PX)}px`;
  };

  const send = () => {
    if (busy || !text.trim()) return;
    onSend(text.trim());
    setText("");
    requestAnimationFrame(resize);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send();
    }
  };

  return (
    <div className="flex flex-col gap-1.5 rounded-lg border border-border bg-background p-2 transition-colors focus-within:border-foreground/30 focus-within:bg-background">
      <div className="flex items-center justify-between px-1.5 text-xs text-muted-foreground">
        <div className="flex items-center gap-2 font-mono text-[11px] text-muted-foreground">
          <span className="size-1.5 rounded-full bg-emerald-500" />
          <span>pgvector:bm25 · hybrid rag</span>
        </div>
        <div className="hidden items-center gap-1.5 text-[10px] font-mono text-muted-foreground/80 md:flex">
          <kbd className="rounded border border-border bg-muted/40 px-1 py-0.5 text-[10px] font-mono">↵</kbd>
          <span>để gửi</span>
          <span className="mx-0.5 opacity-40">·</span>
          <kbd className="rounded border border-border bg-muted/40 px-1 py-0.5 text-[10px] font-mono">⇧↵</kbd>
          <span>xuống dòng</span>
        </div>
      </div>
      <div className="flex items-end gap-2">
        <textarea
          ref={box}
          rows={1}
          value={text}
          aria-label="Câu hỏi"
          maxLength={MAX_QUESTION_LENGTH}
          placeholder="Tra cứu tài liệu đặc tả, API, cấu trúc bảng dữ liệu hoặc đặt câu hỏi kỹ thuật…"
          className="max-h-[200px] min-h-9 flex-1 resize-none bg-transparent px-1.5 py-1 text-sm outline-none placeholder:text-muted-foreground/60"
          onChange={(e) => {
            setText(e.target.value);
            resize();
          }}
          onKeyDown={onKeyDown}
        />
        {busy ? (
          <Button
            type="button"
            size="icon"
            variant="destructive"
            className="size-8 shrink-0 rounded-md transition-opacity hover:opacity-90"
            aria-label="Dừng"
            title="Dừng sinh câu trả lời"
            onClick={onStop}
          >
            <Square className="size-3.5 fill-current" />
          </Button>
        ) : (
          <Button
            type="button"
            size="icon"
            variant="default"
            className="size-8 shrink-0 rounded-md bg-foreground text-background transition-opacity hover:opacity-90 disabled:opacity-30"
            aria-label="Gửi"
            title="Gửi câu hỏi (Enter)"
            disabled={!text.trim()}
            onClick={send}
          >
            <ArrowUp className="size-3.5" />
          </Button>
        )}
      </div>
    </div>
  );
}
