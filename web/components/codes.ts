/**
 * What each exception code means, in one line, for someone who has to act.
 *
 * The engine's codes are short and precise, which is right for a payload and
 * useless on a screen: `MISSING_SETTLEMENT` and `UNSETTLED_PAYMENT` sound
 * interchangeable and are two different people's problem — one is money the
 * gateway says it sent that the bank never received, the other is money a
 * customer paid that the gateway has not accounted for at all.
 */

import type { ExceptionCode } from "@/lib/api";
import type { Tone } from "./Badge";

/** Short enough for a table cell. The code itself is jargon. */
const LABELS: Record<ExceptionCode, string> = {
  FEE_DEDUCTION: "Fee shortfall",
  TAX_DEDUCTION: "Tax shortfall",
  PARTIAL_PAYMENT: "Part paid",
  MISSING_SETTLEMENT: "Payout missing",
  UNSETTLED_PAYMENT: "Never settled",
  UNEXPLAINED: "Unexplained",
};

const TITLES: Record<ExceptionCode, string> = {
  FEE_DEDUCTION:
    "The payout is short by something that behaves like a fee the report does not show.",
  TAX_DEDUCTION:
    "The shortfall matches a GST slab applied to the fee — tax the report did not declare.",
  PARTIAL_PAYMENT: "Part of this settlement arrived. The rest has not.",
  MISSING_SETTLEMENT: "The gateway reported this payout. Nothing matching it reached the bank.",
  UNSETTLED_PAYMENT:
    "The customer paid and the settlement report never mentions it. No bank credit can find this — only the payments file can.",
  UNEXPLAINED:
    "The amounts differ and no known cause fits. Named as unknown rather than guessed at.",
};

/**
 * `UNEXPLAINED` covers three genuinely different situations, and the engine
 * already distinguishes them in `evidence.reason`. Showing the same sentence
 * for all three would throw that away on the one screen where somebody is
 * deciding what to do about it.
 */
const REASONS: Record<string, string> = {
  "contested settlement":
    "Two bank lines both fit this payout. One of them is it; the evidence does not say which, so neither is claimed.",
  ambiguous:
    "Several payouts fit this credit equally well. Picking one would be a guess dressed as an answer.",
  "no candidate":
    "No settlement in the report accounts for this credit at all. It may not be a gateway payout.",
};

const TONES: Record<ExceptionCode, Tone> = {
  FEE_DEDUCTION: "warn",
  TAX_DEDUCTION: "warn",
  PARTIAL_PAYMENT: "warn",
  MISSING_SETTLEMENT: "bad",
  UNSETTLED_PAYMENT: "bad",
  UNEXPLAINED: "neutral",
};

export const codeLabel = (code: ExceptionCode): string => LABELS[code] ?? code;
export const codeTone = (code: ExceptionCode): Tone => TONES[code] ?? "neutral";

export function codeTitle(code: ExceptionCode, reason?: string): string {
  if (reason && REASONS[reason]) return REASONS[reason];
  return TITLES[code] ?? "";
}

/** Worst first. A queue sorted by id is a list; sorted by severity it is a queue. */
export const CODE_ORDER: ExceptionCode[] = [
  "MISSING_SETTLEMENT",
  "UNSETTLED_PAYMENT",
  "PARTIAL_PAYMENT",
  "FEE_DEDUCTION",
  "TAX_DEDUCTION",
  "UNEXPLAINED",
];

export function severity(code: ExceptionCode): number {
  const index = CODE_ORDER.indexOf(code);
  return index === -1 ? CODE_ORDER.length : index;
}
