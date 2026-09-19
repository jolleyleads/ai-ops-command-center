# Outreach + Enrichment Directive

Goal: move a prospect through discovery -> verification -> enrichment -> qualification -> outreach readiness.

Required lead input:
- company_name
- at least one evidence/source URL when a factual claim is asserted

Rules:
- Normalize deterministic fields before AI reasoning.
- Deduplicate before enrichment.
- Keep raw source facts separate from AI inferences.
- AI may classify, summarize, and choose a next action; it may not manufacture missing facts.
- A contact is outreach_ready only when the configured required fields pass verification.
- Sending is a separate execution action and is never implied by content generation.
- On uncertainty, return needs_verification with reasons.
