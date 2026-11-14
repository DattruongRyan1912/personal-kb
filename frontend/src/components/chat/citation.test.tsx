import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { SpecCardBody } from "@/components/chat/citation-badge";
import { MessageItem } from "@/components/chat/message-item";
import { isSpecId, Markdown, withoutUnfinishedLink } from "@/components/markdown/markdown";
import type { ChatMessage } from "@/lib/transport";

afterEach(cleanup);

const ANSWER = "Đơn hàng chỉ chuyển sang PAID khi nhận IPN hợp lệ, chi tiết tại [Luồng thanh toán](SPC-123) và [Từ điển](SDD_CORE_002).";

function stoppedAnswer(text: string): ChatMessage {
  return { id: "a1", role: "assistant", parts: [{ type: "text", text }], metadata: { stopped: true } };
}

describe("citations", () => {
  it("recognises spec ids, not URLs or paths", () => {
    expect(["SPC-123", "SDD_CORE_002", "SDD-AUTH-001"].every(isSpecId)).toBe(true);
    expect(["https://vnpay.vn", "/docs/a", "README", "", undefined].some(isSpecId)).toBe(false);
  });

  it("renders a citation as an inline badge in the middle of the sentence", () => {
    const { container } = render(<Markdown text={ANSWER} />);

    const badge = screen.getByLabelText("Tài liệu SPC-123: Luồng thanh toán");
    expect(badge.tagName).toBe("BUTTON");
    expect(badge.closest("p")?.textContent).toContain("chi tiết tại");
    expect(container.querySelector('a[href="SPC-123"]')).toBeNull();
  });

  it("never throws nor shows raw brackets while a citation streams in, character by character", () => {
    for (let end = 1; end <= ANSWER.length; end++) {
      const { container, unmount } = render(<Markdown text={ANSWER.slice(0, end)} streaming />);
      expect(container.textContent).not.toMatch(/\]\(|\[Lu|\[Từ/);
      unmount();
    }
  });

  it("hides only an unfinished link at the end", () => {
    expect(withoutUnfinishedLink("chi tiết tại [Luồng thanh toán](SPC-")).toBe("chi tiết tại ");
    expect(withoutUnfinishedLink("chi tiết tại [Luồng thanh")).toBe("chi tiết tại ");
    expect(withoutUnfinishedLink("xem [A](SPC-1).")).toBe("xem [A](SPC-1).");
  });

  it("shows no raw link when the answer was stopped in the middle of a citation", () => {
    for (const cut of ["Idempotency-Key bắt buộc [SPC-2](SPC-", "Idempotency-Key bắt buộc [Luồng thanh"]) {
      const { container, unmount } = render(<MessageItem message={stoppedAnswer(cut)} />);
      expect(container.textContent).toContain("Idempotency-Key bắt buộc");
      expect(container.textContent).toContain("Đã dừng");
      expect(container.textContent).not.toMatch(/\]\(|\[SPC|\[Lu/);
      unmount();
    }
  });

  it("keeps a finished citation or bracket at the end of a stopped answer", () => {
    render(<MessageItem message={stoppedAnswer("Theo [Luồng thanh toán](SPC-2), xem bước [1]")} />);
    expect(screen.getByText(/xem bước \[1\]/)).toBeTruthy();
    expect(screen.getByLabelText("Tài liệu SPC-2: Luồng thanh toán")).toBeTruthy();
  });
});

describe("SpecCardBody", () => {
  it("shows the spec's name, owner and status", () => {
    render(
      <SpecCardBody
        specId="SPC-2"
        failure={null}
        card={{ spec_id: "SPC-2", title: "Luồng thanh toán đơn hàng", owner: "Trần Quốc Bảo", status: "APPROVED" }}
      />,
    );
    expect(screen.getByText("Luồng thanh toán đơn hàng")).toBeTruthy();
    expect(screen.getByText("Trần Quốc Bảo")).toBeTruthy();
    expect(screen.getByText("Approved")).toBeTruthy();
  });
});

describe("bare citations", () => {
  it("[SPC-4] and (SPC-4) become badges too, like the backend counts them; code is left alone", () => {
    const { container } = render(
      <Markdown text={"Khoá sau 5 lần [SPC-1]. Thanh toán qua VNPay (SPC-2). Cả hai [SPC-1, SPC-2]. Xem [Luồng](SPC-3). Mã `[SPC-9]`."} />,
    );

    expect(screen.getAllByLabelText(/^Tài liệu SPC-1/)).toHaveLength(2);
    expect(screen.getAllByLabelText(/^Tài liệu SPC-2/)).toHaveLength(2);
    expect(screen.getAllByLabelText(/^Tài liệu SPC-3/)).toHaveLength(1);
    expect(container.querySelector("code")?.textContent).toBe("[SPC-9]");
    expect(container.textContent).not.toMatch(/\[SPC-[12]\]|\(SPC-2\)/);
  });

  it("leaves ordinary brackets and parentheses as they are", () => {
    const { container } = render(<Markdown text="Bước [1] trả (HTTP 401) cho (xem SPC-4)." />);

    expect(container.querySelectorAll("button")).toHaveLength(0);
    expect(container.textContent).toBe("Bước [1] trả (HTTP 401) cho (xem SPC-4).");
  });
});
