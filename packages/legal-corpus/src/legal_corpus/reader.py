"""
`read`: a case's paragraphs in context, or a provision with what it depends on
(research/0010 decision 3, "read before you rely").

For a case, the requested paragraphs come with READ_CONTEXT paragraphs either
side, the heading each sits under, who wrote it and what kind of reasons those
are (a dissent is labelled), and, for enriched cases, the paragraph's role (a
party's submissions, the court below). With no paragraphs asked for, the answer
is the case's outline and brief, so the model can choose where to read.

For a provision, the text comes with the definitions of the defined terms it
uses and the text of the provisions it is "subject to", overrides
("notwithstanding", "despite") or excepts ("except as provided in").

Every unit returned is reported back, because the answer checker's "not read in
context" flag is exact: a pinpoint is read only if `read` returned it.
"""

import json
import re
from dataclasses import dataclass, field

from legal_core.citations import base_section, names_rules
from legal_core.nz import HIGH_COURT_RULES

from legal_corpus.constants import (
    DEFINITION_CHARS,
    PROVISION_DEFINITIONS_MAX,
    PROVISION_NEIGHBOURS,
    READ_CONTEXT,
    READ_MAX_CHARS,
)
from legal_corpus.resolve import resolve_case, resolve_provision, shared_title
from legal_corpus.snapshot import Corpus, _quote

_ROLE_WORDS = {
    "submissions": "a party's submissions",
    "court_below": "the court below's reasons",
    "facts": "facts",
    "analysis": "analysis",
    "holding": "holding",
    "disposition": "disposition",
    "header": "front matter",
    "other": "other",
}
_DEPENDS_ON = re.compile(
    r"\b(?P<how>subject to|notwithstanding|despite|except as (?:otherwise )?provided (?:in|by))"
    r"\s+(?:the\s+)?(?:sections?|subsections?|paragraphs?|ss?\.)\s*"
    r"(?P<section>\d[\w.]*(?:\([^)]{1,6}\))*)",
    re.I,
)
# A section in another Act: "subject to section 37 of the End of Life Choice Act 2019".
# When that Act is not one we hold, the section is not this Act's either.
_OF_ANOTHER_ACT = re.compile(r"\s*(?:of|in)\s+(?:the\s+)?[A-Z]")


@dataclass
class ReadResult:
    text: str
    unit_ids: list[str] = field(default_factory=list)


def read(
    corpus: Corpus, reference: str, paragraphs: list[int] | None = None, cursor: int | None = None
) -> ReadResult:
    """Dispatch on what `reference` names: commentary, a provision, else a case."""
    if reference.startswith("commentary:"):
        return read_commentary(corpus, reference.split("#")[0], paragraphs or [], cursor)
    provision = resolve_provision(corpus, reference)
    if provision and not re.search(corpus.profile.case_shaped, reference):
        return read_provision(corpus, provision.statute_id, provision.section)
    ref = resolve_case(corpus, reference)
    if ref.case_id is None:
        if ref.candidates:
            listed = "\n".join(f"- {c}: {corpus.case(c)['name']}" for c in ref.candidates)
            return ReadResult(
                f"{reference!r} matches more than one case. Call read again with a citation:\n"
                + listed
            )
        shared = shared_title(corpus, reference)
        if shared:
            title, section, ids = shared
            listed = "\n".join(f"- {i}" for i in ids)
            return ReadResult(
                f"{title!r} is the title of {len(ids)} Acts we hold, so {reference!r} does not "
                f"say which. Call read again with the Act's chapter (e.g. '{title}, {ids[0]}, "
                f"s {section}'), and cite it that way in your answer: the answer checker cannot "
                f"check a section of a title several Acts share.\n{listed}"
            )
        return ReadResult(
            f"Nothing in the corpus matches {reference!r}. If it is a case, give its citation; "
            "if a provision, the statute and section (e.g. 'Criminal Code s 265')."
        )
    wanted = list(paragraphs or [])
    if not wanted and ref.para:
        wanted = list(range(ref.para, (ref.para_end or ref.para) + 1))
    if not wanted and ref.page:
        wanted = [ref.page]
    return read_case(corpus, ref.case_id, wanted, cursor)


