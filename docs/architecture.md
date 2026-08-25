# Architecture

## Initial direction

Use a small layered shape once application code begins:

1. Discord adapters translate interactions into application requests and format responses.
2. Application services coordinate complete use cases and own transaction boundaries.
3. Domain code expresses game rules without importing Discord or database libraries.
4. Persistence adapters implement storage using async SQLAlchemy.

Dependencies point inward toward business rules. Discord callbacks must not contain economic
rules or directly coordinate multiple repository writes. A use case that changes related
state succeeds or rolls back as one transaction.

This is a dependency rule, not a request to create one class or interface per layer before a
use case needs it. Organize concrete code around implemented features and extract shared
concepts only when evidence supports them.

## Operational concerns to design with features

- Idempotency for retried Discord interactions and background jobs
- Consistent UTC time handling
- Structured logging without secrets
- Graceful startup, shutdown, and database migration checks
- Explicit handling of Discord rate limits and unavailable dependencies
- Metrics for economic changes and suspicious behavior

## Open questions

- How will configuration and secrets be loaded and validated?
- Are background jobs in-process initially, and what durability do they require?
- What deployment environment and process model will be used?
- Which commands use application commands, prefix commands, or both?
- What is the concurrency strategy when SQLite write contention appears?

