# AI Ops DOE Directives

AI Ops uses a Directive-Orchestration-Execution architecture.

Rules:
1. Directives define policy, inputs, outputs, evidence requirements, and failure behavior.
2. The orchestrator chooses a route. It must never invent evidence.
3. Execution code performs deterministic validation, normalization, deduplication, state transitions, and external API calls.
4. Every step returns a structured result and is logged in the workflow trace.
5. A failed verification stops downstream outreach. No guessed email, phone, company fact, permit, or contact may be promoted to verified.
6. External services may provide data or transport, but workflow state and automation decisions remain owned by AI Ops.
