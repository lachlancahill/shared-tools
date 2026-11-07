"""
New Zealand citations (research/0024). Every example string is copied from a real
NZ judgment in JDO or from the Supreme Court's own site.

The Canadian corpus's parsing must not change: the regression for that is run over
all SCC and ONCA paragraphs and recorded in research/0024 (no citation lost or
changed; 251 added, NZ reports inside Canadian judgments).
"""

import pytest
from legal_core.citations import (
    StatuteNames,
    clean_text,
    find_case_citations,
    find_provision_references,
    find_rule_references,
)
from legal_core.nz import (
    CONDUCT_RULES,
    DISTRICT_COURT_RULES,
    HIGH_COURT_RULES,
    NZ_STATUTE_NAMES,
    NZBORA,
    year_less_names,
)


def parsed(text: str) -> list[tuple]:
    return [(c.key, c.kind, c.para, c.para_end) for c in find_case_citations(clean_text(text))]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "See Siemer v Stiassny [2013] NZSC 110 at [11] and",
            [("[2013] NZSC 110", "foreign", 11, None)],
        ),
        ("Below at [380]–[381] per Winkelmann CJ", []),
        ("[1967] NZLR 1069.", [("[1967] NZLR 1069", "report", None, None)]),
        (
            "Hansen v R [2007] NZSC 7, [2007] 3 NZLR 1 at [104]–[106].",
            [("[2007] NZSC 7", "foreign", None, None), ("[2007] 3 NZLR 1", "report", 104, 106)],
        ),
        ("(1990) 6 CRNZ 12", [("6 CRNZ 12", "report", None, None)]),
        ("[2002] NZAR 308", [("[2002] NZAR 308", "report", None, None)]),
        ("[2025] NZEmpC 5 at [3]", [("[2025] NZEmpC 5", "foreign", 3, None)]),
        # A volume-numbered report keys the same whichever bracket holds its year;
        # NZLR and ERNZ restart volumes each year, so theirs stays.
        ("[1989] 1 PRNZ 451", [("1 PRNZ 451", "report", None, None)]),
        ("[1982] 1 NZFLR 165", [("1 NZFLR 165", "report", None, None)]),
        ("[1990] 2 NZLR 403", [("[1990] 2 NZLR 403", "report", None, None)]),
        ("[1999] 1 ERNZ 1", [("[1999] 1 ERNZ 1", "report", None, None)]),
        ("(1997) 16 FRNZ 258", [("16 FRNZ 258", "report", None, None)]),
    ],
)
def test_neutral_citations_reports_and_bracket_pinpoints(text, expected):
    assert parsed(text) == expected


@pytest.mark.parametrize(
    ("text", "key"),
    [
        (
            "Orlov v New Zealand Law Society (Auckland Branch) (No 5) HC Auckland "
            "CIV-2010-404-2868, 7 December 2011.",
            "CIV-2010-404-2868 2011-12-07",
        ),
        ("LEON SALT V RICHARD FELL CA CA133/06  2 November 2006", "CA133/2006 2006-11-02"),
        ("COA CA233/2011 28 September 2011", "CA233/2011 2011-09-28"),
        ("BURKE V SUPERINTENDENT SC SC CIV 3/2004 30 June 2004", "SC3/2004 2004-06-30"),
        ("HC WN CIV 2001-485-591  30 August 2005", "CIV-2001-485-591 2005-08-30"),
        ("ARVAND V R SC SC CRI 3/2004", "SC3/2004"),
    ],
)
def test_file_numbers_with_and_without_dates(text, key):
    [citation] = find_case_citations(clean_text(text))
    assert (citation.key, citation.kind) == (key, "file")


def test_a_bare_bracketed_number_is_not_a_pinpoint():
    # "[2]" after a citation opens nothing: only "at [2]" is a pinpoint.
    [citation] = find_case_citations(clean_text("[2013] NZSC 110 [2] The appeal"))
    assert citation.para is None


@pytest.fixture(scope="module")
def nz_names() -> StatuteNames:
    titles = [
        NZBORA,
        "Crimes Act 1961",
        "Crimes Act 1908",
        "Sentencing Act 2002",
        "Evidence Act 2006",
        HIGH_COURT_RULES,
        DISTRICT_COURT_RULES,
        CONDUCT_RULES,
    ]
    in_force = [
        NZBORA,
        "Crimes Act 1961",
        "Sentencing Act 2002",
        "Evidence Act 2006",
        HIGH_COURT_RULES,
        DISTRICT_COURT_RULES,
        CONDUCT_RULES,
    ]
    pairs = [(t, t) for t in titles] + year_less_names(in_force)
    return StatuteNames(pairs, built_in=NZ_STATUTE_NAMES)


