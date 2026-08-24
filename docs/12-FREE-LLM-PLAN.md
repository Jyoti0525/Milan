# Free LLM Plan (No Paid APIs)

Constraint: **zero spend.** Free tiers and local models only. Code stays
provider-agnostic so any paid key can slot in later.

---

## First: this is a STRENGTH, not a compromise

Do not present this as "we could not afford an API." Present it as the product
claim it actually is:

> **Milan reconciles 50,000 records at Rs 0 marginal AI cost.
> No API bill. Runs on a laptop.**

For a tool aimed at Indian SMBs — and for Razorpay, who would deploy it across
many merchants — **zero per-merchant AI cost is a real business advantage.**

Our benchmark table then reads *"here is what you gain by paying"* rather than
*"here is what you lose by not paying."* Same table, much better story.

---

## The two optimisations that make free tiers sufficient

Free tiers cannot handle 300 separate calls per run, repeated 30 times during
development. These two changes make the problem disappear.

### 1. BATCH the triage — 20x fewer calls  (API tiers ONLY)

**Important scope limit:** batching is needed **only for the free API tiers.**

Local Ollama has **no rate limits at all** — no RPM, no TPM, no daily cap. On our
primary config we make one call per exception if that is better. **Zero compromise.**

**Does batching cost accuracy?** Unknown, and we will not assert either way.
It might — attention splits across 20 items and reasoning can bleed between them.
It might not — this is a 5-way classification with a fixed output schema.

**So we measure it.** Run triage at batch size 1, 5 and 20 on identical data and
publish the accuracy difference. If batch-20 costs accuracy, use batch-5.
That result belongs in the benchmark table like everything else.


Do not send one exception per call. Send **20 exceptions per call** and get back
a structured array of 20 verdicts.

```
300 exceptions / 20 per call = 15 calls per run
```

15 calls fits inside every free tier listed below, comfortably.

Classification of 20 items in one call is entirely reasonable with structured
output. There is no accuracy reason to do them one at a time.

### 2. CACHE responses on disk — near-zero on re-runs

Content-addressed cache: hash the prompt, store the response.

```
cache/llm/<sha256-of-prompt>.json
```

Our data is **seeded**. The same seed produces the same exceptions produces the
same prompts. So:

| Run | LLM calls |
|---|---|
| 1st run | 15 |
| Runs 2-50 | **0** — all cache hits |
| After a generator change | only the new exception shapes |

**This is not a cost hack.** We already require reproducibility — same input
must give same output. The cache IS that requirement, implemented.

**Combined effect: development becomes effectively free.**

---

## Free options, ranked

### 1. Ollama (local) — PRIMARY

Genuinely unlimited. No rate limits, no daily cap, works offline, no key.

**Your hardware: RTX 3050 Laptop, 4GB VRAM, 15.7GB system RAM.**

| Model | Size (Q4) | Fits 4GB VRAM? | Verdict |
|---|---|---|---|
| **Qwen 2.5 3B** | ~2.0 GB | Yes, fully | **Start here.** Fast, plenty for classification |
| Llama 3.2 3B | ~2.0 GB | Yes, fully | Good alternative |
| Qwen 2.5 7B | ~4.7 GB | Partial offload | Try for quality comparison |
| Llama 3.1 8B | ~4.9 GB | Partial offload | Slower, ~10-20 tok/s |

Start with a **3B model.** Triage is a 5-way classification with a short reason
string — it does not need a big model. Compare against 7B and report the
difference.

**Hardware notes (measured on this machine):**

- **VRAM is separate from system RAM.** A 3B Q4 model (~2GB) loads into the 4GB
  VRAM and runs there. Low system RAM does not block it.
- GPU is idle and ready: `RTX 3050, 4096 MiB total, 0 MiB used, driver 581.95`
- **The Intel Iris Xe is not a usable second GPU** for this. It is integrated,
  shares system RAM, and has no meaningful Ollama/CUDA support. Ignore it.
- System RAM is tight (1.9GB available of 15.7GB). Likely cause: **Docker Desktop
  + WSL2**, which claims up to 50% of RAM by default. Quitting Docker and running
  `wsl --shutdown` when not in use should free several GB.
- If RAM stays tight, Groq/Gemini free tiers need **zero** local RAM. Not blocked.

### 2. Groq (free tier) — SECONDARY

| Limit | Value |
|---|---|
| Requests / minute | 30 |
| Tokens / minute | **6,000** <- the real constraint |
| Requests / day | 14,400 |

Very fast (LPU hardware). The daily cap is generous; **TPM is what binds.**

With batching: 15 calls x ~3,000 tokens = 45,000 tokens = about 7.5 minutes per
full run. Fine for a benchmark, too slow to iterate on — which is what the cache
is for.

Also: **cached tokens do not count toward Groq's rate limits**, so a stable
system prompt stretches the free tier further.

