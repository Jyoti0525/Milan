"use client";

/**
 * The workspace: navigation on the left, the work in the middle, the evidence
 * on the right.
 *
 * The shape follows Modern Treasury's reconciliation dashboard — a side
 * navigation organised around what you are doing, a summary that links to the
 * next task, and a side-by-side view for working a case one at a time. The
 * surfaces and type are Blade's.
 *
 * Two lists behind one navigation, because there are two halves to an honest
 * answer. **Queue** is what could not be resolved and why. **Proved** is what
 * could, each one openable and checkable line by line. A tool that showed only
 * the second would be a demo.
 *
 * One state object holds the loaded run *and the run it belongs to*. Whether
 * the screen is loading is then derived by comparing that key against the
 * selected run rather than stored, which removes the two ways this goes wrong:
 * a spinner left on after a failure, and a slow response for the run you just
 * navigated away from arriving last and winning.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError, listRuns, loadRun, type RunRef, type RunView } from "@/lib/api";
import { ExceptionPanel } from "@/components/ExceptionPanel";
import { Metrics } from "@/components/Metrics";
import { ProofPanel } from "@/components/ProofPanel";
import { ProofList, QueueList, sortQueue, type Selection } from "@/components/Queue";
import { Sidebar, type Tab } from "@/components/Sidebar";

/** A loaded run, tagged with which run it is. */
interface Loaded {
  key: string;
  view: RunView | null;
  failure: ApiError | null;
}

const keyOf = (run: RunRef | null) => (run ? `${run.difficulty}:${run.seed}` : "");

function Notice({ title, body, command }: { title: string; body: string; command?: string }) {
  return (
    <div className="grid h-full place-items-center p-6">
      <div className="card max-w-lg px-6 py-5">
        <div className="text-[15px] font-semibold">{title}</div>
        <p className="mt-2 text-[13px] leading-relaxed text-[var(--text-muted)]">{body}</p>
        {/* Wrapping, not scrolling. The command is here to be copied, and a
            `milan generate` line with four flags runs past the width of this
            card - which turned the one piece of text on the screen that has to
            be complete into the one piece that was cut off mid-flag. */}
        {command && (
          <pre className="mt-3 rounded-[var(--r-control)] bg-[var(--surface-sunken)] p-3 font-mono text-[12px] leading-relaxed break-words whitespace-pre-wrap text-[var(--text-muted)]">
            {command}
          </pre>
        )}
      </div>
    </div>
  );
}

