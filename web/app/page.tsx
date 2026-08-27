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
 * Three lists behind one navigation. **Queue** is what could not be resolved
 * and why. **Proved** is what could, each one openable and checkable line by
 * line — a tool that showed only the second would be a demo. **Charged above
 * contract** is the third answer and the odd one out: every row behind it
 * reconciled to the paisa, and it is still money the merchant should not have
 * paid.
 *
 * One state object holds the loaded run *and the run it belongs to*. Whether
 * the screen is loading is then derived by comparing that key against the
 * selected run rather than stored, which removes the two ways this goes wrong:
 * a spinner left on after a failure, and a slow response for the run you just
 * navigated away from arriving last and winning.
 *
 * Two kinds of run reach this screen and they are not interchangeable. A
 * **generated** run is a pure function of a seed and is scored against the
 * answer key generated with it. An **imported** run is a folder of the
 * merchant's own CSVs, has no answer key, and never will — so it gets a
 * different set of metric cards and an audit tab, and the shared union type
 * is what stops one being rendered with the other's claims.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  ApiError,
  listImports,
  listRuns,
  loadImport,
  loadRun,
  type ImportRef,
  type ImportView,
  type RunRef,
  type RunView,
} from "@/lib/api";
import { ExceptionPanel } from "@/components/ExceptionPanel";
import { ExpandButton, type Panel } from "@/components/Expand";
import { ImportWizard } from "@/components/ImportWizard";
import { ImportMetrics, Metrics } from "@/components/Metrics";
import { Position } from "@/components/Position";
import { TopBar } from "@/components/TopBar";
import { ProofPanel } from "@/components/ProofPanel";
import { LeakList, LeakPanel } from "@/components/Leaks";
import { MappingTables, ProvenancePanel } from "@/components/Provenance";
import { ProofList, QueueList, sortQueue } from "@/components/Queue";
import { Sidebar, type Tab } from "@/components/Sidebar";
import type { Selection } from "@/components/Table";

/**
 * Which run is open, and which sort it is.
 *
 * A union rather than two nullable fields, because "a generated run and an
 * imported run are both selected" is not a state this screen has, and a shape
 * that can express it is a shape somebody eventually produces.
 */
type Source = { kind: "run"; run: RunRef } | { kind: "import"; ref: ImportRef };

/** A loaded run, tagged with which run it is. */
interface Loaded {
  key: string;
  view: RunView | ImportView | null;
  failure: ApiError | null;
}

const keyOf = (source: Source | null) =>
  source === null
    ? ""
    : source.kind === "run"
      ? `run:${source.run.difficulty}:${source.run.seed}`
      : `import:${source.ref.slug}`;

/** Whether a loaded view is the imported sort. Narrows the union for TypeScript. */
const isImport = (view: RunView | ImportView | null): view is ImportView =>
  view !== null && "provenance" in view;

/** Which sort of selection each list makes. */
const KIND: Record<Tab, Selection["kind"]> = {
  queue: "exception",
  proved: "proof",
  leaks: "leak",
  // The audit tab holds one document rather than a list of cases, so there is
  // nothing to select in it. Mapped anyway so the record stays total - a
  // lookup that can miss is a lookup that returns undefined at the worst
  // possible moment.
  provenance: "leak",
};

/**
 * What each list is, said once.
 *
 * These were ternaries inline in the markup, which worked for two lists and
 * turned into nested conditionals at three - the shape that quietly ends with
 * one branch saying something slightly different from the others.
 */
const HEADINGS: Record<
  Tab,
  { title: string; blurb: string; empty: string; absent: string; panel: string; one: string }
