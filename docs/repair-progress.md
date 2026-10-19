# AutoMake AI six-priority repair record

Base: 00e208e00647bcd4e656bacf4b5637a3ac05532e (observed live 2026-10-19).

1. IN PROGRESS. Runtime logs confirm Gunicorn WORKER TIMEOUT at 2026-10-18 09:45:04 UTC, SIGKILL and replacement worker. Persisted campaign claim remained running; prior expiry was 60 minutes, longer than the acceptance client's 45 minute deadline. Repair bounds campaign execution in a supervised child process, expires dead claims during status polling, adds phase progress and pre-send checks, bounds SDK retries/timeouts, and makes acceptance draft-only regardless of production autosend. No claim of fresh production qualification yet.
2. Pending: customer frontend smoke contract.
3. Pending: authentication experience.
4. Pending: research progress and explicit limits.
5. Pending: route protection and workspace isolation.
6. Pending: campaign outcomes and reporting.

No emails or Calendar writes authorized for verification. Preserve existing data and integrations. Local tests use disposable SQLite; PostgreSQL CI remains required.