export default function Workspace() {
  const [runs, setRuns] = useState<RunRef[] | null>(null);
  const [listFailure, setListFailure] = useState<ApiError | null>(null);
  const [current, setCurrent] = useState<RunRef | null>(null);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [tab, setTab] = useState<Tab>("queue");
  const [picked, setPicked] = useState<{ key: string; selection: Selection } | null>(null);

  const key = keyOf(current);

  useEffect(() => {
    let cancelled = false;
    listRuns()
      .then((found) => {
        if (cancelled) return;
        setRuns(found);
        // Prefer a run that will actually open, and the adversarial tier among
        // those — it is the one with something in the queue worth looking at.
        const usable = found.filter((run) => !run.stale);
        setCurrent(
          usable.find((run) => run.difficulty === "adversarial") ?? usable[0] ?? found[0] ?? null,
        );
      })
      .catch((failure: ApiError) => {
        if (!cancelled) setListFailure(failure);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!current) return;
    let cancelled = false;
    loadRun(current.difficulty, current.seed)
      .then((view) => {
        if (!cancelled) setLoaded({ key: keyOf(current), view, failure: null });
      })
      .catch((failure: ApiError) => {
        if (!cancelled) setLoaded({ key: keyOf(current), view: null, failure });
      });
    return () => {
      cancelled = true;
    };
  }, [current]);

  const fresh = loaded?.key === key ? loaded : null;
  const view = fresh?.view ?? null;
  const failure = listFailure ?? fresh?.failure ?? null;
  const loading = current !== null && fresh === null && listFailure === null;
  /*
    A selection belongs to a run *and* to a tab.

    Keying on the run alone left the pane showing a queue case after a switch
    to Proved - the panel and the list disagreeing about what was selected,
    with nothing highlighted in the list to explain it.
  */
  const wanted: Selection["kind"] = tab === "proved" ? "proof" : "exception";
  const selected =
    picked?.key === key && picked.selection.kind === wanted ? picked.selection : null;

  const pick = useCallback((selection: Selection) => setPicked({ key, selection }), [key]);

  /*
    Open the first case rather than an empty pane.

    The detail pane is close to half the screen, and on arrival it held one
    sentence of instruction where the evidence goes - so the first thing the
    screen showed about a reconciliation run was a blank rectangle. There is
    always a sensible first case: the queue is sorted worst-first, so the top
    row is the one somebody would open anyway.

    It is derived, not stored. Writing a selection into state from an effect
    would fight every other path that sets one - switching run, switching tab,
    clicking a row - and the first of those to land would win by timing.
  */
  const fallback = useMemo((): Selection | null => {
    if (!view) return null;
    if (tab === "proved") return view.proofs.length > 0 ? { kind: "proof", index: 0 } : null;
    const first = sortQueue(view.queue)[0];
    return first ? { kind: "exception", index: first.index } : null;
  }, [view, tab]);

  const shown = selected ?? fallback;

  const detail = useMemo(() => {
    if (!view || !shown) return null;
    if (shown.kind === "proof") {
      const proof = view.proofs[shown.index];
      return proof ? <ProofPanel proof={proof} /> : null;
    }
    const item = view.queue[shown.index];
    if (!item) return null;
    // A queue item about a credit that was also proved is rare but real — a
    // settlement can be missing while the credit beside it balances — so the
    // proof is offered when one exists rather than assumed not to.
    const proof = view.proofs.find((candidate) => candidate.credit_id === item.subject.id);
    return proof ? <ProofPanel proof={proof} /> : <ExceptionPanel item={item} />;
  }, [view, shown]);

  const counts = { queue: view?.queue.length ?? 0, proved: view?.proofs.length ?? 0 };

  const body = (() => {
    if (failure && !view) {
      if (failure.status === 0) {
        return (
          <Notice
            title="The engine is not running"
            body={failure.detail}
            command={"cd engine\nuv run milan serve"}
          />
        );
      }
      if (failure.isStale) {
        return (
          <Notice
            title="This run is stale"
            body="The dataset on disk was produced by a different version of the chaos engine, so anything scored against it would describe data this code no longer generates. It is refused rather than shown."
            command={failure.detail.split(": ").slice(-1)[0]}
          />
        );
      }
      return (
        <Notice
          title="No such run"
          body={failure.detail}
          command={"uv run milan generate --seed 42 --difficulty adversarial --orders 600"}
        />
      );
    }

    if (runs !== null && runs.length === 0) {
      return (
        <Notice
          title="Nothing generated yet"
          body="A dataset is a pure function of its seed, so nothing is stored in the repository. Generate one and it will appear here."
          command={"cd engine\nuv run milan generate --seed 42 --difficulty adversarial --orders 600"}
        />
      );
    }

    return (
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="shrink-0 px-5 pt-4">
          {view && <Metrics summary={view.summary} />}
        </div>

        <div className="flex min-h-0 flex-1 gap-4 p-5">
          <section className="card flex min-w-0 flex-1 flex-col overflow-hidden 2xl:max-w-[58%]">
            <div className="flex shrink-0 items-center justify-between gap-4 px-4 py-3">
              <div>
                <h1 className="text-[14px] font-semibold">
                  {tab === "queue" ? "Exception queue" : "Proved credits"}
                </h1>
                <p className="mt-0.5 text-[12px] text-[var(--text-muted)]">
                  {tab === "queue"
                    ? "Everything the engine would not claim, worst first."
                    : "Every credit rebuilt from its settlement rows, to the paisa."}
                </p>
              </div>
              {current && (
                <span className="chip shrink-0 capitalize">
                  {current.difficulty} · seed {current.seed}
                </span>
              )}
            </div>

            <div className="min-h-0 flex-1 overflow-auto">
              {loading && (
                <div className="px-5 py-10 text-center text-[13px] text-[var(--text-subtle)]">
                  Reconciling…
                </div>
              )}
              {view && tab === "queue" && (
                <QueueList items={view.queue} selected={shown} onSelect={pick} />
              )}
              {view && tab === "proved" && (
                <ProofList proofs={view.proofs} selected={shown} onSelect={pick} />
              )}
            </div>
          </section>

          <section className="card hidden min-w-0 flex-1 overflow-hidden xl:block">
            {detail ?? (
              <div className="grid h-full place-items-center px-6 text-center">
                <p className="max-w-xs text-[13px] leading-relaxed text-[var(--text-subtle)]">
                  {tab === "queue"
                    ? "Select a case to see what the engine looked at before it gave up."
                    : "Select a credit to see it rebuilt from its settlement rows, line by line."}
                </p>
              </div>
            )}
          </section>
        </div>
      </div>
    );
  })();

  return (
    <div className="flex h-full">
      <Sidebar
        runs={runs ?? []}
        current={current}
        onPick={setCurrent}
        tab={tab}
        onTab={(next) => setTab(next)}
        counts={counts}
      />
      <main className="flex min-w-0 flex-1 flex-col overflow-hidden">{body}</main>
    </div>
  );
}
