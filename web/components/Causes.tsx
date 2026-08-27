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
 * Every card here states the test its members passed, and states it with
 * numbers, so a reader who thinks a cause is wrong has something to
 * disprove. That is the whole difference between this and a summary: a
 * summary asks to be believed.
 *
 * Nothing here was written by a model. Grouping produced by a model is
 * grouping nobody can check, and an unfalsifiable heading over a list of
 * real money is worse than the list on its own.
 */

import type { CausesView, CauseView } from "@/lib/api";
import { Amount } from "@/components/Amount";

/**
 * The cause that needs no action, marked differently from the ones that do.
 *
 * Usually the most valuable card on the screen. "These nine are refunds
 * clearing into a later payout and the money is accounted for" is an
 * afternoon somebody gets back, and it should not look like the four cards
 * that are asking them to pick up the phone.
 */
function Verdict({ ask }: { ask: string }) {
  if (!ask) {
    return (
      <p className="mt-1.5 text-[12px] font-medium leading-relaxed text-[var(--good)]">
        Nothing to chase — this is already explained.
      </p>
    );
  }
  return (
    <p className="mt-1.5 text-[12px] leading-relaxed">
      <span className="font-medium">Do this: </span>
      <span className="text-[var(--text-subtle)]">{ask}</span>
    </p>
  );
}

function Card({
  cause,
  active,
  onPick,
}: {
  cause: CauseView;
  active: boolean;
  onPick: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onPick}
        aria-pressed={active}
        className={`w-full rounded-md border px-3 py-2.5 text-left transition-colors ${
          active
            ? "border-[var(--accent)] bg-[var(--accent-wash)]"
            : "border-[var(--border)] hover:bg-[var(--surface-hover)]"
        }`}
      >
        <div className="flex items-baseline justify-between gap-3">
          <span className="text-[13px] font-semibold leading-snug">{cause.name}</span>
          <span className="shrink-0 text-[12px] font-medium tabular-nums">
            <Amount paise={cause.total} />
          </span>
        </div>
        {/* The count is the point of the card, so it is not buried in prose. */}
        <p className="mt-1 text-[11px] font-medium uppercase tracking-wider text-[var(--text-subtle)]">
          {cause.members.length} of the rows below
        </p>
        <p className="mt-1.5 text-[12px] leading-relaxed text-[var(--text-subtle)]">
          {cause.because}
        </p>
        <Verdict ask={cause.ask} />
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
    <div className="border-b border-[var(--border)] px-4 py-3">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-subtle)]">
          Why
        </h2>
        {/*
          The coverage, said plainly and including the part that did not fit.
          A screen that showed only the causes would imply the queue was
          entirely explained by them, and the rows that stayed individual are
          exactly the ones nobody should be steered away from.
        */}
        <p className="text-[11px] tabular-nums text-[var(--text-subtle)]">{causes.reading}</p>
      </div>
      <ul className="mt-2.5 grid gap-2 md:grid-cols-2">
        {causes.causes.map((cause) => (
          <Card
            key={cause.name}
            cause={cause}
            active={active === cause.name}
            onPick={() => onPick(active === cause.name ? null : cause.name)}
          />
        ))}
      </ul>
      {active !== null && (
        <button
          type="button"
          onClick={() => onPick(null)}
          className="mt-2 text-[12px] text-[var(--text-subtle)] underline underline-offset-2 hover:text-[var(--text)]"
        >
          Show the whole queue again
        </button>
      )}
    </div>
  );
}
