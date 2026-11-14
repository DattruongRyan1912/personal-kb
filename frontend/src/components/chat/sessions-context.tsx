"use client";

import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { listSessions, type SessionSummary } from "@/lib/api";
import { AuthError, getAccessToken } from "@/lib/auth";

type Sessions = {
  sessions: SessionSummary[];
  refresh: () => Promise<void>;
  /** Call with any error from the API: an AuthError sends the user to sign in. */
  handleError: (error: unknown) => void;
};

const SessionsContext = createContext<Sessions | null>(null);

export function useSessions(): Sessions {
  const value = useContext(SessionsContext);
  if (!value) throw new Error("useSessions outside SessionsProvider");
  return value;
}

/** Signed-in area: no token sends to /login; the session list is shared by the sidebar and the chat window. */
export function SessionsProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);

  const handleError = useCallback(
    (error: unknown) => {
      if (error instanceof AuthError) router.replace(`/login?next=${encodeURIComponent(window.location.pathname)}`);
    },
    [router],
  );

  const refresh = useCallback(async () => {
    try {
      setSessions(await listSessions());
    } catch (error) {
      handleError(error);
    }
  }, [handleError]);

  useEffect(() => {
    getAccessToken().then((token) => {
      if (!token) return handleError(new AuthError("Chưa đăng nhập"));
      setReady(true);
      void refresh();
    });
  }, [handleError, refresh]);

  if (!ready) return null;
  return <SessionsContext.Provider value={{ sessions, refresh, handleError }}>{children}</SessionsContext.Provider>;
}
