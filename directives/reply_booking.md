# Reply qualification and booking directive

## Goal
Turn a verified inbound reply into a controlled next action without allowing the LLM to invent interest, dates, attendees, or booking success.

## Orchestration
The LLM may interpret unstructured reply text and propose exactly one classification: interested, not_interested, question, or unclear. For an interested reply, it may extract explicitly supplied scheduling details and propose a booking request. It may draft an answer to a question using only validated workflow evidence.

## Deterministic execution
Code owns stop rules, classification conflict checks, required booking fields, calendar availability checks, event creation, receipt validation, state transitions, and persistence.

An explicit opt-out or negative-interest signal cannot be overridden by the LLM. A question is not booking-ready merely because the LLM suggests a meeting. Booking requires validated interest plus explicit start, end, timezone, and attendee email. An appointment is not booked until the calendar provider returns a durable event ID.

## State routing
- not_interested: close outreach; no more automated sends.
- question: queue/evaluate a grounded response; do not book.
- unclear: human review or a single non-assumptive clarification; do not book.
- interested: continue to booking readiness.
- booking_ready: calendar availability must be checked before creation.
- booked: only after a validated provider receipt.
