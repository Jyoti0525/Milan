# TODO — audited, not guessed

Written after auditing days 1-3 against
[07-BUILD-ORDER.md](07-BUILD-ORDER.md)'s own definition of done:

> A component is done when it has a test, it runs from the seeded command,
> its numbers appear in the eval harness output, and it works with the LLM
> turned off.

Several components pass three of those four and were being counted as
finished. They are listed below with the one they fail.

---

## First, the thing that governs everything else

**The generator is a model of reality, not a sample of it.** Nothing here
resolves that. A defect the Chaos Engine does not produce is not a defect the
world does not have — it is a defect we cannot see, and our numbers are silent
about it rather than reassuring.

This cuts against the project in one specific direction that has to be said
plainly: **every accuracy figure Milan reports is an upper bound conditional
on the defect catalogue being complete, and the defect catalogue is written by
the same person as the matcher.** A high score means "we handle what we
thought of". It cannot mean "we handle what happens".

The mitigations are partial and worth naming as partial:

1. Model defects from Razorpay's published behaviour and Indian statute, not
   from what is convenient to generate.
2. When a defect class is found missing, fix the generator *before* deciding
   anything about the matcher (see item 2 below — this rule was written
   because it was broken).
3. Report the defect catalogue in the submission so a reader can see the
   boundary of the claim rather than infer it.
4. Never argue from silence. "The cascade scores 100% without X" is evidence
   about the generator until X is generated.

---

## Status

**Every box on this list is now ticked.** Items 10 and 11 remain
deliberately deferred with the reasoning recorded, and the day-6 findings
below were added and closed in the same pass.

Items 1-5 and the P2 block are **done**. Item 6 (property tests) and item 7
(the provider seam) are **done**. Item 8 (Splink) is **decided: cut** — see
below. Items 9-11 are new, from a second and deeper audit against
[02-THE-MONEY-RULES.md](02-THE-MONEY-RULES.md).

---

## P0 — the current numbers are wrong or unverifiable without these

### 1. Section 194-O TDS has never run

`RateCard.tds_applies` defaults to `False` and no tier turns it on, so **no
generated dataset has ever contained a withholding row.** Confirmed: 0 rows
across all four tiers at 600 orders.

Everything downstream of that has therefore never executed against real data —
`_withholding()` in the waterfall, the statutory-rate check that decides
whether a deduction may be *called* TDS, and the "Unattributed per-transaction
deduction" fallback that exists to stop us labelling an unknown deduction with
a citation it has not earned.

It is unit-tested in `test_rates.py` and dead in integration. For a submission
to an India-specific finance track, the statutory withholding path being
untested end to end is the most serious gap found.

- [x] Add a tier or config flag that turns 194-O on
- [x] Confirm the oracle test still passes with withholding present
- [x] Confirm the "TDS" label appears only at the statutory rate, and the
      fallback label appears otherwise

### 2. "UTR corrupted" actually means "UTR deleted"

`_narration()` is binary: a perfect reference, or none at all. Real bank
narrations damage references — truncation, transposition, padding, a reference
split across fields, junk glued on. `ExactUtrStrategy` requires exact string
equality, so one transposed character is a total miss today and we have never
measured that.

This is a generator bug in its own right. It also invalidated the argument for
cutting Splink, which is why it is P0 and not P2.

- [x] Generate damaged-but-present references as a distinct defect class
- [x] Re-measure the baseline, then reopen the Splink decision with evidence

### 3. The deterministic categoriser's headline number is not printed

Tier 1 item 10. `Scorecard.rules_share` is computed and referenced nowhere —
`grep` finds zero call sites. It is the share of exceptions settled with no
model at all, which is the number behind every "we used AI here and not there"
claim in the submission.

Fails the definition of done on "its numbers appear in the eval harness
output".

- [x] Render `rules_share` in `scorecard_detail`
- [x] Same for `merged_rate`, `unreported_detection_rate`, `exception_rate` —
      all computed, none shown

---

## P1 — verification gaps

### 4. Persistence has no test

`milan recon` reads what `milan generate` wrote. If `save_dataset` /
`load_dataset` lost a field, every downstream number would be measured on
different data than was generated, and nothing would fail.

