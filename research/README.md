# Research & design decisions

Read this before changing the shared packages. Consumer-specific decisions stay
with the consumer; this index covers the reusable boundary.

- [0001 — Two libraries, no consumer state](0001-library-boundary.md) — legal-core is dependency-free; legal-corpus takes model callables, owns one snapshot, and leaves singleton loading and credentials to consumers. No real NZ source fixtures are published.
