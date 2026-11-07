"""
Finding case citations and statute references in legal text.

This is the most important module in the project (research/0004 §4). The same
parser runs in two places:

* the ingest job, over every paragraph of every decision, to build the citation
  graph. A2AJ's own citation lists only see neutral citations, which leaves 84%
  of SCC decisions (everything before 2000) with no links at all (research/0002);
* the app, over the model's answer, so that every citation it gives can be
  checked by code before it is shown.

Parsing is deliberately separate from resolution (`resolver.py`): this module
only says "this span is a citation, and this is its canonical key". Whether that
key names a case we hold is the resolver's job.

The parser favours precision over recall. A missed citation is a missing edge;
a wrong one is a false statement in the graph, so a pattern that would match
ordinary prose is left out rather than guarded with heuristics.
"""

import re
from dataclasses import dataclass
from typing import Literal

# --- Normalisation ---------------------------------------------------------

# A2AJ's text keeps a space where italics used to end ("Constitution Act, 1867 ,
# Part III"; "Income Tax Act , R.S.C."). Collapsing it before parsing lets every
# pattern below assume ordinary punctuation. Non-breaking and thin spaces and the
# non-breaking hyphen used in SCC texts ("C‑46") are normalised for the same reason.
_SPACE_BEFORE_PUNCT = re.compile(r"[ \t]+([,.;:)])")
_ODD_SPACES = re.compile(r"[   ]")
_ODD_HYPHENS = re.compile(r"[‐‑]")


def clean_text(text: str) -> str:
    """Return `text` with the typographic noise that would defeat the patterns removed."""
    text = _ODD_SPACES.sub(" ", text)
    text = _ODD_HYPHENS.sub("-", text)
    return _SPACE_BEFORE_PUNCT.sub(r"\1", text)


# --- Case citations --------------------------------------------------------

# Canadian neutral-citation court codes. A fixed list rather than "any capitals"
# because "2019 SCC 65" and "in 2019 CRA 12" look alike to a regex, and only the
# list knows which one is a court. Longest first, so FCA is tried before FC.
_NEUTRAL_COURTS = sorted(
    [
        "SCC",
        "FCA",
        "FC",
        "TCC",
        "CMAC",
        "CHRT",
        "CIRB",
        "CITT",
        "CT",
        "FPSLREB",
        "FPSLRB",
        "OHSTC",
        "SST",
        "TATC",
        "CART",
        "SCT",
        "ONCA",
        "ONSC",
        "ONCJ",
        "ONSCDC",
        "ONLAT",
        "ONWSIAT",
        "HRTO",
        "BCCA",
        "BCSC",
        "BCPC",
        "BCHRT",
        "ABCA",
        "ABKB",
        "ABQB",
        "ABPC",
        "ABCJ",
        "SKCA",
        "SKKB",
        "SKQB",
        "SKPC",
        "MBCA",
        "MBKB",
        "MBQB",
        "MBPC",
        "QCCA",
        "QCCS",
        "QCCQ",
        "QCTDP",
        "QCTAQ",
        "NBCA",
        "NBKB",
        "NBQB",
        "NBPC",
        "NSCA",
        "NSSC",
        "NSPC",
        "NSFC",
        "NSSM",
        "PECA",
        "PESC",
        "PEICA",
        "PEISCTD",
        "NLCA",
        "NLSC",
        "NLTD",
        "NLPC",
        "YKCA",
        "YKSC",
        "YKTC",
        "NWTCA",
        "NWTSC",
        "NUCA",
        "NUCJ",
    ],
    key=len,
    reverse=True,
)

# Foreign neutral citations put the year in brackets: [2004] UKHL 22. The
# Canadian corpus holds none of these cases, but recognising them lets the answer
# checker say "not in our corpus" rather than "not a citation". The New Zealand
# corpus (research/0024) resolves the NZ ones: its courts, and the Privy Council
# for appeals from New Zealand.
_FOREIGN_NEUTRAL_COURTS = [
    "EWCA Civ",
    "EWCA Crim",
    "EWHC",
    "UKHL",
    "UKSC",
    "UKPC",
    "NZSC",
    "NZCA",
    "NZHC",
    "NZEmpC",
    "NZEnvC",
    "NZFC",
    "NZDC",
    "NZYC",
    "HCA",
]

