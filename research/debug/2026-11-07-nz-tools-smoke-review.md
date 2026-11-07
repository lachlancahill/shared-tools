# NZ tools smoke-test feedback reviewed — 2026-11-07

## Symptom

Read-only review of chat conversation `2f7b353f-7290-44dd-8b1a-acf115ec9757`
("NZ Law Tools Test"), assistant message `340C3XF6n1BT6JUs0UsR`, completed at
06:05 UTC. The new feedback is in the answer and tool previews, not the suggestions
collection (which has no new entries from this run). The model also wrote its
conclusions into the project's `PROJECT.md`; this review did not change that file.

The model reported instrument collisions in the provision citator, unavailable
former wording of revoked rules, and conduct-rule naming limitations. Its working
notes repeatedly noticed incorrect Hansen pinpoint text but dismissed it in the
final report.

## Cause

Confirmed against published NZ snapshot `snapshots/2026-11-07T0422`:

### 1. Hansen pinpoints resolve to footnotes, not reasons (highest priority)

- `[2007] NZSC 7#104` contains a 55-character case-reference footnote, not the
  proportionality analysis in the judgment's actual paragraph 104.
- Units 85 and 120 likewise contain footnotes, labelled as paragraphs and attributed
  to Tipping J.
- Unit 1 contains 258,181 characters, including the actual numbered body paragraphs
  2, 85, 104 and 120, through to the judgment's conclusion and first footnote.
- The stored split is wrong, not merely a display convention. The reader's `*`
  marker means **requested unit**, not footnote, contrary to the model's explanation.
- The transcript's citation check marks Hansen at `[104]` verified. Existence/read
  checks cannot protect against a source unit whose number identifies the wrong text.

The shared splitter (`legal_core.decisions._marker_chain`) chooses an ordered chain
of numbering candidates, preferring later candidates on its backward pass. The
stored result is consistent with choosing the appended footnote sequence instead
of the body sequence. Reproduce on the original extracted source before settling
the parser fix; do not special-case Hansen in the reader.

### 2. Provision graph defaults bare conduct references to HCR

`cases_citing_provision("HCR r 8.7")` reproduces the reported 204 results, headed by
`[2026] NZCA 376`. The query in `legal_corpus.graph.citing_provision_rows` **does**
filter `i.statute = ?`; the model's diagnosis that it ignores the instrument is wrong.

The stored edges for this case explain the false positive:
- Paragraph 8 explicitly names the conduct rules and is correctly linked to them.
- Paragraphs 9, 10 and 15 use "the Rules" or bare `r 8.7` and are stored as HCR links.
- Re-running `find_rule_references` on those paragraphs reproduces the attribution.

`ingest.graph._edges_for` in legal-assistant processes paragraphs independently and
passes HCR as the default. It does not carry the document's defined instrument into
later paragraphs. Number-shape filtering cannot distinguish HCR 8.7 from conduct 8.7.
This also affects answer checking: the transcript's explicit prose "conduct rule
8.7" was linked to revoked HCR 8.7.

### 3. Year-bearing short conduct names do not resolve

`Lawyers: Conduct and Client Care Rules 2008 r 13.1` resolves to nothing; `RCCC r 13.1`
and the full official title resolve correctly. `NZ_STATUTE_NAMES` has the short
forms without `2008`, not with it. This is a small naming gap, not a requirement to
always supply the full title.

### Not a defect: revoked text and citation years

Revoked HCR provisions intentionally hold the PCO's dated revocation note, not a
historical consolidation. Historical text would be a new source/versioning feature;
do not restore old wording as if current. The skill already explains this limitation.

`[1992] NZCA 322` is not an alternative spelling of `[1991] NZCA 322`. A report's
publication year does not replace a neutral citation's decision year. Use a proper
neutral or report citation; no fuzzy year fallback is warranted.

## Fix / next work

Investigation only: no runtime code, source data, suggestion statuses, project notes,
consumer pins or deployments changed. Local shared-tools baseline: 178 tests pass.

Recommended order:
1. Reproduce/fix the source splitting and audit other footnote-chain cases, then
   rebuild affected source/search/graph data. Regression tests need genuine duplicate
   paragraph/footnote sequences, not only the reader's synthetic fixtures.
2. Resolve document-level rule context during graph construction, preserving explicit
   instrument names and declining ambiguous attribution rather than blindly applying
   HCR. Audit collisions and rebuild edges. Keep parser behavior for interactive bare
   HCR queries separate from evidence for ingest links.
3. Add the missing short conduct aliases with `2008`, and document `RCCC` as a useful
   supported spelling. This is a shared-tools change.
4. Recheck checker handling of explicit "conduct rule" wording and correct the model's
   misleading persisted project notes, with the project owner's knowledge.

The chat checkout still pins both packages to `de97f16`, not pushed `febd5ee`.
The smoke test's old "No section 138" response confirms that it did not exercise the
new stop/old-number guidance. Updating the consumer pin and rerunning normal and
adversarial prompts is still needed; a push here does not update chat automatically.

Coordination used OpenCode synthetic messages. The other active agent owns chat
naming/project-startup/sidebar timing; no files in that checkout were edited here.
