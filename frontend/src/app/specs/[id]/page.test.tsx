import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockGetSpecContent = vi.fn();
const mockParams = vi.fn();

vi.mock("next/navigation", () => ({
  useParams: () => mockParams(),
}));

vi.mock("@/lib/api", () => ({
  getSpecContent: (...args: unknown[]) => mockGetSpecContent(...args),
}));

const { default: SpecPage } = await import("@/app/specs/[id]/page");

afterEach(cleanup);

describe("SpecPage (/specs/[id])", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders spec content and metadata correctly", async () => {
    mockParams.mockReturnValue({ id: "HR-M04" });
    mockGetSpecContent.mockResolvedValueOnce({
      spec_id: "HR-M04",
      title: "Chính sách Chấm công và Quản lý Nghỉ phép",
      owner: "Phòng Nhân sự",
      status: "APPROVED",
      content: "# HR-M04 Chính sách\n\nNội dung chính sách chấm công chi tiết.",
      content_hash: "hash_hr_m04_9999",
    });

    render(<SpecPage />);

    expect(await screen.findByText("HR-M04 Chính sách")).toBeTruthy();
    expect(screen.getByText("Chính sách Chấm công và Quản lý Nghỉ phép")).toBeTruthy();
    expect(screen.getByText("Phòng Nhân sự")).toBeTruthy();
    expect(screen.getByText("Approved")).toBeTruthy();
    expect(screen.getByText(/hash_hr_m04_9999/)).toBeTruthy();
    expect(screen.getByText("Nội dung chính sách chấm công chi tiết.")).toBeTruthy();
  });

  it("copies markdown content to clipboard", async () => {
    mockParams.mockReturnValue({ id: "PKB-01" });
    mockGetSpecContent.mockResolvedValueOnce({
      spec_id: "PKB-01",
      title: "Kiến trúc Hệ thống",
      owner: "Ryan Truong",
      status: "APPROVED",
      content: "# Content To Copy",
      content_hash: "hash_pkb_01",
    });

    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, {
      clipboard: {
        writeText: writeTextMock,
      },
    });

    render(<SpecPage />);

    const copyBtn = await screen.findByText("Sao chép Markdown");
    fireEvent.click(copyBtn);

    expect(writeTextMock).toHaveBeenCalledWith("# Content To Copy");
    expect(await screen.findByText("Đã chép")).toBeTruthy();
  });

  it("displays error state when spec is not found", async () => {
    mockParams.mockReturnValue({ id: "UNKNOWN-SPEC" });
    mockGetSpecContent.mockRejectedValueOnce(new Error("Document not found"));

    render(<SpecPage />);

    expect(await screen.findByText("Không tìm thấy tài liệu UNKNOWN-SPEC")).toBeTruthy();
    expect(screen.getByText("Document not found")).toBeTruthy();
  });
});
