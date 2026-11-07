"""
Decision parsing. Each fixture is a trimmed copy of a real layout from the A2AJ
corpus, named after the decision it came from, because each one is a format the
parser met and once got wrong.
"""

from legal_core.decisions import parse_decision, segments_from_table

HEADER = (
    "Canada (Minister of Citizenship and Immigration) v. Vavilov\n"
    "Collection\nSupreme Court Judgments\nDate\n2019-12-19\n"
    "Neutral citation\n2019 SCC 65\nReport\n[2019] 4 SCR 653\n"
    "Judges\nWagner, Richard; Abella, Rosalie Silberman\n"
    "On appeal from\nFederal Court of Appeal\nSubjects\nAdministrative law\n"
    "Decision Content\n"
)


def test_header_fields_and_judges_split():
    d = parse_decision(HEADER + "[1] Text.\n[2] More.\n[3] End.\n")
    assert d.header["Neutral citation"] == ["2019 SCC 65"]
    assert d.header["Judges"] == ["Wagner, Richard", "Abella, Rosalie Silberman"]
    assert d.header["On appeal from"] == ["Federal Court of Appeal"]


VAVILOV_BODY = (
    "Coram: Wagner C.J. and Abella, Moldaver JJ.\n"
    "Joint Reasons for Judgment: (paras. 1 to 3)\n"
    "Joint Concurring Reasons: (paras. 4 to 5)\n"
    "Wagner C.J. and Moldaver J.\n"
    "Abella and Karakatsanis JJ.\n"
    "Cases Cited\n"
    "By Wagner C.J. and Moldaver J.\n"
    "Overruled: Dunsmuir v. New Brunswick, 2008 SCC 9, [2008] 1 S.C.R. 190; "
    "considered: C.U.P.E. v. N.B. Liquor Corporation, [1979] 2 S.C.R. 227.\n"
    "By Abella and Karakatsanis JJ.\n"
    "Referred to: Baker v. Canada, [1999] 2 S.C.R. 817.\n"
    "Statutes and Regulations Cited\nCitizenship Act, s. 3.\n"
    "The following is the judgment delivered by\n"
    "[1] The Chief Justice and Moldaver J. — This appeal is about review.\n"
    "I. Overview\n"
    "[2] Reasonableness is the presumptive standard.\n"
    "[3] The appeal is dismissed.\n"
    "The following are the reasons delivered by\n"
    "[4] Abella and Karakatsanis JJ. — Forty years ago, the Court began.\n"
    "[5] We would dismiss the appeal.\n"
)


def test_vavilov_grouped_reasons_table():
    d = parse_decision(HEADER + VAVILOV_BODY)
    assert d.unit == "paragraph"
    assert [(s.kind, s.first_para, s.last_para) for s in d.segments] == [
        ("majority", 1, 3),
        ("concurring", 4, 5),
    ]
    assert d.segments[1].authors == "Abella and Karakatsanis JJ."
    assert [p.segment for p in d.paragraphs] == [0, 0, 0, 1, 1]


def test_heading_moves_to_the_paragraph_it_introduces():
    d = parse_decision(HEADER + VAVILOV_BODY)
    assert d.paragraphs[1].heading == "I. Overview"
    assert d.paragraphs[0].text.endswith("This appeal is about review.")


def test_cases_cited_treatment_and_judge():
    d = parse_decision(HEADER + VAVILOV_BODY)
    cited = [(c.treatment, c.judge, c.keys) for c in d.cases_cited]
    assert cited == [
        ("overruled", "Wagner C.J. and Moldaver J.", ("2008 SCC 9", "[2008] 1 SCR 190")),
        ("considered", "Wagner C.J. and Moldaver J.", ("[1979] 2 SCR 227",)),
        ("referred to", "Abella and Karakatsanis JJ.", ("[1999] 2 SCR 817",)),
    ]


