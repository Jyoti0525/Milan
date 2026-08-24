# Portability and Deployment

## The question that matters

> A Razorpay judge clones our repo on a laptop with no GPU, no API key, and
> maybe no internet. **Does it run?**

If the answer is no, the repo is worth much less. "Build quality — does it run"
is one of their four grading criteria, stated in those words.

**Our answer must be: yes, always, on any machine.**

---

## Graceful degradation — three tiers

This falls straight out of our architecture. The deterministic core needs no LLM.

| What they have | What works | Command |
|---|---|---|
| **Nothing** — no GPU, no key, no internet | Full reconciliation, all metrics, leak detection, exception list, **cached LLM triage** | `make demo` |
| **+ a free API key** (Groq/Gemini) | + live triage on new data, + Q&A agent | set key in `.env`, `make recon` |
| **+ GPU with Ollama** | + all of the above, free and fully offline | set provider, `make recon` |

**Nobody is ever blocked.** The worst case still produces every headline number.

---

## The move that makes Tier 1 work: commit the response cache

We already planned a content-addressed LLM cache (`cache/llm/<hash>.json`) for
cost reasons. **Commit it to the repo.**

Because our data is seeded, the prompts are identical every run. So someone who
clones the repo gets the **full experience including LLM-generated triage and
explanations** — with no key, no GPU, no internet — because the responses are
already there.

- Size: ~300 exceptions x ~500 bytes = **~150KB**. Trivial for git.
- Honest and documented: the README states plainly that the cache holds
  responses from our run, and that deleting it plus setting a key regenerates
  everything from scratch.

This is the standard golden-file / fixture pattern. It is not a trick — it is
what makes our claimed numbers **checkable by anyone in one command.**

---

## Requirement this creates: the deterministic categoriser is Tier 1

For the no-LLM path to be genuinely useful, exception categorisation must work
without a model.

Most exceptions **can** be categorised by rule:

| Rule | Category |
|---|---|
| Difference < Rs 1 | `ROUNDING` |
| Difference matches a fee-rate delta | `FEE_DEDUCTION` |
| Difference matches a GST computation | `TAX_DEDUCTION` |
| Amount matches a known refund | `PARTIAL_PAYMENT` |
| No candidate found at all | `UNEXPLAINED` |

The LLM adds **explanation quality** and handles the genuinely ambiguous
residue — it is not doing the basic sorting.

So the deterministic categoriser is **Tier 1, not a fallback afterthought.**
It also gives us a real baseline to measure the LLM against.

---

## Deployment

### First, the scope guard

**Razorpay does not ask for a deployed app.** The deliverables are a public repo
and a 5-minute video. Deployment is a bonus.

**Do not let it eat Tier 1 time.** Everything below is Tier 3.

### Option A — Static demo (RECOMMENDED)

The engine already emits **static HTML reports** (that was the frontend risk
control). The exception queue browses **precomputed results**.

So the entire demo can be static:

- Run the pipeline offline, commit the outputs
- Host on **Vercel** or **GitHub Pages** — free forever
- No backend, no cold start, no compute cost, no key needed
- Loads instantly when a judge clicks the link

For a submission demo this is strictly better than a live app: nothing can be
down when they look at it.

### Option B — Live app (only if genuinely ahead)

| Piece | Host | Notes |
|---|---|---|
| Next.js frontend | **Vercel** free tier | Easy |
| FastAPI engine | **HuggingFace Spaces** free tier | Docker support, Python-native, free. No GPU |
| LLM | Groq/Gemini free key as a Space secret | No GPU needed on the host |

HuggingFace Spaces is the best free Python host for this. Render/Railway free
tiers spin down and cold-start slowly, which looks bad in a demo.

### Option C — Dockerfile

Ship a `Dockerfile` + `docker compose up`. Removes every "it doesn't run on my
machine" objection in one step. Cheap to add, high credibility, Tier 2/3.

---

## Should we develop locally on Ollama?

**Yes — and it genuinely costs nothing.**

| Question | Answer |
|---|---|
| Does Ollama cost money? | No. Free software, free model weights |
| Rate limits? | **None.** Unlimited calls |
| Internet needed? | No, works fully offline |
| Does it need a GPU? | Helps a lot. RTX 3050 4GB runs a 3B model comfortably |

Develop against **local**, benchmark against the **free APIs**, and verify the
**no-LLM path** works. All three, always.

The local path is also the honest basis for our product claim:
**Rs 0 marginal AI cost.**

---

## What the README must state plainly

1. The three tiers table above, at the very top
2. Exact commands for each tier
3. That the committed cache holds responses from our run
4. How to regenerate everything from scratch (delete cache, set key, one command)
5. The seed used for every reported number
6. Hardware used for the throughput numbers (so the timings mean something)
