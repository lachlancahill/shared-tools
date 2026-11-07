"""
The answer checker (research/0004 §4, 0010 decision 3, 0011 §9).

Code, not a second model call, reads the model's final answer and checks every
citation in it before it is shown:

* the case or provision exists in the corpus;
* the pinpointed paragraph (or report page) exists;
* quoted words appear at the pinpoint.

Existence is not support, so it also adds **context badges**, which are
warnings rather than refusals:

* "not read in context": the pinpoint was never returned by `read` in this
  conversation, only seen in a search snippet;
* "dissent" / "concurrence" / "plurality" / "separate reasons": the paragraph sits
  in those reasons (`corpus.reasons`: a plurality where no reasons had a majority,
  separate reasons beside a majority);
* "overruled" / "reframed": the case has such an edge;
* "revoked": the rule cited is no longer in force, and its held text says when it went;
* "party submission" / "court below": the paragraph's enriched role;
* "pinpoint not checkable": one of the ~1,000 block-unit decisions whose court
  numbering is not in our text (research/0011 §1).

Short forms ("*Eldridge*, at para 42") are resolved against the cases cited in
full in the same answer, then in the conversation's earlier answers (the gap 0011
§9 found, and a follow-up that names its cases only by short name). A bare
pinpoint ("(para 18)") goes to the case last named on its line; a bare section
("s 2(e)") to the statute the answer pairs it with, or failing that the statute
named earlier in its sentence. Anything those rules cannot settle is left
unmarked: a guess would put a tick on the wrong authority, which is worse than
no mark (research/debug/2026-10-01-conversation-review-topic-5.md). The patterns
are written for plain text, as judgments print it, so markdown emphasis is taken
out before matching ("*Charter*, s 7" would otherwise go unchecked, and unmarked).

Answers are checked again whenever a conversation is shown (`check_conversation`),
so a fix to the checker reaches every stored answer.

Each citation renders as a link into the case reader with its marks, and the
counts are logged per turn: they are how we learn whether the model invents
authority or ignores context.
"""

import html
import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from urllib.parse import quote

from legal_core.citations import (
    ProvisionReference,
    base_section,
    clean_text,
    find_case_citations,
    find_model_code_references,
    find_provision_references,
    find_rule_references,
    is_revoked_rule,
    names_rules,
    section_listings,
)
from legal_core.nz import NZ_KEY

from legal_corpus.reader import case_status
from legal_corpus.snapshot import Corpus

logger = logging.getLogger(__name__)

# More paragraphs after a full citation's pinpoint, which the citation parser stops
# short of: "2001 SCC 78 at paras 51, 66" or "at paras 3 and 9–11". A number that
# opens the next citation ("at para 5, 2019 SCC 5") is not one of them.
_MORE_PINPOINTS = re.compile(
    r"(?:\s*(?:,|and)\s*\d{1,4}(?:\s*(?:-|–|to)\s*\d{1,4})?(?!\s*[A-Z(\[\d]))+"
)
# A quotation that ends just before a citation: “…words…” (Oakes, at para 69).
_QUOTE_BEFORE = re.compile(r"[“\"]([^”\"]{20,600})[”\"][^“\"\n]{0,60}$")
# "*Eldridge*, at para 42", "(Ross River, at para 5)": the short name, then up to
# four more capitalised words of the name, then the pinpoint.
_PINPOINT_NUMBERS = r"\d{1,4}(?:\s*(?:,|and|[-–]|to)\s*\d{1,4})*"
# New Zealand writes "*Hansen* at [104]": the bracket form needs its "at".
_SHORT_FORM = (
    r"\b{name}(?:\s+[A-ZÀ-Ý][\w'’.-]*){{0,4}},?\s*(?:(?:at\s+)?paras?\.?\s*|at\s+\[)"
    r"(?P<numbers>" + _PINPOINT_NUMBERS.replace("{", "{{").replace("}", "}}") + ")"
)
# A pinpoint written without its case: "(para 18)", "(paras 2, 45)", "at paras 1–4",
# "deprived detainees of liberty: para 13".
# "(at [13])" in New Zealand form; a bracketed number with no "at" is left alone, as
# "([2007] NZSC 7)" opens a citation.
_BARE_PINPOINT = re.compile(
    r"(?P<lead>\(|\bat\s+|:\s*)(?P<pin>paras?\.?\s*(?P<numbers>" + _PINPOINT_NUMBERS + "))"
    r"|(?P<at>\bat\s+)(?P<bpin>\[(?P<bnumbers>\d{1,4})\])"
)
# "Suresh at para 113", "Wilson J at para 57", "Clyde River (at para 46)": the run of
# capitalised words straight before a bare pinpoint.
_NAME_BEFORE_PIN = re.compile(r"((?:\b[A-Z][\w'’.-]*\s+){0,4}\b[A-Z][\w'’.-]*),?\s*$")
# Judges, whose names before a pinpoint say whose reasons, not which case.
_JUDGE_TITLES = {"J", "JJ", "CJ", "CJC", "JA", "JJA", "C.J", "J.A", "C.J.C"}
# Markdown emphasis: "*Oakes*", "**Charter**", "_Singh_".
_EMPHASIS = re.compile(r"\*+|(?<!\w)_+|_+(?!\w)")
# Where a sentence ends: "... the Bill. Section 2 ..." (not "s. 7" or "v. Oakes" much).
_SENTENCE_END = re.compile(r"[.!?][\"”’)\]]*\s+(?=[A-Z(\"“\[])")
# New Zealand law, the only foreign law the tutor writes (her bridging notes), whose
# section numbers collide with ours: NZBORA s 7 is a report, Charter s 7 a right.
_NEW_ZEALAND = re.compile(r"\bNZ|New Zealand|\bBORA\b")
# An acronym straight before a section names a statute we do not know: "NZBORA s 27(1)".
_ACRONYM_BEFORE = re.compile(r"\b[A-Z]{2,}\s*$")
# "(see ss 2–3 below)": the answer's own numbered parts, not a statute's.
_CROSS_REFERENCE = re.compile(r"\s*(?:below|above)\b")
_NAME_STOP = {
    "r",
    "v",
    "the",
    "queen",
    "king",
    "canada",
    "attorney",
    "general",
    "of",
    "and",
    "minister",
    "re",
    "reference",
    "inc",
    "ltd",
    "her",
    "his",
    "majesty",
    "province",
    "british",
    "columbia",
    "ontario",
    "quebec",
    "alberta",
    "citizenship",
    "immigration",
    "regina",
}


