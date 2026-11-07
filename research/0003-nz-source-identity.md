# 0003 — Preserve source identity before checking citations

- Date: 2026-11-07
- Status: accepted

## Context
The NZ smoke test exposed HCR links to conduct-rule passages and Hansen pinpoints
that returned footnotes. The checker cannot identify corrupt source-unit numbering.

## Decision
Fix Hansen at NZLII HTML extraction in the private ingest job, not by changing the
shared paragraph splitter. The original HTML distinguishes body footnote references
(`fnB104`) from the appended notes (`fn104`); flattening those tags destroyed that
distinction. Extract notes separately and attach them to their actual body paragraphs,
using the existing PDF-extraction footnote marker format. Re-extract HTML into a new
HTML-only cache, leaving the PDF and paid historical OCR caches alone.

For graph construction, infer a bare rule's instrument only when the document names
one rules instrument. If several are named, keep explicit references but omit ambiguous
bare ones. Interactive queries retain their documented HCR default. The shared parser
also recognises explicit "conduct rule" wording and the year-bearing short conduct names.

## Why
Source markup is evidence; guessing whether a numbered line is a footnote after
flattening is not. A document naming conduct rules must not inherit the interactive
HCR assumption. Missing an ambiguous edge is safer than asserting the wrong authority.

## Alternatives considered
- Change the shared paragraph-chain heuristic: treats a source extraction failure as
  a generic numbering problem and risks Canadian quoted-statute parsing.
- Filter suspicious citator results at read time: leaves incorrect graph counts and
  other consumers intact.
- Re-extract all PDFs: unnecessary and expensive; only HTML extraction changed.

## Consequences
Both consumers need one new shared-tools pin, and NZ needs a new snapshot. Validate
Hansen's actual paragraph 104 and Chevalier's conduct links before promotion. Existing
model-written project notes need correction rather than being treated as source truth.
