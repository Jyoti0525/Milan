"use client";

/**
 * The honest half of the result.
 *
 * An exception here is not an error log entry, it is a case, and the panel is
 * built so somebody can pick it up: what the amount is, which record it is
 * about, and what the engine looked at before it gave up.
 *
 * Nothing is truncated. Modern Treasury's rule for their reconciliation
 * dashboard — show the data "as explicitly and granularly as possible" — is
 * the right one here, because the evidence rows *are* the product. A clipped
 * narration is the one piece of text that decides whether a reference was
 * damaged or absent.
 *
 * `Categorised by` is shown on every case on purpose. It says whether the
 * category came from rules or from a model, and it is the number behind every
 * "we used AI here and not there" claim this project makes.
 */

import type { QueueItem } from "@/lib/api";
import { shortDate, withRupeeSign } from "@/lib/money";
import { Amount } from "./Amount";
import { Badge } from "./Badge";
import { codeLabel, codeTitle, codeTone } from "./codes";

const KIND: Record<string, string> = {
  credit: "Bank credit",
  settlement: "Settlement",
  payment: "Payment",
  unknown: "Record",
};

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-4 border-b border-[var(--border)] px-5 py-2.5">
      <div className="w-40 shrink-0 text-[12px] text-[var(--text-subtle)]">{label}</div>
      <div className="min-w-0 flex-1 text-[13px]">{children}</div>
    </div>
  );
}

export function ExceptionPanel({ item }: { item: QueueItem }) {
  const subject = item.subject;

  return (
    <div className="flex h-full flex-col">
      <header className="shrink-0 border-b border-[var(--border)] px-5 py-4">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <Badge tone={codeTone(item.code)}>{codeLabel(item.code)}</Badge>
            <div className="mt-2 text-[12px] text-[var(--text-muted)]">
              {KIND[subject.kind] ?? "Record"}
            </div>
            <div className="chip mt-1 font-mono">{subject.id}</div>
          </div>
          {item.amount !== 0 && (
            <Amount
              paise={item.amount}
              size="xl"
              tone={codeTone(item.code) === "bad" ? "var(--bad)" : undefined}
            />
          )}
        </div>

        <p className="mt-3.5 text-[13.5px] leading-relaxed">{withRupeeSign(item.summary)}</p>
        <p className="mt-2 text-[12px] leading-relaxed text-[var(--text-subtle)]">
          {codeTitle(item.code, item.evidence.reason)}
        </p>
      </header>

      <div className="min-h-0 flex-1 overflow-auto">
        {subject.amount !== null && (
          <Row label={subject.kind === "credit" ? "Amount credited" : "Amount"}>
            <Amount paise={subject.amount} size="md" />
          </Row>
        )}
        {subject.occurred_on && (
          <Row label={subject.kind === "credit" ? "Value date" : "Dated"}>
            <span className="tnum">{shortDate(subject.occurred_on)}</span>
          </Row>
        )}
        {subject.narration && (
          <Row label="Bank narration">
            <span className="font-mono text-[11.5px] break-all">{subject.narration}</span>
          </Row>
        )}

        {Object.entries(item.evidence).length > 0 && (
          <>
            <div className="th border-b border-[var(--border)] px-5">
              What the engine looked at
            </div>
            {Object.entries(item.evidence).map(([key, value]) => (
              <Row key={key} label={key.replace(/_/g, " ")}>
                <span className="break-all">{withRupeeSign(value)}</span>
              </Row>
            ))}
          </>
        )}

        <Row label="Categorised by">
          <span className="capitalize">{item.categorised_by}</span>
          {item.categorised_by === "rules" && (
            <span className="ml-2 text-[12px] text-[var(--text-subtle)]">
              deterministic — no model was involved
            </span>
          )}
        </Row>
      </div>
    </div>
  );
}
