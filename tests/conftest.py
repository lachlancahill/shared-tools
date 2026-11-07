"""Small local snapshots: no cloud credentials, model calls or ingest dependency."""

import json
from dataclasses import replace
from datetime import date

import lancedb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from lancedb.index import FTS
from legal_corpus.profile import CANADA, NEW_ZEALAND
from legal_corpus.snapshot import Corpus

OAKES = "[1986] 1 SCR 103"
MORAL = "2020 SCC 99"  # fictional
NZ_CASE = "[2026] NZCA 99999"  # fictional; no real NZ judgment is published here
CODE = "RSC 1985, c C-46"

SEGMENT = pa.struct(
    [
        ("kind", pa.string()),
        ("authors", pa.string()),
        ("first_unit", pa.int64()),
        ("last_unit", pa.int64()),
    ]
)
SCHEMAS = {
    "cases": pa.schema(
        [
            ("case_id", pa.string()),
            ("dataset", pa.string()),
            ("tier", pa.string()),
            ("name", pa.string()),
            ("decision_date", pa.date32()),
            ("citations", pa.list_(pa.string())),
            ("url", pa.string()),
            ("unit", pa.string()),
            ("unit_count", pa.int64()),
            ("judges", pa.list_(pa.string())),
            ("subjects", pa.list_(pa.string())),
            ("appeal_from", pa.list_(pa.string())),
            ("segments", pa.list_(SEGMENT)),
            ("read_by_ocr", pa.bool_()),
        ]
    ),
    "cites": pa.schema(
        [
            ("citing_case", pa.string()),
            ("citing_unit", pa.int64()),
            ("key", pa.string()),
            ("cited_case", pa.string()),
            ("pin_para", pa.int64()),
            ("pin_para_end", pa.int64()),
            ("pin_page", pa.int64()),
        ]
    ),
    "citation_keys": pa.schema([("key", pa.string()), ("case_id", pa.string())]),
    "treatments": pa.schema(
        [
            ("citing_case", pa.string()),
            ("cited_case", pa.string()),
            ("treatment", pa.string()),
            ("judge", pa.string()),
        ]
    ),
    "llm_treatments": pa.schema(
        [
            ("citing_case", pa.string()),
            ("cited_case", pa.string()),
            ("treatment", pa.string()),
            ("paragraph", pa.int64()),
        ]
    ),
    "interprets": pa.schema(
        [
            ("citing_case", pa.string()),
            ("citing_unit", pa.int64()),
            ("statute", pa.string()),
            ("section", pa.string()),
        ]
    ),
    "statutes": pa.schema(
        [
            ("statute_id", pa.string()),
            ("title", pa.string()),
            ("dataset", pa.string()),
            ("tier", pa.string()),
            ("url", pa.string()),
            ("section_count", pa.int64()),
        ]
    ),
    "definitions": pa.schema(
        [
            ("statute_id", pa.string()),
            ("section", pa.string()),
            ("scope", pa.string()),
            ("term", pa.string()),
            ("text", pa.string()),
        ]
    ),
    "briefs": pa.schema(
        [
            ("case_id", pa.string()),
            ("brief", pa.string()),
            ("reviewed", pa.bool_()),
            ("prompt_version", pa.string()),
        ]
    ),
    "roles": pa.schema(
        [
            ("case_id", pa.string()),
            ("first", pa.int64()),
            ("last", pa.int64()),
            ("role", pa.string()),
        ]
    ),
    "tests": pa.schema(
        [
            ("case_id", pa.string()),
            ("slug", pa.string()),
            ("name", pa.string()),
            ("relation", pa.string()),
            ("statement", pa.string()),
            ("steps", pa.string()),
        ]
    ),
}


def case(case_id, name, court, count, segments=()):
    return dict(
        case_id=case_id,
        name=name,
        dataset=court,
        tier="A",
        decision_date=date(2026, 1, 1),
        citations=[case_id],
        url="",
        unit="paragraph",
        unit_count=count,
        judges=["Dickson, Brian"],
        subjects=[],
        appeal_from=[],
        segments=list(segments),
        read_by_ocr=None,
    )


def unit(doc, number, text, *, section=None, title="R. v. Oakes", court="SCC", **extra):
    return dict(
        id=f"{doc} s {section}" if section else f"{doc}#{number}",
        kind="provision" if section else "case",
        doc_id=doc,
        number=number,
        section=section,
        unit="section" if section else "paragraph",
        heading="Assaults" if section else "Majority",
        note=None,
        page=None,
        segment_kind=None if section else "majority",
        segment_authors=None if section else "The Chief Justice",
        court=court,
        year=1986,
        tier="A",
        title=title,
        syllabus=doc == OAKES or section == "265",
        text=text,
        body=f"{title}: {text}",
        **extra,
    )


def publish(root, graph, units, syllabus=()):
    """Write precisely the reader's on-disk contract, with an exact small-vector index."""
    snap = root / "snapshots" / "test"
    snap.mkdir(parents=True)
    for name, schema in SCHEMAS.items():
        pq.write_table(pa.Table.from_pylist(graph.get(name, []), schema), snap / f"{name}.parquet")
    (snap / "manifest.json").write_text("{}")
    (snap / "syllabus.json").write_text(json.dumps(list(syllabus)))
    table = pa.Table.from_pylist(units)
    vectors = np.random.default_rng(0).standard_normal((len(units), 8)).astype(np.float32)
    table = table.append_column(
        "vector", pa.FixedSizeListArray.from_arrays(pa.array(vectors.ravel()), 8)
    )
    search = lancedb.connect(str(snap / "search")).create_table("units", table)
    search.create_index("body", config=FTS(with_position=True))
    (root / "current.json").write_text(json.dumps({"snapshot": "snapshots/test"}))
    return root


