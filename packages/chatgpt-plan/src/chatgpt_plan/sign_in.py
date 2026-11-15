"""Sign a ChatGPT account in for plan usage, from the machine with the browser.

Opens the browser at OpenAI's consent page, waits on `127.0.0.1:1455` for the callback, and
writes the tokens to the consumer's connection document, where every instance of every app
sharing the connection reads them. Run it again whenever an app logs the connection as
broken: a refused refresh means the saved session is gone. **Do not run it otherwise**: it
replaces the tokens every app is using.

It has to run where the browser is. The callback address is loopback, so it reaches the
machine running the browser and nothing else, which is why this is not part of an app.

The host id in the document is kept across sign-ins, as the docs require: a second run reuses
it, and only the tokens and the issued client id are replaced.
"""

import logging
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from chatgpt_plan import plan

logger = logging.getLogger(__name__)

CALLBACK_HOST, CALLBACK_PORT = "127.0.0.1", 1455
CALLBACK_PATH = "/auth/callback"


def _wait_for_callback() -> dict[str, str]:
    """Serve loopback until the callback arrives, and return its query parameters."""
    received: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urlparse(self.path)
            if url.path != CALLBACK_PATH:
                self.send_error(404)
                return
            received.update({key: values[0] for key, values in parse_qs(url.query).items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Signed in. You can close this tab and go back to the terminal.")

        def log_message(self, *args):
            pass  # the request line carries the authorization code; keep it out of the log

    with HTTPServer((CALLBACK_HOST, CALLBACK_PORT), Handler) as server:
        while not received:
            server.handle_request()
    return received


def sign_in(connection: plan.Plan, agent_name: str) -> None:
    """Run one browser sign-in and write its tokens to `connection`'s document.

    `agent_name` is what ChatGPT's consent screen and "connected apps" settings call it.
    """
    existing = connection.read()
    host_id = existing["credentials"]["host_id"] if existing else plan.new_host_id()
    auth = plan.authorization(host_id, agent_name)

    logger.info("Opening the browser to sign in. If it does not open, visit:\n%s", auth.url)
    webbrowser.open(auth.url)
    callback = _wait_for_callback()

    if callback.get("state") != auth.state:
        raise RuntimeError("The callback's state is not this sign-in's; refusing it.")
    if "error" in callback:
        raise RuntimeError(
            f"Sign-in did not complete: {callback['error']} {callback.get('error_description', '')}"
        )

    credentials = plan.exchange(host_id, callback["client_id"], callback["code"], auth)
    connection.save(credentials)
    logger.info("Signed in as client %s; credentials written.", credentials.client_id)
