# Build Order

## The timing reality

- **Today:** 25 August 2026
- **Deadline:** 5 September 2026
- **Days left:** 11
- **Working alone**

This is not a reason to cut corners. It IS a reason to build in the right order,
because the wrong order is what makes projects half-work.

## The method — thin slice first

**Day 1 goal: 50 records go in, match, one exception appears, one honest number
comes out.** Ugly, unstyled, but END TO END.

> **Day 1 uses NO LLM at all.** Not Ollama, not an API key, nothing.
> The deterministic pipeline plus the rule-based categoriser is the whole day-1
> slice. This is deliberate: it means an Ollama install or a GPU problem can
> never block the critical path, and it proves the no-LLM tier works from hour one.

After that, everything is *deepening* — never *integrating*.

Integration left until the end is the single biggest cause of half-finished
hackathon projects. We remove that risk on day one.

Note: 50 records is Razorpay's literal minimum. We clear their bar on day one,
then spend ten days making it excellent.

## The three tiers

### Tier 1 — must be excellent. Nothing else starts until these hold.

| # | Item | Notes |
|---|---|---|
| 1 | Chaos Engine | Synthetic data + ground-truth answer key + 4 difficulty tiers |
| 2 | Deterministic matcher | Exact ID, amount+date tolerance |
| 3 | Waterfall solver | Fee, GST, TDS, refunds, chargebacks, rounding |
| 4 | N:1 subset solver | With blocking to bound the search |
| 5 | Splink fuzzy layer | Narration -> invoice matching |
| 6 | Exception queue | The UI that carries the demo |
| 7 | Eval harness | Match rate, precision, refusal rate, WITH baselines |
| 8 | Property tests | Financial invariants |
| 9 | Reproducible run | Seeded, one command, same hash |
| 10 | **Deterministic categoriser** | Rule-based exception sorting. NO LLM. Tier 1, not a fallback |
| 11 | **Provider interface + response cache** | Thin adapter, content-addressed disk cache |
| 12 | **Ollama running locally** | Qwen 2.5 3B on the RTX 3050. Day 2-3, never day 1 |

### Tier 2 — earned, only once Tier 1 hits its number.

| # | Item |
|---|---|
| 13 | Leak detection (the big differentiator) |
| 14 | Root-cause clustering |
| 15 | LLM triage via Ollama + the free API adapters |
| 16 | Q&A agent with the no-arithmetic rule |
| 17 | Rule learning (human-approved) |
| 18 | Cash calendar (deterministic, not ML) |
| 19 | ~~Auto-ingest (watched folder)~~ + **schema inference** — **BUILT.** `milan import --from <folder>` reads a folder of the merchant's own CSVs, infers the schema, refuses what it cannot settle, and reconciles. The watcher itself is still uncut and still cuttable; the AI half is done |
| 19b | **Root-cause induction, LLM-assisted** (upgraded from deterministic clustering) |
| 20 | ITC / monthly tax invoice view |

### Tier 3 — only if genuinely ahead.

| # | Item |
|---|---|
| 21 | **LLM-MATCHER ABLATION** — highest priority in Tier 3. A few hours, huge payoff. Includes the "run it twice, two different books" demo |
| 21b | **Cascade vs adaptive Recon benchmark** — settles whether we have an agent |
| ~~21c~~ | ~~**PDF bank statement parsing**~~ — **dropped on purpose**, see decision 201. Excel workbook reading was built instead: it is the format merchants more often actually have, and it is a format rather than a picture of one. A PDF is now refused with the sentence that tells somebody to download the CSV their bank already offers |
| 21d | **LLM-off experiment** (free — the no-LLM path exists from day 1) |
| 22 | **Five-config benchmark** — off / Qwen 3B / Qwen 7B / Groq 70B / Gemini |
| 23 | **Agreement-rate metric** + golden-output test across configs |
| 24 | Cost: Rs 0 actual + projected paid-API cost |
| 25 | Full degradation curve across all four difficulty tiers |
| 26 | Dockerfile |
| 27 | Publish the Chaos Engine dataset to HuggingFace |
| 28 | Static demo deployed to Vercel / GitHub Pages |

**Note:** Tier 3 items are cheap and high-value. If forced to choose, do Tier 3
BEFORE finishing all of Tier 2. Items 16 and 17 take hours and are rarer than
anything in Tier 2.

## Rough sequence

| Days | Focus | LLM needed? |
|---|---|---|
| 1 | Thin end-to-end slice. 50 records in, a number out. Deterministic categoriser | **No** |
| 2-3 | Chaos Engine properly — tiers, injected defects, impossible records, **oracle test** | **No** |
| 4-5 | Matching core — deterministic, subset-sum, then Splink | **No** |
| 6 | Waterfall solver + eval harness with baselines + property tests | **No** |
| 7 | Exception queue UI (this carries the video) | No |
| 8 | **Ollama setup** + provider interface + cache + LLM triage | **Yes, first time** |
| 9 | Leak detection + root-cause clustering | No |
| 10 | **LLM-matcher ablation** + benchmark configs, agreement rate, degradation curve, README | Yes |
| 11 | Video, form, buffer | No |

**Note the LLM does not appear until day 8.** Everything Razorpay grades on is
deterministic and complete before then. If Ollama fights us, we lose a
nice-to-have — never the submission.

## Cut rules — decide these NOW, not under pressure

1. If Tier 1 is not solid by day 7, **Tier 2 gets cut without argument.**
2. The exception queue UI is never cut — it carries the video.
3. The eval harness is never cut — it IS the submission.
4. Q&A gets cut before leak detection. Leak detection is our differentiator;
   Q&A is on their example list and everyone will have one.
5. ITC view gets cut first of all. It is the nicest-to-have.
6. **If Ollama will not run, do not fight it.** Switch to a Groq free key
   (one env line). If that also fails, ship the no-LLM tier — every graded
   number is unaffected.
7. The five-config benchmark can shrink to three (off / local / one API) without
   losing the point.
8. **The LLM-matcher ablation is NOT cut.** It is a few hours and it is the
   single strongest answer to "why so little AI". PDF parsing was cut before
   it, and then cut entirely - see decision 201.
9. If the cascade-vs-adaptive benchmark is not run, **we call it a cascade**,
   never an agent. — **Run on day 11. It is a cascade.** Adaptive control ties
   on three tiers, loses on the fourth, and costs 2.0x the rung attempts. The
   name is now a measurement rather than a caution: `milan control`.

## Definition of done for each component

A component is done when:
- It has a test
- It runs from the seeded command
- Its numbers appear in the eval harness output
- It works with the LLM turned off (or degrades cleanly)

## The deliverables checklist

- [ ] Public GitHub repo, clean README with the numbers up front
- [ ] 5-minute video
- [ ] Google Form, 12 answers
- [ ] "What broke, and how you got out" — write this DURING the build, not after.
      Keep a running log from day 1. They read this field first.
