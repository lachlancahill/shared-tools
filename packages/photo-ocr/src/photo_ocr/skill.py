"""
The non-default agent tool: instructions and a schema, importing neither Pillow nor httpx.

A consumer offers this as an opt-in tool group, as chat does for `nz-law`, and supplies
the implementation: find the named image, check the account may use it, call
`reader.read_photo`, charge `cost_usd` and return `Reading.for_model()`.
"""

from dataclasses import dataclass
from importlib.resources import files

NAME = "photo-ocr"
SUMMARY = "Read the text in photos of printed pages that the user uploaded."


def prose() -> str:
    """Read the packaged instructions; no credentials or network are needed."""
    return files("photo_ocr").joinpath("skills/photo-ocr.md").read_text(encoding="utf-8")


@dataclass(frozen=True)
class Tool:
    """A consumer-neutral tool contract; the consumer supplies its implementation."""

    name: str
    description: str
    parameters: dict


TOOLS = (
    Tool(
        name="read_photo",
        description=(
            "Read the text in one uploaded photo of a printed page. Returns a machine "
            "reading that may contain plausible but wrong words."
        ),
        parameters={
            "type": "object",
            "properties": {
                "image": {
                    "type": "string",
                    "description": (
                        "The name of an image the user uploaded, exactly as the "
                        "conversation gives it."
                    ),
                }
            },
            "required": ["image"],
        },
    ),
)
