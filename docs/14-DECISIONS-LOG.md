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
55. **Schema inference promoted** — our most legitimate AI use. **SETTLED by 183-189: built.**
56. **PDF bank statement parsing** (text-PDFs) as a Tier 3 stretch. Genuinely
    AI load-bearing; ground truth free because we render our own data to PDF.
57. **Video leads with AI-judgment moments**, not the deterministic pipeline.

## Implementation (day 1, 25 August 2026)
58. **Money is integer paise everywhere; floats are rejected at runtime.**
    Rates are `Decimal`, and every rate application goes through one half-up
    rounding function. Half-up, not banker's — Python's built-in `round` would
    quietly disagree with the gateway by a paisa.
59. **`settlement_id` and `matchable` are separate fields in the answer key.**
    One is what is true, the other is what is knowable from the three files.
    Conflating them broke the oracle test on day one. See `18-BUILD-LOG.md`.
60. **A forced answer counts as a false positive even when it is right.**
    Guessing on an ambiguous credit is right about half the time, and
    rewarding the lucky half is how a coin flip comes to look like accuracy.
61. **Proving vetoes matching.** A credit the cascade claimed but the
    waterfall could not reconstruct to zero does not stay matched. It becomes
    an exception.
62. **The rounding allowance is derived, not picked.** `(taxed rows + 1) / 2`
    paise, because that is the widest gap the two roundings can legitimately
    produce. A fixed "within a rupee" would swallow real errors on small
    batches and reject real drift on large ones.
63. **`milan.recon` may not import ground truth.** Enforced by a test that
    greps the package, not by convention.
64. **The eval harness always runs the reference-only baseline.** A match rate
    with nothing to compare it against is not a measurement.
65. **The cascade is called a cascade in the code, not an agent.** Fixed
    sequence, no state, no planning. Consistent with decision 52.
66. **JSON, not Parquet, until volume demands otherwise.** Byte-stable for
    hashing, readable when a number looks wrong. Revisit at scale.
67. **`make` is a convenience, never a dependency.** Windows has no `make`;
    `uv run milan ...` is the real interface.
68. **A bank credit maps to a *set* of settlements, not one.** Banks merge
    transfers in the same window into a single NEFT line. Modelling one
    credit as one settlement would have defined away the case the matching
    design exists for. Supersedes the shape of decision 59: the answer key
    field is `settlement_ids`.
69. **The veto runs inside the cascade, not after it.** The waterfall solver
    is handed to the cascade as a verifier, so a claim that will not
    reconstruct is withdrawn and the credit falls through to the next rung.
    Strengthens decision 61: without this, a merged credit carrying one
    member's reference resolves confidently to the wrong settlement and never
    reaches the rung that could have found the pair.
70. **A settlement that fits alone is a competitor to a combination, not a
    weaker version of it.** When both explain a credit, subset-sum refuses.
    Preferring the combination because it is what that rung knows how to find
    would be the search choosing its own conclusion.
71. **A truncated search refuses instead of reporting its best find.** The
    subset-sum rung claims a match only on uniqueness, and a search that ran
    out of budget has not established uniqueness.
72. **The group's rounding allowance is the sum of its members', not a
    recomputation over the union of rows.** Each settlement rounds its GST
    once, so a group of three carries three roundings. Treating the group as
    one large batch would understate the allowance and turn honest drift into
    an exception. Follows from decision 62.
73. **Settlements per day is a difficulty knob, and it is not a defect.** A
    gateway settles on cut-offs and settles international cards separately.
    With one run a day a batch total is unique across the whole month, so
    amount-plus-date resolves nearly everything and its match rate measures
    nothing.
74. **The 1:N split settlement is deliberately not built.** It requires a
    partition solver rather than a rung, because no single credit proves a
    settlement. N:1 is the commoner case and fits the model, so N:1 is what
    exists. Recorded so the gap is a decision rather than an oversight.
75. **Unreported payments are found by reading the payments file, not by
    matching.** Every other technique starts from a bank credit and can only
    find money that arrived. This one is measured against `T+2`/`T+7` and the
    report's own horizon, never a clock read, so the answer does not change
    with when the run happens.
76. **Splink is cut from the plan.** Fuzzy narration matching would raise a
    number that three deterministic rungs already hold at 100% across every
    tier, volume and pricing model tested — including a fixed-price catalogue
    built specifically to break the amount fingerprint. Measured, then cut.
    The evidence is in `18-BUILD-LOG.md`; days 4-5 go to leak detection and
    property tests instead.
77. **A generator not producing a defect is not evidence the world lacks it.**
    Every accuracy figure Milan reports is an upper bound conditional on the
    defect catalogue being complete, and the catalogue is written by the same
    person as the matcher. Never argue from silence: "the cascade scores 100%
    without X" is a statement about the generator until X is generated. The
    defect catalogue ships with the submission so a reader can see the
    boundary of the claim rather than infer it.
78. **Section 194-O withholding is a merchant attribute, not a difficulty
    tier.** It lives on `RateCard`, not `DefectRates`. An e-commerce operator
    has 1% of gross withheld and a merchant selling their own goods does not;
    both are ordinary months. The reconciliation side is never told which and
    infers the withholding from the rows.
79. **"Reference damaged" and "reference absent" are separate defects.** A
    deleted reference announces itself. A damaged one still looks like
    evidence, defeats string equality completely, and is indistinguishable
    from a wrong reference without measuring similarity. Conflating them for
    two days is what made decision 76 unsupportable.
80. **Merging may consume any real payout, not only credits whose reference
    survived.** The earlier filter made merging pick off exactly the credits
    the first rung could resolve, so the baseline measured that filter rather
    than how often a bank keeps a reference. It went unnoticed because it
    lowered the baseline, and a lower baseline looked like the harder problem
    we wanted. A defect that flatters the story survives longest.
