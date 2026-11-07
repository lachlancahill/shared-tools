"""
Citation parsing. Every example string here was copied from a real SCC or ONCA
decision in the A2AJ corpus, because the parser's job is that text, not the
Canadian Guide's idealised forms.
"""

import pytest
from legal_core.citations import (
    CONSTITUTION_1867,
    CONSTITUTION_1982,
    StatuteNames,
    clean_text,
    find_case_citations,
    find_provision_references,
)


def keys(text: str) -> list[str]:
    return [c.key for c in find_case_citations(clean_text(text))]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Canadian Western Bank v. Alberta, 2007 SCC 22, [2007] 2 S.C.R. 3;",
            ["2007 SCC 22", "[2007] 2 SCR 3"],
        ),
        ("Re: Anti-Inflation Act, [1976] 2 S.C.R. 373;", ["[1976] 2 SCR 373"]),
        ("Munro v. National Capital Commission, [1966] S.C.R. 663;", ["[1966] SCR 663"]),
        ("Russell v. The Queen (1882), 7 App. Cas. 829;", ["7 App Cas 829"]),
        (
            "Attorney-General for Ontario v. Attorney-General for the Dominion, [1896] A.C. 348;",
            ["[1896] AC 348"],
        ),
        ("In re “Insurance Act, 1910” (1913), 48 S.C.R. 260, aff’d", ["48 SCR 260"]),
        (
            "R. v. Oakes, [1986] 1 SCR 103, 26 DLR (4th) 200",
            ["[1986] 1 SCR 103", "26 DLR (4th) 200"],
        ),
        ("(1986), 26 D.L.R. (4th) 200", ["26 DLR (4th) 200"]),
        ("Prosko v. The King (1922) 63 SCR 226", ["63 SCR 226"]),
        (
            "Mason v. Minister of Citizenship and Immigration, 2019 FC 1251, at para. 22 (CanLII)",
            ["2019 FC 1251"],
        ),
        ("R. v. Codina, 2020 ONCA 848", ["2020 ONCA 848"]),
        ("see 1998 CanLII 1234 (ON CA)", ["1998 CanLII 1234"]),
        ("Donoghue v Stevenson, [1932] UKHL 100", ["[1932] UKHL 100"]),
        ("(1983), 64 O.R. (2d) 1", ["64 OR (2d) 1"]),
    ],
)
def test_case_citations_found_and_keyed(text, expected):
    assert keys(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "In 2019 the Court heard 65 appeals.",
        "the SCC held in 2019 that",
        "from 1990 to 1995 the Act applied",
        "paragraphs 12 and 13 of the agreement",
    ],
)
def test_prose_is_not_a_citation(text):
    assert keys(text) == []


def test_pinpoint_paragraph_range():
    [c] = find_case_citations("Craig, 2012 SCC 43, at paras. 28-30; Henry")
    assert (c.key, c.para, c.para_end) == ("2012 SCC 43", 28, 30)


def test_pinpoint_page():
    [c] = find_case_citations("C.U.P.E., [1979] 2 S.C.R. 227, at p. 236")
    assert (c.key, c.page, c.para) == ("[1979] 2 SCR 227", 236, None)


def test_bare_number_after_citation_is_not_a_pinpoint():
    [c] = find_case_citations("2019 SCC 65, 12 cases later")
    assert (c.para, c.page) == (None, None)


def test_span_covers_the_pinpoint():
    text = "see Vavilov, 2019 SCC 65, at para. 23, which"
    [c] = find_case_citations(text)
    assert text[c.start : c.end] == "2019 SCC 65, at para. 23"


def test_clean_text_removes_italics_spacing_and_odd_hyphens():
    assert clean_text("Constitution Act, 1867 , Part III") == "Constitution Act, 1867, Part III"
    assert clean_text("R.S.C. 1985, c. C‑46") == "R.S.C. 1985, c. C-46"


# --- Statute references -----------------------------------------------------

STATUTES = [
    ("RSC 1985, c C-46", "Criminal Code"),
    ("SC 2001, c 27", "Immigration and Refugee Protection Act"),
    ("RSC 1985, c I-21", "Interpretation Act"),
    ("RSO 1990, c I.11", "Interpretation Act"),
    ("RSO 1990, c E.19", "Environmental Protection Act"),
    ("SC 2018, c 12", "Greenhouse Gas Pollution Pricing Act"),
]


