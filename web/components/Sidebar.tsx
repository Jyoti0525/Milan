"use client";

/**
 * Where you are, and what there is to do.
 *
 * Modern Treasury's write-up on their reconciliation dashboard makes the case
 * for a side navigation organised around jobs rather than objects, and the
 * earlier version of this screen had no navigation at all — a header strip
 * and two tabs floating above a table. This gives the run picker somewhere to
 * live and puts the two halves of the answer where they can be counted at a
 * glance.
 */

import type { RunRef } from "@/lib/api";
import { Badge } from "./Badge";

export type Tab = "queue" | "proved";

const TIER_ORDER = ["clean", "realistic", "messy", "adversarial"];

function Item({
  label,
  count,
  active,
  onClick,
  hint,
}: {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
  hint: string;
}) {
  return (
    <button
      onClick={onClick}
      className="flex w-full items-center gap-2 rounded-[var(--r-control)] px-2.5 py-2 text-left transition-colors"
      style={{
        background: active ? "var(--surface-selected)" : undefined,
        color: active ? "var(--accent-strong)" : "var(--text-muted)",
      }}
    >
      <span className="flex-1 truncate text-[13px] font-medium">{label}</span>
      <span className="tnum text-[12px] text-[var(--text-subtle)]">{count}</span>
      <span className="sr-only">{hint}</span>
    </button>
  );
}

export function Sidebar({
  runs,
  current,
  onPick,
  tab,
  onTab,
  counts,
}: {
  runs: RunRef[];
  current: RunRef | null;
  onPick: (run: RunRef) => void;
  tab: Tab;
  onTab: (tab: Tab) => void;
  counts: { queue: number; proved: number };
}) {
  const ordered = [...runs].sort(
    (a, b) =>
      TIER_ORDER.indexOf(a.difficulty) - TIER_ORDER.indexOf(b.difficulty) || a.seed - b.seed,
  );

  return (
    <aside className="hidden w-[228px] shrink-0 flex-col border-r border-[var(--border)] bg-[var(--surface)] lg:flex">
      <div className="flex h-[56px] items-center gap-2 px-4">
        <span
          aria-hidden
          className="grid h-6 w-6 place-items-center rounded-[6px] text-[12px] font-bold text-white"
          style={{ background: "var(--accent)" }}
        >
          M
        </span>
        <div className="min-w-0">
          <div className="truncate text-[14px] font-semibold tracking-[-0.01em]">Milan</div>
        </div>
      </div>

      <div className="px-3 pt-1 pb-3">
        <div className="mb-1.5 px-1 text-[11px] font-medium tracking-wide text-[var(--text-subtle)] uppercase">
          Review
        </div>
        <div className="space-y-0.5">
          <Item
            label="Exception queue"
            count={counts.queue}
            active={tab === "queue"}
            onClick={() => onTab("queue")}
            hint="what could not be resolved"
          />
          <Item
            label="Proved"
            count={counts.proved}
            active={tab === "proved"}
            onClick={() => onTab("proved")}
            hint="credits rebuilt to the paisa"
          />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto border-t border-[var(--border)] px-3 py-3">
        <div className="mb-1.5 px-1 text-[11px] font-medium tracking-wide text-[var(--text-subtle)] uppercase">
          Runs
        </div>
        <div className="space-y-0.5">
          {ordered.map((run) => {
            const active =
              current?.difficulty === run.difficulty && current?.seed === run.seed;
            return (
              <button
                key={`${run.difficulty}:${run.seed}`}
                onClick={() => onPick(run)}
                className="flex w-full items-center gap-2 rounded-[var(--r-control)] px-2.5 py-1.5 text-left"
                style={{
                  background: active ? "var(--surface-selected)" : undefined,
                  color: active ? "var(--accent-strong)" : "var(--text-muted)",
                }}
              >
                <span className="flex-1 truncate text-[13px] capitalize">{run.difficulty}</span>
                {/* The seed identifies the run, so it shows either way. Stale
                    is an extra fact about it, not a replacement for it. */}
                {run.stale && <Badge tone="warn">stale</Badge>}
                {/*
                  Written `#42`, because the two groups in this sidebar put a
                  right-aligned grey number in the same place and mean
                  different things by it: 37 above is how many cases there are,
                  42 here is which dataset this is. Two tiers can share a name
                  and differ only by seed, so it has to be shown - and the hash
                  is what stops it being read as a count.
                */}
                <span className="tnum text-[11px] text-[var(--text-subtle)]">#{run.seed}</span>
              </button>
            );
          })}
          {ordered.length === 0 && (
            <div className="px-1 text-[12px] text-[var(--text-subtle)]">none generated</div>
          )}
        </div>
      </div>

      <div className="border-t border-[var(--border)] px-4 py-3 text-[11px] leading-relaxed text-[var(--text-subtle)]">
        Every figure here is measured against a generated answer key, never
        estimated.
      </div>
    </aside>
  );
}
