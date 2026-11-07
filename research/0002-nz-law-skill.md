# 0002 — Shared NZ research instructions and tool contracts

- Date: 2026-11-07
- Status: accepted; published in `29f3326`

## Context
The reader is published, but chat still needs NZ-only research instructions and
tool contracts. Its deferred tools cannot depend on the private tutor's registry.

## Decision
Package a lightweight `legal_corpus.nz_skill` contract and a Markdown resource.
It imports neither a corpus nor a provider. Consumers own dispatch, access,
read-history recording, charges and checker display. The six research tools do
not include the tutor's NCA comparison canon.

## Why
Both instructions and schemas should have one maintained source, without making
an ordinary chat import DuckDB or load a snapshot. A checked citation means that
the source and pinpoint exist, not that the authority supports the proposition.

## Alternatives considered
Copy the tutor's skill: rejected because its NCA framing and canon are wrong for
NZ litigation, and the copies would drift.

## Consequences
The consumer must publish/pin this addition before deploying it. Source fixtures
and account permissions stay out of this public package. Revocation guidance is
machine-written from the PCO text, not reviewed by a lawyer.