# Law reports, written without their dots. Each entry becomes a pattern that
# accepts the dotted and undotted spellings ("D.L.R." and "DLR").
_REPORTERS = [
    "Admin LR",
    "All ER",
    "Alta LR",
    "App Cas",
    "Imm LR",
    "Man R",
    "Sask R",
    "BCLR",
    "BCAC",
    "CCLT",
    "CCEL",
    "CELR",
    "CRR",
    "CCC",
    "CPR",
    "CTC",
    "DLR",
    "DTC",
    "ETR",
    "FCR",
    "NBR",
    "NSR",
    "OAC",
    "RFL",
    "SCR",
    "WLR",
    "WWR",
    # New Zealand reports (research/0024). Reporters whose pages carry thousands
    # separators ("22 NZTC 19,000", "NZCLC", "NZConvC") are left out: the page
    # pattern would stop at the comma and key the wrong page.
    "NZLR",
    "CRNZ",
    "NZAR",
    "HRNZ",
    "NZFLR",
    "ELRNZ",
    "NZBORR",
    "NZRMA",
    "ERNZ",
    "PRNZ",
    "TCLR",
    "NZCPR",
    "FRNZ",
    "BLR",
    "AC",
    "AR",
    "CR",
    "Ch",
    "FC",
    "KB",
    "NR",
    "OR",
    "QB",
]


def _dotted(abbreviation: str) -> str:
    """
    Turn a reporter abbreviation into a pattern accepting its usual spellings.

    "DLR" accepts "DLR", "D.L.R." and "D. L. R."; "App Cas" accepts "App. Cas.".
    An all-capitals word is spelled letter by letter, and any other word as written.
    """
    words = []
    for word in abbreviation.split():
        if word.isupper() and len(word) > 1:
            words.append(r"\.?\s?".join(re.escape(letter) for letter in word) + r"\.?")
        else:
            words.append(re.escape(word) + r"\.?")
    return r"\s*".join(words)


# New Zealand reports numbered by volume across years ("(1989) 1 PRNZ 451"), where
# the year is only the year of the volume. Courts sometimes write it in square
# brackets ("[1989] 1 PRNZ 451"), so a citation of these with a volume is keyed
# without its year, whatever the bracket, or the two spellings would not meet
# (debug/2026-10-06-nzlii-unmatched.md). NZFLR, NZAR and NZRMA were numbered by
# volume before they were by year ("[1995] NZFLR 145"), which has no volume. NZLR and
# ERNZ restart their volumes each year, so their year stays in the key.
_VOLUME_NUMBERED = {"PRNZ", "CRNZ", "TCLR", "HRNZ", "NZCPR", "ELRNZ", "NZBORR", "FRNZ"} | {
    "NZFLR",
    "NZAR",
    "NZRMA",
}

_REPORTER_PATTERN = "|".join(f"(?:{_dotted(r)})" for r in sorted(_REPORTERS, key=len, reverse=True))
_REPORTER_BY_SPELLING: dict[str, str] = {r.replace(" ", ""): r for r in _REPORTERS}

# New Zealand decisions without a neutral citation (the Court of Appeal before
# about 2005, the High Court before about 2008, and every older decision) are cited
# by court file number, usually with the date: "CA133/06, 2 November 2006",
# "SC CIV 3/2004", "HC Auckland CIV-2010-404-2868, 7 December 2011". A file can
# carry several judgments, so the date is part of the key when it is given.
_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_FILE_NUMBER = (
    r"\b(?:CA\s?(?P<ca_num>\d{1,4})/(?P<ca_year>\d{4}|\d{2})"
    r"|SC\s?(?:(?:CIV|CRI)\s)?(?P<sc_num>\d{1,4})/(?P<sc_year>\d{4})"
    r"|(?P<hc_kind>CIV|CRI)[-\s](?P<hc_year>\d{4})-(?P<hc_registry>\d{3})-(?P<hc_num>\d{1,6}))\b"
    r"(?:,?\s+(?P<f_day>\d{1,2})\s+(?P<f_month>" + _MONTHS + r")\s+(?P<f_fyear>\d{4})\b)?"
)

# "(4th)", "(3d)", "(2d)" series markers.
_SERIES = r"\(\s*(?P<series>\d+)\s*(?:st|nd|rd|th|d)\s*\)"