@dataclass
class Citation:
    """One citation found in an answer, and what the check made of it."""

    start: int
    end: int
    text: str
    kind: str  # "case" or "provision"
    target: str | None = None  # case id or provision id
    name: str = ""
    link: str | None = None
    status: str = "unverified"  # "verified", "unverified" or "not_checkable"
    badges: list[str] = field(default_factory=list)
    unit_id: str | None = None  # the pinpointed unit, once known to be checkable
    extra_unit_ids: list[str] = field(default_factory=list)  # "paras 2, 45": the rest
    # Every paragraph the pinpoint covers, a range filled in: "paras 1–3" is 1, 2, 3.
    # A quote is looked for across all of them (and one paragraph either side).
    covered: list[int] = field(default_factory=list)
    quoted: str | None = None

    def as_dict(self) -> dict:
        return {
            "text": self.text,
            "kind": self.kind,
            "target": self.target,
            "name": self.name,
            "link": self.link,
            "status": self.status,
            "badges": self.badges,
        }


def nz_needed(texts: Iterable[str], loader: Callable[[], Corpus | None]) -> Corpus | None:
    """
    The New Zealand corpus if any of `texts` mentions New Zealand or cites an NZ case,
    else None: loading it is only worth it for an answer with NZ law to check.
    The consumer supplies `loader`; this library never owns a global corpus.
    """
    for text in texts:
        if _NEW_ZEALAND.search(text) or any(
            NZ_KEY.search(c.key) for c in find_case_citations(clean_text(text))
        ):
            return loader()
    return None


def check_conversation(
    corpus: Corpus, messages: list[dict], nz: Corpus | None = None
) -> list[list[Citation] | None]:
    """
    Check every answer of a conversation in order, each with what it could rely on:
    the units read up to and including its own turn (each assistant message stores
    the `read_ids` its turn added), and the cases cited in the answers before it.
    NZ citations are checked against `nz`, when given (`nz_needed`).

    One entry per message: its citations, or None where nothing is checked (her
    messages, and answers stopped part way, which were never finished).
    """
    read: set[str] = set()
    earlier: list[str] = []
    checked: list[list[Citation] | None] = []
    for message in messages:
        read.update(message.get("read_ids") or ())
        if message["role"] != "assistant" or message.get("stopped") or not message["content"]:
            checked.append(None)
            continue
        citations = verify(corpus, message["content"], set(read), earlier, nz)
        earlier += [c.target for c in citations if c.kind == "case" and c.target]
        checked.append(citations)
    return checked


