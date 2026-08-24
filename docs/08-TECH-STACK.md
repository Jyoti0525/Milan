# Tech Stack

## The full stack

### Engine (Python)

| Thing | Choice | Why |
|---|---|---|
| Language | **Python 3.11+** | The matching core needs real algorithms; Python has the libraries |
| API | **FastAPI** | Typed, fast, async. This IS our backend — not a CRUD layer |
| Models / schemas | **Pydantic v2** | Typed tool interfaces. Makes "the LLM can only call typed tools" real |
| Dataframes | **Polars** | Faster than Pandas, better memory behaviour at 50k+ rows |
| Storage / analytics | **DuckDB + Parquet** | Local, fast, no server. Also Splink's default backend |
| Fuzzy matching | **Splink** | Fellegi-Sunter probabilistic record linkage |
| Subset solving | **Ours (DP + blocking)** | See note below |
| Deps | **uv** | Fast, modern, reproducible lockfile |

### Testing

| Thing | Choice | Why |
|---|---|---|
| Tests | **pytest** | Standard |
| Property tests | **Hypothesis** | Financial invariants — the waterfall must always balance |
| Throughput | **pytest-benchmark** | Measured numbers, not stopwatch guesses |

### Frontend

| Thing | Choice | Why |
|---|---|---|
| Framework | **Next.js 15 + React 19 + TypeScript** | Standard, fast to build |
| Tables | **TanStack Table** | Dense, virtualised data grids — right tool for finance |
| Styling | **Tailwind, hand-built components** | See design warning below |
| Charts | **Recharts** | Degradation curve, exception trends |
| Numerals | **Tabular-figure font** (Inter + JetBrains Mono) | Numbers must align in columns |

### LLM layer

| Thing | Choice | Why |
|---|---|---|
| **Primary (dev)** | **Ollama — Qwen 2.5 3B** | Free, unlimited, offline, no rate limits |
| **Benchmark + deploy** | **Groq / Gemini free tiers** | No GPU, runs anywhere, still Rs 0 |
| **Portability** | **Committed response cache** | Repo runs with no key, no GPU, no internet |
| Paid (supported, unused) | Claude / OpenAI | Code supports it; we spend nothing |
| Interface | **Ours, thin** | Not LangChain/LangGraph — see note |
| Agent loop | **Hand-rolled** | ~100 lines, and we control the trace format |

> **Settled: hybrid, free-only.** Full detail in `12-FREE-LLM-PLAN.md`
> and `10-LLM-CHOICE.md`. Decisions 37-43 in `14-DECISIONS-LOG.md`.

### Repo layout

```
/engine     Python: chaos engine, matching, waterfall, agents, API
/web        Next.js: exception queue, settlement view, metrics
/data       Generated Parquet datasets (seeded, reproducible)
/docs       This plan
Makefile    make generate / make recon / make eval / make reproduce
```

## Model strategy — the important decision

### We are NOT fine-tuning a model (see `16-WHY-NOT-FINETUNE.md`)

The instinct (avoid API costs) is right. Fine-tuning is the wrong way to get there.

**Why fine-tuning fails here:**

1. **No training data.** Fine-tuning needs thousands of labelled examples. We would
   have to generate them with an LLM — circular, and weak evidence.
2. **Wrong task shape.** Fine-tuning helps with format adherence and narrow
   classification. Our LLM tasks are reasoning and explanation. It does not help.
3. **Time.** Dataset construction + training + eval is days. We have 11.
4. **It moves none of the numbers.** Match rate, precision and throughput all come
   from the deterministic core. A fine-tuned model changes none of them.
5. **Risk.** A small fine-tuned model that confidently mislabels an exception is
   worse than a good prompt on a strong model.

### The cost problem is ALREADY solved by the architecture

This is the key point.

The deterministic core handles 90-95% of records with **zero LLM calls**. The
model only ever sees the exception residue.

