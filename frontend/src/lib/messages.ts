import type { TranscriptMessage } from "@/lib/api";
import type { ChatMessage } from "@/lib/transport";

/** A saved transcript as useChat messages, so a reloaded page shows the whole conversation (issue 3.2). */
export function fromTranscript(sessionId: string, transcript: TranscriptMessage[]): ChatMessage[] {
  return transcript.map((m, i) => ({
    id: `${sessionId}-${i}`,
    role: m.role,
    parts: [{ type: "text", text: m.content }],
    metadata: m.stopped ? { stopped: true } : undefined,
  }));
}
