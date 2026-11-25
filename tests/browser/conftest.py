"""
chat-ui's modules in a real browser, on a page with nothing else on it.

Opt-in, because it needs Playwright and a browser:

    uv run --group browser playwright install chromium webkit firefox
    uv run --group browser pytest tests/browser
    BROWSER=webkit uv run --group browser pytest tests/browser
"""

import mimetypes
import os

import pytest

pytest.importorskip("playwright.sync_api", reason="uv run --group browser")

import chat_ui  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

ORIGIN = "http://chat.test"
# The same policy a strict consumer sends, so a module that needs more fails here.
POLICY = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:"
PAGE = """<!doctype html><meta charset="utf-8">
<link rel="stylesheet" href="/chat-ui/chat-ui.css"><link rel="stylesheet" href="/page.css">
<div class="chat-ui" id="page"><div class="messages" id="scroller"><div class="turns" id="turns">
</div></div><div class="dock"><button class="jump" id="jump" hidden></button></div></div>
<script type="module" src="/page.js"></script>"""
STYLE = """html, body { margin: 0; height: 100% } #page { display: flex; flex-direction: column;
height: 600px; color-scheme: light } .dock { position: relative; height: 60px }"""
# What an app's own module does.
SCRIPT = """
import { createMessages } from '/chat-ui/messages.js';
import { createTranscript } from '/chat-ui/transcript.js';
import { events } from '/chat-ui/events.js';
const say = (one, many) => (n) => (n === 1 ? one : many.replace('#', n));
window.events = events;
window.ui = createMessages({
  tools: {
    search: { icon: 'search', now: 'Searching', done: 'Searched', say: say('searched', 'searched # times') },
    read: { icon: 'book-open', now: 'Reading', done: 'Read', say: say('read 1 source', 'read # sources') },
    nz_read: { icon: 'book-open', now: 'Reading', done: 'Read', say: say('read 1 source', 'read # sources'), as: 'read' },
  },
  detail: (args) => args.query || '',
  breaks: false,
  makeMark: (mark) => {
    const around = document.createElement(mark.link ? 'a' : 'span');
    around.className = 'cite';
    if (mark.link) around.href = mark.link;
    const after = document.createElement('sup');
    after.className = 'tick';
    after.textContent = mark.sign;
    return { around, after };
  },
});
const el = (id) => document.getElementById(id);
window.transcript = createTranscript({ scroller: el('scroller'), turns: el('turns'), jump: el('jump') });
"""


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as playwright:
        launched = getattr(playwright, os.environ.get("BROWSER", "chromium")).launch()
        yield launched
        launched.close()


@pytest.fixture
def page(browser):
    page = browser.new_page(viewport={"width": 1000, "height": 700})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def serve(route):
        path = route.request.url.removeprefix(ORIGIN)
        own = {"/": PAGE, "/page.css": STYLE, "/page.js": SCRIPT}
        kind = mimetypes.guess_type(path)[0] or "text/html"
        headers = {"Content-Type": kind, "Content-Security-Policy": POLICY}
        if path in own:
            route.fulfill(body=own[path], headers=headers)
        elif not path.startswith("/chat-ui/"):
            route.fulfill(status=404, body="")
        else:
            file = chat_ui.STATIC_DIR / path.removeprefix("/chat-ui/")
            route.fulfill(body=file.read_bytes(), headers=headers)

    page.route(f"{ORIGIN}/**", serve)
    page.goto(f"{ORIGIN}/")
    page.wait_for_function("() => window.transcript")
    yield page
    page.close()
    assert not errors, errors
