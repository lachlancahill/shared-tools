"""
Parsing the text of a decision into its parts.

A2AJ gives each decision as one string: a header block (judges, subjects, the
court appealed from), then for SCC decisions a headnote and a "Cases Cited"
list, then the reasons as numbered paragraphs. This module recovers that
structure, because every later step depends on it:

* **paragraphs**, the unit of search and of every pinpoint (research/0004 §1);
* **reasons segments** (majority, concurring, dissenting, with authors), so a
  dissent is labelled wherever it is shown (research/0010 decision 3);
* **headings**, which `read` shows with a paragraph for context;
* the **treatment** the court itself gave each case it cites ("Applied:",
  "Distinguished:", "Overruled:"), which SCC decisions list in a "Cases Cited"
  section. That is treatment by code, with no model involved.

Everything here is best effort over messy text, and says so by leaving fields
empty rather than guessing: an unlabelled segment has kind "unknown", not
"majority".
"""

import re
from dataclasses import dataclass, field
from typing import Literal

from legal_core.citations import clean_text, find_case_citations

# --- Header ------------------------------------------------------------------

HEADER_LABELS = {
    "Collection",
    "Date",
    "Neutral citation",
    "Report",
    "Case number",
    "Docket numbers",
    "Judges",
    "On appeal from",
    "Subjects",
    "Subject",
    "Notes",
}
_BODY_MARKER = "\nDecision Content\n"


def parse_header(text: str) -> dict[str, list[str]]:
    """
    Read the label/value block before "Decision Content".

    Each label is on its own line and its values follow, one per line, until
    the next label. Judges arrive as one "Surname, Given; Surname, Given" line
    and are split.
    """
    head, _, _ = text.partition(_BODY_MARKER)
    header: dict[str, list[str]] = {}
    current: str | None = None
    for line in head.split("\n")[1:]:  # the first line is the style of cause
        line = line.strip()
        if line in HEADER_LABELS:
            current = line
            header[current] = []
        elif current and line:
            header[current].append(line)
    if "Judges" in header:
        header["Judges"] = [
            j.strip() for line in header["Judges"] for j in line.split(";") if j.strip()
        ]
    return header


# --- Units of text: paragraphs, or pages, or blocks ------------------------------

UnitKind = Literal["paragraph", "page", "block"]

# Three paragraph-numbering styles, all measured in the SCC corpus:
#   "[12] "  most decisions from 2000 on, and many older ones re-typeset;
#   "12 "    a bare number at the start of a line (R v Hydro-Québec, Housen);
#   "12. "   a number and a full stop (R v Oakes).
_BRACKET_MARKER = re.compile(r"(?:(?<=\n)|(?<=^)|(?<= ))\[(\d{1,4})\]\s")
_BARE_MARKER = re.compile(r"(?:(?<=\n)|(?<=^))(\d{1,4}) (?=[A-Z“\"‘'(\[])")
_DOTTED_MARKER = re.compile(r"(?:(?<=\n)|(?<=^))(\d{1,4})\.\s")
# The bracket style wins whenever it gives at least this many paragraphs.
_MIN_BRACKET_CHAIN = 3
# Numbering that yields fewer units than this per 10,000 characters is not the
# decision's own (a numbered list of constitutional questions, say), so the
# decision falls back to pages or blocks.
_MIN_UNITS_PER_10K = 1.0

# Older SCR decisions carry the report's page breaks as lines of their own
# ("page 514"). Cases of that era are pinpointed by page ("at p. 520"), so the
# page is recorded for every unit and, where there is no paragraph numbering,
# the pages are the units.
_PAGE_LINE = re.compile(r"(?m)^page (\d{1,4})\n")
# In a block-unit decision, lines shorter than this are merged into the next.
_MIN_BLOCK_CHARS = 400


