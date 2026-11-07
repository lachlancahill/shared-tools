"""The reader runs without the tutor, its model clients or credentials."""

import subprocess
import sys


def test_reader_imports_without_consumer_packages():
    subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            """
import sys
from legal_corpus import graph, profile, reader, reasons, resolve, search, snapshot, verify
for name in sys.modules:
    assert not name.startswith(('legal_app', 'chat_app', 'openai', 'flask'))
""",
        ],
        check=True,
    )
