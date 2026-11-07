"""
Turning what the model (or Chelsea) writes into a case or a provision we hold.

Tools take references as people write them: "2019 SCC 65 at para 23",
"[1986] 1 S.C.R. 103", "R v Oakes", "s. 7 of the Charter", "Criminal Code s
265(1)(a)". Citations go through the same parser and index the ingest job used,
so a reference resolves in a tool exactly as it did in the graph. A name that
matches several cases is not guessed: the candidates are returned.
"""

import re
from dataclasses import dataclass, field

from legal_core.citations import (
    base_section,
    clean_text,
    find_case_citations,
    find_model_code_references,
    find_provision_references,
    find_rule_references,
    normalise_case_name,
)

from legal_corpus.snapshot import Corpus

# "Criminal Code s 265(1)(a)", "Charter, s. 7", "RSC 1985, c C-46, section 265".
_STATUTE_THEN_SECTION = re.compile(
    r"^(?P<statute>.+?),?\s+(?:ss?\.?|sections?|rr?\.?|rules?)\s*"
    r"(?P<section>\d[\w.-]*(?:\([^)]{1,6}\))*)\s*$",
    re.I,
)
# "s. 12 of the Interpretation Act": the other order people write a provision in.
_SECTION_OF_STATUTE = re.compile(
    r"^(?:ss?\.?|sections?|rr?\.?|rules?)\s*"
    r"(?P<section>\d[\w.-]*(?:\([^)]{1,6}\))*)\s+of\s+(?:the\s+)?(?P<statute>.+)$",
    re.I,
)
# "at para 23-25" typed without a citation-shaped prefix is handled by the parser;
# this catches "Oakes at para 69" where the case is a name.
_NAME_THEN_PINPOINT = re.compile(
    r"^(?P<name>.+?),?\s+at\s+paras?\.?\s*(?P<para>\d+)(?:\s*[-–]\s*(?P<end>\d+))?\s*$", re.I
)


@dataclass
class CaseRef:
    case_id: str | None
    para: int | None = None
    para_end: int | None = None
    page: int | None = None
    candidates: list[str] = field(default_factory=list)


@dataclass
class ProvisionRef:
    statute_id: str
    section: str  # the base section held, "265"
    written: str  # as referred to, "265(1)(a)"


def resolve_case(corpus: Corpus, reference: str) -> CaseRef:
    """A case from a citation (with any pinpoint) or, failing that, a name."""
    text = clean_text(reference.strip())
    for citation in find_case_citations(text):
        case_id = corpus.case_index.resolve(citation.key)
        if case_id:
            return CaseRef(case_id, citation.para, citation.para_end, citation.page)
    # A case id we issued ourselves ("ONCA:C29360") is also accepted as is.
    if corpus.case(text):
        return CaseRef(text)
    para = para_end = None
    pinpoint = _NAME_THEN_PINPOINT.match(text)
    if pinpoint:
        text = pinpoint.group("name")
        para = int(pinpoint.group("para"))
        para_end = int(pinpoint.group("end")) if pinpoint.group("end") else None
    return _by_name(corpus, text, para, para_end)


def _by_name(corpus: Corpus, name: str, para: int | None, para_end: int | None) -> CaseRef:
    wanted = normalise_case_name(name.strip("*_ "))
    exact = corpus.names.get(wanted, [])
    if len(exact) == 1:
        return CaseRef(exact[0], para, para_end)
    # "Oakes" for "R v Oakes": every Tier A case whose name contains the words,
    # most-cited first, and only a unique match is taken.
    words = [w for w in wanted.split() if w not in {"r", "v", "the", "of", "re"}]
    if not words:
        return CaseRef(None, candidates=exact[:8])
    pattern = "%" + "%".join(words) + "%"
    rows = corpus.sql(
        "select c.case_id from cases c left join citing_counts n using (case_id) "
        "where c.tier = 'A' and lower(c.name) like ? order by coalesce(n.citing, 0) desc limit 8",
        [pattern],
    )
    ids = exact or [r[0] for r in rows]
    if len(ids) == 1:
        return CaseRef(ids[0], para, para_end)
    return CaseRef(None, candidates=ids)


def resolve_provision(corpus: Corpus, reference: str) -> ProvisionRef | None:
    """
    A provision from "s. 7 of the Charter", "Criminal Code s 265(1)(a)", "rule 3.4-10"
    (the Model Code), "HCR r 5.17" or a bare "r 5.17" where the profile reads one
    that way (research/0036).
    """
    text = clean_text(reference.strip())
    rules = (
        find_rule_references(text, corpus.statute_names, corpus.profile.rule_default)
        if corpus.profile.rule_default
        else []
    )
    found = (
        find_model_code_references(text)
        or rules
        or find_provision_references(text, corpus.statute_names)
    )
    if found:
        return ProvisionRef(found[0].statute, base_section(found[0].section), found[0].section)
    shaped = _STATUTE_THEN_SECTION.match(text)
    if shaped:
        statute_id = corpus.statute_names.lookup(shaped.group("statute"))
        if statute_id:
            section = re.sub(r"\s+", "", shaped.group("section"))
            return ProvisionRef(statute_id, base_section(section), section)
    return None


def shared_title(corpus: Corpus, reference: str) -> tuple[str, str, list[str]] | None:
    """
    Why a provision reference did not resolve, when the reason is that its title is
    shared: "Interpretation Act, s 8.1" names the federal Act and eight provinces'.
    Returns (title, section, statute ids), the in-force tier first, or None.
    """
    text = clean_text(reference.strip())
    shaped = _STATUTE_THEN_SECTION.match(text) or _SECTION_OF_STATUTE.match(text)
    if not shaped:
        return None
    ids = corpus.statute_names.sharing(shaped.group("statute"))
    if not ids:
        return None
    ordered = corpus.sql(
        "select statute_id from statutes where list_contains(?, statute_id) "
        "order by tier, statute_id",
        [ids],
    )
    title = shaped.group("statute").strip().rstrip(",")
    return title, re.sub(r"\s+", "", shaped.group("section")), [r[0] for r in ordered]
