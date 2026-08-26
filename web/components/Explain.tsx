"use client";

/**
 * The answer to a question, kept out of the way until somebody asks it.
 *
 * This screen had a density problem with an honest cause. Every figure on it
 * needs a sentence of context to be trustworthy — a match rate measured
 * against what, a refusal rate over which population, why your own files have
 * no score — and each sentence was written where its figure was. All of them
 * were true and all of them were on screen at once, and the result was a wall
 * that a person reads none of.
 *
 * Cutting the sentences would trade one failure for a worse one: figures with
 * no provenance, on a tool whose entire argument is that it does not ask to be
 * believed. So the sentences stay and the wall goes. Collapsed, this is a link
 * the width of its own question; open, it is everything there is to say.
 *
 * `<details>` rather than state and a click handler, because it is what the
 * element is for: keyboard operable, findable by the browser's own in-page
 * search even while closed, and correct before any JavaScript has run.
 */

export function Explain({
  question,
  children,
}: {
  question: string;
  children: React.ReactNode;
}) {
  return (
    <details className="explain group">
      <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 text-[11.5px] text-[var(--text-subtle)] transition-colors hover:text-[var(--accent-strong)]">
        <span
          aria-hidden
          className="grid h-[13px] w-[13px] shrink-0 place-items-center rounded-full border border-current text-[9px] leading-none font-semibold"
        >
          ?
        </span>
        {question}
      </summary>
      {/*
        Capped at a readable measure. Left to the card's width these
        paragraphs run past a hundred and forty characters on a wide screen,
        which is the line length at which the eye loses its place returning to
        the left margin - and this is the one block on the page written to be
        read rather than scanned.
      */}
      <div className="mt-2 max-w-[70ch] space-y-1.5 border-l-2 border-[var(--border)] pl-3 text-[12px] leading-relaxed text-[var(--text-muted)]">
        {children}
      </div>
    </details>
  );
}
