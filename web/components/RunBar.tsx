"use client";

/**
 * The run, and the four figures that describe it.
 *
 * Deliberately one line. A dashboard that spends the top third of the screen
 * on four numbers in four cards is a dashboard where the actual work starts
 * below the fold - and the work here is the queue.
 *
 * Refusals get equal billing with the match rate on purpose. A system that
 * forces an answer onto every credit shows a perfect match rate and corrupts
 * the books, so the number that says how often it declined belongs beside the
 * number that says how often it answered.
 */

import type { RunRef, RunSummary } from "@/lib/api";
import { percent, rupees } from "@/lib/money";

function Figure({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: string;
}) {
  return (
    <div className="flex shrink-0 flex-col justify-center px-3.5 whitespace-nowrap">
      <span className="label">{label}</span>
      <span className="figure text-[14px] leading-tight" style={{ color: tone }}>
        {value}
        {hint && (
          <span className="ml-1.5 text-[11px] font-normal text-[var(--ink-faint)]">
            {hint}
          </span>
        )}
      </span>
    </div>
  );
}

export function RunBar({
  runs,
  current,
  summary,
  onPick,
}: {
  runs: RunRef[];
  current: RunRef | null;
  summary: RunSummary | null;
  onPick: (run: RunRef) => void;
}) {
  return (
    <header className="rule-b flex h-[54px] shrink-0 items-stretch bg-[var(--surface)]">
      <div className="rule-r flex items-center gap-2.5 px-4">
        <span className="text-[14px] font-semibold tracking-tight">Milan</span>
        <span className="hidden text-[11.5px] text-[var(--ink-faint)] lg:inline">
          settlement reconciliation
        </span>
      </div>

      <div className="rule-r flex items-center px-3">
        <label className="label mr-2" htmlFor="run">
          Run
        </label>
        <select
          id="run"
          className="figure rounded-[3px] border border-[var(--rule-strong)] bg-[var(--paper)] px-2 py-1 text-[12px]"
          value={current ? `${current.difficulty}:${current.seed}` : ""}
          onChange={(event) => {
            const [difficulty, seed] = event.target.value.split(":");
            const picked = runs.find(
              (run) => run.difficulty === difficulty && run.seed === Number(seed),
            );
            if (picked) onPick(picked);
          }}
        >
          {runs.length === 0 && <option value="">no runs generated</option>}
          {runs.map((run) => (
            <option key={`${run.difficulty}:${run.seed}`} value={`${run.difficulty}:${run.seed}`}>
              {run.difficulty} · seed {run.seed} · {run.orders} orders
              {run.stale ? " · stale" : ""}
            </option>
          ))}
        </select>
      </div>

      {summary && (
        <div className="flex flex-1 items-stretch overflow-x-auto">
          <Figure
            label="Records"
            value={summary.records_processed.toLocaleString("en-IN")}
            hint={`${summary.duration_seconds < 0.01 ? "<10" : Math.round(summary.duration_seconds * 1000)}ms`}
          />
          <Figure
            label="Proved"
            value={`${summary.proofs_balanced}/${summary.credits_total}`}
            hint="exact"
            tone="var(--good)"
          />
          <Figure
            label="Precision"
            value={percent(summary.precision)}
            hint="of claims"
          />
          <Figure
            label="Refused"
            value={percent(summary.refusal_rate)}
            hint="of impossible"
          />
          <Figure label="Queue" value={String(summary.exceptions_total)} hint="unresolved" />
          <Figure
            label="Drift"
            value={rupees(summary.drift_gross)}
            hint="gross"
          />
          <Figure
            label="Sorted by rules"
            value={percent(summary.rules_share, 0)}
            hint="no model"
          />
        </div>
      )}
    </header>
  );
}
