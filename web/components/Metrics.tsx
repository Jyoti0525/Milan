"use client";

/**
 * The four figures that describe a run.
 *
 * Four, not seven. A dashboard that spends the top third of the screen on
 * numbers is a dashboard where the actual work starts below the fold, and the
 * work here is the queue.
 *
 * Refusals get a card of their own, next to the match rate. A system that
 * forces an answer onto every credit shows a perfect match rate and corrupts
 * the books, so the number that says how often it declined belongs beside the
 * number that says how often it answered — not three columns further right.
 *
 * The hint under each figure is four or five words. It was a clause before,
 * and four cards of clauses is a paragraph laid out in a grid: everything a
 * figure needs to be trustworthy, in the place where nobody reads it. What
 * those clauses said now lives in `Explain` underneath, closed.
 */

import type { ImportSummary, RunSummary } from "@/lib/api";
import { percent } from "@/lib/money";
import { Amount, Figure } from "./Amount";
import { Explain } from "./Explain";

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
    <div className="card px-4 py-3">
      <div className="text-[11.5px] font-medium tracking-wide text-[var(--text-subtle)] uppercase">
        {label}
      </div>
      <div className="mt-1.5">{children}</div>
      <div className="mt-0.5 truncate text-[11.5px] text-[var(--text-muted)]">{hint}</div>
    </div>
  );
}

export function Metrics({ summary }: { summary: RunSummary }) {
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        {/*
          The denominator, on screen. `100.0%` over a run of thirty-seven
          credits reads as thirty-seven resolved, and on the adversarial tier
          it means twenty-one - the rest impossible by construction and
          correctly refused. The flattering misreading is the one a rate
          without its population invites.
        */}
        <Card
          label="Match rate"
          hint={`of ${summary.resolvable_credits} that could be resolved`}
        >
          <Figure value={percent(summary.match_rate)} tone="var(--good)" />
        </Card>

        <Card label="Precision" hint="of what it claimed">
          <Figure value={percent(summary.precision)} />
        </Card>

        {/*
          A rate with nothing underneath it is not a measurement. On the clean
          tier no credit is impossible, so this rendered `0.0%` under the word
          "Refused" - which reads as a system that guessed at every hard case,
          and is the exact opposite of what the run showed.
        */}
        <Card
          label="Refused"
          hint={
            summary.refusals_expected === 0
              ? "nothing impossible here"
              : `of ${summary.refusals_expected} impossible`
          }
        >
          {summary.refusals_expected === 0 ? (
            <Figure value="—" tone="var(--text-disabled)" />
          ) : (
            <Figure value={percent(summary.refusal_rate)} />
          )}
        </Card>

        <Card label="Rounding drift" hint={`across ${summary.proofs_with_drift} proofs`}>
          <Amount paise={summary.drift_gross} size="lg" />
        </Card>
      </div>

      <Explain question="What are these measured against?">
        <p>
          This run was generated from a seed, and the answer key was generated with it. Every
          figure above is checked against that key rather than estimated — <b>match rate</b> is
          the share of credits resolved, <b>precision</b> the share of those claims that were
          correct, and <b>refused</b> the share of the credits that were impossible by
          construction which the engine correctly declined to answer.
        </p>
        <p>
          That last one is the point of the row. A system that forces an answer onto every credit
          scores a perfect match rate and quietly corrupts the books.
        </p>
      </Explain>
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
 * survives because it needs no answer key at all — a credit that reconstructs
 * to zero has proved itself, and nothing external had to agree. And the last
 * card says where the schema came from, which is the one question a person
 * looking at somebody else's CSVs actually wants answered.
 *
 * The `Explain` underneath exists because of a real question, asked while
 * looking at exactly this screen: *why is there no score for my files?* It
 * reads as a downgrade and it is not one — it is the difference between a
 * measurement and an assertion, and the honest answer is short enough to fit.
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
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        {/*
          No match rate here and there cannot be one: it is measured against an
          answer key. The count of credits resolved stands in its place, which
          is a fact rather than a score.
        */}
        <Card label="Credits proved" hint={`of ${summary.credits_total} that arrived`}>
          <Figure value={String(summary.proofs_balanced)} tone="var(--good)" />
        </Card>

        <Card label="Exceptions" hint="it would not claim">
          <Figure value={String(summary.exceptions_total)} />
        </Card>

        <Card label="Rounding drift" hint={`across ${summary.proofs_with_drift} proofs`}>
          <Amount paise={summary.drift_gross} size="lg" />
        </Card>

        {/*
          Where the schema came from, in the same place the generated screen
          puts its refusal rate. Both cards answer "how much of this did you
          decide, and on what evidence".
        */}
        <Card
          label="Columns read by a model"
          hint={model ? `${consulted}, checked by values` : "read from the names alone"}
        >
          {model ? (
            <Figure value={String(columnsProposed)} />
          ) : (
            <Figure value="—" tone="var(--text-disabled)" />
          )}
        </Card>
      </div>

      <Explain question="Why is there no score on my own files?">
        <p>
          Because a score has to be measured against something, and your books do not come with an
          answer key. A <b>match rate</b> of 94% means nothing on its own — it means 94% of the
          credits whose right answer was already known. On sample data that key exists, because the
          data and the key were generated together. On your files there is no such thing, and
          there never will be.
        </p>
        <p>
          So rather than print a number nothing could make true, this screen reports what your
          files <i>can</i> prove about themselves: how many credits reconstructed to zero from
          their own settlement rows, how many the engine refused to claim, and how far the
          arithmetic drifted. None of that needs anyone else to agree.
        </p>
        <p>
          <b>How this was read</b> in the sidebar is the other half of the answer — every column,
          what it became, and who decided.
        </p>
      </Explain>
    </div>
  );
}