def _marker_chain(body: str, pattern: re.Pattern[str]) -> list[tuple[int, int, int]]:
    """
    Choose one marker for each paragraph number 1..N, in order.

    Quoted material also contains numbers that look like markers: a statute set
    out in a judgment has its own "3. (1) Except as authorized…" before the
    court's own paragraph 3. So the chain is found in two passes: forward, taking
    the earliest candidate each time, which finds the longest chain N; then
    backward from N, taking for each number the *latest* candidate that still
    comes before the next paragraph. A quotation always precedes the reasons that
    follow it, so the latest candidate is the court's own marker.
    Returns (number, marker start, text start) triples.
    """
    candidates: dict[int, list[re.Match[str]]] = {}
    for match in pattern.finditer(body):
        candidates.setdefault(int(match.group(1)), []).append(match)

    forward: list[re.Match[str]] = []
    position = -1
    while True:
        later = [m for m in candidates.get(len(forward) + 1, []) if m.start() > position]
        if not later:
            break
        forward.append(later[0])
        position = later[0].start()

    # Backward pass. A marker at the start of a line is preferred to one after a
    # space ("overview [1] The appellant" is real, but so is a stray "[12]" in
    # running text), and if the preference ever makes the chain impossible the
    # forward chain is used as it is.
    chosen: list[re.Match[str]] = []
    limit = len(body) + 1
    for number in range(len(forward), 0, -1):
        usable = [m for m in candidates[number] if m.start() < limit]
        at_line_start = [m for m in usable if m.start() == 0 or body[m.start() - 1] == "\n"]
        pick = (at_line_start or usable or [None])[-1]
        if pick is None:
            chosen = forward[::-1]
            break
        chosen.append(pick)
        limit = pick.start()
    return [(int(m.group(1)), m.start(), m.end()) for m in chosen[::-1]]


def _best_chain(body: str) -> list[tuple[int, int, int]]:
    """The bracket chain if it is real, otherwise the longer of the other two styles."""
    brackets = _marker_chain(body, _BRACKET_MARKER)
    if len(brackets) >= _MIN_BRACKET_CHAIN:
        return brackets
    return max(
        (brackets, _marker_chain(body, _BARE_MARKER), _marker_chain(body, _DOTTED_MARKER)),
        key=len,
    )


def strip_page_lines(body: str) -> tuple[str, list[tuple[int, int]]]:
    """
    Remove the "page N" lines, returning (text without them, [(offset, page)]).

    Each offset is where page N begins in the returned text.
    """
    pieces: list[str] = []
    breaks: list[tuple[int, int]] = []
    last, length = 0, 0
    for match in _PAGE_LINE.finditer(body):
        pieces.append(body[last : match.start()])
        length += match.start() - last
        breaks.append((length, int(match.group(1))))
        last = match.end()
    pieces.append(body[last:])
    return "".join(pieces), breaks


def _page_at(offset: int, breaks: list[tuple[int, int]]) -> int | None:
    """The report page that `offset` falls on, or None if the text has no page lines."""
    if not breaks:
        return None
    before = [page for start, page in breaks if start <= offset]
    return before[-1] if before else breaks[0][1] - 1


# A heading is a short line that does not read as the end of a sentence:
# "E. Disposition", "II", "overview", "(2) The Standard of Review".
_MAX_HEADING = 90
_SENTENCE_END = re.compile(r"[.:;,”\"’)]\s*$")


@dataclass
class Paragraph:
    """
    One unit of a decision's text: a numbered paragraph, a report page, or a block.

    `number` is the paragraph number, the page number, or a sequence number,
    according to the decision's `unit`. `page` is the report page the unit starts
    on, where the text records pages.
    """

    number: int
    text: str
    heading: str | None = None
    segment: int | None = None  # index into Decision.segments
    page: int | None = None


def _is_heading(line: str) -> bool:
    line = line.strip()
    return 0 < len(line) <= _MAX_HEADING and not _SENTENCE_END.search(line)


def split_units(body: str) -> tuple[str, list[Paragraph], list[tuple[int, int]], UnitKind]:
    """
    Split a decision body into units. Returns (preamble, units, starts, kind).

    `starts` is (unit number, offset of the unit in the page-stripped body),
    which the segment parser uses to place author lines.

    Paragraph numbering is used when a consistent, dense chain of markers exists.
    Short heading-like lines at the end of one paragraph belong to the next,
    and are moved there as its heading. Without numbering, the report's pages
    are the units; without either, fixed blocks are, and pinpoints into that
    decision cannot be checked.
    """
    text, breaks = strip_page_lines(body)
    chain = _best_chain(text)
    if chain and len(chain) / max(len(text), 1) * 10_000 >= _MIN_UNITS_PER_10K:
        return _paragraph_units(text, chain, breaks)
    if len(breaks) >= 2:
        return _page_units(text, breaks)
    return _block_units(text)


