/**
 * The mark.
 *
 * *Milan* means a meeting — two things coming together — which is what a
 * reconciliation is: the gateway's account of a month and the bank's account
 * of the same month, brought to the same line.
 *
 * So the mark is two forms converging on a rule. The left chevron is what was
 * reported; the right is what arrived; the bar between them is the line they
 * have to meet on, and it is the only part drawn in the accent colour because
 * it is the only part that is a claim. Nothing here is a monogram — an `M` in
 * a rounded square is what every product does, and it says nothing about this
 * one.
 *
 * Drawn from `currentColor` for the chevrons, so the mark inherits whatever
 * text colour it sits in and works on both themes without a second asset.
 */

export function Logo({ size = 28, className = "" }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      className={className}
      role="img"
      aria-label="Milan"
    >
      {/*
        The tile. Kept at a low opacity rather than a solid fill so the mark
        reads as drawn rather than stamped, and so it survives being placed on
        the sunken surface as well as the raised one.
      */}
      <rect x="0" y="0" width="32" height="32" rx="8" fill="var(--accent)" opacity="0.12" />

      {/* Reported: the left side, closing toward the line. */}
      <path
        d="M9 8.5 L14.5 16 L9 23.5"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.75"
      />

      {/* Arrived: the right side, closing toward the same line. */}
      <path
        d="M23 8.5 L17.5 16 L23 23.5"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.75"
      />

      {/* The line they meet on. The claim, and the only thing in the accent. */}
      <path
        d="M16 7 L16 25"
        stroke="var(--accent)"
        strokeWidth="2.4"
        strokeLinecap="round"
      />
    </svg>
  );
}

/**
 * The mark with the name beside it.
 *
 * The tagline is one clause rather than a sentence, and it is the promise
 * rather than the mechanism: what a merchant gets is proof, and the fact that
 * it comes from rebuilding batches out of settlement rows is not a thing to
 * lead with.
 */
export function Wordmark() {
  return (
    <span className="flex min-w-0 items-center gap-2.5">
      <Logo size={28} className="shrink-0" />
      <span className="min-w-0">
        <span className="block text-[15px] leading-tight font-semibold tracking-[-0.015em]">
          Milan
        </span>
        <span className="hidden truncate text-[11px] leading-tight text-[var(--text-subtle)] sm:block">
          Settlement reconciliation
        </span>
      </span>
    </span>
  );
}