81. **There is no `ROUNDING` exception code.** Drift inside the derived
    allowance is explained as a named line inside the proof; a credit that
    reconstructs to zero has no exception to report. An exception code that
    nothing emits reads as a category the system supports.
82. **Decision 76 is withdrawn; Splink is open again.** The evidence for
    cutting it was gathered on a generator that could not produce the input it
    handles. Damaged references now exist and the amount rungs absorb them
    with no false positives — but only because amounts are reliable here. The
    deciding case is a damaged reference *plus* an ambiguous amount, which is
    not yet constructed. Until then Splink is unjustified, not unnecessary.
83. **Splink is cut — the library and, for now, the capability.** Two
    questions, both answered by measurement. The library is wrong for the
    shape of the problem: probabilistic record linkage with EM-learned match
    weights, aimed at comparing one damaged twelve-character reference against
    forty candidates in a date window. The capability is unneeded because in
    the one regime where amounts genuinely collide — a UPI-only, single-price
    merchant, where 11 of 29 batches share a total — every residual failure is
    a merged credit rather than a damaged reference, and one of them carries a
    perfectly intact reference. Narration similarity is not the missing
    evidence in any measured case. Supersedes decisions 76 and 82.
84. **A withdrawn claim keeps its evidence.** When the veto rejects rung one's
    match, the settlement it identified is currently discarded. It should
    become a constraint on the subset-sum search: a merged credit carrying
    member A's reference is a credit whose combination contains A. This is
    what the colliding-merchant measurement actually points at, and it is the
    next matching improvement rather than a fuzzy rung.
85. **The provider seam is built empty, before any model exists.** Interface,
    content-addressed disk cache, and a `NullProvider` that answers nothing.
    `none` is the default and a first-class implementation, not a placeholder:
    running the whole pipeline against it is what proves no graded figure
    depends on a model. Resolves the build order's own contradiction — its
    Tier 1 table says Ollama is day 2-3 and its sequence table says day 8 — by
    doing the part that has no model dependency now.
86. **The cache is content-addressed on the whole request.** Prompt, system,
    model, max tokens and temperature all enter the key, so changing any of
    them asks a new question instead of silently reusing an old answer. A
    cached run is a reproducible run for a reviewer with no key and no local
    model. Failures are never cached — caching an outage makes it permanent.
87. **Temperature defaults to zero and should stay there.** A reconciliation
    tool that answers differently on a second run is not reproducible, and
    none of this output is prose.
88. **Route, Smart Collect, QR pricing and instant settlement are deliberately
    deferred.** All real Razorpay pricing, all optional products a given
    merchant may not use, and all of them add more rates to a waterfall that
    already handles three — no new class of reconciliation problem. Instant
    refund fees are the exception and are queued, because a refund debit
    larger than the refund is a class nothing else in the system produces.
89. **Coverage is measured, and conformance is a test rather than a habit.**
    Two failure shapes produced every gap in the days 1-3 audit: implemented
    but never exercised, and computed but never surfaced. Both are mechanical,
    so `tests/conformance/` now asserts that every exception code is emitted by
    some tier, every rung produces a match somewhere, and every scorecard
    figure is rendered. A promise to be more careful does not scale; a failing
    test does.
90. **A credit can be identifiable and unprovable, and that is a third
    outcome.** `matchable` says the evidence singles the credit out;
    `provable` says the rows then reconstruct it. When a payout disagrees with
    the report, the correct answer is never a match - it is an exception naming
    the shortfall. Scoring counts those separately, because putting them in the
    match-rate denominator would penalise exactly the refusal this system
    exists to make.
91. **The veto starved the categoriser, and coverage found it.** Withdrawing
    unprovable claims inside the cascade meant the pipeline stopped seeing
    them, so every explained shortfall became a generic UNEXPLAINED. A
    withdrawn claim now keeps the settlement it identified, and the pipeline
    reconstructs it to explain the credit it could not prove. Extends decision
    69; supersedes the discarding behaviour it introduced.
92. **Triage checks run most-specific first, and the order is load-bearing.**
    A refund matches a shortfall to the paisa, a GST slab matches it to a
    published rate, a fee surcharge merely has to divide into gross at some
    small percentage - which almost any number does. Running the loosest check
    first had it answering for tax variances it had no business explaining.
93. **A deduction is only called GST when it implies a real slab.** 5, 12, 18
    or 28 percent of the fee charged. An arbitrary percentage that happens to
    fit is a coincidence, and naming it a tax variance attaches a statute to a
    number that has nothing to do with tax. Same principle as decision 61's
    rule for the TDS label.
94. **Variance kinds are cycled, not drawn at random.** A tier asking for three
    variances gets one of each rather than whichever the seed picked. A defect
    class that appears only on some seeds is tested only on some runs.
95. **Which payouts never arrive is decided before variances are placed.** A
    variance on a settlement nobody receives is unobservable, so the defect
    would be spent producing nothing and the tier would silently inject fewer
    than it claims.
96. **A refund row's debit column is the whole cash impact, charges
    included.** `credit - debit` has to stay the row's effect on the payout,
    or a batch appears to net more than it paid. The fee and tax columns then
    break out how much of that was a charge rather than money returned to a
    customer, which is what lets the proof show it on its own line.
97. **Instant refund charges get their own proof line.** Every other deduction
    in the waterfall scales with the transaction, so a few rupees adrift on a
    large batch reads as rounding. A flat Rs 7.99 does not scale: it is noise
    on a big refund and a real percentage on a small one. Folding it into
    "refunds recovered" would hide a charge inside a number the merchant reads
    as money returned to customers.
98. **`GatewayBatch.fee` and `.tax` mean the payment side only.** Summing every
    row's fee would both misreport the platform fee and double-count the
    instant charge, since the refund row's debit already contains it.
