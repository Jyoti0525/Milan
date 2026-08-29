"use client";

/**
 * The overview's answer to "so what do I do about it".
 *
 * Every other panel on this screen reports a state. This one is the only
 * thing on the overview that asks for an action, so it is the last card and
 * the one that hands you into the queue.
 *
 * It shows the largest few causes rather than all of them, because an
 * orientation that lists everything is the list it was meant to replace. The
 * count of what is not shown is stated rather than dropped — the same rule
 * the queue keeps, for the same reason.
 */

import type { CausesView } from "@/lib/api";
import { Amount } from "@/components/Amount";

const SHOWN = 3;

export function WhatToDo({
  causes,
  exceptions,
  onOpen,
}: {
  causes: CausesView;
  /** How many cases are in the queue, whether or not any grouped. */
  exceptions: number;
  onOpen: () => void;
}) {
  if (exceptions === 0) {
    return (
      <section className="card px-5 py-4">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-subtle)]">
          What to do
        </h2>
        {/*
          A finished month is a result, not an empty state, and it should not
          read like a panel that failed to load.
        */}
        <p className="mt-2 text-[13px] leading-relaxed">
          <span className="font-medium text-[var(--good)]">Nothing.</span> Every credit
          on this run was rebuilt from its own settlement rows and closed to the paisa.
        </p>
      </section>
    );
  }

  const top = causes.causes.slice(0, SHOWN);
  const rest = causes.causes.length - top.length;

  return (
    <section className="card px-5 py-4">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-subtle)]">
          What to do
        </h2>
        <button
          type="button"
          onClick={onOpen}
          className="shrink-0 text-[12px] text-[var(--accent)] underline underline-offset-2"
        >
          Open the queue →
        </button>
      </div>

      {top.length === 0 ? (
        <p className="mt-2 text-[13px] leading-relaxed text-[var(--text-subtle)]">
          {exceptions} cases could not be resolved, and no two of them are the same
          thing. Each one has to be read on its own.
        </p>
      ) : (
        <>
          <p className="mt-1.5 text-[13px] leading-relaxed text-[var(--text-subtle)]">
            {causes.covered} of {causes.total} unresolved cases come down to{" "}
            {causes.causes.length} {causes.causes.length === 1 ? "reason" : "reasons"}.
            The largest {top.length === 1 ? "one" : top.length}:
          </p>
          <ol className="mt-3 space-y-3">
            {top.map((cause) => (
              <li key={cause.name} className="flex gap-3">
                {/*
                  The count first and heaviest. It is the whole proposition —
                  that these N cases are one job — and it is what turns a
                  queue of thirty into an afternoon of four.
                */}
                <span className="w-7 shrink-0 text-right text-[15px] font-semibold tabular-nums">
                  {cause.members.length}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="min-w-0 text-[13px] font-medium leading-snug">
                      {cause.name}
                    </span>
                    <span className="shrink-0 tabular-nums">
                      <Amount paise={cause.total} size="sm" />
                    </span>
                  </div>
                  <p className="mt-0.5 text-[12px] leading-relaxed text-[var(--text-subtle)]">
                    {cause.ask || "Nothing to chase — already accounted for."}
                  </p>
                </div>
              </li>
            ))}
          </ol>
          {(rest > 0 || causes.uncaused.length > 0) && (
            <p className="mt-3 border-t border-[var(--border)] pt-2.5 text-[12px] text-[var(--text-subtle)]">
              {rest > 0 && `${rest} more ${rest === 1 ? "reason" : "reasons"}`}
              {rest > 0 && causes.uncaused.length > 0 && ", and "}
              {causes.uncaused.length > 0 &&
                `${causes.uncaused.length} ${
                  causes.uncaused.length === 1 ? "case that is" : "cases that are"
                } each their own`}
              .
            </p>
          )}
        </>
      )}
    </section>
  );
}