def verify(
    corpus: Corpus,
    answer: str,
    read_ids: set[str],
    earlier_cases: Iterable[str] = (),
    nz: Corpus | None = None,
) -> list[Citation]:
    """
    Every citation in `answer`, checked. Offsets index `answer` as given.

    `earlier_cases` are the cases cited in the conversation's earlier answers, which
    a follow-up may call by short name alone, as legal writing does once a case has
    been cited in full.

    NZ citations (an NZ case's citation, an NZ statute) are checked against `nz`, the
    New Zealand corpus (research/0024), in a pass of their own; without it they are
    left as they always were, "not in the corpus" or unmarked. Where the two passes
    mark the same words, the citation that resolved wins.
    """
    # Curly apostrophes compared as straight ones, one for one, so offsets hold:
    # the corpus has "Tsilhqot’in", the tutor writes "Tsilhqot'in".
    text = _EMPHASIS.sub("", clean_text(answer)).replace("’", "'")
    earlier = list(earlier_cases)
    citations = _check_in(corpus, text, read_ids, earlier, leave_nz=nz is not None)
    if nz is not None:
        kept: list[Citation] = []
        for c in sorted(
            citations + _check_in(nz, text, read_ids, earlier, leave_nz=False),
            key=lambda c: (c.target is None, c.start - c.end),
        ):
            if not any(k.start < c.end and c.start < k.end for k in kept):
                kept.append(c)
        citations = kept

    positions = _offset_map(answer, text)
    for c in citations:
        # The end maps from the span's last character: the offset after it would
        # land past any emphasis markers deleted there ("**Charter s 7**:").
        end = positions[c.end - 1] + 1
        c.start, c.end = _whole_emphasis(answer, positions[c.start], end)
        c.text = answer[c.start : c.end]
    return sorted(citations, key=lambda c: c.start)


def _check_in(
    corpus: Corpus, text: str, read_ids: set[str], earlier: list[str], leave_nz: bool
) -> list[Citation]:
    """
    One corpus's pass over the cleaned answer: its case citations, the short forms
    and bare pinpoints into them, and its statutes' sections. New Zealand's pass
    takes only NZ case citations; Canada's leaves them to it when it runs
    (`leave_nz`), and otherwise marks them "not in the corpus" as it always has.
    """
    nz = corpus.profile.name == "nz"
    citations: list[Citation] = []

    for found in find_case_citations(text):
        is_nz = bool(NZ_KEY.search(found.key))
        if (nz and not is_nz) or (not nz and is_nz and leave_nz):
            continue
        citation = Citation(found.start, found.end, "", "case")
        citation.target = corpus.case_index.resolve(found.key)
        quoted = _QUOTE_BEFORE.search(text[: found.start])
        citation.quoted = quoted.group(1) if quoted else None
        if citation.target is None:
            citation.badges.append("not in the corpus")
        else:
            _check_case(corpus, citation, found.para, found.page)
            if citation.unit_id:
                written = f"{found.para}" + (f"–{found.para_end}" if found.para_end else "")
                more = _MORE_PINPOINTS.match(text, found.end)
                if more:
                    written += more.group(0)
                    citation.end = more.end()
                _set_pinpoint(citation, written)
        citations.append(citation)

    cited = [c.target for c in citations if c.target]
    names = _short_names(corpus, cited, earlier)
    citations += _short_forms(corpus, text, citations, names)
    citations += _bare_pinpoints(corpus, text, citations, names)

    explicit = find_provision_references(text, corpus.statute_names)
    candidates = _inherited_references(corpus, text, explicit)
    model_code = [] if nz else find_model_code_references(text)
    # Rules are cited "r 5.17" as often as "s 5.17"; the NZ profile supplies the
    # instrument a bare rule means (research/0036). The finder leaves the Model
    # Code's hyphenated rules to the Canadian pass.
    rules = (
        find_rule_references(text, corpus.statute_names, corpus.profile.rule_default)
        if nz and corpus.profile.rule_default
        else []
    )
    # Every unit the checks need, in one query: each costs a scan of the search table.
    units = corpus.units_by_id(_unit_ids(citations, explicit + candidates + model_code + rules))
    # A section given a statute by inference counts only if that statute has it.
    inherited = [ref for ref in candidates if _provision_id(ref) in units]
    # "ss 90, 92" is one citation over one span, and answers for every section in it.
    listed: dict[tuple[str, int, int], Citation] = {}
    for ref in explicit + inherited + model_code + rules:
        checked = _check_provision(ref, units, read_ids, corpus.profile.link_prefix)
        listing = (ref.statute, ref.start, ref.end)
        if listing in listed:
            _add_to_listing(listed[listing], checked, ref.section)
        elif not any(c.start <= ref.start < c.end for c in citations):
            listed[listing] = checked
            citations.append(checked)

    _check_units(corpus, citations, read_ids, units)

    # A case named without a pinpoint in a heading or a list is fine when the
    # answer pinpoints it elsewhere; the badge is kept only where it never is.
    pinpointed = {c.target for c in citations if c.unit_id or c.status == "not_checkable"}
    for c in citations:
        if c.target in pinpointed and "no pinpoint" in c.badges:
            c.badges.remove("no pinpoint")
    return citations


