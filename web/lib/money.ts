/**
 * Money, on the browser side of the wire.
 *
 * The API sends integer paise and never a formatted string, so this is where
 * rupees are made. It mirrors `format_inr` in `milan.domain.money` exactly,
 * including the Indian grouping convention - last three digits, then pairs,
 * so 12,34,567.89 rather than 1,234,567.89.
 *
 * `Intl.NumberFormat("en-IN")` would do the grouping, and is deliberately not
 * used: it takes a Number, which means dividing paise by 100 and handing the
 * result to a float somewhere between here and the screen. The whole engine
 * is built on integers precisely so that never happens, and the last hundred
 * lines of the pipeline are no place to give that up for a shorter function.
 */

/** Paise. Integer, always. The unit every amount crosses the wire in. */
export type Paise = number;

/** Group the whole-rupee digits Indian style: last three, then pairs. */
function group(digits: string): string {
  if (digits.length <= 3) return digits;
  const tail = digits.slice(-3);
  let head = digits.slice(0, -3);
  const parts: string[] = [];
  while (head.length > 2) {
    parts.unshift(head.slice(-2));
    head = head.slice(0, -2);
  }
  if (head) parts.unshift(head);
  return [...parts, tail].join(",");
}

/** `123456789` becomes `12,34,567.89`. No currency mark. */
export function rupees(paise: Paise): string {
  const sign = paise < 0 ? "-" : "";
  const absolute = Math.abs(paise);
  const whole = Math.trunc(absolute / 100);
  const fraction = absolute % 100;
  return `${sign}${group(String(whole))}.${String(fraction).padStart(2, "0")}`;
}

/** `123456789` becomes `₹12,34,567.89`. */
export function inr(paise: Paise): string {
  const body = rupees(paise);
  return body.startsWith("-") ? `-₹${body.slice(1)}` : `₹${body}`;
}

/**
 * A deduction shown as what it is.
 *
 * Proof lines are signed from the merchant's point of view, so a fee arrives
 * as a negative number. Rendering it as "-₹65.38" beside a positive sale is
 * correct and hard to scan; a ledger writes the sign once, in the column, and
 * this returns the parts to let the caller do that.
 */
export function signed(paise: Paise): { sign: "+" | "-" | ""; body: string } {
  if (paise === 0) return { sign: "", body: rupees(0) };
  return { sign: paise < 0 ? "-" : "+", body: rupees(Math.abs(paise)) };
}

/** `0.9047` becomes `90.5%`. */
export function percent(ratio: number, places = 1): string {
  return `${(ratio * 100).toFixed(places)}%`;
}

/** `2026-07-03` becomes `3 Jul`. Dense, and unambiguous about the month. */
export function shortDate(iso: string): string {
  const [, month, day] = iso.split("-");
  const months = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
  ];
  return `${Number(day)} ${months[Number(month) - 1] ?? month}`;
}
