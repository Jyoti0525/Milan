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
import { Empty, Id, rowProps, type Selection } from "./Table";
import { codeLabel, codeTone, severity } from "./codes";

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
                  <Id id={item.subject.id} />
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
          {/*
            This column used to be `Status`, and on this tab every row of it
            read "Proved" - a column of one repeated word, taking the width
            where the reader's eye lands first. Which rung of the cascade got
            there varies, and is the thing worth knowing about a proof that
            the tab heading does not already say.
          */}
          <th className="th w-[124px]">Resolved by</th>
          <th className="th">Bank credit</th>
          <th className="th text-right">Amount</th>
        </tr>
      </thead>
      <tbody>
        {proofs.map((proof, index) => {
          const active = selected?.kind === "proof" && selected.index === index;
          // What is unusual about this proof, and nothing that is not. A row
          // with an ordinary one-to-one match and no drift carries no note at
          // all, which is what makes the rows that do carry one stand out.
          const notes = [
            proof.settlement_ids.length > 1
              ? `${proof.settlement_ids.length} settlements merged`
              : null,
            proof.drift !== 0 ? "rounding drift" : null,
          ].filter((note): note is string => note !== null);
          return (
            <tr
              key={proof.credit_id}
              {...rowProps(active, () => onSelect({ kind: "proof", index }))}
            >
              <td className="td align-top">
                <span className="text-[12.5px] text-[var(--text-muted)]">
                  {proof.strategy.replace(/_/g, " ")}
                </span>
              </td>
              <td className="td">
                <div className="flex items-center gap-2">
                  <Id id={proof.credit_id} />
                  <span className="tnum text-[11px] text-[var(--text-subtle)]">
                    {shortDate(proof.value_date)}
                  </span>
                </div>
                {notes.length > 0 && (
                  <div className="mt-1.5 flex flex-wrap items-center gap-x-1.5 gap-y-1">
                    {notes.map((note, position) => (
                      <Tag key={note}>
                        {position > 0 && <span className="mr-1.5">·</span>}
                        {note}
                      </Tag>
                    ))}
                  </div>
                )}
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
