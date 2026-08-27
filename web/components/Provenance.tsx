"use client";

/**
 * Where an imported run's numbers came from.
 *
 * Every other list on this screen answers a question about money. This one
 * answers a question about the run itself, and it exists because an imported
 * run cannot be scored. A generated run has an answer key produced alongside
 * it; a merchant's own files come with none, and never will.
 *
 * The temptation is to compute something that looks like accuracy anyway. A
 * number in a card headed "match rate" would be believed, and there is
 * nothing on disk that could make it true — so the screen shows the audit
 * trail instead. Which files were read, which model was asked about the
 * columns, how many it contributed, what it proposed that the values refused,
 * and which checks were switched off for want of a file.
 *
 * The refusals are the part worth looking at. They are the verifier working
 * in public: a model proposed a column, the values in it contradicted the
 * claim, and it was thrown out. A guard whose catches are never shown reports
 * itself as never needed.
 */

import type { ImportProvenance, MappedFile } from "@/lib/api";
import type { Tone } from "./Badge";
import { proven, settledBy } from "@/lib/words";
import { Badge } from "./Badge";
import { Empty } from "./Table";

/** The record kinds, in the order a reconciliation reads them. */
const ORDER = ["orders", "payments", "settlement_rows", "bank_credits"];

/** How each sort of decision reads at a glance. */
const TONE: Record<string, Tone> = {
  confirmed: "good",
  answered: "accent",
  // Amber, deliberately. Not an error — a model's suggestion the values
  // allowed and no header name confirmed, which is exactly the row somebody
  // reviewing an import should stop on.
  unconfirmed: "warn",
  absent: "neutral",
};

const LABEL: Record<string, string> = {
  orders: "Orders",
  payments: "Payments",
  settlement_rows: "Settlement rows",
  bank_credits: "Bank credits",
};

function Section({
  title,
  blurb,
  children,
}: {
  title: string;
  blurb?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="border-t border-[var(--border)] px-4 py-3.5 first:border-t-0">
      <h3 className="text-[12px] font-semibold">{title}</h3>
      {blurb && (
        <p className="mt-0.5 text-[11.5px] leading-relaxed text-[var(--text-subtle)]">{blurb}</p>
      )}
      <div className="mt-2.5">{children}</div>
    </section>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1">
      <span className="text-[12.5px] text-[var(--text-muted)]">{label}</span>
      <span className="tnum text-[12.5px] font-medium">{value}</span>
    </div>
  );
}

/** A line of prose about the run, marked by what sort of statement it is. */
function Line({ tone, children }: { tone: "warn" | "bad"; children: React.ReactNode }) {
  return (
    <li className="flex gap-2 py-1">
      <span
        aria-hidden
        className="mt-[7px] h-[5px] w-[5px] shrink-0 rounded-full"
        style={{ background: tone === "bad" ? "var(--bad)" : "var(--warn)" }}
      />
      <span className="text-[12.5px] leading-relaxed text-[var(--text-muted)]">{children}</span>
    </li>
  );
}

