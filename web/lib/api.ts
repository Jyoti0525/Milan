/**
 * The engine, as the browser sees it.
 *
 * These types are written by hand against the FastAPI schema rather than
 * generated. There are four of them and they change when the engine's output
 * changes, which is a thing worth noticing rather than absorbing silently.
 *
 * Every amount is `Paise` - an integer. Nothing here divides by a hundred.
 */

import type { Paise } from "./money";

export type ExceptionCode =
  | "FEE_DEDUCTION"
  | "TAX_DEDUCTION"
  | "PARTIAL_PAYMENT"
  | "MISSING_SETTLEMENT"
  | "UNSETTLED_PAYMENT"
  | "UNEXPLAINED";

export type SubjectKind = "credit" | "settlement" | "payment" | "unknown";

export interface RunRef {
  seed: number;
  difficulty: string;
  orders: number;
  records: number;
  credits: number;
  /** Predates the current generator. Listed so it can be seen, not opened. */
  stale: boolean;
}

export interface Subject {
  kind: SubjectKind;
  id: string;
  amount: Paise | null;
  occurred_on: string | null;
  narration: string | null;
}

export interface QueueItem {
  code: ExceptionCode;
  summary: string;
  amount: Paise;
  evidence: Record<string, string>;
  categorised_by: string;
  subject: Subject;
}

export interface ProofLine {
  label: string;
  amount: Paise;
  refs: string[];
}

export interface Proof {
  credit_id: string;
  credit_amount: Paise;
  settlement_ids: string[];
  value_date: string;
  narration: string;
  strategy: string;
  confidence: number;
  drift: Paise;
  lines: ProofLine[];
  running: Paise[];
  residual: Paise;
}

/**
 * One overcharge pattern: a rate pair, the rows it was applied to, and what
 * it cost.
 *
 * The rates arrive already formatted — `"2.15%"`, not `0.0215`. Nothing here
 * multiplies them by anything, and writing a second percentage formatter in
 * TypeScript would give the screen and the CLI two chances to disagree about
 * a number that is the whole finding.
 */
export interface LeakFinding {
  label: string;
  contracted_rate: string;
  charged_rate: string;
  excess_rate: string;
  method: string;
  card_type: string | null;
  payments: number;
  overcharge: Paise;
  gst: Paise;
  cash_impact: Paise;
  gross_affected: Paise;
  first_seen: string;
  last_seen: string;
  networks: string[];
  /** Every row behind the claim. Truncated for display, never in the payload. */
  payment_ids: string[];
}

export interface LeakFindings {
  headline: string;
  rows_examined: number;
  payments: number;
  overcharge: Paise;
  gst: Paise;
  cash_impact: Paise;
  findings: LeakFinding[];
}

export interface RunSummary {
  seed: number;
  difficulty: string;
  records_processed: number;
  duration_seconds: number;
  credits_total: number;
  proofs_balanced: number;
  exceptions_total: number;
  exceptions_by_code: Record<string, number>;
  rules_share: number;
  /**
   * Every rupee that reached the bank account this run covers.
   *
   * The first number a merchant asks for. Counts of credits proved are how a
   * reconciliation engine thinks; how much money arrived is how the person
   * paying for it thinks.
   */
  credited: Paise;
  /** How much of that reconstructs to zero against the settlement rows. */
  proved_amount: Paise;
  /**
   * Money the gateway says it sent that has not arrived, plus captured
   * payments the settlement report never mentions.
   *
   * Never added to the two above. Those are about money in the account; this
   * is about money that is not, and a screen that summed them would report a
   * total the merchant does not have.
   */
  awaited: Paise;
  drift_gross: Paise;
  drift_net: Paise;
  proofs_with_drift: number;
  match_rate: number;
  /** The denominator of `match_rate`: credits that could be resolved at all. */
  resolvable_credits: number;
  precision: number;
  refusal_rate: number;
  /** Credits impossible by construction. Zero means there was nothing to
   *  refuse, which is a different statement from refusing none of them. */
  refusals_expected: number;
  explained_rate: number;
}

