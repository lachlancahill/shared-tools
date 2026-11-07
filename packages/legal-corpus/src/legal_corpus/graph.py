"""
The graph tools (research/0003, 0010 decision 2): who cites a case, who cites a
provision, the rest of a case's links, and the syllabus.

Every citing row carries **the citing paragraph as its snippet**, because the
passage that does the citing is what shows how a case is used. Rows are ordered
by court (the Supreme Court, then courts of appeal) and then recency, and paged.
A treatment from a court's own "Cases Cited" list is marked as the court's; one
from enrichment is marked machine-classified (research/0003).
"""

import json

from legal_core.citations import base_section, names_rules

from legal_corpus.constants import CITING_MAX_ROWS, CITING_SNIPPET_CHARS, CO_CITED_MAX
from legal_corpus.resolve import ProvisionRef, resolve_case, resolve_provision
from legal_corpus.snapshot import Corpus

# The apex court first, then the courts of appeal, then the rest.
_COURT_ORDER = "case when k.dataset = ? then 0 when list_contains(?, k.dataset) then 1 else 2 end"
NEGATIVE = ("overruled", "not followed", "disapproved", "criticized", "criticised", "reframed")


def _snippet_around(text: str, key: str | None, length: int = CITING_SNIPPET_CHARS) -> str:
    """The citing paragraph, centred on where it cites."""
    at = text.find(key) if key else -1
    start = max(0, at - length // 2) if at >= 0 else 0
    piece = text[start : start + length].strip()
    return ("…" if start else "") + piece + ("…" if start + length < len(text) else "")


def _unresolved(what: str, reference: str, candidates: list[str], corpus: Corpus) -> str:
    if candidates:
        listed = "\n".join(f"- {c}: {corpus.case(c)['name']}" for c in candidates)
        return f"{reference!r} matches several cases; call again with a citation:\n{listed}"
    return f"No {what} in the corpus matches {reference!r}."


def citing_rows(
    corpus: Corpus,
    case_id: str,
    courts: list[str] | None = None,
    since: int | None = None,
    treatment: str | None = None,
    page: int = 1,
) -> list[dict]:
    """
    The decisions citing a case, best first, each with its citing paragraph's
    snippet and any recorded treatment: the rows behind `cases_citing` and the case
    reader's "Cited by" panel. Every row carries `total`, the unpaged count.
    """
    # Parameters in the order their placeholders appear in the SQL text: the court
    # ordering in the select, the treatment join, then the filters.
    params: list = [corpus.profile.apex, list(corpus.profile.appellate)]
    treatment_join = ""
    if treatment:
        wanted = list(NEGATIVE) if treatment.lower() == "negative" else [treatment.lower()]
        treatment_join = (
            "join (select citing_case, cited_case from treatments "
            "where list_contains(?, treatment) "
            "union select citing_case, cited_case from llm_treatments "
            "where list_contains(?, treatment)) t using (citing_case, cited_case)"
        )
        params += [wanted, wanted]
    filters = ["c.cited_case = ?"]
    params.append(case_id)
    if courts:
        filters.append("list_contains(?, k.dataset)")
        params.append([c.upper() for c in courts])
    if since:
        filters.append("year(k.decision_date) >= ?")
        params.append(int(since))
    rows = corpus.sql_dicts(
        f"""
        with hits as (
            select c.citing_case, min(c.citing_unit) as unit, any_value(c.key) as key,
                   any_value(c.pin_para) as pin, k.name, k.dataset, k.decision_date,
                   {_COURT_ORDER} as level
            from cites c join cases k on k.case_id = c.citing_case {treatment_join}
            where {" and ".join(filters)}
            group by c.citing_case, k.name, k.dataset, k.decision_date
        )
        select *, count(*) over () as total from hits
        order by level, decision_date desc
        limit {CITING_MAX_ROWS} offset {(max(page, 1) - 1) * CITING_MAX_ROWS}
        """,
        params,
    )
    labels = _treatment_labels(corpus, [r["citing_case"] for r in rows], case_id)
    units = corpus.units_by_id([f"{r['citing_case']}#{r['unit']}" for r in rows])
    for r in rows:
        unit = units.get(f"{r['citing_case']}#{r['unit']}")
        r["treatment"] = labels.get(r["citing_case"], "")
        r["snippet"] = _snippet_around(unit["text"], r["key"].split()[0]) if unit else ""
        r["year"] = r["decision_date"].year if r["decision_date"] else ""
    return rows


def cases_citing(
    corpus: Corpus,
    reference: str,
    courts: list[str] | None = None,
    since: int | None = None,
    treatment: str | None = None,
    page: int = 1,
) -> str:
    ref = resolve_case(corpus, reference)
    if ref.case_id is None:
        return _unresolved("case", reference, ref.candidates, corpus)
    cited = corpus.case(ref.case_id)
    rows = citing_rows(corpus, ref.case_id, courts, since, treatment, page)
    if not rows:
        return f"No decision in the corpus cites {cited['name']}, {ref.case_id} with those filters."
    total = rows[0]["total"]
    lines = [
        f"{total} decision(s) cite {cited['name']}, {ref.case_id}; rows "
        f"{(page - 1) * CITING_MAX_ROWS + 1}–{(page - 1) * CITING_MAX_ROWS + len(rows)}:"
    ]
    for r in rows:
        pin = f", pinpointing {corpus.profile.para(r['pin'])}" if r["pin"] else ""
        lines.append(
            f"- {r['name']}, {r['citing_case']} ({r['dataset']} {r['year']}){r['treatment']}"
            f" — at {corpus.profile.para(r['unit'])}{pin}: {r['snippet']}"
        )
    if total > page * CITING_MAX_ROWS:
        lines.append(f"[More: cases_citing(page={page + 1}).]")
    return "\n".join(lines)


def _treatment_labels(corpus: Corpus, citing: list[str], cited: str) -> dict[str, str]:
    rows = corpus.sql(
        "select citing_case, treatment, 'court' from treatments "
        "where cited_case = ? and list_contains(?, citing_case) "
        "union all select citing_case, treatment, 'machine-classified' from llm_treatments "
        "where cited_case = ? and list_contains(?, citing_case)",
        [cited, citing, cited, citing],
    )
    labels: dict[str, list[str]] = {}
    for case_id, treatment, method in rows:
        labels.setdefault(case_id, []).append(f"{treatment} ({method})")
    return {k: " · treatment: " + ", ".join(v) for k, v in labels.items()}


def cases_citing_provision(
    corpus: Corpus,
    reference: str,
    courts: list[str] | None = None,
    since: int | None = None,
    page: int = 1,
) -> str:
    """
    Cases citing a provision. A section includes its subsections; a subsection
    also returns citations of the bare section, marked as general.
    """
    ref = resolve_provision(corpus, reference)
    if ref is None:
        return (
            f"No provision in the corpus matches {reference!r}. Give the statute and "
            "section, e.g. 'Criminal Code s 265' or 's. 7 of the Charter'."
        )
    return citing_provision(corpus, ref, courts, since, page)


def citing_provision_rows(
    corpus: Corpus,
    ref: ProvisionRef,
    courts: list[str] | None = None,
    since: int | None = None,
    page: int = 1,
) -> list[dict]:
    """
    The decisions citing a provision, best first, each with its citing paragraph's
    snippet: the rows behind `cases_citing_provision` and the provision reader's
    panel. A row citing only the bare section when a subsection was asked for is
    marked `general`. Every row carries `total`, the unpaged count.
    """
    written = ref.written
    exact = base_section(written) == written
    filters = ["i.statute = ?", "(i.section = ? or starts_with(i.section, ? || '('))"]
    params: list = [ref.statute_id, written, written]
    if not exact:
        filters[1] = "(i.section = ? or starts_with(i.section, ? || '(') or i.section = ?)"
        params.append(ref.section)
    if courts:
        filters.append("list_contains(?, k.dataset)")
        params.append([c.upper() for c in courts])
    if since:
        filters.append("year(k.decision_date) >= ?")
        params.append(int(since))
    rows = corpus.sql_dicts(
        f"""
        with hits as (
            select i.citing_case, min(i.citing_unit) as unit, any_value(i.section) as section,
                   k.name, k.dataset, k.decision_date, {_COURT_ORDER} as level
            from interprets i join cases k on k.case_id = i.citing_case
            where {" and ".join(filters)}
            group by i.citing_case, k.name, k.dataset, k.decision_date
        )
        select *, count(*) over () as total from hits order by level, decision_date desc
        limit {CITING_MAX_ROWS} offset {(max(page, 1) - 1) * CITING_MAX_ROWS}
        """,
        [corpus.profile.apex, list(corpus.profile.appellate), *params],
    )
    units = corpus.units_by_id([f"{r['citing_case']}#{r['unit']}" for r in rows])
    for r in rows:
        unit = units.get(f"{r['citing_case']}#{r['unit']}")
        r["general"] = r["section"] == ref.section and not exact
        r["snippet"] = _snippet_around(unit["text"], r["section"]) if unit else ""
        r["year"] = r["decision_date"].year if r["decision_date"] else ""
    return rows


def citing_provision(
    corpus: Corpus,
    ref: ProvisionRef,
    courts: list[str] | None = None,
    since: int | None = None,
    page: int = 1,
) -> str:
    """`cases_citing_provision` for a provision already resolved."""
    rows = citing_provision_rows(corpus, ref, courts, since, page)
    statute = corpus.statute(ref.statute_id)
    title = statute["title"] if statute else ref.statute_id
    mark = "r" if names_rules(ref.statute_id) else "s"
    name = f"{title} {mark} {ref.written}"
    if not rows:
        return f"No decision in the corpus cites {name} with those filters."
    lines = [f"{rows[0]['total']} decision(s) cite {name}:"]
    for r in rows:
        general = f" (cites {mark} {r['section']} generally)" if r["general"] else ""
        lines.append(
            f"- {r['name']}, {r['citing_case']} ({r['dataset']} {r['year']}){general}"
            f" — at {corpus.profile.para(r['unit'])}: {r['snippet']}"
        )
    if rows[0]["total"] > page * CITING_MAX_ROWS:
        lines.append(f"[More: cases_citing_provision(page={page + 1}).]")
    return "\n".join(lines)


RELATIONS = ("cites", "status", "treatment_summary", "co_cited", "tests", "syllabus_topics")


def case_links(corpus: Corpus, reference: str, relation: str) -> str:
    ref = resolve_case(corpus, reference)
    if ref.case_id is None:
        return _unresolved("case", reference, ref.candidates, corpus)
    case = corpus.case(ref.case_id)
    title = f"{case['name']}, {ref.case_id}"
    if relation == "cites":
        rows = corpus.sql(
            "select c.cited_case, k.name, count(*) n, min(c.citing_unit) first_unit "
            "from cites c join cases k on k.case_id = c.cited_case where c.citing_case = ? "
            "group by 1, 2 order by n desc, first_unit limit 40",
            [ref.case_id],
        )
        if not rows:
            return f"{title} cites no case we hold."
        return f"{title} cites:\n" + "\n".join(
            f"- {name}, {cid}: {n} time(s), first at {corpus.profile.para(first)}"
            for cid, name, n, first in rows
        )
    if relation == "status":
        from legal_corpus.reader import case_status

        status = case_status(corpus, ref.case_id)
        negative = corpus.sql(
            "select treatment, count(*) from treatments where cited_case = ? "
            "and list_contains(?, treatment) group by 1",
            [ref.case_id, list(NEGATIVE)],
        )
        lines = [f"Status of {title}:"]
        lines += [f"- {s}" for s in status] or ["- No overruling or reframing recorded."]
        if negative:
            lines.append(
                "Negative treatment in courts' own Cases Cited lists: "
                + ", ".join(f"{t} ×{n}" for t, n in negative)
            )
        lines.append(
            "Absence of a record is not proof of good law: the graph sees only the corpus."
        )
        return "\n".join(lines)
    if relation == "treatment_summary":
        rows = corpus.sql(
            "select treatment, 'court' m, count(*) from treatments where cited_case = ? group by 1 "
            "union all select treatment, 'machine-classified', count(*) from llm_treatments "
            "where cited_case = ? group by 1 order by 3 desc",
            [ref.case_id, ref.case_id],
        )
        (citing,) = corpus.sql(
            "select count(distinct citing_case) from cites where cited_case = ?", [ref.case_id]
        )[0]
        lines = [f"{title} is cited by {citing} decision(s). Recorded treatment:"]
        lines += [f"- {t} ({m}): {n}" for t, m, n in rows] or ["- none recorded"]
        return "\n".join(lines)
    if relation == "co_cited":
        rows = corpus.sql(
            f"""
            select other.cited_case, k.name, count(distinct other.citing_case) n
            from cites mine join cites other on other.citing_case = mine.citing_case
            join cases k on k.case_id = other.cited_case
            where mine.cited_case = ? and other.cited_case <> ?
            group by 1, 2 order by n desc limit {CO_CITED_MAX}
            """,
            [ref.case_id, ref.case_id],
        )
        return f"Cases most often cited alongside {title}:\n" + "\n".join(
            f"- {name}, {cid}: together in {n} decision(s)" for cid, name, n in rows
        )
    if relation == "tests":
        own = corpus.sql(
            "select slug, name, relation, statement, steps from tests where case_id = ?",
            [ref.case_id],
        )
        if not own:
            return f"No tests are recorded for {title} (only enriched syllabus cases have them)."
        lines = [f"Tests in {title} (machine-extracted):"]
        for slug, name, relation_kind, statement, steps in own:
            lines.append(f"- {name} [{relation_kind}]: {statement}")
            for step in json.loads(steps):
                paras = ", ".join(map(str, step["paragraphs"]))
                lines.append(f"    • {step['step']}" + (f" (paras {paras})" if paras else ""))
            others = corpus.sql(
                "select t.case_id, k.name, t.relation from tests t join cases k using (case_id) "
                "where t.slug = ? and t.case_id <> ?",
                [slug, ref.case_id],
            )
            if others:
                lines.append("    Also: " + "; ".join(f"{n}, {c} ({r})" for c, n, r in others))
        return "\n".join(lines)
    if relation == "syllabus_topics":
        topics = corpus.syllabus.topics_for_case.get(ref.case_id, [])
        if not topics:
            return f"{title} is not a syllabus reading."
        return f"{title} is a reading for:\n" + "\n".join(
            f"- {s} topic {t}: {title_}" for s, t, title_ in topics
        )
    return f"Unknown relation {relation!r}. Use one of: {', '.join(RELATIONS)}."


def syllabus(corpus: Corpus, subject: str, topic: str | None = None) -> str:
    subjects = corpus.syllabus.subjects
    spine = corpus.profile.spine
    if subject not in subjects:
        listed = ", ".join(subjects) or "none yet"
        return f"No {spine} for {subject!r}. Subjects: {listed}."
    data = subjects[subject]
    if data.get("drafted_by") == "model":
        verified = "machine-selected from the citation graph, checked by code"
        if data.get("reviewed_by") == "model":
            verified += ", then read against the judgments by the model (not by a lawyer)"
    elif data.get("verified"):
        verified = "verified against the PDF"
    else:
        verified = "a draft, not yet verified"
    if topic is None:
        lines = [f"{data['title']}: {spine} ({verified}). Topics:"]
        for t in data["topics"]:
            cases = sum(1 for r in t["readings"] if r["kind"] == "case")
            lines.append(f"- {t['id']}. {t['title']} ({cases} case reading(s))")
        lines.append("Call again with a topic id for its text and readings.")
        return "\n".join(lines)
    found = next((t for t in data["topics"] if t["id"] == str(topic)), None)
    if found is None:
        return f"No topic {topic!r} in {subject}."
    lines = [
        f"{data['title']}, topic {found['id']}: {found['title']} ({verified})",
        found["text"][:4000],
    ]
    lines.append("Readings:")
    for group in group_readings(found["readings"]):
        if group["kind"] == "provisions":
            statute = corpus.statute(group["statute"])
            title = statute["title"] if statute else group["statute"]
            optional = " (optional)" if group["optional"] else ""
            lines.append(f"- provisions: {title}, s {', '.join(group['sections'])}{optional}")
            continue
        r = group
        scope = f" ({r['scope']})" if r.get("scope") else ""
        scope += " (optional)" if r.get("optional") else ""
        if r["kind"] == "case" and r.get("case_id"):
            case = corpus.case(r["case_id"])
            note = " — passages only, no checkable pinpoints" if case["unit"] == "block" else ""
            lines.append(f"- case: {case['name']}, {r['case_id']}{scope}{note}")
        elif r["kind"] == "case":
            lines.append(f"- case (not in the corpus): {r.get('name') or r.get('citation')}{scope}")
        else:
            lines.append(f"- {r['kind']}: {r['as_written']}{scope}")
    return "\n".join(lines)


def group_readings(readings: list[dict]) -> list[dict]:
    """
    A topic's readings with each run of sections of one statute folded into one
    entry: a Model Code chapter is dozens of rules, which read better as a list.
    """
    grouped: list[dict] = []
    for r in readings:
        if r["kind"] != "provision":
            grouped.append(r)
        elif (
            grouped
            and grouped[-1]["kind"] == "provisions"
            and grouped[-1]["statute"] == r["statute"]
            and grouped[-1]["optional"] == bool(r.get("optional"))
        ):
            grouped[-1]["sections"].append(r["section"])
        else:
            grouped.append(
                {
                    "kind": "provisions",
                    "statute": r["statute"],
                    "sections": [r["section"]],
                    "optional": bool(r.get("optional")),
                }
            )
    return grouped