export function ProvenancePanel({ provenance }: { provenance: ImportProvenance }) {
  const model = provenance.consulted !== "none";
  const counts = ORDER.filter((kind) => kind in provenance.counts);

  return (
    <div className="flex h-full flex-col overflow-auto">
      <Section
        title="No answer key, and none is invented"
        blurb="A generated run is scored against ground truth produced alongside it. These are the merchant's own files, so there is no match rate, no precision and no refusal rate to report — those figures are measured against an answer key, and there is not one. What follows is where the numbers did come from."
      >
        <div className="flex flex-wrap gap-1.5">
          <Badge tone="accent">imported</Badge>
          <Badge tone={model ? "accent" : "neutral"}>
            {model ? `columns read by ${provenance.consulted}` : "no model consulted"}
          </Badge>
        </div>
      </Section>

      <Section title="Files read" blurb={provenance.source_root}>
        <div className="flex flex-wrap gap-1.5">
          {provenance.files.map((file) => (
            <span key={file} className="chip font-mono text-[10.5px]">
              {file}
            </span>
          ))}
        </div>
        <div className="mt-2.5">
          {counts.map((kind) => (
            <Row
              key={kind}
              label={LABEL[kind] ?? kind}
              value={provenance.counts[kind].toLocaleString("en-IN")}
            />
          ))}
        </div>
      </Section>

      <Section
        title="What a model contributed"
        blurb={
          model
            ? "Column names, and nothing else. Every amount on this screen was computed before a model was consulted."
            : "Nothing. This import ran on column names and value shapes alone, which is the configuration every claim about this path should be checked in."
        }
      >
        <Row label="Columns proposed and accepted" value={provenance.columns_proposed} />
        <Row label="Proposals the values refused" value={provenance.rejections.length} />
      </Section>

      {provenance.rejections.length > 0 && (
        <Section
          title="Refused"
          blurb="A model named these columns. The values in them contradicted the claim, so they were thrown out rather than weighed."
        >
          <ul>
            {provenance.rejections.map((line) => (
              <Line key={line} tone="bad">
                {line}
              </Line>
            ))}
          </ul>
        </Section>
      )}

      <Section
        title="What this run could not check"
        blurb="Printed before the exception list, not after. A clean queue means less when a check was switched off for want of a file."
      >
        {provenance.limitations.length === 0 ? (
          <p className="text-[12.5px] text-[var(--text-muted)]">
            Nothing. Every file this reconciliation needs was in the folder.
          </p>
        ) : (
          <ul>
            {provenance.limitations.map((line) => (
              <Line key={line} tone="warn">
                {line}
              </Line>
            ))}
          </ul>
        )}
      </Section>

      <Section
        title="Rows the reader would not take"
        blurb="Nothing is repaired. A row that will not read is dropped, and the command line names the file and the line to open."
      >
        <Row label="Dropped" value={provenance.dropped} />
        {/* Not an error and not a credit. Money leaving the account is simply
            not what a settlement reconciliation is about, and it has to be
            counted as neither or the row totals stop adding up. */}
        <Row label="Statement lines that were debits" value={provenance.withdrawals} />
      </Section>
    </div>
  );
}

/**
 * What every column in the merchant's files was read as.
 *
 * This is the artifact the whole feature is for. A merchant handed over a
 * folder; this is the sentence-by-sentence account of what Milan decided each
 * column meant, and — in the `Decided by` column — on whose authority.
 *
 * Confirmed and answered are safe: the header name matched something the
 * schema knows, or a person chose. **Unconfirmed is the one to read.** It
 * means a model proposed the column and the values permitted it, and nothing
 * else agreed — a row that is usually right and is never allowed to be right
 * on its own say-so.
 */
export function MappingTables({ files }: { files: MappedFile[] }) {
  if (files.length === 0) {
    return <Empty>No mapping was saved for this import.</Empty>;
  }

  return (
    <div className="divide-y divide-[var(--border)]">
      {files.map((file) => (
        <div key={file.file} className="px-4 py-3.5">
          <div className="flex items-baseline justify-between gap-3">
            <span className="chip font-mono text-[10.5px]">{file.file}</span>
            <span className="text-[11.5px] text-[var(--text-subtle)]">
              read as {file.kind.replace(/_/g, " ")}
            </span>
          </div>

          <table className="mt-2.5 w-full">
            <thead>
              <tr className="border-b border-[var(--border)] text-left">
                <th className="pb-1 text-[11px] font-medium text-[var(--text-subtle)]">Field</th>
                <th className="pb-1 text-[11px] font-medium text-[var(--text-subtle)]">Column</th>
                <th className="pb-1 text-[11px] font-medium text-[var(--text-subtle)]">
                  Decided by
                </th>
              </tr>
            </thead>
            <tbody>
              {file.columns.map((column) => (
                <tr key={column.field} className="border-b border-[var(--border)] last:border-0">
                  <td className="py-1 pr-3 text-[12px] whitespace-nowrap">{column.field}</td>
                  <td className="py-1 pr-3 text-[12px] text-[var(--text-muted)]">
                    <span className="font-mono text-[11px]">
                      {column.derived ? "derived" : (column.column ?? "—")}
                    </span>
                    {/* The date format, where one was pinned. Two readings of
                        the same column are two different months, so which one
                        was chosen belongs beside the column and not in a
                        footnote. */}
                    {column.pattern && (
                      <span className="ml-1.5 text-[10.5px] text-[var(--text-subtle)]">
                        {column.pattern}
                      </span>
                    )}
                  </td>
                  {/*
                    The audit table and the import dialog now describe a
                    decision the same way, through `settledBy`. They used to
                    disagree: a column the arithmetic proved read as "checked"
                    on one screen and "ollama, unconfirmed" on the other, and
                    the audit trail is the worse place of the two to understate
                    what was done.
                  */}
                  <td className="py-1" title={settledBy(column).means}>
                    <Badge
                      tone={proven(column.reason) ? "good" : (TONE[column.certainty] ?? "neutral")}
                    >
                      {settledBy(column).label}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}
