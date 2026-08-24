# Decisions Log

Every settled decision, in one place, so nothing gets lost.
If a decision is not here, it is not settled.

## Track and framing
1. **Track 04 — AI Finance Controller.** Open Track ruled out by choice.
2. **Project name: Milan** (Hindi: matching / bringing together).
3. **One loop, many surfaces.** The loop is settlement reconciliation. Q&A, cash
   calendar and tax views are surfaces on it, not separate loops.
4. **Position as "settlement assurance", not reconciliation.** Not "did it
   balance" but "where is money leaking, and why".
5. **Never claim Razorpay overcharges anyone.** We inject discrepancies into
   synthetic data and prove detection. Stated explicitly in README and video.

## Architecture
6. **Deterministic code does the maths. LLM does judgment only.**
7. **Three agents only** — Recon, Triage, Q&A. Each genuinely decides something.
8. **No LLM router.** Deterministic dispatch when the UI already knows intent.
9. **Agency, if any, lives in matching strategy** — never in query routing.
   **AMENDED by 52:** a fixed strategy order is a cascade, not an agent. We build
   both and benchmark; if we ship the cascade we call it a cascade.
10. **The LLM never does arithmetic on money.** It narrates; it never calculates.
11. **Precision over recall.** A wrong silent match corrupts the books; an
    exception costs five minutes. When unsure, refuse.
12. **Rule learning is human-approved**, never silent auto-learning.
13. **The deterministic exception categoriser is Tier 1**, not a fallback.

## Data
14. **Chaos Engine** — synthetic generator with 4 difficulty tiers and a
    ground-truth answer key.
15. **Seeded generation.** Seeded means REPEATABLE, not easy. It is what makes
    our numbers checkable by Razorpay.
16. **Impossible-by-construction records** included, to measure correct refusal.
17. **Oracle test must score exactly 100.00%.** If not, the generator is broken.
18. **Freeze the generator by day 4. Version every dataset.**
19. **Money is handled as paise, in integers. Never floats.**

## What makes us different
20. **Leak detection at volume** — the headline. Errors that balance perfectly
    and are invisible below a few thousand records.
21. **Root-cause induction** — "43 of your 71 exceptions share one cause".
    **AMENDED by 54:** LLM-assisted, not deterministic clustering. Inducing a
    shared cause across heterogeneous evidence is genuine reasoning.
22. **Publish our own degradation curve** across all four difficulty tiers.
23. **Honest accounting of what is table stakes** (rule learning, hybrid
    architecture, grounding, human-in-loop) versus what is genuinely ours.

## Measurement
24. **Never report a bare number.** Always with baseline + published industry
    range (60-70% rules-only, 85-95% rules+AI).
25. **Precision on auto-matched outranks match rate.** Zero false matches is the
    real target.
26. **LLM-off experiment** — prove the core stands alone.
27. **Cost per 1,000 records**, reported.
28. **Property tests on financial invariants** (Hypothesis).
29. **"What this cannot do"** section in the README.
30. **Use the industry range to validate our DATA**, not just our system. If
    "Realistic" scores far above it, our data is too easy.

## Stack
31. **Engine:** Python 3.11, FastAPI, Pydantic v2, Polars, DuckDB + Parquet, uv.
32. **Frontend:** Next.js 15, TypeScript, TanStack Table, Tailwind hand-built.
    **No default shadcn look** — it reads as AI-generated.
33. **Splink for the fuzzy layer ONLY.** Plain code for ID matching, our own
    solver for N:1 subset-sum.
34. **No LangChain / LangGraph.** Hand-rolled agent loop, ~100 lines, because we
    control the trace format and the trace is a UI feature.
35. **Own subset solver** (DP + blocking). OR-Tools CP-SAT only if accuracy
    demands it.
36. **Interface-first for Splink** — ship a rapidfuzz implementation day 1 so
    Splink can never block us.

## LLM — HYBRID, settled
37. **Local Ollama for development.** Unlimited, free, offline, fast iteration.
    Qwen 2.5 3B on the RTX 3050 (4GB VRAM); compare against 7B.
38. **Free API (Groq / Gemini) for benchmarking and deployment.** No GPU needed,
    runs anywhere.
39. **Committed response cache for portability.** Anyone can run the repo with no
    key, no GPU, no internet.
40. **Provider-agnostic**: one OpenAI-compatible adapter (Ollama, Groq, Gemini,
    OpenRouter, OpenAI) + one native Anthropic adapter. Switching = one env line.
41. **No fine-tuning — structurally, not just for time.** The cases we can label
    are the cases rules already solve; the cases needing a model cannot be
    labelled. Full argument in `16-WHY-NOT-FINETUNE.md`.
41b. **Publish the DATASET to HuggingFace instead of a model.** Tier 3. Nobody
    has published a synthetic Indian settlement-recon dataset with ground truth.
42. **Batching applies to API tiers only** (local has no rate limits). Whether it
    costs accuracy is measured at batch 1 / 5 / 20, not assumed.
43. **Benchmark five configurations**, all free: off / Qwen 3B / Qwen 7B /
    Groq Llama 70B / Gemini Flash.
43b. **Every graded metric is deterministic and identical across all model
    configs.** The model only affects ambiguous-case categorisation and wording.
    Measure that with an **agreement rate** metric plus a **golden-output test**;
    never claim models behave identically. See `12-FREE-LLM-PLAN.md`.

## Portability and deployment
44. **Three tiers, nobody blocked:** nothing / free key / GPU.
45. **Static demo** on Vercel or GitHub Pages, browsing precomputed results.
    Live app on HuggingFace Spaces only if genuinely ahead.
46. **Dockerfile** for one-command reproduction.
47. **Auto-ingest (watched folder)** is Tier 2. **AMENDED by 55:** schema
    inference is promoted — it is one of our five genuine AI-judgment tasks, not
    a sub-feature of the watcher. The watcher can be cut; schema inference stays.

## Build discipline
48. **Day 1 = thin end-to-end slice.** 50 records in, one number out. Clears
    Razorpay's literal minimum on day one.
49. **Tier 1 / 2 / 3 with cut rules decided in advance.** Q&A gets cut before
    leak detection. ITC view is cut first.
50. **Keep a running "what broke" log from the first commit.** They read that
    field first and it cannot be reconstructed at the end.

## AI involvement (added after honest audit)
51. **State the AI split out loud: ~5-10%.** Hiding it is the only thing that
    would actually sink us. See `17-AI-INVOLVEMENT.md`.
52. **The Recon "Agent" was oversold.** Build cascade AND adaptive, benchmark
    them. If we ship the cascade, we call it a cascade.
53. **LLM-matcher ablation is mandatory, not optional.** Build the AI-heavy
    version, measure it, publish why we did not ship it. The "run it twice, two
    different books" demo is the kill shot.
54. **Root-cause clustering upgraded to LLM-assisted induction** — real
    reasoning, not narration.
55. **Schema inference promoted** — our most legitimate AI use.
56. **PDF bank statement parsing** (text-PDFs) as a Tier 3 stretch. Genuinely
    AI load-bearing; ground truth free because we render our own data to PDF.
57. **Video leads with AI-judgment moments**, not the deterministic pipeline.