99. **The rounding allowance counts payment rows only.** A refund row's tax is
    GST on a flat charge, rounded once on that row, and never takes part in the
    per-row-versus-batch disagreement the allowance exists to cover. Including
    it widened the tolerance for no reason on any batch containing a refund.
    Follows from decision 62.
100. **Decision 83 is amended: the library stays cut, the rung is built.**
     Splink remains the wrong tool - EM-learned match weights across many
     comparison columns, for a problem with one column and a dozen candidates.
     But dropping Tier 1 item 5 because the *library* was wrong conflated two
     questions, and excluding FUZZY_NARRATION from the conformance check hid
     the gap. The rung is `difflib` over a normalised narration, runs last,
     and is measured.
101. **The similarity rung runs last and needs a decisive margin.** Everything
     reaching it has already failed the join key, the amount and the
     combination search, so it never overrides arithmetic. And a ranked list
     always has a top entry: without requiring the best to stand clear of the
     second, the rung would answer every time. The margin is what turns "most
     similar" into "identifiable".
102. **A rung that matches nothing is dead weight, and a test says so.** The
     fuzzy rung fired zero times when first wired in. The fix was to generate
     the defect it exists for - twin credits separable only by a damaged
     reference - not to excuse it. A test now asserts that removing it costs
     matches.
103. **Decision 84's anchor works but has not yet changed a tier number.**
     A/B on identical datasets showed no difference, because the remaining
     failures are merged credits with no reference to anchor on. The case
     where it decides is constructed directly in a unit test. Kept, proven,
     and honestly recorded as unmeasured at tier level rather than claimed as
     an improvement.
104. **"Unnecessary for the defects we generate" is not "unnecessary".** The
     measurement behind cutting the fuzzy capability was sound about its data
     and wrong about what that data covered. When a technique appears
     unnecessary, the first question is which real defect is missing from the
     generator. Same error as arguing from silence, one level up. Extends
     decision 77.
105. **A stored dataset must prove it is current before anything is scored
     against it.** `eval` loaded whatever was in `data/` and scored it. A run
     generated before the reference-twin defect existed was still there, and
     reported a baseline eight points from the published one with nothing on
     screen to suggest a problem. `save_dataset` now writes the config beside
     the data and `load_dataset` regenerates and compares digests. Refused,
     not warned about: a warning in a CLI that prints a table is a warning
     nobody reads.
106. **The command line gets no `--no-verify`.** The library keeps
     `verify=False` for inspecting a file by hand. A flag that lets you score
     a stale dataset from the terminal is a flag that gets used the first time
     regenerating is inconvenient, which is exactly the moment it matters.
107. **Published numbers are generated, never typed.** The README's refusal
     column had gone stale while its match rates stayed current - the kind of
     error no reader can catch. `milan eval --markdown` prints the table, the
     README holds it between fences, and a test fails when the two disagree.
     In a project whose claim is measurement, a wrong number in the README is
     the claim being wrong, not a documentation slip.
108. **The scorer is tested against hand-built reports.** Everything published
     comes out of `score()`, and until now nothing checked it - a scorer that
     counted a wrong match as correct would raise every figure at once with
     the whole suite still green. The stance the project argues for in prose
     is now enforced by tests: a lucky guess is a false positive, half a
     merged credit is not half a success, an unbalanced proof is not a claim.
     Found no bug. That is the expected result and not the reason to have it.
109. **A property test that has never failed is of unknown strength, so
     mutate the code and check it fails.** Three mutations, two caught. The
     third - widening the subset-sum tolerance by Rs 50 - passed, because the
     test built its targets as exact subset sums, and on an exact target a
     correct solver and a sloppy one return the same set. Rebuilt to perturb
     the target off the combination. A test that cannot fail is a comment.
110. **Noise stripping needs word boundaries, and similarity needs the full
     sweep.** Two live defects in the fuzzy rung, both found by asking whether
     a reference is similar to itself. `CR` was being stripped from inside
     `JMSS5NDW4CR`; and after boundaries were added, a bank label glued
     straight onto a truncated reference (`UTRRKBZWJLK`) left the narration
     shorter than the reference it contained, which a sweep sized from the
     reference length steps past. Both are real bank behaviour and neither
     produces a wrong answer - they lower a score, and a lower score looks
     like a hard case.
111. **mypy checks the tests too.** They construct the same models the engine
     does. An annotation that has drifted from a record's real shape is a test
     asserting something about a type that no longer exists.
112. **Splink is closed: measured, not needed.** Dropping the similarity floor
     from 0.78 to 0.45 and the margin to zero - "answer with whatever ranks
     top, always" - gains exactly zero records on any tier in either merchant
     shape. A more sophisticated comparison cannot beat one already allowed
     to answer unconditionally. And of the nine unresolved credits on the
     hardest shape, **none carry any narration evidence at all**: the bank
     sent no reference. The two that do score a perfect 1.00 and still fail,
     because their reference names one member of a merged set rather than the
     set. That is arithmetic, not string comparison. Recorded with its
     boundary: this says Splink adds nothing to the defects we generate,
     including the shape built specifically to break the amount rungs.
113. **A rejection-sampling loop is a hang wearing a distribution.**
     `_draw_amount` cost one over the acceptance probability, which is
     invisible on the default price window and total on a single-price
     merchant - twenty-two seconds and eleven million discarded draws for
     forty orders, and unbounded for a window the distribution cannot reach.
     Replaced with inverse-CDF sampling over the window. Same truncated
     lognormal, computed rather than searched for. When a distribution has to
     respect a constraint, put the constraint in the draw.
114. **The config that mattered most was the one the generator could not
     produce.** The single-price merchant is the only regime where the amount
     rungs genuinely fail, so it is the regime every claim about matching
     needs testing in - and it was the exact shape the sampler could not
     generate. A performance cliff on an unusual config is not a performance
     problem when the unusual config is the benchmark.