def _paragraph_units(
    text: str, chain: list[tuple[int, int, int]], breaks: list[tuple[int, int]]
) -> tuple[str, list[Paragraph], list[tuple[int, int]], UnitKind]:
    chunks = [
        text[text_start : chain[i + 1][1] if i + 1 < len(chain) else len(text)]
        for i, (_, _, text_start) in enumerate(chain)
    ]
    paragraphs: list[Paragraph] = []
    preamble, carried = _pop_trailing_headings(text[: chain[0][1]])
    for (number, marker, _), chunk in zip(chain, chunks, strict=True):
        own_text, next_carried = _pop_trailing_headings(chunk)
        heading = " ".join(line.strip() for line in carried) or None
        paragraphs.append(
            Paragraph(number, own_text.strip(), heading, page=_page_at(marker, breaks))
        )
        carried = next_carried
    return preamble.strip(), paragraphs, [(n, start) for n, start, _ in chain], "paragraph"


def _page_units(
    text: str, breaks: list[tuple[int, int]]
) -> tuple[str, list[Paragraph], list[tuple[int, int]], UnitKind]:
    bounds = [(0, breaks[0][1] - 1), *breaks]
    units, starts = [], []
    for i, (start, page) in enumerate(bounds):
        end = bounds[i + 1][0] if i + 1 < len(bounds) else len(text)
        units.append(Paragraph(page, text[start:end].strip(), page=page))
        starts.append((page, start))
    return "", units, starts, "page"


def _block_units(text: str) -> tuple[str, list[Paragraph], list[tuple[int, int]], UnitKind]:
    """
    Units for a decision with neither paragraph numbers nor page lines.

    About a thousand SCC decisions from the 1980s and 1990s are like this
    (research/0011). Each line of their text is one of the judgment's own
    paragraphs, so a unit is a line, with short lines (headings, "I. Facts")
    merged into the one that follows. Units are numbered in sequence, and the
    `unit` kind "block" tells every consumer that the numbers are ours, not
    the court's: they cannot be cited or checked as pinpoints.
    """
    units: list[Paragraph] = []
    starts: list[tuple[int, int]] = []
    pending: list[str] = []
    pending_start = offset = 0
    for line in text.split("\n"):
        if not pending:
            pending_start = offset
        pending.append(line)
        offset += len(line) + 1
        if sum(len(x) for x in pending) >= _MIN_BLOCK_CHARS:
            units.append(Paragraph(len(units) + 1, "\n".join(pending).strip()))
            starts.append((len(units), pending_start))
            pending = []
    if any(x.strip() for x in pending):
        units.append(Paragraph(len(units) + 1, "\n".join(pending).strip()))
        starts.append((len(units), pending_start))
    return "", units, starts, "block"


def _pop_trailing_headings(chunk: str) -> tuple[str, list[str]]:
    """Split heading-like trailing lines off a chunk of text. Returns (rest, headings in order)."""
    lines = chunk.rstrip().split("\n")
    trailing: list[str] = []
    # Never strip a chunk down to nothing: its first line is the paragraph itself.
    while len(lines) > 1 and _is_heading(lines[-1]):
        trailing.insert(0, lines.pop())
    return "\n".join(lines), trailing


# --- Reasons segments ----------------------------------------------------------

SegmentKind = Literal["majority", "concurring", "dissenting", "dissenting_in_part", "unknown"]

# Modern SCC decisions tabulate their reasons in the header:
#   Joint Reasons for Judgment: (paras. 1 to 197)
#   Joint Concurring Reasons: (paras. 198 to 343)
#   Wagner C.J. and Moldaver, ... JJ.
#   Abella and Karakatsanis JJ.
# The labels come first and their authors follow in the same order.
_REASONS_TABLE_ROW = re.compile(
    r"^(?P<label>(?:[A-Z][^\n:]{0,160}?)?(?:Reasons|Judgment)[^\n:]{0,120}):\s*\(paras?\.\s*"
    # 2007–2012 decisions put the range on a line of its own, ending in a colon
    # ("(paras. 1 to 98):"); left behind, the colon read as the first authors line
    # and shifted every author down a set of reasons (Ipeelee, 2012 SCC 13).
    r"(?P<first>\d+)\s*(?:to|-|–)\s*(?P<last>\d+)\):?",
    re.M,
)

