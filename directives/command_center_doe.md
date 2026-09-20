# Command Center DOE Architecture

## Non-negotiable rule
Never use a large language model for work deterministic software can perform reliably. Architect deterministic systems around the LLM. Reserve the LLM for reasoning, interpretation, judgment, and routing.

## Ownership
- **Directive:** defines qualification, evidence, safety, approval, and transition rules.
- **Orchestration (LLM):** interprets intent and proposes the next allowed workflow route. It never claims execution occurred.
- **Execution (code):** owns API calls, search requests, normalization, deduplication, retries, timeouts, enrichment, sending, scheduling, booking writes, CRM writes, receipts, and durable state.
- **Evidence:** factual claims and promotions require source evidence or deterministic operation receipts.
- **Gates:** code alone authorizes state transitions.

## End-to-end state machine
discovered -> verified -> enriched -> qualified -> outreach_ready -> contacted -> followup_due/responded -> booking_ready -> booked -> crm_synced -> closed

A missing receipt or required evidence blocks advancement. Failure to prove a claim leaves the workflow pending/candidate; it must never be converted into a positive claim by the LLM.

## Module rules
1. Search: LLM may choose search strategy; deterministic providers execute discovery.
2. Verification: source-backed evidence is required; deterministic gate promotes.
3. Enrichment: deterministic APIs retrieve/validate fields; LLM may resolve ambiguity only from supplied evidence.
4. Qualification: deterministic criteria calculate objective qualification; LLM may interpret unstructured evidence.
5. Outreach: LLM may draft language; code validates required fields, approvals, dedupe and sends.
6. Follow-ups: code owns timers, attempt counts, reply checks, stop rules and sending; LLM may draft the message.
7. Reply qualification: LLM interprets meaning; code authorizes the state transition.
8. Booking: code checks availability and creates bookings; LLM never invents availability.
9. CRM: code performs writes and stores receipts/history; LLM never claims a CRM update occurred without a receipt.

## Audit rule
Every state change records from/to stage, gate result, and reason. Side-effect stages require deterministic receipts.
