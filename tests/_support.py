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


class JoiningHTTPServer:
    """Fabrik für einen ThreadingHTTPServer, dessen Anfrage-Threads beim Stoppen abgewartet werden.

    ThreadingHTTPServer startet je Anfrage einen Daemon-Thread und wartet beim Schließen nicht
    darauf. In tearDownClass lief ein solcher Thread (Status bauen, Datenbank, Einstellungen)
    darum manchmal noch, während store.close_all() und das Löschen des Testordners schon liefen –
    in zufälliger Reihenfolge und unter Last ein Rennen mit dem nächsten Test. stop_http_server()
    wartet die Threads mit großzügiger Frist ab, statt sie weiterlaufen zu lassen.
    """

    def __new__(cls, address, handler):
        import threading
        from http.server import ThreadingHTTPServer

        class _Server(ThreadingHTTPServer):
            daemon_threads = True

            def server_activate(self):
                # Wie QuietHTTPServer: nicht blockierend lauschen, sonst kann shutdown() hängen, wenn ein
                # Client seine Verbindung zwischen select() und accept() abbricht.
                super().server_activate()
                self.socket.setblocking(False)

            def process_request(self, request, client_address):
                thread = threading.Thread(target=self.process_request_thread,
                                          args=(request, client_address), daemon=True)
                with self._request_lock:
                    self._request_threads = [t for t in self._request_threads if t.is_alive()]
                    self._request_threads.append(thread)
                thread.start()

        server = _Server(address, handler)
        server._request_lock = threading.Lock()
        server._request_threads = []
        return server


def stop_http_server(httpd, timeout: float = 30.0) -> None:
    """shutdown(), laufende Anfrage-Threads abwarten (Frist), dann server_close()."""
    import time

    httpd.shutdown()
    deadline = time.monotonic() + timeout
    lock = getattr(httpd, "_request_lock", None)
    threads = []
    if lock is not None:
        with lock:
            threads = list(httpd._request_threads)
    for thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))
    httpd.server_close()
