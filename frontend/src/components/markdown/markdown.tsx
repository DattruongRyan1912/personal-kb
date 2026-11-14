"use client";

import { marked } from "marked";
import { Children, isValidElement, memo, useMemo, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { CitationBadge } from "@/components/chat/citation-badge";
import { CodeBlock } from "@/components/markdown/code-block";

/** Top-level Markdown blocks (paragraph, list, table, code fence…), as written. While an answer streams only the last
 * block changes, so the others keep their rendering (issue 3.3: no lag on long answers). */
export function splitBlocks(text: string): string[] {
  return marked.lexer(text).map((token) => token.raw);
}

/** A citation's target: a spec id such as SPC-2 or SDD_CORE_002, not a URL or a path (the agent's syntax, 2.4). */
export function isSpecId(href: string | undefined): href is string {
  return !!href && /^(?=.*\d)[A-Za-z][A-Za-z0-9_.-]{0,63}$/.test(href);
}

/** While an answer streams, a citation arrives a few characters at a time: hide an unfinished `[…` or `[…](SPC-` at
 * the very end, so raw brackets never flash before the badge appears. */
export function withoutUnfinishedLink(text: string): string {
  return text.replace(/\[[^\]\n]*(\]\(?[A-Za-z0-9_.-]*)?$/, "");
}

// the backend's spec id (services/citations.py): letters, then parts joined by - or _, the last ending in digits
const SPEC_ID = String.raw`[A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+)*[-_]\d+[A-Za-z0-9]*`;
const BARE_IDS = new RegExp(
  String.raw`(?<!\])\[\s*(${SPEC_ID}(?:\s*[,;]\s*${SPEC_ID})*)\s*\](?!\()|(?<!\])\(\s*(${SPEC_ID}(?:\s*[,;]\s*${SPEC_ID})*)\s*\)`,
  "g",
);
const CODE = /(```[\s\S]*?(?:```|$)|`[^`\n]*`)/;

/** A model that cites "[SPC-4]" or "(SPC-4)" instead of "[Title](SPC-4)" cites all the same (the backend counts it):
 * turn those into links so they render as badges. Code is left as written. */
export function withBareCitations(text: string): string {
  return text
    .split(CODE)
    .map((part, i) =>
      i % 2 === 1
        ? part
        : part.replace(BARE_IDS, (_, inBrackets?: string, inParens?: string) =>
            (inBrackets ?? inParens ?? "")
              .split(/\s*[,;]\s*/)
              .map((id) => `[${id}](${id})`)
              .join(", "),
          ),
    )
    .join("");
}

/** An answer stopped part-way may end inside a citation: drop an unclosed `[…` or `[…](SPC-`, keep a closed `[1]`. */
export function withoutBrokenLink(text: string): string {
  return text.replace(/\[[^\]\n]*(\]\([^)\n]*)?$/, "");
}

/** Strips YAML frontmatter and raw HTML comments (like <!-- DOCX_P0310 -->) outside code blocks
 * so standard Markdown renders cleanly on the web. */
export function cleanMarkdown(text: string): string {
  if (!text) return "";
  const withoutFrontmatter = text.replace(/^---[\r\n]+[\s\S]*?[\r\n]+---[\r\n]*/, "");
  return withoutFrontmatter
    .split(CODE)
    .map((part, i) => (i % 2 === 1 ? part : part.replace(/<!--[\s\S]*?-->/g, "")))
    .join("");
}

function plainText(children: ReactNode): string {
  return Children.toArray(children)
    .map((child) => (typeof child === "string" || typeof child === "number" ? String(child) : isValidElement<{ children?: ReactNode }>(child) ? plainText(child.props.children) : ""))
    .join("");
}

function codeOf(children: ReactNode): { language?: string; code: string } {
  const child = Children.toArray(children)[0];
  if (!isValidElement<{ className?: string; children?: ReactNode }>(child)) return { code: String(children ?? "") };
  const language = /language-([\w+#.-]+)/.exec(child.props.className ?? "")?.[1];
  return { language, code: String(child.props.children ?? "").replace(/\n$/, "") };
}

export const markdownComponents: Components = {
  pre: ({ children }) => <CodeBlock {...codeOf(children)} />,
  // never loaded: an image URL is a request to any host, and a spec could make the model put data in it; the alt
  // text is kept so nothing the answer says is lost
  img: ({ alt }) => (alt ? <span className="text-muted-foreground">[{alt}]</span> : null),
  code: ({ className, children }) => (
    <code className={className ?? "rounded bg-muted px-1 py-0.5 font-mono text-[0.85em]"}>{children}</code>
  ),
  // a wide table scrolls inside its own frame and never widens the chat (issue 3.3)
  table: ({ children }) => (
    <div className="my-3 max-w-full overflow-x-auto rounded-md border" data-table-scroll>
      <table className="w-full border-collapse text-sm">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-muted">{children}</thead>,
  tr: ({ children }) => <tr className="border-b last:border-b-0 even:bg-muted/40">{children}</tr>,
  th: ({ children, style }) => (
    <th style={style} className="border-r px-3 py-2 text-left font-semibold whitespace-nowrap last:border-r-0">
      {children}
    </th>
  ),
  td: ({ children, style }) => (
    <td style={style} className="border-r px-3 py-2 align-top last:border-r-0">
      {children}
    </td>
  ),
  a: ({ href, children }) =>
    isSpecId(href) ? (
      <CitationBadge specId={href} title={plainText(children)} />
    ) : (
      <a href={href} target="_blank" rel="noopener noreferrer" className="text-primary underline underline-offset-2">
        {children}
      </a>
    ),
  p: ({ children }) => <p className="my-2 leading-relaxed">{children}</p>,
  ul: ({ children }) => <ul className="my-2 list-disc space-y-1 pl-6">{children}</ul>,
  ol: ({ children }) => <ol className="my-2 list-decimal space-y-1 pl-6">{children}</ol>,
  h1: ({ children }) => <h1 className="mt-4 mb-2 text-xl font-semibold">{children}</h1>,
  h2: ({ children }) => <h2 className="mt-4 mb-2 text-lg font-semibold">{children}</h2>,
  h3: ({ children }) => <h3 className="mt-3 mb-1.5 text-base font-semibold">{children}</h3>,
  h4: ({ children }) => <h4 className="mt-3 mb-1 font-semibold">{children}</h4>,
  blockquote: ({ children }) => <blockquote className="my-2 border-l-4 pl-3 text-muted-foreground">{children}</blockquote>,
  hr: () => <hr className="my-4" />,
};

const Block = memo(
  function Block({ content, components }: { content: string; components: Components }) {
    return (
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    );
  },
  (a, b) => a.content === b.content && a.components === b.components,
);

/** Renders an answer as GitHub-flavoured Markdown, block by block; citations become badges (3.4). */
export const Markdown = memo(function Markdown({
  text,
  streaming = false,
  components = markdownComponents,
}: {
  text: string;
  streaming?: boolean;
  components?: Components;
}) {
  const blocks = useMemo(
    () => splitBlocks(cleanMarkdown(withBareCitations(streaming ? withoutUnfinishedLink(text) : text))),
    [text, streaming],
  );
  return (
    <div className="min-w-0 text-sm">
      {blocks.map((block, i) => (
        <Block key={i} content={block} components={components} />
      ))}
    </div>
  );
});