def _whole_emphasis(answer: str, start: int, end: int) -> tuple[int, int]:
    """
    Widen a span that holds a markdown emphasis marker so that wrapping it in a link
    never cuts the emphasis in half: over the markers beside it ("*Charkaoui* at para
    19"), and back to the marker that opens it when that sits earlier on the line
    ("*Re B.C. Motor Vehicle Act* at para 58", whose short form starts at "Motor").
    """
    if "*" not in answer[start:end]:
        return start, end
    while start > 0 and answer[start - 1] == "*":
        start -= 1
    while end < len(answer) and answer[end] == "*":
        end += 1
    # Count runs, not stars: "Motor Vehicle Act** paras 26" holds one closing marker.
    if len(re.findall(r"\*+", answer[start:end])) % 2:
        line_start = answer.rfind("\n", 0, start) + 1
        opening = answer.rfind("*", line_start, start)
        if opening >= 0:
            start = opening
            while start > line_start and answer[start - 1] == "*":
                start -= 1
    return start, end


def _check_case(corpus: Corpus, citation: Citation, para: int | None, page: int | None) -> None:
    """Everything about a resolved case citation that does not need its unit's text."""
    case = corpus.case(citation.target)
    citation.name = case["name"]
    citation.link = f"{corpus.profile.link_prefix}/cases/{quote(citation.target, safe='')}"
    for status in case_status(corpus, citation.target):
        # The court's own "Cases Cited" label is a fact; a brief's is the model's
        # reading, and was wrong about half the time on a sample (research/0013),
        # so it is shown as a question, never as a verdict.
        word = "reframed" if status.startswith("REFRAMED") else "overruled"
        badge = word if status.endswith("(court)") else f"{word}? (machine-classified)"
        if badge not in citation.badges:
            citation.badges.append(badge)
    pin = para or page
    if case["tier"] != "A":
        citation.status = "verified"
        citation.badges.append("metadata only: text not in the corpus")
    elif pin is None:
        citation.status = "verified"
        if case["unit"] == "paragraph":
            citation.badges.append("no pinpoint")
    elif case["unit"] == "block":
        citation.status = "not_checkable"
        citation.badges.append("pinpoint not checkable")
    elif (case["unit"] == "page") != (page is not None):
        citation.badges.append(
            "this case is cited by page" if case["unit"] == "page" else "cite by paragraph"
        )
    else:
        _set_pinpoint(citation, str(pin))
        citation.link += f"#u{pin}"


def _set_pinpoint(citation: Citation, written: str) -> None:
    """
    Point a citation at the paragraphs written ("69", "2, 45", "1–3"): the first is
    its unit, the other numbers written must exist and be read too (a range at both
    ends), and every paragraph covered is searched for its quote.
    """
    numbers = _pinpoint_numbers(written)
    citation.unit_id = f"{citation.target}#{numbers[0]}"
    citation.extra_unit_ids = [f"{citation.target}#{n}" for n in numbers[1:]]
    citation.covered = []
    for part in re.split(r"\s*(?:,|and)\s*", written.strip()):
        ends = _pinpoint_numbers(part)
        citation.covered += range(ends[0], max(ends) + 1)


def _short_name(name: str) -> str | None:
    """
    The word a case is known by: "Eldridge" for "Eldridge v. British Columbia",
    "Motor" for "Re B.C. Motor Vehicle Act" (initials are too short to trust).
    """
    for part in re.split(r"\s+v\.?\s+", name.replace("’", "'"), maxsplit=1):
        for word in re.findall(r"[A-Za-zÀ-ÿ'’-]+", part):
            if word.lower() not in _NAME_STOP and len(word) > 2:
                return word
    return None


def _short_names(corpus: Corpus, cited: list[str], earlier: list[str]) -> dict[str, str]:
    """
    Each case by its short name: {"Oakes": "[1986] 1 SCR 103"}. Cases cited in full in
    this answer come first, then those cited in earlier answers. A name two cases share
    at the same level is dropped rather than guessed ("Singh" could be either Singh),
    and stays dropped: an earlier case cannot claim it.
    """
    names: dict[str, str] = {}
    taken: set[str] = set()
    for case_ids in (cited, earlier):
        level: dict[str, set[str]] = {}
        for case_id in dict.fromkeys(case_ids):
            case = corpus.case(case_id)
            if case and (short := _short_name(case["name"])) and short not in taken:
                level.setdefault(short, set()).add(case_id)
        for short, ids in level.items():
            if len(ids) == 1:
                names[short] = next(iter(ids))
        taken |= set(level)
    return names