export interface RunView {
  summary: RunSummary;
  queue: QueueItem[];
  proofs: Proof[];
  /** Charges above contract, on rows that reconciled. Empty on a clean tier,
   *  and the screen says so rather than showing nothing. */
  leaks: LeakFindings;
}

/**
 * A folder of the merchant's own files, as the picker sees it.
 *
 * `consulted` is the field worth reading. `"none"` means the import ran on
 * column names and value shapes alone, which is the configuration every claim
 * about this path should be checked in — and a picker that hid it would let a
 * reader assume a model was involved when none was.
 */
export interface ImportRef {
  slug: string;
  source_root: string;
  files: string[];
  records: number;
  credits: number;
  consulted: string;
  columns_proposed: number;
  columns_checked: number;
}

/**
 * Where an imported run's numbers came from.
 *
 * This is what stands in place of a scorecard. A generated run is scored
 * against an answer key generated alongside it; a merchant's own files come
 * with none, and inventing a number that looks like accuracy would be the
 * single most dishonest thing this screen could show.
 */
/** One field, and the column an import decided to read it from. */
export interface MappedColumn {
  field: string;
  column: string | null;
  pattern: string;
  /**
   * `confirmed`, `answered`, `unconfirmed` or `absent`.
   *
   * The most important string on this screen. "Your header said so" and "a
   * model thought so" produce identical-looking rows in a mapping table, and
   * the difference is the whole question of whether these numbers can be
   * trusted without opening the file.
   */
  certainty: string;
  proposed_by: string;
  derived: boolean;
  reason: string;
}

export interface MappedFile {
  file: string;
  kind: string;
  columns: MappedColumn[];
}

export interface ImportProvenance {
  source_root: string;
  files: string[];
  consulted: string;
  columns_proposed: number;
  columns_checked: number;
  /** Column proposals the values refused. One line each, already written. */
  rejections: string[];
  /** Checks this run could not perform, and what each absence costs. */
  limitations: string[];
  dropped: number;
  withdrawals: number;
  counts: Record<string, number>;
  /** Every column decision, as it was saved — not recomputed on read. */
  mappings: MappedFile[];
}

/**
 * The headline for an imported run.
 *
 * Deliberately shorter than `RunSummary`. Every field that one carries and
 * this one does not — match rate, precision, refusal rate, explained rate —
 * is measured against ground truth, and there is none here. The screen says
 * so in words rather than printing a zero that would read as a measurement.
 */
export interface ImportSummary {
  slug: string;
  records_processed: number;
  duration_seconds: number;
  credits_total: number;
  proofs_balanced: number;
  exceptions_total: number;
  exceptions_by_code: Record<string, number>;
  rules_share: number;
  /**
   * Every rupee that reached the bank account this run covers.
   *
   * The first number a merchant asks for. Counts of credits proved are how a
   * reconciliation engine thinks; how much money arrived is how the person
   * paying for it thinks.
   */
  credited: Paise;
  /** How much of that reconstructs to zero against the settlement rows. */
  proved_amount: Paise;
  /**
   * Money the gateway says it sent that has not arrived, plus captured
   * payments the settlement report never mentions.
   *
   * Never added to the two above. Those are about money in the account; this
   * is about money that is not, and a screen that summed them would report a
   * total the merchant does not have.
   */
  awaited: Paise;
  drift_gross: Paise;
  drift_net: Paise;
  proofs_with_drift: number;
}

export interface ImportView {
  summary: ImportSummary;
  provenance: ImportProvenance;
  queue: QueueItem[];
  proofs: Proof[];
  leaks: LeakFindings;
}

export const API = process.env.NEXT_PUBLIC_MILAN_API?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

/**
 * An error the interface can act on.
 *
 * The engine distinguishes "no such run" from "that run came from a different
 * generator", and the second one has a command that fixes it. Collapsing both
 * into "failed to fetch" would throw away the only actionable thing the
 * server said.
 */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }

  /** The run is stale: the fix is a command, and the detail carries it. */
  get isStale(): boolean {
    return this.status === 409;
  }

  get isMissing(): boolean {
    return this.status === 404;
  }
}

