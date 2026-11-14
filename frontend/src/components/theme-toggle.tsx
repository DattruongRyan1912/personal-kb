"use client"

import * as React from "react"
import { Moon, Sun } from "lucide-react"
import { Button } from "@/components/ui/button"

export function ThemeToggle() {
  const [theme, setTheme] = React.useState<"light" | "dark">("dark")

  React.useEffect(() => {
    const prefersDark = typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)")?.matches;
    const isDark = document.documentElement.classList.contains("dark") || 
      (!("theme" in localStorage) && !!prefersDark);
    if (isDark) {
      document.documentElement.classList.add("dark")
      setTheme("dark")
    } else {
      document.documentElement.classList.remove("dark")
      setTheme("light")
    }
  }, [])

  const toggleTheme = () => {
    if (theme === "dark") {
      document.documentElement.classList.remove("dark")
      localStorage.setItem("theme", "light")
      setTheme("light")
    } else {
      document.documentElement.classList.add("dark")
      localStorage.setItem("theme", "dark")
      setTheme("dark")
    }
  }

  return (
    <Button
      variant="ghost"
      size="icon-sm"
      onClick={toggleTheme}
      className="text-muted-foreground hover:text-foreground transition-transform active:scale-95"
      title={`Chuyển sang giao diện ${theme === "dark" ? "Sáng" : "Tối"}`}
      aria-label="Đổi giao diện Sáng / Tối"
    >
      {theme === "dark" ? (
        <Sun className="size-4 text-amber-400 transition-all rotate-0 scale-100" />
      ) : (
        <Moon className="size-4 text-slate-700 transition-all rotate-0 scale-100" />
      )}
    </Button>
  )
}