Checked by hand today: round-trips identically on all four tiers. Nothing
would catch a regression.

- [x] Round-trip test: `content_hash(dataset) == content_hash(reload(dataset))`

### 5. The CLI has no test

`cli/main.py` and `cli/render.py` are untested. A broken typer signature or a
renderer that raises on a merged proof would ship green.

- [x] Smoke test each command through typer's `CliRunner`

### 6. Property tests do not exist

Day 6 in the plan, so not overdue — recorded so it does not become overdue.
`tests/property/` is an empty package and Hypothesis is already a dependency.

- [x] Invariants: proof lines sum to the credit; deductions never exceed
      gross; `from_rupees` round-trips; batch net is the sum of its rows

---

## P2 — dead code, small

- [x] `ExceptionCode.ROUNDING` is never emitted. Drift inside the allowance is
      explained as a proof line, not raised — which is right, so the member
      should go rather than the behaviour change.
- [x] `total_pending()` has no callers.
- [x] `LedgerDirection` has no real use.
- [x] `AnswerKey.matchable_count` has no callers.

---

## Plan-level, needs a decision rather than code

### 7. The build order contradicts itself about Ollama

[07-BUILD-ORDER.md](07-BUILD-ORDER.md) Tier 1 item 12 says Ollama is
**"Day 2-3, never day 1"**. The rough sequence table in the same document puts
Ollama setup on **day 8**. Both cannot be right, and days 2-3 are now spent.

Tier 1 item 11 — provider interface plus content-addressed response cache — is
also unbuilt and also Tier 1.

The day-8 reading is the safer one and matches the stated principle that no
graded number depends on an LLM. But it leaves two Tier 1 items landing on a
single day, and the cut rules say Tier 2 is cut without argument if Tier 1 is
not solid by day 7.

Proposal: build the **provider interface and cache early and empty** — the
adapter, the disk cache, and a null provider — so day 8 is only "point it at
Ollama" rather than "design the seam". It is a few hours, it has no dependency
on any model running, and it removes the single-day risk.

### 8. Splink — the library is cut; the RUNG IS BEING BUILT

Two separate questions, and both are now answered on evidence rather than
taste.

**The library is the wrong tool regardless.** Splink does probabilistic record
linkage across datasets with many comparison columns and match weights learned
by EM. This problem is: compare one damaged twelve-character reference against
roughly forty candidate settlements inside a date window. That is a string
similarity lookup. Splink would bring a DuckDB backend, blocking rules and a
training step to a forty-row candidate set.

**The capability is not needed either, and this was measured.** Damaged
references now exist (item 2) and defeat exact matching completely. To find a
regime where the amount evidence *also* fails, a merchant shape was
constructed where batch totals genuinely collide: UPI-only, single-price,
which removes the fee variation that keeps totals apart. It works — 11 of 29
batches share a total with another.

In that regime the cascade does break, honestly:

| Tier | Reference only | + amount/date | + subset sum | Precision |
|---|---|---|---|---|
| realistic | 84.6% | 92.3% | 96.2% | 100.0% |
| messy | 71.4% | 81.0% | 85.7% | 100.0% |
| adversarial | 27.8% | 66.7% | **88.9%** | 100.0% |

Precision holds at 100% — it refuses rather than guesses, which is the design
working. But **every residual failure is a merged credit, not a damaged
reference.** One of them carries a perfectly intact reference. Narration
similarity is not the missing evidence in any measured case.

**What the measurement points at instead:** when rung one's claim is withdrawn
by the veto, the settlement it identified is thrown away. It should be kept as
a constraint — a merged credit carrying member A's reference is a credit whose
combination *contains A*, which collapses the subset-sum search and resolves
exactly the credits that fail above. That is the next matching improvement,
and it is not Splink.

**Corrected scope.** The measurement above says a fuzzy rung is not needed to
raise the match rate. It does not license dropping Tier 1 item 5 from the
plan, and treating it as though it did was wrong twice over: the rung was
skipped *and* `FUZZY_NARRATION` was quietly excluded from the conformance check
that asserts every rung matches something — precisely the kind of exclusion
that hides missing work.

