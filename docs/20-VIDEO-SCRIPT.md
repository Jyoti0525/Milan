# The five-minute video

One of two pass/fail deliverables, and the one that carries everything else.
The rubric reads *problem taste, build quality, AI judgment, failure
recovery*, so the script is built to hit all four — and to hit the third one
hardest, because "where you chose **not** to use a model" is the line most
submissions will not have an answer for.

**Nothing in here is a mock.** Every screen and every figure below is a
command that runs. If a number on screen disagrees with a number in this
script, the script is wrong and gets corrected — never the other way round.

---

## Before recording

```bash
# terminal one
cd engine
uv run milan generate --seed 42 --difficulty adversarial --orders 600
MILAN_WEB_ORIGIN=http://localhost:3000 uv run milan serve

# terminal two
cd web && npm run dev
```

- Browser at **1440×900**, zoom 100%, dark mode off, bookmarks bar hidden.
- Terminal at a large font — 16pt or more. A judge on a laptop cannot read 11pt.
- Close the Next.js dev-tools badge (bottom left) before recording the UI.
- Have `adversarial · seed 42` selected in the run picker.
- One take per section is fine. Cut between sections rather than restarting.

---

## 0:00 – 0:35 · The problem

**On screen:** the README's problem block, or a plain terminal.

> "You run an online store. Last week you sold a hundred orders worth ninety-five
> thousand rupees. Today, one deposit lands in your bank — ninety thousand, six
> hundred and eight rupees, forty-seven paise.
>
> Two questions you cannot answer without opening a spreadsheet. Which of my
> orders are inside this one deposit? And where did the missing four thousand
> three hundred and ninety-two rupees go?
>
> At most Indian businesses that is somebody's actual job, every week. This is
> Milan, and it does not answer those questions by matching. It answers them by
> proving."

---

## 0:35 – 1:20 · The proof

**On screen:** the workspace, **Proved** tab, click the top credit.

> "Three inputs a merchant already has — the order book, the gateway settlement
> report, the bank statement. One output: every bank credit rebuilt from the
> rows that make it up.
>
> The sale. The platform fee at two percent. GST on that fee. A refund that was
> netted out. And a running total that lands exactly on what the bank actually
> paid.
>
> The last row is the whole product. *Unexplained: zero point zero zero.*
>
> Most tools are matchers — they tell you what lined up. A match is a claim.
> This is evidence, and every line points back at the source rows behind it, so
> a finance team can check it against their own export instead of trusting me."

**Beat:** hover a proof line so the record-id chips are visible.

---

## 1:20 – 2:05 · What it refuses to do

**On screen:** switch to **Exception queue**. Let the 37 cases show, then open one.

> "The other half of an honest answer. Thirty-seven cases this run would not
> claim, sorted worst first.
>
> The generator deliberately produces credits that are *impossible* to resolve —
> the reference is destroyed, two payouts fit equally well. And the eval harness
> scores whether we correctly refuse them. Forcing a match onto one is counted
> as a false positive **even when the forced answer happens to be right**.
>
> Two hundred impossible credits across twenty seeds. Two hundred refusals. Not
> one guess.
>
> Because a wrong silent match corrupts a merchant's books, and a flagged
> exception costs a human five minutes."

---

## 2:05 – 2:50 · The money that is wrong while everything balances

**On screen:** **Charged above contract** in the sidebar. Open the finding.

> "Now the part no matcher can do.
>
> A domestic consumer card is contracted at two percent. The gateway charged
> two point one five. The settlement row foots. The batch foots. The bank credit
> reconciles to the paisa and the proof closes on zero.
>
> Nothing is unmatched, so nothing looks wrong. That is exactly why this
> survives in real merchant accounts for years.
>
> Two hundred and thirty-two rupees across forty-seven payments, in one pattern
> — not forty-seven line items nobody reads. One rate pair, one date range, one
> owner, and every payment id kept underneath so the claim can be checked.
>
> The GST is stated separately on purpose. It is real cash that left, and a
> registered merchant gets it back as input tax credit. Folding it into the
> headline would overstate the loss by eighteen percent — and overstating harm
> is the same failure as understating it.
>
> Seven hundred and sixty-two leaks across twenty seeds. All seven hundred and
> sixty-two found, and not one false accusation."

