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

import { useState } from "react";
import type { ExceptionCode, Proof, QueueItem } from "@/lib/api";
import { inr, shortDate, withRupeeSign } from "@/lib/money";
import { Amount } from "./Amount";
import { Badge, Tag } from "./Badge";
import { Empty, Id, rowProps, type Selection } from "./Table";
import { codeLabel, codeTitle, codeTone, severity } from "./codes";

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

/**
 * What kinds of problem this run has, and what each is worth.
 *
 * The queue is sorted worst-first and every row of it is a sentence, which
 * is right for working through and wrong for arriving at. Nine rows reading
 * "The gateway reported ... No bank credit matches it." tell somebody that
 * nine things are wrong; they do not say that eight of them are the same
 * thing and are worth eighty thousand rupees between them.
 *
 * So the kinds come first, with a count and a total each, and picking one
 * filters the list under it. That is the shape of the question a person
 * actually arrives with - "what is wrong with my books" - and the individual
 * cases are what they move to once they have chosen which problem to have.
 *
 * The totals are absolute values summed within a kind and are never summed
 * across kinds. Money the bank never received and money that arrived short
 * are two different populations, and a single headline over both would be
 * the same mistake this project already fixed once upstairs.
 */
function kindsIn(
  items: QueueItem[],
): { code: ExceptionCode; count: number; total: number }[] {
  const seen = new Map<
    ExceptionCode,
    { code: ExceptionCode; count: number; total: number }
  >();
  for (const item of items) {
    const found = seen.get(item.code) ?? {
      code: item.code,
      count: 0,
      total: 0,
    };
    found.count += 1;
    found.total += Math.abs(item.amount);
    seen.set(item.code, found);
  }
  return [...seen.values()].sort(
    (a, b) => severity(a.code) - severity(b.code) || b.total - a.total,
  );
}

/** The chip's word takes the code's own severity colour, not the badge's wash. */
const CHIP_INK: Record<string, string> = {
  bad: "var(--bad)",
  warn: "var(--warn)",
  neutral: "var(--text-muted)",
  good: "var(--good)",
  accent: "var(--accent-strong)",
};

function KindChip({
  label,
  count,
  total,
  tone,
  active,
  title,
  onClick,
}: {
  label: string;
  count: number;
  total: number | null;
  tone: string;
  active: boolean;
  title: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-pressed={active}
      className="flex items-baseline gap-2 rounded-[var(--r-chip)] border px-2.5 py-1.5 text-left transition-colors"
      style={{
        borderColor: active ? "var(--accent)" : "var(--border)",
        background: active ? "var(--accent-wash)" : "transparent",
      }}
    >
      <span className="text-[12px] font-medium" style={{ color: tone }}>
        {label}
      </span>
      <span className="tnum text-[12px] font-semibold">{count}</span>
      {total !== null && (
        <span className="tnum text-[11.5px] text-[var(--text-subtle)]">
          {inr(total)}
        </span>
      )}
    </button>
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
  const [only, setOnly] = useState<ExceptionCode | null>(null);
  const kinds = kindsIn(items);
  const ordered = sortQueue(items).filter(
    ({ item }) => only === null || item.code === only,
  );

  if (items.length === 0) return <Empty>Nothing unresolved in this run.</Empty>;

  return (
    <>
      {kinds.length > 1 && (
        <div className="flex flex-wrap items-center gap-1.5 border-b border-[var(--border)] px-4 py-2.5">
          <KindChip
            label="Everything"
            count={items.length}
            total={null}
            tone="var(--text-muted)"
            active={only === null}
            title="Every unresolved case in this run"
            onClick={() => setOnly(null)}
          />
          {kinds.map((kind) => (
            <KindChip
              key={kind.code}
              label={codeLabel(kind.code)}
              count={kind.count}
              total={kind.total}
              tone={CHIP_INK[codeTone(kind.code)]}
              active={only === kind.code}
              title={codeTitle(kind.code)}
              onClick={() => setOnly(only === kind.code ? null : kind.code)}
            />
          ))}
        </div>
      )}
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
            const active =
              selected?.kind === "exception" && selected.index === index;
            return (
              <tr
                key={`${item.subject.id}-${index}`}
                {...rowProps(active, () =>
                  onSelect({ kind: "exception", index }),
                )}
              >
                <td className="td align-top">
                  <Badge tone={codeTone(item.code)}>
                    {codeLabel(item.code)}
                  </Badge>
                </td>
                <td className="td">
                  <div className="text-[13px] leading-snug text-[var(--text)]">{withRupeeSign(item.summary)}</div>
                  <div className="mt-1.5 flex items-center gap-2">
                    <Id id={item.subject.id} />
                    <span className="tnum text-[11px] text-[var(--text-subtle)]">
                      {item.subject.occurred_on
                        ? shortDate(item.subject.occurred_on)
                        : "no date"}
                    </span>
                  </div>
                </td>
                <td className="td align-top text-right whitespace-nowrap">
                  {item.amount === 0 ? (
                    <span className="text-[12px] text-[var(--text-disabled)]">
                      —
                    </span>
                  ) : (
                    <Amount paise={item.amount} size="md" />
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </>
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
