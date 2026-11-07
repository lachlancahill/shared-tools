"""Import smoke check for the libraries; never loads a private corpus."""

import logging

from legal_core import citations
from legal_corpus import graph, reader, search, verify

logger = logging.getLogger(__name__)


def main() -> None:
    """Confirm the parser, reader and checker import without a consumer app."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    modules = (citations, graph, reader, search, verify)
    logger.info("Imported %s", ", ".join(m.__name__ for m in modules))


if __name__ == "__main__":
    main()
