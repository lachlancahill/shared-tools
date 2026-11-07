# The checker missed the Acts an answer was built on — 2026-11-08

## Symptom
A real answer (lachlancahill-com-chat research/0067) relied on "EA s 8" and "CPA s 88"
and said "I read every provision below". It never opened EA s 8 or CPA ss 81, 86, 87, 89
and 92, and no check noticed, because none of those citations were recognized. Ticks also
landed after the wrong number: "r 9.11, 20 working days" and "s 19, 12 jurors".

## Cause
1. `EA` and `CPA` are not known names.
2. "Evidence Act s 8" and "Juries Act s 19" did not resolve either. `year_less_names`
   drops a short name that two in-force Acts share, and tier A holds Acts with no
   recorded repeal (`Evidence Act 1905`, `Arms Act 1846`; 5,128 Acts). Of 3,186 short
   names, 531 looked shared. "Criminal Procedure Act" worked only because it has one Act.
3. The list pattern took any comma and number as another section.

## Fix
1. `NZ_ANSWER_STATUTE_NAMES` adds EA and CPA for `Corpus` only, so the reader and the
   checker take them. The graph build keeps `NZ_STATUTE_NAMES`: in judgments "EA" is an
   anonymised party (*EA v Rennie Cox*) and "CPA" can be CPA Australia or another Act.
   The nz-law skill states what the two mean and asks for other Acts in full.
2. `newest_act_names`, for `Corpus` only: a year-less name is the newest Act of that
   name, if that Act is tier A. "Education Act" stays unresolved, since its newest is
   the repealed 1989 Act. "Newest in tier A" alone would have said 1914. `year_less_names`
   stays for the graph, where an old judgment's "Evidence Act" may mean an old Act.
3. After a singular `s` or `r`, a comma and a number before an ordinary word ends the
   list. Plurals are untouched, so "ss 90, 92 apply" keeps both.

4. A list is one citation for its whole span, and only the first section used to be
   checked, so "ss 90, 92" looked read with s 92 unread. Each section now counts and the
   worst result shows. This applies to the Canadian tutor's answers too.

## Still open
- A bare section takes the last statute named in its sentence, and `;` does not end one,
  so the real answer's "s 166" went to the Evidence Act's Australian subpoena section.
  It shows amber "not read", and opening it exposes the bad cite. Left alone.
- **Tier A is not "in force"**, because `legal-assistant`'s `legislation.py` only sees
  a repeal it has a marker for. A newest Act that was really repealed but has no marker
  still resolves ("Licensing Act" to 1908). Fixing that needs the ingest job.
- The pattern change also applies to the graph once `legal-assistant` moves its pin.
