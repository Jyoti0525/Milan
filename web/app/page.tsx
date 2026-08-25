"use client";

/**
 * The workspace: a run at the top, a list on the left, the detail on the right.
 *
 * Two lists behind one pair of tabs, because they are the two halves of one
 * honest answer. **Queue** is what could not be resolved and why. **Proved**
 * is what could, each one openable and checkable line by line. A tool that
 * showed only the second would be a demo.
 *
 * The failure states get real handling rather than a spinner that never ends.
 * "The engine is not running" and "this dataset came from a different
 * generator" are both things a person can fix in one command, and the screen
 * says which command.
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
import { ProofPanel } from "@/components/ProofPanel";
import { ProofList, QueueList, type Selection } from "@/components/Queue";
import { RunBar } from "@/components/RunBar";

type Tab = "queue" | "proved";

/** A loaded run, tagged with which run it is. */
interface Loaded {
  key: string;
  view: RunView | null;
  failure: ApiError | null;
}

const keyOf = (run: RunRef | null) => (run ? `${run.difficulty}:${run.seed}` : "");

function Notice({ title, body, command }: { title: string; body: string; command?: string }) {
  return (
    <div className="mx-auto mt-16 max-w-lg px-6">
      <div className="label mb-1.5">{title}</div>
      <p className="text-[13px] leading-relaxed text-[var(--ink-soft)]">{body}</p>
      {command && (
        <pre className="ident rule-t mt-3 overflow-x-auto pt-3 text-[11.5px]">{command}</pre>
      )}
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
        // Prefer a run that will actually open, and the adversarial tier
        // among those — it is the one with something in the queue worth
        // looking at.
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

  // Everything below is derived from those two, so none of it can disagree
  // with which run is selected.
  const fresh = loaded?.key === key ? loaded : null;
  const view = fresh?.view ?? null;
  const failure = listFailure ?? fresh?.failure ?? null;
  const loading = current !== null && fresh === null && listFailure === null;
  const selected = picked?.key === key ? picked.selection : null;

  const pick = useCallback((selection: Selection) => setPicked({ key, selection }), [key]);

  const detail = useMemo(() => {
    if (!view || !selected) return null;
    if (selected.kind === "proof") {
      const proof = view.proofs[selected.index];
      return proof ? <ProofPanel proof={proof} /> : null;
    }
    const item = view.queue[selected.index];
    if (!item) return null;
    // A queue item about a credit that was also proved is rare but real — a
    // settlement can be missing while the credit beside it balances — so the
    // proof is offered when one exists rather than assumed not to.
    const proof = view.proofs.find((candidate) => candidate.credit_id === item.subject.id);
    return proof ? <ProofPanel proof={proof} /> : <ExceptionPanel item={item} />;
  }, [view, selected]);

  if (failure && !view) {
    return (
      <div className="flex h-full flex-col">
        <RunBar runs={runs ?? []} current={current} summary={null} onPick={setCurrent} />
        {failure.status === 0 ? (
          <Notice
            title="The engine is not running"
            body={failure.detail}
            command={"cd engine\nuv run milan serve"}
          />
        ) : failure.isStale ? (
          <Notice
            title="This run is stale"
            body="The dataset on disk was produced by a different version of the chaos engine, so anything scored against it would describe data this code no longer generates. It is refused rather than shown."
            command={failure.detail.split(": ").slice(-1)[0]}
          />
        ) : (
          <Notice
            title="No such run"
            body={failure.detail}
            command={"uv run milan generate --seed 42 --difficulty adversarial --orders 600"}
          />
        )}
      </div>
    );
  }

  if (runs !== null && runs.length === 0) {
    return (
      <div className="flex h-full flex-col">
        <RunBar runs={[]} current={null} summary={null} onPick={setCurrent} />
        <Notice
          title="Nothing generated yet"
          body="A dataset is a pure function of its seed, so nothing is stored in the repository. Generate one and it will appear here."
          command={"cd engine\nuv run milan generate --seed 42 --difficulty adversarial --orders 600"}
        />
      </div>
    );
  }

  const counts = { queue: view?.queue.length ?? 0, proved: view?.proofs.length ?? 0 };

  return (
    <div className="flex h-full flex-col">
      <RunBar
        runs={runs ?? []}
        current={current}
        summary={view?.summary ?? null}
        onPick={setCurrent}
      />

      <div className="flex min-h-0 flex-1">
        <section className="rule-r flex min-w-0 flex-1 flex-col bg-[var(--surface)] lg:max-w-[52%]">
          <div className="rule-b flex h-[34px] shrink-0 items-stretch">
            {(["queue", "proved"] as Tab[]).map((name) => (
              <button
                key={name}
                onClick={() => setTab(name)}
                className="label rule-r px-4"
                style={{
                  color: tab === name ? "var(--ink)" : undefined,
                  boxShadow: tab === name ? "inset 0 -2px 0 var(--select-edge)" : undefined,
                }}
              >
                {name === "queue" ? "Queue" : "Proved"}
                <span className="ml-1.5 font-normal text-[var(--ink-faint)]">{counts[name]}</span>
              </button>
            ))}
          </div>

          <div className="min-h-0 flex-1 overflow-auto">
            {loading && (
              <div className="px-4 py-6 text-[12.5px] text-[var(--ink-faint)]">Reconciling…</div>
            )}
            {view && tab === "queue" && (
              <QueueList items={view.queue} selected={selected} onSelect={pick} />
            )}
            {view && tab === "proved" && (
              <ProofList proofs={view.proofs} selected={selected} onSelect={pick} />
            )}
          </div>
        </section>

        <section className="hidden min-w-0 flex-1 bg-[var(--surface)] lg:block">
          {detail ?? (
            <div className="px-4 py-6 text-[12.5px] text-[var(--ink-faint)]">
              {tab === "queue"
                ? "Select a case to see what the engine looked at before it gave up."
                : "Select a credit to see it rebuilt from its settlement rows."}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