_CASE_PATTERN = re.compile(
    r"(?P<neutral>\b(?P<n_year>(?:19|20)\d{2})\s+(?P<n_court>"
    + "|".join(_NEUTRAL_COURTS)
    + r")\s+(?P<n_num>\d{1,5})\b)"
    + r"|(?P<canlii>\b(?P<c_year>(?:19|20)\d{2})\s+CanLII\s+(?P<c_num>\d{1,7})\b)"
    + r"|(?P<foreign>\[(?P<f_year>\d{4})\]\s+(?P<f_court>"
    + "|".join(re.escape(c).replace(r"\ ", r"\s+") for c in _FOREIGN_NEUTRAL_COURTS)
    + r")\s+(?P<f_num>\d{1,5})\b)"
    # [1986] 1 S.C.R. 103 / [1949] S.C.R. 1 / [1932] A.C. 562: the year is the volume.
    + r"|(?P<yearvol>\[(?P<y_year>\d{4})\]\s*(?:(?P<y_vol>\d{1,2})\s+)?(?P<y_rep>"
    + _REPORTER_PATTERN
    + r")\s*(?:"
    + _SERIES.replace("series", "y_series")
    + r"\s*)?(?P<y_page>\d{1,5})\b)"
    # (1986), 26 D.L.R. (4th) 200 / 63 S.C.R. 226 / (1882), 7 App. Cas. 829.
    + r"|(?P<volume>(?:\((?P<v_year>\d{4})\),?\s*)?\b(?P<v_vol>\d{1,4})\s+(?P<v_rep>"
    + _REPORTER_PATTERN
    + r")\s*(?:"
    + _SERIES.replace("series", "v_series")
    + r"\s*)?(?P<v_page>\d{1,5})\b)"
    + r"|(?P<file>"
    + _FILE_NUMBER
    + r")"
)

# A pinpoint straight after a citation: ", at para. 23", "at paras. 28-30",
# ", at p. 138", "para 23". "at 138" with no "p." is left alone: it is as often a
# page as a paragraph, and a wrong pinpoint fails the answer check for no reason.
# New Zealand writes paragraph pinpoints in brackets, always after "at": "at
# [23]", "at [23]–[25]". A bare "[23]" is left alone, because a year in brackets
# opens the next citation.
_PINPOINT = re.compile(
    r"\s*,?\s*(?:"
    r"(?:at\s+)?(?:paras?\.?|paragraphs?|¶¶?)\s*(?P<para>\d{1,4})"
    r"(?:\s*(?:-|–|to)\s*(?P<para_end>\d{1,4}))?"
    r"|(?:at\s+)?pp?\.\s*(?P<page>\d{1,5})(?:\s*(?:-|–)\s*(?P<page_end>\d{1,5}))?"
    r"|at\s+\[(?P<bracket>\d{1,4})\](?:\s*(?:-|–|to)\s*\[(?P<bracket_end>\d{1,4})\])?"
    r")"
)

CitationKind = Literal["neutral", "canlii", "foreign", "report", "file"]


@dataclass(frozen=True)
class CaseCitation:
    """
    One case citation found in text.

    `key` is the canonical spelling used for resolution: "2019 SCC 65",
    "[1986] 1 SCR 103", "26 DLR (4th) 200". `start` and `end` index the text the
    parser was given (after `clean_text`), and include any pinpoint.
    """

    key: str
    kind: CitationKind
    year: int | None
    start: int
    end: int
    para: int | None = None
    para_end: int | None = None
    page: int | None = None
    page_end: int | None = None


def _reporter_key(spelled: str) -> str:
    """Map a reporter as written ("D.L.R.", "App. Cas.") to its canonical abbreviation."""
    compact = re.sub(r"[.\s]", "", spelled)
    return _REPORTER_BY_SPELLING[compact]


def _key_for(match: re.Match[str]) -> tuple[str, CitationKind, int | None]:
    """Build the canonical key, kind and year for one `_CASE_PATTERN` match."""
    g = match.groupdict()
    if g["neutral"]:
        return f"{g['n_year']} {g['n_court']} {int(g['n_num'])}", "neutral", int(g["n_year"])
    if g["canlii"]:
        return f"{g['c_year']} CanLII {int(g['c_num'])}", "canlii", int(g["c_year"])
    if g["foreign"]:
        court = re.sub(r"\s+", " ", g["f_court"])
        return f"[{g['f_year']}] {court} {int(g['f_num'])}", "foreign", int(g["f_year"])
    if g["file"]:
        return _file_key(g), "file", None
    if g["yearvol"]:
        reporter = _reporter_key(g["y_rep"])
        volume = f"{int(g['y_vol'])} " if g["y_vol"] else ""
        series = f" ({_ordinal(g['y_series'])})" if g["y_series"] else ""
        year = "" if volume and reporter in _VOLUME_NUMBERED else f"[{g['y_year']}] "
        key = f"{year}{volume}{reporter}{series} {int(g['y_page'])}"
        return key, "report", int(g["y_year"])
    reporter = _reporter_key(g["v_rep"])
    series = f" ({_ordinal(g['v_series'])})" if g["v_series"] else ""
    key = f"{int(g['v_vol'])} {reporter}{series} {int(g['v_page'])}"
    return key, "report", int(g["v_year"]) if g["v_year"] else None


