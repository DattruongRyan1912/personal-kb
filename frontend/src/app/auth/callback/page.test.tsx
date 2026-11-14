import { cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const replace = vi.fn();
const auth = {
  getSession: vi.fn(async () => ({ data: { session: { access_token: "t" } }, error: null })),
  exchangeCodeForSession: vi.fn(async () => ({ data: {}, error: { message: "code verifier missing" } })),
};

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));
vi.mock("@/lib/auth", () => ({ supabaseClient: () => ({ auth }) }));

const { default: AuthCallback } = await import("@/app/auth/callback/page");

afterEach(cleanup);

describe("AuthCallback", () => {
  it("lets the Supabase client exchange the code itself, then goes home", async () => {
    window.history.pushState({}, "", "/auth/callback?code=abc");

    render(<AuthCallback />);

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
    expect(auth.exchangeCodeForSession).not.toHaveBeenCalled();
  });
});
