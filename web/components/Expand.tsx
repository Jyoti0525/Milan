"use client";

/**
 * Giving one panel the whole screen, because two panels are not always right.
 *
 * The work area is a list beside a case. That split is correct for working
 * through a queue — pick a row, read it, pick the next — and it is wrong for
 * two things people do constantly and could not do here:
 *
 * **Reading one case properly.** An exception's evidence rows are the
 * product. On a laptop the detail pane is under half the window, so a bank
 * narration wraps three times and the row that explains the shortfall sits
 * below the fold, in a pane a fifth the height of the screen.
 *
 * **Seeing the shape of the queue.** Grouped by kind, nine exceptions are
 * five chips and a list — and the chips take two rows and the list gets what
 * is left, which on the same laptop is four visible rows out of nine.
 *
 * Neither is fixed by tightening the layout, because the constraint is real:
 * the screen is being asked to show two things at once. So it stops being
 * asked. Maximising takes the metric strip away too — those are a summary of
 * the run, and somebody who has just asked for one panel at full size is past
 * the summary.
 *
 * Deliberately not a modal. A dialog over the page would darken the thing
 * being read, trap focus, and need its own close affordance; this is the same
 * panel in the same place with the other one out of the way, and Escape puts
 * it back.
 */

export type Panel = "list" | "detail";

function Arrows({ inward }: { inward: boolean }) {
  // Two corner brackets. Outward for "make this bigger", inward for "put it
  // back" - the direction is the whole message, so the icon is drawn rather
  // than reused from a set where it would be one glyph among many.
  return (
    <svg
      width="13"
      height="13"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {inward ? (
        <>
          <path d="M9.5 2v4.5H14" />
          <path d="M6.5 14V9.5H2" />
        </>
      ) : (
        <>
          <path d="M10 1.5h4.5V6" />
          <path d="M6 14.5H1.5V10" />
        </>
      )}
    </svg>
  );
}

/**
 * The control, labelled by what it will do rather than by what it is.
 *
 * `what` names the panel — "the queue", "this case" — so the tooltip and the
 * screen-reader label read as a sentence. An icon button with no accessible
 * name is the most common way a keyboard user loses a feature entirely.
 */
export function ExpandButton({
  expanded,
  onToggle,
  what,
}: {
  expanded: boolean;
  onToggle: () => void;
  what: string;
}) {
  const label = expanded ? `Show ${what} beside the list again` : `Give ${what} the whole screen`;
  return (
    <button
      type="button"
      onClick={onToggle}
      title={`${label}${expanded ? " (Esc)" : ""}`}
      aria-label={label}
      aria-pressed={expanded}
      className="grid size-6 shrink-0 place-items-center rounded-[5px] text-[var(--text-subtle)] transition-colors hover:bg-[var(--surface-sunken)] hover:text-[var(--text)]"
    >
      <Arrows inward={expanded} />
    </button>
  );
}