def _file_key(g: dict) -> str:
    """
    "CA133/2006 2006-11-02", "SC3/2004", "CIV-2010-404-2868 2011-12-07": the court's
    file number with a four-digit year, then the date where one is given.
    """
    if g["ca_num"]:
        year = g["ca_year"]
        if len(year) == 2:
            year = ("19" if int(year) > 50 else "20") + year
        key = f"CA{int(g['ca_num'])}/{year}"
    elif g["sc_num"]:
        key = f"SC{int(g['sc_num'])}/{g['sc_year']}"
    else:
        key = f"{g['hc_kind']}-{g['hc_year']}-{g['hc_registry']}-{int(g['hc_num'])}"
    if g["f_day"]:
        month = _MONTHS.split("|").index(g["f_month"]) + 1
        key += f" {g['f_fyear']}-{month:02d}-{int(g['f_day']):02d}"
    return key


def _ordinal(number: str) -> str:
    """Spell a reporter series the way the Canadian Guide does: 2d, 3d, 4th, 5th."""
    n = int(number)
    return {1: "1st", 2: "2d", 3: "3d"}.get(n, f"{n}th")


def find_case_citations(text: str) -> list[CaseCitation]:
    """
    Return every case citation in `text`, in order, each with any pinpoint that follows it.

    `text` should already have been through `clean_text`; the offsets refer to it.
    """
    found = []
    for match in _CASE_PATTERN.finditer(text):
        key, kind, year = _key_for(match)
        end = match.end()
        pin = {"para": None, "para_end": None, "page": None, "page_end": None}
        pin_match = _PINPOINT.match(text, end)
        if pin_match and any(pin_match.groupdict().values()):
            g = {k: int(v) if v else None for k, v in pin_match.groupdict().items()}
            pin = {
                "para": g["para"] or g["bracket"],
                "para_end": g["para_end"] or g["bracket_end"],
                "page": g["page"],
                "page_end": g["page_end"],
            }
            end = pin_match.end()
        found.append(CaseCitation(key, kind, year, match.start(), end, **pin))
    return found


# --- Statute references ----------------------------------------------------

# Statute chapter citations: R.S.C. 1985, c. C-46 / S.C. 2002, c. 1 /
# R.S.O. 1990, c. J.3 / R.S.C. 1985, c. 1 (5th Supp.). They are compared by
# `chapter_key`, never by spelling.
# The province letters after "R.S." or "S.": C, O, B.C., A, M, N.S., N.B., S.
_PROVINCE = r"(?:C|O|B\.?\s?C|A|M|N\.?\s?S|N\.?\s?B|S)\.?"
_JURISDICTION = rf"(?P<j>R\.?\s?S\.?\s?{_PROVINCE}|S\.?\s?{_PROVINCE})"
_CHAPTER_PATTERN = re.compile(
    _JURISDICTION
    + r"\s*(?P<y>\d{4}),?\s*c\.?\s*(?P<ch>[A-Z]{0,2}[-.]?\d+(?:\.\d+)?)"
    + r"(?:\s*\((?P<supp>\d+(?:st|nd|rd|th))\s*Supp\.?\))?"
)

# "s. 7", "ss. 91 and 92", "section 91(2)", "s. 265(1)(a)", "s. 92A", "ss. 175.1 to 177".
_SECTION_NUMBER = r"\d+(?:\.\d+)*[A-Z]?(?:\s?\(\s?[0-9a-zA-Z.]{1,6}\s?\))*"
_SECTION_PATTERN = re.compile(
    r"\b(?:ss?\.|[Ss]ections?|[Ss]ubsections?|ss?(?=\s\d))\s*(?P<list>"
    + _SECTION_NUMBER
    + r"(?:\s*(?:,|and|or|to|-|–)\s*(?!(?:19|20)\d{2}\b)"
    + _SECTION_NUMBER
    + r")*)"
)
_ONE_SECTION = re.compile(_SECTION_NUMBER)

