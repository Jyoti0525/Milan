# The Agents

## The decision we made

We are NOT building an LLM router that picks between five agents.

Reasons:
1. "Multi-agent orchestration" is the most common architecture claim of 2026.
   It is the opposite of unique.
2. Using an LLM to decide which agent to call, when the UI already knows what
   the user clicked, is exactly the waste Razorpay grades against.
3. Razorpay said "closes ONE finance-ops loop." Five agents reads as five
   half-loops.

Instead: **three agents, each of which genuinely earns the name**, sitting on
top of deterministic tools.

## Agent 1 — Recon Agent

**Decides:** which matching strategy to try next, and when to stop trying.

> **HONESTY CORRECTION.** A fixed order — exact, tolerance, subset, fuzzy, give
> up — is a **state machine, not an agent.** Calling it an agent would be
> naming doing work the implementation does not.

**So we build both and benchmark them:**

| Mode | What it does |
|---|---|
| **Cascade** (baseline) | Fixed strategy order. Deterministic. Fast |
| **Adaptive** | Model reads the failure signature, picks the next strategy, may stop early |

Then report the difference in accuracy, latency and cost.

- If adaptive wins, we have a genuine agent and the evidence for it.
- If it loses, we report *"adaptive cost X% accuracy and Yx latency, so we
  shipped the cascade"* — **and we call it a cascade, not an agent.**

Either outcome is defensible. Guessing is not. See `17-AI-INVOLVEMENT.md`.

## Agent 2 — Triage Agent

**Decides:** what category an exception belongs to, and what rule would fix it.

**Why it is a real agent:** categorising an ambiguous exception is judgment.
Proposing a reusable rule from a few human corrections is judgment.

## Agent 3 — Q&A Agent

**Decides:** which tools to call to answer a merchant's plain-English question.

**The hard rule that makes this ours:**

> **The LLM is never allowed to do arithmetic on money.**

Every number in every answer is computed by deterministic code and carries a
citation to its source rows. The model **narrates**; it never **calculates**.
If a figure was not computed by the engine, the system refuses to say it.

*"Milan will never tell you a number it made up."*

Most projects will pipe raw numbers into a prompt and let the model do the maths.
It looks fine in a demo and it is completely wrong.

## What is NOT an agent

These are deterministic tools. Calling them agents would be decoration:

- Fee and tax calculation
- Subset-sum solving
- Cash calendar projection
- Leak scanning (detection)
- ITC comparison

## Where AI genuinely earns its place

Five real judgment tasks — this is the list we must be able to point at:

1. **Triage** of exceptions the rules cannot categorise
2. **Rule induction** — three examples in, a working rule out
3. **Root-cause induction** — "43 of these 71 share one cause, and it is this"
   *(upgraded from deterministic clustering: inducing a shared cause across
   heterogeneous evidence is genuine reasoning, not narration)*
4. **Schema inference** — unknown file in, correctly identified and mapped
5. **Q&A tool selection** over free text

Everything else is arithmetic, and arithmetic belongs in code.

## How routing works

- **User clicked a button** -> deterministic dispatch, no LLM
- **User typed free text** -> Q&A Agent picks tools

Being able to say *"we route deterministically wherever the intent is already
known"* is a scoring sentence.

## Rule learning, explained simply

The system hits a bank line it cannot match:

```
NEFT-ACMECORP-4471
```

It gives up and puts it in the exception queue. You look and say "that's
invoice 4471." You fix it by hand.

It happens again. And again.

**Rule learning** = the system notices the pattern and asks you:

> "The digits after the last dash look like the invoice number.
>  Use this as a rule from now on?"

You approve. Next cycle, those match automatically. **The exception list shrinks
every run.**

Same idea as marking emails as spam — after a few, it learns.

**We use human-approved rules, not silent auto-learning.** In finance, a rule
that quietly learns wrong and then mis-matches money is dangerous. Approval is
the correct design here, not the lazy one.
