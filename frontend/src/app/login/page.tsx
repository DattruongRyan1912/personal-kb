"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { Button } from "@/components/ui/button";
import { signInDev, signInWithGoogle } from "@/lib/auth";
import { DEV_LOGIN, SUPABASE_URL } from "@/lib/config";
import { pathOnThisSite } from "@/lib/redirect";

function Login() {
  const router = useRouter();
  const next = useSearchParams().get("next");
  const [error, setError] = useState<string | null>(null);

  const run = async (signIn: () => Promise<void>, redirect: boolean) => {
    setError(null);
    try {
      await signIn();
      if (redirect) router.replace(pathOnThisSite(next));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="flex h-dvh items-center justify-center p-4 bg-background text-foreground">
      <div className="w-full max-w-sm space-y-4 rounded-md border border-border bg-card p-6 shadow-2xs">
        <div>
          <div className="flex size-7 items-center justify-center rounded-sm bg-muted border border-border text-foreground font-mono text-xs font-semibold mb-3">
            KB
          </div>
          <h1 className="text-sm font-semibold tracking-tight font-mono text-foreground uppercase">Personal KB · Đăng nhập</h1>
          <p className="text-xs text-muted-foreground font-mono mt-1">Đăng nhập để hỏi đáp và quản trị kho tri thức đặc tả.</p>
        </div>

        <div className="space-y-2 pt-2">
          {SUPABASE_URL && (
            <Button className="w-full h-8 rounded-sm bg-foreground text-background font-mono text-xs hover:bg-foreground/90 shadow-2xs" onClick={() => run(signInWithGoogle, false)}>
              Đăng nhập với Google
            </Button>
          )}
          {DEV_LOGIN && (
            <Button className="w-full h-8 rounded-sm border border-border bg-background hover:bg-muted font-mono text-xs" variant="outline" onClick={() => run(signInDev, true)}>
              Đăng nhập dev (local)
            </Button>
          )}
          {!SUPABASE_URL && !DEV_LOGIN && (
            <p className="text-xs font-mono text-destructive">Chưa cấu hình đăng nhập: xem ai/frontend/.env.example.</p>
          )}
          {error && <p className="text-xs font-mono text-destructive rounded-sm border border-destructive/30 bg-destructive/10 p-2">{error}</p>}
        </div>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <Login />
    </Suspense>
  );
}
