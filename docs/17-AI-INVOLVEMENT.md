# How Much AI Is Actually In This

An honest accounting, because the track is called "AI Finance Controller" and
this question will be asked.

---

## The honest split

By volume of work, deterministic code dominates. Roughly **5-10% of the system
is AI.**

| Genuinely AI | Built? | Deterministic |
|---|---|---|
| Triage of ambiguous exceptions | **yes** — `llm/triage.py` | Matching (exact, tolerance) |
| **Schema inference** on unknown files | **yes** — `ingest/propose.py` | Subset-sum / N:1 solving |
| Explanation writing | **yes** | Fee, GST, TDS, waterfall |
| **Rule induction** from human fixes | no | Leak detection |
| **Root-cause induction** across clusters | no | Cash calendar, metrics, categorisation |
| Q&A tool selection + narration | no | Column profiling and the ingest verifier |

The `Built?` column was added late and is the point of the table. Three of the
five planned AI-judgment tasks exist; two do not. A doc that listed all five
without saying which had been written would be describing an intention and
calling it a system.

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
| **Semantic schema resolution** across different accounting systems | Hard problem AI actually solves — **and now ours.** `milan import` maps a stranger's columns onto our schema, and every proposal is checked against the values before it can move a rupee |

**The honest reason we were not that:** we chose **structured inputs**, and
with a clean CSV, AI genuinely is not needed for most of the work. **A
project's AI-heaviness is largely decided by how messy its input is.**

**Partly corrected.** The fourth row above is now ours. Structured does not
mean *our* structure: a merchant's folder holds an HDFC statement with four
lines of banner above the header, amounts written `37,419.37 Cr`, and a column
called `Particulars`. Reading that is genuine judgment, and no alias list
generalises to the next bank. What we kept is the boundary — the model maps
columns, arithmetic still does the reconciling. See `docs/22-INGEST.md`.

## So should we become that? Partly — and this section argued for the wrong slice

**The original argument, kept because reversing it is the interesting part:**

> **Add PDF bank statement parsing.** Not scanned images, not a whole document
> subsystem — just **text-PDFs**, which is what most Indian bank statements
> actually are.
>
> - **Genuinely AI load-bearing.** Layout varies by bank; no deterministic
>   parser generalises. This is real extraction work.
> - **Realistic.** Merchants get PDF statements, not tidy CSVs.
> - **Ground truth is free.** We render our own synthetic data TO PDFs, so we
>   know the correct answer and can report **extraction accuracy** as a
>   measured number.
> - **Cheap.** pdfplumber plus an LLM for layout variance. Roughly half a day.

### Why that was dropped

Two of those four points do not survive contact with the thing they describe.

**"Ground truth is free" is circular.** A PDF we render ourselves has clean,
predictable layout, because we chose the layout. Real bank statements wrap a
narration across two lines, right-align an amount into the next column's box,
repeat a header at a page break, and change format between two months of the
same account. Extraction accuracy measured against our own renders would be a
high number that transfers to nothing — which is precisely the flattering
measurement this project refuses everywhere else. Measuring it honestly needs
real statements with hand-made keys, and that is not half a day.

**"Merchants get PDF statements" is true and does not lead where it looks.**
They get the PDF *and* a CSV or Excel download, on the same page, from every
major Indian bank. The merchant is one click from a file that is a table
rather than a picture of one.

And the risk is asymmetric in the worst direction. Everywhere else in Milan a
wrong answer announces itself: a batch that will not reconstruct becomes an
exception. **A misread PDF column is a wrong balance that still foots** — the
arithmetic closes, every downstream check passes, and the number is wrong. A
system whose entire argument is that it refuses to guess cannot put its
riskiest guess at the input boundary.

### What was built instead

**Excel workbook reading**, a sheet at a time. Less impressive to describe and
more useful to have: it is the format a gateway dashboard's export button
actually produces, it is a format rather than a rendering of one, and every
amount in it can be proved to come back to the paisa. See `docs/22-INGEST.md`.

A PDF now produces a refusal that says what to do about it, which is a worse
demo and a better product.

**If it is built later, the bar it has to clear:** extraction accuracy measured
against real bank statements with hand-made keys, published beside the number
of statements and banks it was measured over — never against PDFs we rendered
ourselves.

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
4. **Schema inference** — unknown file in, correctly identified, and one
   proposal visibly refused because the values contradicted it

Do not open on the deterministic pipeline. Open on the money question, then show
judgment where judgment happens.
