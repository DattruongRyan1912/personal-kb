"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/** A new chat: every chat lives at /c/<session id>, so a reload keeps it. */
export default function NewChat() {
  const router = useRouter();
  useEffect(() => {
    router.replace(`/c/${crypto.randomUUID()}`);
  }, [router]);
  return null;
}