@pytest.fixture(scope="session")
def corpus(tmp_path_factory):
    oakes = case(
        OAKES,
        "R. v. Oakes",
        "SCC",
        72,
        [
            dict(kind="majority", authors="The Chief Justice", first_unit=1, last_unit=71),
            dict(kind="dissenting", authors="Estey J.", first_unit=72, last_unit=72),
        ],
    )
    graph = {
        "cases": [oakes, case(MORAL, "R. v. Moral", "SCC", 1)],
        "citation_keys": [
            dict(key=k, case_id=v)
            for k, v in (
                (OAKES, OAKES),
                ("26 DLR (4th) 200", OAKES),
                (MORAL, MORAL),
            )
        ],
        "cites": [dict(citing_case=MORAL, citing_unit=1, key=OAKES, cited_case=OAKES, pin_para=69)],
        "treatments": [dict(citing_case=MORAL, cited_case=OAKES, treatment="applied")],
        "interprets": [dict(citing_case=MORAL, citing_unit=1, statute=CODE, section="265(1)")],
        "statutes": [
            dict(statute_id=i, title=t, dataset=d, tier=tier, url="", section_count=n)
            for i, t, d, tier, n in (
                (CODE, "Criminal Code", "LEGISLATION-FED", "A", 2),
                ("SC 1960, c 44", "Canadian Bill of Rights", "LEGISLATION-FED", "A", 2),
                ("RSBC 1996, c 238", "Interpretation Act", "LEGISLATION-BC", "B", 0),
                ("RSC 1985, c I-21", "Interpretation Act", "LEGISLATION-FED", "A", 0),
            )
        ],
        "definitions": [
            dict(
                statute_id=CODE,
                section="2",
                scope="Act",
                term="consent",
                text="**consent** means agreement freely given.",
            )
        ],
        "roles": [dict(case_id=OAKES, first=72, last=72, role="analysis")],
    }
    units = [
        unit(OAKES, n, t)
        for n, t in (
            (68, "To establish that a limit is reasonable..."),
            (
                69,
                "First, the objective, which the measures responsible for a limit on a Charter "
                "right or freedom are designed to serve, must be of sufficient importance "
                "to warrant overriding a constitutionally protected right or freedom.",
            ),
            (
                70,
                "Second, once a sufficiently significant objective is recognized, then the party "
                "invoking s. 1 must show that the means chosen are reasonable and "
                "demonstrably justified.",
            ),
            (71, "Proportionality."),
            (72, "I would decide this appeal differently."),
        )
    ]
    units[-1].update(segment_kind="dissenting", segment_authors="Estey J.", heading="Dissent")
    units += [
        unit(
            MORAL,
            1,
            "Applying R. v. Oakes, [1986] 1 S.C.R. 103, at para. 69, the objective is pressing.",
            title="R. v. Moral",
        )
    ]
    for doc, n, section, title, text in (
        (
            CODE,
            0,
            "265",
            "Criminal Code",
            "(1) A person commits an assault when (a) without the "
            "consent of another person, he applies force intentionally, subject to section 266.",
        ),
        (CODE, 1, "266", "Criminal Code", "Every one who commits an assault is guilty."),
        ("SC 1960, c 44", 0, "1", "Canadian Bill of Rights", "Property and due process of law."),
        ("SC 1960, c 44", 1, "2", "Canadian Bill of Rights", "The right to a fair hearing."),
        ("Constitution Act, 1982", 0, "7", "Constitution Act, 1982", "Life, liberty and security."),
    ):
        units.append(unit(doc, n, text, section=section, title=title, court="LEGISLATION-FED"))
    syllabus = [
        dict(
            subject="constitutional",
            title="Constitutional Law",
            topics=[
                dict(
                    id="24",
                    title="Limitation of Rights",
                    readings=[
                        dict(kind="case", case_id=OAKES, name="R v Oakes"),
                        dict(kind="provision", statute=CODE, section="265(1)"),
                    ],
                )
            ],
        )
    ]
    root = publish(tmp_path_factory.mktemp("corpus"), graph, units, syllabus)
    return Corpus(replace(CANADA, corpus_uri=str(root)))


@pytest.fixture(scope="session")
def nz_corpus(tmp_path_factory):
    from legal_core.nz import HIGH_COURT_RULES

    graph = {
        "cases": [case(NZ_CASE, "Example v Sample", "NZCA", 3)],
        "citation_keys": [dict(key=NZ_CASE, case_id=NZ_CASE)],
        "statutes": [
            dict(
                statute_id=HIGH_COURT_RULES,
                title=HIGH_COURT_RULES,
                dataset="NZ-LEGISLATION",
                tier="A",
                url="",
                section_count=2,
            )
        ],
    }
    units = [
        unit(NZ_CASE, n, text, title="Example v Sample", court="NZCA")
        for n, text in (
            (1, "This is invented judgment text about discovery."),
            (2, "The example order is refused."),
            (3, "The example appeal is dismissed."),
        )
    ]
    units += [
        unit(
            HIGH_COURT_RULES,
            n,
            text,
            section=section,
            title=HIGH_COURT_RULES,
            court="NZ-LEGISLATION",
        )
        for n, section, text in (
            (0, "8.4", "Invented current discovery text for a reader test."),
            (1, "8.7", "Rule 8.7: revoked, on 1 January 2026, by rule 39."),
        )
    ]
    root = publish(tmp_path_factory.mktemp("nz-corpus"), graph, units)
    return Corpus(replace(NEW_ZEALAND, corpus_uri=str(root)))