> = {
  provenance: {
    title: "Column mapping",
    blurb: "What every column in these files was read as, and who decided.",
    empty: "",
    absent: "",
    panel: "The file",
    one: "this file",
  },
  queue: {
    title: "Exception queue",
    blurb: "Everything the engine would not claim, worst first.",
    empty: "Select a case to see what the engine looked at before it gave up.",
    absent: "Nothing to open. Every credit on this run was resolved.",
    panel: "The case",
    one: "this case",
  },
  proved: {
    title: "Proved credits",
    blurb: "Every credit rebuilt from its settlement rows, to the paisa.",
    empty: "Select a credit to see it rebuilt from its settlement rows, line by line.",
    absent: "Nothing to open. No credit on this run was proved.",
    panel: "The proof",
    one: "this proof",
  },
  leaks: {
    title: "Charged above contract",
    blurb: "Rows that reconciled perfectly and were still priced wrong.",
    empty: "Select a finding to see the rate pair, the window, and every row behind it.",
    absent: "Nothing to open. Every fee on this run matched the rate its own row describes.",
    panel: "The finding",
    one: "this finding",
  },
};

/**
 * The screen somebody sees before they have done anything.
 *
 * There was none. An engine with no runs showed a card headed "Nothing
 * generated yet" and a shell command, which tells a merchant neither what
 * this is nor that it will read their own files. This says the three things
 * Milan does, in the order it does them, and puts the only action that
 * matters where the eye lands.
 */
