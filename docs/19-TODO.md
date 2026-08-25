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

- [ ] Add a tier or config flag that turns 194-O on
- [ ] Confirm the oracle test still passes with withholding present
- [ ] Confirm the "TDS" label appears only at the statutory rate, and the
      fallback label appears otherwise

### 2. "UTR corrupted" actually means "UTR deleted"

`_narration()` is binary: a perfect reference, or none at all. Real bank
narrations damage references — truncation, transposition, padding, a reference
split across fields, junk glued on. `ExactUtrStrategy` requires exact string
equality, so one transposed character is a total miss today and we have never
measured that.

This is a generator bug in its own right. It also invalidated the argument for
cutting Splink, which is why it is P0 and not P2.

- [ ] Generate damaged-but-present references as a distinct defect class
- [ ] Re-measure the baseline, then reopen the Splink decision with evidence

### 3. The deterministic categoriser's headline number is not printed

Tier 1 item 10. `Scorecard.rules_share` is computed and referenced nowhere —
`grep` finds zero call sites. It is the share of exceptions settled with no
model at all, which is the number behind every "we used AI here and not there"
claim in the submission.

Fails the definition of done on "its numbers appear in the eval harness
output".

- [ ] Render `rules_share` in `scorecard_detail`
- [ ] Same for `merged_rate`, `unreported_detection_rate`, `exception_rate` —
      all computed, none shown

---

## P1 — verification gaps

### 4. Persistence has no test

`milan recon` reads what `milan generate` wrote. If `save_dataset` /
`load_dataset` lost a field, every downstream number would be measured on
different data than was generated, and nothing would fail.

Checked by hand today: round-trips identically on all four tiers. Nothing
would catch a regression.

- [ ] Round-trip test: `content_hash(dataset) == content_hash(reload(dataset))`

### 5. The CLI has no test

`cli/main.py` and `cli/render.py` are untested. A broken typer signature or a
renderer that raises on a merged proof would ship green.

- [ ] Smoke test each command through typer's `CliRunner`

### 6. Property tests do not exist

Day 6 in the plan, so not overdue — recorded so it does not become overdue.
`tests/property/` is an empty package and Hypothesis is already a dependency.

- [ ] Invariants: proof lines sum to the credit; deductions never exceed
      gross; `from_rupees` round-trips; batch net is the sum of its rows

---

## P2 — dead code, small

- [ ] `ExceptionCode.ROUNDING` is never emitted. Drift inside the allowance is
      explained as a proof line, not raised — which is right, so the member
      should go rather than the behaviour change.
- [ ] `total_pending()` has no callers.
- [ ] `LedgerDirection` has no real use.
- [ ] `AnswerKey.matchable_count` has no callers.

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

### 8. Splink — open, not cut

Reopened after item 2. The evidence that prompted the cut was gathered on a
generator that cannot produce the input Splink handles. Decide after item 2
lands.

---

## Not behind

For the record, so the list above is not read as a project in trouble:

- The N:1 subset solver was a day 4-5 item and shipped on day 3.
- The exception queue UI (day 7) and Ollama (day 8) are not due.
- The oracle test, the eval baselines and the reproducible run all hold.
