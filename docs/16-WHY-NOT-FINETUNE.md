# Why We Are Not Fine-Tuning (and what to do instead)

This was seriously considered. It does not survive scrutiny — and the reason is
fundamental, not a matter of time or effort.

---

## The idea

Fine-tune a small model on our task, publish it (e.g. to HuggingFace), and ship
it with the repo so anyone can use it without their own API key.

## Step 1 — could we even get labels?

Fine-tuning needs thousands of examples: *"this exception is category X."*

Three possible sources:

| Source | Verdict |
|---|---|
| Hand-label thousands of examples | Not in 11 days, solo |
| Generate labels with a bigger LLM | **Circular.** We would be distilling another model, and our ceiling becomes its accuracy. Proves nothing |
| **Derive labels from the Chaos Engine's answer key** | **Actually works.** The generator knows the truth |

So yes — technically we *could* build a perfectly labelled dataset for free, at
any volume. That is a real option, not a fake one.

## Step 2 — the fatal flaw

Here is the problem.

> **If a label comes from a generator rule, then a rule-based classifier scores
> 100% on it.**

The Chaos Engine injects a rounding-drift defect and records `ROUNDING`. Our
deterministic categoriser checks "is the difference under Rs 1" and gets it right
every single time — instantly, with no model.

So a model fine-tuned on generator-derived labels would be **learning rules we
have already written in code.** It would be:

- Slower than the rules
- Larger than the rules
- Less accurate than the rules
- And impossible to defend at a panel

*"You trained a model to reproduce logic you already had?"* is a question with no
good answer.

## Step 3 — the argument in one line

Where the LLM genuinely earns its place in Milan is the **ambiguous residue** —
the exceptions the rules cannot categorise. But those are exactly the cases the
generator has no clean label for, because if it knew the answer, a rule would
already catch it.

> **The cases we can label are the cases we do not need a model for.**
> **The cases we need a model for are the cases we cannot label.**

That is why fine-tuning fails here. Not "too hard" — **structurally pointless.**

## Step 4 — what about fine-tuning for explanation quality?

Explanations and Q&A narration could in principle be distilled from a bigger
model. But:

- The quality ceiling is that bigger model
- Evaluation becomes subjective, which breaks our entire measurement thesis
- 2-3 days of the 11 we have, out of Tier 1 time
- A fine-tune that underperforms is worse than no fine-tune, and the days are gone

Not worth it.

---

## The goal behind the request is ALREADY solved

The real want was: *anyone who clones the repo should be able to use it without
getting their own API key.*

We have that, three ways over:

| Mechanism | What it gives |
|---|---|
| **Committed response cache** | Full LLM triage and explanations, zero setup, no key, no GPU, no internet |
| **Deterministic categoriser** | Complete reconciliation and all headline numbers with no model at all |
| **Provider-agnostic adapters** | Any free key (Groq/Gemini) slots in with one env line |

A published fine-tune would add **nothing** to this that we do not already have.

---

## The better idea: publish the DATASET instead

If we want a HuggingFace artifact — and it is a good instinct — publish the
**Chaos Engine dataset**, not a model.

**Why this is genuinely strong:**

- **Nobody has published a synthetic Indian settlement-reconciliation dataset
  with ground truth.** Not on HuggingFace, not on Kaggle. We checked the
  landscape — open source here is thin scripts and Excel exporters.
- It is a **real contribution**, useful to anyone working on this problem.
- It is **free for us** — we are generating it anyway.
- It makes our numbers **reproducible by anyone**, which is the entire thesis of
  this submission.
- It reinforces our position instead of undercutting it: we are the team that
  publishes the thing others can measure against.

**What to publish:**

```
milan-settlement-recon/
  clean/        orders, settlements, bank statement, answer key
  realistic/    same, with normal messiness
  hostile/      heavy defects, timing splits
  adversarial/  deliberately nasty + impossible-by-construction records
  README.md     schema, generation seed, defect rates, licence
```

Plus a datasheet: how it was generated, what each defect class means, the exact
seed, and what it must NOT be used for (it is synthetic — not real merchant data).

**Cost:** a couple of hours. **Tier:** 3 (nice-to-have, after Tier 1 holds).

---

## The honest forward-looking line (keep this for the video)

> "We are not fine-tuning today because we have no labels — and the labels we
> *could* fabricate are exactly the ones our rules already handle. The exception
> queue is how you get real labels. Six months of production resolutions across
> merchants, and a 3B fine-tune on genuine Indian settlement data beats anything
> general-purpose at this task."

Turns a limitation into a roadmap, and it is true.
