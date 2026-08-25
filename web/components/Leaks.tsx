"use client";

/**
 * The findings that survive the books balancing.
 *
 * Every other screen in this workspace answers *did the payout arrive*. This
 * one answers whether it should have been that size, and it is the only list
 * here whose rows all reconciled perfectly: the settlement row foots, the
 * batch foots, the bank credit proves to the paisa. Nothing is unmatched, so
 * nothing looks wrong — which is exactly why this class of error survives in
 * real merchant accounts for years.
 *
 * A separate list rather than a section of the queue. The queue is what could
 * not be resolved; every row behind these findings was resolved, and filing
 * them together would bury the one thing in the run that a perfect
 * reconciliation cannot hide.
 *
 * One finding, not forty-seven rows. The rows are underneath it, because a
 * claim about money that cannot be drilled into is a claim nobody should act
 * on.
 */

import type { LeakFinding, LeakFindings } from "@/lib/api";
import { shortDate, withRupeeSign } from "@/lib/money";
import { Amount } from "./Amount";
import { Badge } from "./Badge";
import { Id, rowProps, type Selection } from "./Table";

/**
 * The sentence the engine wrote about the run, above the table.
 *
 * It is here rather than in the page header because it is the finding, not a
 * caption: on a clean tier it is the entire result, and a screen that showed
 * an empty table instead would look like a feature that had not run.
 */
function Headline({ leaks }: { leaks: LeakFindings }) {
  return (
    <div className="border-b border-[var(--border)] bg-[var(--surface-sunken)] px-4 py-3">
      <p className="text-[13px] leading-relaxed">{withRupeeSign(leaks.headline)}</p>
    </div>
  );
}

export function LeakList({
  leaks,
  selected,
  onSelect,
}: {
  leaks: LeakFindings;
  selected: Selection | null;
  onSelect: (selection: Selection) => void;
}) {
  if (leaks.findings.length === 0) {
    return (
      <div>
        <Headline leaks={leaks} />
        {/*
          Said plainly, because "no findings" is a result here and not an
          absence. A detector whose only visible output is the runs where it
          fired cannot be told apart from one that fires at random.
        */}
        <p className="px-4 py-6 text-[12.5px] leading-relaxed text-[var(--text-subtle)]">
          Every fee on this run reproduces exactly from the rate its own row
          describes. The clean and realistic tiers carry no mispriced rows by
          construction — a detector that finds something everywhere has learned
          to find nothing.
        </p>
      </div>
    );
  }

  return (
    <div>
      <Headline leaks={leaks} />
      <table className="w-full border-collapse">
        <thead>
          <tr>
            <th className="th">Finding</th>
            <th className="th w-[92px] text-right">Payments</th>
            <th className="th w-[132px] text-right">Overcharged</th>
          </tr>
        </thead>
        <tbody>
          {leaks.findings.map((finding, index) => {
            const active = selected?.kind === "leak" && selected.index === index;
            return (
              <tr
                key={`${finding.method}-${finding.card_type}-${finding.charged_rate}`}
                {...rowProps(active, () => onSelect({ kind: "leak", index }))}
              >
                <td className="td">
                  <div className="text-[13px] leading-snug first-letter:uppercase">
                    {finding.label} charged{" "}
                    <span className="tnum font-semibold">{finding.charged_rate}</span>, contracted{" "}
                    <span className="tnum">{finding.contracted_rate}</span>
                  </div>
                  <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-[var(--text-subtle)]">
                    <span className="tnum">
                      {shortDate(finding.first_seen)} – {shortDate(finding.last_seen)}
                    </span>
                    <span>·</span>
                    <span className="inline-flex items-baseline gap-1">
                      on
                      <Amount
                        paise={finding.gross_affected}
                        size="sm"
                        tone="var(--text-subtle)"
                      />
                      settled
                    </span>
                  </div>
                </td>
                <td className="td tnum align-top text-right text-[13px]">{finding.payments}</td>
                <td className="td align-top text-right whitespace-nowrap">
                  <Amount paise={finding.overcharge} size="md" tone="var(--warn)" />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-4 border-b border-[var(--border)] px-5 py-2.5">
      <div className="w-40 shrink-0 text-[12px] text-[var(--text-subtle)]">{label}</div>
      <div className="min-w-0 flex-1 text-[13px]">{children}</div>
    </div>
  );
}

export function LeakPanel({ finding }: { finding: LeakFinding }) {
  return (
    <div className="flex h-full flex-col">
      <header className="shrink-0 border-b border-[var(--border)] px-5 py-4">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <Badge tone="warn">Charged above contract</Badge>
            <div className="mt-2 text-[12px] text-[var(--text-muted)] first-letter:uppercase">
              {finding.label}, {finding.method.replace(/_/g, " ")}
            </div>
            <div className="mt-1.5 flex items-baseline gap-2">
              <span className="tnum text-[20px] font-semibold tracking-[-0.01em]">
                {finding.charged_rate}
              </span>
              <span className="text-[12px] text-[var(--text-subtle)]">
                against a contracted <span className="tnum">{finding.contracted_rate}</span>
              </span>
            </div>
          </div>
          <Amount paise={finding.overcharge} size="xl" tone="var(--warn)" />
        </div>

        {/*
          The line that says why nothing else in this tool found it. Without it
          a reader assumes the matcher missed something; with it they can see
          that the matcher was right and the price was wrong.
        */}
        <p className="mt-3.5 text-[12.5px] leading-relaxed text-[var(--text-muted)]">
          Every one of these {finding.payments} rows reconciled to the paisa. Nothing was
          unmatched, so no amount of matching could have found this. It is read off the row
          against the rate the row&rsquo;s own columns imply.
        </p>
      </header>

      <div className="min-h-0 flex-1 overflow-auto">
        <Row label="Charged above contract">
          <span className="tnum">{finding.excess_rate}</span>
          <span className="ml-2 text-[12px] text-[var(--text-subtle)]">on every affected row</span>
        </Row>
        <Row label="Settled value affected">
          <Amount paise={finding.gross_affected} size="md" />
        </Row>
        <Row label="Window">
          <span className="tnum">
            {shortDate(finding.first_seen)} – {shortDate(finding.last_seen)}
          </span>
        </Row>
        {finding.networks.length > 0 && (
          /* The first question anybody asks about a rate mismatch: one
             network's pricing, or the gateway's classification. Most affected
             first. */
          <Row label="Card networks">{finding.networks.join(", ")}</Row>
        )}
        <Row label="Fees overcharged">
          <Amount paise={finding.overcharge} size="md" tone="var(--warn)" />
          <span className="ml-2 text-[12px] text-[var(--text-subtle)]">not recoverable</span>
        </Row>
        <Row label="GST on those fees">
          <Amount paise={finding.gst} size="md" />
          <span className="ml-2 text-[12px] text-[var(--text-subtle)]">
            recoverable as input tax credit
          </span>
        </Row>
        <Row label="Cash that left">
          <Amount paise={finding.cash_impact} size="md" />
        </Row>

        <div className="th border-b border-[var(--border)] px-5">
          The {finding.payment_ids.length} rows behind this
        </div>
        {/*
          All of them, not a sample. This is the difference between a finding a
          merchant can check against their own export and a number they have to
          take on trust, and it is the whole reason the rows are kept after they
          are grouped.
        */}
        <div className="flex flex-wrap gap-1 px-5 py-3">
          {finding.payment_ids.map((id) => (
            <Id key={id} id={id} />
          ))}
        </div>
      </div>

    </div>
  );
}
