"use client";

/**
 * The four figures that describe a run, as Blade metric cards.
 *
 * There were seven of these in a 54-pixel strip before, and the hints wrapped
 * onto second lines that had nowhere to go. Seven numbers is not a summary,
 * it is the detail table moved to the top of the page — so this is four, and
 * the rest live in the detail pane where somebody who wants them is already
 * looking.
 *
 * Refusals get a card of their own, next to the match rate. A system that
 * forces an answer onto every credit shows a perfect match rate and corrupts
 * the books, so the number that says how often it declined belongs beside the
 * number that says how often it answered — not three columns further right.
 */

import type { ImportSummary, RunSummary } from "@/lib/api";
import { percent } from "@/lib/money";
import { Amount, Figure } from "./Amount";

function Card({
  label,
  hint,
  children,
}: {
  label: string;
  hint: string;
  children: React.ReactNode;
}) {
  return (
    <div className="card min-w-0 px-4 py-3">
      <div className="text-[12px] font-medium text-[var(--text-muted)]">{label}</div>
      <div className="mt-1.5">{children}</div>
      <div className="mt-1 truncate text-[11.5px] text-[var(--text-subtle)]">{hint}</div>
    </div>
  );
}

export function Metrics({ summary }: { summary: RunSummary }) {
  return (
    <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
      <Card
        label="Proved to the paisa"
        hint={`${summary.records_processed.toLocaleString("en-IN")} records reconciled`}
      >
        <Figure value={`${summary.proofs_balanced}/${summary.credits_total}`} tone="var(--good)" />
      </Card>

      <Card label="Precision" hint="of the settlements claimed, correct">
        <Figure value={percent(summary.precision)} />
      </Card>

      {/*
        A rate with nothing underneath it is not a measurement. On the clean
        tier no credit is impossible, so this was rendering `0.0%` under the
        word "Refused" - which reads as a system that guessed at every hard
        case, and is the exact opposite of what the run showed.
      */}
      <Card
        label="Refused"
        hint={
          summary.refusals_expected === 0
            ? "nothing impossible in this run"
            : `of ${summary.refusals_expected} impossible, never guessed`
        }
      >
        {summary.refusals_expected === 0 ? (
          <Figure value="—" tone="var(--text-disabled)" />
        ) : (
          <Figure value={percent(summary.refusal_rate)} />
        )}
      </Card>

      <Card label="Rounding drift" hint={`gross, across ${summary.proofs_with_drift} proofs`}>
        <Amount paise={summary.drift_gross} size="lg" />
      </Card>
    </div>
  );
}

/**
 * The four figures an imported run can honestly report.
 *
 * Three of the generated screen's cards are missing and one is new, and the
 * swap is the whole point. Precision and refusal rate are measured against an
 * answer key; a merchant's own files come with none, so a card in their place
 * would be a number nothing on disk could make true.
 *
 * What replaces them is what the run *can* say about itself. Rounding drift
 * survives because it needs no answer key at all - a credit that reconstructs
 * to zero has proved itself, and nothing external had to agree. And the last
 * card says where the schema came from, which is the one question a person
 * looking at somebody else's CSVs actually wants answered.
 */
export function ImportMetrics({
  summary,
  consulted,
  columnsProposed,
}: {
  summary: ImportSummary;
  consulted: string;
  columnsProposed: number;
}) {
  const model = consulted !== "none";
  return (
    <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
      <Card
        label="Proved to the paisa"
        hint={`${summary.records_processed.toLocaleString("en-IN")} records reconciled`}
      >
        <Figure value={`${summary.proofs_balanced}/${summary.credits_total}`} tone="var(--good)" />
      </Card>

      <Card label="Exceptions raised" hint="credits the engine would not claim">
        <Figure value={String(summary.exceptions_total)} />
      </Card>

      <Card label="Rounding drift" hint={`gross, across ${summary.proofs_with_drift} proofs`}>
        <Amount paise={summary.drift_gross} size="lg" />
      </Card>

      {/*
        Where the schema came from, in the same place the generated screen puts
        its refusal rate. Both cards answer "how much of this did you decide,
        and on what evidence" - the generated one against an answer key, this
        one against the merchant's own column names.
      */}
      <Card
        label="Columns read by a model"
        hint={
          model
            ? `proposed by ${consulted}, checked against the values`
            : "read from the column names alone"
        }
      >
        {model ? (
          <Figure value={String(columnsProposed)} />
        ) : (
          <Figure value="—" tone="var(--text-disabled)" />
        )}
      </Card>
    </div>
  );
}
