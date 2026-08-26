"use client";

/**
 * What this is, what you are looking at, and the one thing you came to do.
 *
 * The context chip is the fix for a specific complaint: clicking a different
 * run swapped every figure silently, and a person could not tell whether
 * anything had happened. It is keyed on the run so React remounts it and the
 * animation replays — feedback that is structural rather than a flag somebody
 * has to remember to raise.
 *
 * It used to end with the words **not scored** on an imported run, which was
 * true and was read — correctly — as a demerit. It is not one. A generated run
 * is scored because it was generated with an answer key beside it; a
 * merchant's own books have no answer key and never will, so there is nothing
 * to score *against*. Saying "not scored" puts the absence on the merchant's
 * files rather than where it belongs, which is on the nature of real data. So
 * the chip now names what the run *is* — your books, or sample data — and the
 * explanation lives one click away in `Explain`, where somebody who wants it
 * can have all of it and nobody else has to read any of it.
 */

import type { ImportRef, RunRef } from "@/lib/api";
import { Wordmark } from "./Logo";

export type Source = { kind: "run"; run: RunRef } | { kind: "import"; ref: ImportRef };

function Context({ source }: { source: Source }) {
  const imported = source.kind === "import";
  return (
    <span
      key={imported ? source.ref.slug : `${source.run.difficulty}:${source.run.seed}`}
      className="settle inline-flex max-w-full items-center gap-2 rounded-[var(--r-control)] border px-2.5 py-1"
      style={{
        borderColor: imported ? "var(--accent-line)" : "var(--border)",
        background: imported ? "var(--accent-wash)" : "var(--surface-sunken)",
      }}
    >
      <span
        aria-hidden
        className="h-1.5 w-1.5 shrink-0 rounded-full"
        style={{ background: imported ? "var(--accent)" : "var(--text-disabled)" }}
      />
      <span className="truncate text-[12.5px] font-medium">
        {imported ? source.ref.slug : `${source.run.difficulty} · seed ${source.run.seed}`}
      </span>
      <span className="shrink-0 text-[11.5px] text-[var(--text-subtle)]">
        {imported ? "your books" : "sample data"}
      </span>
    </span>
  );
}

export function TopBar({
  source,
  onImport,
  busy,
}: {
  source: Source | null;
  onImport: () => void;
  busy: boolean;
}) {
  return (
    <header className="flex h-[56px] shrink-0 items-center gap-4 border-b border-[var(--border)] bg-[var(--surface)] px-4">
      <Wordmark />

      <div className="flex min-w-0 flex-1 justify-center">
        {source && <Context source={source} />}
      </div>

      <button type="button" className="btn btn-primary shrink-0" onClick={onImport} disabled={busy}>
        <span aria-hidden>↑</span>
        <span className="hidden sm:inline">Import your files</span>
        <span className="sm:hidden">Import</span>
      </button>
    </header>
  );
}
