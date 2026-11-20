---
name: script-review
description: Write an Arabic content script (Reel, short video) in one file and run the review loop that scores every line for spoken white Arabic (Levantine presenter, Gulf + Levant viewers) and Hormozi content rules, rewriting until it passes. Use when the user wants a script written, checked, polished or made "clean Arabic".
---

# Script review loop

One script = one file. Five independent reviewers (meaning, complete beginner, Levantine presenter, Gulf viewer, content + compliance + lessons) score it, a writer fixes what they flag, and the loop repeats until it passes the benchmark or hits the round limit.

## Files
- **Benchmark (all projects):** `agent/skills/script-review/benchmark.md`. Language criteria L0-L3 (scored per line, 1-10; L0 = a complete beginner gets the full point), content criteria C1-C6 (pass/fail), spelling conventions, reference examples. Add real presenter lines to the reference table when the user gives them.
- **Lessons (all projects):** `agent/skills/script-review/lessons.md`. Every rule learned from the user's notes, with bad and better lines. The writer reads it before every draft and rewrite; reviewers fail any line that breaks it.
- **Lessons (one business):** `projects/<id>/scripts/lessons.md`. Same, for offer-specific messages (refunds, prices, claims).
- **Project rules:** `projects/<id>/scripts/compliance.md`. Blocking rules for that business (claims, prices, refunds, names). Create it first if missing, from the project's decisions.
- **Script:** `projects/<id>/scripts/<IDEA-ID>.md`, in the format below.
- **Loop:** `agent/workflows/script-review.js` (also at `.claude/workflows/script-review.js`).

## Script file format
```
# <IDEA-ID>: <title in English>

| Field | Value |
|---|---|
| Platform / format | Reel, 60-90 s (no hard limit; a complete idea beats a short one) |
| Goal | ... |
| Objection / fear | ... |
| Give or Ask | ... |
| CTA asset | ... |

## Script
| ID | Point (English) | On screen | Spoken (Arabic) |
|---|---|---|---|
| S0 | Stop the scroll | (visual, first 3 seconds) | — |
| L1 | what a beginner must understand from this line | ... | ... |

## Hook variations
| ID | Hook | Headline components | Call-out |

## Notes
(English: compliance notes, placeholders, what the trainer must check)

## Review log
```
Hook variations get ids H1, H2… and are scored like lines.

## Steps
1. Use the `work` skill rules: one project id only; read and write through `python -m alexai project ...`.
2. Brain first for the content: search the content notes (`leads-content-unit`, `leads-headline-components`, `leads-retain-lists-steps-stories`, `leads-call-to-action`, …). Use `prompts/content-writer.md` as the writing guide.
3. Read both lessons files first. Write each line's Point in plain English first, then say that whole point in white Arabic, as you would explain it to someone who has never traded. Never fusha, never a word-for-word translation of the Point, never drop a reason to save time.
4. Run the loop:
   `Workflow({ scriptPath: "agent/workflows/script-review.js", args: { project: "<id>", script: "<IDEA-ID>", maxRounds: 3, threshold: 9, maxWords: 280 } })`
   Lines that pass every reviewer are locked and never touched again; the word budget is counted by command and enforced in code.
5. Read the final file yourself. Report: pass or not, scores per round, what changed, anything left for the user or the trainer. Do not claim it passed if `passed` is false.
6. The user (or a presenter) is the final judge. **Every note they give becomes a lesson before you fix the script:** add it to `lessons.md` (general: language, clarity, structure) or `projects/<id>/scripts/lessons.md` (offer-specific), with the next id, the rule in one sentence, why, and the bad and better lines. Then fix the script, then rerun the loop. A note that isn't recorded as a lesson will come back.
7. If a note conflicts with the offer or the compliance rules, say so and propose wording that is both clear and true; record the agreed wording as the lesson.