# The Constitution Acts are not in A2AJ (research/0002) and get ids of their own.
# The Charter is Part I of the Constitution Act, 1982, and numbered within it, so
# "s. 7 of the Charter" is s. 7 of that Act.
CONSTITUTION_1867 = "Constitution Act, 1867"
CONSTITUTION_1982 = "Constitution Act, 1982"
# The FLSC Model Code (research/0012) is held as a statute whose sections are rules.
MODEL_CODE = "FLSC Model Code of Professional Conduct"
BUILT_IN_STATUTE_NAMES: dict[str, str] = {
    "Canadian Charter of Rights and Freedoms": CONSTITUTION_1982,
    "Charter of Rights and Freedoms": CONSTITUTION_1982,
    "Charter": CONSTITUTION_1982,
    "Constitution Act, 1982": CONSTITUTION_1982,
    "Constitution Act, 1867": CONSTITUTION_1867,
    "British North America Act, 1867": CONSTITUTION_1867,
    "British North America Act": CONSTITUTION_1867,
    "B.N.A. Act": CONSTITUTION_1867,
    "BNA Act": CONSTITUTION_1867,
    "Criminal Code": "RSC 1985, c C-46",
    "Model Code": MODEL_CODE,
    "Model Code of Professional Conduct": MODEL_CODE,
    "Canadian Charter": CONSTITUTION_1982,
    # Canadian writing says "the Bill of Rights" for the Canadian Bill of Rights.
    "Bill of Rights": "SC 1960, c 44",
}
# Short names that also end other instruments' names ("Quebec Charter", "Alberta Bill of
# Rights", "NZ Bill of Rights"), so they count only when no capitalised word sits
# straight before them. "Canadian Charter" is listed above so it is not excluded.
_SHORT_NAMES = frozenset({"Charter", "Bill of Rights"})


@dataclass(frozen=True)
class ProvisionReference:
    """
    A reference to one section of one statute.

    `statute` is a statute id (an A2AJ citation such as "RSC 1985, c C-46", or
    one of the Constitution ids above). `section` is compact: "265(1)(a)".
    """

    statute: str
    section: str
    start: int
    end: int


def chapter_key(match: re.Match[str]) -> str:
    """
    A spelling-independent key for a chapter citation.

    The same chapter is written "R.S.O. 1990, c. J.3" in a judgment and
    "RSO 1990, c J3" in A2AJ, while federal ids keep the hyphen ("c C-46"), so
    neither spelling can serve as the key. Dots, spaces and hyphens are removed
    from the jurisdiction and chapter: "RSO 1990 c J3", "RSC 1985 c C46",
    "RSC 1985 c 1 (5th Supp)".
    """
    jurisdiction = re.sub(r"[.\s]", "", match.group("j"))
    chapter = re.sub(r"[-.\s]", "", match.group("ch"))
    supp = f" ({match.group('supp')} Supp)" if match.group("supp") else ""
    return f"{jurisdiction} {match.group('y')} c {chapter}{supp}"


def _compact_section(raw: str) -> str:
    return re.sub(r"\s+", "", raw)


def _sections_in(listing: str) -> list[str]:
    """The section numbers in "91 and 92" or "175.1 to 177". A range keeps only its two ends."""
    return [_compact_section(m.group(0)) for m in _ONE_SECTION.finditer(listing)]


_RANGE_BETWEEN = re.compile(r"\s*(?:-|–|to)\s*")


def section_listings(text: str) -> list[tuple[int, int, list[tuple[str, str | None]]]]:
    """
    Every section reference in `text`, whatever its statute: (start, end, parts).

    Each part is (section, None) or, for a range, (first, last): "ss 91-95, 101"
    gives [("91", "95"), ("101", None)]. For callers that know the statute from
    context and can expand a range, which `find_provision_references` cannot.
    """
    found = []
    for match in _SECTION_PATTERN.finditer(text):
        listing = match.group("list")
        numbers = list(_ONE_SECTION.finditer(listing))
        parts: list[tuple[str, str | None]] = []
        i = 0
        while i < len(numbers):
            first = _compact_section(numbers[i].group(0))
            between = (
                listing[numbers[i].end() : numbers[i + 1].start()] if i + 1 < len(numbers) else ""
            )
            if i + 1 < len(numbers) and _RANGE_BETWEEN.fullmatch(between):
                parts.append((first, _compact_section(numbers[i + 1].group(0))))
                i += 2
            else:
                parts.append((first, None))
                i += 1
        found.append((match.start(), match.end(), parts))
    return found


