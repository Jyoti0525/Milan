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

Under active development for the 5 September 2026 deadline. The engine's
deterministic core is being built first; see [docs/07-BUILD-ORDER.md](docs/07-BUILD-ORDER.md).

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

## Where it stands

Measured on 600 orders, seed 42, adversarial tier. Each row adds one rung, so
the gain over the row above it is what that rung is worth.

| Configuration | Match rate | Precision | Correct refusals |
|---|---|---|---|
| reference (UTR) only | 32.1% | 100.0% | 8/8 |
| + amount and date | 78.6% | 100.0% | 8/8 |
| + subset sum | 100.0% | 100.0% | 8/8 |

Reproduce it:

```bash
uv run milan generate --seed 42 --difficulty adversarial --orders 600
uv run milan eval --seed 42 --difficulty adversarial --detail
```

Add `--withholding` to the generate command for a merchant subject to Section
194-O, where 1% of gross is withheld before the payout leaves.

The 100% is worth less than the 32.1%, and the reason is written up in
[docs/18-BUILD-LOG.md](docs/18-BUILD-LOG.md): a settlement total turns out to
be a near-unique fingerprint once the fee stack is modelled properly, so this
class of matching is easier than it looks. What is hard is proving a credit to
the paisa, refusing the ones the evidence cannot settle, and finding money
that is wrong while everything still balances.

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