def case_status(corpus: Corpus, case_id: str) -> list[str]:
    """Overruling and reframing recorded against a case, newest first."""
    rows = corpus.sql(
        """
        select t.treatment, t.citing_case, c.name, c.decision_date, 'court' as method
        from treatments t join cases c on c.case_id = t.citing_case
        where t.cited_case = ? and t.treatment in ('overruled', 'not followed', 'disapproved')
        union all
        select t.treatment, t.citing_case, c.name, c.decision_date, 'machine-classified'
        from llm_treatments t join cases c on c.case_id = t.citing_case
        where t.cited_case = ? and t.treatment in ('overruled', 'reframed')
        order by 4 desc
        """,
        [case_id, case_id],
    )
    return [
        f"{treatment.upper()} by {name}, {citing} ({method})"
        for treatment, citing, name, _, method in rows
    ]


def _segments_line(corpus: Corpus, case: dict) -> str:
    parts = []
    for s in case["segments"] or []:
        kind = corpus.reasons_words(case["case_id"], s["authors"], s["kind"])
        span = f"{s['first_unit']}–{s['last_unit']}" if s["last_unit"] else f"{s['first_unit']}–"
        parts.append(f"{s['authors']}{' (' + kind + ')' if kind else ''}, {span}")
    return "; ".join(parts)


def _roles(corpus: Corpus, case_id: str) -> list[tuple[int, int, str]]:
    return corpus.sql(
        "select first, last, role from roles where case_id = ? order by first", [case_id]
    )


def _role_of(number: int, roles: list[tuple[int, int, str]]) -> str | None:
    return next((role for first, last, role in roles if first <= number <= last), None)


_UNIT_NOTES = {
    "paragraph": "numbered paragraphs",
    "page": "report pages (cite 'at p. N')",
    "block": "passages we numbered: the court's own pinpoints are not in our text, so "
    "cite the case without a pinpoint",
}


def case_header(corpus: Corpus, case: dict) -> list[str]:
    # The NZ corpus's citation-only cases and its Canadian link nodes have no text,
    # so no unit kind (research/0025 §4–5).
    units = f" Units: {_UNIT_NOTES[case['unit']]}." if case["unit"] else ""
    lines = [
        f"{case['name']}, {case['case_id']} — {case['dataset']}, {case['decision_date']}."
        f"{units} Cited by {case['citing']} decision(s) in the corpus.",
    ]
    if case["read_by_ocr"]:
        lines.append(
            "Text: read by OCR from a scan, so a word may be misread. "
            "Quote it with care, and cite the decision by its report."
        )
    if case["segments"]:
        lines.append(f"Reasons: {_segments_line(corpus, case)}")
    status = case_status(corpus, case["case_id"])
    lines.append(
        "Status: " + ("; ".join(status) if status else "no overruling or reframing recorded.")
    )
    topics = corpus.syllabus.topics_for_case.get(case["case_id"], [])
    if topics:
        lines.append(
            f"{corpus.profile.spine}: "
            + "; ".join(f"{s} topic {t} ({title})" for s, t, title in topics)
        )
    return lines


def _outline(corpus: Corpus, case: dict) -> list[str]:
    rows = (
        corpus.search_table.search()
        .where(f"doc_id = {_quote(case['case_id'])} and kind = 'case' and heading is not null")
        .select(["number", "heading"])
        .limit(max(case["unit_count"], 1))
        .to_list()
    )
    rows.sort(key=lambda r: r["number"])
    return [
        f"  {corpus.profile.unit(case['unit'], r['number'])}: {r['heading']}" for r in rows[:80]
    ]