# Older decisions, and appellate courts, mark each set of reasons with an author
# line: "Wilson J. (dissenting)—", "Per Davis J. (dissenting in part)—",
# "Doherty J.A.:", "The Chief Justice--This appeal", "[198] Abella and
# Karakatsanis JJ. — Forty years ago". It sits at the start of a line, just
# before or at the start of the first paragraph of those reasons.
_AUTHOR_LINE = re.compile(
    r"^(?:\[\d{1,4}\]\s|\d{1,4}\.\s)?(?:Per\s+)?"
    r"(?P<authors>(?:The Chief Justice|[A-ZÀ-Ý][\w.’'\- ,]{0,150}?"
    r"(?:C\.J\.[A-Z.]*|J\.A\.|JJ\.A\.|JJ\.|J\.)))"
    r"\s*(?:\((?P<note>dissenting in part|dissenting|concurring|partially concurring)\))?"
    r"\s*(?:[—–]|--|\s-\s|:(?=\s|$))",
    re.M,
)
# The statement before an author line in older reports, naming everyone who joined
# the reasons: "The reasons of Dickson C.J. and Lamer and Wilson JJ. were delivered
# by", "The judgment of the Court was delivered by". "The following are the reasons
# delivered by" names no one else, and matches nothing here.
_DELIVERED_BY = re.compile(
    r"The (?:judgment|reasons|opinion)s? of (?P<joined>[^\n]{2,300}?)\s+(?:was|were)\s+"
    r"delivered\s+by\s*(?://[^\n]*//\s*)?$"
)
# How far before an author line its "delivered by" statement can sit.
_DELIVERED_BY_LEAD = 400
# An author line more than this far before paragraph 1 is part of the headnote
# ("Per Lamer J.: ..." summaries), not the start of the reasons.
_MAX_AUTHOR_LEAD = 400


@dataclass
class Segment:
    """One set of reasons: who wrote it, what kind it is, and the paragraphs it spans."""

    kind: SegmentKind
    authors: str
    first_para: int
    last_para: int | None = None
    label: str | None = None
    # Who joined these reasons, as the report's "delivered by" statement names them
    # ("Dickson C.J. and Lamer and Wilson JJ.", or "the Court"). The author line
    # names only the writer, and counting the writer alone made majorities look
    # like pluralities (research/debug/2026-10-01-drill-review.md).
    joined: str | None = None


def _kind_from(label: str) -> SegmentKind:
    lowered = label.lower()
    if "dissenting in part" in lowered or "partially dissenting" in lowered:
        return "dissenting_in_part"
    if "dissent" in lowered:
        return "dissenting"
    if "concurring" in lowered:
        return "concurring"
    if "judgment" in lowered:
        return "majority"
    return "unknown"


def segments_from_table(text: str) -> list[Segment]:
    """
    Read the modern SCC reasons table, if the decision has one.

    It comes in two layouts. Grouped: every label line, then every author line
    in the same order (Vavilov). Interleaved: each label line followed by its
    authors (the Greenhouse Gas References). Consecutive label lines mean grouped.
    """
    rows = list(_REASONS_TABLE_ROW.finditer(text))
    if not rows:
        return []
    grouped = all(
        text[a.end() : b.start()].count("\n") == 1 for a, b in zip(rows, rows[1:], strict=False)
    )
    if grouped and len(rows) > 1:
        following = text[rows[-1].end() :].lstrip("\n").split("\n")
        authors = [line.strip() for line in following[: len(rows)]]
    else:
        authors = [text[row.end() :].lstrip("\n").split("\n", 1)[0].strip() for row in rows]
    return [
        Segment(
            _kind_from(row.group("label")),
            author,
            int(row.group("first")),
            int(row.group("last")),
            row.group("label"),
        )
        for row, author in zip(rows, authors, strict=True)
    ]


