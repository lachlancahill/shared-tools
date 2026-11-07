# The HCR number filter hid old rules from the checker — 2026-11-07

## Symptom
Testing the released `29f3326` against the live NZ snapshot: an answer citing a
rule the High Court Rules 2016 cannot have produced no citation at all, so nothing
warned about it.

| Answer | `verify` at `29f3326` |
|---|---|
| `r 138 of the High Court Rules` | **no citation found** |
| `High Court Rules 2016, r 138` | **no citation found** |
| `HCR r 138` | **no citation found** |
| `s 138 of the High Court Rules` | unverified, "not in the corpus" |
| `r 8.99 of the High Court Rules` | unverified, "not in the corpus" |

A model is likely to repeat old numbering, because older judgments in the corpus
use it. A silent gap is the worst result a checker can give.

## Cause
The previous fix ([explicit HCR numbers](2026-11-07-explicit-hcr-numbers.md))
applied the `part.rule` shape check inside `find_rule_references`, whichever way the
instrument was named. That finder has two callers with opposite needs. The graph
wants only real links, but `verify` needs to see a wrong citation in order to flag it.
The tests pinned the finder's output and did not check the checker's result.

## Fix
The finder returns named references again and filters only a bare `r 138`, which
is not a reference to anything we can identify. The graph build now owns dropping
impossible numbers (`legal-assistant`'s `ingest.graph`), which also covers the `s N`
path behind the audit's last 21 links. Four checker regressions assert the warning;
the three `r` forms fail on the released parser and pass with this change.

Published in `de97f16`, together with the ingest filter (`legal-assistant` `5a7a946`).
The two must stay together: this parser without that filter would put about 2,300
old-number links back in the graph. The live check on testing then marked `r 138`
"not in the corpus".

## Still open
`r 19.5(1) High Court Rules, s 343 Property Law Act 2007` attaches `s 343` to the
rules because no "of" follows it, so a correct citation shows "not in the corpus".
That is a false warning, not a silent pass. Left as it is.