115. **`shortfalls named` was never a measurement at one seed.** Denominator
     of six per run, range 17% to 83% across twenty seeds. The README had
     published 5/6 and then 3/6 and both were noise. The honest figure is 55%
     of 120, and it is the weakest thing the system does: detection of a
     payout variance is 100%, explanation of it is 55%.
116. **Pool the counts, do not average the rates.** A run with six shortfalls
     and a run with two are not equally informative. Averaging their
     percentages says they are, and on this project's figures the two answers
     differ by enough to change what a reader concludes.
117. **A sweep runs the headline configuration only.** The ablation ladder is
     the whole point of a single evaluation and pure cost across twenty
     seeds. Skipping it takes the sweep to 1.4 seconds, which is what lets
     the README's pooled table be verified in the ordinary test run rather
     than in a slow lane nobody runs.
118. **The API is thin because a second implementation of the rules would
     drift.** Every decision worth making has been made in the engine. What
     the API adds is what the engine's own output cannot carry: an exception
     joined back to the record it is about, and a running total computed on
     the side of the wire that has tests.
119. **The answer key does not cross the wire, and a test greps for it.**
     `milan.recon` may not import ground truth; a JSON route serving it to a
     browser would walk around that boundary rather than break it, which is
     worse - nothing would fail. Scores are still reported, computed inside
     the evaluation package and never exposed record by record.
120. **Money crosses as integer paise, never a float, never a formatted
     string.** A test walks the whole payload at any depth. Formatting is a
     display concern, and sending "Rs 1,234.50" would make the number
     unusable for anything except printing it back out. The cost is that the
     browser has to do Indian digit grouping itself, which is why that
     formatter is held to the same table as `format_inr`.
121. **Listing runs does not verify them; opening one does.** A single stale
     dataset in the data directory made `/api/runs` return a 500, so the
     picker could not show the run the person needed to be told to
     regenerate. Metadata should survive what content cannot.
122. **`MILAN_WEB_ORIGIN` rather than a wider CORS allowlist.** `next dev`
     moving to another port is exactly the moment the temptation to open it
     appears. A per-machine addition is a decision; `allow_origins=["*"]` is
     a permanent hole that gets added during a hackathon and never removed.
123. **Ambiguity has two shapes and the queue was reporting the wrong one.**
     A credit fitting several settlements asks which payout arrived; several
     credits fitting one settlement asks which bank line is the payout. The
     collision resolver produced the second and the categoriser described the
     first, printing `fits 1 settlements equally well`. The grammar made it
     visible; the substance is that it sends somebody to the wrong file.
     `Attempt.contested_by` now carries the rivals.
124. **Every number was right and the sentence was wrong.** That defect had
     been in every run since the collision resolver was written, and no test
     looked at the sentence. Exception text is a deliverable of this project,
     not a log line, and it now has tests of its own.
125. **Loading state is derived, not stored.** The loaded run is held with the
     key of the run it belongs to. A slow response for a run the user has
     navigated away from cannot arrive last and win, and a spinner cannot be
     left on after a failure. React 19's lint rule caught the first version.
126. **The interface is dense on purpose.** Thirty-pixel rows, hairline rules,
     tabular numerals, colour only on state. Somebody reconciling a month is
     scanning a few hundred rows for the one that is wrong, and padding is
     rows they cannot see. The tech-stack doc's "must not look
     AI-generated" is a usability constraint, not a style note.
127. **Vulcan is a model, not a design system.** Razorpay's Vulcan is their AI
     payments foundation model, launched this month with NVIDIA and AWS. There
     is no Vulcan frontend. The thing that governs how Razorpay's product
     looks is **Blade**, their open design system - and Blade is the better
     reference anyway, because its tokens are published rather than guessed.
128. **Blade's tokens are transcribed, not approximated.** The greys are its
     `ashGray` scales, the blue is `azure`, state is `emerald` / `cider` /
     `crimson`, and they are written as `hsl()` because that is how Blade
     stores them. Approximating a design system by eye produces something that
     looks nearly right beside it, which is worse than looking different.
129. **The package is not a dependency.** One screen does not justify a
     component library and its styled-components runtime. What is borrowed is
     the language - scale, greys, and the way money is set - which is what
     makes the result belong beside a Razorpay dashboard.
130. **Money is set the way Blade sets it: ₹ small, rupees large, paise small
     and muted.** In a column of settlement values the rupees are what you
     scan and the paise are what you check. Equal weight makes the eye do the
     separating instead of the type.
131. **Nothing in the queue is truncated.** Modern Treasury's rule for their
     reconciliation dashboard is to show data "as explicitly and granularly as
     possible", and the first version clipped every exception summary to one
     line with an ellipsis - a direct contradiction of this project's own
     claim that the exception text is the deliverable. A case you cannot read
     is a case you cannot pick up.
132. **Three columns, not five.** Subject and date had columns of their own,
     and between them squeezed the summary to four wrapped lines and pushed
     the amount off the edge of the pane. They belong under the sentence they
     qualify.
133. **`format_inr` keeps saying "Rs", and the browser normalises it.** Making
     the engine emit ₹ raises `UnicodeEncodeError` on a default Windows
     console, and the CLI is a deliverable. The browser has no such limit, so
     the display layer swaps the one token - fenced by tests, including the
     strings it must not touch.
134. **Reasoning from a description of a reference is not reading the
     reference.** The first interface followed the written brief - "dense and
     precise, like a finance tool" - and produced thirty-pixel rows and
     uppercase micro-labels. Blade reads that same brief as generous rows and
     soft status pills, because the density that matters is information per
     row, not rows per screen. Blade publishes its tokens; there was never a
     need to guess.
135. **Component classes live in `@layer components`.** Unlayered CSS beats
     every layered rule regardless of specificity, so `.th { text-align: left }`
     silently won against the `text-right` utility on the amount column, and
     would have beaten any utility on any header cell. Inside the layer the
     utilities come after and win, which is what every Tailwind class in this
     project already assumed.
