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
> Accuracy is measured against a generated answer key rather than demonstrated
> on an example: across twenty adversarial seeds, 389/389 credits matched at
> 100% precision, 200/200 impossible credits correctly refused, and 762/762
> overcharges found with no false accusations.

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
> model: I measured what it contributes rather
> than assuming, and it contributes 16% agreement, 47 arithmetically-rejected
> proposals and 5 invented record identifiers. That is why it proposes and never
> concludes.

---

## Length

If the field is short, use these three in this order: **the oracle test**, **the
number that was measuring the wrong thing**, and **the ablation going stale**.
They cover all four rubric lines — build quality, problem taste, AI judgment,
failure recovery — in about two hundred words.

## Before you submit

- [ ] Repo public, README current, `main` pushed
- [ ] Video uploaded, unlisted, link tested in a private window
- [ ] Every figure quoted in answers 9 and 12 matches a fresh run
- [ ] Submitted before **5 September 2026**
