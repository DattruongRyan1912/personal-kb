import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockListProposals = vi.fn();
const mockApproveProposal = vi.fn();
const mockRejectProposal = vi.fn();
const mockCreateProposal = vi.fn();

vi.mock("@/lib/api", () => ({
  listProposals: (...args: unknown[]) => mockListProposals(...args),
  approveProposal: (...args: unknown[]) => mockApproveProposal(...args),
  rejectProposal: (...args: unknown[]) => mockRejectProposal(...args),
  createProposal: (...args: unknown[]) => mockCreateProposal(...args),
}));

const { default: ApprovalsPage } = await import("@/app/approvals/page");

afterEach(cleanup);

describe("ApprovalsPage (/approvals)", () => {
  const dummyProposals = [
    {
      id: "prop-1",
      spec_id: "HR-M04",
      title: "Bổ sung chính sách làm việc từ xa WFH",
      action: "UPDATE_SECTION",
      section: "Mục 4.2",
      proposed_content: "# Cập nhật WFH\nNhân viên được WFH 2 ngày/tuần.",
      rationale: "Phù hợp với mô hình làm việc linh hoạt 2026.",
      status: "PENDING",
      created_at: "2026-10-20T08:00:00Z",
    },
    {
      id: "prop-2",
      spec_id: "PKB-02",
      title: "Cập nhật thuật toán mã hoá Token",
      action: "REPLACE_DOCUMENT",
      section: "All",
      proposed_content: "# Bảo mật\nSử dụng Ed25519 cho chữ ký số.",
      rationale: "Nâng cấp bảo mật theo tiêu chuẩn OWASP.",
      status: "APPROVED",
      created_at: "2026-10-19T10:00:00Z",
      reviewed_at: "2026-10-19T11:00:00Z",
      reviewed_by: "Ryan Truong",
    },
    {
      id: "prop-3",
      spec_id: "PKB-03",
      title: "Tạo tài liệu đặc tả API v2",
      action: "CREATE_DOCUMENT",
      section: "",
      proposed_content: "# API v2",
      rationale: "Thiết kế API v2",
      status: "REJECTED",
      created_at: "2026-10-18T10:00:00Z",
      reviewed_at: "2026-10-18T11:00:00Z",
      reviewed_by: "Ryan Truong",
      review_note: "Chưa đúng quy chuẩn format",
    },
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    mockListProposals.mockResolvedValue(dummyProposals);
  });

  it("loads and displays proposals and metric counts", async () => {
    render(<ApprovalsPage />);

    expect(await screen.findByText("Bổ sung chính sách làm việc từ xa WFH")).toBeTruthy();
    expect(screen.getByText("Cập nhật thuật toán mã hoá Token")).toBeTruthy();
    expect(screen.getByText("Tạo tài liệu đặc tả API v2")).toBeTruthy();

    // Check metric cards
    expect(screen.getByText("Tổng số đề xuất")).toBeTruthy();
    expect(screen.getAllByText("Chờ duyệt").length).toBeGreaterThan(0);
  });

  it("filters proposals by search query", async () => {
    render(<ApprovalsPage />);

    await screen.findByText("Bổ sung chính sách làm việc từ xa WFH");

    const searchInput = screen.getByPlaceholderText("Tìm theo ID, Spec, tiêu đề...");
    fireEvent.change(searchInput, { target: { value: "mã hoá Token" } });

    expect(screen.queryByText("Bổ sung chính sách làm việc từ xa WFH")).toBeNull();
    expect(screen.getByText("Cập nhật thuật toán mã hoá Token")).toBeTruthy();
  });

  it("approves a pending proposal through the in-app confirm dialog", async () => {
    const nativeConfirm = vi.spyOn(window, "confirm");
    mockApproveProposal.mockResolvedValueOnce({
      ...dummyProposals[0],
      status: "APPROVED",
      reviewed_at: "2026-10-20T09:00:00Z",
      reviewed_by: "Ryan Truong",
    });

    render(<ApprovalsPage />);

    await screen.findByText("Bổ sung chính sách làm việc từ xa WFH");

    // Click Duyệt button on the row
    const approveBtn = screen.getByRole("button", { name: /^Duyệt$/i });
    fireEvent.click(approveBtn);

    const dialog = screen.getByRole("alertdialog");
    expect(dialog.textContent).toContain("prop-1");
    expect(mockApproveProposal).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /Xác nhận duyệt/i }));

    expect(nativeConfirm).not.toHaveBeenCalled();
    expect(mockApproveProposal).toHaveBeenCalledWith("prop-1", "Ryan Truong", false);
    expect(await screen.findByText(/Đã phê duyệt prop-1/i)).toBeTruthy();
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("closes the approve dialog on cancel without calling the API", async () => {
    render(<ApprovalsPage />);
    await screen.findByText("Bổ sung chính sách làm việc từ xa WFH");

    fireEvent.click(screen.getByRole("button", { name: /^Duyệt$/i }));
    fireEvent.click(screen.getByRole("button", { name: /^Hủy$/i }));

    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(mockApproveProposal).not.toHaveBeenCalled();
  });

  it("requires an explicit force tick to approve a conflicting proposal", async () => {
    mockListProposals.mockResolvedValue([
      { ...dummyProposals[0], conflict_detected: true, conflict_rule_id: "NC-HR-001", conflict_reason: "float cho tiền" },
    ]);
    mockApproveProposal.mockResolvedValueOnce({ ...dummyProposals[0], status: "APPROVED" });

    render(<ApprovalsPage />);
    await screen.findByText("Bổ sung chính sách làm việc từ xa WFH");

    fireEvent.click(screen.getByRole("button", { name: /^Duyệt$/i }));
    const confirmBtn = screen.getByRole("button", { name: /Xác nhận duyệt/i }) as HTMLButtonElement;
    expect(confirmBtn.disabled).toBe(true);

    fireEvent.click(screen.getByRole("checkbox", { name: /Ép buộc duyệt/i }));
    expect(confirmBtn.disabled).toBe(false);
    fireEvent.click(confirmBtn);

    expect(mockApproveProposal).toHaveBeenCalledWith("prop-1", "Ryan Truong", true);
  });

  it("rejects a pending proposal with reason", async () => {
    mockRejectProposal.mockResolvedValueOnce({
      ...dummyProposals[0],
      status: "REJECTED",
      reviewed_at: "2026-10-20T09:00:00Z",
      reviewed_by: "Ryan Truong",
      review_note: "Nội dung chưa đầy đủ các case đặc biệt",
    });

    render(<ApprovalsPage />);

    await screen.findByText("Bổ sung chính sách làm việc từ xa WFH");

    // Click "Chi tiết" to open modal
    const detailBtns = screen.getAllByRole("button", { name: /Chi tiết/i });
    fireEvent.click(detailBtns[0]);

    // Click Từ chối button inside detail modal
    const rejectBtn = screen.getByRole("button", { name: /^Từ chối$/i });
    fireEvent.click(rejectBtn);

    // Modal opens, enter reason
    expect(screen.getByText("Từ chối đề xuất cập nhật")).toBeTruthy();
    const reasonInput = screen.getByPlaceholderText("Nhập lý do từ chối...");
    fireEvent.change(reasonInput, { target: { value: "Nội dung chưa đầy đủ các case đặc biệt" } });

    // Click submit reject
    const submitRejectBtn = screen.getByRole("button", { name: /Xác nhận từ chối/i });
    fireEvent.click(submitRejectBtn);

    expect(mockRejectProposal).toHaveBeenCalledWith("prop-1", "Ryan Truong", "Nội dung chưa đầy đủ các case đặc biệt");
    expect(await screen.findByText(/Đã từ chối đề xuất cập nhật tri thức/i)).toBeTruthy();
  });

  it("creates a new knowledge proposal", async () => {
    const createdProposal = {
      id: "prop-new",
      spec_id: "HR-M04",
      title: "Đề xuất mới từ Admin",
      action: "UPDATE_SECTION" as const,
      section: "",
      proposed_content: "# Nội dung mới",
      rationale: "Lý do cập nhật",
      status: "PENDING" as const,
      created_at: "2026-10-20T10:00:00Z",
    };
    mockCreateProposal.mockResolvedValueOnce(createdProposal);

    render(<ApprovalsPage />);

    await screen.findByText("Bổ sung chính sách làm việc từ xa WFH");

    // Click "Tạo đề xuất mới" button
    const createBtn = screen.getByRole("button", { name: /Tạo đề xuất mới/i });
    fireEvent.click(createBtn);

    expect(screen.getByText("Gửi Đề xuất Cập nhật Tri thức Mới")).toBeTruthy();

    // Fill form
    fireEvent.change(screen.getByPlaceholderText("Tóm tắt ngắn gọn nội dung cập nhật..."), {
      target: { value: "Đề xuất mới từ Admin" },
    });
    fireEvent.change(screen.getByPlaceholderText("Tại sao cần cập nhật? Căn cứ theo thông tư, quyết định nào?..."), {
      target: { value: "Lý do cập nhật" },
    });
    fireEvent.change(screen.getByPlaceholderText("Nhập nội dung markdown chuẩn của quy tắc, bảng biểu, quy trình..."), {
      target: { value: "# Nội dung mới" },
    });

    // Submit form via fireEvent.submit
    const submitCreateBtn = screen.getByRole("button", { name: /Gửi Đề xuất/i });
    fireEvent.submit(submitCreateBtn.closest("form")!);

    expect(mockCreateProposal).toHaveBeenCalledWith({
      spec_id: "HR-M04",
      title: "Đề xuất mới từ Admin",
      section: "",
      action: "UPDATE_SECTION",
      rationale: "Lý do cập nhật",
      proposed_content: "# Nội dung mới",
    });

    expect((await screen.findAllByText("Đề xuất mới từ Admin")).length).toBeGreaterThan(0);
  });
});