136. **A line that stands on the rows above it says so rather than reprinting
     them.** The fee is charged on the payments that settled and the GST on
     that fee, so three consecutive proof lines carried the same thirty ids.
     Printing them three times said nothing the first printing did not, and at
     1280px it pushed the drift line - the argument of the panel - below the
     fold.
137. **A column whose every row holds the same word is not a column.** The
     proved tab had `Status`, twenty-one rows of "Proved", under a heading that
     already said it. Which rung of the cascade resolved the credit varies, and
     showing that makes the cascade visible in the list.
138. **The detail pane opens the first case.** It is half the screen, and it
     held a sentence of instruction where the evidence goes. Derived from the
     view rather than stored, so it cannot race the three other paths that set
     a selection.
139. **Driving the interface finds what reading it cannot.** Eight defects
     survived a source review and two screenshots, and four of them only exist
     at a particular width or in a particular state - a header alignment
     decided by a cascade rule in neither file, chips that stack only when the
     pane is narrow, a command clipped only when it is long, a pane empty only
     before the first click.
140. **A model may propose; only arithmetic may conclude.** The LLM returns a
     typed claim naming a cause and a record that must already exist, never
     prose, and that claim goes through the same categoriser the rules use. A
     wrong proposal is discarded before anything is printed, which is what
     makes a model safe to consult at all.
141. **Diagnose before designing.** The number day 8 existed to move turned
     out to be two different failures under one name - 11 explanation misses
     and 43 matching misses - and the fix for the 11 was a tolerance the
     prover two modules away already had. A model was never the answer, and
     an hour of reading the failures said so before any of it was built.
142. **A tolerance may only be widened together with a uniqueness rule.**
     Matching a refund inside the rounding allowance closes 11 of 11 gaps; the
     same change without requiring the candidate to be unique would eventually
     name the nearer of two refunds and state a guess as a finding.
143. **The model's contribution is a number, not an adjective.** Qwen 2.5 3B
     agrees with the deterministic rules 19.5% of the time on a task where the
     answer is known, and invented 5 record identifiers in 41 proposals. That
     is measured with the model running, because inferring it from a model
     never switched on would be an argument from silence.
144. **The seal on the graded numbers is structural, not behavioural.** A test
     parses the imports of `recon`, `domain` and `chaos` and fails if any of
     them reaches `milan.llm`. Running the pipeline twice and comparing would
     only prove no model was consulted on that data.
145. **Read the measurement's own output for contradictions.** The ablation
     reported six disagreements and zero rejections in the same table, which
     cannot both be true, and an "identifiers invented" column that could
     never be non-zero because the guard threw away what it rejected. Both
     were bugs in the instrument, not the subject.

146. **Splink is cut because the evidence it consumes does not exist.** Of the
     43 credits that reach the end of the cascade unmatched, 0 carry a
     recoverable reference in their narration - the four narration forms are
     bank boilerplate, and the one that looks like a reference is an IFSC
     branch code. A linkage library infers from signal present in a field.
     There is no signal in this field. Not a judgement about the library.
147. **A rung may match on a total being wrong.** Every rung above treats
     exactness as the whole of the evidence, which makes a credit that is one
     settlement minus an unexplained deduction invisible to all of them -
     though it lands on the settlement date exactly and is short by a median
     of 0.31%.
148. **Its band is derived from the rate card, never tuned to the data.** The
     widest legitimate reduction is the worst card rate, plus GST on that fee,
     plus withholding where it applies. A tolerance fitted to the generator
     would be fitting to the defect catalogue that every accuracy figure here
     is already conditional on, which is circular.
149. **A rung that never survives proving still earns its place.** The
     shortfall rung's claims are withdrawn every time by design, so it cannot
     move the match rate, precision or the refusal count - and what it leaves
     behind turns "no settlement behind it" into "this is settlement A, short
     by exactly refund R". Measuring rungs by proofs alone called the most
     useful one in the queue dead.
150. **Match rate and attribution are two rates because they are two
     questions.** Match rate excludes unprovable credits deliberately; that
     exclusion left a credit failing *both* matching and proving scored only
     against explanation, with its matching failure unreported anywhere.
     Attribution puts them back and is the strictly harder number.
151. **A named shortfall carries the rung that identified it.** One named
     against a reference is a fact; one named against a settlement found
     nearby on the right date is an argument at 35% confidence. The queue
     presented both with equal authority until `UnprovenCredit` was given the
     strategy and confidence that `Proof` had carried from the start.
152. **Never index a measurement ladder by position.** `test_fuzzy.py`
     compared `cards[-2]` to `cards[-1]`; adding a fifth rung silently
     repointed it at two configurations it was never written about, and it
     failed for a reason that had nothing to do with fuzzy.

153. **A leak is found by reading a row against the contract, not against
     another row.** Every other check in this engine compares two records; this
     one compares a fee against the rate the row's own columns imply. It is the
     only finding that survives everything reconciling, which is exactly why no
     matcher can produce it.
154. **Precision on leaks is a higher bar than anywhere else in the project.**
     A missed leak costs a merchant money they were already losing; a false one
     sends them to their account manager to complain about an overcharge that
     never happened. An undercharge, a refund's flat fee, an international card
     at its contracted 3%, and a row with no method are all silent.
155. **The comparison is exact, with no rounding tolerance.** `apply_rate` is
     the same function the fee was computed with, so an honest row reproduces
     to the paisa. Slack would only hide the smallest leaks, which are the ones
     most likely to survive a human review.
156. **GST on an overcharge is reported separately from the overcharge.** It is
     real cash out of the account and it returns as input tax credit, so the
     permanent loss is the fee difference alone. Rolling it into the headline
     would overstate the harm by 18%, which is the same failure as
     understating it.
