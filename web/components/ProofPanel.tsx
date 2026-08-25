"use client";

/**
 * The screen this whole project exists to produce.
 *
 * A match says "this credit is that settlement", which is a claim. This is the
 * evidence: the sale, then every deduction that happened to it, then the total
 * those lines build — and that total is the amount the bank actually paid, to
 * the paisa. The footer is the row that matters. If `Unexplained` is not zero
 * this is not a proof, and the credit belongs in the queue instead.
 *
 * Every line carries the source record ids behind it. A line with no refs is
 * an assertion; a line with refs is something a finance team can check against
 * their own export, which is the difference between a tool they trust and a
 * tool they audit by hand anyway.
 */

import type { Proof } from "@/lib/api";
import { percent, shortDate } from "@/lib/money";
import { Amount } from "./Amount";
import { Badge } from "./Badge";

function Meta({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-[11px] font-medium text-[var(--text-subtle)]">{label}</div>
      <div className="mt-0.5 truncate text-[13px]">{children}</div>
    </div>
  );
}

export function ProofPanel({ proof }: { proof: Proof }) {
  const balanced = proof.residual === 0;

  return (
    <div className="flex h-full flex-col">
      <header className="shrink-0 border-b border-[var(--border)] px-5 py-4">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <Badge tone="good">Proved</Badge>
              {proof.settlement_ids.length > 1 && (
                <Badge tone="accent">{proof.settlement_ids.length} settlements merged</Badge>
              )}
            </div>
            <div className="mt-2 text-[12px] text-[var(--text-muted)]">Bank credit</div>
            <div className="chip mt-1 font-mono">{proof.credit_id}</div>
          </div>
          <Amount paise={proof.credit_amount} size="xl" />
        </div>

        <div className="mt-4 grid grid-cols-3 gap-4">
          <Meta label="Value date">
            <span className="tnum">{shortDate(proof.value_date)}</span>
          </Meta>
          <Meta label="Resolved by">{proof.strategy.replace(/_/g, " ")}</Meta>
          <Meta label="Confidence">
            <span className="tnum">{percent(proof.confidence, 0)}</span>
          </Meta>
        </div>

        <div className="mt-3">
          <div className="text-[11px] font-medium text-[var(--text-subtle)]">
            Narration, as the bank sent it
          </div>
          <div className="mt-1 font-mono text-[11.5px] break-all text-[var(--text-muted)]">
            {proof.narration}
          </div>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full border-collapse">
          <thead className="sticky top-0 z-10">
            <tr>
              <th className="th">Line</th>
              <th className="th w-[132px] text-right">Amount</th>
              <th className="th w-[132px] text-right">Running</th>
            </tr>
          </thead>
          <tbody>
            {proof.lines.map((line, index) => (
              <tr key={`${line.label}-${index}`} className="align-top">
                <td className="td">
                  <div className="text-[13px]">{line.label}</div>
                  {line.refs.length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {line.refs.slice(0, 5).map((ref) => (
                        <span key={ref} className="chip font-mono text-[10.5px]">
                          {ref.replace(/^(pay|rfnd|adj)_/, "")}
                        </span>
                      ))}
                      {line.refs.length > 5 && (
                        <span className="self-center text-[11px] text-[var(--text-subtle)]">
                          +{line.refs.length - 5} more
                        </span>
                      )}
                    </div>
                  )}
                </td>
                <td className="td text-right">
                  <Amount
                    paise={line.amount}
                    size="md"
                    showSign
                    tone={line.amount < 0 ? "var(--text-muted)" : undefined}
                  />
                </td>
                <td className="td tnum text-right text-[12px] text-[var(--text-subtle)]">
                  <Amount paise={proof.running[index] ?? 0} size="sm" tone="var(--text-subtle)" />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/*
        The claim, stated so it can be checked rather than believed. This is
        the only place colour is spent on this panel, and it is spent on the
        one row a reader should look at first.
      */}
      <footer className="shrink-0 border-t border-[var(--border)] bg-[var(--surface-sunken)] px-5 py-3">
        <div className="flex items-baseline justify-between gap-4">
          <span className="text-[12.5px] text-[var(--text-muted)]">
            Reconstructed from {proof.lines.length} lines
          </span>
          <Amount paise={proof.running[proof.running.length - 1] ?? 0} size="md" />
        </div>
        <div className="mt-2 flex items-baseline justify-between gap-4">
          <span
            className="text-[13px] font-semibold"
            style={{ color: balanced ? "var(--good)" : "var(--bad)" }}
          >
            {balanced ? "Unexplained" : "Unexplained — this is not a proof"}
          </span>
          <Amount
            paise={proof.residual}
            size="lg"
            tone={balanced ? "var(--good)" : "var(--bad)"}
          />
        </div>
        {proof.drift !== 0 && (
          <p className="mt-2 text-[11.5px] leading-relaxed text-[var(--text-subtle)]">
            Includes <Amount paise={proof.drift} size="sm" tone="var(--text-subtle)" /> of
            rounding drift — per-transaction fees rounding against a batch-level GST figure.
            Inside the allowance these rows carry, and named rather than quietly absorbed.
          </p>
        )}
      </footer>
    </div>
  );
}
