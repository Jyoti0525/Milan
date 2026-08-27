/**
 * The engine's names for things, and a person's.
 *
 * `settlement_rows`, `value_date`, `utr`, `entity_id` are the right names
 * *inside* the engine: they are what the records are called, what the saved
 * mapping is keyed on, and what a developer greps for. On screen, in a dialog
 * a merchant opened to hand over their bank statement, they are a wall of
 * somebody else's vocabulary.
 *
 * So the screen says "your bank statement" and "date on the statement", and
 * keeps the engine's name in a `title` for anybody cross-referencing the
 * command line or the saved mapping. Nothing is renamed in the data — a
 * translation table is reversible and a rename is not.
 *
 * Where a name is unknown, the fallback is the raw field with its underscores
 * turned into spaces. A missing translation should read as slightly clumsy
 * English, never as a blank.
 */

/** What a file turned out to be, in the words the merchant knows it by. */
const KINDS: Record<string, { name: string; from: string }> = {
  settlement_rows: {
    name: "Settlement report",
    from: "the payout report from your payment gateway",
  },
  bank_credits: {
    name: "Bank statement",
    from: "money that actually landed in your account",
  },
  payments: {
    name: "Payments export",
    from: "what your customers paid, before any of it settled",
  },
  orders: {
    name: "Orders export",
    from: "the sales side, to check the payments against",
  },
};

export const kindName = (kind: string): string =>
  KINDS[kind]?.name ?? kind.replace(/_/g, " ");

export const kindMeans = (kind: string): string => KINDS[kind]?.from ?? "";

/**
 * What each field is, said the way somebody reading their own statement
 * would say it.
 *
 * The pairs that matter most are `credit`/`debit` and the three dates. A
 * merchant who reads "credit" as "the credit card column" and answers
 * accordingly inverts every row in the file, and nothing downstream would
 * catch it — the arithmetic balances either way.
 */
const FIELDS: Record<string, string> = {
  // Bank statement
  amount: "amount received",
  value_date: "date on the statement",
  narration: "description",
  utr: "bank reference number",
  debit: "money out",

  // Settlement report
  entity_id: "row ID",
  type: "what the row is",
  credit: "money in",
  fee: "gateway fee",
  tax: "GST on the fee",
  created_at: "date of the transaction",
  settled_at: "date it was paid out",
  settlement_id: "payout ID",
  settlement_utr: "bank reference for the payout",

  // Payments and orders
  payment_id: "payment ID",
  order_id: "order ID",
  order_receipt: "invoice number",
  captured_at: "date it was captured",
  method: "how they paid",
  card_type: "card type",
  card_network: "card network",
  currency: "currency",
  on_hold: "on hold",
  settled: "settled",
};

export const fieldName = (field: string): string =>
  FIELDS[field] ?? field.replace(/_/g, " ");

/**
 * How a column came to be attached to a field, without the jargon.
 *
 * The four states are genuinely different and the difference is the point of
 * the whole dialog, so none of them is collapsed. What changes is that
 * "confirmed" becomes "matched by name" — which says what happened rather
 * than asserting that it is right.
 */
export const CERTAINTY_WORDS: Record<string, { label: string; means: string }> = {
  confirmed: {
    label: "matched",
    means: "the column name and what is in it both fit",
  },
  answered: {
    label: "you chose it",
    means: "you picked this column yourself",
  },
  unconfirmed: {
    label: "suggested",
    means: "a model suggested it and nothing in the column contradicts it",
  },
  absent: {
    label: "not here",
    means: "no column in this file holds it",
  },
};

/**
 * A plan blocker, turned into something with a next step in it.
 *
 * The engine's blockers are precise and are written for somebody who knows
 * what a settlement report is. The two structural ones are the whole reason a
 * first-time upload fails, and "there is nothing to reconcile the bank
 * against" does not tell a merchant that they need to go back to their
 * gateway dashboard and download one more file.
 */
