# Reading a Merchant's Own Files

`docs/11-AUTO-INGEST.md` describes the intention. This describes what exists.

```
milan import --from C:\merchant\july-2026
```

Point it at a folder. It reads every CSV in there, works out what each file is
and what each column means, **stops and asks about anything it cannot settle**,
and then reconciles — through the same pipeline, the same waterfall and the same
cascade as a generated run.

---

## Why this is the one place a model belongs

Everything else Milan reports about money is arithmetic, deliberately. But no
amount of arithmetic knows that `Particulars`, `Txn Remarks` and `Narration` are
the same field, or that a bank writing `Deposit Amount(INR)` means the credit.

A list of aliases covers the banks somebody has already met. **A model covers the
next one.** That is the whole argument, and it is why decision 55 called schema
inference "our most legitimate AI use" before any of it was written.

The boundary is unchanged from `llm/triage.py`, applied to schema instead of to
money:

> **A model may propose. Only arithmetic may conclude.**

Here that means: the model proposes a column mapping, and the **values decide**.

---

## Three things get a say, and only one has a veto

| | What it contributes | Can it veto? |
|---|---|---|
| **The values** | Does this column parse as money, as a date, as one of the four entity types? | **Yes** |
| **The header name** | Is this a name the schema already knows? | No — it confirms |
| **A model** | What might these unfamiliar names mean? | No — it proposes |

A column whose contents do not parse as a field's kind **is not a candidate,
whoever nominated it.** That check runs before anything else and it is not
overridable.

### What that looks like in practice

Pointed at a hostile export with Qwen 2.5 3B (a 3-billion-parameter model on a
4 GB card), the model mapped nine of the ten required settlement fields
correctly, and got two wrong in instructive ways:

| Proposal | Outcome |
|---|---|
| `credit` ← `paid_out_flag` | **Rejected by the values.** That column holds `Y`/`N`, not money |
| `debit` ← `paid_in` | Values fit; semantically inverted. **Became a question** — never applied |

Both failures were contained by a different mechanism, which is the design
working rather than luck.

---

## The rule: ambiguity never resolves itself

A field two columns could be, or one that only a model's guess supports, is
never quietly assigned. What happens instead depends on whether the field is
required:

- **Required** → the import **stops and asks**. A settlement report without a fee
  column is not a settlement report.
- **Optional** → the field is **dropped, and its cost is printed**. Losing the
  card-type column costs a leak attribution; guessing at it costs a balance.

Every column in the mapping table is labelled with how it was decided:

| Label | Meaning |
|---|---|
| `confirmed` | The header name is one the schema knows, and the values agree. Nothing was guessed |
| `answered` | A person chose it |
| `unconfirmed` | A model proposed it and the values permit it; no name confirms it |
| `absent` | Not in this file |
| `open` | Nothing proceeds until this is answered |

**Nothing runs until the whole table is approved.**

---

## The questions it actually asks

Three kinds, and each one is a question a person is genuinely better placed to
answer than a program.

**Which date column?** A statement carrying both `Txn Date` and `Value Date` is
carrying two different days. Which one reconciliation should use is a finance
decision.

**Which reading of the date?** `06-07-2026` is the 6th of July or the 7th of
June. Only the column's own values can settle it — whether any date in it has a
day past the twelfth. When none does, the import shows both readings of a real
value from the file and asks. A parser that picked one would not be slightly
wrong; it would be silently reporting a different month.

**Which column is this field?** Asked when no header name matches and only a
model's suggestion supports it. The suggestion becomes the first option, and
nothing more.

Answer them interactively, or in advance:

```
milan import --from <folder> --map "OpTxnHistory.csv:amount=Deposit Amount(INR)"
```

A refusal always prints the exact flag for every open question. An import that
refuses and then leaves the operator to work out the syntax has refused twice.

---

## Placing the files — a cascade, like the matcher

Each rung is cheaper and more checkable than the one below, and the model sits
near the bottom rather than at the top.

| Rung | Test |
|---|---|
| 0 | **Feasible?** Does every required field have *some* column here whose values could be it? A record type a file cannot supply is not a candidate for it |
| 1 | Three quarters of the required column names recognised, and ahead of every alternative |
| 2 | Half of them, and at least 1.5× the next best — decisively the clearest fit |
| 3 | A model maps the required fields of each candidate; the kind whose mapping the **values can actually fill** wins |
| 4 | Fall back to what the names said. A model being wrong is not a reason to discard the header evidence |

