import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockGetSpecContent = vi.fn();

vi.mock("@/lib/api", () => ({
  getSpecContent: (...args: unknown[]) => mockGetSpecContent(...args),
}));

const { SpecDrawer } = await import("@/components/chat/spec-drawer");

afterEach(cleanup);

describe("SpecDrawer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders nothing when specId is null", () => {
    const { container } = render(<SpecDrawer specId={null} onClose={vi.fn()} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders spec content and metadata", async () => {
    mockGetSpecContent.mockResolvedValueOnce({
      spec_id: "PKB-01",
      title: "Tổng quan Kiến trúc Personal-KB",
      owner: "Ryan Truong",
      status: "APPROVED",
      content: "# PKB-01 Header\n\nNội dung đặc tả chi tiết kiến trúc hệ thống.",
      content_hash: "abcd1234ef567890",
    });

    const onClose = vi.fn();
    render(<SpecDrawer specId="PKB-01" onClose={onClose} />);

    expect(await screen.findByLabelText("Chi tiết tài liệu PKB-01")).toBeTruthy();
    expect(screen.getAllByText("PKB-01").length).toBeGreaterThan(0);
    expect(screen.getByText("Tổng quan Kiến trúc Personal-KB")).toBeTruthy();
    expect(screen.getByText("Ryan Truong")).toBeTruthy();
    expect(screen.getByText("Approved")).toBeTruthy();
    expect(screen.getByText("Nội dung đặc tả chi tiết kiến trúc hệ thống.")).toBeTruthy();
  });

  it("handles copy to clipboard", async () => {
    mockGetSpecContent.mockResolvedValueOnce({
      spec_id: "PKB-02",
      title: "Cấu hình Bảo mật",
      owner: "SecOps",
      status: "DRAFT",
      content: "Markdown body to copy",
      content_hash: "hash123",
    });

    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, {
      clipboard: {
        writeText: writeTextMock,
      },
    });

    render(<SpecDrawer specId="PKB-02" onClose={vi.fn()} />);

    const copyBtn = await screen.findByText("Sao chép");
    fireEvent.click(copyBtn);

    expect(writeTextMock).toHaveBeenCalledWith("Markdown body to copy");
    expect(await screen.findByText("Đã chép")).toBeTruthy();
  });

  it("calls onClose when clicking close button or backdrop", async () => {
    mockGetSpecContent.mockResolvedValueOnce({
      spec_id: "PKB-03",
      title: "Sơ đồ luồng dữ liệu",
      owner: "DataTeam",
      status: "APPROVED",
      content: "Flow content",
      content_hash: "hashflow",
    });

    const onClose = vi.fn();
    render(<SpecDrawer specId="PKB-03" onClose={onClose} />);

    await screen.findByLabelText("Chi tiết tài liệu PKB-03");

    // Click close button with aria-label="Đóng"
    const closeBtn = screen.getByLabelText("Đóng");
    fireEvent.click(closeBtn);
    expect(onClose).toHaveBeenCalledTimes(1);

    // Click backdrop
    const backdrop = document.querySelector(".bg-black\\/50");
    if (backdrop) {
      fireEvent.click(backdrop);
      expect(onClose).toHaveBeenCalledTimes(2);
    }
  });

  it("displays error message when fetching spec fails", async () => {
    mockGetSpecContent.mockRejectedValueOnce(new Error("Network timeout"));

    render(<SpecDrawer specId="NON-EXISTENT" onClose={vi.fn()} />);

    expect(await screen.findByText(/Không thể tải nội dung tài liệu/i)).toBeTruthy();
    expect(screen.getByText("Network timeout")).toBeTruthy();
  });
});
