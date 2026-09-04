# The twelve answers

The application form asks for exactly twelve things and takes about fifteen
minutes. Six of them are about the person and only you can answer those; six
are about the build and they are drafted here.

Form: https://forms.gle/d9r2gvxp8cmoZhon9

Their own note on the last one: *"The last one is the one we read first."* It
is drafted longest for that reason.

---

## About you — yours to fill in

| # | Question | Answer |
|---|---|---|
| 1 | Full name | *(yours)* |
| 2 | College | *(yours)* |
| 3 | Graduation year | *(yours)* |
| 4 | In-person from September | *(yes / no — your call)* |
| 5 | 6 or 12 months | *(your pick)* |
| 6 | Resume file | *(upload — they take it and say they do not screen on it)* |

---

## 7 · Your track

> Track 04 — AI Finance Controller

---

## 8 · Project name

> Milan

---

## 9 · What it solves

*(One paragraph. The form does not ask for a pitch, it asks what it solves, so
this leads with the problem and not with the technology.)*

> A merchant sells a hundred orders worth Rs 95,000 and one deposit arrives:
> Rs 90,608.47. Working out which orders are inside it, and where the missing
> Rs 4,392 went, is somebody's actual job every week at most Indian businesses.
>
> Milan reconciles the three files a merchant already has — the order book, the
> gateway settlement report, the bank statement — and produces a checked
> breakdown of every bank credit: the sale, each deduction, and a running total
> that lands exactly on what the bank paid. A match that cannot be reconstructed
> to the paisa is not reported as a match; it becomes an exception that says
> what was missing.
>
> It also finds the money that is wrong while everything balances. A card
> contracted at 2% charged at 2.15% leaves a settlement report that foots, a
> batch that balances and a bank credit that proves to zero — nothing is
> unmatched, so no matcher can see it. Milan reads each row against the contract
> instead of against another row, groups the findings by the rate pair that
> caused them, and reports the GST separately because a registered merchant
> recovers that part.
>
> And it answers the other half of the track's own title — the cash position —
> without predicting anything. Money the merchant has already captured is dated
> by Razorpay's published settlement cycle and reduced by their own fee stack,
> so the output is a schedule of what is owed and when it is due rather than a
> guess at what is likely. Money that cannot be dated is reported as undated
> rather than given a date it did not earn, and asking Milan to *forecast* is
> still refused outright, with the schedule offered in its place.
>
> Accuracy is measured against a generated answer key rather than demonstrated
> on an example: across twenty adversarial seeds, 389/389 credits matched at
> 100% precision, 200/200 impossible credits correctly refused, and 762/762
> overcharges found with no false accusations. The schedule is marked the same
> way — built from one half of a month and graded against the half it was never
> allowed to read, where every date it gets wrong turns out to belong to money
> that never settled at all.

---

## 10 · GitHub repo URL, public

> https://github.com/Jyoti0525/Milan

**Check before submitting:**
- [ ] Repository visibility is **public**
- [ ] `main` is pushed and the README renders
- [ ] `uv run milan reproduce` still prints `Identical.` on a clean clone

---

## 11 · Five-minute pitch video

> *(unlisted YouTube link — record from [20-VIDEO-SCRIPT.md](20-VIDEO-SCRIPT.md))*

---

## 12 · What broke, and how you got out

*(They read this first. It is drafted long so you can cut, not padded so you
can fill. Every incident below is in [18-BUILD-LOG.md](18-BUILD-LOG.md) with
the commit that fixed it — pick three or four and cut the rest.)*

