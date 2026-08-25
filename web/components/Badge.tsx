/**
 * A status pill, in Blade's shape.
 *
 * Blade's tables carry status as a soft-tinted rounded badge — Completed in
 * a green wash, Failed in red, Pending in amber — and that is what makes a
 * long table scannable without reading it. An earlier version of this screen
 * used a two-pixel coloured edge instead, on the theory that a pill was
 * decoration. It was too quiet to find anything by, which is the opposite of
 * the point.
 */

export type Tone = "neutral" | "good" | "warn" | "bad" | "accent";

const WASH: Record<Tone, string> = {
  neutral: "var(--surface-sunken)",
  good: "var(--good-wash)",
  warn: "var(--warn-wash)",
  bad: "var(--bad-wash)",
  accent: "var(--accent-wash)",
};

const INK: Record<Tone, string> = {
  neutral: "var(--text-muted)",
  good: "var(--good)",
  warn: "var(--warn)",
  bad: "var(--bad)",
  accent: "var(--accent)",
};

export function Badge({
  children,
  tone = "neutral",
  className = "",
}: {
  children: React.ReactNode;
  tone?: Tone;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-[2px] text-[11px] font-medium whitespace-nowrap ${className}`}
      style={{ background: WASH[tone], color: INK[tone] }}
    >
      {children}
    </span>
  );
}

/** A quieter variant for the things that qualify a row rather than classify it. */
export function Tag({ children }: { children: React.ReactNode }) {
  return (
    <span className="text-[11px] whitespace-nowrap text-[var(--text-subtle)]">{children}</span>
  );
}