def segments_from_author_lines(
    body: str, starts: list[tuple[int, int]], unit: UnitKind
) -> list[Segment]:
    """
    Find segments by their author lines.

    `starts` is (unit number, offset) for every unit. With numbered paragraphs an
    author line opens a segment at the first paragraph at or after it, because
    the line precedes the paragraph ("Doherty J.A.:" then "[1]"). With pages or
    blocks it opens the segment at the unit that contains it, and lines before
    the first "delivered by" are ignored, since in those older decisions the
    headnote's "Per Lamer J.:" summaries come first.

    Only an explicit "(dissenting)" or "(concurring)" sets a kind; the rest stay
    "unknown", because an unlabelled opinion is not necessarily the majority.
    """
    if not starts:
        return []
    if unit == "paragraph":
        earliest = starts[0][1] - _MAX_AUTHOR_LEAD
    else:
        earliest = max(body.find("delivered by"), 0)
    by_first_para: dict[int, Segment] = {}
    for match in _AUTHOR_LINE.finditer(body):
        if match.start() < earliest:
            continue
        if unit == "paragraph":
            placed = [number for number, offset in starts if offset >= match.start()][:1]
        else:
            placed = [number for number, offset in starts if offset <= match.start()][-1:]
        if not placed:
            break
        first = placed[0]
        note = match.group("note")
        kind: SegmentKind = _kind_from(note) if note else "unknown"
        # Several matches can land on one paragraph ("The judgment of … was
        # delivered by" then "The Chief Justice--"); the last is the author.
        statement = _DELIVERED_BY.search(
            body, max(0, match.start() - _DELIVERED_BY_LEAD), match.start()
        )
        joined = re.sub(r"\s+", " ", statement.group("joined")).strip() if statement else None
        by_first_para[first] = Segment(kind, match.group("authors").strip(), first, joined=joined)
    segments = [by_first_para[k] for k in sorted(by_first_para)]
    for current, nxt in zip(segments, segments[1:], strict=False):
        current.last_para = nxt.first_para - 1
    if segments:
        segments[-1].last_para = starts[-1][0]
    return segments


# "Present: Dickson C.J. and Beetz, Estey, McIntyre, Lamer and Wilson JJ." names the
# Chief Justice, whom reports elsewhere call only "The Chief Justice".
_PRESENT = re.compile(r"^Present:\s*(?P<judges>[^\n]+)$", re.M)
_CHIEF = re.compile(r"(?P<name>[A-ZÀ-Ý][\w'’-]+(?:\s[A-ZÀ-Ý][\w'’-]+)?)\s+C\.J\.(?:C\.)?")
_THE_CHIEF_JUSTICE = re.compile(r"\bthe Chief Justice\b", re.IGNORECASE)
# The headnote's summary of each set of reasons: "Per Dickson C.J. and Lamer and Wilson
# JJ.: Appellants ...". One line per set of reasons, naming everyone who signed it.
_PER_LINE = re.compile(r"^Per (?P<judges>[^\n:]{3,200}):", re.M)
_PER_NOTE = re.compile(r",?\s*\(?(?P<note>dissenting|concurring)(?P<part> in part)?\)?\s*$", re.I)
_WRITER = re.compile(r"^(?:Per\s+)?(?P<name>[A-ZÀ-Ý][\w'’-]+)")


def fill_joined(segments: list[Segment], text: str) -> None:
    """
    Complete each segment's `joined` from what else the report says (research/debug/
    2026-10-01-drill-review.md):

    * "the Chief Justice" is replaced by the Chief Justice's name, from the
      "Present:" line, so that it can be matched to the bench;
    * a segment with no "delivered by" statement takes the headnote's "Per ...:"
      line that names its writer, when exactly one does. A writer named in two
      (one who joined the majority and also wrote) is left alone: either could be
      theirs, and the wrong one would misstate the count;
    * an unlabelled segment whose writer's one Per line says "(dissenting)" is a
      dissent: R v B (F.F.)'s author lines do not say so, its headnote does.
    """
    present = _PRESENT.search(text)
    chief_match = _CHIEF.search(present.group("judges")) if present else None
    chief = chief_match.group("name") if chief_match else None
    groups = []
    for m in _PER_LINE.finditer(text):
        note = _PER_NOTE.search(m.group("judges"))
        dissent = None
        if note and note.group("note").lower() == "dissenting":
            dissent = "dissenting_in_part" if note.group("part") else "dissenting"
        groups.append((_PER_NOTE.sub("", m.group("judges")).strip(), dissent))

    def named(line: str) -> str:
        return _THE_CHIEF_JUSTICE.sub(f"{chief} C.J.", line) if chief else line

    for segment in segments:
        author = named(segment.authors)
        writer = _WRITER.match(author)
        holding = []
        if writer:
            surname = re.escape(writer.group("name"))
            holding = [g for g in groups if re.search(rf"(?<!\w){surname}(?!\w)", g[0], re.I)]
        if len(holding) == 1 and holding[0][1] and segment.kind == "unknown":
            segment.kind = holding[0][1]
        if segment.joined:
            if segment.joined.casefold() != "the court":
                segment.joined = named(segment.joined)
        elif len(holding) == 1:
            segment.joined = named(holding[0][0])
        elif author != segment.authors:
            # "The Chief Justice" alone: at least say who that is.
            segment.joined = f"{chief} C.J."


