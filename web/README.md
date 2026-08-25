# web — the exception queue

The interface Milan is judged on. It reads the reconciliation API and shows
two things side by side: what could not be resolved and why, and what could,
rebuilt line by line down to nothing unexplained.

```bash
# terminal one — the engine
cd engine
uv run milan generate --seed 42 --difficulty adversarial --orders 600
uv run milan serve

# terminal two — the interface
cd web
npm install
npm run dev
```

Then open http://localhost:3000.

If `next dev` reports that port 3000 is taken and moves to another, the API
will refuse the browser's requests — its CORS allowlist is deliberately narrow
because it serves settlement data. Name the port you actually got instead of
widening it:

```bash
MILAN_WEB_ORIGIN=http://localhost:3002 uv run milan serve
```

Point the interface somewhere other than `127.0.0.1:8000` with
`NEXT_PUBLIC_MILAN_API`.

## Layout

| Path | What is in it |
|---|---|
| `app/page.tsx` | The workspace: run bar, list, detail pane |
| `app/globals.css` | The design tokens, and why they are these ones |
| `components/` | Run bar, queue and proved lists, the two detail panels |
| `lib/api.ts` | Types written against the FastAPI schema, and the fetch layer |
| `lib/money.ts` | Paise to rupees, Indian grouping, no floats anywhere |

## Two rules this interface keeps

**Money arrives as integer paise and is never divided by a hundred.** The API
refuses to send formatted strings, which puts the obligation here instead:
`lib/money.ts` does the grouping on integers. `Intl.NumberFormat` would be
shorter and takes a `Number`, which is exactly the imprecision the engine
spends its whole design avoiding. The formatter is tested against the same
table as `format_inr` in the engine, so the two cannot drift apart.

**The visual language is Blade's.** Blade is the design system that powers
Razorpay, and its tokens are transcribed into `app/globals.css` from
`github.com/razorpay/blade` rather than eyeballed: the greys are its `ashGray`
scales, the blue is `azure`, and success / warning / error are `emerald` /
`cider` / `crimson`. Spacing, radii and the type scale follow Blade's, and
money is set the way Blade's `Amount` component sets it — the ₹ small, the
rupees large, the paise small and muted.

The package itself is not a dependency. This is one screen, and pulling in a
component library plus its styled-components runtime to render two tables
would weigh more than the thing it renders. What is borrowed is the language,
so the result belongs beside a Razorpay dashboard instead of looking like a
generic admin template.

The layout follows Modern Treasury's reconciliation dashboard: side navigation
organised around the job, a summary that leads to the next task, and a
side-by-side view for working one case at a time. Their rule about showing
data "as explicitly and granularly as possible" is why nothing here is
truncated — the exception text *is* the product.

## Testing

```bash
npx vitest run     # the money formatter
npx tsc --noEmit   # types
npm run lint
```
