import { describe, expect, it } from "vitest";

import { readServerEvents } from "@/lib/sse";

function body(...pieces: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const piece of pieces) controller.enqueue(encoder.encode(piece));
      controller.close();
    },
  });
}

async function all(stream: ReadableStream<Uint8Array>) {
  const events = [];
  for await (const event of readServerEvents(stream)) events.push(event);
  return events;
}

describe("readServerEvents", () => {
  it("reads events split anywhere across network chunks, Vietnamese bytes included", async () => {
    const raw = 'event: status\ndata: {"type": "status", "message": "Đang tìm"}\n\nevent: text_delta\ndata: {"type": "text_delta", "delta": "Hệ "}\n\n';
    const bytes = new TextEncoder().encode(raw);
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        for (let i = 0; i < bytes.length; i += 7) controller.enqueue(bytes.slice(i, i + 7));
        controller.close();
      },
    });

    expect(await all(stream)).toEqual([
      { type: "status", message: "Đang tìm" },
      { type: "text_delta", delta: "Hệ " },
    ]);
  });

  it("skips the server's keep-alive comments", async () => {
    expect(await all(body(": ping\n\n", 'event: done\ndata: {"type": "done"}\n\n', ": ping\n\n"))).toEqual([{ type: "done" }]);
  });

  it("ignores an unfinished last event", async () => {
    expect(await all(body('event: done\ndata: {"type": "done"}\n\nevent: text_delta\ndata: {"ty'))).toEqual([{ type: "done" }]);
  });
});
