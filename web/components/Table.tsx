"use client";

/**
 * The parts the three lists share.
 *
 * The queue, the proved credits and the leak findings are three answers to
 * three different questions, and they are deliberately the same table: a
 * light header row, hairline rules, identifiers on mono chips, money
 * right-aligned. Somebody moving between them should not have to relearn the
 * layout, and a reader should not have to work out whether two screens
 * disagree because the data differs or because the markup drifted.
 *
 * This file exists because the leak list was the third one. Two copies of a
 * row handler is a coincidence; three is a component.
 */

export type Selection =
  | { kind: "exception"; index: number }
  | { kind: "proof"; index: number }
  | { kind: "leak"; index: number };

/**
 * An identifier, whole.
 *
 * This used to clip to ten characters with an ellipsis: `xzxbqya4bc…` cannot
 * be pasted into a ledger search, cannot be read out over a call, and cannot
 * be told apart from another id sharing its first ten characters. The ids
 * this engine mints are a fixed nineteen characters and they fit.
 */
export function Id({ id }: { id: string }) {
  return <span className="chip font-mono text-[10.5px]">{id}</span>;
}

export function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-6 py-10 text-center text-[13px] text-[var(--text-subtle)]">{children}</div>
  );
}

/** Not a hook — plain props. Named without `use` so it is not treated as one. */
export function rowProps(active: boolean, choose: () => void) {
  return {
    "aria-selected": active,
    tabIndex: 0,
    onClick: choose,
    onKeyDown: (event: React.KeyboardEvent) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        choose();
      }
    },
    className: "row-link",
  };
}
