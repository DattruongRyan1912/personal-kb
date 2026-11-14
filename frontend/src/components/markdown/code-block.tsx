"use client";

import { Check, Copy } from "lucide-react";
import { memo, useState } from "react";
import { PrismLight as SyntaxHighlighter } from "react-syntax-highlighter";
import bash from "react-syntax-highlighter/dist/esm/languages/prism/bash";
import diff from "react-syntax-highlighter/dist/esm/languages/prism/diff";
import go from "react-syntax-highlighter/dist/esm/languages/prism/go";
import http from "react-syntax-highlighter/dist/esm/languages/prism/http";
import java from "react-syntax-highlighter/dist/esm/languages/prism/java";
import javascript from "react-syntax-highlighter/dist/esm/languages/prism/javascript";
import json from "react-syntax-highlighter/dist/esm/languages/prism/json";
import jsx from "react-syntax-highlighter/dist/esm/languages/prism/jsx";
import markdown from "react-syntax-highlighter/dist/esm/languages/prism/markdown";
import python from "react-syntax-highlighter/dist/esm/languages/prism/python";
import sql from "react-syntax-highlighter/dist/esm/languages/prism/sql";
import tsx from "react-syntax-highlighter/dist/esm/languages/prism/tsx";
import typescript from "react-syntax-highlighter/dist/esm/languages/prism/typescript";
import yaml from "react-syntax-highlighter/dist/esm/languages/prism/yaml";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";

// the languages SDD specs use; others are shown uncoloured
const LANGUAGES = { bash, diff, go, http, java, javascript, json, jsx, markdown, python, sql, tsx, typescript, yaml };
for (const [name, grammar] of Object.entries(LANGUAGES)) SyntaxHighlighter.registerLanguage(name, grammar);
const ALIASES: Record<string, string> = { js: "javascript", ts: "typescript", py: "python", yml: "yaml", sh: "bash", shell: "bash", md: "markdown" };

/** The Clipboard API exists only in a secure context (https, localhost) and may be denied: fall back to a selected
 * hidden textarea, which copies plain text too. */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.focus();
    area.select();
    try {
      return document.execCommand("copy");
    } finally {
      area.remove();
    }
  }
}

/** A fenced code block: dark highlighting, the language in a header, and Copy, which puts the code exactly as
 * written on the clipboard (indentation kept, no markup). */
export const CodeBlock = memo(function CodeBlock({ language, code }: { language?: string; code: string }) {
  const [result, setResult] = useState<"copied" | "failed" | null>(null);
  const copied = result === "copied";
  const lang = language ? (ALIASES[language] ?? language) : undefined;

  const copy = async () => {
    setResult((await copyText(code)) ? "copied" : "failed");
    setTimeout(() => setResult(null), 1500);
  };

  return (
    <div className="my-3 overflow-hidden rounded-lg border border-zinc-800 bg-[#282c34]">
      <div className="flex items-center justify-between border-b border-zinc-700 px-3 py-1.5 text-xs text-zinc-300">
        <span className="font-mono">{language || "text"}</span>
        <button
          type="button"
          onClick={copy}
          aria-label={copied ? "Đã copy" : "Copy"}
          className="flex items-center gap-1 rounded px-1.5 py-0.5 hover:bg-zinc-700 hover:text-white"
        >
          {copied ? <Check className="size-3.5 text-emerald-400" /> : <Copy className="size-3.5" />}
          {copied ? "Đã copy" : result === "failed" ? "Không copy được" : "Copy"}
        </button>
      </div>
      <SyntaxHighlighter
        language={lang && lang in LANGUAGES ? lang : "text"}
        style={oneDark}
        customStyle={{ margin: 0, padding: "0.75rem 1rem", background: "transparent", fontSize: "0.8125rem" }}
        codeTagProps={{ style: { fontFamily: "var(--font-code), ui-monospace, monospace" } }}
      >
        {code}
      </SyntaxHighlighter>
    </div>
  );
});
