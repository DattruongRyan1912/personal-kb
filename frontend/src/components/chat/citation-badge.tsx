"use client";

import { BookOpen, FileText } from "lucide-react";
import { useState } from "react";

import { SpecDrawer } from "@/components/chat/spec-drawer";
import { Button } from "@/components/ui/button";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "@/components/ui/hover-card";
import { getSpecCard, type SpecCard } from "@/lib/api";

/** A citation `[Tên tài liệu](SPEC_ID)` as an inline pill (issue 3.4); hovering, focusing, tapping or clicking it
 * shows the spec's card, and clicking opens the full-text slide-over drawer. */
export function CitationBadge({ specId, title }: { specId: string; title: string }) {
  const [open, setOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [card, setCard] = useState<SpecCard | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const toggle = (next: boolean) => {
    setOpen(next);
    if (!next || card) return;
    setFailure(null);
    getSpecCard(specId).then(setCard, (e) => setFailure(e instanceof Error ? e.message : String(e)));
  };

  const handleOpenDrawer = () => {
    setOpen(false);
    setDrawerOpen(true);
  };

  return (
    <>
      <HoverCard open={open} onOpenChange={toggle}>
        <HoverCardTrigger
          delay={150}
          render={<button type="button" onClick={() => toggle(!open)} />}
          aria-label={`Tài liệu ${specId}: ${title}`}
          className="mx-0.5 inline-flex max-w-[18rem] cursor-pointer items-center gap-1 rounded-sm border border-border bg-muted/60 px-1.5 py-0.5 align-[0.05em] text-xs leading-4 font-mono text-foreground shadow-2xs hover:bg-muted hover:border-foreground/30 focus-visible:ring-1 focus-visible:ring-ring focus-visible:outline-none transition-colors"
        >
          <FileText className="size-3 shrink-0 text-muted-foreground" />
          <span className="truncate font-sans font-medium">{title || specId}</span>
          <span className="shrink-0 font-mono text-[0.7rem] text-muted-foreground">{specId}</span>
        </HoverCardTrigger>
        <HoverCardContent className="w-80 border-border bg-popover p-3 rounded-md shadow-md">
          <SpecCardBody specId={specId} card={card} failure={failure} onViewContent={handleOpenDrawer} />
        </HoverCardContent>
      </HoverCard>

      {/* Slide-over Drawer for full markdown spec provenance */}
      <SpecDrawer specId={drawerOpen ? specId : null} onClose={() => setDrawerOpen(false)} />
    </>
  );
}

export function SpecCardBody({
  specId,
  card,
  failure,
  onViewContent,
}: {
  specId: string;
  card: SpecCard | null;
  failure: string | null;
  onViewContent?: () => void;
}) {
  if (failure) return <p className="text-xs text-destructive font-mono">Không tải được {specId}: {failure}</p>;
  if (!card) return <p className="animate-pulse text-xs text-muted-foreground font-mono">Đang tải {specId}…</p>;
  const approved = card.status.toUpperCase() === "APPROVED";
  return (
    <dl className="space-y-2 text-xs">
      <div>
        <dt className="sr-only">Tên spec</dt>
        <dd className="text-sm font-semibold text-foreground">{card.title}</dd>
        <dd className="font-mono text-[11px] text-muted-foreground">{card.spec_id}</dd>
      </div>
      <div className="flex gap-2">
        <dt className="text-muted-foreground">Người tạo:</dt>
        <dd className="text-foreground">{card.owner ?? "—"}</dd>
      </div>
      <div className="flex items-center gap-2">
        <dt className="text-muted-foreground">Trạng thái:</dt>
        <dd>
          <span
            className={
              approved
                ? "rounded-sm border border-emerald-500/30 bg-emerald-500/10 px-1.5 py-0.5 font-mono text-[10px] text-emerald-500 font-medium"
                : "rounded-sm border border-amber-500/30 bg-amber-500/10 px-1.5 py-0.5 font-mono text-[10px] text-amber-500 font-medium"
            }
          >
            {approved ? "Approved" : card.status}
          </span>
        </dd>
      </div>

      {onViewContent && (
        <div className="pt-2 border-t border-border">
          <Button
            size="sm"
            variant="default"
            className="w-full h-7 text-xs font-mono gap-1.5 bg-foreground text-background hover:bg-foreground/90 rounded-sm"
            onClick={onViewContent}
          >
            <BookOpen className="size-3.5" />
            <span>Xem toàn văn tài liệu</span>
          </Button>
        </div>
      )}
    </dl>
  );
}
