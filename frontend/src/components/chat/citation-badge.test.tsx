import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({
  getSpecCard: vi.fn(async (specId: string) => ({
    spec_id: specId,
    title: "Luồng thanh toán đơn hàng",
    owner: "Trần Quốc Bảo",
    status: "APPROVED",
  })),
  getSpecContent: vi.fn(async (specId: string) => ({
    spec_id: specId,
    title: "Luồng thanh toán đơn hàng",
    owner: "Trần Quốc Bảo",
    status: "APPROVED",
    content: "# SPC-2 — Luồng thanh toán đơn hàng\n\nNội dung chi tiết quy trình thanh toán.",
    content_hash: "hash_test_123456",
  })),
}));

const { CitationBadge } = await import("@/components/chat/citation-badge");

afterEach(cleanup);

describe("CitationBadge", () => {
  it("opens the spec card on a tap or click, not only on hover (phones have no hover)", async () => {
    render(<CitationBadge specId="SPC-2" title="Luồng thanh toán" />);

    fireEvent.click(screen.getByLabelText("Tài liệu SPC-2: Luồng thanh toán"));

    expect(await screen.findByText("Trần Quốc Bảo")).toBeTruthy();
    expect(await screen.findByText("Xem toàn văn tài liệu")).toBeTruthy();
  });

  it("opens the full spec drawer when clicking 'Xem toàn văn tài liệu'", async () => {
    render(<CitationBadge specId="SPC-2" title="Luồng thanh toán" />);

    // Open card
    fireEvent.click(screen.getByLabelText("Tài liệu SPC-2: Luồng thanh toán"));
    const viewBtn = await screen.findByText("Xem toàn văn tài liệu");
    
    // Click view content button
    fireEvent.click(viewBtn);

    // Drawer should appear
    expect(await screen.findByLabelText("Chi tiết tài liệu SPC-2")).toBeTruthy();
    expect(await screen.findByText("Nội dung chi tiết quy trình thanh toán.")).toBeTruthy();
  });
});
