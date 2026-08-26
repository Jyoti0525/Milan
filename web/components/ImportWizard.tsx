"use client";

/**
 * Handing over your own files, and being asked about them.
 *
 * The command line has a folder to point at. A merchant has three CSVs in a
 * downloads directory and no idea what a data root is — so until this existed,
 * the whole "bring your own books" story was available to anyone comfortable
 * with a terminal and to nobody else.
 *
 * The step this dialog exists for is the middle one. Uploading is easy and
 * running is easy; the interesting part is that the engine **stops and asks**
 * when two columns could be the value date, or when `06-07-2026` could be
 * July or June. Those questions are the product, not an obstacle in front of
 * it, so they are shown as questions with real options and a plain sentence
 * saying why they are being asked — never as a validation error.
 *
 * Nothing is kept until Import is pressed. Closing the dialog discards the
 * upload, which is why the close path calls the server rather than just
 * hiding the panel: a merchant's settlement data should not sit in a staging
 * directory because somebody changed their mind.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  answerImport,
  commitImport,
  discardImport,
  uploadFiles,
  type Plan,
  type Question,
  type StagedFile,
} from "@/lib/api";
import { Badge, type Tone } from "./Badge";

const CERTAINTY: Record<string, Tone> = {
  confirmed: "good",
  answered: "accent",
  unconfirmed: "warn",
  absent: "neutral",
};

/** What each label means, in one line, for somebody meeting it first time. */
const MEANS: Record<string, string> = {
  confirmed: "your header name and the values agree",
  answered: "you chose this",
  unconfirmed: "a model suggested it and the values allow it",
  absent: "not in this file",
};

function Dropzone({ onFiles, busy }: { onFiles: (files: File[]) => void; busy: boolean }) {
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  return (
    <div className="p-5">
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(event) => {
          event.preventDefault();
          setOver(false);
          onFiles([...event.dataTransfer.files]);
        }}
        className="grid place-items-center rounded-[var(--r-card)] border border-dashed px-6 py-10 text-center transition-colors"
        style={{
          borderColor: over ? "var(--accent)" : "var(--border-strong)",
          background: over ? "var(--accent-wash)" : "var(--surface-sunken)",
        }}
      >
        <div className="text-[14px] font-semibold">Drop your files here</div>
        <p className="mt-1.5 max-w-md text-[12.5px] leading-relaxed text-[var(--text-muted)]">
          Your settlement or recon report, and your bank statement. Add a payments export too and
          the run can also look for money that was captured and never settled.
        </p>
        <button
          type="button"
          className="btn btn-primary mt-4"
          disabled={busy}
          onClick={() => input.current?.click()}
        >
          {busy ? "Reading…" : "Choose files"}
        </button>
        <input
          ref={input}
          type="file"
          multiple
          accept=".csv,.tsv,.txt,.xlsx,.xlsm"
          className="hidden"
          onChange={(event) => onFiles([...(event.target.files ?? [])])}
        />
        {/*
          The formats, named. A merchant whose bank gave them a workbook and
          who reads "CSV" here converts the file before trying, or gives up -
          and the workbook was always the more likely thing for them to have.
        */}
        <p className="mt-3 text-[11.5px] text-[var(--text-subtle)]">
          CSV, TSV or Excel (.xlsx) — whatever your bank calls its columns. Nothing is reconciled
          until you approve how they were read.
        </p>
      </div>
    </div>
  );
}

/**
 * One question, with its suggestion led rather than buried.
 *
 * The first version of this rendered every candidate column as an identical
 * button. On a settlement export whose headers we have never met that came
 * out as fifteen questions, one of them offering twenty-two identical
 * choices — technically a refusal to guess, and in practice a wall nobody
 * reads to the end of.
 *
 * So where a model proposed something, that is the primary button and it says
 * who proposed it. The rest are still there, one click away, because the
 * whole point is that the suggestion can be overruled.
 */
function Ask({
  question,
  onAnswer,
  busy,
}: {
  question: Question;
  onAnswer: (key: string, value: string) => void;
  busy: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const suggested = question.choices.find((choice) => choice.value === question.suggested);
  const rest = question.choices.filter((choice) => choice.value !== question.suggested);
  const shown = expanded ? rest : rest.slice(0, suggested ? 0 : 6);
  const hidden = rest.length - shown.length;

  return (
    <div className="border-t border-[var(--border)] px-5 py-4 first:border-t-0">
      <div className="flex items-baseline gap-2">
        <Badge tone={question.blocking ? "warn" : "neutral"}>
          {question.blocking ? "needs you" : "optional"}
        </Badge>
        <span className="text-[12.5px] font-medium">
          {question.subject === "record" ? question.file : question.subject}
        </span>
      </div>
      <p className="mt-1.5 text-[12.5px] leading-relaxed text-[var(--text-muted)]">
        {question.asks}
      </p>

      <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
        {suggested && (
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy}
            onClick={() => onAnswer(question.key, suggested.value)}
          >
            Use {suggested.label}
          </button>
        )}
        {shown.map((choice) => (
          <button
            key={choice.value}
            type="button"
            className="btn"
            disabled={busy}
            onClick={() => onAnswer(question.key, choice.value)}
          >
            {choice.label}
          </button>
        ))}
        {hidden > 0 && (
          <button type="button" className="btn" onClick={() => setExpanded(true)} disabled={busy}>
            {suggested ? `Choose a different column (${hidden})` : `Show ${hidden} more`}
          </button>
        )}
      </div>
    </div>
  );
}

