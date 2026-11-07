"""
New Zealand names, shared by the NZ ingest job and the app (research/0024).

NZ statutes are identified by their title, year included ("Crimes Act 1961"), which
is how NZ courts cite them and cannot collide with a Canadian statute id (a chapter
citation, or "Constitution Act, 1867" with its comma).
"""

import re

NZBORA = "New Zealand Bill of Rights Act 1990"

HIGH_COURT_RULES = "High Court Rules 2016"
DISTRICT_COURT_RULES = "District Court Rules 2014"
CONDUCT_RULES = "Lawyers and Conveyancers Act (Lawyers: Conduct and Client Care) Rules 2008"

# Secondary legislation searched by default (research/0036). Other instruments stay
# Tier B: there are thousands of them and older decisions cite them, but a litigation
# question turns on the court's rules and the conduct rules.
TIER_A_SECONDARY = frozenset({HIGH_COURT_RULES, DISTRICT_COURT_RULES, CONDUCT_RULES})

# Short names NZ judgments use, where the name alone is unambiguous in NZ writing.
# "the Bill of Rights" is the NZ Act here, as "the Charter" is Canada's in the
# Canadian corpus.
NZ_STATUTE_NAMES: dict[str, str] = {
    "New Zealand Bill of Rights": NZBORA,
    "NZ Bill of Rights": NZBORA,
    "Bill of Rights Act": NZBORA,
    "Bill of Rights": NZBORA,
    "NZBORA": NZBORA,
    "BORA": NZBORA,
    # Court rules are cited by acronym, and "r 5.17" is read as the High Court's
    # rules in the courts the corpus holds (research/0036).
    "HCR": HIGH_COURT_RULES,
    "DCR": DISTRICT_COURT_RULES,
    # The conduct rules are cited short in professional-responsibility writing.
    "Conduct and Client Care Rules": CONDUCT_RULES,
    "Conduct and Client Care Rules 2008": CONDUCT_RULES,
    "Lawyers: Conduct and Client Care Rules": CONDUCT_RULES,
    "Lawyers: Conduct and Client Care Rules 2008": CONDUCT_RULES,
    "RCCC": CONDUCT_RULES,
}

_YEAR_SUFFIX = re.compile(r"\s+\d{4}$")

# A citation key is New Zealand's if it is an NZ report, an NZ neutral citation, or
# an NZ court file number. Both corpora route citations by it: the answer checker
# sends these to the NZ corpus, and the NZ job never matches them against Canada.
NZ_KEY = re.compile(
    r"\b(?:NZLR|CRNZ|NZAR|HRNZ|NZFLR|ELRNZ|NZBORR|NZRMA|ERNZ|PRNZ|TCLR|NZCPR)\b"
    r"|^\[\d{4}\] NZ|^(?:CA|SC)\d+/\d{4}|^(?:CIV|CRI)-\d{4}"
)


def year_less_names(in_force_titles: list[str]) -> list[tuple[str, str]]:
    """
    "Crimes Act" for "Crimes Act 1961": courts drop the year once an Act is named.

    Only titles in force are considered, and only a short name exactly one of them
    has: "Crimes Act" is the 1961 Act (the 1908 one is repealed), while a short
    name two Acts in force share is left out rather than guessed.
    Returns (statute id, short name) pairs, ready for `StatuteNames`.
    """
    owners: dict[str, set[str]] = {}
    for title in in_force_titles:
        short = _YEAR_SUFFIX.sub("", title)
        if short != title:
            owners.setdefault(short, set()).add(title)
    return [(next(iter(ids)), short) for short, ids in owners.items() if len(ids) == 1]
