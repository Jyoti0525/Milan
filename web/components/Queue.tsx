"use client";

/**
 * The queue, and the proved list beside it.
 *
 * Both are Blade tables: a light header row, generous cells, hairline rules
 * between rows, identifiers on mono chips and money right-aligned in the
 * `Amount` face. They share a shape because they are two answers to the same
 * question, and a reader switching between them should not have to relearn
 * the layout.
 *
 * The summary is not truncated. An earlier version clipped it at one line
 * with an ellipsis, which turned every row into half a sentence — and the
 * whole claim of this project is that the exception text is the deliverable.
 * A case you cannot read is a case you cannot pick up.
 *
 * Sorted worst-first rather than by id. A settlement that never arrived and a
 * two-rupee rounding note are not equally urgent.
 */

import type { Proof, QueueItem } from "@/lib/api";
import { shortDate, withRupeeSign } from "@/lib/money";
import { Amount } from "./Amount";
import { Badge, Tag } from "./Badge";
import { codeLabel, codeTone, severity } from "./codes";

export type Selection =
  | { kind: "exception"; index: number }
  | { kind: "proof"; index: number };

export function sortQueue(items: QueueItem[]): { item: QueueItem; index: number }[] {
  return items
    .map((item, index) => ({ item, index }))
    .sort(
      (a, b) =>
        severity(a.item.code) - severity(b.item.code) ||
        Math.abs(b.item.amount) - Math.abs(a.item.amount) ||
        a.item.subject.id.localeCompare(b.item.subject.id),
    );
}

function shortId(id: string): string {
  const body = id.replace(/^(bank|setl|pay|order)_/, "");
  return body.length > 10 ? `${body.slice(0, 10)}…` : body;
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="px-6 py-10 text-center text-[13px] text-[var(--text-subtle)]">{children}</div>;
}

/** Not a hook — plain props. Named without `use` so it is not treated as one. */
function rowProps(active: boolean, choose: () => void) {
  return {
    "aria-selected": active,
    tabIndex: 0,
    onClick: choose,
    onKeyDown: (event: React.KeyboardEvent) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        choose();
      }
    },
    className: "row-link",
  };
}

export function QueueList({
  items,
  selected,
  onSelect,
}: {
  items: QueueItem[];
  selected: Selection | null;
  onSelect: (selection: Selection) => void;
}) {
  const ordered = sortQueue(items);
  if (ordered.length === 0) return <Empty>Nothing unresolved in this run.</Empty>;

  return (
    <table className="w-full border-collapse">
      <thead>
        <tr>
          {/*
            Three columns, not five. The subject and the date used to have
            their own, and between them they squeezed the summary into four
            wrapped lines and pushed the amount off the edge of the pane.
            They belong under the sentence they qualify.
          */}
          <th className="th w-[132px]">Type</th>
          <th className="th">What happened</th>
          <th className="th text-right">Amount</th>
        </tr>
      </thead>
      <tbody>
        {ordered.map(({ item, index }) => {
          const active = selected?.kind === "exception" && selected.index === index;
          return (
            <tr
              key={`${item.subject.id}-${index}`}
              {...rowProps(active, () => onSelect({ kind: "exception", index }))}
            >
              <td className="td align-top">
                <Badge tone={codeTone(item.code)}>{codeLabel(item.code)}</Badge>
              </td>
              <td className="td">
                <div className="text-[13px] leading-snug text-[var(--text)]">{withRupeeSign(item.summary)}</div>
                <div className="mt-1.5 flex items-center gap-2">
                  <span className="chip font-mono text-[10.5px]">
                    {shortId(item.subject.id)}
                  </span>
                  <span className="tnum text-[11px] text-[var(--text-subtle)]">
                    {item.subject.occurred_on ? shortDate(item.subject.occurred_on) : "no date"}
                  </span>
                </div>
              </td>
              <td className="td align-top text-right whitespace-nowrap">
                {item.amount === 0 ? (
                  <span className="text-[12px] text-[var(--text-disabled)]">—</span>
                ) : (
                  <Amount paise={item.amount} size="md" />
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function ProofList({
  proofs,
  selected,
  onSelect,
}: {
  proofs: Proof[];
  selected: Selection | null;
  onSelect: (selection: Selection) => void;
}) {
  if (proofs.length === 0) return <Empty>Nothing proved in this run.</Empty>;

  return (
    <table className="w-full border-collapse">
      <thead>
        <tr>
          <th className="th w-[92px]">Status</th>
          <th className="th">Bank credit</th>
          <th className="th text-right">Amount</th>
        </tr>
      </thead>
      <tbody>
        {proofs.map((proof, index) => {
          const active = selected?.kind === "proof" && selected.index === index;
          return (
            <tr
              key={proof.credit_id}
              {...rowProps(active, () => onSelect({ kind: "proof", index }))}
            >
              <td className="td align-top">
                <Badge tone="good">Proved</Badge>
              </td>
              <td className="td">
                <div className="flex items-center gap-2">
                  <span className="chip font-mono text-[10.5px]">
                    {shortId(proof.credit_id)}
                  </span>
                  <span className="tnum text-[11px] text-[var(--text-subtle)]">
                    {shortDate(proof.value_date)}
                  </span>
                </div>
                <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="text-[12.5px] text-[var(--text-muted)]">
                    resolved by {proof.strategy.replace(/_/g, " ")}
                  </span>
                  {proof.settlement_ids.length > 1 && (
                    <Tag>· {proof.settlement_ids.length} settlements merged</Tag>
                  )}
                  {proof.drift !== 0 && <Tag>· rounding drift</Tag>}
                </div>
              </td>
              <td className="td align-top text-right whitespace-nowrap">
                <Amount paise={proof.credit_amount} size="md" />
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
