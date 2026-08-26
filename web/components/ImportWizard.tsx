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
  addFiles,
  ApiError,
  answerImport,
  commitImport,
  discardImport,
  uploadFiles,
  type Plan,
  type Question,
  type StagedFile,
} from "@/lib/api";
import { fromDrop, keep } from "@/lib/files";
import {
  askDetail,
  askTitle,
  blockerHelp,
  CERTAINTY_WORDS,
  fieldName,
  kindMeans,
  kindName,
  whyNotUsed,
} from "@/lib/words";
import { Badge, type Tone } from "./Badge";
import { Explain } from "./Explain";

const CERTAINTY: Record<string, Tone> = {
  confirmed: "good",
  answered: "accent",
  unconfirmed: "warn",
  absent: "neutral",
};

/**
 * What to hand over, and three ways to hand it over.
 *
 * A merchant's books are a **folder**. That is how the command line takes
 * them and how they sit on disk, and until this existed the dialog took files
 * one at a time — so five files meant five trips through a picker, and the
 * folder somebody actually had could not be given to us at all.
 *
 * Worse, each trip started a *new* upload. Picking the settlement report,
 * looking at the result, and then picking the statement left a plan holding
 * the statement alone, with the report silently gone and a message underneath
 * saying there was nothing to reconcile against. That is fixed on the server
 * (`addFiles`); this offers the folder so the situation stops arising.
 */