157. **Findings are grouped by the rate pair that caused them, ordered by
     money.** Forty-seven rows is a complete report nobody reads. Rows sharing
     a rate pair share a cause by construction, so no distance metric is
     involved - one would find the same groups less legibly and occasionally
     find others that mean nothing.
158. **Leaks are carried beside the exceptions, never among them.** An
     exception is something that did not reconcile. Every leak reconciled
     perfectly, and filing them together would bury the one finding that
     survives the books balancing. A test asserts no payment appears in both.
159. **Unreachable defensive code is deleted, not excused.** `_rate_of` guarded
     against a zero amount its only caller had already rejected. Correct dead
     code is the state that looks most like being careful while being untested
     by construction.

160. **Leaks get their own group in the navigation, not a third item under
     Review.** Review is about credits: what could not be resolved, and what
     could. Every row behind a leak reconciled to the paisa, so listing it
     beside the exceptions would suggest the reconciliation missed something.
     The heading has to say "Recover" before the count says anything.
161. **Rates cross the API already formatted; money never does.** Every amount
     is integer paise and the browser groups it Indian-style with its own
     tested code. A rate is not money, nothing in the browser multiplies by
     one, and sending `0.0215` would only give two implementations a chance to
     disagree about how to write `2.15%`.
162. **A rate with a zero denominator is shown as a dash, not as 0.0%.** The
     clean tier has nothing impossible in it, so the refusal rate is 0/0.
     Printing `0.0%` under "Refused" claims the system guessed at every hard
     case; the truth is that it was never asked one, and the card now names
     the denominator when there is one.
163. **The dead code a new consumer exposes is deleted, not kept for later.**
     Building the leak screen showed that `LeakTotal`, `total()`,
     `LeakCluster.describe()`, `ProofView.merged` and `Service.forget()` were
     read by nothing. Correct, tested, unreachable code is the state that
     looks most like being finished, and the honest response to finding it is
     `git rm`, not a comment explaining why it is still there.

164. **The cache keys on the model that will actually answer, not on the one
     the caller named.** Callers never name one - they ask a provider - so the
     key had no model in it and two models shared entries. The failure would
     have surfaced only as two identical columns in a size benchmark, which
     reads as a finding rather than a bug.
165. **Token counts are read from the provider's counters, never estimated.**
     A cost figure has to be checkable against a bill. Estimating tokens from
     characters would put a number in a table nobody could verify, which is
     the same failure as every other unmeasured claim here.
166. **A published price carries its source and the date it was read.** A rate
     is somebody else's claim, restated, and it goes stale. A secondary source
     is labelled as one rather than presented as the vendor's word.
167. **The reproducibility experiment runs without the cache.** Everywhere
     else a cached answer is what makes a run with a model reproducible. In
     `milan twice` a cache hit would prove the point by refusing to run the
     experiment, so `direct()` exists to build a provider with nothing in
     front of it.
168. **A rate with a zero denominator prints as a dash in every surface.**
     Established for the queue's refusal card and applied to the degradation
     curve the same day. Clean tiers generate nothing impossible and no leaks,
     and `0.0%` under those headings claims a failure at work that was never
     given.
169. **The ablation is asserted by replaying the committed cache, not by
     retyping it.** It is the one figure a reader cannot regenerate, because
     it depends on a model, a quantisation and a daemon. The answers are in
     the repository and a test replays all 110 with no model present, failing
     if one question misses.

170. **A provider is "ready" only if the model is still in the key's
     catalogue.** Both hosted defaults were retired by their vendors between
     being wired in and being run, and a key-presence check said yes to both.
     "A key is set" and "this will answer" are different questions, and the
     Ollama provider had already learned the local version of this lesson.
171. **A partially answered evaluation says so, loudly.** The first hosted run
     answered ten of a hundred and ten questions and printed a 2.7% agreement
     rate - a measurement of a rate limit wearing the model's name. Unanswered
     questions are scored as disagreements, which makes the published rate a
     floor, and the command now says which it is.
172. **Rate limits are waited out, not lost.** `post_json` retries a 429 and
     honours `Retry-After` up to ninety seconds. Off by default: a local
     daemon that refuses a connection will refuse the next one, and sleeping
     over that would turn "no model configured" into a slow run.
173. **The answer budget belongs to the model, not to the question.** 96
     tokens is generous for a 3B instruct model and truncates a reasoning
     model mid-thought, which is counted as an unanswered question. It is per
     run, defaults to the local value, and is part of the cache key.
174. **Thinking tokens are counted as output, because that is how they are
     billed.** Gemini reports them in a separate field. Counting only the
     visible answer would have understated a thinking model's cost by an order
     of magnitude, and it is not a coincidence that the error would have run
     in the flattering direction.
175. **The word "cascade" is now a measurement, not modesty.** Cut rule 9 made
     the vocabulary conditional on a benchmark that had never been run. It has
     been run. An adaptive matcher over the same rungs, the same verifier and
     the same scorer ties on three tiers, loses three attributions and three
     named shortfalls on the adversarial one, and costs 2.0x the rung
     attempts. The project keeps the less impressive noun because it earned
     it.
176. **The collision rule and the "keep the stronger failure" rule left the
     cascade.** Both are about whether a claim may be believed and neither is
     about which rung made it. A second control policy would otherwise have
     imported private methods off a class it does not extend, or grown its own
     copy - and a benchmark whose arms disagree about what a collision is
     measures the disagreement.
177. **A benchmark arm gets built to win.** The adaptive matcher was wrong
     three times in the direction that flattered the cascade: it skipped the
     similarity rung whenever no reference could be extracted, which is
     exactly that rung's case; it had no way to break a collision on evidence
     strength; and it never reconsidered a rung after losing one. Each cost it
     accuracy that would have been published as a fact about adaptivity. A
     strawman arm does not measure a policy, it measures the person who wrote
     it.
