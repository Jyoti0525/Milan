# Milan

**Settlement reconciliation that proves where every rupee went — and refuses to guess when it cannot.**

Razorpay AI Buildathon, Track 04 — AI Finance Controller.

---

## The problem

You run an online store. Last week you sold 100 orders worth Rs 95,000.
Today one deposit lands in your bank: **Rs 90,608.47**.

Two questions you cannot answer without opening a spreadsheet:

1. Which of my orders are inside this single deposit?
2. Where did the missing Rs 4,392 go?

At most Indian businesses, answering that is somebody's actual job, every week.

## What this does

Three inputs a merchant already has — the order book, the gateway settlement
report, and the bank statement — and one output: a complete, checked breakdown
of every bank credit.

```
Bank credit  Rs 90,608.47   (24 Aug)
 = 97 orders            Rs 95,000.00
 - Platform fee @2%     Rs  1,900.00
 - GST on fee @18%      Rs    342.00
 - refund  #4471        Rs    950.00
 - chargeback #2210     Rs  1,200.00
 - rounding drift       Rs      0.47   <- explained, not ignored
 = balances to zero
```

Every line points back at the source rows that justify it.

Most tools are **matchers** — they tell you what lined up. This is a **prover**:
a match that cannot be proved to the paisa is not reported as a match. It
becomes an exception, and the exception says what was missing.

## Status

Under active development for the 5 September 2026 deadline. The deterministic
engine, the exception queue and the model layer are built. No graded number
depends on the model, and that is now enforced by a test rather than promised
— see **Where the model earns its place** below. See
[docs/07-BUILD-ORDER.md](docs/07-BUILD-ORDER.md).

Measured numbers are published in the eval harness output and nowhere else.
No figure appears in this README that did not come out of a seeded run.

## Repository layout

| Path | Contents |
|---|---|
| [engine/](engine/) | Python: chaos generator, matching, waterfall solver, eval harness, API |
| [web/](web/) | Next.js: exception queue, settlement view, metrics |
| [docs/](docs/) | The plan, the money rules, the decisions log |
| `data/` | Generated datasets. Reproducible from a seed, never committed |

## Running it

The engine is a `uv` project. Everything is driven by one CLI.

```bash
cd engine
uv sync

uv run milan generate --seed 42 --difficulty realistic --orders 100
uv run milan recon
uv run milan eval
```

A `Makefile` at the repository root wraps the same commands for anyone who
prefers `make generate` / `make recon` / `make eval`. The CLI is the real
interface — the Makefile is a convenience, because `make` is not present on a
default Windows install and the project must not depend on it.

`recon` and `eval` refuse to run against a dataset this version of the
generator would not produce. A stored run is only meaningful because it is a
pure function of its seed and config; once the generator moves on, the file
still loads, still looks well formed, and describes a merchant the engine no
longer generates. So the config is written beside the data and checked on
load, and a mismatch tells you which command to re-run.

## Where it stands

Measured on 600 orders, seed 42, adversarial tier. Each row adds one rung, so
the gain over the row above it is what that rung is worth.

<!-- generated: eval -->
| Configuration | Match rate | Precision | Correct refusals | Shortfalls named |
|---|---|---|---|---|
| reference only (baseline) | 23.8% | 100.0% | 10/10 | 2/6 |
| + amount and date | 61.9% | 100.0% | 10/10 | 2/6 |
| + subset sum | 90.5% | 100.0% | 10/10 | 2/6 |
| + fuzzy narration | 100.0% | 100.0% | 10/10 | 3/6 |
| full cascade (+ shortfall) | 100.0% | 100.0% | 10/10 | 5/6 |
<!-- /generated -->

Four outcomes, not one. **Match rate** counts credits proved to the paisa.
**Refusals** counts credits that were impossible by design and correctly left
alone. **Shortfalls named** counts credits that are identifiable but *cannot*
be proved, because the payout disagrees with the report — for those the right
answer is never a match, it is an exception saying exactly what is missing and
why. The ones we cannot name lost their reference as well, so nothing could
identify which settlement was short; that is the correct output, not a miss.
This column is the weak one, and the section below says how weak.

