"""Kleine Hilfen für mehrere Testmodule."""

import socket
import unittest


def closed_tcp_port(testcase: unittest.TestCase) -> int:
    """Ein TCP-Port auf 127.0.0.1, der sicher ablehnt: gebunden, aber ohne listen().

    Feste „sicher geschlossene“ Ports (1, 9, 2947) hängen vom Host ab – auf einem Pi mit
    gpsd antwortet 2947 echt. Der hier gebundene Port bleibt bis zum Testende reserviert,
    und ein connect() bekommt sofort RST (ECONNREFUSED)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    testcase.addCleanup(s.close)
    s.bind(("127.0.0.1", 0))
    return s.getsockname()[1]


def fake_hostnames(testcase: unittest.TestCase, hostname: str = "testhost",
                   fqdn: str = "testhost.example") -> None:
    """Eigene Rechnernamen festlegen, ohne den Resolver des Runners zu fragen (getfqdn() fragt das
    DNS rückwärts und kann Sekunden dauern). Setzt den Namens-Cache vorher und nachher zurück."""
    from unittest import mock

    import diagnostics
    for name, value in (("gethostname", hostname), ("getfqdn", fqdn)):
        patcher = mock.patch.object(socket, name, return_value=value)
        patcher.start()
        testcase.addCleanup(patcher.stop)
    diagnostics._reset_own_names()
    testcase.addCleanup(diagnostics._reset_own_names)