function FileCard({ file }: { file: StagedFile }) {
  const mapped = file.resolutions.filter((row) => row.column !== null || row.derived);
  return (
    <div className="border-t border-[var(--border)] px-5 py-3.5 first:border-t-0">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="chip font-mono text-[10.5px]">{file.file}</span>
        <span className="text-[12px] text-[var(--text-muted)]">
          {file.kind ? (
            <>
              read as <strong className="font-medium">{file.kind.replace(/_/g, " ")}</strong> ·{" "}
              {file.rows.toLocaleString("en-IN")} rows
            </>
          ) : (
            <span className="text-[var(--text-subtle)]">not used</span>
          )}
        </span>
      </div>
      <p className="mt-1 text-[11.5px] leading-relaxed text-[var(--text-subtle)]">
        {file.kind_reason}
      </p>

      {mapped.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {mapped.map((row) => (
            <span
              key={row.field}
              title={`${row.field} ← ${row.derived ? "derived" : row.column} — ${row.reason}`}
              className="inline-flex items-center gap-1 rounded-[var(--r-chip)] border border-[var(--border)] bg-[var(--surface-sunken)] px-1.5 py-[2px] text-[11px]"
            >
              <span className="text-[var(--text-muted)]">{row.field}</span>
              <span aria-hidden className="text-[var(--text-disabled)]">
                ←
              </span>
              <span className="font-mono text-[10.5px]">
                {row.derived ? "derived" : row.column}
              </span>
              <Badge tone={CERTAINTY[row.certainty] ?? "neutral"}>
                {row.certainty === "unconfirmed" && row.proposed_by
                  ? row.proposed_by
                  : row.certainty}
              </Badge>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export function ImportWizard({
  onClose,
  onImported,
}: {
  onClose: () => void;
  onImported: (slug: string) => void;
}) {
  const [plan, setPlan] = useState<Plan | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [name, setName] = useState("");

  const staged = plan?.id ?? null;
  const blocking = plan?.questions.filter((question) => question.blocking) ?? [];
  const suggested = blocking.filter((question) => question.suggested);
  const offers = plan?.questions.filter((question) => !question.blocking) ?? [];

  /*
    Discarding on close is the whole reason this is a callback and not just
    `onClose`. A merchant who opens the dialog, drops a settlement report and
    then changes their mind has left their books in a staging directory, and
    nothing else in the system will ever clean it up on their behalf.
  */
  const close = useCallback(() => {
    if (staged) void discardImport(staged);
    onClose();
  }, [staged, onClose]);

  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    window.addEventListener("keydown", escape);
    return () => window.removeEventListener("keydown", escape);
  }, [close]);

  const run = async <T,>(work: () => Promise<T>, then: (value: T) => void) => {
    setBusy(true);
    setFailure(null);
    try {
      then(await work());
    } catch (error) {
      setFailure(error instanceof ApiError ? error.detail : String(error));
    } finally {
      setBusy(false);
    }
  };

  const upload = (files: File[]) => {
    if (files.length === 0) return;
    if (!name) setName(files[0].name.replace(/\.[^.]+$/, ""));
    void run(() => uploadFiles(files), setPlan);
  };

  const answer = (key: string, value: string) => {
    if (!staged) return;
    void run(() => answerImport(staged, { [key]: value }), setPlan);
  };

  /*
    One deliberate act instead of fifteen identical ones.

    This is not a hole in the refuse-and-ask contract, and it is worth saying
    why. The contract is that nothing is applied without a person agreeing —
    not that agreement has to be typed once per column. Fifteen identical
    clicks is not more consent than one reviewed batch; it is less, because by
    the eighth nobody is reading. What follows either way is the mapping
    table, with every one of these marked `answered` and open to being
    changed.
  */
  const acceptAll = () => {
    if (!staged || suggested.length === 0) return;
    const answers = Object.fromEntries(
      suggested.map((question) => [question.key, question.suggested]),
    );
    void run(() => answerImport(staged, answers), setPlan);
  };

  const keep = () => {
    if (!staged) return;
    void run(
      () => commitImport(staged, name),
      ({ slug }) => {
        setPlan(null);
        onImported(slug);
      },
    );
  };

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Import your files"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) close();
      }}
    >
      <div className="card rise flex max-h-[88vh] w-full max-w-2xl flex-col overflow-hidden">
        <header className="flex shrink-0 items-start justify-between gap-4 border-b border-[var(--border)] px-5 py-3.5">
          <div>
            <h2 className="text-[15px] font-semibold">Import your files</h2>
            <p className="mt-0.5 text-[12px] text-[var(--text-muted)]">
              {plan
                ? "Check how each column was read. Nothing runs until you approve it."
                : "Your own exports, in whatever shape your bank and gateway wrote them."}
            </p>
          </div>
          <button type="button" className="btn" onClick={close} aria-label="Close">
            Cancel
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-auto">
          {failure && (
            <div className="border-b border-[var(--border)] bg-[var(--bad-wash)] px-5 py-3 text-[12.5px] text-[var(--bad)]">
              {failure}
            </div>
          )}

          {!plan && <Dropzone onFiles={upload} busy={busy} />}

          {plan && (
            <>
              {/*
                Two kinds of question, and running them together was the bug.
                One sort stops the import because guessing would change a
                balance. The other is an offer to be told what an unrecognised
                file is - and presenting that in the same alarming amber made
                "we left your invoice register alone" look like a failure.
              */}
              {blocking.length > 0 && (
                <section>
                  <div className="bg-[var(--warn-wash)] px-5 py-2.5 text-[12.5px] text-[var(--warn)]">
                    {blocking.length === 1
                      ? "One thing the engine will not decide for you."
                      : `${blocking.length} things the engine will not decide for you.`}{" "}
                    Guessing here would change a balance.
                  </div>
                  {suggested.length > 2 && (
                    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--border)] px-5 py-2.5">
                      <span className="text-[12.5px] text-[var(--text-muted)]">
                        {plan.consulted} has a suggestion for {suggested.length} of them, and the
                        values allow all {suggested.length}.
                      </span>
                      <button
                        type="button"
                        className="btn btn-primary"
                        disabled={busy}
                        onClick={acceptAll}
                      >
                        Accept {suggested.length} suggestions
                      </button>
                    </div>
                  )}
                  {blocking.map((question) => (
                    <Ask key={question.key} question={question} onAnswer={answer} busy={busy} />
                  ))}
                </section>
              )}

              {offers.length > 0 && (
                <section>
                  <div className="border-b border-[var(--border)] bg-[var(--surface-sunken)] px-5 py-2.5 text-[12.5px] text-[var(--text-muted)]">
                    {offers.length === 1 ? "One file was" : `${offers.length} files were`} not
                    recognised. If you know what {offers.length === 1 ? "it is" : "they are"}, say
                    so — otherwise they are left alone and nothing is read from them.
                  </div>
                  {offers.map((question) => (
                    <Ask key={question.key} question={question} onAnswer={answer} busy={busy} />
                  ))}
                </section>
              )}

              <section>
                {plan.files.map((file) => (
                  <FileCard key={file.file} file={file} />
                ))}
              </section>

              {plan.rejections.length > 0 && (
                <section className="border-t border-[var(--border)] px-5 py-3.5">
                  <h3 className="text-[12px] font-semibold">Suggestions the values refused</h3>
                  <p className="mt-0.5 text-[11.5px] text-[var(--text-subtle)]">
                    {plan.consulted} proposed these columns. What is in them contradicted the claim,
                    so they were thrown out rather than weighed.
                  </p>
                  <ul className="mt-1.5 space-y-1">
                    {plan.rejections.map((line) => (
                      <li key={line} className="text-[12px] text-[var(--text-muted)]">
                        {line}
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {plan.limitations.length > 0 && (
                <section className="border-t border-[var(--border)] px-5 py-3.5">
                  <h3 className="text-[12px] font-semibold">What this run cannot check</h3>
                  <ul className="mt-1.5 space-y-1">
                    {plan.limitations.map((line) => (
                      <li key={line} className="text-[12px] text-[var(--text-muted)]">
                        {line}
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              <section className="border-t border-[var(--border)] px-5 py-3 text-[11.5px] text-[var(--text-subtle)]">
                {Object.entries(MEANS).map(([key, means]) => (
                  <span key={key} className="mr-3 inline-flex items-center gap-1">
                    <Badge tone={CERTAINTY[key] ?? "neutral"}>{key}</Badge> {means}
                  </span>
                ))}
              </section>
            </>
          )}
        </div>

        {plan && (
          <footer className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-[var(--border)] px-5 py-3">
            <label className="flex items-center gap-2 text-[12.5px] text-[var(--text-muted)]">
              Call it
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="july-2026"
                className="rounded-[var(--r-control)] border border-[var(--border)] bg-[var(--surface)] px-2 py-1 text-[12.5px] text-[var(--text)]"
              />
            </label>
            <div className="flex items-center gap-3">
              {!plan.ready && (
                <span className="text-[12px] text-[var(--text-subtle)]">{plan.blockers[0]}</span>
              )}
              <button
                type="button"
                className="btn btn-primary"
                disabled={!plan.ready || busy}
                onClick={keep}
              >
                {busy ? "Reconciling…" : "Reconcile these files"}
              </button>
            </div>
          </footer>
        )}
      </div>
    </div>
  );
}
