/**
 * Money, set the way Blade sets it.
 *
 * Razorpay's `Amount` component renders the currency mark small, the rupees
 * large, and the paise small and muted: ₹**1,000**.00. It is not decoration.
 * In a column of settlement values the rupees are what you scan and the paise
 * are what you check, and giving them the same weight makes the eye do the
 * separating instead of the type.
 *
 * The value arrives as integer paise and stays that way. Nothing here divides
 * by a hundred.
 */

import { rupees, type Paise } from "@/lib/money";

type Size = "sm" | "md" | "lg" | "xl";

const RUPEE: Record<Size, string> = {
  sm: "text-[12px]",
  md: "text-[14px]",
  lg: "text-[18px]",
  xl: "text-[26px]",
};

const MARK: Record<Size, string> = {
  sm: "text-[10px]",
  md: "text-[11px]",
  lg: "text-[13px]",
  xl: "text-[16px]",
};

const PAISE: Record<Size, string> = {
  sm: "text-[10px]",
  md: "text-[11px]",
  lg: "text-[13px]",
  xl: "text-[16px]",
};

export function Amount({
  paise,
  size = "md",
  tone,
  showSign = false,
  className = "",
}: {
  paise: Paise;
  size?: Size;
  tone?: string;
  showSign?: boolean;
  className?: string;
}) {
  const negative = paise < 0;
  const [whole, fraction] = rupees(Math.abs(paise)).split(".");
  const sign = negative ? "−" : showSign ? "+" : "";

  return (
    <span
      className={`tnum inline-flex items-baseline whitespace-nowrap ${className}`}
      style={{ color: tone }}
    >
      {sign && <span className={`${MARK[size]} mr-px`}>{sign}</span>}
      <span className={`${MARK[size]} mr-[1px] opacity-70`}>₹</span>
      <span className={`${RUPEE[size]} font-semibold tracking-[-0.01em]`}>{whole}</span>
      <span className={`${PAISE[size]} text-[var(--text-subtle)]`}>.{fraction}</span>
    </span>
  );
}

/** For a figure that is a count or a ratio rather than money. */
export function Figure({
  value,
  size = "lg",
  tone,
}: {
  value: string;
  size?: Size;
  tone?: string;
}) {
  return (
    <span
      className={`tnum font-semibold tracking-[-0.01em] ${RUPEE[size]}`}
      style={{ color: tone }}
    >
      {value}
    </span>
  );
}