So the rung gets built, on the same evidence:

- **Not with Splink.** Probabilistic record linkage with EM-learned weights is
  the wrong tool for comparing one damaged reference against forty candidates.
  A normalised similarity over the narration is the right size of hammer.
- **Measured, not assumed.** It runs as a fourth rung with its own row in the
  eval harness. If it adds nothing, that is a published ablation result — a
  stronger claim than either shipping it untested or skipping it on argument.
- **The exclusion goes.** Once the rung exists, the conformance check covers
  every strategy with no special cases.

---

## New, from the second audit — against the money rules

[02-THE-MONEY-RULES.md](02-THE-MONEY-RULES.md) says "our engine must model
every line here". Four lines are not modelled.

### 9. Instant refund fees — DONE

Rs 7.99 up to Rs 1,000, Rs 11.99 to Rs 25,000, Rs 14.99 above. This is the one
that matters, because it creates an exception class nothing else produces: a
refund debit **larger than the refund**. Everywhere else in this system a
refund costs the merchant exactly its face value, and a shortfall of Rs 11.99
against a Rs 4,000 refund is precisely the kind of number that gets written off
as "some bank charge" in a real finance team.

It is not a one-line change. The refund row's fee and tax columns become
non-zero, so `GatewayBatch.fee` and `.tax` must start meaning *payment* fee and
tax, and the waterfall needs its own line for instant refund charges rather
than folding them into the platform fee. The oracle test will catch any
arithmetic error in that.

- [x] `RateCard.instant_refund_fee(amount)` with the three slabs
- [x] Split batch fee/tax into payment and debit components
- [x] A named "Instant refund fees" proof line
- [x] Confirm the oracle still balances

### 10. Route, Smart Collect and QR pricing — deliberately deferred

Route (0.1% + platform fee), Smart Collect (1% or Rs 10, whichever is lower)
and QR (0.99% UPI / 2.0% cards) are all real Razorpay pricing, and all three
are **optional products a given merchant may not use at all**. Modelling them
adds fee-rate variety but no new *class* of reconciliation problem: they are
more rates in the same waterfall, and the waterfall already handles three.

Recorded as a decision rather than an oversight. If time allows they are cheap;
if it does not, nothing about the submission is weaker for their absence.

### 11. Instant settlement timing — deferred, same reasoning

Payouts in minutes instead of T+2. It breaks the settlement-date window the
matcher relies on, which makes it genuinely interesting, but it is a merchant
attribute rather than a defect and the date window already tolerates a day
either side.

### On the `ROUNDING` exception code

The money rules list `ROUNDING` as an industry-standard category meaning
"acceptable sub-rupee difference". The code was removed today because nothing
emitted it: drift inside the derived allowance is explained as a named line
*inside* the proof, and a credit that reconstructs to zero has no exception to
raise.

That behaviour is right and stays. What is genuinely missing is the reporting
side — the monthly total of rounding drift, which is the figure a merchant
would actually want and which no per-credit exception would give them.

- [x] Total drift across a run, reported in `eval --detail`. Gross and net,
      in that order, because drift cancels and a net near zero would read
      as "this does not happen" rather than "this happens both ways".

---

## Not behind

For the record, so the list above is not read as a project in trouble:

- The N:1 subset solver was a day 4-5 item and shipped on day 3.
- The exception queue UI (day 7) and Ollama (day 8) are not due.
- The oracle test, the eval baselines and the reproducible run all hold.

---

## Found by the day-6 verification pass — all closed

Day 6's three components (waterfall, eval harness, property tests) already
existed, so the work was holding each against the definition of done. Two of
the three failed it.

### 12. `eval` scored whatever dataset was on disk — DONE

No check that a stored run was one the current generator produces. A dataset
predating the reference-twin defect was still in `data/` and scored without
complaint, reporting a 33.3% baseline against a published 23.8%.

- [x] `save_dataset` writes the `GenerationConfig` beside the data
- [x] `load_dataset` regenerates from it and compares digests
- [x] `StaleDatasetError` refuses rather than warns, with the fix command in it
- [x] The CLI exits 1 instead of raising, and a test asserts that

