"use client";

import { useCallback, useEffect, useRef } from "react";

export const NEAR_BOTTOM_PX = 48;

type Metrics = { scrollTop: number; scrollHeight: number; clientHeight: number };

export function isNearBottom(el: Metrics): boolean {
  return el.scrollHeight - el.scrollTop - el.clientHeight <= NEAR_BOTTOM_PX;
}

/** Whether to follow after a scroll event: any move up stops it, even within the margin, unless the content shrank
 * and the browser moved a view kept at its end; reaching the bottom again resumes it. */
export function followsAfterScroll(following: boolean, lastTop: number, el: Metrics): boolean {
  const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
  if (el.scrollTop < lastTop && distance > 1) return false;
  if (distance <= NEAR_BOTTOM_PX) return true;
  return following;
}

/** Follows the newest text only while the user stays at the bottom (issue 3.2): scrolling up, even slightly, stops
 * it at once; coming back to the bottom resumes it. `viewport` scrolls, `content` is what grows inside it. */
export function useAutoScroll() {
  const viewport = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const following = useRef(true);

  useEffect(() => {
    const el = viewport.current;
    const inner = content.current;
    if (!el || !inner) return;
    let touchY = 0;
    let lastTop = el.scrollTop;
    // a scroll event comes from the user, our own jump to the bottom, or content shrinking under the view
    const onScroll = () => {
      following.current = followsAfterScroll(following.current, lastTop, el);
      lastTop = el.scrollTop;
    };
    const onWheel = (e: WheelEvent) => {
      if (e.deltaY < 0) following.current = false;
    };
    const onTouchStart = (e: TouchEvent) => {
      touchY = e.touches[0]?.clientY ?? 0;
    };
    const onTouchMove = (e: TouchEvent) => {
      if ((e.touches[0]?.clientY ?? 0) > touchY) following.current = false; // finger down: reading upwards
    };
    const observer = new ResizeObserver(() => {
      if (following.current) el.scrollTop = el.scrollHeight;
    });
    el.addEventListener("scroll", onScroll, { passive: true });
    el.addEventListener("wheel", onWheel, { passive: true });
    el.addEventListener("touchstart", onTouchStart, { passive: true });
    el.addEventListener("touchmove", onTouchMove, { passive: true });
    observer.observe(inner);
    return () => {
      el.removeEventListener("scroll", onScroll);
      el.removeEventListener("wheel", onWheel);
      el.removeEventListener("touchstart", onTouchStart);
      el.removeEventListener("touchmove", onTouchMove);
      observer.disconnect();
    };
  }, []);

  const scrollToBottom = useCallback(() => {
    following.current = true;
    const el = viewport.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, []);

  return { viewport, content, scrollToBottom };
}
