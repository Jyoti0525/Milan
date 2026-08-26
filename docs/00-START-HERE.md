# Milan — Start Here

This folder is the full plan for our Razorpay AI Buildathon submission.
Read the files in order. Each one covers one topic in plain language.

| File | What's inside |
|---|---|
| `BUILDATHON_BRIEF.md` | Razorpay's official brief, captured word-for-word |
| `01-WHAT-WE-ARE-BUILDING.md` | The product, explained simply |
| `02-THE-MONEY-RULES.md` | Indian fees, taxes, settlement rules (the real numbers) |
| `03-ARCHITECTURE.md` | How the system is put together |
| `04-THE-AGENTS.md` | The three agents and what each one decides |
| `05-WHAT-MAKES-US-DIFFERENT.md` | Honest list: what's standard, what's ours |
| `06-HOW-WE-MEASURE.md` | The numbers we report and what we compare against |
| `07-BUILD-ORDER.md` | What to build first, and what gets cut |
| `08-TECH-STACK.md` | Tools we use and why |
| `09-RISKS-AND-MITIGATIONS.md` | The four real risks and how each is controlled |
| `10-LLM-CHOICE.md` | Which model, and the cost controls |
| `11-AUTO-INGEST.md` | The watched-folder feature, as planned. The watcher was cut and the schema inference shipped - see `22-INGEST.md` |
| `12-FREE-LLM-PLAN.md` | Running on free models only, and why that's a strength |
| `13-PORTABILITY-AND-DEPLOYMENT.md` | Making it run on anyone's machine, and where to deploy |
| `14-DECISIONS-LOG.md` | **Every settled decision in one place** — read this if unsure |
| `15-PRODUCTION-STORY.md` | How a real merchant uses it, and where the model runs in production |
| `16-WHY-NOT-FINETUNE.md` | Why fine-tuning fails here, and the better HuggingFace artifact |
| `17-AI-INVOLVEMENT.md` | **How much AI is really in this**, the ablation, and the competitor analysis |
| `18-BUILD-LOG.md` | What broke each day, and how we got out. Written as it happens |
| `22-INGEST.md` | **Reading a merchant's own files.** What `milan import` does, what it refuses to decide, and how the schema inference is checked |

## The basics

- **Competition:** Razorpay AI Buildathon (student-only, hiring AI Builder Interns)
- **Track:** 04 — AI Finance Controller
- **Deadline:** 5 September 2026
- **Format:** Individual, not team
- **Project name:** Milan (Hindi: *matching / bringing together*)

## One-paragraph summary

A merchant sells 100 orders worth Rs 95,000. One deposit of Rs 90,608 lands in
their bank. Milan works out which orders are inside that deposit, explains every
rupee that was deducted along the way, reports honestly how many it could not
match, and flags money that is quietly leaking out. It runs the deterministic
work in plain code and uses AI only where judgment is genuinely required.

## What we must deliver

1. Public GitHub repo
2. 5-minute pitch video (unlisted is fine)
3. The Google Form: 12 answers
4. A written answer to "what broke, and how you got out" — they read this first
