"use client";

/**
 * Ask this month a question, and get arithmetic back.
 *
 * The thing that makes this different from every chat box bolted onto a
 * finance tool is what it will not do. There is no model writing the reply.
 * A model — when one is configured at all — is given exactly one job, which
 * is deciding which of ten known questions was asked; every figure below the
 * headline is then computed from the reconciled report and carries the record
 * ids it came from. The worst a wrong reading can do is answer a different
 * question, visibly, with correct numbers.
 *
 * Which is why a refusal is rendered as a first-class reply rather than an
 * error state. "I could not tell which question that is" is the honest output
 * for anything this cannot compute, and a merchant who gets a confident
 * paragraph about the wrong month has no way to tell it from a right one.
 */

import { useState } from "react";
import { ApiError, type AnswerView } from "@/lib/api";
import { Amount } from "@/components/Amount";

/**
 * Openers, shown until the first question.
 *
 * Not decoration — an empty box gives no clue what a closed vocabulary
 * accepts, and somebody guessing at it will conclude the feature is broken
 * on their second refusal.
 */
const OPENERS = [
  "why was my payout short?",
  "am I being overcharged?",
  "what hasn't been settled yet?",
  "what's the biggest problem here?",
];

function Reply({ answer }: { answer: AnswerView }) {
  const refused = answer.intent === null;
  return (
    <div className="mt-3 border-t border-[var(--border)] pt-3">
      <p
        className={`text-[13px] leading-relaxed ${
          refused ? "text-[var(--warn)]" : ""
        }`}
      >
        {answer.headline}
      </p>

      {answer.lines.length > 0 && (
        <ul className="mt-2.5 space-y-1.5">
          {answer.lines.map((line, index) => (
            <li key={`${line.label}-${index}`} className="flex gap-3 text-[12px]">
              <span className="min-w-0 flex-1 leading-relaxed">
                {line.label}
                {line.detail && (
                  <span className="block text-[var(--text-subtle)]">{line.detail}</span>
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
        <ul className="mt-2 space-y-1">
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
        want to second-guess.
      */}
      {!refused && (
        <p className="mt-2.5 text-[11px] text-[var(--text-subtle)]">
          read as <code>{answer.intent}</code> by {answer.routed_by} · every figure
          computed from the report
        </p>
      )}
    </div>
  );
}

export function Ask({ onAsk }: { onAsk: (question: string) => Promise<AnswerView> }) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<AnswerView | null>(null);
  const [thinking, setThinking] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);

  async function submit(text: string) {
    const asked = text.trim();
    if (!asked || thinking) return;
    setThinking(true);
    setFailed(null);
    try {
      setAnswer(await onAsk(asked));
    } catch (error) {
      // A failed request is not a refusal and must not look like one. One is
      // the engine saying it cannot answer; the other is the engine not being
      // reachable, and telling somebody their question was not understood
      // when the server is down sends them to rewrite a perfectly good
      // question.
      setFailed(error instanceof ApiError ? error.message : "The engine did not answer.");
      setAnswer(null);
    } finally {
      setThinking(false);
    }
  }

  return (
    <section className="card px-4 py-3">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void submit(question);
        }}
        className="flex gap-2"
      >
        <label className="sr-only" htmlFor="ask">
          Ask a question about this month
        </label>
        <input
          id="ask"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Ask about this month — why was my payout short?"
          maxLength={500}
          className="min-w-0 flex-1 bg-transparent text-[13px] outline-none placeholder:text-[var(--text-subtle)]"
        />
        <button
          type="submit"
          disabled={thinking || question.trim() === ""}
          className="chip shrink-0 disabled:opacity-40"
        >
          {thinking ? "Working…" : "Ask"}
        </button>
      </form>

      {answer === null && failed === null && !thinking && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {OPENERS.map((opener) => (
            <button
              key={opener}
              type="button"
              onClick={() => {
                setQuestion(opener);
                void submit(opener);
              }}
              className="chip text-[var(--text-subtle)]"
            >
              {opener}
            </button>
          ))}
        </div>
      )}

      {failed !== null && (
        <p className="mt-3 border-t border-[var(--border)] pt-3 text-[13px] text-[var(--bad)]">
          {failed}
        </p>
      )}
      {answer !== null && <Reply answer={answer} />}
    </section>
  );
}
