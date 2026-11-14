"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { supabaseClient } from "@/lib/auth";

/** Google sign-in returns here. The Supabase browser client exchanges the code in the URL for a session (PKCE) by
 * itself as it starts (detectSessionInUrl); getSession() waits for that. Exchanging the code a second time here
 * would fail: the first exchange has already used the code verifier. */
export default function AuthCallback() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  const client = supabaseClient();

  useEffect(() => {
    if (!client) return;
    client.auth.getSession().then(({ data, error }) =>
      error || !data.session ? setError(error?.message ?? "Đăng nhập không thành công") : router.replace("/"),
    );
  }, [client, router]);

  const message = client ? (error ?? "Đang đăng nhập…") : "Chưa cấu hình Supabase";
  return <p className="p-6 text-sm text-muted-foreground">{message}</p>;
}