### 13. The README's numbers had gone stale — DONE

Match rates current, refusal column carried over from an earlier run.

- [x] `milan eval --markdown` prints the table
- [x] The README holds it between generated-block fences
- [x] A test fails when a fresh run and the README disagree
- [x] Two cases guard the specific superseded figures

### 14. Nothing tested the scorer — DONE

`score()` produces every published number. The oracle proves the matcher; the
grader was unverified, and a scorer that counted a wrong match as correct
would raise every figure at once with the suite still green.

- [x] Hand-built reports with the answer known: 15 cases
- [x] The design stance is enforced, not just described — a lucky guess is a
      false positive, half a merged credit is not half a success

### 15. Property tests never reached the waterfall — DONE

Thirteen invariants, all covering layers *below* the interesting one.

- [x] Ten invariants over `prove`, the veto, the combination search and
      similarity
- [x] Each verified by mutation. One mutation passed first — the combination
      test used exact subset sums, where a correct and a sloppy solver agree —
      and the test was rebuilt to perturb the target off the combination

### 16. Two live defects in the similarity rung — DONE

Both found by the property "a reference is similar to itself".

- [x] Word boundaries on the noise pattern, so `CR` is not stripped from
      inside `JMSS5NDW4CR`
- [x] A sweep over every start position, so a bank label glued onto a
      truncated reference (`UTRRKBZWJLK`) is stepped past
- [x] Regression tests for both, plus one asserting the wider sweep did not
      become more agreeable

### 17. Splink — CLOSED, measured

The remaining open question from item 8, now answered with numbers rather than
argument. Lowering the similarity floor to 0.45 and the margin to zero gains
zero records on any tier or shape; of the credits still unresolved on the
colliding merchant, none carry narration evidence at all. Written up in
[18-BUILD-LOG.md](18-BUILD-LOG.md).

- [x] Measure whether our own measure is the binding constraint
- [x] Measure whether the unresolved credits carry string evidence at all
- [x] Record the boundary of the claim, not just the conclusion

### 18. The generator could hang on a valid config — DONE

`_draw_amount` was unbounded rejection sampling. Twenty-two seconds and eleven
million discarded draws for forty single-price orders; unbounded for a window
the distribution cannot reach.

- [x] Inverse-CDF sampling over the price window
- [x] A reversed window is rejected by the config, not hung on
- [x] Regression test asserting a single-price merchant generates promptly,
      still respects its window, and really has one price

### 19. One seed was not a measurement — DONE

`shortfalls named` ranged 17% to 83% across twenty seeds on a denominator of
six. The README had published two different noise readings of it.

- [x] `milan sweep` pools counts across seeds and reports the spread
- [x] The README carries the pooled table, checked by a test
- [x] The weakest figure is stated plainly: detection 100%, explanation 55%

---

## Day 7 — the exception queue

Tier 1 item 6, the one the cut rules say is never cut.

- [x] FastAPI layer over the engine (`milan.api`), 14 tests
- [x] The answer key cannot reach the browser, asserted by a test that greps
      the whole payload
- [x] Money crosses the wire as integer paise, asserted at any depth
- [x] Next.js workspace: run bar, queue, proved list, two detail panels
- [x] The browser's money formatter, held to the same table as `format_inr`
- [x] `milan serve`, `make serve` / `make web`

### Found by running it, not by testing it

- [x] `/api/runs` returned 500 when one dataset on disk was stale — listing is
      metadata, opening is what has to be trustworthy
- [x] CORS blocked a dev server that had moved to port 3002. Added
      `MILAN_WEB_ORIGIN` rather than widening the allowlist
- [x] The queue printed `fits 1 settlements equally well`. Two shapes of
      ambiguity were being reported as one, which sends somebody to the wrong
      file. `Attempt.contested_by`, nine tests

### Still open, and deliberately so

- Leak detection reads `LeakTruth`, which is still unread by any code — day 9
- The queue has no filter or search. At 37 cases it does not need one; at 400
  it would. Recorded rather than built, because the demo is a month of one
  merchant and inventing scale it does not have is how a screen gets busy
