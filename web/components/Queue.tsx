"use client";

/**
 * The queue, and the proved list beside it.
 *
 * Both are the same shape of thing - one row per credit, thirty pixels high,
 * id on the left, money on the right - because they are two answers to the
 * same question and a reader switching between them should not have to
 * relearn the layout.
 *
 * The queue is sorted worst-first rather than by id. A settlement that never
 * arrived and a two-rupee rounding note are not equally urgent, and a list
 * that treats them as equal makes somebody scroll to find out which is which.
 */

import type { Proof, QueueItem } from "@/lib/api";
import { rupees, shortDate } from "@/lib/money";
import { codeTone, severity } from "./codes";

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
  return body.length > 12 ? `${body.slice(0, 12)}…` : body;
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

  if (ordered.length === 0) {
    return (
      <div className="px-4 py-6 text-[12.5px] text-[var(--ink-faint)]">
        Nothing unresolved in this run.
      </div>
    );
  }

  return (
    <table className="w-full border-collapse">
      <tbody>
        {ordered.map(({ item, index }) => {
          const active = selected?.kind === "exception" && selected.index === index;
          const tone = codeTone(item.code);
          return (
            <tr
              key={`${item.subject.id}-${index}`}
              tabIndex={0}
              onClick={() => onSelect({ kind: "exception", index })}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelect({ kind: "exception", index });
                }
              }}
              className={`row rule-b cursor-pointer ${active ? "selected" : "hoverable"}`}
            >
              <td className="w-0 pl-3 pr-2">
                <span
                  aria-hidden
                  className="block h-3.5 w-[2px]"
                  style={{ background: tone }}
                />
              </td>
              <td className="max-w-0 py-0 pr-2">
                <div className="truncate text-[12px]">{item.summary}</div>
              </td>
              <td className="w-[86px] py-0 pr-2">
                <span className="ident text-[10.5px]">{shortId(item.subject.id)}</span>
              </td>
              <td className="w-[62px] py-0 pr-2 text-right">
                <span className="figure text-[11px] text-[var(--ink-faint)]">
                  {item.subject.occurred_on ? shortDate(item.subject.occurred_on) : "—"}
                </span>
              </td>
              <td className="w-[104px] py-0 pr-3 text-right">
                <span className="figure text-[12px]" style={{ color: tone }}>
                  {item.amount === 0 ? "—" : rupees(item.amount)}
                </span>
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
  if (proofs.length === 0) {
    return (
      <div className="px-4 py-6 text-[12.5px] text-[var(--ink-faint)]">
        Nothing proved in this run.
      </div>
    );
  }

  return (
    <table className="w-full border-collapse">
      <tbody>
        {proofs.map((proof, index) => {
          const active = selected?.kind === "proof" && selected.index === index;
          return (
            <tr
              key={proof.credit_id}
              tabIndex={0}
              onClick={() => onSelect({ kind: "proof", index })}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelect({ kind: "proof", index });
                }
              }}
              className={`row rule-b cursor-pointer ${active ? "selected" : "hoverable"}`}
            >
              <td className="w-0 pl-3 pr-2">
                <span
                  aria-hidden
                  className="block h-3.5 w-[2px]"
                  style={{ background: "var(--good)" }}
                />
              </td>
              <td className="max-w-0 py-0 pr-2">
                <span className="ident text-[11px]">{shortId(proof.credit_id)}</span>
                {proof.settlement_ids.length > 1 && (
                  <span className="ml-2 text-[11px] text-[var(--ink-faint)]">
                    {proof.settlement_ids.length} merged
                  </span>
                )}
                {proof.drift !== 0 && (
                  <span className="ml-2 text-[11px] text-[var(--ink-faint)]">drift</span>
                )}
              </td>
              <td className="w-[110px] py-0 pr-2">
                <span className="text-[11px] text-[var(--ink-faint)]">
                  {proof.strategy.replace(/_/g, " ")}
                </span>
              </td>
              <td className="w-[62px] py-0 pr-2 text-right">
                <span className="figure text-[11px] text-[var(--ink-faint)]">
                  {shortDate(proof.value_date)}
                </span>
              </td>
              <td className="w-[104px] py-0 pr-3 text-right">
                <span className="figure text-[12px]">{rupees(proof.credit_amount)}</span>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
