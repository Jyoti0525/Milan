/**
 * The formatter is the one piece of arithmetic on this side of the wire, so
 * it is the one piece that gets tested.
 *
 * It exists because the API sends integer paise and refuses to send a
 * formatted string - which is the right call, and which puts the obligation
 * here instead. These cases are the same ones `format_inr` is held to in the
 * engine, because two implementations of Indian digit grouping that disagree
 * would disagree in the place a reader is least likely to check: the middle of
 * a large number.
 */

import { describe, expect, it } from "vitest";

import { inr, percent, rupees, shortDate, signed, withRupeeSign } from "./money";

describe("Indian digit grouping", () => {
  it("groups the last three digits, then pairs", () => {
    expect(rupees(100000000)).toBe("10,00,000.00");
    expect(rupees(123456789)).toBe("12,34,567.89");
    expect(rupees(1000000000)).toBe("1,00,00,000.00");
  });

  it("leaves small amounts ungrouped", () => {
    expect(rupees(0)).toBe("0.00");
    expect(rupees(1)).toBe("0.01");
    expect(rupees(99)).toBe("0.99");
    expect(rupees(100)).toBe("1.00");
    expect(rupees(99999)).toBe("999.99");
  });

  it("puts the first comma after three digits, not four", () => {
    // The boundary the western convention gets wrong: 1,00,000 not 100,000.
    expect(rupees(100000)).toBe("1,000.00");
    expect(rupees(1000000)).toBe("10,000.00");
    expect(rupees(10000000)).toBe("1,00,000.00");
  });

  it("always shows two decimal places", () => {
    expect(rupees(500)).toBe("5.00");
    expect(rupees(505)).toBe("5.05");
    expect(rupees(550)).toBe("5.50");
  });

  it("keeps the sign outside the currency mark", () => {
    expect(rupees(-123456789)).toBe("-12,34,567.89");
    expect(inr(-123456789)).toBe("-₹12,34,567.89");
    expect(inr(123456789)).toBe("₹12,34,567.89");
  });
});

describe("never touching a float", () => {
  it("formats amounts a float would round wrong", () => {
    // 0.1 + 0.2 in rupees. As integers there is nothing to get wrong, which
    // is the entire reason paise cross the wire.
    expect(rupees(10 + 20)).toBe("0.30");
    // Large enough that a float's mantissa starts to matter.
    expect(rupees(999999999999)).toBe("9,99,99,99,999.99");
  });

  it("is exact at the paisa for every amount in a realistic range", () => {
    for (let paise = 0; paise < 20000; paise += 7) {
      const [whole, fraction] = rupees(paise).split(".");
      expect(Number(whole.replace(/,/g, "")) * 100 + Number(fraction)).toBe(paise);
    }
  });
});

describe("signed amounts", () => {
  it("separates the sign so a column can carry it", () => {
    expect(signed(-6538)).toEqual({ sign: "-", body: "65.38" });
    expect(signed(326900)).toEqual({ sign: "+", body: "3,269.00" });
  });

  it("gives zero no sign at all", () => {
    expect(signed(0)).toEqual({ sign: "", body: "0.00" });
  });
});

describe("the smaller formatters", () => {
  it("renders a ratio as a percentage", () => {
    expect(percent(0.9047)).toBe("90.5%");
    expect(percent(1)).toBe("100.0%");
    expect(percent(1, 0)).toBe("100%");
  });

  it("renders a date densely without losing the month", () => {
    expect(shortDate("2026-07-03")).toBe("3 Jul");
    expect(shortDate("2026-12-31")).toBe("31 Dec");
    expect(shortDate("2026-01-01")).toBe("1 Jan");
  });
});

describe("the engine's prose, rendered for a browser", () => {
  it("swaps Rs for the rupee sign where an amount follows", () => {
    expect(withRupeeSign("Short by Rs 1,619.24, which is exactly refund rfnd_x.")).toBe(
      "Short by ₹1,619.24, which is exactly refund rfnd_x.",
    );
  });

  it("swaps every amount in a sentence, not just the first", () => {
    expect(withRupeeSign("GST at 28% of the Rs 61.78 fee. The Rs 6.18 is the shortfall.")).toBe(
      "GST at 28% of the ₹61.78 fee. The ₹6.18 is the shortfall.",
    );
  });

  it("leaves negatives intact", () => {
    expect(withRupeeSign("Rs -65.38")).toBe("₹-65.38");
  });

  it("does not touch words that merely start with those letters", () => {
    // The guard that stops this becoming a search-and-replace on real text.
    for (const text of ["Rsomething", "Rs. 40", "settled in Rs", "RSA key"]) {
      expect(withRupeeSign(text)).toBe(text);
    }
  });
});
