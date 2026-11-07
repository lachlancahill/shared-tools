# A model hunted for 4½ minutes for a rule we do not hold — 2026-11-07

## Symptom
In the first signed-in chat test, "What does r 138 of the High Court Rules say? Cite
it." took 55 tool calls over about 4½ minutes (DeepSeek V4.1 Flash, high effort, $0.05).
It tried `HCR r 1.38`, `High Court Rules 1985 r 138`, `SR 1985/277 r 138` and other
variations, then web searches, `fetch_url` and `browse`. Its answer quoted the old rule
from outside the corpus. The citation check correctly marked `r 138` "not in the corpus".

The prompt was adversarial, written to exercise the checker. The question it exposed is
still real: what stops a model looking for something the corpus cannot give it?

## Cause
Nothing told it to stop. The reader said only `No section 138 of High Court Rules 2016
in the corpus`. That does not say why, calls a rule a section, and reads as though
another wording might work. The skill prose covered how to search but not when to give up.

## Fix
- The reader now says an undotted High Court rule is probably pre-2016 numbering, that
  the earlier rules are not held, and that further searches will not find its text.
- The skill says to stop after two or three differently worded attempts, and to look
  outside the held sources only if the user asks.
- The skill also asks for a provision to be quoted as a nested Markdown list, because
  the stored text is flat (legal-assistant's `ingest_nz.legislation._render`).

Local and unpublished. **The prose is instructions to a model, and its effect has not
been measured:** repeat the prompt on testing once this is pinned.

## Not addressed
A bare `r 138` still falls through to a case-name match on the digits (three unrelated
cases). A named instrument we do not hold (`High Court Rules 1985 r 138`) still gets the
generic "Nothing in the corpus matches".
