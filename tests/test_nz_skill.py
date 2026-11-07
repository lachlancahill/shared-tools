"""The packaged skill must be usable before a consumer imports any reader stack."""

import subprocess
import sys

from legal_corpus import graph, nz_skill


def test_skill_contracts_match_the_reader_without_loading_it_to_read_the_prose():
    relations = next(t for t in nz_skill.TOOLS if t.name == "nz_case_links")
    assert set(relations.parameters["properties"]["relation"]["enum"]) <= set(graph.RELATIONS)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
from legal_corpus import nz_skill
assert 'Read before relying' in nz_skill.prose()
assert '8.4A' in nz_skill.prose()
assert 'nz_canon' not in nz_skill.prose()
assert not {'duckdb', 'pyarrow', 'lancedb'} & sys.modules.keys()
""",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
