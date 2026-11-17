---
id: models-payment-plan-upsell-and-declines
type: tactic
title: 'Payment-plan upsells and fewer declined payments'
author: alex-hormozi
topics: [downsells, upsells, continuity]
sources:
- {id: hormozi-100m-money-models-p06, ref: 'Part 6, ~11:46'}
related: [models-downsell-payment-plan, models-billing-cadence-churn, models-processing-fee-and-backup-payment]
questions:
- "Too many recurring payments fail; how do I recover declined cards?"
- "Should I offer a pay-off discount to customers on installment plans?"
- "What day should I charge customers to avoid failed payments?"
aliases:
- "failed payments"
- "dunning"
- "payment retries"
- "involuntary churn"
updated: '2026-11-16'
---

Periodically re-offer the original paid-in-full discount to people on plans, and align charges with paydays to cut declines.

**Built-in upsell.** During the plan, offer the original prepay discount if they pay off the balance now. Customers forget it exists, and some jump at it. Pay salespeople the same bonus for closing the balance so they follow up. You can also extend the prepay discount through the first 30 days of the relationship to collect more cash up front. People pay slower if allowed to and faster if rewarded.

**Fewer declines.**
- Charge on the customer's payday.
- If a charge fails, retry it several times that day (deposits land at different times). Hormozi recovers about a third of declined payments this way (a tactic from his mentor John).

**When to use.** Any business running payment plans or recurring billing.
