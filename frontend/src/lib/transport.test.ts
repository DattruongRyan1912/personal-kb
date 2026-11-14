import { describe, expect, it } from "vitest";

import type { ServerEvent } from "@/lib/sse";
import { answerText, STREAM_CUT, toChunks } from "@/lib/transport";

async function* events(...items: ServerEvent[]) {
  yield* items;
}

async function chunks(...items: ServerEvent[]) {
  const out = [];
  for await (const chunk of toChunks(events(...items))) out.push(chunk);
  return out;
}

describe("toChunks", () => {
  it("streams status as one data part and text into one text part", async () => {
    expect(
      await chunks(
        { type: "status", message: "🔍 Đang tìm" },
        { type: "text_delta", delta: "Hệ " },
        { type: "text_delta", delta: "thống" },
        { type: "done" },
      ),
    ).toEqual([
      { type: "start" },
      { type: "data-status", id: "status", data: { message: "🔍 Đang tìm" } },
      { type: "text-start", id: "text-1" },
      { type: "text-delta", id: "text-1", delta: "Hệ " },
      { type: "text-delta", id: "text-1", delta: "thống" },
      { type: "text-end", id: "text-1" },
      { type: "finish" },
    ]);
  });

  it("starts an empty text part on reset, so the dropped draft is no longer the answer", async () => {
    const out = await chunks(
      { type: "text_delta", delta: "Để tôi tra cứu." },
      { type: "reset" },
      { type: "text_delta", delta: "Dùng VNPay." },
      { type: "done" },
    );

    expect(out.slice(1, 6)).toEqual([
      { type: "text-start", id: "text-1" },
      { type: "text-delta", id: "text-1", delta: "Để tôi tra cứu." },
      { type: "text-end", id: "text-1" },
      { type: "text-start", id: "text-2" },
      { type: "text-delta", id: "text-2", delta: "Dùng VNPay." },
    ]);
  });

  it("ends with the API's error message", async () => {
    expect((await chunks({ type: "text_delta", delta: "a" }, { type: "error", message: "Xin lỗi" })).slice(-2)).toEqual([
      { type: "text-end", id: "text-1" },
      { type: "error", errorText: "Xin lỗi" },
    ]);
  });

  it("says so when the stream is cut before done, instead of leaving half an answer", async () => {
    const out = await chunks({ type: "text_delta", delta: "Hệ thống dùng" });

    expect(out.slice(-2)).toEqual([
      { type: "text-end", id: "text-1" },
      { type: "error", errorText: STREAM_CUT },
    ]);
  });
});

describe("answerText", () => {
  it("is the last text part", () => {
    const parts = [
      { type: "text" as const, text: "nháp" },
      { type: "data-status" as const, id: "status", data: { message: "x" } },
      { type: "text" as const, text: "" },
    ];
    expect(answerText({ parts })).toBe("");
    expect(answerText({ parts: [...parts, { type: "text" as const, text: "Đáp án" }] })).toBe("Đáp án");
  });
});