The table above is printed by the command below rather than typed, and a test
fails if this file and a fresh run disagree. It is here because the numbers in
it were once retyped and quietly went stale.

Reproduce it:

```bash
uv run milan generate --seed 42 --difficulty adversarial --orders 600
uv run milan eval --seed 42 --difficulty adversarial --detail
```

### One seed is not a measurement

The table above is a single run, which is fine for the rungs — the match rate
moves by tens of credits and does not depend on which seed drew them. It is
not fine for the smaller figures. **Shortfalls named** has a denominator of
about six per run, and across twenty seeds it ranged from 67% to 100% while
everything else sat at 100%. Either end could have been published with a
straight face.

So the honest version pools the counts across twenty seeds rather than
averaging the rates, and reports the spread beside each figure:

<!-- generated: sweep -->
| Measure | Pooled | Of | Worst seed | Median | Best seed |
|---|---|---|---|---|---|
| match rate | 100.0% | 389/389 | 100.0% | 100.0% | 100.0% |
| settlement attributed | 98.0% | 499/509 | 92.3% | 100.0% | 100.0% |
| precision | 100.0% | 389/389 | 100.0% | 100.0% | 100.0% |
| refusal rate | 100.0% | 200/200 | 100.0% | 100.0% | 100.0% |
| shortfalls named | 91.7% | 110/120 | 66.7% | 100.0% | 100.0% |
| merged credits resolved | 100.0% | 120/120 | 100.0% | 100.0% | 100.0% |
| missing payouts flagged | 100.0% | 40/40 | 100.0% | 100.0% | 100.0% |
| unsettled payments flagged | 100.0% | 153/153 | 100.0% | 100.0% | 100.0% |
<!-- /generated -->

```bash
uv run milan sweep --seeds 20 --difficulty adversarial
```

**Naming a shortfall is the weakest thing this system does — 91.7%, not the
100% one seed would have shown.** Everything else holds at 100% across twenty
seeds: 389 credits matched with nothing wrongly claimed, and 200 impossible
credits refused without a single forced answer.

**Two rates, because there are two questions.** *Match rate* asks whether a
credit was reconciled, and its denominator excludes credits that are
identifiable but cannot be reconstructed — the right output for those is an
exception, not a match. *Settlement attributed* asks whether the engine worked
out which payout a credit was, and it puts those credits back in. It is the
strictly harder number and it is 98.0%.

That second row exists because a measurement gap was found by reading
failures rather than totals. **A credit that failed to match *and* was
unprovable was scored only against explanation**, where it looked like a
naming problem — its matching failure had nowhere to be reported. Pooled over
twenty seeds, 43 credits were in exactly that position: their bank reference
was corrupted, no candidate was ever found, and they surfaced as *"no
settlement behind it"*.

They are attributed now, by a fifth rung that matches on a total being
**wrong**. A credit that arrived on the settlement date, short by an amount
inside what a fee stack could account for, is evidence — just not exact
evidence, and every rung above treats exactness as the whole of the evidence.
The band is read off the merchant's rate card (worst card rate, plus GST on
that fee, plus withholding where it applies) rather than tuned against the
data, because a tolerance fitted to the generator would be fitting to the
defects we chose to write.

Its claims are then **withdrawn by the prover, every time, by design.** It
matches on the total being wrong, so nothing it touches can pass proving —
which is why adding it moved shortfalls named from 64.2% to 91.7% and left
match rate, precision and the refusal count exactly where they were. What it
leaves behind is the settlement id, and that turns *"no settlement behind it"*
into *"this is settlement A and it is short by exactly refund R"*.

Ten credits across twenty seeds are still unattributed: too far short for any
fee stack to explain, or short by an amount that fits two payouts equally
well. Those are refused, and refusing them is the point.

Add `--withholding` to the generate command for a merchant subject to Section
194-O, where 1% of gross is withheld before the payout leaves.