def _brief_lines(corpus: Corpus, case_id: str) -> list[str]:
    rows = corpus.sql("select brief, reviewed from briefs where case_id = ?", [case_id])
    if not rows:
        return []
    brief, reviewed = json.loads(rows[0][0]), rows[0][1]
    label = "reviewed by Chelsea" if reviewed else "machine-generated, not yet reviewed"
    lines = [f"Brief ({label}):", f"  Ratio: {brief['ratio']}"]
    for issue in brief["issues"][:6]:
        at = (
            f" (paras {', '.join(map(str, issue['paragraphs'][:6]))})"
            if issue["paragraphs"]
            else ""
        )
        lines.append(f"  Issue: {issue['question']} — {issue['holding']}{at}")
    for test in brief["tests"][:4]:
        lines.append(f"  Test ({test['relation']}): {test['name']}: {test['statement']}")
    return lines


def read_case(
    corpus: Corpus, case_id: str, wanted: list[int], cursor: int | None = None
) -> ReadResult:
    case = corpus.case(case_id)
    lines = case_header(corpus, case)
    if case["tier"] != "A":
        lines.append(corpus.profile.not_held)
        return ReadResult("\n".join(lines))
    if not wanted and cursor is None:
        lines += _brief_lines(corpus, case_id)
        outline = _outline(corpus, case)
        if outline:
            lines += ["Outline (headings):", *outline]
        lines.append(
            f"{case['unit_count']} units. Call read with `paragraphs` to read the text in context."
        )
        return ReadResult("\n".join(lines))

    if cursor is not None:
        numbers = list(range(cursor, cursor + 40))
    else:
        numbers = sorted(
            {n + d for n in wanted for d in range(-READ_CONTEXT, READ_CONTEXT + 1) if n + d > 0}
        )
    units = sorted(corpus.units(case_id, numbers), key=lambda u: u["number"])
    if not units:
        return ReadResult(
            "\n".join([*lines, f"No units numbered {wanted or cursor} in this case."])
        )
    roles = _roles(corpus, case_id)
    body: list[str] = []
    returned: list[str] = []
    used = sum(len(line) for line in lines)
    last_heading = None
    for unit in units:
        piece = []
        if unit["heading"] and unit["heading"] != last_heading:
            piece.append(f"## {unit['heading']}")
            last_heading = unit["heading"]
        labels = []
        if unit["segment_authors"]:
            kind = corpus.reasons_words(case_id, unit["segment_authors"], unit["segment_kind"])
            labels.append(f"{unit['segment_authors']}{', ' + kind if kind else ''}")
        role = _role_of(unit["number"], roles)
        if role in ("submissions", "court_below", "header"):
            labels.append(f"role: {_ROLE_WORDS[role]}")
        tag = f" [{'; '.join(labels)}]" if labels else ""
        marker = "*" if unit["number"] in wanted else ""
        label = corpus.profile.unit(case["unit"], unit["number"])
        piece.append(f"{marker}{label}{tag}: {unit['text']}")
        text = "\n".join(piece)
        if used + len(text) > READ_MAX_CHARS and body:
            lines += body
            lines.append(f"[Cut at the length limit. Continue with read(cursor={unit['number']}).]")
            return ReadResult("\n".join(lines), returned)
        body.append(text)
        returned.append(unit["id"])
        used += len(text)
    lines += body
    if cursor is not None and units[-1]["number"] < case["unit_count"]:
        lines.append(f"[More follows: read(cursor={units[-1]['number'] + 1}).]")
    return ReadResult("\n".join(lines), returned)


def _not_held(statute_id: str, section: str) -> str:
    """
    What to tell the model about a provision we do not hold.

    An undotted High Court rule gets an explanation, because a bare "not found" sent a
    model on 55 tool calls looking for it (debug/2026-11-07-agent-hunting-old-rules.md).
    """
    note = f"No {'r' if names_rules(statute_id) else 's'} {section} of {statute_id} in the corpus."
    if statute_id == HIGH_COURT_RULES and "." not in section:
        note += (
            " Every current rule is numbered part.rule (e.g. r 8.4), so this is probably a"
            " pre-2016 number. The earlier High Court Rules are not held, so further searches"
            " will not find its text. Tell the user that, and find the current rule by its"
            " subject rather than by its old number."
        )
    return note


