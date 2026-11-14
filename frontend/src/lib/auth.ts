import { createBrowserClient } from "@supabase/ssr";
import type { SupabaseClient } from "@supabase/supabase-js";

import { API_URL, DEV_LOGIN, SUPABASE_ANON_KEY, SUPABASE_URL } from "@/lib/config";

/** The user is not signed in, or the API refused the token: sign in again. */
export class AuthError extends Error {}

const DEV_TOKEN_KEY = "personalkb.devToken";
const LEGACY_DEV_TOKEN_KEY = "cyberos.devToken";
let supabase: SupabaseClient | null = null;

export function supabaseClient(): SupabaseClient | null {
  if (!SUPABASE_URL || !SUPABASE_ANON_KEY) return null;
  supabase ??= createBrowserClient(SUPABASE_URL, SUPABASE_ANON_KEY);
  return supabase;
}

/** The bearer token for the API: the dev token, or the access token of the Supabase session (Google sign-in). */
export async function getAccessToken(): Promise<string | null> {
  if (DEV_LOGIN) {
    const stored = localStorage.getItem(DEV_TOKEN_KEY) ?? localStorage.getItem(LEGACY_DEV_TOKEN_KEY);
    if (!stored) return null;
    const { token, expiresAt } = JSON.parse(stored) as { token: string; expiresAt: number };
    return Date.now() < expiresAt - 30_000 ? token : null;
  }
  const client = supabaseClient();
  if (!client) return null;
  const { data } = await client.auth.getSession();
  return data.session?.access_token ?? null;
}

export async function signInDev(): Promise<void> {
  const response = await fetch(`${API_URL}/api/v1/dev/token`, { method: "POST" });
  if (!response.ok) throw new Error(`Đăng nhập dev thất bại (HTTP ${response.status}): bật DEV_LOGIN trên API`);
  const body = (await response.json()) as { access_token: string; expires_in: number };
  localStorage.setItem(DEV_TOKEN_KEY, JSON.stringify({ token: body.access_token, expiresAt: Date.now() + body.expires_in * 1000 }));
}

export async function signInWithGoogle(): Promise<void> {
  const client = supabaseClient();
  if (!client) throw new Error("Chưa cấu hình Supabase (NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY)");
  const { error } = await client.auth.signInWithOAuth({
    provider: "google",
    options: { redirectTo: `${window.location.origin}/auth/callback` },
  });
  if (error) throw error;
}

export async function signOut(): Promise<void> {
  localStorage.removeItem(DEV_TOKEN_KEY);
  localStorage.removeItem(LEGACY_DEV_TOKEN_KEY);
  await supabaseClient()?.auth.signOut();
}
