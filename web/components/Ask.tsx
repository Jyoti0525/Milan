"use client";

/**
 * Ask this month a question, and get arithmetic back.
 *
 * A panel rather than a strip, and that was a correction. It began as a row
 * wedged between the metrics and the queue, where it read as one more card
 * of figures — nobody could tell it was a thing you *type into*, which is
 * the only thing it is for.
 *
 * What makes this different from a chat box bolted onto a finance tool is
 * what it will not do. There is no model writing the reply. A model — when
 * one is configured at all — is given exactly one job: deciding which of
 * fourteen known questions was asked. Every figure below the headline is
 * then computed from the reconciled report and carries the record ids it
 * came from. The worst a wrong reading can do is answer a different
 * question, visibly, with correct numbers.
 *
 * Which is why a refusal is a first-class reply here rather than an error
 * state. "I could not tell which question that is" is the honest output for
 * anything this cannot compute, and a merchant handed a confident paragraph
 * about the wrong month has no way to tell it from a right one.
 */

import { useEffect, useRef, useState } from "react";
import { ApiError, type AnswerView } from "@/lib/api";
import { Amount } from "@/components/Amount";

/**
 * Openers, shown only while the conversation is empty.
 *
 * Not decoration and not the menu. An empty box gives no clue what a closed
 * vocabulary accepts, and somebody guessing at it gives up on the second
 * refusal — but these are examples of the *shape* of question that works,
 * not the list of permitted ones, which is why the field invites typing and
 * these sit under it as suggestions rather than as a form.
 */
const OPENERS = [
  "why was my payout short?",
  "am I being overcharged?",
  "how much came in on UPI?",
  "how long do payouts take?",
  "what's the biggest problem here?",
  "what hasn't been settled yet?",
];

type Exchange = {
  question: string;
  answer: AnswerView | null;
  /** Set when the request itself failed — not the same as a refusal. */
  failed: string | null;
};

function Reply({ answer }: { answer: AnswerView }) {
  const refused = answer.intent === null;
  return (
    <>
      <p
        className={`text-[13px] leading-relaxed ${refused ? "text-[var(--warn)]" : ""}`}
      >
        {answer.headline}
      </p>

      {answer.lines.length > 0 && (
        <ul className="mt-3 space-y-2.5">
          {answer.lines.map((line, index) => (
            <li key={`${line.label}-${index}`} className="flex gap-3 text-[12px]">
              <span className="min-w-0 flex-1 leading-relaxed">
                {line.label}
                {line.detail && (
                  <span className="mt-0.5 block text-[var(--text-subtle)]">
                    {line.detail}
                  </span>
                )}
              </span>
              {line.amount !== 0 && (
                <span className="shrink-0 tabular-nums">
                  <Amount paise={line.amount} size="sm" />
                </span>
              )}
            </li>
          ))}
        </ul>
      )}

      {refused && answer.suggestions.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {answer.suggestions.slice(0, 6).map((suggestion) => (
            <span
              key={suggestion}
              className="rounded-full bg-[var(--surface-sunken)] px-2.5 py-1 text-[11.5px] text-[var(--text-muted)]"
            >
              {suggestion}
            </span>
          ))}
        </div>
      )}

      {/*
        Last and quiet. Which question was read, and who read it — provenance
        rather than the answer. It earns its place when a model did the
        reading, because that is the one part of this reply a person might
        reasonably want to second-guess.
      */}
      {!refused && (
        <p className="mt-3 text-[11px] text-[var(--text-subtle)]">
          read as{" "}
          <code className="rounded bg-[var(--surface-sunken)] px-1 py-0.5">
            {answer.intent}
          </code>{" "}
          by {answer.routed_by} · every figure computed from the report
        </p>
      )}
    </>
  );
}