def _short_forms(
    corpus: Corpus, text: str, citations: list[Citation], names: dict[str, str]
) -> list[Citation]:
    """Pinpoints written as a short name ("Eldridge, at para 42") into cases cited in full."""
    found = []
    for short, case_id in names.items():
        for match in re.finditer(_SHORT_FORM.format(name=re.escape(short)), text):
            if any(c.start <= match.start() < c.end for c in citations + found):
                continue
            # "at [3]" is how New Zealand pinpoints; Canada's pass leaves it alone.
            if "[" in match.group(0) and corpus.profile.name != "nz":
                continue
            citation = Citation(match.start(), match.end(), "", "case", case_id)
            quoted = _QUOTE_BEFORE.search(text[: match.start()])
            citation.quoted = quoted.group(1) if quoted else None
            numbers = _pinpoint_numbers(match.group("numbers"))
            _check_case(corpus, citation, numbers[0], None)
            if citation.unit_id:
                _set_pinpoint(citation, match.group("numbers"))
            found.append(citation)
    return found


def _pinpoint_numbers(written: str) -> list[int]:
    """ "2, 45" -> [2, 45]; "1–4" -> [1, 4] (a range is checked at both ends)."""
    return [int(n) for n in re.findall(r"\d{1,4}", written)]


def _bare_pinpoints(
    corpus: Corpus, text: str, citations: list[Citation], names: dict[str, str]
) -> list[Citation]:
    """
    Pinpoints written without their case ("(para 18)", "at paras 2, 45"), which legal
    writing uses once a case has been named. Each is attributed to the nearest case
    named before it **on the same line** (a paragraph of prose, a list item or a table
    row) that can be pinpointed (held in full, with numbered paragraphs). A case is
    named by a citation or by its short name alone ("In *Charkaoui*, ...: para 13").
    When nothing on the line names one, the pinpoint is left unchecked rather than
    guessed: crediting it to "the answer's only case" once put every pinpoint of a
    follow-up on the wrong case, each with a tick.
    """
    case_ids = {c.target for c in citations if c.target and c.kind == "case"}
    pinpointable = {}
    for case_id in case_ids | set(names.values()):
        case = corpus.case(case_id)
        pinpointable[case_id] = case["tier"] == "A" and case["unit"] == "paragraph"
    named = [(c.start, c.target) for c in citations if pinpointable.get(c.target)]
    for short, case_id in names.items():
        if pinpointable[case_id]:
            named += [(m.start(), case_id) for m in re.finditer(rf"\b{re.escape(short)}\b", text)]
    found = []
    for match in _BARE_PINPOINT.finditer(text):
        if match.group("bpin") and corpus.profile.name != "nz":
            continue  # a bracketed pinpoint is New Zealand's
        pin = "pin" if match.group("pin") else "bpin"
        if any(c.start <= match.start(pin) < c.end for c in citations):
            continue
        line_start = text.rfind("\n", 0, match.start()) + 1
        before = [(at, target) for at, target in named if line_start <= at < match.start()]
        if not before or _names_another_case(text, line_start, match.start(), names):
            continue
        target = max(before)[1]
        numbers = _pinpoint_numbers(match.group("numbers") or match.group("bnumbers"))
        lead = match.group("lead") or match.group("at")
        start = match.start() if lead.startswith("at") else match.start(pin)
        citation = Citation(start, match.end(), "", "case", target)
        citation.name = corpus.case(target)["name"]
        prefix = corpus.profile.link_prefix
        citation.link = f"{prefix}/cases/{quote(target, safe='')}#u{numbers[0]}"
        _set_pinpoint(citation, match.group("numbers") or match.group("bnumbers"))
        found.append(citation)
    return found


def _inherited_references(
    corpus: Corpus, text: str, explicit: list[ProvisionReference]
) -> list[ProvisionReference]:
    """
    Sections written without their statute ("s 2(e)", "Section 7 applies"), as legal
    prose writes them once the statute has been named. Each takes, in order:

    1. the statute this answer pairs that exact section with elsewhere, if only one
       ("Charter s 7" anywhere makes a bare "s 7" the Charter's, even in a sentence
       about the Bill of Rights);
    2. the statute named last before it in the same sentence, on the same line
       ("(*Canadian Bill of Rights*, SC 1960, c 44): s 1(a) ...; s 2(e) provides").

    Otherwise it is left unmarked, as is one whose statute has no such section (the
    caller drops those once it has looked them up): a failed guess must not show as
    the model's mistake, nor a wrong one as a tick. Nothing is inferred where the
    section plainly belongs elsewhere (`_belongs_elsewhere`).
    """
    paired: dict[str, set[str]] = {}
    for ref in explicit:
        paired.setdefault(ref.section, set()).add(ref.statute)
    found = []
    for start, end, parts in section_listings(text):
        if any(ref.start <= start < ref.end for ref in explicit):
            continue
        if _belongs_elsewhere(text, start, end, corpus.profile.name == "nz"):
            continue
        sections = [number for part in parts for number in part if number]
        pairings = {
            next(iter(paired[s])) if len(paired.get(s, ())) == 1 else None for s in sections
        }
        statute = pairings.pop() if len(pairings) == 1 else None
        statute = statute or _statute_named_in_sentence(corpus, text, start, explicit)
        if statute is None:
            continue
        found += [ProvisionReference(statute, section, start, end) for section in sections]
    return found


