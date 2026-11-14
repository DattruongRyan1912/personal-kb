"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { ChatWindow } from "@/components/chat/chat-window";
import { useSessions } from "@/components/chat/sessions-context";
import { getTranscript } from "@/lib/api";
import { fromTranscript } from "@/lib/messages";
import type { ChatMessage } from "@/lib/transport";

/** A session: its saved transcript first (a reload restores the whole conversation, issue 3.2), then the chat. */
export default function ChatPage() {
  const { id } = useParams<{ id: string }>();
  const { handleError } = useSessions();
  const [loaded, setLoaded] = useState<{ id: string; messages: ChatMessage[] } | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    getTranscript(id)
      .then((t) => current && setLoaded({ id, messages: fromTranscript(id, t) }))
      .catch((error) => {
        handleError(error);
        if (current) setFailure(error instanceof Error ? error.message : String(error));
      });
    return () => {
      current = false;
    };
  }, [id, handleError]);

  if (failure) return <p className="p-6 text-sm text-destructive">Không tải được cuộc trò chuyện: {failure}</p>;
  if (loaded?.id !== id) return <p className="p-6 text-sm text-muted-foreground">Đang tải…</p>;
  return <ChatWindow key={id} sessionId={id} initialMessages={loaded.messages} />;
}
