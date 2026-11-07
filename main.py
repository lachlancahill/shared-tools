"""Import smoke check for the libraries; never loads a private corpus."""

import logging

from legal_core import citations
from legal_corpus import graph, reader, search, verify
from photo_ocr import reader as photo_reader
from photo_ocr import skill as photo_skill

logger = logging.getLogger(__name__)


def main() -> None:
    """Confirm the parser, readers and checker import without a consumer app or a paid call."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    modules = (citations, graph, reader, search, verify, photo_reader, photo_skill)
    logger.info("Imported %s", ", ".join(m.__name__ for m in modules))


if __name__ == "__main__":
    main()
