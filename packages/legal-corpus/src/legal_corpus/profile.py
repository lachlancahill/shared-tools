"""
What differs between the two corpora the app reads (research/0024 §7).

The Canadian corpus and the New Zealand one are built by the same stages and read
by the same corpus layer (`search`, `reader`, `graph`, `resolve`). What differs is
small and lives here: where the snapshot is, which court leads, how a pinpoint is
written, which short statute names the courts use, and where the reader's pages
are. Every field differs between the two today; nothing here is a setting for a
corpus that does not exist.
"""

import os
from dataclasses import dataclass, field

from legal_core.citations import BUILT_IN_STATUTE_NAMES
from legal_core.nz import HIGH_COURT_RULES, NZ_ANSWER_STATUTE_NAMES


@dataclass(frozen=True)
class Profile:
    name: str
    corpus_uri: str
    apex: str  # the court whose decisions rank first
    appellate: tuple[str, ...]  # the courts that rank next
    # How a paragraph pinpoint is written in this jurisdiction: "para 69", "[104]".
    pinpoint: str
    # What the reader's pages are under: "/cases/...", "/nz/cases/...".
    link_prefix: str
    statute_names: dict[str, str] = field(default_factory=dict)
    # NZ courts drop an Act's year once it is named ("the Crimes Act").
    year_less_names: bool = False
    # What the corpus's spine is called where a tool shows it.
    spine: str = "Syllabus"
    # What `read` says of a case whose text is not held.
    not_held: str = ""
    # Citations a tool takes as naming a case, not a statute.
    case_shaped: str = ""
    # The tiers whose cases can be found by name. Canada's Tier B (trial courts) is
    # left out, as names there collide; NZ's Tier B is its citation-only cases,
    # found by name ("Noort") because they are cited by name.
    named_tiers: tuple[str, ...] = ("A",)
    # The instrument a bare "r 5.17" refers to, where the corpus's courts read it
    # that way. None means never guess: only a named instrument resolves.
    rule_default: str | None = None

    def para(self, number: int) -> str:
        return self.pinpoint.format(n=number)

    def unit(self, kind: str, number: int) -> str:
        """A unit as the tools name it: "para 69" or "[104]", "p. 520", "passage 3"."""
        if kind == "paragraph":
            return self.para(number)
        return f"{'p.' if kind == 'page' else 'passage'} {number}"


CANADA = Profile(
    name="canada",
    corpus_uri=os.environ.get("CORPUS_URI", "gs://nca-tutor-lc-corpus"),
    apex="SCC",
    appellate=("ONCA", "BCCA", "NSCA", "YKCA", "FCA", "CMAC"),
    pinpoint="para {n}",
    link_prefix="",
    statute_names=BUILT_IN_STATUTE_NAMES,
    not_held=(
        "This case is held as metadata only (Tier B): its text is not in the corpus. "
        "The research skill's live A2AJ tools can fetch it."
    ),
    case_shaped=r"\b(?:SCC|SCR|S\.C\.R|ONCA|BCCA|FCA|NSCA|v\.?)\b",
)

NEW_ZEALAND = Profile(
    name="nz",
    corpus_uri=f"{CANADA.corpus_uri}/nz",
    apex="NZSC",
    appellate=("NZCA",),
    pinpoint="[{n}]",
    link_prefix="/nz",
    statute_names=NZ_ANSWER_STATUTE_NAMES,
    year_less_names=True,
    spine="NZ comparison canon",
    not_held=(
        "This decision is not held: Judicial Decisions Online does not have it (it starts in "
        "2003 for the Court of Appeal and 2005 for the High Court, and lacks some later "
        "judgments too, Supreme Court ones included), and it has not been fetched from NZLII, "
        "or NZLII's copy could not be read or not yet confirmed as this decision. "
        "Read how later courts state it: nz_cases_citing lists the held decisions that cite it, "
        "with their paragraphs."
    ),
    case_shaped=r"\b(?:NZSC|NZCA|NZHC|NZLR|CRNZ|UKPC|v\.?)\b",
    named_tiers=("A", "B"),
    rule_default=HIGH_COURT_RULES,
)