def _belongs_elsewhere(text: str, start: int, end: int, nz: bool) -> bool:
    """
    Whether a bare section is plainly not one of this pass's to infer. For Canada's:
    after New Zealand is mentioned on its line (the tutor ends a paragraph with its
    "*NZ contrast: ...*", so what follows on the line is about NZ law), or straight
    after a statute acronym ("NZBORA s 27(1)", "BORA s 5"); each was linked to a
    Canadian provision, with a tick, before it was excluded. For New Zealand's: a
    line that never mentions New Zealand. For both: the answer pointing at its own
    parts ("ss 2–3 below").
    """
    line_start = text.rfind("\n", 0, start) + 1
    if _CROSS_REFERENCE.match(text, end):
        return True
    on_nz_line = bool(_NEW_ZEALAND.search(text, line_start, start))
    if nz:
        return not on_nz_line
    return on_nz_line or bool(_ACRONYM_BEFORE.search(text, line_start, start))


def _statute_named_in_sentence(
    corpus: Corpus, text: str, position: int, explicit: list[ProvisionReference]
) -> str | None:
    """The statute named last before `position` in its sentence, on its line."""
    line_start = text.rfind("\n", 0, position) + 1
    ends = [m.end() for m in _SENTENCE_END.finditer(text, line_start, position)]
    start = ends[-1] if ends else line_start
    named = corpus.statute_names.names_in(text, start, position)
    named += [(ref.start, ref.statute) for ref in explicit if start <= ref.start < position]
    return max(named)[1] if named else None


def _provision_id(ref: ProvisionReference) -> str:
    """The search unit id of the section a reference is to (as `ingest.laws.provision_id`)."""
    return f"{ref.statute} s {base_section(ref.section)}"


def _unit_ids(citations: list[Citation], references: list[ProvisionReference]) -> list[str]:
    """Every unit the checks will look at: pinpoints, their neighbours for quotes, sections."""
    ids = {_provision_id(ref) for ref in references}
    for c in citations:
        if c.unit_id:
            ids.update([c.unit_id, *c.extra_unit_ids])
            if c.quoted:
                ids.update(f"{c.target}#{n}" for n in _quote_numbers(c))
    return sorted(ids)


def _quote_numbers(citation: Citation) -> list[int]:
    """The paragraphs a citation's quote may come from: those covered, and one either side."""
    return sorted({n + d for n in citation.covered for d in (-1, 0, 1)})


def _names_another_case(text: str, line_start: int, position: int, names: dict[str, str]) -> bool:
    """
    Whether a bare pinpoint's own short name is a case we do not know: "citing
    *Suresh* at para 113" is Suresh's paragraph, not that of the case named before it.
    """
    found = _NAME_BEFORE_PIN.search(text, line_start, position)
    if not found:
        return False
    words = {word.rstrip(".") for word in found.group(1).split()}
    # Part of a known case's name ("Clyde River"), or a judge ("Dickson CJ"): not another case.
    return not words & (set(names) | _JUDGE_TITLES)


def _check_provision(
    ref: ProvisionReference, units: dict[str, dict], read_ids: set[str], prefix: str
) -> Citation:
    citation = Citation(ref.start, ref.end, "", "provision")
    unit = units.get(_provision_id(ref))
    if unit is None:
        citation.badges.append("not in the corpus")
        return citation
    citation.target = unit["id"]
    citation.name = f"{unit['title']} {'r' if names_rules(ref.statute) else 's'} {ref.section}"
    citation.status = "verified"
    citation.link = (
        f"{prefix}/provisions/{quote(ref.statute, safe='')}/{quote(unit['section'], safe='')}"
    )
    if unit["id"] not in read_ids:
        citation.badges.append("not read in context")
    if is_revoked_rule(unit["text"]):
        citation.badges.append("revoked")
    return citation


def _add_to_listing(citation: Citation, other: Citation, section: str) -> None:
    """
    Fold another section of a list into its citation, so the mark shows the worst of
    them: a list whose second section was never read must not look read.
    """
    if citation.target == other.target:
        return  # "s 9(1)" and "s 9(2)" are one unit
    citation.name += f", {section}"
    if other.status == "unverified":
        citation.status = "unverified"
    citation.badges += [b for b in other.badges if b not in citation.badges]


