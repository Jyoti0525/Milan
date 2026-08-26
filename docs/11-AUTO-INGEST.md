# Auto-Ingest (Watched Folder)

## The idea

The user picks a folder. They drop files in it. Milan notices and processes them
automatically. No upload button, no manual step.

## Verdict: YES — but scoped tight, and Tier 2

It is a good idea. It is not, on its own, a differentiator — it moves none of
the numbers Razorpay grades (match rate, precision, throughput). So it earns its
place only once Tier 1 is solid.

**But it is cheaper than it looks**, because most of the work is already in scope.

## Why it is cheap: it is a surface on work we already need

We already committed to **idempotency** — re-running a cycle must never
double-count. Auto-ingest needs exactly the same machinery:

```
new file appears
  -> content hash (SHA-256)
  -> already ingested? skip
  -> parse
  -> run cycle
```

The dedup logic IS the idempotency logic. The watcher is a thin layer on top.

## The genuinely interesting part: schema inference

> **PROMOTED, THEN BUILT.** Schema inference is no longer a sub-feature of the
> watcher. It is one of our **five genuine AI-judgment tasks** (see
> `04-THE-AGENTS.md` and `17-AI-INVOLVEMENT.md`). **The watcher can be cut;
> schema inference stays.**
>
> It shipped as `milan import --from <folder>`, in `milan/ingest/`. The watcher
> was not built and is not missed: a merchant points the command at a folder.
> What follows described the intention; `docs/22-INGEST.md` describes what
> exists.

This is what makes the feature worth having.

When a CSV lands, **which of the three inputs is it?** Bank statement,
settlement report, or order export? And which column is the amount, the date,
the reference?

Deterministic column matching handles the easy cases. The messy ones — unknown
bank formats, renamed headers, extra columns — are exactly where an LLM belongs.

This is a **legitimate AI use**, not decoration. Commercial tools charge for it:
"file-format agnostic" is literally one of Osfin's selling points.

And it fits our rule: the LLM infers **structure**, deterministic code does the
**arithmetic**.

## Scope

| In | Out |
|---|---|
| Watch one configured folder | Multiple folders |
| Content-hash dedup | Cloud storage / S3 |
| Schema auto-detection | Live bank API integration |
| Auto-run the cycle on new file | Real-time streaming |
| Show ingestion history in the UI | Scheduled polling of remote sources |

## Windows gotchas (we are on Windows 11)

These are real and will bite:

1. **Partial writes.** The watcher fires while the file is still being written.
   Fix: wait for the file size to be stable for ~1 second before reading.
2. **File locks.** Windows locks files being written by another process.
   Fix: retry on `PermissionError` with backoff.
3. **Duplicate events.** Windows fires multiple events for a single write.
   Fix: debounce, plus the content hash catches it anyway.

Library: `watchdog` (cross-platform, mature).

## Why it helps the video

"Drop a file into a folder, everything happens" is a strong opening ten seconds.
Better than clicking an upload button.

That is a real benefit — the video is a graded deliverable.

## Cut rule

If Tier 1 is not solid by day 7, **the folder watcher** is cut along with the
rest of Tier 2. The manual path (point the engine at a file) must always work.

**Schema inference is NOT cut with it** — it is a standalone AI-judgment feature
and works on manually supplied files just as well. This is what happened: the
watcher was cut, the inference shipped, and the manual path is the only path.