178. **The pipeline takes a `Matcher`, not a `Cascade`.** Typing the seam to
     the protocol is what lets the benchmark run its alternative arm through
     the same pipeline, the same prover and the same scorer. A benchmark that
     reimplements the pipeline for one arm is comparing two pipelines.
179. **A merchant attribute draws no randomness when it is switched off.**
     Instant settlement and Route both default to zero, and both check that
     before touching the stream. Drawing unconditionally shifts every later
     draw, which would silently change every dataset this project has
     published - at a setting that means "this merchant does not use the
     product". Caught by the counts moving at zero, where nothing should.
180. **A Route transfer is not a refund, and the proof says so.** Both are
     debits that reduce a payout by a principal plus a fee plus GST, so one
     code path could carry both and the arithmetic would still close. It
     would also tell a marketplace its Route commission was an instant refund
     charge. `EntityType.TRANSFER`, its own line, and the commission named
     with its rate.
181. **A rate with no citation does not get invented.** Instant settlement's
     timing is modelled and its fee is not, because the sourced pricing
     records the first and not the second. Every accuracy figure here is
     already conditional on the defect catalogue being honest; a made-up rate
     would make it conditional on a guess as well.
182. **Smart Collect and QR stay cut, on a sharper reason than before.** The
     original "more rates, no new problem" was half wrong about Route - the
     split was a new shape. It is entirely right about these two: a virtual
     account and a QR code change what a payment costs, not how it settles.
183. **Item 19 was skipped for four days, and that was the error.** Schema
     inference was Tier 2 and decision 47 explicitly protected it — "the
     watcher can be cut; schema inference stays" — while Tier 3's control
     benchmark was pulled forward ahead of it. The consequence was a system
     that could not read a merchant's own files at all: pointed at a folder of
     real CSVs it reported "nothing generated yet". Recorded because the
     failure was one of sequencing, not of design, and the plan had already
     said what to do.
184. **A model proposes the mapping; the values decide.** Same rule as
     `llm/triage.py`, applied to schema instead of to money. Every column a
     model names is profiled first, and a proposal whose values contradict it
     is rejected and recorded rather than weighed. The rejections are printed:
     a guard whose catches are never counted reports itself as never needed.
185. **Ambiguity never resolves itself.** A field two columns could be, or one
     only a model's guess supports, either stops the import (required) or is
     dropped with its cost stated (optional). It is never quietly assigned,
     because a wrong column here does not produce a wrong explanation, it
     produces a wrong balance — and a wrong balance looks exactly like a right
     one.
186. **Asking a model what a file *is* was circular, and was removed.** The
     first design asked "which of the four records is this?" and checked the
     answer against the header aliases. But the aliases are exactly what had
     just failed to place the file, so the check could only ever say no — and
     it did, on a bank statement the model had called a settlement report.
     Replaced by ranking the record kinds on how much of the file each one's
     *proposed mapping* can actually fill, which is a claim the values can
     verify independently.
187. **A record type a file cannot supply is not a candidate for it.** The
     question is not whether anything did map to each required field but
     whether anything could — is there a column here, under any name, whose
     values read as that kind. A GST invoice register has an id, an amount and
     a reference, which satisfies three of the four fields a payments file
     needs; what it has no column for is a date. That absence is checkable
     without asking anybody, and it is what keeps junk out of the folder.
188. **One column offered for two fields is not a mapping with a mistake in
     it.** Qwen 2.5 3B answered `igst_rate` for the credit, the debit and the
     tax of a GST register, and three plausible-looking assignments were enough
     to clear the placement bar. Keeping any one of the three would be
     picking. All of them are dropped and all of them are reported.
189. **The date format is a question, not a default.** `06-07-2026` is the 6th
     of July or the 7th of June, and only the column's own values can say —
     whether any date in it has a day past the twelfth. When none does, the
     import stops and shows both readings of a real value from the file. A
     parser that picked one and moved on would not be slightly wrong; it would
     be silently reporting a different month.
190. **The imported run is checked against the native one.** An imported
     reconciliation has no answer key, so one is manufactured: a generated
     dataset is written out as CSV in the shapes real exports arrive in — a
     bank's banner, `37,419.37 Cr`, `%d-%b-%Y` — read back through the full
     import, and compared proof for proof and exception for exception against
     the run the engine did from its own records. They match exactly. That is
     a stronger claim than "the import ran".
191. **The engine has a POST, and the line is worth writing down.** Until the
     import wizard, this API could only be read from - a page that got past
     the origin check could learn a merchant's settlement figures and nothing
     more. It can now stage an upload and delete a staged one. What it still
     cannot do is touch a stored run: no route writes to `data/runs`, and
     committing an import creates a new archive rather than modifying
     anything. The origin list stays as narrow as it was, and that is the
     control actually doing the work.
192. **An upload is not an import.** Files landing on disk changes nothing.
     A staged folder has a plan, that plan may have open questions, and until
     they are answered nothing is reconciled and nothing is archived. Closing
     the dialog deletes the upload, because a merchant who changed their mind
     should not leave their books in a staging directory.
193. **Fifteen identical clicks is not more consent than one reviewed batch.**
     The first wizard rendered every candidate column as an identical button
     and asked fifteen times. `Accept N suggestions` replaces that, and the
     contract survives intact: nothing is applied without a person agreeing,
     and what follows is the mapping table with every row marked `answered`
     and open to being changed. By the eighth question nobody is reading, so
     the long version was the less honest one.
194. **The collision rule applies to people too.** `coherent` policed a
     model's proposals and not a person's answers, which left the invariant
     breakable in three clicks - accept `paid_in` for the debit, then answer
     `paid_in` for the credit, and every settlement row comes out with its
     debit equal to its credit. An answer now clears any other field holding
     the same column, and that field goes back to being asked.
