"""Abgebrochene Browserverbindungen landen nicht als Traceback im Log."""
import errno
import io
import os
import socket
import sys
import unittest
from contextlib import redirect_stderr
from unittest import mock

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

    def test_network_oserrors_are_silent(self):
        # 1.5.1: „OSError: [Errno 113] No route to host“ landete als Traceback im Log.
        for code in ("EHOSTUNREACH", "ENETUNREACH", "ENETDOWN", "EHOSTDOWN", "ETIMEDOUT", "ECONNRESET",
                     "EPIPE", "ECONNABORTED"):
            if hasattr(errno, code):
                exc = OSError(getattr(errno, code), code)
                self.assertEqual(self._error_output(exc), "", code)
        self.assertEqual(self._error_output(socket.timeout("timed out")), "")
        self.assertEqual(self._error_output(ConnectionAbortedError(103, "abort")), "")

    def test_real_errors_still_logged(self):
        self.assertIn("ValueError", self._error_output(ValueError("kaputt")))

    def test_other_oserrors_still_logged(self):
        out = self._error_output(OSError(errno.EMFILE, "Too many open files"))
        self.assertIn("Too many open files", out)
        self.assertIn("OSError", self._error_output(OSError("ohne errno")))


class BindTest(unittest.TestCase):
    """B3: WEB_BIND mit IPv6-Adresse und eine Fehlermeldung, die zur Ursache passt.
    Bindet nie wirklich an IPv6 (die Testumgebung hat evtl. keins)."""

    def test_ipv6_uses_af_inet6(self):
        self.assertEqual(server.make_server.__module__, "server")
        for bind, expected in (("::", "::"), ("[::1]", "::1"), (" [::] ", "::")):
            with mock.patch.object(server.QuietHTTPServer6, "__init__", return_value=None) as init:
                srv = server.make_server(bind, 8080)
            self.assertIsInstance(srv, server.QuietHTTPServer6)
            self.assertEqual(srv.address_family, socket.AF_INET6)
            self.assertEqual(init.call_args.args[0], (expected, 8080))

    def test_ipv4_stays_af_inet(self):
        with mock.patch.object(server.QuietHTTPServer, "__init__", return_value=None) as init:
            srv = server.make_server("0.0.0.0", 8080)
        self.assertNotIsInstance(srv, server.QuietHTTPServer6)
        self.assertEqual(srv.address_family, socket.AF_INET)
        self.assertEqual(init.call_args.args[0], ("0.0.0.0", 8080))

    def _message(self, exc, bind="192.0.2.55"):
        with mock.patch.object(server.QuietHTTPServer, "__init__", side_effect=exc), \
                mock.patch.object(server.QuietHTTPServer6, "__init__", side_effect=exc):
            with self.assertRaises(SystemExit) as cm:
                server.make_server(bind, 8080)
        return str(cm.exception.code)

    def test_missing_address_points_to_web_bind(self):
        text = self._message(OSError(errno.EADDRNOTAVAIL, "Cannot assign requested address"))
        self.assertIn("WEB_BIND", text)
        self.assertNotIn("WEB_PORT anpassen", text)
        self.assertIn("Cannot assign requested address", text)
        text = self._message(socket.gaierror(-9, "Address family for hostname not supported"), "::1")
        self.assertIn("WEB_BIND", text)

    def test_permission_denied_points_to_low_port(self):
        for code in (errno.EACCES, errno.EPERM):
            text = self._message(PermissionError(code, "Permission denied"), "0.0.0.0")
            self.assertIn("CAP_NET_BIND_SERVICE", text)
            self.assertIn("WEB_PORT", text)
            self.assertNotIn("WEB_BIND", text)

    def test_ipv6_server_is_dual_stack(self):
        """IPV6_V6ONLY wird vor dem Binden auf 0 gesetzt, unabhängig von net.ipv6.bindv6only."""
        srv = server.QuietHTTPServer6.__new__(server.QuietHTTPServer6)
        srv.socket = mock.Mock()
        srv.server_address = ("::", 0)
        order = []
        srv.socket.setsockopt.side_effect = lambda *a: order.append("setsockopt")
        with mock.patch.object(server.QuietHTTPServer, "server_bind",
                               side_effect=lambda: order.append("bind")) as base_bind:
            srv.server_bind()
        srv.socket.setsockopt.assert_called_once_with(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        base_bind.assert_called_once()
        self.assertEqual(order, ["setsockopt", "bind"])

    def test_ipv6_server_binds_without_v6only_option(self):
        srv = server.QuietHTTPServer6.__new__(server.QuietHTTPServer6)
        srv.socket = mock.Mock()
        srv.socket.setsockopt.side_effect = OSError(errno.ENOPROTOOPT, "Protocol not available")
        with mock.patch.object(server.QuietHTTPServer, "server_bind") as base_bind:
            srv.server_bind()
        base_bind.assert_called_once()

    def test_port_in_use_points_to_web_port(self):
        text = self._message(OSError(errno.EADDRINUSE, "Address already in use"))
        self.assertIn("WEB_PORT", text)
        self.assertNotIn("WEB_BIND", text)


if __name__ == "__main__":
    unittest.main()
