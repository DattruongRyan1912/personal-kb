import type { ChatTransport, UIMessage, UIMessageChunk } from "ai";

import { apiFetch, errorMessage } from "@/lib/api";
import { readServerEvents, type ServerEvent } from "@/lib/sse";

export type ChatMessage = UIMessage<{ stopped?: boolean }, { status: { message: string } }>;
type Chunk = UIMessageChunk<{ stopped?: boolean }, { status: { message: string } }>;

/** The answer is the last text part of a message: a reset starts a new, empty part, so a dropped draft disappears. */
export function answerText(message: Pick<UIMessage, "parts">): string {
  const texts = message.parts.filter((p) => p.type === "text");
  return texts.at(-1)?.text ?? "";
}

export const STREAM_CUT = "Kết nối bị ngắt trước khi câu trả lời xong. Hãy gửi lại câu hỏi.";

/** Maps the API's events to AI SDK chunks: status is one data part updated in place, text deltas go to the current
 * text part, reset closes it and opens an empty one. */
export async function* toChunks(events: AsyncIterable<ServerEvent>): AsyncGenerator<Chunk> {
  yield { type: "start" };
  let part = 0;
  let open = false;
  const id = () => `text-${part}`;
  for await (const event of events) {
    switch (event.type) {
      case "status":
        yield { type: "data-status", id: "status", data: { message: event.message } };
        break;
      case "text_delta":
        if (!open) {
          open = true;
          part += 1;
          yield { type: "text-start", id: id() };
        }
        yield { type: "text-delta", id: id(), delta: event.delta };
        break;
      case "reset":
        if (open) {
          yield { type: "text-end", id: id() };
          part += 1;
          yield { type: "text-start", id: id() };
        }
        break;
      case "error":
        if (open) yield { type: "text-end", id: id() };
        yield { type: "error", errorText: event.message };
        return;
      case "done":
        if (open) yield { type: "text-end", id: id() };
        yield { type: "finish" };
        return;
    }
  }
  // the stream was cut before "done" (server restarted, proxy timeout): say so, the answer may be incomplete
  if (open) yield { type: "text-end", id: id() };
  yield { type: "error", errorText: STREAM_CUT };
}

function toStream<T>(items: AsyncGenerator<T>): ReadableStream<T> {
  return new ReadableStream<T>({
    async pull(controller) {
      const { value, done } = await items.next();
      if (done) controller.close();
      else controller.enqueue(value);
    },
    async cancel() {
      await items.return(undefined);
    },
  });
}

/** useChat's transport for the Personal KB API: the chat id is the session id, only the new question is sent (the API
 * keeps the history), and aborting (Stop) closes the connection, which cancels the run on the server. */
export class PersonalKBChatTransport implements ChatTransport<ChatMessage> {
  async sendMessages({ chatId, messages, abortSignal }: Parameters<ChatTransport<ChatMessage>["sendMessages"]>[0]) {
    const question = messages.at(-1);
    const response = await apiFetch("/api/v1/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: chatId, message: question ? answerText(question) : "" }),
      signal: abortSignal,
    });
    if (!response.ok || !response.body) throw new Error(await errorMessage(response));
    return toStream(toChunks(readServerEvents(response.body))) as ReadableStream<UIMessageChunk>;
  }

  async reconnectToStream() {
    return null;
  }
}

/** Backward compatibility alias */
export const CyberosChatTransport = PersonalKBChatTransport;