def test_greenhouse_gas_interleaved_reasons_table():
    body = (
        "Reasons for Judgment: (paras. 1 to 2)\n"
        "Wagner C.J. (Abella J. concurring)\n"
        "Reasons Dissenting in Part: (paras. 3 to 3)\n"
        "Côté J.\n"
        "Dissenting Reasons: (paras. 4 to 4)\n"
        "Brown J.\n"
        "IN THE MATTER OF References\n"
        "[1] One.\n[2] Two.\n[3] Three.\n[4] Four.\n"
    )
    d = parse_decision(HEADER + body)
    assert [(s.kind, s.authors) for s in d.segments] == [
        ("majority", "Wagner C.J. (Abella J. concurring)"),
        ("dissenting_in_part", "Côté J."),
        ("dissenting", "Brown J."),
    ]


def test_oakes_dotted_numbering_skips_the_quoted_statute():
    body = (
        "The judgment of Dickson C.J. and Lamer J. was delivered by\n"
        "1. The Chief Justice--This appeal concerns s. 8 of the Narcotic Control Act.\n"
        "2. Before reviewing the facts, I set out the provisions:\n"
        "3. (1) Except as authorized by this Act, no person shall have a narcotic.\n"
        "4. (1) No person shall traffic in a narcotic.\n"
        "3. The respondent was charged with possession.\n"
        "4. Following this finding, Mr. Oakes brought a motion.\n"
        "5. At trial the judge held the section invalid.\n"
    )
    d = parse_decision(HEADER + body)
    assert d.unit == "paragraph"
    assert [p.number for p in d.paragraphs] == [1, 2, 3, 4, 5]
    assert d.paragraphs[2].text.startswith("The respondent was charged")
    assert "Except as authorized" in d.paragraphs[1].text
    assert d.segments[0].authors == "The Chief Justice"


def test_housen_bare_numbering_and_inline_dissent():
    body = (
        "The judgment of McLachlin C.J. was delivered by\n"
        "Iacobucci and Major JJ. --\n"
        "1 A court of appeal should not interfere with findings of fact.\n"
        "2 Authority for this abounds.\n"
        "3 The appeal is allowed.\n"
        "The reasons of Gonthier J. were delivered by\n"
        "Bastarache J. (dissenting) --\n"
        "4 I have read the reasons of my colleagues.\n"
        "5 I would dismiss the appeal.\n"
    )
    d = parse_decision(HEADER + body)
    assert [p.number for p in d.paragraphs] == [1, 2, 3, 4, 5]
    assert [(s.kind, s.authors, s.first_para, s.last_para) for s in d.segments] == [
        ("unknown", "Iacobucci and Major JJ.", 1, 3),
        ("dissenting", "Bastarache J.", 4, 5),
    ]


def test_onca_author_line_before_the_first_paragraph():
    text = (
        "R. v. Codina\nCollection\nDecisions of the Court of Appeal\n"
        "Neutral citation\n2020 ONCA 848\nDecision Content\n"
        "COURT OF APPEAL FOR ONTARIO\nOn appeal from the convictions.\n"
        "Doherty J.A.:\nI\noverview [1] The appellant was convicted.\n"
        "[2] The appellant appealed.\nII\nthe evidence\n[3] The events occurred in 2011.\n"
    )
    d = parse_decision(text)
    assert [(s.authors, s.first_para, s.last_para) for s in d.segments] == [("Doherty J.A.", 1, 3)]
    assert d.paragraphs[0].heading == "I overview"
    assert d.paragraphs[2].heading == "II the evidence"


def test_egan_report_pages_become_units():
    body = (
        "The reasons of Lamer C.J. were delivered by\n"
        "LA FOREST J. -- This appeal concerns the Old Age Security Act, and the\n"
        "page 514\n"
        "spouses allowance under s. 19(1).\n"
        "page 515\n"
        "for this purpose one must look at the whole.\n"
    )
    d = parse_decision(HEADER + body)
    assert d.unit == "page"
    assert [(p.number, p.page) for p in d.paragraphs] == [(513, 513), (514, 514), (515, 515)]
    assert "page 514" not in " ".join(p.text for p in d.paragraphs)


def test_unnumbered_decision_falls_back_to_blocks():
    lines = [f"Line {i} of an unnumbered judgment, " + "words " * 80 for i in range(6)]
    d = parse_decision(HEADER + "\n".join(lines))
    assert d.unit == "block"
    assert len(d.paragraphs) == 6