function Dropzone({
  onFiles,
  busy,
  adding,
}: {
  onFiles: (files: File[]) => void;
  busy: boolean;
  /** Whether this is topping up an upload that already has files in it. */
  adding?: boolean;
}) {
  const [over, setOver] = useState(false);
  const files = useRef<HTMLInputElement>(null);
  const folder = useRef<HTMLInputElement>(null);

  const drop = (event: React.DragEvent) => {
    event.preventDefault();
    setOver(false);
    // Folders arrive as entries rather than files and have to be walked; see
    // `lib/files`. A plain multi-file drop takes the same path and returns
    // immediately.
    void fromDrop(event.dataTransfer).then(onFiles);
  };

  return (
    <div className={adding ? "px-5 pb-4" : "p-5"}>
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={drop}
        className="grid place-items-center rounded-[var(--r-card)] border border-dashed px-6 text-center transition-colors"
        style={{
          borderColor: over ? "var(--accent)" : "var(--border-strong)",
          background: over ? "var(--accent-wash)" : "var(--surface-sunken)",
          paddingTop: adding ? "1.25rem" : "2.25rem",
          paddingBottom: adding ? "1.25rem" : "2.25rem",
        }}
      >
        <div className="text-[14px] font-semibold">
          {adding ? "Add another file" : "Drop the whole folder here"}
        </div>

        {!adding && (
          <>
            {/*
              Named in the merchant's terms, and in the order they matter. The
              old copy said "settlement or recon report" first, which is the
              engine's vocabulary and the file people are least sure they have.
            */}
            <p className="mt-1.5 max-w-md text-[12.5px] leading-relaxed text-[var(--text-muted)]">
              We need two things: the <strong className="font-medium">statement</strong> from the
              bank account your payouts land in, and the{" "}
              <strong className="font-medium">settlement report</strong> from your payment gateway.
            </p>
            <p className="mt-1 max-w-md text-[12px] leading-relaxed text-[var(--text-subtle)]">
              Anything else in the folder is left alone. Add a payments export and we can also look
              for money that was captured and never paid out.
            </p>
          </>
        )}

        <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
          <button
            type="button"
            className="btn btn-primary"
            disabled={busy}
            onClick={() => folder.current?.click()}
          >
            {busy ? "Reading\u2026" : "Choose a folder"}
          </button>
          <button
            type="button"
            className="btn"
            disabled={busy}
            onClick={() => files.current?.click()}
          >
            Or pick files
          </button>
        </div>

        {/*
          The browser's own confirmation.

          Picking a folder makes Chrome put up "Upload 4 files to this site?"
          in its own chrome, and a page cannot restyle it, replace it or
          suppress it - which is the point of it. What we can do is stop it
          being a surprise, because an unexplained security prompt in the
          middle of handing over bank statements is exactly where somebody
          sensible stops.

          It is only shown on the first screen: by the time you are adding a
          second file you have already seen it once.
        */}
        {!adding && (
          <p className="mt-2.5 max-w-md text-[11.5px] leading-relaxed text-[var(--text-subtle)]">
            Your browser will ask you to confirm the folder before it hands anything over. That
            prompt is your browser&apos;s, not ours - choose <strong className="font-medium">Upload</strong>.
            Nothing is read until you approve the plan on the next screen.
          </p>
        )}

        {/*
          `webkitdirectory` is non-standard, unprefixed nowhere, and supported
          everywhere. React does not know the attribute, hence the cast - and
          the plain file input beside it is the fallback for anything that
          ignores it, rather than a second-best offered for its own sake.
        */}
        <input
          ref={folder}
          type="file"
          multiple
          {...({ webkitdirectory: "", directory: "" } as Record<string, string>)}
          className="hidden"
          onChange={(event) => onFiles(keep([...(event.target.files ?? [])]))}
        />
        <input
          ref={files}
          type="file"
          multiple
          accept=".csv,.tsv,.txt,.xlsx,.xlsm,.pdf,.xls"
          className="hidden"
          onChange={(event) => onFiles(keep([...(event.target.files ?? [])]))}
        />

        <p className="mt-3 max-w-md text-[11.5px] leading-relaxed text-[var(--text-subtle)]">
          CSV, TSV or Excel. If your bank only gave you a PDF, download the same statement as CSV
          instead — it is on the same page.
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
      {/*
        A question, phrased as one. The engine states its own position -
        "no header is named like credit", "Date, Value Dt could all be
        value_date" - which is accurate and is not what the person clicking is
        being asked. What they are being asked is always the same shape: which
        column in this file holds this thing.

        The engine's sentence stays underneath as the reason, with the file
        name trimmed off its front because the heading already says it.
      */}
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span className="text-[13px] font-semibold">
          {askTitle(question.subject, question.file)}
        </span>
        <span className="truncate text-[11.5px] text-[var(--text-subtle)]">{question.file}</span>
        {!question.blocking && <Badge tone="neutral">optional</Badge>}
      </div>
      <p className="mt-1 text-[12.5px] leading-relaxed text-[var(--text-muted)]">
        {askDetail(question.asks, question.file)}
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

/**
 * One file, and what we made of it.
 *
 * The version this replaces led with `read as bank_credits`, followed by
 * `100% of the required column names recognised, and 42% of the file\u2019s
 * columns accounted for`, then a row of chips reading `value_date \u2190 Tran
 * Date confirmed`. Every one of those is true and precise, and together they
 * are unreadable by the person who owns the file \u2014 they are the engine
 * describing itself.
 *
 * So the file leads with **what it turned out to be**, in the words the
 * merchant knows it by, and the column detail is folded away. Somebody
 * checking our work opens it; somebody who just wants to know whether we
 * understood their folder does not have to.
 *
 * The percentages are gone from the surface entirely. `42% of the file\u2019s
 * columns accounted for` sounds like a failing grade and means "your
 * statement has a balance column and a branch code and we did not need
 * them", which is not a problem and should not look like one.
 */
function FileCard({
  file,
  onIgnore,
  busy,
}: {
  file: StagedFile;
  onIgnore: (file: string) => void;
  busy: boolean;
}) {
  const mapped = file.resolutions.filter((row) => row.column !== null || row.derived);
  const used = file.kind !== null;
  return (
    <div className="group border-t border-[var(--border)] px-5 py-3 first:border-t-0">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span
          aria-hidden
          className="text-[13px]"
          style={{ color: used ? "var(--good)" : "var(--text-disabled)" }}
        >
          {used ? "\u2713" : "\u2013"}
        </span>
        <span className="text-[13px] font-semibold">
          {used ? kindName(file.kind as string) : "Not used"}
        </span>
        <span className="truncate text-[12px] text-[var(--text-subtle)]">{file.file}</span>
        {used && (
          <span className="tnum ml-auto text-[12px] text-[var(--text-muted)]">
            {file.rows.toLocaleString("en-IN")} rows
          </span>
        )}
      </div>

      {/*
        Saying what an unrecognised file is has always been possible. Saying
        that a recognised one is *not* what we think has not, and a purchase
        ledger read as an orders export is exactly that case: a PO number, a
        value and a raised-on date are what an order book needs, nothing in
        the file rules it out, and only the person who owns it knows.
      */}
      {used && (
        <button
          type="button"
          className="mt-1 text-[11.5px] text-[var(--text-subtle)] underline decoration-dotted underline-offset-2 transition-colors hover:text-[var(--warn)]"
          disabled={busy}
          onClick={() => onIgnore(file.file)}
        >
          That is not what this file is — leave it out
        </button>
      )}

      <p className="mt-0.5 text-[12px] leading-relaxed text-[var(--text-muted)]">
        {used ? kindMeans(file.kind as string) : whyNotUsed(file.kind_reason)}
      </p>

      {mapped.length > 0 && (
        <details className="explain mt-1.5">
          <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 text-[11.5px] text-[var(--text-subtle)] hover:text-[var(--accent-strong)]">
            <span
              aria-hidden
              className="grid h-[13px] w-[13px] place-items-center rounded-full border border-current text-[9px] leading-none font-semibold"
            >
              ?
            </span>
            Which column we read as what ({mapped.length})
          </summary>
          <div className="mt-2 space-y-1 border-l-2 border-[var(--border)] pl-3">
            {mapped.map((row) => {
              const words = CERTAINTY_WORDS[row.certainty];
              return (
                <div
                  key={row.field}
                  className="flex flex-wrap items-baseline gap-x-1.5 text-[12px]"
                  title={`${row.field} \u2190 ${row.column ?? "derived"} \u2014 ${row.reason}`}
                >
                  <span className="font-mono text-[11px] font-medium">
                    {row.derived ? "worked out from the other columns" : row.column}
                  </span>
                  <span aria-hidden className="text-[var(--text-disabled)]">
                    is the
                  </span>
                  <span className="text-[var(--text-muted)]">{fieldName(row.field)}</span>
                  <Badge tone={CERTAINTY[row.certainty] ?? "neutral"}>
                    {row.certainty === "unconfirmed" && row.proposed_by
                      ? `${row.proposed_by} suggested`
                      : (words?.label ?? row.certainty)}
                  </Badge>
                </div>
              );
            })}
          </div>
        </details>
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
  /*
    A structural blocker - no settlement report, or no bank statement - is a
    different thing from an unanswered column, and it is the one a first
    upload almost always hits. It has no question attached, so it is found by
    looking for a blocker that no question accounts for.
  */
  const structural = plan?.blockers.find((line) => !line.includes(" is unanswered")) ?? null;
  const missing = structural ? blockerHelp(structural) : null;
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

  /*
    More files for the upload already open, rather than a new one.

    `uploadFiles` opens a fresh staging area, which is right the first time
    and destructive every time after: a merchant who picked their settlement
    report, looked at the result and then picked their statement ended up with
    the statement alone and their report silently gone.
  */
  const more = (files: File[]) => {
    if (files.length === 0 || !staged) return;
    void run(() => addFiles(staged, files), setPlan);
  };

  const answer = (key: string, value: string) => {
    if (!staged) return;
    void run(() => answerImport(staged, { [key]: value }), setPlan);
  };

  /*
    `-` is the answer meaning "not in this file", and against the record
    subject it means "this file is not one of mine to read". The engine keeps
    it as a decision rather than as the absence of one, so the placement rules
    do not simply run again and place it back.
  */
  const ignore = (file: string) => answer(`${file}:record`, "-");

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

  const commit = () => {
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

          {/*
            The missing-file case, said where somebody can act on it.

            This was one line of grey text beside a disabled button reading
            "no settlement or recon report was found: there is nothing to
            reconcile the bank against". Every word of that is true and none
            of it tells a merchant what to do, which is: go back to your
            gateway dashboard and download one more file.

            It sits at the top rather than the bottom because it is the reason
            nothing below it can run, and because a person who has just
            uploaded one file and seen a dead button is looking for exactly
            this.
          */}
          {plan && missing && (
            <section className="border-b border-[var(--border)] bg-[var(--warn-wash)] px-5 py-3.5">
              <h3 className="text-[13px] font-semibold text-[var(--warn)]">{missing.title}</h3>
              <p className="mt-1 max-w-xl text-[12.5px] leading-relaxed text-[var(--text-muted)]">
                {missing.what}
              </p>
              <Dropzone onFiles={more} busy={busy} adding />
            </section>
          )}

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
                      ? "One question before we can run this."
                      : `${blocking.length} questions before we can run this.`}{" "}
                    We could guess, but a wrong guess here changes what your books say.
                  </div>
                  {suggested.length > 2 && (
                    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--border)] px-5 py-2.5">
                      <span className="text-[12.5px] text-[var(--text-muted)]">
                        {plan.consulted} has an answer for {suggested.length} of them, and nothing
                        in those columns contradicts it. You can take them all and change any of
                        them afterwards.
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
                    We did not recognise {offers.length === 1 ? "one file" : `${offers.length} files`}.
                    That is usually right — a books folder holds invoices and ledgers we have no
                    use for. If we got it wrong, say what {offers.length === 1 ? "it is" : "they are"};
                    otherwise nothing is read from {offers.length === 1 ? "it" : "them"}.
                  </div>
                  {offers.map((question) => (
                    <Ask key={question.key} question={question} onAnswer={answer} busy={busy} />
                  ))}
                </section>
              )}

              <section>
                {plan.files.map((file) => (
                  <FileCard key={file.file} file={file} onIgnore={ignore} busy={busy} />
                ))}
              </section>

              {/*
                Where your other files went.

                This list reached the browser from the first day the upload
                endpoint existed and was rendered nowhere, which is the worst
                possible handling of it: a merchant who dropped six files and
                sees four has no way to find out which two are missing or why.
                It is shown rather than folded, and framed as an outcome
                rather than an error, because for a real folder it usually is
                one - the PDF you downloaded first, and the logo.
              */}
              {plan.unreadable.length > 0 && (
                <section className="border-t border-[var(--border)] px-5 py-3">
                  <h3 className="text-[12.5px] font-semibold">
                    {plan.unreadable.length === 1
                      ? "One file we could not read"
                      : `${plan.unreadable.length} files we could not read`}
                  </h3>
                  <p className="mt-0.5 text-[11.5px] text-[var(--text-subtle)]">
                    Everything else was staged as normal. Nothing below stops the reconciliation.
                  </p>
                  <ul className="mt-1.5 space-y-1">
                    {plan.unreadable.map((line) => (
                      <li key={line} className="text-[12px] leading-relaxed text-[var(--text-muted)]">
                        {line}
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {/*
                Both of these used to be headed sections in the main flow,
                which put "Suggestions the values refused" and "What this run
                cannot check" between a merchant and the button they came for.
                Neither needs an answer. Both are worth keeping - the first is
                the verifier visibly working, the second is the honest list of
                switched-off checks - so both are folded.
              */}
              {plan.rejections.length > 0 && (
                <section className="border-t border-[var(--border)] px-5 py-3">
                  <Explain
                    question={
                      plan.rejections.length === 1
                        ? `We ignored 1 suggestion that did not add up`
                        : `We ignored ${plan.rejections.length} suggestions that did not add up`
                    }
                  >
                    <p>
                      {plan.consulted} suggested these columns. We looked at what is actually in
                      them, found it contradicted the suggestion, and threw it out rather than
                      weighing it up.
                    </p>
                    <ul className="space-y-1">
                      {plan.rejections.map((line) => (
                        <li key={line} className="text-[var(--text-subtle)]">
                          {line}
                        </li>
                      ))}
                    </ul>
                  </Explain>
                </section>
              )}

              {plan.limitations.length > 0 && (
                <section className="border-t border-[var(--border)] px-5 py-3">
                  <Explain question="What we will not be able to check">
                    <p>
                      Nothing here stops the reconciliation. These are checks this folder does not
                      contain the files for, listed before the run rather than after, so a clean
                      result is read for what it is.
                    </p>
                    <ul className="space-y-1">
                      {plan.limitations.map((line) => (
                        <li key={line} className="text-[var(--text-subtle)]">
                          {line}
                        </li>
                      ))}
                    </ul>
                  </Explain>
                </section>
              )}
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
              {/*
                What is still in the way, in a count rather than a sentence.
                The sentence is now either the card at the top of the dialog
                or the question itself, and repeating it down here made the
                footer the third place saying the same thing.
              */}
              {!plan.ready && !missing && (
                <span className="text-[12px] text-[var(--text-subtle)]">
                  {blocking.length === 1
                    ? "1 question left"
                    : `${blocking.length} questions left`}
                </span>
              )}
              <button
                type="button"
                className="btn btn-primary"
                disabled={!plan.ready || busy}
                onClick={commit}
                title={plan.ready ? undefined : plan.blockers[0]}
              >
                {busy ? "Reconciling\u2026" : "Reconcile these files"}
              </button>
            </div>
          </footer>
        )}
      </div>
    </div>
  );
}