@pytest.fixture(scope="module")
def names():
    return StatuteNames(STATUTES)


def refs(text, names):
    return [(r.statute, r.section) for r in find_provision_references(clean_text(text), names)]


def test_section_of_named_statute(names):
    text = "the “Peace, Order, and good Government” clause of s. 91 of the Constitution Act, 1867"
    assert refs(text, names) == [(CONSTITUTION_1867, "91")]


def test_charter_is_the_constitution_act_1982(names):
    assert refs("a breach of s. 7 of the Charter", names) == [(CONSTITUTION_1982, "7")]
    assert refs("Canadian Charter of Rights and Freedoms, s. 1", names) == [
        (CONSTITUTION_1982, "1")
    ]


def test_subsections_and_lists(names):
    text = "contrary to s. 91(1) of the Immigration and Refugee Protection Act, 2001, c. 27"
    assert refs(text, names) == [("SC 2001, c 27", "91(1)")]
    assert refs("under ss. 91 and 92 of the Constitution Act, 1867", names) == [
        (CONSTITUTION_1867, "91"),
        (CONSTITUTION_1867, "92"),
    ]
    assert refs("s. 265(1)(a) of the Criminal Code", names) == [("RSC 1985, c C-46", "265(1)(a)")]


def test_name_then_chapter_then_section(names):
    text = "Criminal Code, R.S.C. 1985, c. C-46, s. 265"
    assert refs(text, names) == [("RSC 1985, c C-46", "265")]


def test_ambiguous_title_needs_a_chapter(names):
    assert refs("s. 12 of the Interpretation Act", names) == []
    assert refs("Interpretation Act, R.S.O. 1990, c. I.11, s. 10", names) == [
        ("RSO 1990, c I.11", "10")
    ]
    assert refs("s. 12 of the Interpretation Act, R.S.C. 1985, c. I-21", names) == [
        ("RSC 1985, c I-21", "12")
    ]


def test_section_with_no_statute_is_skipped(names):
    assert refs("The Registrar relied on s. 3(2)(a).", names) == []


def test_year_after_a_section_is_not_another_section(names):
    assert refs("s. 7 of the Charter, 2019 SCC 65", names) == [(CONSTITUTION_1982, "7")]


def test_title_must_end_on_a_word_boundary(names):
    # "Criminal Code" must not match the start of "Criminal Code Amendment Act".
    assert refs("s. 4 of the Criminal Codex", names) == []


# The shapes below are from the tutor's answers
# (research/debug/2026-10-01-conversation-review-topic-5.md).


def test_the_bill_of_rights_by_its_short_name(names):
    assert refs("Bill of Rights s 2(e)", names) == [("SC 1960, c 44", "2(e)")]
    assert refs("s 2(e) of the Bill of Rights", names) == [("SC 1960, c 44", "2(e)")]


def test_a_short_name_inside_a_longer_one_is_not_ours(names):
    # Quebec's Charter, and New Zealand's and Alberta's Bills of Rights, are other laws.
    assert refs("Quebec Charter s 10", names) == []
    assert refs("NZ Bill of Rights s 5", names) == []
    assert refs("Alberta Bill of Rights, s 1", names) == []
    assert refs("Canadian Charter s 7", names) == [(CONSTITUTION_1982, "7")]


def test_a_possessive_name_before_a_section(names):
    assert refs("the Charter's s 1 lets the government justify it", names) == [
        (CONSTITUTION_1982, "1")
    ]


def test_names_in_finds_each_statute_named_on_a_line(names):
    text = clean_text("(Canadian Bill of Rights, SC 1960, c 44): s 1(a), unlike the Charter")
    found = StatuteNames([*STATUTES, ("SC 1960, c 44", "Canadian Bill of Rights")]).names_in(
        text, 0, len(text)
    )
    assert [statute for _, statute in found] == ["SC 1960, c 44", CONSTITUTION_1982]


def test_a_name_that_ends_the_text_ends_where_it_does(names):
    text = "a breach of s. 7 of the Charter"
    assert [r.end for r in find_provision_references(text, names)] == [len(text)]
