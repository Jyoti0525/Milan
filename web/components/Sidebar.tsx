"use client";

/**
 * Where you are, and what there is to do.
 *
 * Modern Treasury's write-up on their reconciliation dashboard makes the case
 * for a side navigation organised around jobs rather than objects, and the
 * earlier version of this screen had no navigation at all — a header strip
 * and two tabs floating above a table. This gives the run picker somewhere to
 * live and puts the lists where they can be counted at a glance.
 *
 * Two groups, because there are two jobs. **Review** is about credits: what
 * could not be resolved, and what could. **Recover** is about rows that
 * reconciled perfectly and were still charged too much, which is somebody
 * else's morning entirely.
 *
 * The run picker at the bottom has two halves for the same reason. A
 * generated run is scored against an answer key; an imported one is a folder
 * of the merchant's own CSVs and has none. Listing them together under one
 * heading would let somebody read a figure from one as if it came from the
 * other, so they are two lists with two headings and the difference is said
 * in the footer.
 */

import type { ImportRef, RunRef } from "@/lib/api";
import { Badge } from "./Badge";

export type Tab = "queue" | "proved" | "leaks" | "provenance";

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
  imports,
  current,
  onPick,
  onPickImport,
  tab,
  onTab,
  counts,
}: {
  runs: RunRef[];
  imports: ImportRef[];
  current: { kind: "run"; run: RunRef } | { kind: "import"; ref: ImportRef } | null;
  onPick: (run: RunRef) => void;
  onPickImport: (ref: ImportRef) => void;
  tab: Tab;
  onTab: (tab: Tab) => void;
  counts: { queue: number; proved: number; leaks: number; provenance: number };
}) {
  const imported = current?.kind === "import";
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

      {/*
        Its own group, not a third item under Review.

        Review is about credits: what could not be resolved, and what could.
        Every row behind a leak *was* resolved - it reconciled to the paisa -
        so listing it beside them would suggest the reconciliation missed
        something. It did not. The price was wrong, which is a different job
        for a different person, and the heading has to say so before the count
        does.
      */}
      <div className="px-3 pb-3">
        <div className="mb-1.5 px-1 text-[11px] font-medium tracking-wide text-[var(--text-subtle)] uppercase">
          Recover
        </div>
        <div className="space-y-0.5">
          <Item
            label="Charged above contract"
            count={counts.leaks}
            active={tab === "leaks"}
            onClick={() => onTab("leaks")}
            hint="findings on rows that balanced"
          />
        </div>
      </div>

      {/*
        Only on an imported run, because only an imported run has one.

        A generated run's provenance is its seed - it is a pure function of an
        integer, and there is nothing to audit. A merchant's folder was read,
        and every decision made while reading it is a decision somebody may
        want to check. Showing this tab on both would mean writing a version
        of it that says "generated" and nothing else.
      */}
      {imported && (
        <div className="px-3 pb-3">
          <div className="mb-1.5 px-1 text-[11px] font-medium tracking-wide text-[var(--text-subtle)] uppercase">
            Audit
          </div>
          <div className="space-y-0.5">
            <Item
              label="How this was read"
              count={counts.provenance}
              active={tab === "provenance"}
              onClick={() => onTab("provenance")}
              hint="which columns, which model, what was refused"
            />
          </div>
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-auto border-t border-[var(--border)] px-3 py-3">
        <div className="mb-1.5 px-1 text-[11px] font-medium tracking-wide text-[var(--text-subtle)] uppercase">
          Runs
        </div>
        <div className="space-y-0.5">
          {ordered.map((run) => {
            const active =
              current?.kind === "run" &&
              current.run.difficulty === run.difficulty &&
              current.run.seed === run.seed;
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

        <div className="mt-4 mb-1.5 px-1 text-[11px] font-medium tracking-wide text-[var(--text-subtle)] uppercase">
          Imported
        </div>
        <div className="space-y-0.5">
          {imports.map((ref) => {
            const active = current?.kind === "import" && current.ref.slug === ref.slug;
            return (
              <button
                key={ref.slug}
                onClick={() => onPickImport(ref)}
                className="flex w-full items-center gap-2 rounded-[var(--r-control)] px-2.5 py-1.5 text-left"
                style={{
                  background: active ? "var(--surface-selected)" : undefined,
                  color: active ? "var(--accent-strong)" : "var(--text-muted)",
                }}
                title={ref.source_root}
              >
                <span className="flex-1 truncate text-[13px]">{ref.slug}</span>
                {/* Which model read the columns, or nothing at all. The badge
                    appears only when one was consulted, so its absence is the
                    statement that none was. */}
                {ref.consulted !== "none" && <Badge tone="accent">{ref.consulted}</Badge>}
              </button>
            );
          })}
          {imports.length === 0 && (
            <div className="px-1 text-[12px] leading-relaxed text-[var(--text-subtle)]">
              none yet — point Milan at a folder with{" "}
              <span className="font-mono text-[11px]">milan import</span>
            </div>
          )}
        </div>
      </div>

      {/*
        Two sentences, because the picker above now holds two kinds of run and
        only one of them can be scored. A footer that claimed an answer key
        for both would be the exact misreading the split headings exist to
        prevent.
      */}
      <div className="border-t border-[var(--border)] px-4 py-3 text-[11px] leading-relaxed text-[var(--text-subtle)]">
        {imported
          ? "These are the merchant's own files. There is no answer key, so nothing here is scored — the audit tab says how it was read."
          : "Every figure here is measured against a generated answer key, never estimated."}
      </div>
    </aside>
  );
}
