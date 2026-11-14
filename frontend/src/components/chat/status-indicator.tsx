import { LoaderCircle } from "lucide-react";

/** What the agent is doing, until the first word of the answer arrives (issue 3.4). */
export function StatusIndicator({ message }: { message: string }) {
  return (
    <div role="status" aria-live="polite" className="flex">
      <span className="inline-flex animate-pulse items-center gap-2 rounded-full border bg-muted/60 px-3 py-1 text-xs text-muted-foreground">
        <LoaderCircle className="size-3.5 animate-spin" />
        {message}
      </span>
    </div>
  );
}
