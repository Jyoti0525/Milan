# Architecture

## The rule that shapes everything

> **Plain code does the maths. AI only does judgment.**

Razorpay grades on "AI judgment — the right tool in the right place, and where
you chose NOT to use one." So every component below is labelled.

## The flow

```
  Orders          Settlement report          Bank statement
     |                    |                        |
     +--------------------+------------------------+
                          |
                   [ 1. Normalise ]          no AI
                          |
                   [ 2. Match ]              no AI (mostly)
                    exact by ID
                    amount + date tolerance
                    N:1 subset solve
                    fuzzy narration  <------- Splink
                          |
                   [ 3. Waterfall solve ]    no AI
                    fee, GST, TDS, refunds,
                    chargebacks, rounding
                          |
              +-----------+-----------+
              |                       |
        MATCHED                  UNMATCHED
              |                       |
     [ 4. Leak scan ]         [ 5. Triage ]     AI here
       no AI (detection)         categorise
       finds balanced            explain
       but wrong                 propose rule
              |                       |
              +-----------+-----------+
                          |
              [ 5b. Root-cause induction ]   AI here
               "43 of these 71 share one cause"
                          |
                   [ 6. Surfaces ]
                    Q&A  |  cash calendar  |  ITC view  |  exception queue
```

## The six components

| # | Component | Job | AI? |
|---|---|---|---|
| 1 | **Chaos Engine** | Generate realistic synthetic data WITH the correct answers | No |
| 2 | **Matching core** | Exact -> tolerance -> subset-sum -> fuzzy | Splink only |
| 3 | **Waterfall solver** | Break a net amount into its deductions | No |
| 4 | **Leak scanner** | Find losses that balance but are still wrong | No (detection) |
| 5 | **Triage** | Categorise, explain, propose rules | **Yes** |
| 5b | **Root-cause induction** | Find the shared cause behind a cluster | **Yes** |
| 5c | **Schema inference** | Unknown file in, correctly identified and mapped | **Yes** |
| 6 | **Surfaces** | Q&A, cash calendar, ITC view, exception queue | Partly |

> **Honest split: roughly 5-10% of this system is AI.** We state that out loud.
> The five genuine AI-judgment tasks are listed in `04-THE-AGENTS.md`, and the
> full accounting plus the LLM-matcher ablation is in `17-AI-INVOLVEMENT.md`.

## Why the Chaos Engine matters most

It is component #1 for a reason. Because **we** generate the data, **we know the
correct answer for every row.** That is what makes our match rate an honest
measurement instead of a guess.

It generates data at four difficulty levels, and injects real defects on purpose:
broken IDs, refunds landing in later cycles, rounding drift, rate mismatches,
duplicate netting, and records that are **impossible to match by design**.

That last one lets us measure something almost nobody measures:
**does the system correctly give up instead of forcing a wrong answer?**

## The design stance

**Precision beats recall.** A wrong silent match corrupts the books. A flagged
exception costs a human five minutes. When unsure, the system must refuse.

## Non-negotiables

- Every match traces back to source rows
- The same input always produces the same output (seeded, reproducible)
- Re-running a cycle never double-counts
- The deterministic core works with the LLM switched off