- No write actions. Nothing in this system resolves a case yet, and a button
  that pretended to would be the dishonest kind of demo


---

# Day 8 — the first day anything touches a model

## The number this day exists to move

Pooled across 20 seeds, detection is 100% and **explanation is 55%**:
shortfalls named 66/120, range 16.7%–83.3%. Every graded number is already at
its ceiling. This one is not, and it is the one a merchant actually reads.

The 45% is locatable to a single fall-through. `Categoriser.unproven_credit`
tries three checks — recovery gap, tax slab, fee surcharge — and when none
fires it emits `UNEXPLAINED` with the bare residual. That fall-through is the
whole gap.

## The rule that governs the design

**A model may propose. Only arithmetic may conclude.**

An LLM that writes "this looks like a refund" into a summary is fabricating a
finding, which is the one thing this project claims never to do. So the seam
is not model-writes-prose. It is:

    proposer → Hypothesis (typed, checkable) → verifier → finding | discarded

A `Hypothesis` names a *kind* and an *entity that exists*. It carries no
amount, because an amount from a model is an amount nobody checked. The
verifier does the arithmetic that already exists in `triage.py` and rejects
anything that does not foot to the paisa. A wrong proposal is therefore
discarded, never printed — the failure mode is a missed explanation, not a
false one.

This makes the LLM's contribution measurable rather than asserted: the share
of its hypotheses that survive verification is a number, and so is the share
of shortfalls it names that rules alone did not.

## The order of work

- [x] **Diagnose before designing.** Dump the unnamed shortfalls across the
      20-seed sweep and read what they actually are. Widening the rules may
      close most of the gap on its own, and if it does, that is the finding —
      not a disappointment. Measure first, then decide what a model is for.
- [x] Ollama installed, Qwen 2.5 3B pulled, verified on the 4 GB RTX 3050
- [x] `OllamaProvider`: health-checked, timed out, never raises, absent daemon
      degrades to unanswered rather than failing the run
- [x] Free hosted adapters behind the same interface (Groq, Gemini). Absent
      key means unavailable, not broken
- [x] Cache exercised against a real provider end to end, and the cached run
      shown to be reproducible without a model present
- [x] `Hypothesis` / verifier seam, with the three existing checks rewritten
      as proposers so rules and model go through identical verification
- [x] Deterministic proposers widened to cover whatever the diagnosis found
- [x] LLM proposer behind the seam, constrained to existing entity ids
- [x] Measurement: shortfalls named under rules-only vs rules+LLM, LLM
      proposal precision, and **a test that every graded number is identical
      across all three configurations**
- [x] `--provider` on the CLI, docs, and the build log

**Done, except the hosted configs.** Groq and Gemini are wired, tested against
recorded response bodies, and unrun: there is no key on this machine. That is
recorded as an absence rather than left looking like an oversight - the cut
rules already allow the five-config benchmark to shrink to three, and the
three that ran are *off*, 1.5B and 3B.

The size axis turned out to say more than a vendor axis would have. The 1.5B
model answered all 110 questions in valid schema and declined every one of
them; the 3B model proposed on 65 and was right on 18. Neither moved a
published figure, which is the seal doing its job rather than a coincidence.

Two things were found rather than built:

1. **The published ablation had gone stale.** 77 shortfalls became 110 when
   the shortfall rung landed, and nothing could have caught it - that table
   was typed, because regenerating it needs a model. It is now asserted by
   replaying the committed cache.
2. **The cache could not tell two models apart.** A caller never names a
   model, so the key had none in it. The only place that surfaces is a
   size benchmark, as two identical columns that read as a finding.

## What would make this day a failure


Not "the model did not help" — that is a publishable result and cut rule 6
already accepts it. A failure is a summary on screen that no arithmetic
checked.

## Day 8, closed

Every box above is ticked, and three of them closed differently than written.

**The verifier seam is the existing `Categoriser`, not a rewrite of it.** The
plan said to rewrite the three deterministic checks as proposers so rules and
model went through identical verification. They already did go through
identical verification once the model's hypothesis was handed to the same
object - and a second implementation written for the model would have drifted
out of step with the one used for the rules, at which point comparing them
would have stopped meaning anything.