def _check_units(
    corpus: Corpus, citations: list[Citation], read_ids: set[str], units: dict[str, dict]
) -> None:
    """Mark each pinpointed citation from its unit, already looked up in `units`."""
    pinned = [c for c in citations if c.unit_id]
    roles: dict[str, list[tuple]] = {}
    for citation in pinned:
        unit = units.get(citation.unit_id)
        if unit is None:
            citation.badges.append("pinpoint does not exist")
            continue
        if any(extra not in units for extra in citation.extra_unit_ids):
            citation.badges.append("pinpoint does not exist")
            continue
        citation.status = "verified"
        if any(u not in read_ids for u in [citation.unit_id, *citation.extra_unit_ids]):
            citation.badges.append("not read in context")
        if citation.target not in roles:
            roles[citation.target] = corpus.sql(
                "select first, last, role from roles where case_id = ?", [citation.target]
            )
        # Every paragraph named counts: "paras 69–72" ends in a dissent even when 69
        # is the majority's.
        for named in [unit, *(units[extra] for extra in citation.extra_unit_ids)]:
            for badge in _whose(corpus, citation.target, named, roles[citation.target]):
                if badge not in citation.badges:
                    citation.badges.append(badge)
        if citation.quoted:
            nearby = [units.get(f"{citation.target}#{n}") for n in _quote_numbers(citation)]
            passage = " ".join(u["text"] for u in nearby if u)
            if not quote_found(citation.quoted, passage):
                citation.badges.append("quote not found at the pinpoint")


_REASONS_BADGE = {
    "dissenting": "dissent",
    "dissenting_in_part": "dissent",
    "concurring": "concurrence",
    "plurality": "plurality",
    "separate": "separate reasons",
}
_ROLE_BADGE = {"submissions": "party submission", "court_below": "court below"}


def _whose(corpus: Corpus, case_id: str, unit: dict, roles: list[tuple]) -> list[str]:
    """The badges for whose reasons a paragraph is in, and whose words it reports."""
    kind = corpus.reasons_kind(case_id, unit["segment_authors"], unit["segment_kind"])
    role = next((r for first, last, r in roles if first <= unit["number"] <= last), None)
    return [b for b in (_REASONS_BADGE.get(kind), _ROLE_BADGE.get(role)) if b]