export function blockerHelp(line: string): { title: string; what: string } {
  if (line.includes("no settlement or recon report")) {
    return {
      title: "We need your settlement report too",
      what:
        "You have given us a bank statement, which tells us what arrived. To prove where each " +
        "amount came from we also need the payout or settlement report from your payment " +
        "gateway — in Razorpay it is under Settlements, and most dashboards call it the same " +
        "thing.",
    };
  }
  if (line.includes("no bank statement")) {
    return {
      title: "We need your bank statement too",
      what:
        "You have given us a settlement report, which is what your gateway says it paid you. " +
        "To check that against what actually arrived, download the statement for the account " +
        "those payouts land in — as CSV or Excel, not PDF.",
    };
  }
  return { title: "One column still needs an answer", what: line };
}

/**
 * Why a file was left alone, without the engine's vocabulary.
 *
 * The raw reason is a semicolon-joined list built for a developer:
 *
 *     no column in it reads as entity_type, which settlement_rows needs;
 *     no column in it reads as temporal, which bank_credits needs; ...
 *
 * Four clauses, three internal type names, and one actual fact — the file has
 * no date column. A merchant reading that about their GST register concludes
 * something is broken, when the correct conclusion is "quite right, that is
 * not a settlement report".
 *
 * So the shapes are collapsed into what they mean. Anything unrecognised is
 * returned untouched, because a slightly technical sentence beats a confident
 * mistranslation.
 */
const VALUE_WORDS: Record<string, string> = {
  temporal: "a date",
  money: "an amount",
  identifier: "an ID",
  entity_type: "a row type (payment, refund, adjustment)",
  payment_method: "a payment method",
  card_type: "a card type",
  boolean: "a yes/no flag",
  text: "any text",
};

export function whyNotUsed(reason: string): string {
  const clauses = reason.split(";").map((part) => part.trim());
  const missing = new Set<string>();
  for (const clause of clauses) {
    const match = /^no column in it reads as (\w+), which/.exec(clause);
    if (!match) return reason;
    missing.add(VALUE_WORDS[match[1]] ?? match[1]);
  }
  if (missing.size === 0) return reason;

  const listed = [...missing];
  const named =
    listed.length === 1
      ? listed[0]
      : `${listed.slice(0, -1).join(", ")} or ${listed[listed.length - 1]}`;
  return `Nothing in it looks like ${named}, so it cannot be any of the files we reconcile. Left untouched.`;
}

/**
 * The headline for a question, as a question.
 *
 * The engine phrases these as statements about its own state — "no header is
 * named like credit", "Date, Value Dt could all be value_date". Both are
 * accurate and neither is what a person answering is being asked. What they
 * are being asked is always the same shape: which column in this file holds
 * this thing.
 */
export function askTitle(subject: string, file: string): string {
  if (subject === "record") return `What is ${file}?`;
  return `Which column holds the ${fieldName(subject)}?`;
}

/**
 * The engine's sentence with the file name cut off the front.
 *
 * Every `asks` begins `<file>: `, which was right when the file was not
 * otherwise on screen and is now repetition directly under a heading that
 * names it.
 */
export function askDetail(asks: string, file: string): string {
  return asks.startsWith(`${file}: `) ? asks.slice(file.length + 2) : asks;
}

/**
 * A column the file's own arithmetic settled, rather than a person or a name.
 *
 * `unconfirmed` used to mean one thing — a model said so and the values did
 * not object — and the screen said "suggested", which was honest. It now also
 * covers columns the import *proved*: a settlement report's five money
 * columns satisfying `credit - debit == amount - fee - tax` on every row, or
 * a deposit column left standing after the balance and the row number are
 * eliminated.
 *
 * Those are a stronger claim than a suggestion and a weaker one than a
 * person's answer, so they get their own word. Detected from the reason
 * rather than from a new certainty value, because the certainty is genuinely
 * the same — what changed is what backs it.
 */
export function proven(reason: string): boolean {
  return reason.startsWith("the arithmetic holds") || reason.startsWith("it is the only money");
}

/** The badge for one mapped column, and the sentence behind it. */
export function settledBy(row: {
  certainty: string;
  reason: string;
  proposed_by: string;
}): { label: string; means: string } {
  if (proven(row.reason)) {
    return { label: "checked", means: row.reason };
  }
  if (row.certainty === "unconfirmed" && row.proposed_by) {
    return {
      label: `${row.proposed_by} suggested`,
      means: CERTAINTY_WORDS.unconfirmed.means,
    };
  }
  const words = CERTAINTY_WORDS[row.certainty];
  return { label: words?.label ?? row.certainty, means: words?.means ?? row.reason };
}
