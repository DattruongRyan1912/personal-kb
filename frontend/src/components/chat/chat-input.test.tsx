import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ChatInput } from "@/components/chat/chat-input";

afterEach(cleanup);

function setup(busy = false) {
  const onSend = vi.fn();
  const onStop = vi.fn();
  render(<ChatInput busy={busy} onSend={onSend} onStop={onStop} />);
  return { onSend, onStop, box: screen.getByLabelText("Câu hỏi") };
}

describe("ChatInput", () => {
  it("sends on Enter and clears the box", () => {
    const { onSend, box } = setup();
    fireEvent.change(box, { target: { value: "  Luồng thanh toán?  " } });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(onSend).toHaveBeenCalledWith("Luồng thanh toán?");
    expect((box as HTMLTextAreaElement).value).toBe("");
  });

  it("keeps Shift+Enter and an Enter that confirms a composed word for the text", () => {
    const { onSend, box } = setup();
    fireEvent.change(box, { target: { value: "dòng 1" } });
    fireEvent.keyDown(box, { key: "Enter", shiftKey: true });
    fireEvent.keyDown(box, { key: "Enter", isComposing: true });
    expect(onSend).not.toHaveBeenCalled();
  });

  it("shows Stop instead of Send while an answer streams", () => {
    const { onStop, onSend, box } = setup(true);
    fireEvent.change(box, { target: { value: "x" } });
    fireEvent.keyDown(box, { key: "Enter" });
    fireEvent.click(screen.getByLabelText("Dừng"));
    expect(onSend).not.toHaveBeenCalled();
    expect(onStop).toHaveBeenCalledOnce();
    expect(screen.queryByLabelText("Gửi")).toBeNull();
  });

  it("stops at the API's 4,000 characters instead of letting the request fail", () => {
    const { box } = setup();
    expect((box as HTMLTextAreaElement).maxLength).toBe(4000);
  });
});
