# LLM Choice

> **SETTLED: hybrid, and free-only for this build.**
> Local Ollama for development (unlimited, offline) - free API tiers
> (Groq / Gemini) for benchmarking and deployment - committed response cache so
> anyone can run the repo with no key, no GPU, no internet.
> Paid APIs are supported in code but **not used for this submission**.
> See `12-FREE-LLM-PLAN.md` for the free-tier detail and `14-DECISIONS-LOG.md`
> items 37-43.


## Where the LLM is actually used

Only three places. Everything else is deterministic code.

| Task | Volume per run | Latency | Needs |
|---|---|---|---|
| **Exception triage** — categorise + explain | ~300 calls | Not urgent | Structured output, consistency |
| **Rule proposal** — spot a pattern from human fixes | ~10 calls | Not urgent | Real reasoning |
| **Q&A narration** — answer a merchant question | Interactive | Fast | Quality, tool use |

Note the volumes. **~300 calls per 50,000 records**, because the deterministic
core handles everything else. That is the whole point of the architecture.

## Paid models — reference only, NOT used in this build

Kept here because the code supports them and Razorpay may want them in
production. **We spend nothing on this submission.**


| Model | Model ID | Context | Input $/1M | Output $/1M |
|---|---|---|---|---|
| Claude Opus 5 | `claude-opus-5` | 1M | $5.00 | $25.00 |
| Claude Sonnet 5 | `claude-sonnet-5` | 1M | $3.00 | $15.00 |
| Claude Haiku 4.5 | `claude-haiku-4-5` | 200K | $1.00 | $5.00 |

## The decision: benchmark it, do not guess it

Consistent with everything else in this project — **we do not pick a model by
vibes, we measure it.**

**Default in code: `LLM_PROVIDER=ollama`, `LLM_MODEL=qwen2.5:3b`.**

Run the triage benchmark across five configurations, **all free**, and publish:

| Config | Triage accuracy | Cost / 1,000 records |
|---|---|---|
| Off (deterministic categoriser only) | n/a | **Rs 0** |
| Ollama Qwen 2.5 3B (local) | measure | **Rs 0** |
| Ollama Qwen 2.5 7B (local) | measure | **Rs 0** |
| Groq Llama 3.3 70B (free tier) | measure | **Rs 0** |
| Gemini 3 Flash (free tier) | measure | **Rs 0** |

Then report **the smallest model that holds accuracy** — that is the finding.

Stronger than any single model choice, because it demonstrates the exact
judgment Razorpay grades: the right tool in the right place. And the whole
table costs nothing to produce.

## Three cost controls that come free

### 1. Response cache — the big one
Content-addressed cache on disk (`cache/llm/<sha256>.json`). Because our data is
seeded, prompts repeat exactly, so runs 2-50 make **zero** calls.
This is also our portability story — see `13-PORTABILITY-AND-DEPLOYMENT.md`.

*(If a paid API is ever used, the Batch API gives 50% off for non-latency-sensitive
triage. Results return in any order — key by `custom_id`, never by position.)*

### 2. Stable prompt prefix
The triage system prompt (categories, rules, the fee stack) is **identical
across every call.** Put stable content first, per-exception data last.

On Groq, **cached tokens do not count toward rate limits**, so this directly
stretches the free tier. On paid APIs it is a straight discount.

### 3. Structured outputs
Triage must return a strict schema (category, confidence, reason). Use
`output_config: {format: {...}}` and `strict: true` on tool definitions.

Not a cost control directly — but it removes retry loops caused by malformed
output, which are a real cost in practice.

## Local model option (Ollama)

Free, zero marginal cost, and gives Razorpay a deployment path with no API spend.

- **Primary: Qwen 2.5 3B** (~2GB at Q4) — fits fully in the 4GB VRAM
- Comparison: **Qwen 2.5 7B** (~4.7GB, partial CPU offload, slower)
- **14B and above will not fit 4GB VRAM** — do not attempt
- Expect lower triage accuracy — that is fine, we **measure and report** it

The point is not that the local model is as good. The point is that we can say:

> "Here is exactly what you lose by running it free."

## What we are NOT doing

**No fine-tuning.** Reasons in `08-TECH-STACK.md`: no training data, wrong task
shape, days of work, and it moves none of our headline numbers.

**No LangChain / LangGraph.** Our agent loop is bounded and simple. Hand-rolled
is ~100 lines and gives us the trace format the UI needs.

## Implementation notes

- **Two adapters only:** an OpenAI-compatible one (Ollama, Groq, Gemini,
  OpenRouter, OpenAI — differ only by `base_url`) and a native Anthropic one
  using the official `anthropic` SDK. Claude is never routed through a
  compatibility shim.
- Validate every response against a Pydantic schema. On parse failure: one
  retry, then fall back to `UNEXPLAINED` and log it.
- **Report parse-failure rate per model** in the benchmark table — small local
  models are less reliable at JSON, and that belongs in the numbers.
- If a paid Anthropic path is used later: `thinking: {type: "adaptive"}` for
  reasoning tasks, `output_config: {effort: "low"}` for classification, never
  `budget_tokens` (removed, returns 400), and always check `stop_reason` before
  reading content.