class StatuteNames:
    """
    The statute names the parser is allowed to recognise, and what each one means.

    A name maps to a statute id only when it is unambiguous. "Interpretation Act"
    is the title of a federal Act and of one in every province, so a bare
    "s. 12 of the Interpretation Act" is left unresolved rather than guessed; it
    still resolves when a chapter citation sits beside it ("Interpretation Act,
    R.S.C. 1985, c. I-21, s. 12").

    Lookups are by exact string at each candidate length rather than one regex
    alternation: there are ~27,000 titles, and the ingest job asks this question
    for every section reference in over a million paragraphs.
    """

    def __init__(
        self,
        statutes: list[tuple[str, str]],
        built_in: dict[str, str] = BUILT_IN_STATUTE_NAMES,
    ):
        """
        `statutes` is every (statute id, title) pair we hold, across all jurisdictions.
        `built_in` are the short names the corpus's courts use: Canada's by default,
        where "the Charter" and "the Bill of Rights" are Canadian; the New Zealand
        corpus passes its own (`legal_core.nz.NZ_STATUTE_NAMES`).
        """
        ids_by_title: dict[str, set[str]] = {}
        ids_by_chapter: dict[str, set[str]] = {}
        for statute_id, title in statutes:
            ids_by_title.setdefault(clean_text(title), set()).add(statute_id)
            chapter = _CHAPTER_PATTERN.match(statute_id)
            if chapter:
                ids_by_chapter.setdefault(chapter_key(chapter), set()).add(statute_id)
        self._by_name = {n: next(iter(ids)) for n, ids in ids_by_title.items() if len(ids) == 1}
        self._by_name.update(built_in)
        # Titles left unresolved because several Acts carry them, kept so a tool can list
        # the Acts instead of saying nothing matches (644 titles in the Canadian corpus).
        self._shared = {
            n: sorted(ids) for n, ids in ids_by_title.items() if len(ids) > 1 and n not in built_in
        }
        self._by_chapter = {
            k: next(iter(ids)) for k, ids in ids_by_chapter.items() if len(ids) == 1
        }
        self._lengths = sorted({len(n) for n in self._by_name}, reverse=True)

    def id_for(self, name: str) -> str:
        return self._by_name[name]

    def lookup(self, text: str) -> str | None:
        """
        The statute a bare name or chapter citation names, if exactly one: "Criminal
        Code", "the Charter", "RSC 1985, c C-46", "Interpretation Act, RSC 1985, c I-21".
        """
        text = clean_text(text.strip().rstrip(","))
        text = text[4:] if text.lower().startswith("the ") else text
        if text in self._by_name:
            return self._by_name[text]
        chapter = _CHAPTER_PATTERN.search(text)
        if chapter and chapter_key(chapter) in self._by_chapter:
            return self._by_chapter[chapter_key(chapter)]
        return None

    def sharing(self, text: str) -> list[str]:
        """
        The statutes that share the title `text`, when `lookup` refuses it for being
        shared: "Interpretation Act" gives the federal Act and the provinces'. Empty
        for a title only one Act has, or none.
        """
        text = clean_text(text.strip().rstrip(","))
        text = text[4:] if text.lower().startswith("the ") else text
        return self._shared.get(text, [])

    def name_after(self, text: str, position: int) -> tuple[str, int] | None:
        """
        If "of the <statute>" starts at `position`, return (statute id, end of the reference).

        A chapter citation after the name ("of the Interpretation Act, R.S.C. 1985,
        c. I-21") decides the statute on its own, which is what rescues ambiguous names.
        """
        lead = _OF_THE.match(text, position)
        if not lead:
            return None
        start = lead.end()
        chaptered = _TITLE_THEN_CHAPTER.match(text, start)
        if chaptered and chapter_key(chaptered) in self._by_chapter:
            return self._by_chapter[chapter_key(chaptered)], chaptered.end()
        return self.name_at(text, start)

    def name_at(self, text: str, position: int) -> tuple[str, int] | None:
        """If a statute's name starts at `position`, return (statute id, end of the name)."""
        for length in self._lengths:
            if position + length > len(text):
                # A slice past the end is shorter than `length` and would report a false end.
                continue
            candidate = text[position : position + length]
            if (
                candidate in self._by_name
                and not _continues_word(text, position + length)
                and not _inside_longer_name(text, position, candidate)
            ):
                return self._by_name[candidate], position + length
        return None

    def names_in(self, text: str, start: int, end: int) -> list[tuple[int, str]]:
        """
        Every statute named within `text[start:end]`, as (position, statute id) in
        order: "the Charter" and "Canadian Bill of Rights" in a line of an answer.
        """
        found = []
        covered = start
        for word in _WORD_START.finditer(text, start, end):
            if word.start() < covered:
                continue
            named = self.name_at(text, word.start())
            if named and named[1] <= end:
                found.append((word.start(), named[0]))
                covered = named[1]
        return found

    def name_before(self, text: str, position: int) -> str | None:
        """
        If "<statute>, ", "<statute> ", "<statute>'s " or "<statute>, <chapter>, " ends
        at `position`, return its id. Judgments put a comma there; the tutor's answers
        often do not ("Charter s 7", "the Charter's s 1").
        """
        window = text[max(0, position - 200) : position]
        chaptered = _CHAPTER_BEFORE.search(window)
        if chaptered and chapter_key(chaptered) in self._by_chapter:
            return self._by_chapter[chapter_key(chaptered)]
        trimmed = _BEFORE_SECTION.sub("", window)
        if trimmed == window:
            return None
        for length in self._lengths:
            if length > len(trimmed):
                continue
            candidate = trimmed[len(trimmed) - length :]
            if (
                candidate in self._by_name
                and not _continues_word(trimmed, len(trimmed) - length - 1)
                and not _inside_longer_name(trimmed, len(trimmed) - length, candidate)
            ):
                return self._by_name[candidate]
        return None


