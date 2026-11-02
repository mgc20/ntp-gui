"""Abgebrochene Browserverbindungen landen nicht als Traceback im Log."""
import io
import os
import sys
import unittest
from contextlib import redirect_stderr

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

import server  # noqa: E402


class QuietHTTPServerTest(unittest.TestCase):
    def _error_output(self, exc: BaseException) -> str:
        srv = server.QuietHTTPServer.__new__(server.QuietHTTPServer)
        buf = io.StringIO()
        with redirect_stderr(buf):
            try:
                raise exc
            except BaseException:
                srv.handle_error(None, ("192.0.2.1", 1234))
        return buf.getvalue()

    def test_connection_aborts_are_silent(self):
        for exc in (ConnectionResetError(104, "reset"), BrokenPipeError(32, "pipe"), TimeoutError()):
            self.assertEqual(self._error_output(exc), "", exc)

    def test_real_errors_still_logged(self):
        self.assertIn("ValueError", self._error_output(ValueError("kaputt")))


if __name__ == "__main__":
    unittest.main()