function Welcome({ onImport }: { onImport: () => void }) {
  const steps = [
    {
      title: "Hand over your books",
      body: "Your settlement report and bank statement, in whatever shape they were exported. Anything ambiguous is asked about, not guessed.",
    },
    {
      title: "Every rupee proved, or named",
      body: "Each credit is rebuilt from its settlement rows until it reconstructs to zero. What will not is listed with the reason.",
    },
    {
      title: "What balanced and was still wrong",
      body: "Rows charged above your contracted rate reconcile perfectly. They are reported separately, because nothing else finds them.",
    },
  ];

  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col justify-center gap-5 p-6">
      <div>
        <h1 className="text-[22px] font-semibold tracking-[-0.015em]">
          Reconcile a month of settlements, and see what does not add up.
        </h1>
        <p className="mt-1.5 text-[13.5px] leading-relaxed text-[var(--text-muted)]">
          Point Milan at your own exports, or open a sample run in the sidebar to see what it does
          before you hand over anything.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        {steps.map((step, index) => (
          <div key={step.title} className="card px-4 py-3.5">
            <div className="tnum text-[11px] font-medium text-[var(--text-subtle)]">
              {String(index + 1).padStart(2, "0")}
            </div>
            <div className="mt-1 text-[13px] font-semibold">{step.title}</div>
            <p className="mt-1 text-[12px] leading-relaxed text-[var(--text-muted)]">{step.body}</p>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <button type="button" className="btn btn-primary" onClick={onImport}>
          <span aria-hidden>↑</span> Import your files
        </button>
        <span className="text-[12px] text-[var(--text-subtle)]">
          CSV, TSV or Excel. Nothing is reconciled until you approve how the columns were read.
        </span>
      </div>
    </div>
  );
}

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
  const [imports, setImports] = useState<ImportRef[]>([]);
  const [listFailure, setListFailure] = useState<ApiError | null>(null);
  const [current, setCurrent] = useState<Source | null>(null);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [chosen, setTab] = useState<Tab>("queue");
  /*
    Which panel, if either, has the work area to itself.

    Held here rather than in the two sections because it is one choice with
    three states, not two independent booleans - maximising the case has to
    put the list away, and a pair of booleans can be true at once.
  */
  const [big, setBig] = useState<Panel | null>(null);
  const [importing, setImporting] = useState(false);
  const [picked, setPicked] = useState<{
    key: string;
    selection: Selection;
  } | null>(null);

  const key = keyOf(current);

  useEffect(() => {
    let cancelled = false;
    /*
      Both lists, and the imports are allowed to fail on their own.

      An engine too old to know the route answers 404, and a picker that took
      the whole screen down over a missing section would be worse than one
      that shows no imports. The generated runs are what the screen is for;
      the imports are an addition to it.
    */
    Promise.all([listRuns(), listImports().catch((): ImportRef[] => [])])
      .then(([found, imported]) => {
        if (cancelled) return;
        setRuns(found);
        setImports(imported);
        /*
          Your own books first, and generated data only when there are none.

          This opened on a generated adversarial run for as long as it has
          existed, which was right while generated runs were the only thing
          there was. Once a merchant has imported their own files, opening
          somebody else's sample month and putting its figures under a
          headline that says "money that reached your account" is the wrong
          first screen - the numbers are not theirs, and nothing about a
          landing state says so loudly enough to matter.
        */
        const usable = found.filter((run) => !run.stale);
        const sample =
          usable.find((candidate) => candidate.difficulty === "adversarial") ??
          usable[0] ??
          found[0] ??
          null;
        if (imported.length > 0) setCurrent({ kind: "import", ref: imported[0] });
        else if (sample) setCurrent({ kind: "run", run: sample });
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
    const key = keyOf(current);
    const pending =
      current.kind === "run"
        ? loadRun(current.run.difficulty, current.run.seed)
        : loadImport(current.ref.slug);
    pending
      .then((view: RunView | ImportView) => {
        if (!cancelled) setLoaded({ key, view, failure: null });
      })
      .catch((failure: ApiError) => {
        if (!cancelled) setLoaded({ key, view: null, failure });
      });
    return () => {
      cancelled = true;
    };
  }, [current]);

  const fresh = loaded?.key === key ? loaded : null;
  const view = fresh?.view ?? null;
  const provenance = isImport(view) ? view.provenance : null;

  /*
    The audit tab exists only for an imported run, so leaving it selected
    across a switch to a generated one left the heading over two empty cards -
    a screen with nothing on it and no way to tell that from a failed load.

    Derived from the selection rather than reset in a handler, and keyed on
    which *sort* of run is open rather than on whether the provenance has
    arrived. Keying on the data would bounce the tab back to the queue for as
    long as an imported run took to load, and then not return.
  */
  const audited = current?.kind === "import";
  const tab: Tab = chosen === "provenance" && !audited ? "queue" : chosen;
  const failure = listFailure ?? fresh?.failure ?? null;
  const loading = current !== null && fresh === null && listFailure === null;
  /*
    A selection belongs to a run *and* to a tab.

    Keying on the run alone left the pane showing a queue case after a switch
    to Proved - the panel and the list disagreeing about what was selected,
    with nothing highlighted in the list to explain it.
  */
  const wanted = KIND[tab];
  const selected =
    picked?.key === key && picked.selection.kind === wanted ? picked.selection : null;

  const pick = useCallback((selection: Selection) => setPicked({ key, selection }), [key]);

  /*
    Re-list rather than push the new import onto the array we hold. The list
    endpoint is where record counts and the provider name come from, and a
    locally assembled row would be the one row on this screen that was not
    read from the engine.
  */
  const imported = useCallback((slug: string) => {
    setImporting(false);
    void listImports().then((found) => {
      setImports(found);
      const opened = found.find((ref) => ref.slug === slug);
      if (opened) setCurrent({ kind: "import", ref: opened });
    });
  }, []);

  /*
    Escape puts the split back.

    A maximised panel covers the navigation that would otherwise be the way
    out, and Escape is what somebody presses when a screen has grown to fill
    everything. Bound only while one is maximised, so it never competes with
    the import dialog's own handler.
  */
  useEffect(() => {
    if (big === null) return;
    const restore = (event: KeyboardEvent) => {
      if (event.key === "Escape") setBig(null);
    };
    window.addEventListener("keydown", restore);
    return () => window.removeEventListener("keydown", restore);
  }, [big]);

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
    if (tab === "provenance") return null;
    if (tab === "proved") return view.proofs.length > 0 ? { kind: "proof", index: 0 } : null;
    if (tab === "leaks") return view.leaks.findings.length > 0 ? { kind: "leak", index: 0 } : null;
    const first = sortQueue(view.queue)[0];
    return first ? { kind: "exception", index: first.index } : null;
  }, [view, tab]);

  const shown = selected ?? fallback;

  const detail = useMemo(() => {
    if (tab === "provenance") {
      return provenance ? <ProvenancePanel provenance={provenance} /> : null;
    }
    if (!view || !shown) return null;
    if (shown.kind === "proof") {
      const proof = view.proofs[shown.index];
      return proof ? <ProofPanel proof={proof} /> : null;
    }
    if (shown.kind === "leak") {
      const finding = view.leaks.findings[shown.index];
      return finding ? <LeakPanel finding={finding} /> : null;
    }
    const item = view.queue[shown.index];
    if (!item) return null;
    // A queue item about a credit that was also proved is rare but real — a
    // settlement can be missing while the credit beside it balances — so the
    // proof is offered when one exists rather than assumed not to.
    const proof = view.proofs.find((candidate) => candidate.credit_id === item.subject.id);
    return proof ? <ProofPanel proof={proof} /> : <ExceptionPanel item={item} />;
  }, [view, shown, tab, provenance]);

  // Keyed by tab name, so the navigation counts and the empty-state copy
  // read the same number.
  const counts: Record<Tab, number> = {
    queue: view?.queue.length ?? 0,
    proved: view?.proofs.length ?? 0,
    // Findings, not affected rows. Forty-seven small charges is a report
    // nobody reads; the one pattern behind them is the thing somebody picks
    // up, and the count in the navigation should be a count of those.
    leaks: view?.leaks.findings.length ?? 0,
    // Things somebody has to read, not facts on file. A refused proposal and
    // a switched-off check both need a person; the file list and the column
    // counts do not, so counting those here would put a permanent number
    // beside a tab that usually has nothing to say.
    provenance: provenance ? provenance.rejections.length + provenance.limitations.length : 0,
  };

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

    if (runs !== null && runs.length === 0 && imports.length === 0) {
      return <Welcome onImport={() => setImporting(true)} />;
    }

    return (
      <div className="flex min-h-0 flex-1 flex-col">
        {/*
          Keyed on the run so the strip remounts and its animation replays.
          Switching run used to swap every figure with no sign that anything
          had happened, which reads as a screen that did not respond.
        */}
        {/*
          The run summary, which a maximised panel does not need.

          Four cards and a cash position are an orientation, and somebody who
          has just asked for one panel at full size has finished orienting.
          Keeping them would spend a fifth of the height they asked for on
          figures they had already read.
        */}
        <div
          key={key}
          className={`settle shrink-0 space-y-3 px-5 pt-4 ${big === null ? "" : "hidden"}`}
        >
          {view && (
            <Position
              credited={view.summary.credited}
              proved={view.summary.proved_amount}
              awaited={view.summary.awaited}
              records={view.summary.records_processed}
              seconds={view.summary.duration_seconds}
            />
          )}
          {isImport(view) ? (
            <ImportMetrics
              summary={view.summary}
              consulted={view.provenance.consulted}
              columnsProposed={view.provenance.columns_proposed}
              columnsChecked={view.provenance.columns_checked}
            />
          ) : (
            view && <Metrics summary={view.summary} />
          )}
          {loading && (
            <div className="card px-5 py-4 text-[13px] text-[var(--text-subtle)]">Reconciling…</div>
          )}
        </div>

        <div className="flex min-h-0 flex-1 gap-4 p-5">
          <section
            className={`card flex min-w-0 flex-1 flex-col overflow-hidden ${
              big === "detail" ? "hidden" : big === "list" ? "" : "2xl:max-w-[58%]"
            }`}
          >
            <div className="flex shrink-0 items-center justify-between gap-4 border-b border-[var(--border)] px-4 py-2.5">
              {/*
                Title only. The blurb under it said what the list was, which is
                what the sidebar item that opened it already said - and a
                sentence repeated one click later is a sentence nobody reads
                twice. It is now the empty state, where somebody who has not
                selected anything is looking for exactly that.
              */}
              <h1 className="truncate text-[13.5px] font-semibold" title={HEADINGS[tab].blurb}>
                {HEADINGS[tab].title}
              </h1>
              {current?.kind === "run" && (
                <span className="chip shrink-0 capitalize">
                  {current.run.difficulty} · seed {current.run.seed}
                </span>
              )}
              {/* The folder, not a tier and a seed. An imported run has no
                  seed to name it by, and the thing a person recognises is
                  where the files came from. */}
              {current?.kind === "import" && (
                <span className="chip shrink-0" title={current.ref.source_root}>
                  {current.ref.slug} · {current.ref.files.length} files
                </span>
              )}
              {/* Last, and pushed right by the truncating title beside it. */}
              <div className="ml-auto">
                <ExpandButton
                  expanded={big === "list"}
                  onToggle={() => setBig(big === "list" ? null : "list")}
                  what={HEADINGS[tab].title.toLowerCase()}
                />
              </div>
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
              {view && tab === "leaks" && (
                <LeakList leaks={view.leaks} selected={shown} onSelect={pick} />
              )}
              {provenance && tab === "provenance" && <MappingTables files={provenance.mappings} />}
            </div>
          </section>

          {/*
            A header the right-hand panel did not have.

            It exists for the control in it, and it earns its own line by
            making the two panels symmetric - before this the left had a bar
            and the right began abruptly with a badge. The label is what one
            selected thing is called on this tab, which is the one word the
            panel below never says about itself.
          */}
          <section
            className={`card min-w-0 flex-1 flex-col overflow-hidden ${
              big === "list" ? "hidden" : big === "detail" ? "flex" : "hidden xl:flex"
            }`}
          >
            <div className="flex shrink-0 items-center justify-between gap-4 border-b border-[var(--border)] px-4 py-2.5">
              <h2 className="truncate text-[13.5px] font-semibold">{HEADINGS[tab].panel}</h2>
              <ExpandButton
                expanded={big === "detail"}
                onToggle={() => setBig(big === "detail" ? null : "detail")}
                what={HEADINGS[tab].one}
              />
            </div>
            <div className="min-h-0 flex-1 overflow-hidden">
            {detail ?? (
              <div className="grid h-full place-items-center px-6 text-center">
                {/*
                  "Select a case" is the wrong sentence when there is nothing
                  to select. On a clean tier all three lists can be empty, and
                  an instruction to click a row that does not exist reads as a
                  screen that failed to load rather than a run with nothing
                  wrong in it.
                */}
                <div className="max-w-xs space-y-1.5">
                  <p className="text-[13px] leading-relaxed text-[var(--text-muted)]">
                    {HEADINGS[tab].blurb}
                  </p>
                  <p className="text-[12.5px] leading-relaxed text-[var(--text-subtle)]">
                    {counts[tab] === 0 ? HEADINGS[tab].absent : HEADINGS[tab].empty}
                  </p>
                </div>
              </div>
            )}
            </div>
          </section>
        </div>
      </div>
    );
  })();

  const amounts = {
    queue: view?.queue.reduce((total, item) => total + item.amount, 0) ?? 0,
    proved: view?.summary.proved_amount ?? 0,
    leaks: view?.leaks.cash_impact ?? 0,
  };

  return (
    <div className="flex h-full flex-col">
      <TopBar source={current} onImport={() => setImporting(true)} busy={importing} />
      {importing && <ImportWizard onClose={() => setImporting(false)} onImported={imported} />}
      <div className="flex min-h-0 flex-1">
        <Sidebar
          runs={runs ?? []}
          imports={imports}
          current={current}
          onPick={(run) => setCurrent({ kind: "run", run })}
          onPickImport={(ref) => setCurrent({ kind: "import", ref })}
          tab={tab}
          /*
          Leaving the audit tab open after switching to a generated run would
          show a tab the sidebar no longer offers, with nothing in it. The
          selection follows what the run can actually answer.
        */
          onTab={(next) => setTab(next)}
          counts={counts}
          amounts={amounts}
        />
        <main className="flex min-w-0 flex-1 flex-col overflow-hidden">{body}</main>
      </div>
    </div>
  );
}