Models: Llama 3.1 8B, Llama 3.3 70B, Qwen 3, GPT-OSS 120B — all on the same limits.

### 3. Gemini (free tier) — TERTIARY

| Model | RPM | RPD | TPM |
|---|---|---|---|
| Gemini 3 Flash | 10 | 1,500 | 250,000 |
| Flash-Lite | 15 | 1,000 | - |
| Gemini 2.5 Flash | 10 | 250 | - |

Much higher TPM than Groq (250K vs 6K), but lower RPM. With batching, 15 calls
at 10 RPM is ~1.5 minutes per run. **Quota resets at midnight Pacific.**

Your worry was whether the free key can handle the volume. **With batching:
yes, easily.** Without batching: no. That is why batching is not optional.

---

## Will the API model behave the same as the local model?

**No, not identically — and it mostly does not matter.** Here is the split.

### Invariant across ALL model configs (deterministic — no LLM involved)

- Match rate
- Precision on auto-matched
- False match count
- Correct refusal rate
- Throughput
- Leak detection
- Waterfall, subset-sum, tax computation

**Every metric Razorpay grades on is in this list.** Swapping Qwen 3B for Gemini
moves none of them by a single digit.

### Varies by model

- Exception category on genuinely ambiguous cases
- Explanation wording
- Q&A phrasing

### Four controls that keep the variance small

1. **Structured output** — category is a 5-value enum, confidence a float,
   reason a string. Schema validation rejects anything else, so the *shape* of
   the answer is identical regardless of model.
2. **Committed response cache** — for the repo's dataset the outputs are frozen.
   A judge sees byte-for-byte what we saw. Zero variance on what is judged.
3. **Prompt controls style, not the model.** A tight format constraint
   ("one sentence, name the deduction, cite the record id") collapses most drift.
4. **One prompt, one schema, five backends.** Nothing is tuned per-model, so
   there is no local-only behaviour to lose when deploying.

### Turn it into a number: AGREEMENT RATE

Do not claim they match — measure it. Add to the benchmark:

| Comparison | Category agreement |
|---|---|
| Qwen 3B vs Llama 70B | measure |
| Qwen 3B vs Gemini Flash | measure |
| Rules-only vs Qwen 3B | measure |

If 3B disagrees with 70B on 12% of ambiguous cases, **that is a finding worth
reporting**, not a flaw to hide.

### Golden-output test

Freeze expected *categories* for a fixed set of exceptions. Any config must
reproduce them. Wording may differ; the decision may not. Catches drift in CI.

### What we can honestly claim

> "Every reported metric is deterministic and identical across all five model
> configurations. The model affects only how ambiguous exceptions are described
> and categorised — and here is the measured agreement rate between them."

Stronger than "it works the same", because it is checkable.

## Provider-agnostic design

One protocol, two adapters, everything configured by env var.

```python
class LLMProvider(Protocol):
    def complete(self, system: str, user: str, schema: dict) -> dict: ...
```

**Adapter 1 — OpenAI-compatible.** Covers Ollama, Groq, Gemini, OpenRouter and
OpenAI with nothing but a different `base_url`. All of them expose an
OpenAI-compatible endpoint.

**Adapter 2 — Anthropic native.** Uses the official `anthropic` SDK. We do not
route Claude through an OpenAI-compatible shim.

### `.env.example`

```
# Pick one: ollama | groq | gemini | anthropic | openai
LLM_PROVIDER=ollama

LLM_MODEL=qwen2.5:3b
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=

# --- Free options ---
# GROQ_API_KEY=
# GEMINI_API_KEY=

# --- Paid, for later ---
# ANTHROPIC_API_KEY=
# OPENAI_API_KEY=
```

Switching provider must be a **one-line env change**, never a code change.
That is also a defensible engineering point in the write-up: no vendor lock-in.

---

## What the benchmark becomes

Same table as planned, all free:

| Config | Triage accuracy | Cost / 1,000 records | Notes |
|---|---|---|---|
| Off (deterministic only) | n/a | Rs 0 | Proves the core stands alone |
| Ollama Qwen 2.5 3B | measure | **Rs 0** | Runs on a laptop |
| Ollama Qwen 2.5 7B | measure | **Rs 0** | Quality vs speed |
| Groq Llama 3.3 70B | measure | **Rs 0** | Free tier, big model |
| Gemini 3 Flash | measure | **Rs 0** | Free tier |

Five configurations, zero spend, and a real finding at the end: **which is the
smallest model that holds accuracy?**

That is a better result than "we used an expensive model and it worked."

---

## Structured output warning

Small local models are less reliable at emitting valid JSON.

Controls:
- Use the provider's JSON/structured-output mode where available
- Validate every response against a Pydantic schema
- On parse failure: one retry, then fall back to `UNEXPLAINED` and log it
- **Count and report parse-failure rate per model** — it belongs in the
  benchmark table, and it is exactly the kind of honest metric this project is about
