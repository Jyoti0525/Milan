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