195. **Money first, and the two populations stay apart.** The first figure on
     this screen was `21/37` for six days. That is how a reconciliation engine
     thinks about a month, not how the person paying for one does. The
     headline is now what arrived, how much of it is proved, and - below a
     rule and in its own sentence - what was reported and never arrived. The
     second is never added to the first: a screen that summed them would show
     a total the merchant does not have.
196. **The navigation speaks the merchant's language and the panes keep ours.**
     "Exception queue" and "Charged above contract" are precise and they are
     our words, and their one-line explanations were `sr-only` - invisible to
     everybody who needed them. The sidebar now reads "Needs you", "Accounted
     for", "Overcharged", with the explanation on screen. The precise terms
     are the headings of the panes those items open, where somebody who has
     already decided to look is reading carefully.
197. **Match rate is on screen at last.** It was computed, carried in the API
     payload, and rendered nowhere for six days - while the card in that slot
     repeated a figure the headline now states in rupees. Razorpay's brief
     asks for a match rate by name.

198. **A merchant does not only have CSV, and pretending otherwise was our
     problem to fix.** The download button on a gateway dashboard gives a
     workbook; HDFC and ICICI both offer `.xls` above `.csv`; any file a
     finance team has opened has been saved by Excel. Asking for CSV was
     asking the merchant to convert their books before we would look at them.
     `.xlsx` and `.xlsm` are now read, **one table per sheet** - a real export
     puts settlements on one sheet and payments on another, and a reader
     taking the active sheet would import a third of the month, balance
     perfectly over it, and raise nothing.
199. **The header search was never about CSV.** Walking past a bank's banner
     rows is a problem about a grid of strings. `workbook` turns a sheet into
     that grid and everything below `_find_header` cannot tell the two apart,
     so supporting spreadsheets did not mean a second reader with its own
     subtly different idea of where a statement begins.
200. **Formats are diagnosed by content, not by extension, because banks lie
     about extensions.** ICICI's "Excel" download is an HTML table named
     `.xls`. A PDF decodes as text perfectly well and would import as one
     column called `%PDF-1.7`. Every refusal names what to do instead - the
     person holding a PDF statement is standing in front of a download page
     that also offers CSV, and that sentence costs them thirty seconds rather
     than an evening.
201. **PDF is refused rather than parsed, deliberately.** Table extraction
     from a PDF is inference about ink positions, and a misread column in a
     bank statement is a wrong balance that still foots. A system whose whole
     argument is that it refuses to guess cannot have its riskiest guess at
     the input boundary. The refusal is the honest answer, and every Indian
     bank offers the same statement in a format that is a table.
202. **Excel's floats stop at the boundary.** A cell becomes a decimal string
     exactly once, in `workbook.render`, and everything after it is `Decimal`.
     Six fractional digits rather than two, because this converts contracted
     rates as well as amounts and `0.0215` truncated to two places is a fee
     card that says 2% where the merchant pays 2.15%.
203. **Sample files are written in other people's dialects, and generated
     rather than committed.** Test data invented by whoever wrote the reader
     drifts toward the aliases the schema knows, and the confidence that
     follows is circular. `milan samples` imitates specific real exports - the
     trailing space inside ICICI's `Withdrawal Amount (INR )`, HDFC's
     `dd/mm/yy` and its `*** End of Statement ***`, Kotak's `Cr` suffix. On
     demand rather than in the repository, because a megabyte of settlement
     rows goes stale the first time the generator changes and a stale sample
     demonstrates a month this code no longer produces.
204. **Each sample folder's README is asserted.** A folder is a claim - "one
     question is asked", "this file is left alone with the reason printed" -
     and it is the first thing somebody new points Milan at. A README
     describing last month's behaviour is worse than none, because they will
     believe it and conclude the engine is broken.
205. **A weak placement may not block.** A hand-kept refund log has an amount
     and a date, which is two thirds of what an order book needs; it was
     placed as one, found no order id, and stopped the whole import until
     somebody answered a question about a file that was never an order book. A
     file placed on half its names, which then cannot answer something
     required, was guessed at rather than placed - so the placement is
     overturned and the file left alone, with `_placeable` still offering to
     be told otherwise.
206. **A folder import reports the formats it cannot read.** Skipping a PDF in
     silence is the worst outcome available: the merchant dropped a folder
     containing their bank statement, the run covered a month with no bank
     side, and nothing said why. Discovery picks up the four formats somebody
     could reasonably believe they had handed their books over in. Everything
     else - a logo, a `.DS_Store`, Excel's `~$` lock file - is skipped without
     a word, because reporting it would bury the line that matters.
207. **The explanation moved behind the question it answers.** Every figure on
     the screen needs a sentence to be trustworthy, each sentence was written
     beside its figure, and all of them were on screen at once. `Explain` is a
     `<details>` the width of its own question - closed by default, complete
     when opened, findable by in-page search either way. Cutting the sentences
     instead would have traded one failure for a worse one: figures with no
     provenance, on a tool whose argument is that it does not ask to be
     believed.
208. **"Not scored" was true and read as a demerit.** A score needs something
     to be measured against, and a merchant's books come with no answer key.
     Putting "not scored" on their files blames the files for a property of
     real data. The chip says what the run is - your books, or sample data -
     and an `Explain` gives the reason, alongside what an imported run *can*
     prove about itself: credits reconstructed to zero, exceptions refused,
     arithmetic drift. None of that needs anyone else to agree.
209. **A published rate carries its population.** `100.0%` sat above "21 of 37
     credits" - a rate and a denominator that contradict each other, because
     match rate excludes the credits that are impossible by construction. It
     is 21 of 21 resolvable. A rate without its population invites exactly one
     misreading and it is the flattering one, which is the lesson decision 187
     already learned about the refusal rate and this screen had not.