async function get<T>(path: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API}${path}`, { cache: "no-store" });
  } catch {
    throw new ApiError(0, `Cannot reach the engine at ${API}. Start it with: uv run milan serve`);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(response.status, body.detail ?? response.statusText);
  }
  return (await response.json()) as T;
}

export const listRuns = () => get<RunRef[]>("/api/runs");

export const loadRun = (difficulty: string, seed: number) =>
  get<RunView>(`/api/runs/${difficulty}/${seed}`);

export const listImports = () => get<ImportRef[]>("/api/imports");

export const loadImport = (slug: string) => get<ImportView>(`/api/imports/${slug}`);

/* -------------------------------------------------------------- uploading */

/** One field the import could not settle, and the answers it will take. */
export interface Choice {
  value: string;
  label: string;
}

export interface Question {
  key: string;
  kind: string;
  file: string;
  subject: string;
  asks: string;
  choices: Choice[];
  /** The answer a model proposed, when one did. Empty otherwise. */
  suggested: string;
  /**
   * Whether the import refuses to proceed until this is answered.
   *
   * False only when being asked what an unrecognised file is. A merchant's
   * folder legitimately holds an invoice register nobody needs, and demanding
   * an answer about it would turn "we left your other file alone" into an
   * error message.
   */
  blocking: boolean;
}

export interface Resolution {
  field: string;
  describes: string;
  required: boolean;
  column: string | null;
  pattern: string;
  certainty: string;
  reason: string;
  proposed_by: string;
  derived: boolean;
}

export interface StagedFile {
  file: string;
  kind: string | null;
  kind_reason: string;
  rows: number;
  headers: string[];
  resolutions: Resolution[];
}

/**
 * A reading of an upload, before anybody has agreed to it.
 *
 * The whole state rather than a delta. Every answer re-plans on the server,
 * and a browser holding a patched-up copy of an older plan is a browser that
 * can show somebody a mapping the engine is not going to use.
 */
export interface Plan {
  id: string;
  consulted: string;
  files: StagedFile[];
  questions: Question[];
  rejections: string[];
  limitations: string[];
  blockers: string[];
  ready: boolean;
  unreadable: string[];
}

async function send<T>(path: string, init: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API}${path}`, init);
  } catch {
    throw new ApiError(0, `Cannot reach the engine at ${API}. Start it with: uv run milan serve`);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(response.status, body.detail ?? response.statusText);
  }
  return (await response.json()) as T;
}

export function uploadFiles(files: File[]): Promise<Plan> {
  const body = new FormData();
  for (const file of files) body.append("files", file, file.name);
  return send<Plan>("/api/uploads", { method: "POST", body });
}

/**
 * More files for an upload that is already open, keeping the answers given.
 *
 * The distinction from `uploadFiles` is the whole point. Posting to
 * `/api/uploads` again opens a *new* staging area, so picking a settlement
 * report and then picking a bank statement produced a plan holding the
 * statement alone — the report silently gone, and an error underneath saying
 * there was nothing to reconcile against.
 */
export function addFiles(id: string, files: File[]): Promise<Plan> {
  const body = new FormData();
  for (const file of files) body.append("files", file, file.name);
  return send<Plan>(`/api/uploads/${id}/files`, { method: "POST", body });
}

export const answerImport = (id: string, answers: Record<string, string>) =>
  send<Plan>(`/api/uploads/${id}/answers`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ answers }),
  });

export const commitImport = (id: string, name: string) =>
  send<{ slug: string }>(`/api/uploads/${id}/commit`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name }),
  });

/** Throw a staged upload away. Failure is ignored: the caller wanted it gone. */
export const discardImport = (id: string) =>
  fetch(`${API}/api/uploads/${id}`, { method: "DELETE" }).catch(() => undefined);