**`--provider` is on `ablate` and nowhere else.** Putting it on `recon` or
`eval` would imply a model could change what they report, and the whole point
is that it cannot. The seal test now enforces that.

**The cache is committed.** `data/**` is ignored because a dataset is a pure
function of its seed and regenerating it is cheaper than storing it. A
completion is not a pure function of anything in this repository - it depends
on weights, a quantisation and a daemon - so the 77 answers are the one thing
here that has to be stored to be reproducible. `milan ablate` replays the
published 19.5% in 2.1 seconds on a machine with no GPU, no Ollama and no key.

### What day 8 actually found

The 55% was two failures under one name, and the 11 that were genuinely
explanation failures were closed by a tolerance the prover already had. The
model, measured properly against the rules it was meant to improve on, agreed
19.5% of the time and invented five record identifiers out of 41 proposals.

The named priority going in was *explanation quality is 55% while detection is
100%, and days 8-9 are where that must move.* It moved to 64.2%, and it moved
for a reason that had nothing to do with a model.

### What day 9 inherits

**43 unmatched credits per twenty adversarial seeds, and no metric reports
them as a matching failure.** They have corrupted bank references and are
excluded from the match-rate denominator because they are unprovable. Naming
that population properly is the honest half of day 9, alongside leak
detection - and it is the only place left where a model could plausibly earn
its keep, since the question there is *which settlement is this* rather than
*why is it short*.


---

# The two open items, closed

Both were reported as *"deliberately not done"*. Neither should have stayed
that way, and the second turned out to be the largest single improvement in
the project's weakest number.

## Splink - closed on evidence, not on taste

The earlier reasoning stands and is now decisive rather than persuasive,
because the population Splink would exist to rescue has been isolated and
read. Pooled over twenty adversarial seeds, the credits that reached the end
of the cascade unmatched number 43, and every one of them had its bank
reference corrupted. Their narrations:

| count | narration |
|---|---|
| 20 | `NEFT INWARD RAZORPAY SOFTWARE PVT LTD` |
| 11 | `ACH C- RAZORPAYSOFTWARE` |
| 7 | `IMPS/RZPY/SETTLEMENT` |
| 5 | `NEFT CR-RATN0000088-RAZORPAY-SETTLEMENT` |

**Recoverable references: 0 of 43.** The fourth form is the one that looks
promising and is not - `RATN0000088` is an IFSC branch code, not a settlement
reference, and treating it as one would be a wrong answer stated confidently.

That settles it as a measurement rather than an opinion. A probabilistic
linkage library - or any string method, Splink or otherwise - infers from
signal present in a field. There is no signal in these fields. Splink is not
cut because it is heavy; it is cut because **the evidence it consumes does not
exist in the cases it would be asked to solve.**

The capability Tier 1 asked for is still delivered: `FuzzyNarrationStrategy`
handles *damaged* references, and `test_fuzzy.py` measures that removing it
costs matches on messy and adversarial. It earns its place. Splink would not.

## The 43 unmatched credits - attributed, and the blind spot closed

Two separate failures, and both are fixed.

**The measurement gap.** `match_rate` excludes unprovable credits on purpose,
because the right output for those is an exception rather than a match. That
exclusion also meant a credit which failed to match *and* was unprovable was
scored only against explanation, where it read as a naming problem. Its
matching failure had nowhere to be reported. There is now a second rate beside
the first - **settlement attributed**, over every identifiable credit whether
it proved or not, at 98.0% (499/509). Strictly the harder denominator.

**The matching gap.** The evidence in those 43 was real and no rung could see
it: all 43 land on the settlement date exactly, short by a median of 0.31%.
Every rung above treats exactness as the whole of the evidence, so a credit
that is one settlement minus an unexplained deduction fell through all four.

`ShortfallStrategy` is the fifth rung. It matches on a total being *wrong*,
inside a band read off the merchant's rate card - worst card rate, GST on that
fee, withholding where it applies - rather than tuned against the data, which
would be fitting to the defect catalogue this project's own numbers are
already conditional on.