def read_provision(corpus: Corpus, statute_id: str, section: str) -> ReadResult:
    unit = corpus.provision(statute_id, section)
    statute = corpus.statute(statute_id)
    if unit is None or statute is None:
        return ReadResult(_not_held(statute_id, section))
    title = (
        statute["title"] if statute["title"] == statute_id else f"{statute['title']}, {statute_id}"
    )
    head = f"{title}, {'r' if names_rules(statute_id) else 's'} {section}"
    if unit["note"]:
        head += f" ({unit['note']})"
    if unit["heading"]:
        head += f" — under '{unit['heading']}'"
    lines = [head, unit["text"]]
    returned = [unit["id"]]

    definitions = definitions_used(corpus, statute_id, section, unit["text"])
    if definitions:
        lines.append("Defined terms this section uses:")
        lines += [
            f"  - '{d['term']}' (s {d['section']}, applies to {d['applies']}): {d['text']}"
            for d in definitions
        ]
    depends = depends_on(corpus, statute_id, section, unit["text"])
    if depends:
        lines.append("Provisions it depends on:")
        for d in depends:
            where = f"s {d['section']}" + (f" of the {d['title']}" if d["title"] else "")
            lines.append(f"  - {d['how']} {where}: {d['text']}")
            returned.append(d["id"])
    topics = corpus.syllabus.topics_for_provision.get((statute_id, base_section(section)), [])
    if topics:
        lines.append(
            f"{corpus.profile.spine}: " + "; ".join(f"{s} topic {t} ({ti})" for s, t, ti in topics)
        )
    (count,) = corpus.sql(
        "select count(distinct citing_case) from interprets where statute = ? and "
        "(section = ? or starts_with(section, ? || '('))",
        [statute_id, section, section],
    )[0]
    lines.append(f"Cited in {count} decision(s) in the corpus (see cases_citing_provision).")
    return ReadResult("\n".join(lines)[:READ_MAX_CHARS], returned)


def statute_around(corpus: Corpus, statute_id: str, section: str) -> dict:
    """
    A section among its neighbours as the statute prints them, for the provision
    reader's left column (research/0020): the sections under the same heading
    (at most PROVISION_NEIGHBOURS either side), the section before and after that
    run, and for each section how many decisions cite it and which syllabus
    topics point to it.
    """
    unit = corpus.provision(statute_id, section)
    number = unit["number"]
    # One more either side than is shown, to know the previous and next sections.
    reach = PROVISION_NEIGHBOURS + 1
    rows = (
        corpus.search_table.search()
        .where(
            f"doc_id = {_quote(statute_id)} and kind = 'provision' "
            f"and number >= {number - reach} and number <= {number + reach}"
        )
        .select(["number", "section", "heading", "note", "text"])
        .limit(2 * reach + 1)
        .to_list()
    )
    rows.sort(key=lambda r: r["number"])
    run = same_heading_run(rows, number, PROVISION_NEIGHBOURS)
    first, last = rows.index(run[0]), rows.index(run[-1])
    cited = dict(
        corpus.sql(
            "select regexp_extract(section, '^[^(]+') as base, count(distinct citing_case) "
            "from interprets where statute = ? and list_contains(?, base) group by base",
            [statute_id, [r["section"] for r in run]],
        )
    )
    for r in run:
        r["cited"] = cited.get(r["section"], 0)
        r["topics"] = corpus.syllabus.topics_for_provision.get((statute_id, r["section"]), [])
        r["current"] = r["number"] == number
    return {
        "sections": run,
        "previous": rows[first - 1] if first > 0 else None,
        "next": rows[last + 1] if last + 1 < len(rows) else None,
    }


