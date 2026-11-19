"""The removed stocks / India / F&O pages must land on the SPA's markets sections.

Old bookmarks hit `do_GET`; each must answer 302 to the matching `/#markets/*`
hash instead of serving a page (or a 404).
"""

import io

import pytest

from jarvis.api import server as server_module


class _Handler(server_module.JarvisRequestHandler):
    """Transport stubbed; the real `do_GET` routing runs."""

    def __init__(self, path):
        self.path = path
        self.headers = {}
        self.wfile = io.BytesIO()
        self.client_address = ("127.0.0.1", 12345)
        self.status_codes = []
        self.sent_headers = {}

    def send_response(self, code, message=None):
        self.status_codes.append(code)

    def send_header(self, keyword, value):
        self.sent_headers[keyword] = value

    def end_headers(self):
        pass

    def send_error(self, code, message=None, explain=None):
        self.status_codes.append(code)

    def log_message(self, *args, **kwargs):
        pass


@pytest.mark.parametrize("path,target", [
    ("/stocks", "/#markets/us"),
    ("/screener", "/#markets/us"),
    ("/india", "/#markets/india"),
    ("/nse", "/#markets/india"),
    ("/options", "/#markets/fno"),
    ("/fno", "/#markets/fno"),
])
def test_old_market_pages_redirect_to_spa(monkeypatch, path, target):
    monkeypatch.setattr(server_module.JarvisRequestHandler, "start_background_syncer", staticmethod(lambda: None))
    handler = _Handler(path)
    handler.do_GET()
    assert handler.status_codes == [302]
    assert handler.sent_headers["Location"] == target
