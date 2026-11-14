import { beforeEach, describe, expect, it, vi } from "vitest";

const apiFetch = vi.fn();
vi.mock("@/lib/api", () => ({ apiFetch: (...args: unknown[]) => apiFetch(...args), errorMessage: async () => "x" }));

const { CyberosChatTransport } = await import("@/lib/transport");

function sse(): Response {
  return new Response('event: done\ndata: {"type": "done"}\n\n', { headers: { "content-type": "text/event-stream" } });
}

describe("CyberosChatTransport", () => {
  beforeEach(() => apiFetch.mockReset().mockResolvedValue(sse()));

  const question = { id: "m1", role: "user" as const, parts: [{ type: "text" as const, text: "Luồng thanh toán?" }] };
  const send = (body?: object) =>
    new CyberosChatTransport().sendMessages({ trigger: "submit-message", chatId: "s1", messageId: undefined, messages: [question], abortSignal: undefined, body });

  it("posts only the new question: the API keeps the history and decides how much to read", async () => {
    await send();
    expect(JSON.parse(apiFetch.mock.calls[0][1].body)).toEqual({ session_id: "s1", message: "Luồng thanh toán?" });
  });
});
