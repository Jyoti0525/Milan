"use client";

/**
 * Who this merchant is, worked out from their own settlement rows.
 *
 * Three things change what a payout is allowed to look like — 1% withheld
 * under Section 194-O, sales split onward through Route, payouts taken the
 * same day — and none of them is anything a merchant would think to mention.
 * They are on this screen because a finance team reading a payout smaller
 * than their sales is owed the reason, and each of these is a reason.
 *
 * Nothing here was configured. The engine read every settlement row and
 * reported what the arithmetic and the type column said, which is why every
 * finding carries the population it was counted over: `278 of 278` is
 * evidence and `278` is a number.
 *
 * Absent by design when there is nothing to say. An ordinary merchant — no
 * withholding, no linked accounts, no same-day payouts — gets no strip at
 * all, because three lines saying *no* is how a reader learns to stop looking
 * at a panel.
 */

import type { Finding } from "@/lib/api";

/**
 * A finding whose rows disagreed with each other, marked as a question.
 *
 * The one case worth a different colour. Some payments short by exactly the
 * statutory percent and the rest not is the shape of *both* an operator with
 * anomalies and an ordinary merchant being overcharged a percent — and those
 * two want opposite responses, so it is put to a person rather than decided.
 */
function Mark({ held }: { held: boolean | null }) {
  const open = held === null;
  return (
    <span
      aria-hidden
      className={`mt-[6px] size-1.5 shrink-0 rounded-full ${
        open ? "bg-[var(--warn)]" : "bg-[var(--good)]"
      }`}
    />
  );
}

function Row({ finding }: { finding: Finding }) {
  const open = finding.held === null;
  return (
    <li className="flex gap-2.5">
      <Mark held={finding.held} />
      <div className="min-w-0">
        <p className="text-[13px] font-medium">
          {finding.name}
          {open && <span className="text-[var(--warn)]">?</span>}
          {/* The count and its denominator, never one without the other. */}
          {finding.of > 0 && (
            <span className="ml-2 font-normal tabular-nums text-[var(--text-subtle)]">
              {finding.rows} of {finding.of}
            </span>
          )}
        </p>
        <p className="mt-0.5 text-[12px] leading-relaxed text-[var(--text-subtle)]">
          {finding.because}
        </p>
      </div>
    </li>
  );
}

export function Merchant({ findings }: { findings: Finding[] }) {
  if (findings.length === 0) return null;

  const asked = findings.some((finding) => finding.held === null);
  return (
    <section className="card px-4 py-3">
      <h2 className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-subtle)]">
        Who this merchant is
        {/*
          Said once, here. It is the whole claim of this strip: nobody set a
          flag, nobody answered a form, and the same files that get reconciled
          are the ones that named the merchant.
        */}
        <span className="ml-2 font-normal normal-case tracking-normal">
          read from their own rows
        </span>
      </h2>
      <ul className="mt-2.5 space-y-2">
        {findings.map((finding) => (
          <Row key={finding.name} finding={finding} />
        ))}
      </ul>
      {asked && (
        <p className="mt-2.5 border-t border-[var(--border)] pt-2.5 text-[12px] leading-relaxed text-[var(--text-subtle)]">
          A finding marked with a question was not settled by the rows. The
          reconciliation ran on the safer reading of it, and the number beside
          it is the evidence either way.
        </p>
      )}
    </section>
  );
}
