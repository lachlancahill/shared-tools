# Explicit High Court Rules names bypassed the numbering check — 2026-11-07

## Symptom
A consumer's post-publication audit found undotted rule numbers still linked to
the High Court Rules 2016, despite the bare-rule correction. The graph's HCR
links fell from 101,581 to 71,971, but 2,314 undotted links (564 strings),
including numbers such as 136 and 187, remained.

## Cause
`find_rule_references` checked the `part.rule` shape only when falling back to
the default instrument. An explicit name or acronym bypassed it. A historical
"High Court Rules" name can resolve to the current instrument's short name,
but its undotted rule cannot belong to the 2016 numbering. Some sampled
references instead use a part's number as if it were a rule; that is not a
current pinpoint either, and the parser must not guess a correction.

## Fix
Apply the shape check after resolving the instrument whenever its ID is the
High Court Rules 2016, named or defaulted. Keep valid dotted HCR rules and other
instruments' numbering unchanged, including undotted conduct rules. Three
regressions cover an explicit name before/after the number and a mixed list.
This fix is local and requires a new consumer pin/build; it does not rewrite an
already-published graph. No source text or real judgment fixture was added.
