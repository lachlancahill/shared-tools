"""
Whose reasons a passage is in, and whether they speak for the Court
(research/debug/2026-10-01-drill-review.md).

The ingest labels a decision's first reasons "majority" whatever their size, so in
Mikisew Cree (2018 SCC 40) three judges of nine read as the Court, and both halves
of Singh's 3–3 split are "unknown". The size is counted here instead: a set of
reasons is a majority only if more than half the bench signed it.

Who signed comes from two places the ingest keeps: the authors line ("Karakatsanis
J. (Wagner C.J. and Gascon J. concurring)"), and, in older reports, the statement
before it ("The reasons of Dickson C.J. and Lamer and Wilson JJ. were delivered
by", kept as `joined`). The bench is `cases.judges`.
"""

import re


def judges_in(authors: str, bench: list[str]) -> int:
    """
    How many of the bench signed these reasons: each judge's surname ("Wagner" from
    "Wagner, Richard") looked for in the authors line ("Karakatsanis J. (Wagner C.J.
    and Gascon J. concurring)"), in any case ("BEETZ J.").
    """
    authors = authors.replace("’", "'")
    surnames = {judge.split(",")[0].strip().replace("’", "'") for judge in bench if judge.strip()}
    return sum(
        1
        for name in surnames
        if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", authors, re.IGNORECASE)
    )


# Judicial titles and notes around the names in an authors line or a "delivered by"
# statement: what is left, split on commas and "and", is one name each.
_NOT_NAMES = re.compile(
    r"\((?:dissenting|concurring|partially concurring)[^)]*\)|\bconcurring\b"
    r"|\bthe Chief Justice\b"
    r"|\b(?:C\.J\.C\.|C\.J\.|JJ\.A\.|J\.A\.|JJ\.|J\.)",
    re.IGNORECASE,
)


def names_given(text: str) -> int:
    """
    How many judges a line names, without consulting the bench: "Karakatsanis J.
    (Wagner C.J. and Gascon J. concurring)" names three. Compared with the bench
    matches, it shows when the bench list is incomplete.
    """
    # A bracket separates names as a comma does: "Karakatsanis J. (Wagner C.J. ...".
    cleaned = re.sub(r"[()]", ",", _NOT_NAMES.sub(" ", text.replace("’", "'")))
    # Each name once: the authors line and the "delivered by" statement often repeat them.
    names = {" ".join(part.split()).casefold() for part in re.split(r",|\band\b", cleaned)}
    return sum(1 for name in names if re.search(r"\w{2,}", name))


def signed_by(segment: dict, bench: list[str]) -> int:
    """How many judges signed a set of reasons: all of them for "the judgment of the Court"."""
    joined = segment.get("joined") or ""
    if joined.casefold() == "the court":
        return len(bench)
    return judges_in(f"{segment['authors']} {joined}", bench)


def classify(segments: list[dict], bench: list[str]) -> dict[str, tuple[str, int]]:
    """
    Each set of reasons' kind and how many signed it, by its authors line.
    Dissents and concurrences keep their labels; "majority" and "unknown" are
    decided by size, but only where the counts settle it:

    * reasons that more than half the bench signed are the **majority**, and the
      other unlabelled reasons beside them are **separate** reasons;
    * when no set of reasons could reach a majority, even if every judge the
      counts miss had joined it, each unlabelled set is a **plurality**;
    * otherwise the stored label stands. A report naming only each writer cannot
      say who joined whom, and one name is not one judge.

    Nothing is decided when the text names a judge the bench list lacks: the list
    is incomplete, and a count against it would be wrong.
    """
    signed = {s["authors"]: signed_by(s, bench) for s in segments}
    # Every name the text gives must be on the bench, or the bench list is short
    # (Grdic v The Queen lists 4 of its 7 judges) and no count can be trusted.
    complete = all(
        (s.get("joined") or "").casefold() == "the court"
        or names_given(f"{s['authors']} {s.get('joined') or ''}") <= signed[s["authors"]]
        for s in segments
    )
    if not complete:
        return {s["authors"]: (s["kind"], signed[s["authors"]]) for s in segments}
    missing = max(len(bench) - sum(signed.values()), 0)
    has_majority = bool(bench) and any(n * 2 > len(bench) for n in signed.values())
    no_majority = bool(bench) and all((n + missing) * 2 <= len(bench) for n in signed.values())
    kinds = {}
    for segment in segments:
        kind, n = segment["kind"], signed[segment["authors"]]
        if kind in ("majority", "unknown"):
            if has_majority:
                kind = "majority" if n * 2 > len(bench) else "separate"
            elif no_majority:
                kind = "plurality"
        kinds[segment["authors"]] = (kind, n)
    return kinds


def describe(kind: str, signed: int, bench: list[str]) -> str:
    """The words shown for a kind: "plurality: 3 of 9 judges, no majority"."""
    if kind == "plurality":
        return f"plurality: {signed} of {len(bench)} judges, no majority"
    if kind == "separate":
        return f"separate reasons: {signed} of {len(bench)} judges, not the majority"
    return {
        "majority": "majority",
        "concurring": "concurring",
        "dissenting": "DISSENTING",
        "dissenting_in_part": "DISSENTING IN PART",
    }.get(kind, "")
