"use client";

/**
 * The honest half of the result.
 *
 * An exception here is not an error log entry. It is a case, and the panel is
 * built so that somebody can pick it up: what the amount is, which record it
 * is about, what the engine looked at before it gave up, and - where the
 * subject is a credit the cascade did claim and could not prove - the proof
 * attempt itself, so a reader can see exactly which line failed to close.
 *
 * `categorised_by` is shown on every case on purpose. It says whether a
 * category came from rules or from a model, and it is the number behind every
 * "we used AI here and not there" claim this project makes.
 */

import type { QueueItem } from "@/lib/api";
import { inr, shortDate } from "@/lib/money";
import { codeTone, codeTitle } from "./codes";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rule-b flex gap-4 px-4 py-1.5">
      <div className="label w-40 shrink-0 pt-0.5">{label}</div>
      <div className="min-w-0 flex-1 text-[12.5px]">{children}</div>
    </div>
  );
}

export function ExceptionPanel({ item }: { item: QueueItem }) {
  const tone = codeTone(item.code);
  const subject = item.subject;

  return (
    <div className="flex h-full flex-col">
      <header className="rule-b shrink-0 px-4 py-3">
        <div className="flex items-baseline justify-between gap-4">
          <div className="min-w-0">
            <div className="label" style={{ color: tone }}>
              {item.code.replace(/_/g, " ")}
            </div>
            <div className="ident mt-0.5 truncate text-[12.5px]">{subject.id}</div>
          </div>
          {item.amount !== 0 && (
            <div className="figure shrink-0 text-[17px] font-medium" style={{ color: tone }}>
              {inr(item.amount)}
            </div>
          )}
        </div>
        <p className="mt-2.5 text-[13px] leading-snug">{item.summary}</p>
        <p className="mt-1.5 text-[11.5px] text-[var(--ink-faint)]">{codeTitle(item.code, item.evidence.reason)}</p>
      </header>

      <div className="min-h-0 flex-1 overflow-auto">
        <Row label="Subject">
          <span className="capitalize">{subject.kind}</span>
          <span className="ident ml-2">{subject.id}</span>
        </Row>
        {subject.amount !== null && (
          <Row label={subject.kind === "credit" ? "Amount credited" : "Amount"}>
            <span className="figure">{inr(subject.amount)}</span>
          </Row>
        )}
        {subject.occurred_on && (
          <Row label={subject.kind === "credit" ? "Value date" : "Dated"}>
            <span className="figure">{shortDate(subject.occurred_on)}</span>
          </Row>
        )}
        {subject.narration && (
          <Row label="Bank narration">
            <span className="ident break-all">{subject.narration}</span>
          </Row>
        )}

        {Object.entries(item.evidence).length > 0 && (
          <>
            <div className="label rule-b bg-[var(--raised)] px-4 py-1.5">
              What the engine looked at
            </div>
            {Object.entries(item.evidence).map(([key, value]) => (
              <Row key={key} label={key.replace(/_/g, " ")}>
                <span className="break-all">{value}</span>
              </Row>
            ))}
          </>
        )}

        <Row label="Categorised by">
          <span>{item.categorised_by}</span>
          {item.categorised_by === "rules" && (
            <span className="ml-2 text-[11.5px] text-[var(--ink-faint)]">
              deterministic — no model was involved
            </span>
          )}
        </Row>
      </div>
    </div>
  );
}