def test_stray_bracket_number_in_text_does_not_split_a_paragraph():
    body = "[1] First.\n[2] As the Court said at para. [3] of an old case, it holds.\n[3] Third.\n"
    d = parse_decision(HEADER + body)
    assert [p.text for p in d.paragraphs] == [
        "First.",
        "As the Court said at para. [3] of an old case, it holds.",
        "Third.",
    ]


def test_who_joined_each_set_of_reasons_is_kept():
    # Singh and Re B.C. Motor Vehicle Act name only the writer in the author line;
    # the statement before it names everyone who joined.
    body = (
        "The reasons of Dickson C.J. and Lamer and Wilson JJ. were delivered by\n"
        "1. Wilson J.--The issue is s. 7.\n"
        "2. Second.\n"
        "The reasons of Beetz, Estey and McIntyre were delivered by\n"
        "3. Beetz J.--The Bill of Rights decides it.\n"
        "The following are the reasons delivered by\n"
        "4. McIntyre J.--I agree in the result.\n"
    )
    d = parse_decision(HEADER + body)
    assert [(s.authors, s.joined) for s in d.segments] == [
        ("Wilson J.", "Dickson C.J. and Lamer and Wilson JJ."),
        ("Beetz J.", "Beetz, Estey and McIntyre"),
        ("McIntyre J.", None),
    ]


def test_the_chief_justice_and_headnote_per_lines_complete_who_joined():
    # OPSEU and Mitchell v Peguis shapes: "The Chief Justice" with no statement, and a
    # writer whose only statement of who joined is the headnote's "Per" line.
    text = HEADER.replace(
        "Decision Content",
        "Present: Dickson C.J. and Beetz, Lamer, Wilson and La Forest JJ.\n"
        "Per La Forest and Beetz JJ.: The appeal fails.\n"
        "Per Lamer and Wilson JJ.: The appeal fails for another reason.\n"
        "Per Dickson C.J.: I agree in the result.\nDecision Content",
    ) + (
        "1. The Chief Justice--I agree in the result.\n"
        "2. La Forest J.--The appeal fails.\n"
        "3. Wilson J.--Another reason.\n"
    )
    d = parse_decision(text)
    assert [(s.authors, s.joined) for s in d.segments] == [
        ("The Chief Justice", "Dickson C.J."),
        ("La Forest J.", "La Forest and Beetz JJ."),
        ("Wilson J.", "Lamer and Wilson JJ."),
    ]


def test_a_dissent_named_only_in_the_headnote_is_a_dissent():
    text = HEADER.replace(
        "Decision Content",
        "Present: Lamer C.J. and Sopinka, Iacobucci and Gonthier JJ.\n"
        "Per Sopinka and Iacobucci JJ.: Allowed.\n"
        "Per Gonthier J. (dissenting): Dismissed.\nDecision Content",
    ) + (
        "The judgment of Iacobucci and Sopinka JJ. was delivered by\n"
        "1. Iacobucci J.--Allowed.\n"
        "The following are the reasons delivered by\n"
        "2. Gonthier J.--Dismissed.\n"
    )
    d = parse_decision(text)
    assert [(s.kind, s.authors, s.joined) for s in d.segments] == [
        ("unknown", "Iacobucci J.", "Iacobucci and Sopinka JJ."),
        ("dissenting", "Gonthier J.", "Gonthier J."),
    ]


def test_a_reasons_table_with_ranges_on_their_own_lines():
    # Ipeelee (2012 SCC 13): each range on its own line, ending in a colon.
    text = (
        "Coram: McLachlin C.J. and Binnie, LeBel, Deschamps, Fish, Abella and Rothstein JJ.\n"
        "Reasons for Judgment:\n(paras. 1 to 98):\n"
        "Reasons Dissenting in Part:\n(paras. 99 to 157):\n"
        "LeBel J. (McLachlin C.J. and Binnie, Deschamps, Fish and Abella JJ. concurring)\n"
        "Rothstein J.\n"
        "R. v. Ipeelee, 2012 SCC 13, [2012] 1 S.C.R. 433\n"
    )
    majority, dissent = segments_from_table(text)
    assert (majority.kind, majority.first_para, majority.last_para) == ("majority", 1, 98)
    assert majority.authors.startswith("LeBel J. (McLachlin C.J.")
    assert (dissent.kind, dissent.authors) == ("dissenting_in_part", "Rothstein J.")
