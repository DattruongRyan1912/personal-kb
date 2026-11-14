# Personal Knowledge Base — Design System & Engineering UI Guardrails

> **Strict Non-Negotiable Rules for All AI Agents and Developers**  
> *Philosophy: Developer Ergonomics, Information Density, High Signal-to-Noise, Linear / Midday / Dub.co Aesthetic.*

---

## 1. Core Philosophy

Personal-KB is an engineering tool for developers, architects, and technical operators.
- **NEVER** treat this interface as a generic customer-support chatbot.
- **NEVER** introduce consumer AI tropes ("AI slop"): sparkles, neon gradients, playful rounded pills, glowing ping animations, or salesy prompt cards.
- **ALWAYS** prioritize clarity, density, 1px hairline borders, monochrome palette, and monospace metadata.

---

## 2. Strict Blacklist (FORBIDDEN ANTI-PATTERNS)

The following patterns are **STRICTLY PROHIBITED** anywhere in this codebase:

1. **NO Decorative Sparkles or AI Glyphs:**
   - ❌ Never use `Sparkles`, `Stars`, `Wand2`, or playful decorative emoji in headers or hero states.
   - ✅ Use semantic icons: `BookOpen`, `Database`, `Search`, `FileText`, `Terminal`, `Cpu`, `Layers`, `ShieldCheck`.

2. **NO Multi-Color or Neon Gradients:**
   - ❌ Never use `bg-gradient-to-r`, `bg-clip-text text-transparent`, or purple/indigo/pink gradient blends.
   - ✅ Use solid text colors: `text-foreground`, `text-muted-foreground`, and subtle neutral badges.

3. **NO Oversized Border Radii:**
   - ❌ Never use `rounded-2xl`, `rounded-3xl`, or `rounded-full` for cards, inputs, and buttons.
   - ✅ Use `rounded-md` (6px) or `rounded-lg` (8px) for buttons, inputs, and cards. Only avatar circles or mini-badges may use `rounded-full`.

4. **NO Radar Pings or Pulse Gimmicks:**
   - ❌ Never use `animate-ping` or distracting glowing animations on status dots.
   - ✅ Use clean, solid status dots: `<span className="size-1.5 rounded-full bg-emerald-500" />`.

5. **NO Arbitrary Tailwind Colors:**
   - ❌ Never use raw color classes like `bg-blue-600`, `text-purple-400`, `border-amber-300`.
   - ✅ Always use CSS semantic variables: `bg-background`, `bg-card`, `bg-muted`, `border-border`, `text-foreground`, `text-muted-foreground`.

6. **NO Generic "Salesy" Empty States:**
   - ❌ Never display "Hi there! What can I help you with?" or generic question cards like "Tell me a joke" or "Summary of X".
   - ✅ Default empty states must show actual technical data: system status, index health, and a catalog table of managed specs.

---

## 3. Strict Whitelist (ENGINEERING STANDARDS)

### 3.1 Palette (Zinc / Monochrome)
- **Dark Mode (Default & Priority):**
  - Background: `#09090b` (oklch neutral zinc 950)
  - Card / Panel: `#121215` (subtle elevation, 1px border)
  - Border: `#27272a` (1px hairline)
  - Foreground: `#f4f4f5` (clean zinc white)
  - Muted: `#71717a` (secondary text)
- **Light Mode:**
  - Background: `#fafafa`
  - Card / Panel: `#ffffff`
  - Border: `#e4e4e7`
  - Foreground: `#09090b`

### 3.2 Typography & Density
- **Font Family:** Neutral sans-serif for UI, monospace (`font-mono`) for all technical entities:
  - Spec IDs (`SPC-01`, `HR-M04`)
  - Chunks, tokens, hashes, latency (`14ms`, `768d`, `12 chunks`)
  - Code blocks and keyboard shortcuts (`<kbd>↵</kbd>`)
- **Type Scale:** Compact and readable. Main text is `text-sm` (14px), metadata is `text-xs` (12px) or `text-[11px]`.

### 3.3 Layout & Components
- **Split-Pane / Workspace Hierarchy:**
  - Left: Tree navigation & specs directory (`w-60` or `w-64`, hairline right border).
  - Center: High-density Document / Specs catalog or clean conversation stream.
  - Command Bar: Raycast-style search & query input with `<kbd>` shortcuts.
