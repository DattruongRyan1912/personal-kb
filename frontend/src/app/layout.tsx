import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";

import { TooltipProvider } from "@/components/ui/tooltip";
import "./globals.css";

const sans = Inter({ variable: "--font-sans", subsets: ["latin", "vietnamese"] });
const mono = JetBrains_Mono({ variable: "--font-code", subsets: ["latin", "vietnamese"] });

export const metadata: Metadata = {
  title: "Personal KB | Knowledge Base",
  description: "Kho tri thức cá nhân và quản trị tài liệu đặc tả (Personal Knowledge Base)",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="vi" className={`${sans.variable} ${mono.variable} h-full antialiased`}>
      <body className="h-full">
        <TooltipProvider>{children}</TooltipProvider>
      </body>
    </html>
  );
}