> **The oracle test failed, and it was right to.**
>
> Early on I wrote a test that hands the matcher the answer key and demands
> exactly 100%. If a matcher that has been given the answers cannot score
> perfectly, the bug is in the engine and not in the matching. It failed. The
> generator was rounding fees per transaction and GST once per batch — which is
> what actually happens — and my prover expected both to round the same way. The
> fix was not to loosen the test. It was to work out the exact allowance those
> two rounding rules can produce, `(taxed rows + 1) // 2 + 1` paise, and to
> report the drift as a named line rather than absorb it silently.
>
> **A feature that was fully built, fully tested, and had never run.**
>
> Section 194-O TDS — the 1% an e-commerce operator withholds — was implemented,
> unit-tested, and switched off in every difficulty tier. So no generated
> dataset ever contained a withholding row, and the entire statutory path was
> dead in integration while looking finished. For a submission to an
> India-specific finance track that was the most serious gap I found. It is now
> generated, and I wrote a conformance test that fails if any exception code or
> matching rung is never exercised by any tier, because "correct dead code" is
> the state that looks most like being done.
>
> **The number I published was measuring the wrong thing.**
>
> I reported "shortfalls named: 55%" and treated it as one weak measure. It was
> two failures wearing one name. Eleven were cases where the shortfall was found
> and the cause went unnamed, because that check demanded an exact match on a
> refund amount while the prover two modules away already treated the same paisa
> as rounding drift — one rule, stated two different ways. Fixing that took it to
> 64%.
>
> The other forty-three were worse: those credits never matched at all, because
> their bank reference had been destroyed. They were scored only against
> explanation — unmatchable credits sit outside the match-rate denominator on
> purpose, so their *matching* failure had nowhere to be reported at all. I added
> a fifth rung that matches on a total being **wrong**, and whose claims are then
> withdrawn by the prover every time by design, which turns "no settlement behind
> this credit" into "this is settlement A and it is short by exactly refund R".
> Shortfalls named went 64% to 92% with match rate, precision and refusals
> unchanged — and I added a strictly harder measure, *settlement attributed*, so
> that population can never be invisible again.
>
> **A UI bug that was invisible in both files that caused it.**
>
> The Amount column header sat left-aligned over right-aligned figures. The CSS
> looked right and the markup looked right. Tailwind v4 puts utilities in a
> layer, and unlayered CSS beats every layered rule regardless of specificity —
> so my component class silently won against the utility. Moving the block into
> `@layer components` fixed it. I only found it by driving the interface with a
> browser instead of reading the source.
>
> **The model measurement I published went stale and nothing could have told
> me.**
>
> Every number in my README is printed by the command it describes and asserted
> by a test, because I retyped a table once and it drifted. The one exception was
> the LLM ablation, because reproducing it needs a model. When I added the fifth
> rung, the population it measures grew from 77 shortfalls to 110 and the
> published agreement rate stopped being true. The fix was to commit the model's
> actual answers, addressed by the hash of each question, and write a test that
> replays all 110 with no model present and asserts the exact figures. A reader
> with no GPU can now reproduce the one table they otherwise could not.
>
> **The cache could not tell two models apart.**
>
> Found while benchmarking a 1.5B model against a 3B one. A caller never names a
> model — it asks a provider, and the provider uses whichever one it was built
> with — so the model was absent from the cache key and the second model silently
> replayed the first one's answers. The only place that surfaces is exactly the
> experiment the cache exists to make reproducible, and it would have surfaced as
> two identical columns that read like a finding rather than like a bug.
>
> **Both hosted models had been retired before I ever ran them.**
>
> I wired Groq and Gemini in behind the same interface as the local model, and
> tested both against recorded response bodies. When a live key finally arrived,
> neither worked: Groq answers `model_not_found` for the Llama 3.3 70B I had
> configured, and Gemini answers 404 for `gemini-2.0-flash` with a message
> naming its replacement. My `ready()` check said both were fine, because it was
> answering "is a key set" when the question people ask it is "will this
> answer". It checks the model against the key's live catalogue now — which is
> the same check my local provider already had, since a running Ollama daemon
> without the model is the failure people actually hit.
>
> **Then the first hosted run printed a number that was really a rate limit.**
>
> Groq answered 10 of my 110 questions and the tool reported *2.7% agreement*.
> That is worse than a crash, because a crash gets investigated and a percentage
> gets published. Its free tier is 8,000 tokens a minute, and every
> general-purpose model it now serves reasons for a few hundred tokens before
> answering, so the budget was gone after ten questions and the rest came back
> empty — indistinguishable, to a counter, from a model that declined. I added
> bounded retries on 429 that honour `Retry-After`, and — more importantly —
> made the command say *"3 of 110 went unanswered; they are scored as
> disagreements, so this rate is a floor, not an estimate."* The silent version
> of that sentence is how 2.7% got printed in the first place.
>
> **I built the agent version to check whether I needed one.**
>
> Everything here runs as a fixed cascade of five matching rungs, and I had
> been defending that in prose - my own build rules said that until an
> adaptive matcher was measured against it, I had to call this a cascade and
> never an agent. So I built the adaptive one: same rungs, same verifier, same
> scorer, and the only difference is that it chooses what to try next per
> record instead of running a fixed order.
>
> It never won. It ties on three difficulty tiers, loses three attributions
> and three named shortfalls on the hardest one, and asks the rungs for twice
> the work to get there. What makes it a finding rather than a null result is
> *why*: every repair the adaptive arm needed was me handing back something
> the fixed order supplies for free - a priority rule for collisions, a
> spent-rung block, repeated passes. Choosing per record destroys the global
> ordering that made choosing unnecessary.
>
> It also took three tries to stop that arm being a strawman, and all three
> failures happened to flatter the cascade. The worst skipped the fuzzy-match
> rung whenever no clean reference could be extracted, which is exactly the
> case that rung exists for. A benchmark whose losing arm was written to lose
> measures its author, so those three are in the build log rather than
> smoothed away.
>
> **What I did not build, and why.**
>
> I planned to use Splink, a probabilistic record-linkage library, for fuzzy
> narration matching. Before adding the dependency I isolated the population it
> would exist to rescue — the 43 credits that reach the end of the cascade
> unmatched — and read their bank narrations. All 43 have their reference
> destroyed, and the four narration forms that remain are boilerplate; the one
> that looks promising contains `RATN0000088`, which is an IFSC branch code and
> not a settlement reference. Recoverable references: 0 of 43. So Splink is cut,
> not because it is heavy but because **the evidence a linkage library consumes
> does not exist in the cases it would be asked to solve** — and that is recorded
> as a measurement with its boundary rather than as a preference. Same for the
> model: I measured what four of them contribute rather
> than assuming. Agreement with the deterministic rules rises with capability —
> 0%, 16%, 28%, 36% from a 1.5B local model to a 120B hosted one — and the
> contribution row is 0/0 in every column, because the rules already name every
> shortfall the engine reaches. The 3B model invented five record identifiers
> along the way. That is why a model proposes here and never concludes.

---

## Length

If the field is short, use these three in this order: **the oracle test**, **the
number that was measuring the wrong thing**, and **the rate limit that printed
itself as an agreement rate**. If there is room for a fourth, add **the agent
version that lost** - it is the only one that answers "why so little AI" with
a table instead of an argument. They cover all four rubric lines — build quality,
problem taste, AI judgment, failure recovery — in about two hundred words, and
the third one is the most quotable: *a crash gets investigated, a percentage
gets published.*

## Before you submit

- [ ] Repo public, README current, `main` pushed
- [ ] Video uploaded, unlisted, link tested in a private window
- [ ] Every figure quoted in answers 9 and 12 matches a fresh run
- [ ] Submitted before **5 September 2026**