def assign_segments(paragraphs: list[Paragraph], segments: list[Segment]) -> None:
    """Point each paragraph at the segment whose range contains it."""
    for paragraph in paragraphs:
        for index, segment in enumerate(segments):
            last = segment.last_para if segment.last_para is not None else paragraph.number
            if segment.first_para <= paragraph.number <= last:
                paragraph.segment = index
                break


# --- Cases Cited ---------------------------------------------------------------

_TREATMENTS = (
    "not followed|referred to|distinguished|disapproved|overruled|considered|discussed|"
    "explained|approved|followed|applied|affirmed|reversed|criticized|criticised|quoted|"
    "cited|mentioned|adopted|compared"
)
_TREATMENT_LABEL = re.compile(rf"(?:^|(?<=[;.\n])\s*)(?P<t>(?i:{_TREATMENTS}))\s*:", re.M)
_BY_JUDGE = re.compile(r"^By (?P<judge>[^\n]{2,120})$", re.M)
_CASES_CITED_END = re.compile(
    r"\n(?:Statutes and Regulations Cited|Authors Cited"
    r"|Treaties and Other International Instruments"
    r"|Rules and Regulations Cited|APPEAL|REFERENCE|APPLICATION|MOTION)\b"
)


@dataclass(frozen=True)
class CitedCase:
    """One entry in a "Cases Cited" list: the court's own treatment of a case."""

    treatment: str  # lower case: "applied", "referred to", "overruled"...
    judge: str | None  # whose reasons cite it, when the list is split by judge
    keys: tuple[str, ...]  # canonical citation keys for the case, as parsed
    text: str


def parse_cases_cited(text: str) -> list[CitedCase]:
    """Parse the SCC "Cases Cited" section, if there is one."""
    start = text.find("\nCases Cited\n")
    if start < 0:
        return []
    section = text[start + len("\nCases Cited\n") :]
    end = _CASES_CITED_END.search(section)
    if end:
        section = section[: end.start()]

    entries: list[CitedCase] = []
    # Walk the section in order, switching judge and treatment as their labels appear.
    marks = sorted(
        [(m.start(), m.end(), "judge", m.group("judge")) for m in _BY_JUDGE.finditer(section)]
        + [
            (m.start(), m.end(), "treatment", m.group("t").lower())
            for m in _TREATMENT_LABEL.finditer(section)
        ]
    )
    judge: str | None = None
    for i, (_, mark_end, kind, value) in enumerate(marks):
        if kind == "judge":
            judge = value.strip()
            continue
        stop = marks[i + 1][0] if i + 1 < len(marks) else len(section)
        for item in section[mark_end:stop].split(";"):
            item = clean_text(item.strip().rstrip("."))
            found = tuple(c.key for c in find_case_citations(item))
            if found:
                entries.append(CitedCase(value, judge, found, item))
    return entries


# --- The whole decision --------------------------------------------------------


@dataclass
class Decision:
    """A parsed decision. `unit` says what `paragraphs` are: paragraphs, pages or blocks."""

    header: dict[str, list[str]]
    preamble: str
    paragraphs: list[Paragraph]
    unit: UnitKind
    segments: list[Segment] = field(default_factory=list)
    cases_cited: list[CitedCase] = field(default_factory=list)


def parse_decision(text: str) -> Decision:
    """
    Parse one decision's full text.

    The segment table wins when present (it is the court's own statement of who
    wrote what); author lines are the fallback for older decisions and for
    courts that do not tabulate their reasons.
    """
    text = clean_text(text)
    header = parse_header(text)
    _, _, body = text.partition(_BODY_MARKER)
    body = body or text
    preamble, paragraphs, starts, unit = split_units(body)
    stripped, _ = strip_page_lines(body)
    segments = segments_from_table(stripped) or segments_from_author_lines(stripped, starts, unit)
    fill_joined(segments, text)
    assign_segments(paragraphs, segments)
    return Decision(header, preamble, paragraphs, unit, segments, parse_cases_cited(stripped))