```
50,000 records processed
   ~300 exceptions
   ~300 LLM calls   (not 50,000)
```

Cost is tiny **by design**. That is not a happy accident — it is the reason the
architecture is shaped this way, and it is a selling point we should state out loud.

### What we do instead: model-agnostic, benchmarked

Put the LLM behind a thin interface with three swappable configurations, then
**run all three and publish the comparison:**

| Config | Triage accuracy | Parse-fail rate | Cost |
|---|---|---|---|
| Off (deterministic categoriser only) | n/a | n/a | **Rs 0** |
| Ollama Qwen 2.5 3B (local) | measure | measure | **Rs 0** |
| Ollama Qwen 2.5 7B (local) | measure | measure | **Rs 0** |
| Groq Llama 3.3 70B (free tier) | measure | measure | **Rs 0** |
| Gemini 3 Flash (free tier) | measure | measure | **Rs 0** |

This gets everything the fine-tuning idea was reaching for — zero-cost
deployment option, no vendor lock-in — at a fraction of the effort and risk.

And it turns an instinct into a **measured result**, which is exactly what this
whole submission is about. Almost nobody will have this table.

Note: Ollama local is free but needs hardware (~8-16GB RAM for an 8B model).
Fine on a dev machine; worth stating as a deployment requirement.

## Two build-vs-buy notes

### Splink — use it, for the fuzzy layer ONLY

Our problem is three problems needing three tools:

| Sub-problem | Tool | Why |
|---|---|---|
| Payment <-> settlement by ID | **Plain code** | Deterministic. No probability needed |
| Which orders compose this credit (N:1) | **Ours** | Subset-sum. Combinatorial, not record linkage. Splink cannot do it |
| Messy narration -> invoice | **Splink** | Genuine fuzzy linkage. Exactly its purpose |

Forcing Splink onto everything would be picking a tool because it looks
impressive. That is the failure mode Razorpay grades against. Applying "right
tool in the right place" to **libraries** as well as **AI** is a consistency we
can point at.

Why Splink over hand-rolling: Fellegi-Sunter is the canonical model, 2M
downloads, links a million records in about a minute, and it returns **match
probabilities** — which is what turns "precision over recall" into a *calibrated*
system instead of a slogan.

**Contingency:** it has a learning curve. It is Tier 1 so we hit it early. If it
fights us, fall back to a simplified Fellegi-Sunter scorer, which we will
understand by then.

### No LangChain / LangGraph

Our agent loop is bounded and simple: try strategy A, then B, then C, stop.
That is ~100 lines hand-rolled.

Reasons to hand-roll:
- We control the **trace format**, and the agent trace is a UI feature. A generic
  framework trace is worse for our purpose.
- One less dependency and one less abstraction between us and the logic.
- "We did not need a framework for this" is a defensible engineering position
  and fits the ethos of the whole project.

If asked why: because a bounded strategy loop is not a graph problem.

### Subset solver — ours first, OR-Tools only if needed

Start with dynamic programming + blocking to bound the candidate space.
Fast, explainable, fully ours.

If accuracy demands a proper constraint solver, **OR-Tools CP-SAT** is the right
escalation. Document the decision either way — subset-sum is NP-hard and saying
so, with our bounding strategy, shows more depth than hand-waving.

## Frontend design warning

**Must not look AI-generated.** Avoid:
- Purple/violet gradients
- Large rounded cards with generous padding
- Emoji headings
- Hero sections
- **Default shadcn/ui styling** — it is what most AI-generated apps ship, so it
  reads as AI-generated even when it is not

Finance tools should look **dense and precise**:
- Tight tabular data, small row height
- Tabular numerals, right-aligned figures
- Restrained colour, used only to signal state
- References: Stripe Dashboard, Linear, Mercury

## Reproducibility

- Seeded random generation
- `make reproduce` regenerates everything
- Identical output hash on re-run
- Pinned lockfile (uv)