export function Ask({
  scope,
  onAsk,
}: {
  /** What this panel is answering about, named so the reader can see it. */
  scope: string;
  onAsk: (question: string) => Promise<AnswerView>;
}) {
  const [open, setOpen] = useState(false);
  const [question, setQuestion] = useState("");
  const [thread, setThread] = useState<Exchange[]>([]);
  const [thinking, setThinking] = useState(false);
  const field = useRef<HTMLInputElement>(null);
  const tail = useRef<HTMLDivElement>(null);

  // The conversation belongs to the run it was about. Switching runs and
  // keeping the answers would leave figures from one month sitting under a
  // heading naming another.
  useEffect(() => {
    setThread([]);
    setQuestion("");
  }, [scope]);

  useEffect(() => {
    if (open) field.current?.focus();
  }, [open]);

  useEffect(() => {
    tail.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [thread, thinking]);

  async function submit(text: string) {
    const asked = text.trim();
    if (!asked || thinking) return;
    setQuestion("");
    setThinking(true);
    try {
      const answer = await onAsk(asked);
      setThread((so_far) => [...so_far, { question: asked, answer, failed: null }]);
    } catch (error) {
      // A failed request is not a refusal and must not look like one. One is
      // the engine saying it cannot answer; the other is the engine not being
      // reachable — and telling somebody their question was not understood
      // when the server is down sends them off to rewrite a good question.
      setThread((so_far) => [
        ...so_far,
        {
          question: asked,
          answer: null,
          failed:
            error instanceof ApiError ? error.message : "The engine did not answer.",
        },
      ]);
    } finally {
      setThinking(false);
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        // `btn-primary` rather than a restatement of it. The accent lightens
        // in dark mode and the white-on-accent contrast trade is one this
        // design system has already made once, in one place.
        className="btn btn-primary fixed bottom-5 right-5 z-40 gap-2.5 rounded-full px-4 py-3 shadow-lg transition-transform hover:scale-[1.02]"
      >
        <span aria-hidden className="text-[14px] leading-none">
          ✦
        </span>
        Ask about this book
      </button>
    );
  }

  return (
    <section
      aria-label="Ask a question about this book"
      className="card fixed bottom-5 right-5 z-40 flex max-h-[78vh] w-[min(31rem,calc(100vw-2.5rem))] flex-col overflow-hidden shadow-2xl"
    >
      <header className="flex shrink-0 items-center gap-3 border-b border-[var(--border)] px-4 py-3">
        <div className="min-w-0 flex-1">
          <h2 className="text-[13px] font-semibold leading-tight">Ask about this book</h2>
          {/*
            The scope, named. Answers are computed from one reconciled run and
            nothing else, and a reader with several books open needs to know
            which one is being described before they trust a figure.
          */}
          <p className="truncate text-[11px] text-[var(--text-subtle)]">{scope}</p>
        </div>
        <button
          type="button"
          onClick={() => setOpen(false)}
          aria-label="Close"
          className="grid size-6 shrink-0 place-items-center rounded-[5px] text-[var(--text-subtle)] transition-colors hover:bg-[var(--surface-hover)] hover:text-[var(--text)]"
        >
          ✕
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-auto px-4 py-3">
        {thread.length === 0 && (
          <div className="py-1">
            <p className="text-[13px] leading-relaxed">
              Ask anything about these books.
            </p>
            <p className="mt-1 text-[12px] leading-relaxed text-[var(--text-subtle)]">
              Every figure comes back computed from the reconciled rows — nothing here
              is written by a model. If a question cannot be answered from these
              files, it says so rather than guessing.
            </p>
            <p className="mt-4 text-[11px] font-semibold uppercase tracking-wider text-[var(--text-subtle)]">
              For example
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {OPENERS.map((opener) => (
                <button
                  key={opener}
                  type="button"
                  onClick={() => void submit(opener)}
                  className="rounded-full border border-[var(--border)] px-3 py-1.5 text-[12px] text-[var(--text-muted)] transition-colors hover:border-[var(--accent)] hover:text-[var(--accent)]"
                >
                  {opener}
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="space-y-5">
          {thread.map((exchange, index) => (
            <div key={index}>
              {/*
                The question, marked by a rule rather than a bubble. A chat
                transcript of alternating alignments would make a page of
                settlement figures read like a messaging app, which is the
                wrong register for money.
              */}
              <p className="border-l-2 border-[var(--accent)] pl-2.5 text-[13px] font-medium">
                {exchange.question}
              </p>
              <div className="mt-2.5">
                {exchange.failed !== null ? (
                  <p className="text-[13px] text-[var(--bad)]">{exchange.failed}</p>
                ) : (
                  exchange.answer !== null && <Reply answer={exchange.answer} />
                )}
              </div>
            </div>
          ))}

          {thinking && (
            <p className="text-[13px] text-[var(--text-subtle)]">Working it out…</p>
          )}
        </div>
        <div ref={tail} />
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          void submit(question);
        }}
        className="shrink-0 border-t border-[var(--border)] p-3"
      >
        <label className="sr-only" htmlFor="ask">
          Your question
        </label>
        {/*
          The border is on the wrapper rather than the input, so the send
          control sits inside the field. An input and a button side by side
          read as two things; one bordered row reads as somewhere to type.
        */}
        <div className="flex items-center gap-2 rounded-[var(--r-control)] border border-[var(--border)] px-3 py-2 transition-colors focus-within:border-[var(--accent)]">
          <input
            id="ask"
            ref={field}
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Ask anything about these books…"
            maxLength={500}
            className="min-w-0 flex-1 bg-transparent text-[13px] outline-none placeholder:text-[var(--text-subtle)]"
          />
          <button
            type="submit"
            disabled={thinking || question.trim() === ""}
            aria-label="Ask"
            className="btn btn-primary grid size-6 shrink-0 place-items-center rounded-full p-0 text-[12px] leading-none transition-opacity disabled:opacity-25"
          >
            {thinking ? "·" : "↑"}
          </button>
        </div>
      </form>
    </section>
  );
}
