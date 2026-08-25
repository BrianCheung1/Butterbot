# Testing

## Strategy

- Unit-test pure business rules without Discord or a database.
- Integration-test application services against temporary real SQLite databases.
- Test Discord adapters with narrow fakes at the presentation boundary.
- Exercise complete migrations, constraints, rollback behavior, and transaction atomicity.
- Control clocks and random sources in tests once time or randomness enters the domain.
- Add regression tests before fixing economic exploits or data-loss bugs.

Tests should assert observable outcomes and invariants rather than mirror implementation
details. Concurrency-sensitive use cases need tests for retries, duplicate requests, and
competing updates. PostgreSQL compatibility tests can be added when its driver and CI service
are intentionally adopted.

## Quality gates

The baseline local checks are Ruff linting and formatting, strict Pyright analysis, and
pytest. Coverage is diagnostic; no percentage threshold is chosen yet.

## Open questions

- Which Python 3.13 versions and operating systems will CI cover?
- When should PostgreSQL integration tests become mandatory?
- Which economic invariants should be property-tested or model-tested?
- What performance and load targets represent realistic Discord activity?

