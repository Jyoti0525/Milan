# Milan Engine

The reconciliation engine: chaos generator, matching cascade, waterfall solver,
deterministic categoriser, and the eval harness that scores all of it against
ground truth.

Pure Python, no LLM required. See `../docs/` for the full plan.

## Quick start

```bash
uv sync
uv run milan generate --seed 42 --difficulty realistic --orders 100
uv run milan recon
uv run milan eval
```

## Layout

| Path | Contents |
|---|---|
| `src/milan/domain/` | Money, rates, records, results. Pure types, no I/O |
| `src/milan/chaos/` | Synthetic data generation and the answer key |
| `src/milan/recon/` | Matching cascade, waterfall solver, categoriser |
| `src/milan/evaluation/` | Scoring against ground truth |
| `src/milan/persistence/` | Reading and writing datasets |
| `src/milan/cli/` | Command line entry points |