def _normalise(text: str) -> str:
    text = text.lower().replace("’", "'").replace("‘", "'")
    text = re.sub(r"\[[^\]]{0,40}\]|\.\.\.|…", " ", text)  # editorial brackets, ellipses
    text = re.sub(r"[^\w\s']", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def quote_found(quoted: str, passage: str) -> bool:
    """
    Whether quoted words appear in a passage, allowing for ellipses, editorial
    brackets and punctuation: four in five of its five-word runs must occur.
    """
    words = _normalise(quoted).split()
    haystack = _normalise(passage)
    if len(words) < 5:
        return " ".join(words) in haystack
    runs = [" ".join(words[i : i + 5]) for i in range(len(words) - 4)]
    return sum(1 for run in runs if run in haystack) / len(runs) >= 0.8


def _offset_map(original: str, cleaned: str) -> list[int]:
    """
    For each offset in `cleaned` (from `clean_text`), the offset in `original`.

    `clean_text` swaps look-alike spaces and hyphens one for one and deletes spaces
    before punctuation, so walking both strings together recovers the mapping.
    """
    mapping, i = [], 0
    for ch in cleaned:
        while i < len(original) and original[i] != ch and not _same(original[i], ch):
            i += 1
        mapping.append(i)
        i += 1
    mapping.append(len(original))
    return mapping


def _same(original: str, cleaned: str) -> bool:
    return (
        (original.isspace() and cleaned == " ")
        or (cleaned == "-" and original in "‐‑")
        or (cleaned == "'" and original == "’")
    )


# --- Rendering -------------------------------------------------------------------------

_BADGE_CLASS = {
    "not read in context": "warn",
    "dissent": "warn",
    "concurrence": "note",
    "plurality": "warn",
    "separate reasons": "note",
    "overruled": "bad",
    "reframed": "warn",
    "overruled? (machine-classified)": "warn",
    "reframed? (machine-classified)": "note",
    "party submission": "warn",
    "court below": "warn",
    "pinpoint does not exist": "bad",
    "not in the corpus": "bad",
    "quote not found at the pinpoint": "bad",
    "pinpoint not checkable": "note",
    "no pinpoint": "note",
}
_MARK = {"verified": "✓", "not_checkable": "~", "unverified": "✗"}
# What each badge means, shown on hover: what the check found, and what to do about it.
_BADGE_HELP = {
    "not read in context": (
        "The tutor did not read this passage in this conversation before citing it, so it "
        "may be cited from memory. Open it and check it says what the answer says."
    ),
    "dissent": "This passage is in dissenting reasons: it is not the law the court laid down.",
    "concurrence": (
        "This passage is in concurring reasons: they agree with the result, not necessarily "
        "with the majority's reasoning."
    ),
    "plurality": (
        "These reasons were signed by fewer than half the bench: no single set of reasons "
        "spoke for the court."
    ),
    "separate reasons": "This passage is in separate reasons, not the reasons of the court.",
    "overruled": "The court's own Cases Cited list records this decision as overruled.",
    "reframed": "The court's own Cases Cited list records this decision as reframed or restated.",
    "overruled? (machine-classified)": (
        "A model reading later decisions thought this one may have been overruled. Such "
        "labels were wrong about half the time on a sample, so treat it as a question."
    ),
    "reframed? (machine-classified)": (
        "A model reading later decisions thought this one may have been reframed. Such labels "
        "were wrong about half the time on a sample, so treat it as a question."
    ),
    "party submission": ("This paragraph sets out a party's argument, not the court's view."),
    "court below": "This paragraph describes the decision under appeal, not the court's view.",
    "pinpoint does not exist": "The decision has no paragraph with this number.",
    "not in the corpus": (
        "This citation matched nothing in the corpus, so nothing about it was checked. It may "
        "be real but not held, or it may be wrong."
    ),
    "quote not found at the pinpoint": (
        "The quoted words are not in the pinpointed paragraphs or the paragraph either side. "
        "The quote or the pinpoint may be wrong."
    ),
    "pinpoint not checkable": (
        "This decision has no numbered paragraphs in the corpus, so the pinpoint could not "
        "be checked."
    ),
    "no pinpoint": "Cited without a pinpoint, so only the decision's existence was checked.",
    "metadata only: text not in the corpus": (
        "The corpus knows this decision from its citations but does not hold its text, so "
        "nothing it says was checked."
    ),
    "this case is cited by page": "This decision is held by page, and was pinpointed by paragraph.",
    "cite by paragraph": "This decision has numbered paragraphs, and was pinpointed by page.",
}


def annotate(answer: str, citations: list[Citation]) -> str:
    """
    The answer with each citation wrapped as a link into the reader, followed by
    its marks. Inline HTML passes through the markdown renderer and DOMPurify.
    """
    out, last = [], 0
    for c in citations:
        if c.start < last:
            continue
        out.append(answer[last : c.start])
        title = html.escape(c.name or c.text, quote=True)
        label = html.escape(c.text)
        if c.link:
            href = html.escape(c.link, quote=True)
            out.append(f'<a class="cite cite-{c.status}" href="{href}" title="{title}">{label}</a>')
        else:
            out.append(f'<span class="cite cite-{c.status}" title="{title}">{label}</span>')
        explained = html.escape(explain(c), quote=True)
        out.append(
            f'<sup class="cite-mark cite-{c.status}" title="{explained}">{_MARK[c.status]}</sup>'
        )
        out += [
            f'<span class="badge badge-{_BADGE_CLASS.get(b, "note")}" '
            f'title="{html.escape(_BADGE_HELP.get(b, b), quote=True)}">{html.escape(b)}</span>'
            for b in c.badges
        ]
        last = c.end
    out.append(answer[last:])
    return "".join(out)


def explain(c: Citation) -> str:
    """
    What the check of one citation did and did not establish, in plain words, for
    the hover on its mark. A tick says the citation is real and where it points; it
    never says the passage supports what the answer claims, and this says so.
    """
    if c.status == "unverified":
        return "Not verified: " + (_BADGE_HELP.get(c.badges[0], "") if c.badges else "")
    if c.status == "not_checkable":
        return _BADGE_HELP["pinpoint not checkable"] + " The decision itself is in the corpus."
    if c.kind == "provision":
        checked = f"Checked by code: {c.name} is in the corpus"
        if "not read in context" not in c.badges:
            checked += " and the tutor read it in this conversation"
    elif not c.unit_id:
        checked = f"Checked by code: {c.name or c.text} is in the corpus"
    else:
        numbers = sorted(set(c.covered))
        where = f"paragraph{'s' if len(numbers) > 1 else ''} {_runs(numbers)}"
        checked = f"Checked by code: {c.name} is in the corpus and {where} exist"
        if "not read in context" not in c.badges:
            checked += ", and the tutor read them in this conversation"
        if c.quoted and "quote not found at the pinpoint" not in c.badges:
            checked += "; the quoted words are there"
    return (
        f"{checked}. Not checked: that the passage says what the answer says it does. "
        "Open it before relying on it."
    )


def _runs(numbers: list[int]) -> str:
    """[1, 2, 3, 7] -> "1–3, 7"."""
    runs: list[list[int]] = []
    for n in numbers:
        if runs and n == runs[-1][-1] + 1:
            runs[-1].append(n)
        else:
            runs.append([n])
    return ", ".join(f"{r[0]}–{r[-1]}" if len(r) > 1 else str(r[0]) for r in runs)


def summary(citations: list[Citation]) -> dict[str, int]:
    """The counts logged per turn (research/0010 decision 3)."""
    counts: dict[str, int] = {"citations": len(citations)}
    for c in citations:
        counts[c.status] = counts.get(c.status, 0) + 1
        for badge in c.badges:
            counts[badge] = counts.get(badge, 0) + 1
    return counts
