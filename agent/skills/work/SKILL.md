---
name: work
description: Run an Alex AI strategy session on exactly one business project, applying Hormozi frameworks from the brain to offers, leads, sales or pricing, and recording decisions and deliverables in that project only. Use when the user wants to brainstorm, plan or build strategy for a specific business.
---

# Strategy session (one project)

## Start
1. Confirm the project id. If none fits, list projects or use the `new-project` skill. Work on that one id only for the whole session.
2. Load the context with `python -m alexai project read <id>`, which returns the brief, the decisions and the file list. Read deliverables only when they are relevant.
3. Agree on the session goal in one sentence.

## Work loop
1. **Brain first.** Run `python -m alexai brain search "<question>" --json`, then `brain get <id>` on the best hits.
2. Name the framework and apply it to this business. Cite notes as `[note-id | source-id, ref]`.
3. Ask for the numbers the framework needs. Show your calculations and label every assumption.
4. Push back on weak ideas, then propose stronger options and rank them.
5. Label anything not found in the brain as **general knowledge**, and note what material would fill the gap.

## Record
- For each accepted decision, run `python -m alexai project decide <id> "<decision>. Why: <reason>. Framework: <note-id>"`.
- Save artifacts (offer stacks, scripts, ad copy, plans) with `python -m alexai project write <id> deliverables/<name>.md`.
- At the end, write a short session log with `python -m alexai project write <id> sessions/<YYYY-MM-DD>-<topic>.md` (goal, what was decided, open questions, next actions).

## Boundaries
- Read only `brain/` and `projects/<id>/`. Never open another project.
- Do not edit `brain/`. If knowledge is missing or wrong, suggest a feed session instead.
