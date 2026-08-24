# How Much AI Is Actually In This

An honest accounting, because the track is called "AI Finance Controller" and
this question will be asked.

---

## The honest split

By volume of work, deterministic code dominates. Roughly **5-10% of the system
is AI.**

| Genuinely AI | Deterministic |
|---|---|
| Triage of ambiguous exceptions | Matching (exact, tolerance) |
| **Rule induction** from human fixes | Subset-sum / N:1 solving |
| **Schema inference** on unknown files | Fee, GST, TDS, waterfall |
| **Root-cause induction** across clusters | Leak detection |
| Q&A tool selection + narration | Cash calendar, metrics, categorisation |
| Explanation writing | |

If someone called this "a rules engine with an LLM alongside", they would not be
wrong. **We say this out loud rather than hiding it.**

## Why that is the correct design here

Razorpay's own rubric: *"AI judgment — the right tool in the right place, and
**where you chose not to use one**."*

You do not write that sentence unless you are actively looking for restraint.

And the track name is **"AI Finance Controller"** — a finance controller that
uses AI, not an AI that does finance. Their "why now" says verification is the
bottleneck, and verification is deterministic by nature. You cannot LLM your way
to "these numbers balance."

**But that only protects us if the AI we do use is doing genuinely hard things.**

---

## CORRECTION: the Recon Agent was oversold

Earlier docs called strategy selection "genuine agency". If strategies run in a
fixed order — exact, tolerance, subset, fuzzy, give up — **that is a state
machine with a fancy name.**

**Fix: build both and benchmark them.**

| Mode | What it does |
|---|---|
| **Cascade** (baseline) | Fixed order, deterministic |
| **Adaptive** | Model reads the failure signature and picks the next strategy, or stops early |

Then report the difference. Either adaptive wins and we have a real agent, or it
loses and we report *"adaptive selection cost 3% accuracy and 40x latency, so we
shipped the cascade."*

**Both outcomes are strong. Guessing is not.** If we ship the cascade, we call it
a cascade, not an agent.

---

## THE BIG ONE: the LLM-matcher ablation

Do not *argue* that less AI is right. **Prove it with an experiment nobody else
will run.**

Build the thing everyone else is building — a naive LLM matcher — run it on
identical data, and publish:

| | LLM matcher | Our deterministic core |
|---|---|---|
| Accuracy | measure | measure |
| Speed | measure | measure |
| Cost | measure | Rs 0 |
| **Same answer twice?** | **No** | **Yes** |

**That last row is the kill shot.** An LLM matcher run twice on the same data
produces different books. In financial records that is disqualifying — and we can
demonstrate it live: run it twice, get two different reconciliations.

Our position then stops being "we used less AI" and becomes:

> **"We built the AI-heavy version, measured it, and here is exactly why we did
> not ship it."**

That is a bigger claim than the competitor's, because it contains theirs plus the
evidence against it.

**Cost: a few hours. Highest-leverage item remaining.**

### The honest caveat
If the ablation shows LLM matching is competitive, **we reconsider the
architecture.** Unlikely — models are bad at exact arithmetic and are
non-deterministic — but the experiment decides, not our priors.

### A structural problem for heavy-AI competitors
Razorpay's bar demands **measured accuracy**. A non-deterministic system gives a
different number every run. **Which number do they report?** They either pick a
favourable run (dishonest) or report a range (weak). We do not have that problem.

---

## What a genuinely brilliant heavy-AI competitor looks like

Being honest about what we are up against:

| Idea | Why it would be strong |
|---|---|
| **Unstructured input** — scanned invoices, PDF statements, email threads | **The strongest.** AI is genuinely irreplaceable when the input has no schema |
| **Code-writing agent** — writes Python to match two unknown files, runs it, iterates | Real agency, real 2026 pattern |
| **NL-defined pipelines** — "reconcile Razorpay against Tally, ignore under Rs 10" | Impressive, genuinely useful |
| **Semantic schema resolution** across different accounting systems | Hard problem AI actually solves |

**The honest reason we are not that:** we chose **structured inputs.** With a
clean CSV, AI genuinely is not needed for most of the work. **A project's
AI-heaviness is largely decided by how messy its input is.**

## So should we become that? Partly — and cheaply

**Add PDF bank statement parsing.** Not scanned images, not a whole document
subsystem — just **text-PDFs**, which is what most Indian bank statements
actually are.

Why this is the right slice:
- **Genuinely AI load-bearing.** Layout varies by bank; no deterministic parser
  generalises. This is real extraction work.
- **Realistic.** Merchants get PDF statements, not tidy CSVs.
- **Ground truth is free.** We render our own synthetic data TO PDFs, so we know
  the correct answer and can report **extraction accuracy** as a measured number.
- **Cheap.** pdfplumber plus an LLM for layout variance. Roughly half a day.

Scope: Tier 3 stretch. Text-PDFs only. If it slips, the CSV path is untouched.

## Drawbacks of being the heavy-AI competitor

They are real, and they are our advantages:

1. **Non-determinism is disqualifying in financial records.** Two runs, two sets
   of books.
2. **Cost scales with transaction volume**, not with exceptions.
3. **Errors are silent and unauditable.** A wrong match that balances is invisible.
4. **Correctness cannot be proven** — only demonstrated on cherry-picked cases,
   which Razorpay explicitly warned against.

A heavy-AI competitor can have an impressive demo and a system no finance team
would deploy.

---

## Video structure consequence

Make the **AI-judgment moments the most visible ones**:

1. The **ablation** — "here's the AI-heavy version, run twice, two different answers"
2. **Rule induction** — three examples in, a working rule out
3. **Root-cause induction** — "43 of your 71 exceptions share one cause"
4. **Schema inference** — unknown file in, correctly identified

Do not open on the deterministic pipeline. Open on the money question, then show
judgment where judgment happens.
