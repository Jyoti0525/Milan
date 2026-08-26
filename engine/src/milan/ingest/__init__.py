"""Reading a merchant's own files, in whatever shape their software wrote them.

Everything else in this engine reads records it already understands. This
package is the one place that does not: it is handed a directory of CSVs
written by somebody else's system, and it has to work out what each column
means before a single rupee can be reconciled.

That is a judgment task, and it is the one place in Milan where a language
model earns its seat. No rule can know that `Particulars` and `Narration` and
`Txn Remarks` are the same field, or that a bank called its credit column
`Deposit Amt` this year. A model knows immediately.

So the split here is the same one the rest of the project uses, applied to
schema instead of to money:

  **the model proposes a mapping, and the values decide whether it stands.**

Every column the model names is profiled first - does it parse as money, as a
date, as one of the four entity types - and a proposal the values contradict
is rejected and recorded, never applied. Where the evidence neither confirms
nor refutes, the import stops and asks. It does not guess, because a wrong
column here does not produce a wrong explanation, it produces a wrong balance.
"""