@pytest.mark.parametrize(
    ("text", "statute", "section"),
    [
        ("s 5 of the New Zealand Bill of Rights Act 1990", NZBORA, "5"),
        ("s 5 of the Bill of Rights", NZBORA, "5"),
        ("NZBORA s 27(1)", NZBORA, "27(1)"),
        ("s 167 of the Crimes Act 1961", "Crimes Act 1961", "167"),
        ("s 48 of the Crimes Act", "Crimes Act 1961", "48"),
        ("Sentencing Act 2002, s 8(g)", "Sentencing Act 2002", "8(g)"),
    ],
)
def test_nz_statutes_by_title_short_title_and_acronym(nz_names, text, statute, section):
    [ref] = find_provision_references(clean_text(text), nz_names)
    assert (ref.statute, ref.section) == (statute, section)


def test_year_less_name_needs_exactly_one_act_in_force():
    pairs = year_less_names(["Crimes Act 1961", "Evidence Act 2006", "Evidence Act 1908"])
    assert ("Crimes Act 1961", "Crimes Act") in pairs
    assert all(short != "Evidence Act" for _, short in pairs)


@pytest.mark.parametrize(
    ("text", "statute", "sections"),
    [
        ("r 5.17", HIGH_COURT_RULES, ["5.17"]),
        ("rule 5.17", HIGH_COURT_RULES, ["5.17"]),
        ("HCR r 5.17", HIGH_COURT_RULES, ["5.17"]),
        ("High Court Rules 2016, r 5.17", HIGH_COURT_RULES, ["5.17"]),
        # Naming the current instrument cannot turn its predecessor's number
        # into a current rule: the published-corpus audit found this bypass.
        ("High Court Rules, r 136", None, []),
        ("r 187(3)(a) of the High Court Rules", None, []),
        ("HCR rr 5.17 and 136", HIGH_COURT_RULES, ["5.17"]),
        ("r 5.17 of the High Court Rules 2016", HIGH_COURT_RULES, ["5.17"]),
        ("DCR r 5.17", DISTRICT_COURT_RULES, ["5.17"]),
        ("rr 5.17–5.20", HIGH_COURT_RULES, ["5.17", "5.20"]),
        (
            "r 13.2 of the Conduct and Client Care Rules",
            CONDUCT_RULES,
            ["13.2"],
        ),
        # The year in a title is not a rule number, and a named Act is not rules.
        ("Rules 2008", None, []),
        ("Evidence Act 2006, r 5.17", None, []),
        # A High Court rule is part.rule, so the default takes nothing else: the old
        # numbering, the Court of Appeal's rules and the conduct rules' sub-rules.
        ("Under r 43(3) the appeal is deemed abandoned", None, []),
        ("had breached r 13.5.3 in doing so", None, []),
        ("rr 5.17 and 43", HIGH_COURT_RULES, ["5.17"]),
        ("the application under r 5.35A", HIGH_COURT_RULES, ["5.35A"]),
        # A name we cannot resolve is still a name: these are not the High Court's.
        ("r 36.15 of the Criminal Procedure Rules 2015 (UK)", None, []),
        ("r 5.1 of the then NZX Listing Rules", None, []),
        ("Supreme Court Rules 2009 (UK), r 15.1.", None, []),
        ("r 43 of the Court of Appeal (Civil) Rules", None, []),
        # "the Rules" names nothing; conduct rules need not have dotted numbers.
        ("Rule 32.2 of the Rules provides for a freezing order", HIGH_COURT_RULES, ["32.2"]),
        ("High Court Rules, r 2.3(4).", HIGH_COURT_RULES, ["2.3(4)"]),
        ("r 13 of the Conduct and Client Care Rules", CONDUCT_RULES, ["13"]),
    ],
)
def test_nz_rules_resolve_by_acronym_short_name_and_a_bare_rule(nz_names, text, statute, sections):
    refs = find_rule_references(clean_text(text), nz_names, HIGH_COURT_RULES)
    assert [(r.statute, r.section) for r in refs] == (
        [(statute, section) for section in sections] if statute else []
    )


def test_a_bare_rule_is_not_guessed_without_a_default(nz_names):
    assert find_rule_references(clean_text("r 5.17"), nz_names) == []