---

## 2:50 – 3:35 · Measured, not demonstrated

**On screen:** terminal.

```bash
uv run milan eval --seed 42 --difficulty adversarial
uv run milan curve --seeds 20 --orders 600
```

> "Every figure is scored against a generated answer key, so accuracy is
> measured rather than eyeballed.
>
> Each row adds one rung of the cascade, so the gain over the row above is what
> that rung is worth. Reference matching alone: twenty-three point eight percent.
> The full cascade: a hundred — at a hundred percent precision, with every
> impossible credit still refused.
>
> And across all four difficulty tiers, the two rates that move are the two
> where the evidence genuinely thins. Working out which payout a credit was
> falls from a hundred to ninety-eight. Naming why a payout came up short falls
> to ninety-two.
>
> Where a tier has nothing to score, it prints a dash rather than a flattering
> hundred percent. A rate over an empty denominator is not a measurement.
>
> Eighteen hundred records in twenty-eight milliseconds."

---

## 3:35 – 4:30 · Where the model earns its place

**On screen:** terminal, then the ablation table.

```bash
uv run milan ablate --provider ollama --seeds 20 --orders 600
uv run milan ablate --provider groq   --seeds 20 --orders 600 --max-tokens 512
uv run milan twice --seeds 6 --questions 30 --temperature 0.7 --no-pin
```

> "This is a track about AI, so here is the honest version.
>
> Four models — two local, two hosted — are asked exactly one kind of question:
> *why is this credit short*. And they are never believed. **A model may
> propose. Only arithmetic may conclude.**
>
> A hundred and ten shortfalls. A one-point-five billion parameter model agreed
> with the deterministic rules zero percent of the time. Three billion:
> sixteen. Gemini Flash Lite: twenty-eight. A hundred and twenty billion:
> thirty-six.
>
> Agreement doubles as the models get better. The bottom row does not move. Not
> one of them reached a case the rules had left open, and not one of them
> changed a number this project publishes — because they are asked *after* the
> arithmetic has already concluded.
>
> The three-billion model invented five identifiers: refunds that exist nowhere
> in the report. Had it been writing the summaries, this system would have sent
> a finance team through their ledger looking for records that were never there.
> Caught by arithmetic, cost nothing, never reached a screen.
>
> And this is why it does not get to decide. The same thirty questions, asked
> twice, nothing changed in between — sampling on, seed left to the daemon,
> which is what almost every LLM integration ships. Eleven of thirty answers
> moved. Four blamed a different refund the second time.
>
> Two different sets of books from one input. Milan's output does not move, and
> there is a command that proves it."

**If you have 20 spare seconds**, add: *"Both hosted models had been retired by
their vendors between being wired in and being run — so the tool now checks the
model against the key's live catalogue, not just that a key is set."*

## 4:30 – 5:00 · Close

**On screen:** terminal.

```bash
uv run milan reproduce --seed 42 --difficulty adversarial --orders 600
```

> "Same seed, same digest, every time. *Identical.*
>
> Five hundred and eleven tests, ninety-seven percent coverage. Every dataset is
> a pure function of its seed, so nothing is stored in the repository and
> anything on screen can be regenerated on your machine in one command — including
> the model's answers, which are committed so you can replay the ablation with no
> GPU at all.
>
> Milan. It proves where every rupee went, and it says so when it cannot."

---

## What to cut if it runs long

In this order:

1. The throughput line at 3:35 (nice, not load-bearing).
2. The degradation-curve half of section 5 — keep the eval ladder.
3. The hover-the-refs beat at 1:20.

**Never cut:** the `Unexplained 0.00` row, the refusal count, the leak
section, or the eleven-of-thirty result. Those four are the submission.

## What not to say

- Do not call it an agent. The cascade-vs-adaptive benchmark has not been run,
  and the build order's own cut rule says that until it is, this is a cascade.
- Do not say "100% accurate". Say what the denominator is: *a hundred percent
  of the credits that are matchable and provable*, which is what the README
  says.
- Do not claim the model helps. It measurably does not, and that finding is
  worth more than the claim would be.