Rung 0 is what keeps junk out. A register of GST invoices has an id, an amount
and a reference — three of the four fields a payments file needs. What it has no
column for is a date, and nothing can invent one.

### One rung that was removed

The first version asked the model *"which of the four records is this file?"* and
checked the answer against the header aliases. That is circular: the aliases are
exactly what had just failed to place the file, so the check could only ever say
no. It did, on a bank statement the model had called a settlement report.

Ranking the record kinds by how much of the file each proposed **mapping** can
fill answers the same question with evidence the values verify independently.

---

## What gets refused, and why it is printed

| Refusal | Example |
|---|---|
| A column the file does not have | The model named `Deposit Amt.`; the header says `Deposit Amount(INR)` |
| A column whose values contradict the field | `Withdrawal Amount(INR)` is empty in every row |
| **One column offered for two fields** | `igst_rate` proposed as the credit, the debit *and* the tax |

The last one is worth its own line. That is not a mapping with three mistakes in
it — it is not a mapping. Keeping any one of the three would be picking, so all
three are dropped and all three are reported.

---

## What it says it cannot do

Before the run, not after:

```
What this import cannot check
  - no payments file: captured money the settlement report never mentions
    cannot be raised, so the exception list covers bank credits only
  - OpTxnHistory.csv has no debit column: lines with no credit amount are
    dropped on that basis alone
```

A merchant reading a clean exception list has a right to know which checks were
switched off before they trust it.

---

## Reading values other people wrote

| Handled | Because |
|---|---|
| `1,23,456.78` and `1,234,567.89` | Indian and Western grouping both turn up |
| `₹ 2,500.50`, `Rs. 90,608.47`, `INR 500.00` | Every prefix an export uses |
| `37,419.37 Cr` / `1,234.56 Dr` | Indian statements write direction as a suffix, not a sign |
| `(1,234.56)` | Accounting negatives |
| Four lines of bank banner above the header | HDFC's actual export. `csv.DictReader` would read one column called `HDFC BANK LIMITED` |
| A BOM from Excel | Otherwise `Date` becomes `﻿Date` and no alias ever matches it |
| Two columns both called `Amount` | A dict would silently keep one |
| `;` `\t` `|` delimiters, cp1252 encoding | Sniffed |

**A blank credit is not zero.** It is a line that is not a credit. Reading it as
zero would invent a nil-rupee payout for every withdrawal the merchant made that
month, and each one would then be reported as a credit nothing could explain.

Money goes through `from_rupees`, which means `Decimal` all the way down. No
float touches an amount here, for the same reason it does not anywhere else.

**Nothing is repaired.** A row that will not read is dropped, and reported with
its file and the line number to open in a spreadsheet.

---

## The proof that it read the files correctly

An imported run has no answer key. So one is manufactured.

`tests/integration/test_ingest_round_trip.py` takes a generated dataset, writes
it out as CSV in the shapes real exports arrive in — the banner, the grouped
rupees, the `Cr` markers, `%d-%b-%Y` — reads it back through the full import, and
compares the result against the reconciliation the engine already did from its
own records.

**Every proof, every cascade rung, every exception and every amount matches.**

That is a stronger statement than "the import ran". It is that reading a
merchant's files produces the same answer as having the data natively — which is
the only claim that makes the feature worth having. A dropped paisa, a date read
the other way round, or a debit read as a credit all fail it.

The same check on the real merchant folder, against `realistic/seed 9`:

| | Native | Imported |
|---|---|---|
| Proofs | 19 | 19 |
| Cascade rungs | 14 exact / 2 subset / 2 amount+date / 1 fuzzy | identical |
| Exceptions | 10 | 10 |
| Exception codes and amounts | — | identical |

---

## Reproducibility

A generated run is reproducible because it is a pure function of its seed. An
imported one cannot be — the merchant's files live outside this repository.

What *is* made reproducible is everything that happened **to** those files: which
column was read as the fee, which date format was chosen, what a model proposed
and what a person answered. That is written to `data/imports/<name>/mapping.json`.

**The second import of a folder asks nothing and consults no model.** The
judgment happened once and was recorded, rather than being repeated and possibly
answered differently — which is also what stops a demonstration from depending on
a daemon being up.

The merchant's own directory is never written to. Their folder is evidence, and
evidence a tool has left files in is worth less.

---

## The browser path

```
milan serve --provider ollama
```

Then **Import your files** in the top bar. Drop the CSVs in, and the same
refuse-and-ask contract runs behind HTTP:

| Route | What it does |
|---|---|
| `POST /api/uploads` | Stages the files and returns a reading of them. **Nothing is reconciled and nothing is archived** |
| `POST /api/uploads/{id}/answers` | Answers one or more questions; returns the whole plan back |
| `POST /api/uploads/{id}/commit` | Reconciles and keeps it. 409 if anything is still unanswered |
| `DELETE /api/uploads/{id}` | Throws the upload away. Closing the dialog calls this |

This is the engine's only `POST`. It binds to loopback and has no
authentication, so the filename check, the twelve-file cap and the 32 MB cap
are the boundary rather than a belt beside a brace — a filename is data from a
browser, and treating it as a path is how an upload writes outside its own
directory.

### Fifteen questions is a refusal nobody reads

The first version of the wizard put every candidate column up as an identical
button. On an export whose headers we have never met that came out as fifteen
questions, one of them offering twenty-two choices. Technically a refusal to
guess; in practice a wall.

So where the model proposed something, that is the primary button and it says
who proposed it — and when three or more questions have a suggestion, one
**Accept N suggestions** takes them all. That is not a hole in the contract.
The contract is that nothing is applied without a person agreeing, not that
agreement is typed once per column: fifteen identical clicks is *less* consent
than one reviewed batch, because by the eighth nobody is reading. What follows
either way is the mapping table, every row marked `answered`, all of it open
to being changed.

On the hostile export that takes fifteen questions down to two — and the two
left are exactly the ones a model could not help with: `Date` vs `Value Dt`,
and a credit column whose only proposal the values had already refused.

### One column cannot be two fields, whoever says so

`coherent` enforced that on a model's proposals from the start. It did not
enforce it on a person's answers, and the gap was reachable in three clicks:
accept a suggestion that puts `paid_in` on the debit, then answer `paid_in`
for the credit. Both stuck. Every settlement row came out with its debit equal
to its credit and nothing said a word.

Answering a field with a column that already answers another now **clears the
other**, and that field goes back to being an open question. The person has
just said what that column is; the thing it used to be is once again unknown.

---

## On screen

`milan serve` lists imported folders beside the generated runs, under their own
heading. Opening one gives the same exception queue, the same proof panel and
the same leak view — and a different set of metric cards, because a different
set of things can honestly be said about it.

| Generated run | Imported run |
|---|---|
| Proved to the paisa | Proved to the paisa |
| **Precision** — against the answer key | **Exceptions raised** |
| **Refused** — against the answer key | Rounding drift |
| Rounding drift | **Columns read by a model** |

Precision and the refusal rate are gone because there is no answer key to
measure them against, and a zero in their place would read as a measurement
rather than as an absence. Rounding drift stays, because it is the one
accuracy-shaped number that needs no answer key at all: a credit that
reconstructs to zero has proved itself.

In their place is an **audit tab** that a generated run does not have, because a
generated run does not need one — it is a pure function of a seed. It shows:

- the **column mapping** for every file, each row labelled `confirmed`,
  `answered`, `unconfirmed` or `absent`, with the date format printed beside
  the column it was pinned for;
- what a model contributed, as a count of columns;
- **every proposal the values refused**, in full;
- what the run could not check, and what each absence costs.

The `unconfirmed` rows are the ones to read. They are where a model proposed a
column, the values permitted it, and nothing else agreed.

---

## Where the code is

| Module | Job |
|---|---|
| `ingest/reading.py` | Find the header, sniff the delimiter, decode, keep line numbers |
| `ingest/parsing.py` | Money, dates, booleans, vocabulary |
| `ingest/profile.py` | Measure each column. **The veto** |
| `ingest/schema.py` | What Milan needs, its aliases, and what each absence costs |
| `ingest/propose.py` | **The model.** Prompt, parse, refuse incoherent mappings |
| `ingest/resolver.py` | Place files, resolve columns, or refuse and ask |
| `ingest/build.py` | Confirmed mapping → `ReconInput` |
| `ingest/archive.py` | Keep the mapping so the second import asks nothing |
| `cli/ingest_render.py` | Show a merchant what we think their files are, before we touch them |
| `api/service.py` | `/api/imports` and `/api/imports/{slug}` — a separate route, because an imported run has no scorecard |
| `web/components/Provenance.tsx` | The audit view: the mapping table, and what was refused |

---

## What is not built

- **The folder watcher.** Cut, as decision 47 always said it could be. A merchant
  points the command at a folder.
- **PDF statements.** Still Tier 3 (`21c`). The CSV path does not depend on it.
- **Multi-currency.** The currency column is read and carried; nothing converts.