Its claims are withdrawn by the prover **every time, by design**, so it cannot
touch the match rate, precision, or the refusal count. What survives is the
settlement id, which turns *"no settlement behind it"* into *"this is
settlement A and it is short by exactly refund R"*.

| | before | after |
|---|---|---|
| shortfalls named | 64.2% (77/120) | **91.7% (110/120)** |
| worst seed | 33.3% | 66.7% |
| median seed | 66.7% | 100.0% |
| settlement attributed | not measured | **98.0% (499/509)** |
| match rate / precision / refusal | 100% | **100%, unchanged** |

Ten credits across twenty seeds remain unattributed: short by more than any
fee stack can account for, or short by an amount that fits two payouts equally
well. Those are refused, and refusing them is the point.

### Two tests this broke, and what each was hiding

**A test that indexed the ladder by position.** `test_fuzzy.py` compared
`cards[-2]` against `cards[-1]`, so adding a fifth configuration silently
repointed it to compare fuzzy against shortfall. It now finds both by label. A
test that names the two things it compares cannot be repointed by an unrelated
change.

**A conformance test that knew only one way to earn a place.** It asserted
every rung produces a balanced proof, and this rung produces none by design.
The honest fix was to name the second way - a claim the verifier withdraws,
which still names the settlement a credit fell short of - rather than to
exempt the rung, because "allowed to be dead" and "contributes differently"
look identical in a skip. There is now also a test asserting the shortfall
rung *never* proves anything, because that is the safety argument for a band
this wide, and it should fail loudly if it stops being true.

Making that test pass surfaced a real omission: `UnprovenCredit` carried no
record of which rung identified the settlement, so the queue presented every
named shortfall with equal authority. It does not deserve equal authority. One
named against a settlement the reference rung identified is a fact; one named
against a settlement this rung found nearby on the right date is an argument
at 35% confidence. Both now say which they are.


---

# Day 9 - the money that is wrong while everything balances

## Why this is the differentiator, stated precisely

Every number this project has published so far answers *did the payout
arrive*. Leak detection answers a different question: **the payout arrived,
in full, and the merchant was still robbed.**

A domestic consumer card is contracted at 2%. The gateway charges 2.15%. The
settlement row foots, the batch total foots, the bank credit matches to the
paisa, and the reconciliation is clean. There is nothing unmatched to notice,
which is exactly why no matcher on earth finds this - and why it survives in
real merchant accounts for years.

The generator has been injecting these since day 1 and **no code has ever
read them.** `LeakTruth` is written into every answer key and only
`test_chaos_engine.py` has ever looked at it.

| tier | leaks in 5 seeds | overcharged |
|---|---|---|
| clean | 0 | Rs 0.00 |
| realistic | 0 | Rs 0.00 |
| messy | 102 | Rs 376.97 |
| adversarial | 179 | Rs 683.85 |

About 36 a run, and the engine currently finds none of them.

## How it is detected

Not by matching. By reading one row against the contract:

    expected = platform_rate(row.method, row.card_type) applied to row.amount
    leak     = row.fee != expected

The row declares a domestic consumer card and carries a corporate-rate fee,
so the report contradicts itself on a single line. Deterministic, no model,
and the answer key makes it measurable rather than demonstrable.

**Report the GST correctly or the figure is wrong.** GST is charged on the
inflated fee, so the cash leaving the merchant is the overcharge plus 18% of
it. For a GST-registered merchant that 18% is recoverable as input tax
credit, so the *permanent* loss is the overcharge alone. Publishing the
larger number without that distinction would be overstating the harm, which
is the same sin as understating it.

## The order of work

- [x] `milan/leaks/detector.py` - find rate mismatches against the rate card
- [x] Scored against `LeakTruth`: found, missed, and **false leaks**, because
      accusing a gateway of overcharging when it did not is the expensive
      mistake here
- [x] Root-cause clustering: 36 rows become "every corporate-rate charge on a
      domestic consumer card, 36 payments, Rs X". A list is not a finding.
- [x] Both figures in the eval harness and the sweep, per the definition of
      done
