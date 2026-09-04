# What We Are Building

## The problem, in one story

You run an online store. Last week you sold **100 orders worth Rs 95,000**.

Today, **one** deposit lands in your bank: **Rs 90,608**.

Two questions you cannot answer without opening a spreadsheet:

1. Which of my 100 orders are inside this single deposit?
2. Where did the missing **Rs 4,392** go?

The answer is a stack of deductions:

| What happened | Amount |
|---|---|
| Platform fee (2%) | -Rs 1,900 |
| GST on that fee (18%) | -Rs 342 |
| One refund | -Rs 950 |
| One chargeback | -Rs 1,200 |
| **Total** | **-Rs 4,392** |

Right now a real person does this by hand, every week, for thousands of orders.
At most Indian companies this is somebody's actual job.

## What Milan does

**Three inputs** a real merchant already has:

1. **Order book** — what they sold
2. **Gateway settlement report** — what the processor says it is paying
3. **Bank statement** — what actually arrived

**One output** — a complete, provable breakdown of every bank credit:

```
Bank credit  Rs 90,608.47   (24 Aug)
 = 97 orders            Rs 95,000.00
 - Platform fee @2%     Rs  1,900.00
 - GST on fee @18%      Rs    342.00
 - refund  #4471        Rs    950.00
 - chargeback #2210     Rs  1,200.00
 - rounding drift       Rs      0.47   <- explained, not ignored
 = balances to zero
```

Every line clicks through to its source row.

## The idea in one line

Most tools are **matchers** — they tell you what lined up.

Milan is a **prover** — it shows where every rupee went, and refuses to guess
when it cannot be sure.

## Who it is for

A finance person at a mid-size Indian business who currently opens three
spreadsheets every Monday morning.

## What it is NOT

- Not a chatbot with a database behind it
- Not an ML forecasting model
- Not a general-purpose accounting system

It does one job: **close the settlement reconciliation loop, honestly.**

## The one thing it says about the future

The track is called "Run the books and the cash position", and the second half
needs an answer that does not contradict the first. `milan.forecast` gives one:
money the merchant has **already captured**, dated by Razorpay's published
settlement cycle and reduced by the merchant's own fee stack.

That is a schedule, not a forecast. A forecast says what is likely and can be
wrong about the world; a schedule says what is owed and when it is due, and can
only be wrong about arithmetic. No sale is extrapolated and no trend is fitted,
so the second bullet above still holds exactly as written — and the question
answerer still refuses the word *forecast* outright, offering the schedule
instead.

Money that cannot be dated is reported as undated rather than given a date it
did not earn, and the whole schedule is marked against the half of the month it
was not allowed to read. See `docs/06-HOW-WE-MEASURE.md`.
