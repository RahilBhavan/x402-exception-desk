---
title: "A payment timeout is not a failed payment"
description: "How I built and tested a synthetic settlement-to-delivery exception desk without hiding a failed policy hypothesis."
date: 2026-09-22
---

# A payment timeout is not a failed payment

A payment request times out. The customer has no receipt. The seller has no final answer. Should the system charge the customer again?

No. A timeout describes what the caller observed. It does not prove that the payment failed.

I built a synthetic operations project around that distinction. The project models the evidence between payment authorization, chain observation, report delivery, and refunds. It then asks a second question: which exception should an operator handle first?

The result is a local Python application with 16 cases, 65 events, an independently authored oracle, four queue policies, and a 3,600-scenario sensitivity sweep. No wallet, customer data, live transaction, or Coinbase system is involved.

## The state model keeps separate facts separate

Many payment failures become dangerous when one status field tries to answer several questions. This project keeps four kinds of state separate:

- Payment state records whether the system submitted or observed a payment.
- Delivery state records whether the seller prepared and delivered the report.
- Refund state records approval, reservation, submission, and settlement.
- Exception state records the missing evidence and the actions that remain safe.

The reducer reads an append-only event stream and derives those states. Replaying the same events produces the same projection. Duplicate event IDs do not create a second effect.

The timeout case shows why this matters. The original attempt stays unresolved after the timeout. Late payment evidence attaches to that attempt. The operator may reconcile the attempt, but the system forbids another charge.

```text
request submitted
        |
        v
caller times out ----> outcome remains unknown
        |                         |
        |                         v
        +--------------> reconcile original attempt
                                  |
                                  v
                         late evidence may resolve it
```

## The oracle is separate from the reducer

I wrote expected outcomes in a separate oracle before using the reducer to generate project artifacts. That separation matters. A test that derives both the result and the expected answer from the same function can confirm its own mistake.

Each oracle case declares the expected payment state, delivery state, financial totals, exception type, safe actions, forbidden actions, and closure evidence. The conformance check compares the reducer output with those declarations.

The fixture corpus includes happy paths and operational failures such as:

- an authorization rejection;
- a timeout followed by late success;
- a payment observed without delivery acknowledgment;
- payment evidence reused across two orders;
- a pre-finality observation that becomes invalid; and
- two refunds that compete for the same refundable balance.

## The first policy hypothesis failed

I initially compared FIFO with deadline-first routing. I declared a replacement gate before running the comparison: deadline-first had to reduce overdue cases by at least 15 percent without adding a control failure.

Both policies produced six overdue cases. Deadline-first reduced value-weighted delay, but it did not pass the declared gate. The decision remained FIFO.

That failed hypothesis improved the project. It forced the recommendation to follow the evidence instead of the intended story.

I then added value-first and a hybrid SLA-window policy. Both produced four overdue cases in the initial workload. That result is a useful signal, but it is not enough to recommend either policy for a real operation. The handling times and incident frequencies are synthetic.

## Sensitivity matters more than one ranking

The policy sweep varies seeded workloads, operator capacity, handling-time profiles, evidence delays, and finality delays. It produces 3,600 scenarios.

The output reports distributions and win rates for overdue count, weighted delay, tail delay, unfinished work, and control failures. Every policy in a scenario receives the same workload fingerprint. That identity check prevents an unfair comparison.

The sweep answers a narrower question than production analytics. It shows how the policy ranking changes when the declared assumptions change. It does not estimate Coinbase volume, staffing, loss, or customer behavior.

## The release checks its own evidence

The repository includes one release command:

```sh
python3 scripts/release.py
```

The command runs 67 tests, regenerates the artifacts, runs 26 cross-artifact checks, verifies the PDF, workbook, and video hashes, and builds the ZIP. It also writes a SHA-256 checksum for that archive.

The consistency checks compare run IDs, fixture hashes, oracle hashes, workload hashes, record counts, policy metrics, scenario counts, and synthetic-data labels. They also require the claim boundary that chain evidence does not prove delivery.

## What remains unproven

This is a synthetic simulation. It does not prove that the workload assumptions represent a payment operation. It does not test a live x402 implementation. It does not establish production security, privacy, performance, or authorization controls.

The next meaningful test requires people. The repository includes a fixed operator task protocol for payments or finance-operations practitioners. Reviewers would identify unsafe decisions, missing evidence, unclear terms, and slow navigation. That review has not happened, so the project does not claim it.

## The engineering lesson

The most important design choice was not a queue algorithm. It was the refusal to convert missing evidence into certainty.

A timeout is not a failure. A chain observation is not delivery. A refund approval is not a settled refund. When software preserves those distinctions, an operator can choose a safe next action without inventing facts.

The source, generated evidence, decision memo, demo, and verification commands are available in the project repository.
