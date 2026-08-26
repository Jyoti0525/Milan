/**
 * The mark.
 *
 * *Milan* means a meeting — two things coming together — which is what a
 * reconciliation is: the gateway's account of a month and the bank's account
 * of the same month, brought to the same line.
 *
 * So the mark is two sets overlapping: the gateway's account of the month,
 * the bank's account of the same month, and the lens where they agree. The
 * lens is the only filled shape and the only thing in the accent colour,
 * because it is the only part that is a claim — everything this engine does
 * is an argument about how much of that overlap is real.
 *
 * It took two wrong drawings to get here, both failing at size rather than in
 * concept. Two chevrons closing on a vertical rule became an asterisk at
 * twenty-eight pixels; the same two chevrons sharing a vertex became an `X`,
 * which is a close button and therefore the worst available association for
 * a mark that means agreement. Curves survive small sizes where converging
 * strokes do not, and nothing else in an interface looks like this.
 *
 * The outlines are `currentColor` so the mark inherits the text colour it
 * sits in, and works on both themes without a second asset.
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
      {/* Reported by the gateway. */}
      <circle cx="11" cy="16" r="8" stroke="currentColor" strokeWidth="2.1" opacity="0.45" />

      {/* Received by the bank. */}
      <circle cx="21" cy="16" r="8" stroke="currentColor" strokeWidth="2.1" opacity="0.45" />

      {/*
        Where the two agree. The chord runs from (9.755) to (22.245) on
        x = 16: half of it is sqrt(r squared minus half the centre distance
        squared), with r = 8 and the centres 10 apart. Spelled out rather than
        left as a magic path, because moving either circle changes it and it
        cannot be re-derived by eye.
      */}
      <path
        d="M16 9.755 A8 8 0 0 1 16 22.245 A8 8 0 0 1 16 9.755 Z"
        fill="var(--accent)"
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
