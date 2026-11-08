"""Content-Security-Policy und weitere Sicherheitsköpfe an jeder Antwort (HTML, API, Fehlerseiten).

Dazu: Kein Code im Frontend darf etwas nutzen, das die strenge CSP sperrt (Inline-Skripte,
on…-Attribute, style-Attribute). el() setzt Stile deshalb per CSSOM.
"""

import http.client
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken
from _support import JoiningHTTPServer, stop_http_server  # noqa: E402

import server  # noqa: E402
import settings  # noqa: E402
import store  # noqa: E402

EXPECTED = {
    "default-src": "'self'",
    "img-src": "'self' data:",
    "style-src": "'self'",
    "script-src": "'self'",
    "connect-src": "'self'",
    "object-src": "'none'",
    "frame-ancestors": "'none'",
    "base-uri": "'none'",
    "form-action": "'self'",
}


def parse_csp(value: str) -> dict:
    out = {}
    for part in value.split(";"):
        words = part.split()
        if words:
            out[words[0]] = " ".join(words[1:])
    return out


class SecurityHeaderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        env = {k: v for k, v in os.environ.items() if k not in ("WEB_USER", "WEB_PASSWORD", "WEB_READONLY")}
        cls.patches = [
            mock.patch.object(settings, "DATA_DIR", cls.tmp.name),
            mock.patch.object(settings, "SETTINGS_FILE", os.path.join(cls.tmp.name, "settings.json")),
            mock.patch.object(server, "RUN_DIR", cls.tmp.name),
            mock.patch.dict(os.environ, env, clear=True),
        ]
        for patch in cls.patches:
            patch.start()
        server.AUTH_CACHE.clear()
        cls.httpd = JoiningHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        stop_http_server(cls.httpd)
        for patch in reversed(cls.patches):
            patch.stop()
        store.close_all()
        server.AUTH_CACHE.clear()
        cls.tmp.cleanup()

    def get(self, path, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", path, headers=headers or {})
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp, body

    def assert_headers(self, resp, label):
        csp = resp.getheader("Content-Security-Policy")
        self.assertTrue(csp, f"{label}: keine Content-Security-Policy")
        self.assertEqual(parse_csp(csp), EXPECTED, label)
        self.assertNotIn("unsafe-inline", csp, label)
        self.assertNotIn("unsafe-eval", csp, label)
        self.assertEqual(resp.getheader("X-Content-Type-Options"), "nosniff", label)
        self.assertEqual(resp.getheader("X-Frame-Options"), "DENY", label)
        self.assertEqual(resp.getheader("Referrer-Policy"), "same-origin", label)
        self.assertEqual(len(resp.msg.get_all("Content-Security-Policy")), 1, f"{label}: doppelt")

    def test_html_static_and_api_responses(self):
        for path in ("/", "/clock", "/static/app.css", "/static/js/util.js", "/healthz",
                     "/api/gibt-es-nicht", "/gibt-es-nicht"):
            resp, _ = self.get(path)
            self.assert_headers(resp, f"{path} ({resp.status})")

    def test_host_rejection_page(self):
        resp, body = self.get("/", headers={"Host": "fremd.example", "Accept": "text/html"})
        self.assertEqual(resp.status, 403)
        self.assert_headers(resp, "Ablehnungsseite")
        self.assertNotIn(b"style=", body, "style-Attribut würde von der CSP gesperrt")

    def test_send_error_pages(self):
        # Kaputte Anfragezeile: http.server antwortet selbst über send_error.
        with socket.create_connection(("127.0.0.1", self.port), timeout=10) as sock:
            sock.sendall(b"GET / HTTP/9.9\r\n\r\n")
            raw = b""
            while chunk := sock.recv(4096):
                raw += chunk
        head = raw.split(b"\r\n\r\n", 1)[0].decode("latin-1")
        self.assertRegex(head.splitlines()[0], r" 50[05] | 400 ")
        self.assertIn("Content-Security-Policy: default-src 'self'", head)


class CspCompatibleFrontendTest(unittest.TestCase):
    """Nichts im Frontend darf von der strengen CSP gesperrt werden."""

    def test_html_has_no_inline_code_or_styles(self):
        for name in ("index.html", "clock.html"):
            text = (ROOT / "app" / "static" / name).read_text(encoding="utf-8")
            self.assertNotRegex(text, r"<script(?![^>]*\bsrc=)", f"{name}: Inline-Skript")
            self.assertNotRegex(text, r"\son[a-z]+\s*=", f"{name}: Inline-Handler")
            self.assertNotRegex(text, r"\sstyle\s*=", f"{name}: style-Attribut")
            self.assertNotIn("<style", text, f"{name}: Inline-Stylesheet")
            for match in re.finditer(r"""(?:src|href)=["']([^"']+)""", text):
                url = match.group(1)
                self.assertFalse(url.startswith(("http:", "https:", "//")), f"{name}: externe Quelle {url}")

    def test_js_sets_no_style_attribute(self):
        for path in (ROOT / "app" / "static" / "js").rglob("*.js"):
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"setAttribute\(\s*[\"']style", path.name)
            self.assertNotRegex(text, r"innerHTML|insertAdjacentHTML|new Function|\beval\(", path.name)

    @unittest.skipUnless(shutil.which("node"), "node fehlt")
    def test_el_style_uses_cssom(self):
        module = (ROOT / "app" / "static" / "js" / "util.js").as_uri()
        script = f"""
const attrs = [];
class FakeNode {{
  constructor() {{ this.style = {{ cssText: "" }}; this.dataset = {{}}; }}
  setAttribute(k, v) {{ attrs.push(k); }}
  addEventListener() {{}}
  append() {{}}
}}
globalThis.Node = FakeNode;
globalThis.document = {{ createElement: () => new FakeNode(), createElementNS: () => new FakeNode(),
                         createTextNode: () => ({{}}) }};
const {{ el }} = await import({json.dumps(module)});
const node = el("span", {{ class: "fill", style: "width:5%" }});
console.log(JSON.stringify({{ attrs, css: node.style.cssText }}));
"""
        out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True,
                             timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        result = json.loads(out.stdout)
        self.assertEqual(result, {"attrs": ["class"], "css": "width:5%"})


if __name__ == "__main__":
    unittest.main()
