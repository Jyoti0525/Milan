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

import type { RunSummary } from "@/lib/api";
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

      <Card label="Refused" hint="of the impossible, never guessed">
        <Figure value={percent(summary.refusal_rate)} />
      </Card>

      <Card
        label="Rounding drift"
        hint={`gross, across ${summary.proofs_with_drift} proofs`}
      >
        <Amount paise={summary.drift_gross} size="lg" />
      </Card>
    </div>
  );
}
