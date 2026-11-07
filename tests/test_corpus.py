"""The corpus tools over the fixture snapshot: resolution, read, the graph, keyword search."""

from conftest import MORAL, OAKES
from legal_corpus import graph, reader, search
from legal_corpus.resolve import resolve_case, resolve_provision


def test_a_parallel_report_citation_resolves_to_the_case(corpus):
    ref = resolve_case(corpus, "26 D.L.R. (4th) 200, at para. 69")
    assert (ref.case_id, ref.para) == (OAKES, 69)


def test_a_name_resolves_when_it_is_unique(corpus):
    assert resolve_case(corpus, "R v Oakes").case_id == OAKES
    assert resolve_case(corpus, "Oakes at para 70").para == 70


def test_provisions_resolve_in_the_forms_people_write(corpus):
    for written in ("Criminal Code, s. 265(1)(a)", "Criminal Code s 265"):
        ref = resolve_provision(corpus, written)
        assert (ref.statute_id, ref.section) == ("RSC 1985, c C-46", "265")


def test_read_lists_the_acts_a_shared_title_could_mean(corpus):
    # "Interpretation Act, s 8.1" said nothing matched, though the federal Act was held
    # (backlog 37iaxZiXaFexq6IOfljH): now it names each Act, the in-force tier first.
    for written in ("Interpretation Act, s 8.1", "s. 8.1 of the Interpretation Act"):
        text = reader.read(corpus, written).text
        assert "is the title of 2 Acts" in text
        assert "'Interpretation Act, RSC 1985, c I-21, s 8.1'" in text
        assert text.index("RSC 1985, c I-21") < text.index("RSBC 1996, c 238")
    assert "Nothing in the corpus matches" in reader.read(corpus, "Evidence Act s 8").text


def test_read_returns_context_and_labels_the_dissent(corpus):
    result = reader.read(corpus, f"{OAKES} at para 70")
    assert "*para 70" in result.text  # the asked-for paragraph is marked
    assert "para 68" in result.text and "para 72" in result.text  # two either side
    assert "Estey J., DISSENTING" in result.text
    assert f"{OAKES}#72" in result.unit_ids


def test_read_without_paragraphs_gives_the_outline_not_the_text(corpus):
    result = reader.read(corpus, OAKES)
    assert "Outline" in result.text and result.unit_ids == []
    assert "Syllabus: constitutional topic 24" in result.text


def test_read_provision_brings_definitions_and_what_it_is_subject_to(corpus):
    result = reader.read(corpus, "Criminal Code s 265")
    assert "'consent' (s 2, applies to the whole Act)" in result.text
    assert "subject to s 266" in result.text
    assert "RSC 1985, c C-46 s 266" in result.unit_ids


def test_cases_citing_shows_the_citing_paragraph_and_the_courts_treatment(corpus):
    text = graph.cases_citing(corpus, "R v Oakes")
    assert MORAL in text and "at para 1" in text and "pinpointing para 69" in text
    assert "applied (court)" in text


def test_cases_citing_a_section_includes_its_subsections(corpus):
    assert MORAL in graph.cases_citing_provision(corpus, "Criminal Code s 265")


def test_keyword_query_syntax():
    assert search.parse_keyword_query('"pith and substance" -immunity paramountcy') == (
        ["pith and substance"],
        ["immunity"],
        "paramountcy",
    )


def test_keyword_search_finds_phrases_and_groups_by_case(corpus):
    text = search.keyword_search(corpus, '"sufficient importance"', search.Filters(kind="cases"))
    assert "R. v. Oakes" in text and "SYLLABUS READING" in text


def test_tier_b_legislation_is_searched_only_when_a_jurisdiction_asks():
    assert "tier = 'A'" in search.Filters(kind="legislation").where()
    assert "LEGISLATION-BC" in search.Filters(kind="legislation", jurisdiction="BC").where()


def test_search_kinds_filter_to_their_own_rows():
    assert search.Filters(kind="commentary").where() == "kind = 'commentary'"
    everything = search.Filters().where()
    assert "kind = 'case'" in everything and "kind = 'commentary'" in everything


def test_subject_to_a_section_of_another_act_is_looked_up_in_that_act():
    from legal_core.citations import StatuteNames
    from legal_corpus.reader import depends_on

    class Stub:
        statute_names = StatuteNames([("EOLC", "End of Life Choice Act 2019")], {})
        held = {("EOLC", "37"): "Immunity", ("Crimes", "37"): "Warrantless arrest"}

        def provision(self, statute_id, section):
            text = self.held.get((statute_id, section))
            return text and {"text": text, "id": f"{statute_id} s {section}", "title": statute_id}

    def found(text):
        return [(d["statute"], d["text"]) for d in depends_on(Stub(), "Crimes", "48", text)]

    assert found("This section is subject to section 37 of the End of Life Choice Act 2019.") == [
        ("EOLC", "Immunity")
    ]
    assert found("This section is subject to section 37.") == [("Crimes", "Warrantless arrest")]
    # An Act we do not hold: its s 37 is not the Crimes Act's.
    assert found("This section is subject to section 37 of the Unheld Act 1990.") == []
