"use client";

/**
 * Ask this month a question, and get arithmetic back.
 *
 * A panel rather than a strip, and that was a correction. It began as a row
 * wedged between the metrics and the queue, where it read as one more card
 * of figures — nobody could tell it was a thing you *type into*, which is
 * the only thing it is for. It now opens from a launcher, keeps the
 * conversation, and puts the input where an input belongs.
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
 * not the list of permitted ones, which is why the placeholder invites
 * typing and these sit underneath it.
 */
const OPENERS = [
  "why was my payout short?",
  "am I being overcharged?",
  "how much came in on UPI?",
  "what's the biggest problem here?",
  "how long do payouts take?",
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
        <ul className="mt-2.5 space-y-2">
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
        <ul className="mt-2.5 space-y-1">
          {answer.suggestions.map((suggestion) => (
            <li key={suggestion} className="text-[12px] text-[var(--text-subtle)]">
              — {suggestion}
            </li>
          ))}
        </ul>
      )}

      {/*
        Last and quiet. Which question was read, and who read it — provenance
        rather than the answer. It earns its place when a model did the
        reading, because that is the one part of this reply a person might
        reasonably want to second-guess.
      */}
      {!refused && (
        <p className="mt-2.5 text-[11px] text-[var(--text-subtle)]">
          read as <code>{answer.intent}</code> by {answer.routed_by} · every figure
          computed from the report
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
    tail.current?.scrollIntoView({ block: "end" });
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
        className="fixed bottom-5 right-5 z-40 flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface)] px-4 py-2.5 text-[13px] font-medium shadow-lg transition-colors hover:bg-[var(--surface-hover)]"
      >
        <span aria-hidden className="text-[15px] leading-none">
          ?
        </span>
        Ask about this month
      </button>
    );
  }

  return (
    <section
      aria-label="Ask a question about this month"
      className="card fixed bottom-5 right-5 z-40 flex max-h-[76vh] w-[min(30rem,calc(100vw-2.5rem))] flex-col overflow-hidden shadow-2xl"
    >
      <header className="flex shrink-0 items-baseline gap-3 border-b border-[var(--border)] px-4 py-2.5">
        <h2 className="text-[13px] font-semibold">Ask about this month</h2>
        {/*
          The scope, named. The answers are computed from one reconciled run
          and nothing else, and a reader with several runs open needs to know
          which one is being described before they trust a figure.
        */}
        <span className="min-w-0 flex-1 truncate text-[11px] text-[var(--text-subtle)]">
          {scope}
        </span>
        <button
          type="button"
          onClick={() => setOpen(false)}
          aria-label="Close"
          className="shrink-0 text-[13px] text-[var(--text-subtle)] hover:text-[var(--text)]"
        >
          ✕
        </button>
      </header>

      <div className="min-h-0 flex-1 space-y-4 overflow-auto px-4 py-3">
        {thread.length === 0 && (
          <div>
            <p className="text-[13px] leading-relaxed text-[var(--text-subtle)]">
              Type any question about these books. Every figure comes back computed
              from the reconciled rows — nothing is written by a model. If the
              question cannot be answered from these files, it will say so rather
              than guess.
            </p>
            <ul className="mt-3 space-y-1.5">
              {OPENERS.map((opener) => (
                <li key={opener}>
                  <button
                    type="button"
                    onClick={() => void submit(opener)}
                    className="text-left text-[12px] text-[var(--accent)] underline underline-offset-2"
                  >
                    {opener}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

        {thread.map((exchange, index) => (
          <div key={index} className={index > 0 ? "border-t border-[var(--border)] pt-4" : ""}>
            <p className="text-[13px] font-medium">{exchange.question}</p>
            <div className="mt-2">
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
        <div ref={tail} />
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          void submit(question);
        }}
        className="flex shrink-0 items-center gap-2 border-t border-[var(--border)] px-4 py-2.5"
      >
        <label className="sr-only" htmlFor="ask">
          Your question
        </label>
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
          className="chip shrink-0 disabled:opacity-40"
        >
          {thinking ? "…" : "Ask"}
        </button>
      </form>
    </section>
  );
}
