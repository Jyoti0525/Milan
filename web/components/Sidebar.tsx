"use client";

/**
 * Where you are, and what there is to do — in the merchant's words.
 *
 * Modern Treasury's write-up on their reconciliation dashboard makes the case
 * for a side navigation organised around jobs rather than objects. This one
 * was organised around jobs and then labelled with our vocabulary: "Exception
 * queue", "Proved", "Charged above contract", each with a one-line
 * explanation that was `sr-only` and therefore invisible to everybody who
 * needed it.
 *
 * So the labels are now what a person came to do — **Needs you**, **Accounted
 * for**, **Overcharged** — and the explanation is on screen underneath rather
 * than in the accessibility tree. The precise terms have not been abandoned;
 * they are the headings of the panes those items open, where somebody who has
 * already decided to look is reading carefully.
 *
 * Two groups because there are two jobs. **Review** is about credits: what
 * could not be resolved, and what could. **Recover** is about rows that
 * reconciled perfectly and were still charged too much, which is somebody
 * else's morning entirely.
 *
 * The run picker has two halves for a different reason: a generated run is
 * scored against an answer key and an imported one has none. Listing them
 * together would let somebody read a figure from one as if it came from the
 * other.
 */

import type { ImportRef, RunRef } from "@/lib/api";
import { inr, type Paise } from "@/lib/money";
import { Badge } from "./Badge";

export type Tab = "queue" | "proved" | "leaks" | "provenance";

const TIER_ORDER = ["clean", "realistic", "messy", "adversarial"];

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="px-3 pb-3">
      <div className="mb-1 px-1 text-[11px] font-medium tracking-wide text-[var(--text-subtle)] uppercase">
        {title}
      </div>
      <div className="space-y-0.5">{children}</div>
    </div>
  );
}

function Item({
  label,
  hint,
  count,
  amount,
  active,
  onClick,
}: {
  label: string;
  hint: string;
  count: number;
  amount?: Paise;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="w-full rounded-[var(--r-control)] px-2.5 py-2 text-left transition-colors"
      style={{
        background: active ? "var(--surface-selected)" : undefined,
        color: active ? "var(--accent-strong)" : "var(--text-muted)",
      }}
    >
      <span className="flex items-center gap-2">
        <span className="flex-1 truncate text-[13px] font-medium">{label}</span>
        <span className="tnum text-[12px] text-[var(--text-subtle)]">{count}</span>
      </span>
      {/*
        On screen, not `sr-only`. These sentences are what tell somebody who
        has never seen this what the item is, and hiding them from everyone
        who can see the screen made the navigation four nouns and three
        numbers.
      */}
      <span className="mt-0.5 block text-[11px] leading-tight text-[var(--text-subtle)]">
        {amount !== undefined && amount > 0 ? `${inr(amount)} · ${hint}` : hint}
      </span>
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
  amounts,
}: {
  runs: RunRef[];
  imports: ImportRef[];
  current: { kind: "run"; run: RunRef } | { kind: "import"; ref: ImportRef } | null;
  onPick: (run: RunRef) => void;
  onPickImport: (ref: ImportRef) => void;
  tab: Tab;
  onTab: (tab: Tab) => void;
  counts: { queue: number; proved: number; leaks: number; provenance: number };
  amounts: { queue: Paise; proved: Paise; leaks: Paise };
}) {
  const imported = current?.kind === "import";
  const ordered = [...runs].sort(
    (a, b) =>
      TIER_ORDER.indexOf(a.difficulty) - TIER_ORDER.indexOf(b.difficulty) || a.seed - b.seed,
  );

  return (
    <aside className="hidden w-[236px] shrink-0 flex-col border-r border-[var(--border)] bg-[var(--surface)] lg:flex">
      <div className="pt-3">
        <Group title="Review">
          {/*
            No rupee figure here, deliberately. This queue holds two different
            populations - credits that arrived and would not reconstruct, and
            payouts the bank never received - and one total across both is a
            number the merchant does not have anywhere. The headline strip
            splits them properly; a sidebar cannot, so it counts instead.
          */}
          <Item
            label="Needs you"
            hint="we would not guess at these"
            count={counts.queue}
            active={tab === "queue"}
            onClick={() => onTab("queue")}
          />
          <Item
            label="Accounted for"
            hint="rebuilt to the paisa"
            count={counts.proved}
            amount={amounts.proved}
            active={tab === "proved"}
            onClick={() => onTab("proved")}
          />
        </Group>

        {/*
          Its own group, not a third item under Review. Every row behind a leak
          *was* resolved - it reconciled to the paisa - so listing it beside
          them would suggest the reconciliation missed something. It did not.
          The price was wrong, which is a different job for a different person.
        */}
        <Group title="Recover">
          <Item
            label="Overcharged"
            hint="balanced, and still priced wrong"
            count={counts.leaks}
            amount={amounts.leaks}
            active={tab === "leaks"}
            onClick={() => onTab("leaks")}
          />
        </Group>

        {/*
          Only on an imported run, because only an imported run has one. A
          generated run's provenance is its seed; there is nothing to audit.
        */}
        {imported && (
          <Group title="Audit">
            <Item
              label="How this was read"
              hint="which columns, and who decided"
              count={counts.provenance}
              active={tab === "provenance"}
              onClick={() => onTab("provenance")}
            />
          </Group>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-auto border-t border-[var(--border)] py-3">
        <Group title="Your files">
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
                {/* Only when a model was consulted, so its absence is the
                    statement that none was. */}
                {ref.consulted !== "none" && <Badge tone="accent">{ref.consulted}</Badge>}
              </button>
            );
          })}
          {imports.length === 0 && (
            <div className="px-1 text-[11.5px] leading-relaxed text-[var(--text-subtle)]">
              None yet. Use <span className="font-medium">Import your files</span> above.
            </div>
          )}
        </Group>

        <Group title="Sample runs">
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
                {run.stale && <Badge tone="warn">stale</Badge>}
                {/* `#42` rather than `42`, because the two lists in this
                    sidebar put a right-aligned grey number in the same place
                    and mean different things by it. */}
                <span className="tnum text-[11px] text-[var(--text-subtle)]">#{run.seed}</span>
              </button>
            );
          })}
          {ordered.length === 0 && (
            <div className="px-1 text-[11.5px] text-[var(--text-subtle)]">none generated</div>
          )}
        </Group>
      </div>

      <div className="border-t border-[var(--border)] px-4 py-3 text-[11px] leading-relaxed text-[var(--text-subtle)]">
        {imported
          ? "These are your own files. There is no answer key, so nothing here is scored — the audit tab says how it was read."
          : "Every figure here is measured against a generated answer key, never estimated."}
      </div>
    </aside>
  );
}
