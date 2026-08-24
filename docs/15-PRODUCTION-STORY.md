# Production Story

Forget the jury. How would a real merchant actually use this, and where does the
model run?

---

## How models work RIGHT NOW (the mental model)

This is the piece that is easy to get confused about.

**A model is just an HTTP endpoint.** Nothing more.

| Config | What it actually is |
|---|---|
| Ollama local | A server process on YOUR machine at `localhost:11434` |
| Groq | A server on THEIR machine at `api.groq.com` |
| Gemini | A server on THEIR machine at `generativelanguage.googleapis.com` |

All three speak the same OpenAI-compatible shape. Switching between them is a
**`base_url` change** — that is the entire difference.

So "we are using a local model" just means: the HTTP endpoint happens to be on
your laptop. Nothing is special about it, and nothing about it is permanent.

---

## "Why can't we deploy a fine-tuned model on a server?"

**We can. It is entirely possible. It costs money — that is the only reason not
to right now.**

| Option | Cost | Notes |
|---|---|---|
| Rented GPU (AWS g5, RunPod, Lambda) | ~$0.30-1.50/hour | ~Rs 15,000-50,000/month if always on |
| Serverless GPU (Modal, Replicate) | Per second | Cold starts of 10-60s |
| HuggingFace Inference Endpoints | Paid | Dedicated, managed |
| Free GPU hosting | Does not exist for production | |

For a buildathon with zero budget, we cannot. **For Razorpay in production, this
is exactly what they would do** — and our provider-agnostic design means it is a
config change, not a rewrite.

---

## Why we are NOT fine-tuning — and it is "not yet", not "never"

The honest reason is simple:

> **We have no labels.**

Fine-tuning needs thousands of examples of "this exception is category X, and
here is the correct explanation." On day one we have zero. Generating them with
an LLM to train another LLM is circular and proves nothing.

### But here is the good part

**Our rule-learning feature IS the label collection pipeline.**

Every time a human resolves an exception in the queue, that is a labelled
example. Run this in production for six months across many merchants and you
accumulate hundreds of thousands of real, human-verified labels.

**Then** fine-tuning a small model becomes obvious, cheap, and genuinely better
than a general-purpose model — because it would be trained on real Indian
settlement data that no frontier model has ever seen.

That is a strong thing to say in the video:

> "We are not fine-tuning today because we have no labels. The exception queue is
> how you get them. Six months of production data and a 3B fine-tune beats
> anything general-purpose at this specific task."

It turns a limitation into a roadmap.

---

## How a real merchant would use it

### Today's version (what we build)
1. Merchant drops three files into a folder, or points the tool at them
2. Reconciliation runs
3. They review exceptions and resolve them
4. Rules accumulate; the exception list shrinks each cycle

### The mature version (what it becomes)

**No file uploads at all.**

```
Razorpay APIs  ──┐
(payments,       │
 settlements,    ├──►  Milan  ──►  Exception queue  ──►  Merchant
 refunds,        │      (runs automatically           reviews only
 disputes)       │       every settlement cycle)      what needs a human
                 │
Bank feed  ──────┘
(account aggregator
 or bank API)
```

- Runs **automatically on the T+2 cycle** — no one presses a button
- Merchant gets a notification: *"Settlement reconciled. 3 exceptions need review."*
- They open the queue only when something actually needs judgment
- Most weeks, they open nothing

**Razorpay already has most of this data.** Payments, settlements, refunds and
disputes are all in their system. That is what makes this a natural product for
them rather than a generic tool.

The **file-watching auto-ingest we are building is the on-ramp** — it is how a
merchant who is not yet API-connected gets value on day one.

---

## Where the model runs in production — and the crossover

Three options, and the right one depends on scale:

| Scale | Best choice | Why |
|---|---|---|
| Small | Hosted API (Claude / Gemini / Groq) | Pay per call. No infra. Cheapest below the crossover |
| Large | **Self-hosted open model on GPU** | Fixed monthly cost beats per-call. Data never leaves |
| Any | **Mostly no model at all** | Our architecture only calls it on the exception residue |

### The crossover is calculable

~300 exceptions per merchant per cycle. At 10,000 merchants that is **3 million
LLM calls per cycle.** That is well past the point where running your own GPU is
cheaper than paying per call.

Below a few hundred merchants, the hosted API wins. Above a few thousand,
self-hosting wins.

**Being able to state that crossover is product thinking**, and it costs us
nothing to say — the architecture already supports both.

### And the third row is the real point

Because the deterministic core handles 90-95% of records with **zero** model
calls, the LLM bill scales with **exceptions**, not with **transaction volume**.

A merchant doing 10x the transactions does not pay 10x the AI cost. That is an
architectural property, and it is worth saying out loud.

---

## Data privacy — worth one line

Settlement data is sensitive. The self-hosted and local options mean **merchant
financial data never leaves the merchant's infrastructure.** For an Indian
fintech with RBI data-localisation obligations, that is not a nice-to-have.

Our provider-agnostic design gives that for free.
