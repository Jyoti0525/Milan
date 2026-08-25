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
  drift_gross: Paise;
  drift_net: Paise;
  proofs_with_drift: number;
  match_rate: number;
  precision: number;
  refusal_rate: number;
  explained_rate: number;
}

export interface RunView {
  summary: RunSummary;
  queue: QueueItem[];
  proofs: Proof[];
}

export const API =
  process.env.NEXT_PUBLIC_MILAN_API?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

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
    throw new ApiError(
      0,
      `Cannot reach the engine at ${API}. Start it with: uv run milan serve`,
    );
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
