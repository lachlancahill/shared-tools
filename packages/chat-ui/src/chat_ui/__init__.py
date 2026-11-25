"""
The transcript of a chat page, as static ES modules and one stylesheet (research/0006).

The consumer serves STATIC_DIR at `/chat-ui/` and imports `/chat-ui/messages.js` and
the rest from its own modules. Nothing here knows a route, a tool, an event name or a
framework. Serve it with `Cache-Control: no-cache`, so a deploy never mixes versions.
"""

from pathlib import Path

STATIC_DIR = Path(__file__).parent / "static"
