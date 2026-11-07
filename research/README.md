# Research & design decisions

Read this before changing the shared packages. Consumer-specific decisions stay
with the consumer; this index covers the reusable boundary.

- [0001 — Two libraries, no consumer state](0001-library-boundary.md) — legal-core is dependency-free; legal-corpus takes model callables, owns one snapshot, and leaves singleton loading and credentials to consumers. No real NZ source fixtures are published.
- [0002 — NZ law skill](0002-nz-law-skill.md) — Shared NZ-only instructions and six research tool contracts stay lightweight; consumers own permission gates, dispatch, costs and citation-check display.

## Debug notes

- [2026-11-07 — Explicit HCR numbers](debug/2026-11-07-explicit-hcr-numbers.md) — Named current High Court Rules must pass the same numbering check as bare rules, so old undotted references cannot bypass it; fix is local, not yet published.
