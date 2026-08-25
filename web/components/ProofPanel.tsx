"use client";

/**
 * The screen this whole project exists to produce.
 *
 * A match says "this credit is that settlement", which is a claim. This is the
 * evidence: the sale, then every deduction that happened to it, then the total
 * those lines build - and that total is the amount the bank actually paid, to
 * the paisa. The last row is the one that matters. If it is not zero, this is
 * not a proof and the credit belongs in the queue instead.
 *
 * Every line carries the source record ids behind it. A line with no refs is
 * an assertion; a line with refs is something a finance team can go and check
 * against their own export, which is the difference between a tool they trust
 * and a tool they audit by hand anyway.
 */

import type { Proof } from "@/lib/api";
import { inr, percent, rupees, shortDate, signed } from "@/lib/money";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="label mb-0.5">{label}</div>
      <div className="truncate">{children}</div>
    </div>
  );
}

export function ProofPanel({ proof }: { proof: Proof }) {
  const balanced = proof.residual === 0;

  return (
    <div className="flex h-full flex-col">
      <header className="rule-b shrink-0 px-4 py-3">
        <div className="flex items-baseline justify-between gap-4">
          <div className="min-w-0">
            <div className="label">Bank credit</div>
            <div className="ident truncate text-[12.5px]">{proof.credit_id}</div>
          </div>
          <div className="figure shrink-0 text-[17px] font-medium">
            {inr(proof.credit_amount)}
          </div>
        </div>

        <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2.5 sm:grid-cols-4">
          <Field label="Value date">
            <span className="figure text-[12px]">{shortDate(proof.value_date)}</span>
          </Field>
          <Field label="Matched by">
            <span className="text-[12px]">{proof.strategy.replace(/_/g, " ")}</span>
          </Field>
          <Field label="Confidence">
            <span className="figure text-[12px]">{percent(proof.confidence, 0)}</span>
          </Field>
          <Field label={proof.settlement_ids.length > 1 ? "Settlements" : "Settlement"}>
            <span className="ident text-[11px]">
              {proof.settlement_ids.length > 1
                ? `${proof.settlement_ids.length} merged`
                : proof.settlement_ids[0]}
            </span>
          </Field>
        </div>

        <div className="mt-3">
          <div className="label mb-0.5">Narration, as the bank sent it</div>
          <div className="ident break-all text-[11px]">{proof.narration}</div>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full border-collapse">
          <thead className="rule-b sticky top-0 bg-[var(--surface)]">
            <tr>
              <th className="label px-4 py-1.5 text-left font-semibold">Line</th>
              <th className="label px-3 py-1.5 text-right font-semibold">Amount</th>
              <th className="label px-4 py-1.5 text-right font-semibold">Running</th>
            </tr>
          </thead>
          <tbody>
            {proof.lines.map((line, index) => {
              const { sign, body } = signed(line.amount);
              const deduction = line.amount < 0;
              return (
                <tr key={`${line.label}-${index}`} className="rule-b align-top">
                  <td className="px-4 py-1.5">
                    <div className="text-[12.5px]">{line.label}</div>
                    {line.refs.length > 0 && (
                      <div className="ident mt-0.5 text-[10.5px] leading-relaxed">
                        {line.refs.slice(0, 6).join("  ")}
                        {line.refs.length > 6 && `  +${line.refs.length - 6} more`}
                      </div>
                    )}
                  </td>
                  <td
                    className="figure px-3 py-1.5 text-right text-[12.5px] whitespace-nowrap"
                    style={{ color: deduction ? "var(--ink-soft)" : undefined }}
                  >
                    {sign}
                    {body}
                  </td>
                  <td className="figure px-4 py-1.5 text-right text-[12.5px] whitespace-nowrap text-[var(--ink-faint)]">
                    {rupees(proof.running[index] ?? 0)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/*
        The claim, stated so it can be checked rather than believed. Green is
        the only place colour is spent on this panel, and it is spent on the
        one row a reader should look at first.
      */}
      <footer className="rule-t shrink-0 px-4 py-2.5">
        <div className="flex items-baseline justify-between gap-4">
          <span className="text-[12.5px] text-[var(--ink-soft)]">
            Reconstructed from {proof.lines.length} lines
          </span>
          <span className="figure text-[13px]">
            {rupees(proof.running[proof.running.length - 1] ?? 0)}
          </span>
        </div>
        <div className="mt-1 flex items-baseline justify-between gap-4">
          <span
            className="text-[12.5px] font-medium"
            style={{ color: balanced ? "var(--good)" : "var(--bad)" }}
          >
            {balanced ? "Unexplained" : "Unexplained — this is not a proof"}
          </span>
          <span
            className="figure text-[13px] font-medium"
            style={{ color: balanced ? "var(--good)" : "var(--bad)" }}
          >
            {rupees(proof.residual)}
          </span>
        </div>
        {proof.drift !== 0 && (
          <div className="mt-1.5 text-[11.5px] text-[var(--ink-faint)]">
            Includes {inr(proof.drift)} of rounding drift — per-transaction fees rounding
            against a batch-level GST figure. Inside the allowance these rows carry, and
            named rather than quietly absorbed.
          </div>
        )}
      </footer>
    </div>
  );
}