- [x] `milan leaks` on the CLI
- [x] Surface it in the queue, because this is what carries the video
- [x] Tests, including the two that matter: a clean tier reports no leaks at
      all, and a leak is still found when the batch balances perfectly

**Done.** 762/762 caught with 762/762 precision across twenty adversarial
seeds; the clean and realistic tiers report nothing.

The screen is a third list beside the queue and the proofs, under its own
heading, because every row behind a finding *reconciled* - filing them with
the exceptions would say the reconciliation missed something when it did not.
The rate pair, the window, the networks and every payment id behind the claim
are on the panel, untruncated.

Three things went out with it that had been shipped the day before and read
by nothing: `LeakTotal`/`total()`, a second implementation of sums
`LeakReport` already had; `LeakCluster.describe()`, a canned sentence no
surface could use verbatim; and `ProofView.merged` and `Service.forget()` in
the API, dead since they were written. Coverage found all of them once the
screen existed to demand the rest. A metric nobody can see is a metric nobody
checks, and the same is true of a method.

One display bug fell out of testing the clean tier: **Refused** read `0.0%`
where no credit was impossible, which says "guessed at every hard case" when
the truth is "was never asked one". The card now shows a dash and names the
denominator when there is one.

## What would make this day a failure

Reporting a leak that is not one. A false exception costs somebody five
minutes; a false accusation of overcharging costs them a call with their
account manager and their credibility. The precision bar here is higher than
anywhere else in the project, not lower.


---

# Day 10 - what the model is worth, priced and plotted

Build order item 21 and the Tier 3 block around it. The single strongest
answer to "why is there so little AI in this", and the cut rules say it is
never cut.

Day 8 measured one model on one tier and published the result: **19.5%
agreement, 0/0 contribution, 26 rejected by arithmetic, 5 invented
identifiers.** That is one point on a curve. This day turns it into a curve,
puts a price on it, and makes it replayable by a reader with no GPU.

## The order of work

- [x] **Degradation curve across all four tiers** (item 25). Pooled counts per
      tier in one table, generated by a command, pasted into the README. Every
      figure this project publishes is from the adversarial tier, which is
      honest but leaves the shape of the curve unstated - and a system whose
      accuracy is flat from clean to adversarial is either very good or not
      being tested.
- [x] **Token accounting** (item 24). `Completion` carries what the model
      actually consumed, read from the provider's own counters rather than
      estimated. The cache has to be repopulated for this, which is free: the
      requests are unchanged, so the answers are the same.
- [x] **Cost, actual and projected.** Rs 0 spent, and what the same token
      volume would have cost on the paid tiers of the same models. Priced from
      published rates, with the rate and the date recorded beside the figure.
- [x] **A second local model** (items 22, 23). Qwen 2.5 1.5B beside 3B, on the
      same questions, through the same verifier. Three configs - off, 1.5B, 3B
      - is what the cut rules already allow the five-config benchmark to
      shrink to, and a size axis says more than a vendor axis about whether
      this task is model-limited at all.
- [~] **A hosted config if a key exists**, and a recorded absence if not.
      Groq and Gemini are one env var each and the adapters are already
      written. Not having run them is a fact to report, not a gap to hide.
- [x] **Golden-output test.** The committed cache replayed, asserting the
      published agreement and contribution figures. This is what turns "here
      are our numbers" into "here are our numbers, and here is the run" for a
      reader with no model at all.
- [x] **Run it twice, two different books.** The demo from item 21: the same
      questions put twice with sampling on, showing the answers move - beside
      `milan reproduce`, which shows the cascade's digests do not. The claim
      of this project is reproducibility, and this is the experiment that
      makes it falsifiable rather than asserted.
- [x] **README with the numbers up front**, including the ablation, the curve
      and the cost.

## What would make this day a failure

Publishing a number that flatters the model, or one that flatters the rules.

The temptation runs both ways here. A generous verifier would turn 19.5%
agreement into something respectable; a stingy one would let the project
claim the model is useless. Both are the same failure - the verifier is the
`Categoriser` the rules themselves use, and it stays that way precisely so
neither thumb can reach the scale.

The second failure is a cost figure with no rate and no date beside it. A
projected price is a claim about someone else's price list, and it goes stale.