The 100% is worth less than the 23.8%, and the reason is written up in
[docs/18-BUILD-LOG.md](docs/18-BUILD-LOG.md): a settlement total turns out to
be a near-unique fingerprint once the fee stack is modelled properly, so this
class of matching is easier than it looks. What is hard is proving a credit to
the paisa, refusing the ones the evidence cannot settle, and finding money
that is wrong while everything still balances.

## The exception queue

Two halves of one honest answer. **Queue** is what could not be resolved, and
why — each case joined back to the record it is about, with what the engine
looked at before it gave up.

![The exception queue](docs/images/queue.png)

**Proved** is what could be, rebuilt line by line: the sale, every deduction
that happened to it, and a running total that lands exactly on what the bank
paid. Every line carries the source record ids behind it, so a finance team
can check it against their own export rather than take it on trust.

![A credit proved to the paisa](docs/images/proof.png)

The last row is the point. `Unexplained  0.00` is the claim this project
makes, stated so it can be checked rather than believed.

```bash
# terminal one
cd engine && uv run milan serve

# terminal two
cd web && npm install && npm run dev
```

Money crosses that API as integer paise and never as a float or a formatted
string; the browser does its own Indian-grouping arithmetic, tested against
the same table as the engine's. The API also refuses to serve the answer key —
a queue that can see the answers is a demo, and a test asserts it cannot.

The visual language is [Blade](https://github.com/razorpay/blade), the design
system behind the Razorpay dashboard. Its tokens are transcribed rather than
approximated, and money is set the way Blade sets it: the ₹ small, the rupees
large, the paise small and muted.

## Where the model earns its place

A local Qwen 2.5 3B runs through Ollama, with free Groq and Gemini tiers
behind the same interface. It is asked exactly one kind of question — *why is
this credit short?* — and it is never believed.

**A model may propose. Only arithmetic may conclude.** It does not return
prose. It returns a typed claim naming a cause and a record that must already
exist in the report, and that claim is then put through the same arithmetic
the rule-based categoriser uses. A claim that does not foot to the paisa is
discarded before anything is printed.

Which makes the model's contribution a number rather than an adjective. Over
the 77 shortfalls in twenty adversarial seeds, every one of which the
deterministic rules had already named:

| | Qwen 2.5 3B, local |
|---|---|
| questions answered | 77/77 |
| **agreement with the rules** | **19.5%** (15/77) |
| contribution beyond them | 0/0 — the rules named every shortfall the engine reached |
| proposals rejected by arithmetic | 26 |
| **identifiers invented** | **5** |

```bash
uv run milan ablate --provider ollama --seeds 20
```

Read the last two rows together. The model made 41 confident proposals; 26
were wrong, and **5 of them named a refund that does not exist anywhere in the
report**. Had it been allowed to write summaries, this system would have sent
a finance team looking through their ledger for records that were never
there. Every one of those was caught by arithmetic, cost nothing, and never
reached a screen.

The contribution row is 0/0 rather than 0%, and the distinction is the honest
one: there were no shortfalls left for the model to attempt, because the
deterministic checks now name every shortfall the engine reaches on all four
tiers. That is a measured result and not an assumption — it was measured with
a model actually running, because "the rules already win" inferred from never
switching one on is an argument from silence.

**The seal is structural.** `milan.recon`, `milan.domain` and `milan.chaos`
produce every published figure, and none of them may import `milan.llm`. A
test parses their imports and fails if one ever does, because a claim like
this is true when written and quietly stops being true nine commits later.

## Design stance

**Precision beats recall.** A wrong silent match corrupts a merchant's books.
A flagged exception costs a human five minutes. When the evidence does not
support an answer, the system says so.

That is not a slogan: the generator deliberately produces records that are
impossible to resolve, and the eval harness scores whether the engine correctly
refuses them. Forcing a match onto one is counted as a false positive, **even
when the forced answer happens to be right**.

**Proving beats matching.** A match is a claim; a proof is evidence. Every
claim is checked against the waterfall before it is accepted, and a claim that
cannot be reconstructed to zero is withdrawn — which is how a bank credit that
merges two payouts, and carries one of their reference numbers, avoids being
filed confidently against the wrong settlement.

## Documentation

Start at [docs/00-START-HERE.md](docs/00-START-HERE.md).
