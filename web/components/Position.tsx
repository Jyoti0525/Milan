"use client";

/**
 * Where the merchant's money stands, before any of our vocabulary.
 *
 * For six days the first figure on this screen was `21/37`. That is how a
 * reconciliation engine thinks about a month. It is not how the person paying
 * for one thinks about it: they want to know how much arrived, how much of it
 * is explained, and how much is still theirs to chase — in rupees, at the top,
 * before the word "exception" appears anywhere.
 *
 * The bar is doing real work rather than decorating. A proportion is the one
 * thing a person reads without reading, and "most of it is fine, this sliver
 * is not" is the entire summary of a good month.
 *
 * **Two populations, and they are never added.** What arrived is money in the
 * account. What was reported and never arrived is money that is not, and a
 * screen that summed them would show a total the merchant does not have — so
 * it sits below a rule, in its own sentence, with the word "separately".
 */

import type { Paise } from "@/lib/money";
import { Amount } from "./Amount";

function Dot({ tone }: { tone: string }) {
  return (
    <span
      aria-hidden
      className="mt-[5px] h-[7px] w-[7px] shrink-0 rounded-full"
      style={{ background: tone }}
    />
  );
}

function Leg({
  tone,
  label,
  paise,
  hint,
}: {
  tone: string;
  label: string;
  paise: Paise;
  hint: string;
}) {
  return (
    <div className="flex min-w-0 gap-2">
      <Dot tone={tone} />
      <div className="min-w-0">
        <Amount paise={paise} size="md" />
        <div className="text-[12px] font-medium">{label}</div>
        <div className="text-[11.5px] leading-snug text-[var(--text-subtle)]">{hint}</div>
      </div>
    </div>
  );
}

export function Position({
  credited,
  proved,
  awaited,
  records,
  seconds,
}: {
  credited: Paise;
  proved: Paise;
  awaited: Paise;
  records: number;
  seconds: number;
}) {
  const unexplained = Math.max(0, credited - proved);
  /*
    Guarded, and the guard is not paranoia. A folder whose bank statement has
    no credit lines in it reconciles to a credited total of zero, and the
    division would put `NaN%` in the one place on this screen a person is
    meant to read at a glance.
  */
  const provedShare = credited > 0 ? (proved / credited) * 100 : 0;

  return (
    <section className="card px-5 py-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <div>
          <div className="text-[12px] font-medium text-[var(--text-muted)]">
            Money that reached your account
          </div>
          <div className="mt-0.5">
            <Amount paise={credited} size="xl" />
          </div>
        </div>
        <div className="text-[11.5px] text-[var(--text-subtle)]">
          {records.toLocaleString("en-IN")} records read in {seconds.toFixed(3)}s
        </div>
      </div>

      <div className="meter mt-3" role="img" aria-label={`${provedShare.toFixed(1)}% proved`}>
        <span style={{ width: `${provedShare}%`, background: "var(--good)" }} />
        <span style={{ width: `${100 - provedShare}%`, background: "var(--warn)" }} />
      </div>

      <div className="mt-3 grid gap-4 sm:grid-cols-2">
        <Leg
          tone="var(--good)"
          label="Proved to the paisa"
          paise={proved}
          hint="rebuilt from its settlement rows, fee and GST included"
        />
        <Leg
          tone="var(--warn)"
          label="Still to explain"
          paise={unexplained}
          hint="arrived, and the engine would not claim to know why"
        />
      </div>

      {/*
        Below a rule and worded as a separate statement, because it is money
        in a different place. Everything above is in the account; this is not.
      */}
      <div className="mt-3.5 border-t border-[var(--border)] pt-3 text-[12.5px] text-[var(--text-muted)]">
        Separately, <Amount paise={awaited} size="sm" /> was reported as paid out and never reached
        the bank, or was captured and never settled.{" "}
        <span className="text-[var(--text-subtle)]">Not part of the total above.</span>
      </div>
    </section>
  );
}
