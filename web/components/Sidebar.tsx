"use client";

/**
 * Where you are, and what there is to do — in the merchant's words.
 *
 * The labels are what a person came to do — **Needs you**, **Accounted for**,
 * **Overcharged** — rather than what the engine calls those things. The
 * precise terms are the headings of the panes those items open, where somebody
 * who has already decided to look is reading carefully.
 *
 * Every item used to carry its explanation underneath, on screen, because
 * before that the explanations were `sr-only` and therefore invisible to
 * everybody who needed them. Both versions were wrong in the same way: three
 * items and three sentences is six lines of navigation, and a person scanning
 * for where to click reads the labels and nothing else. So the sentence is
 * back to being a `title`, and the thing that carries urgency is the count —
 * amber when the queue has something in it, quiet when it does not.
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
 *
 * The generated half is folded shut. It earns its place - it is what makes
 * every accuracy claim here checkable - but six sample months stacked above a
 * merchant's four real imports reads as a demo with the customer's data filed
 * underneath it. One click reopens it, and nothing is deleted.
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
  tone,
  active,
  onClick,
}: {
  label: string;
  hint: string;
  count: number;
  amount?: Paise;
  /** Colour for the count when there is something in it. */
  tone?: string;
  active: boolean;
  onClick: () => void;
}) {
  const live = count > 0 && tone !== undefined;
  return (
    <button
      onClick={onClick}
      title={hint}
      className="w-full rounded-[var(--r-control)] px-2.5 py-[7px] text-left transition-colors hover:bg-[var(--surface-hover)]"
      style={{
        background: active ? "var(--surface-selected)" : undefined,
        color: active ? "var(--accent-strong)" : "var(--text-muted)",
      }}
    >
      <span className="flex items-center gap-2">
        <span className="flex-1 truncate text-[13px] font-medium">{label}</span>
        {/*
          The count carries the urgency the sentence underneath used to carry.
          A pill when there is something to do and plain grey when there is
          not, so a person scanning three items sees which one wants them
          without reading a word.
        */}
        <span
          className="tnum shrink-0 rounded-full px-1.5 text-[11.5px] leading-[18px] font-medium"
          style={{
            background: live ? `var(${tone}-wash)` : "transparent",
            color: live ? `var(${tone})` : "var(--text-subtle)",
          }}
        >
          {count}
        </span>
      </span>
      {/*
        The rupee figure stays, because it is a fact rather than a caption and
        it is the thing that decides which item somebody opens first.
      */}
      {amount !== undefined && amount > 0 && (
        <span className="tnum mt-0.5 block text-[11px] leading-tight text-[var(--text-subtle)]">
          {inr(amount)}
        </span>
      )}
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
    <aside className="hidden w-[228px] shrink-0 flex-col border-r border-[var(--border)] bg-[var(--surface)] lg:flex">
      <div className="pt-3">
        <Group title="Review">
          {/*
            No rupee figure on this one, deliberately. The queue holds two
            different populations - credits that arrived and would not
            reconstruct, and payouts the bank never received - and one total
            across both is a number the merchant does not have anywhere. The
            headline strip splits them properly; a sidebar cannot, so it counts.
          */}
          <Item
            label="Needs you"
            hint="Credits the engine would not claim, and the reason for each. Worst first."
            count={counts.queue}
            tone="--warn"
            active={tab === "queue"}
            onClick={() => onTab("queue")}
          />
          <Item
            label="Accounted for"
            hint="Credits rebuilt from their settlement rows to the paisa — fee, GST and refunds included."
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
            hint="Rows that reconciled perfectly and were still charged above your contracted rate."
            count={counts.leaks}
            amount={amounts.leaks}
            tone="--bad"
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
              hint="Which column became which field, who decided, and what was refused."
              count={counts.provenance}
              active={tab === "provenance"}
              onClick={() => onTab("provenance")}
            />
          </Group>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-auto border-t border-[var(--border)] py-3">
        <Group title="Your books">
          {imports.map((ref) => {
            const active = current?.kind === "import" && current.ref.slug === ref.slug;
            return (
              <button
                key={ref.slug}
                onClick={() => onPickImport(ref)}
                className="flex w-full items-center gap-2 rounded-[var(--r-control)] px-2.5 py-1.5 text-left hover:bg-[var(--surface-hover)]"
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
              None yet — use <span className="font-medium">Import your files</span> above.
            </div>
          )}
        </Group>

        {/*
          Folded away, and open only when somebody asks for it.

          These are generated months. They are the reason every accuracy claim
          in this project is checkable rather than asserted, and they have no
          business being the first thing in a sidebar belonging to a merchant
          with their own books in it - six sample runs above four real imports
          reads as a demo with the customer's data filed underneath.

          A `<details>` rather than a flag, so it is one click back rather
          than a rebuild, and nothing is deleted. Closed by default; the
          browser's own in-page search still finds what is inside it.
        */}
        <details className="explain px-3 pb-3">
          <summary className="mb-1 flex cursor-pointer list-none items-center gap-1.5 px-1 text-[11px] font-medium tracking-wide text-[var(--text-subtle)] uppercase transition-colors hover:text-[var(--text-muted)]">
            <span aria-hidden className="text-[9px] leading-none">
              &#9656;
            </span>
            Sample data
            <span className="tnum ml-auto text-[11px] normal-case">{ordered.length}</span>
          </summary>
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
                className="flex w-full items-center gap-2 rounded-[var(--r-control)] px-2.5 py-1.5 text-left hover:bg-[var(--surface-hover)]"
                style={{
                  background: active ? "var(--surface-selected)" : undefined,
                  color: active ? "var(--accent-strong)" : "var(--text-muted)",
                }}
                title={`${run.orders} orders, generated from seed ${run.seed}`}
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
          </div>
        </details>
      </div>
    </aside>
  );
}
