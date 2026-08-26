"use client";

/**
 * What this is, what you are looking at, and the one thing you came to do.
 *
 * There was no top bar. The product name sat in a corner of the sidebar and
 * nothing on screen said what Milan was for, which run was open, or how to
 * bring your own books — that last one was a command-line flag and nothing
 * else, so the answer to "how do I load my files" was, on this screen,
 * nowhere.
 *
 * The context chip is the fix for a specific complaint: clicking a different
 * run swapped every figure silently, and a person could not tell whether
 * anything had happened. It is keyed on the run so React remounts it and the
 * animation replays — feedback that is structural rather than a flag somebody
 * has to remember to raise.
 */

import type { ImportRef, RunRef } from "@/lib/api";

export type Source = { kind: "run"; run: RunRef } | { kind: "import"; ref: ImportRef };

function Context({ source }: { source: Source }) {
  const imported = source.kind === "import";
  return (
    <span
      key={imported ? source.ref.slug : `${source.run.difficulty}:${source.run.seed}`}
      className="settle inline-flex items-center gap-2 rounded-[var(--r-control)] border px-2.5 py-1"
      style={{
        borderColor: imported ? "var(--accent)" : "var(--border)",
        background: imported ? "var(--accent-wash)" : "var(--surface-sunken)",
      }}
    >
      <span
        aria-hidden
        className="h-1.5 w-1.5 rounded-full"
        style={{ background: imported ? "var(--accent)" : "var(--good)" }}
      />
      <span className="text-[12.5px] font-medium">
        {imported ? source.ref.slug : `${source.run.difficulty} · seed ${source.run.seed}`}
      </span>
      {/*
        The distinction the whole screen turns on, said where it is unmissable.
        A generated run is scored against an answer key. Your own files are
        not, and never will be.
      */}
      <span className="text-[11.5px] text-[var(--text-subtle)]">
        {imported ? "your files · not scored" : "generated · scored"}
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
      <div className="flex min-w-0 items-center gap-2.5">
        <span
          aria-hidden
          className="grid h-7 w-7 shrink-0 place-items-center rounded-[7px] text-[13px] font-bold text-white"
          style={{ background: "var(--accent)" }}
        >
          M
        </span>
        <div className="min-w-0">
          <div className="text-[14px] leading-tight font-semibold tracking-[-0.01em]">Milan</div>
          <div className="hidden truncate text-[11px] leading-tight text-[var(--text-subtle)] sm:block">
            Proves where every rupee went, and refuses to guess
          </div>
        </div>
      </div>

      <div className="min-w-0 flex-1 truncate text-center">
        {source && <Context source={source} />}
      </div>

      <button type="button" className="btn btn-primary shrink-0" onClick={onImport} disabled={busy}>
        <span aria-hidden>↑</span> Import your files
      </button>
    </header>
  );
}
