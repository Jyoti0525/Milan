"use client";

/**
 * The few reasons behind the queue.
 *
 * The chips under this filter by *code* — what kind of problem each row is.
 * This filters by *cause* — why it happened — and they are not the same
 * question. Six rows can all be `FEE_DEDUCTION` and be six separate
 * arguments with an account manager, or they can be one deduction taken six
 * times, which is one argument. Only the second is worth somebody's morning.
 *
 * Laid out as a ranked list rather than a grid of cards, and that was a
 * correction. Eight cards of prose in a column this narrow reduced every
 * cause to four cramped words and a wall of grey text, so the thing meant to
 * make the queue legible was the least legible thing on the screen. A list
 * gives each cause one scannable line — how many, how much, what it is — and
 * opens the reasoning only for the one being looked at.
 *
 * Every cause states the arithmetic test its members passed, with numbers in
 * it, so a reader who thinks a cause is wrong has something to disprove.
 * That is the difference between this and a summary: a summary asks to be
 * believed.
 *
 * Nothing here was written by a model. Grouping produced by a model is
 * grouping nobody can check, and an unfalsifiable heading over real money is
 * worse than the list underneath it.
 */

import type { CausesView, CauseView } from "@/lib/api";
import { Amount } from "@/components/Amount";

/**
 * The cause that needs no action, marked apart from the ones that do.
 *
 * Usually the most valuable line on the screen. "These nine are refunds
 * clearing into a later payout and the money is accounted for" is an
 * afternoon somebody gets back, and it should not read like the four that
 * are asking them to pick up the phone.
 */
function Verdict({ ask }: { ask: string }) {
  if (!ask) {
    return (
      <p className="mt-2 text-[12px] font-medium leading-relaxed text-[var(--good)]">
        Nothing to chase — this is already accounted for.
      </p>
    );
  }
  return (
    <p className="mt-2 text-[12px] leading-relaxed">
      <span className="font-medium">Do this: </span>
      <span className="text-[var(--text-subtle)]">{ask}</span>
    </p>
  );
}

function Row({
  cause,
  open,
  onPick,
}: {
  cause: CauseView;
  open: boolean;
  onPick: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onPick}
        aria-expanded={open}
        className={`w-full border-l-2 px-3 py-2 text-left transition-colors ${
          open
            ? "border-l-[var(--accent)] bg-[var(--accent-wash)]"
            : "border-l-transparent hover:bg-[var(--surface-hover)]"
        }`}
      >
        <div className="flex items-baseline gap-2.5">
          {/*
            The count, given the most visual weight on the line. It is the
            whole proposition — that these N rows are one thing — and it is
            what a reader scans the column for.
          */}
          <span className="w-7 shrink-0 text-right text-[15px] font-semibold tabular-nums">
            {cause.members.length}
          </span>
          <span className="min-w-0 flex-1 text-[13px] font-medium leading-snug">
            {cause.name}
          </span>
          <span className="shrink-0 tabular-nums">
            <Amount paise={cause.total} size="sm" />
          </span>
        </div>

        {open && (
          <div className="mt-2 pl-[38px]">
            <p className="text-[12px] leading-relaxed text-[var(--text-subtle)]">
              {cause.because}
            </p>
            <Verdict ask={cause.ask} />
            <p className="mt-2 text-[11px] text-[var(--text-subtle)]">
              Showing only these {cause.members.length} below.
            </p>
          </div>
        )}
        {!open && (
          <p className="mt-0.5 truncate pl-[38px] text-[12px] text-[var(--text-subtle)]">
            {cause.ask || "Nothing to chase — already accounted for."}
          </p>
        )}
      </button>
    </li>
  );
}

export function Causes({
  causes,
  active,
  onPick,
}: {
  causes: CausesView;
  /** The name of the cause currently filtering the list, if any. */
  active: string | null;
  onPick: (name: string | null) => void;
}) {
  if (causes.causes.length === 0) return null;

  return (
    <div className="border-b border-[var(--border)]">
      <div className="flex items-baseline justify-between gap-3 px-4 pb-1.5 pt-3">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-subtle)]">
          Why — the {causes.causes.length} reasons behind this queue
        </h2>
        {/*
          The coverage, said plainly and including the part that did not fit.
          A screen showing only the causes would imply the queue was entirely
          explained by them, and the rows that stayed individual are exactly
          the ones nobody should be steered away from.
        */}
        <p className="shrink-0 text-[11px] tabular-nums text-[var(--text-subtle)]">
          {causes.covered} of {causes.total} grouped
          {causes.uncaused.length > 0 && `, ${causes.uncaused.length} on their own`}
        </p>
      </div>

      <ul className="pb-1">
        {causes.causes.map((cause) => (
          <Row
            key={cause.name}
            cause={cause}
            open={active === cause.name}
            onPick={() => onPick(active === cause.name ? null : cause.name)}
          />
        ))}
      </ul>

      {active !== null && (
        <div className="px-4 pb-2.5">
          <button
            type="button"
            onClick={() => onPick(null)}
            className="text-[12px] text-[var(--accent)] underline underline-offset-2"
          >
            Show the whole queue again
          </button>
        </div>
      )}
    </div>
  );
}
