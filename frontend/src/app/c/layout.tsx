"use client";

import { Menu, X } from "lucide-react";
import { useState, type ReactNode } from "react";

import { SessionsProvider } from "@/components/chat/sessions-context";
import { Sidebar } from "@/components/chat/sidebar";
import { Button } from "@/components/ui/button";

export default function ChatLayout({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <SessionsProvider>
      <div className="flex h-dvh">
        <aside className="hidden w-64 shrink-0 border-r md:block">
          <Sidebar />
        </aside>
        {open && (
          <div className="fixed inset-0 z-40 md:hidden">
            <div className="absolute inset-0 bg-black/40" onClick={() => setOpen(false)} />
            <aside className="absolute inset-y-0 left-0 w-72 border-r shadow-xl">
              <Sidebar onNavigate={() => setOpen(false)} />
            </aside>
          </div>
        )}
        <main className="flex min-w-0 flex-1 flex-col">
          <header className="flex items-center gap-2 border-b px-3 py-2 md:hidden">
            <Button size="icon" variant="ghost" aria-label="Lịch sử" onClick={() => setOpen((v) => !v)}>
              {open ? <X className="size-4" /> : <Menu className="size-4" />}
            </Button>
            <span className="text-sm font-semibold tracking-wide">Personal KB</span>
          </header>
          <div className="min-h-0 flex-1">{children}</div>
        </main>
      </div>
    </SessionsProvider>
  );
}