_OF_THE = re.compile(r"\s*of\s+(?:[Tt]he\s+)?")
# What may sit between a statute's name and its section: "Charter, s 7", "Charter s 7",
# "the Charter's s 1".
_BEFORE_SECTION = re.compile(r"\s*,\s*$|['’]s\s+$|\s+$")
_WORD_START = re.compile(r"(?<![\w.])[A-Z]")
_WORD_BEFORE = re.compile(r"([A-Za-z][\w'’.-]*)\s+$")
_TITLE_THEN_CHAPTER = re.compile(r"[A-Z][^,;()\n]{2,100}?,\s*" + _CHAPTER_PATTERN.pattern)
_CHAPTER_BEFORE = re.compile(_CHAPTER_PATTERN.pattern + r"\s*,\s*$")


def _continues_word(text: str, index: int) -> bool:
    """True if the character at `index` would make a name match only part of a word."""
    return 0 <= index < len(text) and text[index].isalnum()


def _inside_longer_name(text: str, position: int, name: str) -> bool:
    """True if a short name at `position` is the tail of a longer one ("Quebec Charter")."""
    if name not in _SHORT_NAMES:
        return False
    before = _WORD_BEFORE.search(text, max(0, position - 40), position)
    return bool(before) and before.group(1)[0].isupper() and before.group(1) != "The"


def find_provision_references(text: str, names: StatuteNames) -> list[ProvisionReference]:
    """
    Return every section reference in `text` whose statute can be identified.

    Two shapes are recognised, because they are the two the courts use:
    "s. 7 of the Charter" (name after) and "Criminal Code, R.S.C. 1985,
    c. C-46, s. 265" (name before). A section reference with neither, such as
    "s. 12" meaning "of the Act under discussion", is skipped: resolving it
    needs the surrounding document, and a guess would be a false edge.
    """
    found = []
    for match in _SECTION_PATTERN.finditer(text):
        sections = _sections_in(match.group("list"))
        after = names.name_after(text, match.end())
        if after:
            statute, end = after
        else:
            statute = names.name_before(text, match.start())
            end = match.end()
        if statute is None:
            continue
        found.extend(ProvisionReference(statute, s, match.start(), end) for s in sections)
    return found


# --- Names and sections, as the app and the job both compare them ------------------

# A section number, with the "-10" of a Model Code rule ("3.4-10") where there is one.
_BASE_SECTION = re.compile(r"^[0-9]+(?:\.[0-9]+)*(?:-[0-9]+(?:\.[0-9])?)?[A-Z]?")


def base_section(section: str) -> str:
    """The section a reference is to: "11(d)" -> "11"; "3.4-10" is kept whole."""
    found = _BASE_SECTION.match(section)
    return found.group(0) if found else section


def names_rules(statute_id: str) -> bool:
    """
    True if an instrument's id says it is rules ("High Court Rules 2016").

    Rules are cited "r 5.17", not "s 5.17"; the reader and the search prefix use this
    to write the reference the way the court does. The check is the title's own word,
    not a list, so a new rule set needs no entry.
    """
    return " Rules " in f" {statute_id} "


# The PCO's own note on a revoked rule, which is the text held for it (research/0036):
# "Rule 9.42: revoked, on 1 January 2026, by rule 39 of the High Court (...) Rules 2025".
_REVOKED_RULE = re.compile(r"^Rules? [^:]+: revoked\b")


def is_revoked_rule(text: str) -> bool:
    """True if a provision's held text is the note saying the rule was revoked."""
    return _REVOKED_RULE.match(text) is not None


def normalise_case_name(name: str) -> str:
    """A spelling-tolerant style of cause: "Regina v. Howson" and "R. v. Howson" compare equal."""
    name = name.lower().replace("’", "'")
    name = re.sub(
        r"^(?:the queen|regina|her majesty the queen|his majesty the king)\s+v\b", "r v", name
    )
    name = re.sub(r"\bv\.?\s", "v ", name)
    name = re.sub(r"[^\w\s']", " ", name)
    return re.sub(r"\s+", " ", name).strip()


