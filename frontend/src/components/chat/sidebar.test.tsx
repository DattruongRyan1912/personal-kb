import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockPush = vi.fn();
const mockRefresh = vi.fn();
const mockHandleError = vi.fn();
const mockDeleteSession = vi.fn();
const mockListProposals = vi.fn();

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "session-1" }),
  usePathname: () => "/c/session-1",
  useRouter: () => ({
    push: mockPush,
  }),
}));

vi.mock("@/components/chat/sessions-context", () => ({
  useSessions: () => ({
    sessions: [
      { session_id: "session-1", title: "Hỏi về kiến trúc Personal-KB", updated_at: 1700000000 },
      { session_id: "session-2", title: "Thảo luận SDD Ingestion", updated_at: 1699990000 },
    ],
    refresh: mockRefresh,
    handleError: mockHandleError,
  }),
}));

vi.mock("@/lib/api", () => ({
  deleteSession: (...args: unknown[]) => mockDeleteSession(...args),
  listProposals: (...args: unknown[]) => mockListProposals(...args),
}));

vi.mock("@/lib/auth", () => ({
  signOut: vi.fn(),
}));

const { Sidebar } = await import("@/components/chat/sidebar");

afterEach(cleanup);

describe("Sidebar", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockListProposals.mockResolvedValue([
      { id: "prop-1", status: "PENDING" },
      { id: "prop-2", status: "PENDING" },
    ]);
  });

  it("renders brand, navigation links, and pending badge", async () => {
    render(<Sidebar />);

    expect(screen.getByText("Personal KB")).toBeTruthy();
    expect(screen.getByText("Dữ liệu & Storage")).toBeTruthy();
    expect(screen.getByText("Phê duyệt Tri thức")).toBeTruthy();

    // Pending count badge
    expect(await screen.findByText("2")).toBeTruthy();
  });

  it("renders list of sessions and highlights active session", () => {
    render(<Sidebar />);

    expect(screen.getByText("Hỏi về kiến trúc Personal-KB")).toBeTruthy();
    expect(screen.getByText("Thảo luận SDD Ingestion")).toBeTruthy();

    const activeLink = screen.getByText("Hỏi về kiến trúc Personal-KB").closest("a");
    expect(activeLink?.className).toContain("bg-muted");
  });

  it("navigates to home when clicking new chat button", () => {
    const onNavigate = vi.fn();
    render(<Sidebar onNavigate={onNavigate} />);

    const newChatBtn = screen.getByText("Cuộc trò chuyện mới");
    fireEvent.click(newChatBtn);

    expect(onNavigate).toHaveBeenCalled();
    expect(mockPush).toHaveBeenCalledWith("/");
  });

  it("deletes a session when confirmed in the in-app dialog", async () => {
    const nativeConfirm = vi.spyOn(window, "confirm");
    mockDeleteSession.mockResolvedValueOnce(undefined);

    render(<Sidebar />);

    const deleteBtns = screen.getAllByTitle("Xoá");
    fireEvent.click(deleteBtns[0]);

    const dialog = screen.getByRole("alertdialog");
    expect(mockDeleteSession).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: /^Xoá$/ }));

    expect(nativeConfirm).not.toHaveBeenCalled();
    expect(mockDeleteSession).toHaveBeenCalledWith("session-1");
  });
});
