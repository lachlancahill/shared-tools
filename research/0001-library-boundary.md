# 0001 — Two libraries, no consumer state

- Date: 2026-11-07
- Status: accepted

## Context

The private legal-assistant project's research/0035 and 0037 call for a shared
reader so the chat app can use NZ law without forking an NCA tutor. The existing
weekly jobs already publish the snapshot. The extraction follows their API,
without adding a microservice or a second copy of the reader.

## Decision

- `legal-core`: citation parsing, resolution, decision parsing and NZ names. No dependencies.
- `legal-corpus`: snapshot/profile, resolution, read, graph, search, reasons and verify.
  DuckDB, LanceDB, PyArrow and NumPy are its only direct dependencies besides core.
- The consumer owns process-wide loading, reloads, credentials and model clients.
  Semantic search receives explicit embedding/reranking callables that return their
  cost; `nz_needed` receives a loader. NZ can also be the primary corpus.
- Profiles own corpus URIs and links. The default private bucket name can be public;
  bucket credentials and source data cannot. Local tests need neither.
- Keep the original parser and checker regression tests; add local semantic-search
  tests and synthetic NZ reader tests. Real NZ PDFs/XML and ingest-stage tests stay
  with the private job. Copied snippets in parser regression strings are not a corpus.
- Skills for chat will be packaged here when its tool group is built; the NCA
  comparison skill and canon are not that skill and stay in the tutor.

## Why

A parser-only consumer should not pay for a graph/search stack. Neither package
should import a web app, a model SDK or an account's secret store. Moving both
consumers onto one implementation is the point, rather than publishing a copy.

## Alternatives considered

- One package: forces citation-only ingest consumers to install the search stack.
- A service: adds provisioning and auth without avoiding snapshot load time.
- Publishing source fixtures: unnecessary, with unresolved NZ source terms.

## Consequences

Consumers must pin both packages to the same commit. During this initial extraction
legal-assistant uses editable path sources; it cannot deploy until the library is
committed/pushed by Lachlan and those sources are replaced with a git pin.
The corpus format remains the weekly jobs' current format. A breaking format change
needs a coordinated dependency bump, since consumers follow current.json.