# "rule 3.4-10", "r. 3.3-3", "Model Code, rule 5.1-2A", "Rules 3.4-1": a Model Code rule.
_MODEL_CODE_RULE = re.compile(
    r"\b(?:(?:FLSC\s+)?Model Code(?: of Professional Conduct)?,?\s+)?(?:[Rr]ules?|r\.|rr\.)\s*"
    r"(?P<rule>\d\.\d{1,2}-\d{1,2}(?:\.\d)?[A-Z]?)"
)


def find_model_code_references(text: str) -> list[ProvisionReference]:
    """Every Model Code rule referred to in `text`, as a provision of MODEL_CODE."""
    return [
        ProvisionReference(MODEL_CODE, m.group("rule"), m.start(), m.end())
        for m in _MODEL_CODE_RULE.finditer(text)
    ]


# A rule number as New Zealand courts write it: "5.17", "5.17A", "13.2", "14.5(2)(j)".
# The Model Code's hyphenated rules ("3.4-10") are matched by the finder above; here a
# hyphen is a range ("rr 5.17-5.20"), which keeps only its two ends.
_RULE_NUMBER = r"\d+(?:\.\d+)*[A-Z]?(?:\s?\(\s?[0-9a-zA-Z.]{1,6}\s?\))*"
_RULE_PATTERN = re.compile(
    r"\b(?:rr?\.?|[Rr]ules?)\s+(?!\d{4}\b)(?P<list>"
    + _RULE_NUMBER
    + r"(?:\s*(?:,|and|or|to|-|–)\s*(?!\d{4}\b)"
    + _RULE_NUMBER
    + r")*)"
)
# Every High Court rule is numbered part.rule, so a bare "r 43" (the 1985 numbering, or
# the Court of Appeal's rules) or "r 13.5.3" (the conduct rules) cannot be one.
_DEFAULT_RULE_NUMBER = re.compile(r"\d+\.\d+[A-Z]?(?:\(|$)")
# A rule that names an instrument we could not resolve is that instrument's, not the
# default's: "r 36.15 of the Criminal Procedure Rules 2015 (UK)", "r 5.1 of the then NZX
# Listing Rules", "Supreme Court Rules 2009 (UK), r 15". "of the Rules" names nothing.
_NAMES_OTHER_AFTER = re.compile(r"\s*of\s+(?:[Tt]he\s+)?(?:then\s+)?(?!Rules\b)[A-Z]")
_NAMES_OTHER_BEFORE = re.compile(r"[A-Z(]\S*\s+Rules(?:\s+\d{4})?(?:\s+\(\w+\))?,?\s*$")


def _names_other_rules(text: str, start: int, end: int) -> bool:
    """True if the rule reference at `start`..`end` is tied to a name beside it."""
    return (
        _NAMES_OTHER_AFTER.match(text, end) is not None
        or _NAMES_OTHER_BEFORE.search(text[max(0, start - 80) : start]) is not None
    )


def find_rule_references(
    text: str, names: StatuteNames, default: str | None = None
) -> list[ProvisionReference]:
    """
    Every rule reference in `text` whose rules can be identified.

    Two shapes are recognised, as for sections: "r 5.17 of the High Court Rules
    2016" (name after) and "HCR r 5.17" or "High Court Rules 2016, r 5.17" (name
    before). When `default` is given, a bare "r 5.17" is a reference to that
    instrument's rules; New Zealand's held courts read a bare "r" as the High Court
    Rules (research/0036). Without it a bare rule is skipped, because a guess would
    be a false edge. The default takes only a part.rule number beside no other name,
    which still leaves the odd plan or listing rule that shares the shape.

    The number shape is New Zealand's. The Model Code's hyphenated rules have their
    own finder, and a match that overlaps one of those is left out.
    """
    model_code = find_model_code_references(text)
    found = []
    for match in _RULE_PATTERN.finditer(text):
        if any(ref.start < match.end() and match.start() < ref.end for ref in model_code):
            continue
        sections = _sections_in(match.group("list"))
        after = names.name_after(text, match.end())
        if after:
            statute, end = after
        else:
            statute = names.name_before(text, match.start())
            end = match.end()
            if statute is None and not _names_other_rules(text, match.start(), match.end()):
                statute = default
                sections = [s for s in sections if _DEFAULT_RULE_NUMBER.match(s)]
        # "r 5.17" belongs to an instrument whose title says it is rules; a name
        # before it may be an Act the paragraph is also discussing.
        if statute is None or not names_rules(statute):
            continue
        found.extend(ProvisionReference(statute, s, match.start(), end) for s in sections)
    return found
