# Research & design decisions

Read this before changing the shared packages. Consumer-specific decisions stay
with the consumer; this index covers the reusable boundary.

- [0001 — Two libraries, no consumer state](0001-library-boundary.md) — legal-core is dependency-free; legal-corpus takes model callables, owns one snapshot, and leaves singleton loading and credentials to consumers. No real NZ source fixtures are published.
- [0002 — NZ law skill](0002-nz-law-skill.md) — Shared NZ-only instructions and six research tool contracts stay lightweight; consumers own permission gates, dispatch, costs and citation-check display.
- [0003 — NZ source identity](0003-nz-source-identity.md) — Extract HTML footnotes before splitting paragraphs; graph defaults follow one named instrument, not the interactive HCR assumption.

## Debug notes

- [2026-11-07 — NZ tools smoke-test review](debug/2026-11-07-nz-tools-smoke-review.md) — Hansen pinpoints return footnotes, bare conduct references pollute HCR edges, and year-bearing short conduct names fail; revoked notes are deliberate. Investigation only, fixes outstanding.
- [2026-11-07 — A model hunted for a rule we do not hold](debug/2026-11-07-agent-hunting-old-rules.md) — 55 tool calls on `r 138`: the reader now explains old numbering, and the skill says when to stop and to quote provisions as nested lists. Local, unpublished; effect on models not yet measured.
- [2026-11-07 — The number filter hid old rules from the checker](debug/2026-11-07-checker-missed-old-hcr-rules.md) — `r 138 of the High Court Rules` produced no citation at `29f3326`; the finder must keep named references so the checker can flag them, and the graph drops impossible numbers. Published in `de97f16`.
- [2026-11-07 — Explicit HCR numbers](debug/2026-11-07-explicit-hcr-numbers.md) — Named current High Court Rules must pass the same numbering check as bare rules, so old undotted references cannot bypass it; published in `29f3326`, and its placement is corrected by the note below.
