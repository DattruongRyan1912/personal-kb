/** The events of POST /api/v1/chat/stream (issue 3.1). */
export type ServerEvent =
  | { type: "status"; message: string }
  | { type: "text_delta"; delta: string }
  | { type: "reset" } // the text streamed so far was a draft: drop it
  | { type: "error"; message: string }
  | { type: "done" };

/** Reads a text/event-stream body; an event may arrive split across several network chunks. */
export async function* readServerEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<ServerEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder(); // stream mode: a multi-byte character split across chunks stays whole
  let buffer = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) return;
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
      let end: number;
      while ((end = buffer.indexOf("\n\n")) >= 0) {
        const data = buffer
          .slice(0, end)
          .split("\n")
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).replace(/^ /, ""))
          .join("\n");
        buffer = buffer.slice(end + 2);
        if (data) yield JSON.parse(data) as ServerEvent;
      }
    }
  } finally {
    await reader.cancel().catch(() => {});
  }
}
