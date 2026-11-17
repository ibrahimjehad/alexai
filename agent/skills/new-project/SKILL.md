---
name: new-project
description: Create a new Alex AI business project (one folder per business, which is also the isolation boundary) and fill in its brief through a short interview. Use when the user wants to start working on a new business, client or offer.
---

# New project

1. Agree on a kebab-case project id with the user, for example `acme-gym`. Check it is not already taken with `python -m alexai project list`.
2. Create the project: `python -m alexai project new <id> --name "<Business name>" --description "<one line>"`.
   This creates `projects/<id>/brief.md`, `decisions.md`, `deliverables/` and `sessions/`.
3. Interview the user briefly. Ask only for what is missing, a few questions at a time:
   - what they sell, the price and how it is delivered
   - who buys it, the customer's pain and dream outcome
   - numbers: revenue, gross margin, CAC, LTGP, leads per month, conversion rate, churn
   - constraints (time, cash, team) and the goal for the next 90 days
4. Write the completed brief with `python -m alexai project write <id> brief.md` (pass the content on stdin). Keep the template's headings, and write `unknown` for anything the user does not know yet.
5. Summarise the brief and suggest a first strategy session (`work` skill), for example "offer audit" or "lead channel choice".

Do not read any other project's folder.
