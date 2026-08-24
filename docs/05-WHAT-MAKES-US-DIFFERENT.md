# What Makes Us Different

## First, an honest list of what does NOT

Research into Ledge, Osfin, Numeric and ReconPe shows these are **industry
table stakes**, not innovations. We build them because they are correct. We do
NOT pitch them as our ideas:

| Feature | Reality |
|---|---|
| Rule learning across runs | ReconPe's actual tagline is "AI-Agent Reconciliation That Remembers Across Runs" |
| Deterministic core + LLM on the residue | This IS the standard architecture |
| Grounded matches with citations | Described industry-wide as "non-negotiable" |
| Human-in-the-loop | Called "a design requirement" |

Claiming these as innovation would look naive to anyone who knows this market.

## What IS genuinely ours

### 1. The Chaos Engine
A synthetic data generator with difficulty tiers and a ground-truth answer key.
Nobody publishes their own test-data generator. It is what makes every number
we report verifiable.

### 2. Measuring correct refusal
We inject records that are **impossible to match by construction** — the linking
data genuinely does not exist. Then we measure: did the system correctly give up,
or did it force a wrong match?

Almost nobody measures whether their system knows when to stop.

### 3. Publishing our own degradation curve
Not one match rate. Four, across four difficulty levels:

| Tier | What it is |
|---|---|
| Clean | Well-formed, no defects |
| Realistic | Normal messiness |
| Hostile | Heavy defects, timing splits |
| Adversarial | Deliberately nasty |

This is the direct answer to their line *"one cherry-picked match proves
nothing."* We are not showing one good case — we are showing exactly where we
break, on purpose.

### 4. THE BIG ONE — leak detection at volume

Their bar asks for **throughput**. Everyone will treat that as a speed brag.

**We use throughput to find errors that are mathematically invisible at low volume.**

Some money losses **balance perfectly**. They produce no exception. A normal
reconciliation tool reports 100% matched and misses all of them:

| Leak type | Why it is invisible at 50 records |
|---|---|
| **Rounding bias** | Each row off by Rs 0.30. Noise at 50 rows. Real money at 50,000. |
| **Rate drift** | Charged 2.15% where 2% was contracted. Any one row looks fine. The pattern is the evidence. |
| **TDS on the GST component** | Per Razorpay's docs, 194-O does not apply to GST. If applied, provably wrong only in aggregate. |
| **Double-netted refunds** | Same refund netted in two cycles. Both cycles balance. |
| **Won disputes never credited back** | Chargeback deducted, dispute won, money never returned. Nothing looks unbalanced. |

So the product shifts from **reconciliation** to **settlement assurance**:

> Don't just tell me the books balance.
> Tell me where money is leaving that shouldn't be — and why.

**This is also the answer to "why did you run 50,000 records when we asked for
50?"** Not to show off. Because this entire class of finding is mathematically
invisible below a few thousand records. The throughput is a requirement, not a flex.

### 5. Root-cause induction (LLM-assisted)
Not "here are 71 exceptions" but *"43 of your 71 exceptions trace to one cause:
corporate cards are being deducted at a tier you did not contract for."*

Turns a clerical output into a business finding.

**This one is genuinely AI.** Inducing a shared cause across heterogeneous
evidence is real reasoning — not narration, and not something a clustering
algorithm produces on its own.

### 6. India-specific depth
Real fee stack, real 194-O TDS rules, real T+2 timing, real ITC matching against
the monthly tax invoice, real Razorpay field names.

## IMPORTANT — how we must frame this

We are **NOT** claiming Razorpay overcharges anyone.

We **inject** these discrepancy classes into the Chaos Engine deliberately, and
prove the system detects them. It is a capability demonstration on synthetic
data, exactly as the brief specifies.

This distinction must be explicit in the repo README and in the video.

## Optional framing line

> **Reconciliation as CI for money.** Every settlement cycle runs a test suite
> against the books. You get pass/fail, a diff, and a list of what broke.

Makes the project instantly legible to an engineer.