def same_heading_run(rows: list[dict], number: int, most_each_side: int) -> list[dict]:
    """
    The unbroken run of `rows` (sorted by number) sharing the heading of the row
    numbered `number`, at most `most_each_side` rows either side of it. Sections
    with no heading count as one run, so the cap is what bounds them.
    """
    at = next(i for i, r in enumerate(rows) if r["number"] == number)
    heading = rows[at]["heading"]
    start = at
    while start > 0 and at - start < most_each_side and rows[start - 1]["heading"] == heading:
        start -= 1
    end = at
    while end + 1 < len(rows) and end - at < most_each_side and rows[end + 1]["heading"] == heading:
        end += 1
    return rows[start : end + 1]


def definitions_used(corpus: Corpus, statute_id: str, section: str, text: str) -> list[dict]:
    """
    Definitions from this statute whose term appears in `text`, longest terms first,
    each as {term, section, applies, text}.

    A definition that applies only to one Part or section is still shown, with
    its scope, because whether it reaches this section is for the reader to
    check against the Act's structure.
    """
    rows = corpus.sql(
        "select section, scope, term, text from definitions where statute_id = ? "
        "order by length(term) desc",
        [statute_id],
    )
    lowered = text.lower()
    found = []
    for def_section, scope, term, definition in rows:
        if def_section == section:
            continue
        if not re.search(rf"\b{re.escape(term.lower())}\b", lowered):
            continue
        found.append(
            {
                "term": term,
                "section": def_section,
                "applies": "the whole Act" if scope == "Act" else f"its {scope} only",
                "text": definition[:DEFINITION_CHARS],
            }
        )
        if len(found) >= PROVISION_DEFINITIONS_MAX:
            break
    return found


def depends_on(corpus: Corpus, statute_id: str, section: str, text: str) -> list[dict]:
    """
    Up to four other sections this one refers to ("subject to s 7", "despite s 12"),
    in this statute or in another one named after the section ("subject to section
    37 of the End of Life Choice Act 2019"), each as {how, statute, title, section,
    text, id}.
    """
    out = []
    seen = set()
    for match in _DEPENDS_ON.finditer(text):
        named = corpus.statute_names.name_after(text, match.end())
        if named:
            target = named[0]
        elif _OF_ANOTHER_ACT.match(text, match.end()):
            continue  # an Act we do not hold: its s 37 is not ours
        else:
            target = statute_id
        other = base_section(match.group("section"))
        if (target, other) in {(statute_id, section), *seen}:
            continue
        seen.add((target, other))
        unit = corpus.provision(target, other)
        if unit:
            out.append(
                {
                    "how": match.group("how").lower(),
                    "statute": target,
                    "title": "" if target == statute_id else unit["title"],
                    "section": match.group("section"),
                    "text": unit["text"][:700],
                    "id": unit["id"],
                }
            )
        if len(out) >= 4:
            break
    return out


def read_commentary(
    corpus: Corpus, doc_id: str, wanted: list[int], cursor: int | None
) -> ReadResult:
    """
    Passages of a commentary source added through the manual channel. Commentary
    explains and criticises; it is never cited as authority, and says so.
    """
    start = cursor or (min(wanted) - READ_CONTEXT if wanted else 1)
    numbers = list(range(max(start, 1), max(start, 1) + 12))
    rows = (
        corpus.search_table.search()
        .where(f"doc_id = {_quote(doc_id)} and number in ({', '.join(map(str, numbers))})")
        .select(["id", "number", "title", "text"])
        .limit(len(numbers))
        .to_list()
    )
    if not rows:
        return ReadResult(f"No passages of {doc_id} from {start}.")
    rows.sort(key=lambda r: r["number"])
    lines = [f"{rows[0]['title']} (commentary: explains, is not authority)"]
    lines += [f"passage {r['number']}: {r['text']}" for r in rows]
    lines.append(f"[More: read('{doc_id}', cursor={rows[-1]['number'] + 1}).]")
    return ReadResult("\n".join(lines)[:READ_MAX_CHARS], [r["id"] for r in rows])
