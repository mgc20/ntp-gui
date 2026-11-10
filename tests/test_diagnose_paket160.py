"""Funde aus der Auswertung eines Diagnosepakets von 1.6.0 (Raspberry Pi, Docker).

Alle Daten hier sind synthetisch: Adressen aus RFC 5737 (192.0.2.0/24, 198.51.100.0/24), Namen aus
example.org bzw. Test-CA „dns.test“, Kennungen frei erfunden.

  * DoH: Server spricht nur HTTP/2 – statt roher Rahmen-Bytes eine klare Meldung; ALPN „http/1.1“.
  * Fehlertexte aus dem Netz: nur druckbar und begrenzt (Ereignisse, Hinweise, Status).
  * Hinweis „Eigene DNS-Server nicht erreichbar“ nennt den letzten Fehler je Server.
  * Automatische GPS-Schranke/Kalibrierung: nur chronyd neu laden (reload-chronyd.request).
  * dnsfwd meldet einen bekannten Ausfall nach einem Neustart nicht erneut.
  * NTS-Hinweis: Beispiel passend zum DNS-Modus, gekürzte Liste mit „(und N weitere)“.
  * GPS-Rolle: „+“ (mitgerechnet) ist nicht „Netzquellen schlechter“.
  * Datenschutzfilter: chronyc-CSV behält Spalten und Werte, Refclock-Delays bleiben genau,
    power_profile.version, data.subject, Kanal-Kennungen, Laufzeiten, DOP, öffentliche Resolver,
    gps_show_position, Fundart bei entfernten Zeilen.
  * GPS-Schranke: Einschwingen nach einem Start von chronyd nicht mitmessen; Vergrößern nach kurzer
    Messung nur bei deutlichem Anstieg.
"""

import http.client
import json
import os
import shutil
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken

import diagnostics  # noqa: E402
import dnsfwd  # noqa: E402
import egress  # noqa: E402
import events  # noqa: E402
import gpsquality  # noqa: E402
import holdover  # noqa: E402
import insights  # noqa: E402
import textsafe  # noqa: E402
from test_dnsfwd import _make_ca, make_answer  # noqa: E402
from test_nts_proxy import _entrypoint_functions  # noqa: E402

H = 3600.0
# Ein HTTP/2-SETTINGS-Rahmen, wie ihn ein Server sofort nach dem Handshake schickt (MAX_CONCURRENT_STREAMS).
H2_SETTINGS = b"\x00\x00\x06\x04\x00\x00\x00\x00\x00\x00\x03\x00\x00\x00\x64"
# GOAWAY (Typ 7): letzter Stream 0, Fehler PROTOCOL_ERROR – Antwort auf einen falschen Vorspann.
H2_GOAWAY = b"\x00\x00\x08\x07\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01"


def _answer_http11(tls):
    """Ein DoH-Server mit HTTP/1.1: eine Anfrage, eine Antwort."""
    data = b""
    while b"\r\n\r\n" not in data:
        data += tls.recv(65535)
    head, body = data.split(b"\r\n\r\n", 1)
    length = int(next(line.split(b":")[1] for line in head.split(b"\r\n")
                      if line.lower().startswith(b"content-length")))
    while len(body) < length:
        body += tls.recv(65535)
    reply = make_answer(body)
    tls.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/dns-message\r\n"
                + f"Content-Length: {len(reply)}\r\nConnection: close\r\n\r\n".encode() + reply)


# =========================================================================================
# DoH / Fehlertexte
# =========================================================================================
class TlsServerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        ctxs = _make_ca(cls.tmp)
        if not ctxs:
            shutil.rmtree(cls.tmp, ignore_errors=True)
            raise unittest.SkipTest("openssl fehlt – TLS-Tests übersprungen")
        cls.client_ctx = ctxs[0]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def server_ctx(self, alpn=None):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(self.tmp / "srv.pem"), str(self.tmp / "srv.key"))
        if alpn:
            ctx.set_alpn_protocols(alpn)
        return ctx

    def serve(self, ctx, handler):
        """TLS-Server auf 127.0.0.1; handler(tls) beantwortet eine Verbindung. Gibt (Port, gesehene ALPN) zurück."""
        lsock = socket.socket()
        lsock.bind(("127.0.0.1", 0))
        lsock.listen(4)
        self.addCleanup(lsock.close)
        seen = []

        def one(conn):
            tls = None
            try:
                tls = ctx.wrap_socket(conn, server_side=True)
                seen.append(tls.selected_alpn_protocol())
                handler(tls)
            except (OSError, ssl.SSLError):
                pass
            finally:
                (tls or conn).close()

        def loop():
            while True:
                try:
                    conn, _ = lsock.accept()
                except OSError:
                    return
                threading.Thread(target=one, args=(conn,), daemon=True).start()
        threading.Thread(target=loop, daemon=True).start()
        return lsock.getsockname()[1], seen

    def boot(self):
        boot = mock.Mock()
        boot.resolve.return_value = ["127.0.0.1"]
        return boot


class DohHttp2Test(TlsServerCase):
    def test_doh_offers_http11_via_alpn(self):
        def answer(tls):
            data = b""
            while b"\r\n\r\n" not in data:
                data += tls.recv(65535)
            head, body = data.split(b"\r\n\r\n", 1)
            length = int(next(line.split(b":")[1] for line in head.split(b"\r\n")
                              if line.lower().startswith(b"content-length")))
            while len(body) < length:
                body += tls.recv(65535)
            reply = make_answer(body)
            tls.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/dns-message\r\n"
                        + f"Content-Length: {len(reply)}\r\nConnection: close\r\n\r\n".encode() + reply)
        port, seen = self.serve(self.server_ctx(["h2", "http/1.1"]), answer)
        up = dnsfwd.DohUpstream(f"https://dns.test:{port}/dns-query", ["127.0.0.1"], self.boot(), self.client_ctx)
        up.exchange(dnsfwd.build_query("a.example", 1), time.monotonic() + 3)
        self.assertEqual(seen, ["http/1.1"])   # ohne ALPN wählte ein h2-Server von sich aus HTTP/2
        self.assertEqual(dnsfwd.tls_context(dnsfwd.DOH_ALPN).__class__, ssl.SSLContext)

    def test_http2_only_server_gives_clear_message(self):
        def h2(tls):
            tls.sendall(H2_SETTINGS)        # Vorspann eines reinen HTTP/2-Servers
            try:
                tls.recv(24)                # „POST … HTTP/1.1“ statt „PRI * HTTP/2.0“ …
            except (OSError, ssl.SSLError):
                pass
            tls.sendall(H2_GOAWAY)          # … also GOAWAY und sofort zu, Anfragekörper ungelesen
        port, _seen = self.serve(self.server_ctx(), h2)
        up = dnsfwd.DohUpstream(f"https://dns.test:{port}/dns-query", ["127.0.0.1"], self.boot(), self.client_ctx)
        with self.assertRaises(dnsfwd.Http2OnlyError) as ctx:
            up.exchange(dnsfwd.build_query("a.example", 1), time.monotonic() + 3)
        self.assertIn("HTTP/2", str(ctx.exception))
        self.assertTrue(dnsfwd.hard_failure(ctx.exception))
        # Über den Weiterleiter: Fehlertext im Status ist lesbar, kein \x00 mehr.
        fwd = dnsfwd.Forwarder("doh", [up], use_fallback=False)
        fwd.resolve(dnsfwd.build_query("b.example", 1))
        self.assertIn("spricht nur HTTP/2", up.last_error)
        self.assertTrue(up.last_error.isprintable())
        self.assertGreater(up.down_until, 0)   # harter Fehler: gleich als ausgefallen

    def test_http2_only_server_closing_hard_and_h2_alpn_noack(self):
        """Sofortiges Schließen mit RST (SO_LINGER 0) und ein Server, der „h2“ will, aber ohne gemeinsames
        Protokoll weitermacht (wie Go/OpenSSL): trotzdem die HTTP/2-Meldung, kein „Broken pipe“."""
        def h2_rst(tls):
            tls.sendall(H2_SETTINGS)
            try:
                tls.recv(24)
            except (OSError, ssl.SSLError):
                pass
            tls.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        for ctx in (self.server_ctx(), self.server_ctx(["h2"])):
            port, _seen = self.serve(ctx, h2_rst)
            up = dnsfwd.DohUpstream(f"https://dns.test:{port}/dns-query", ["127.0.0.1"], self.boot(),
                                    self.client_ctx)
            for _ in range(3):
                with self.assertRaises(dnsfwd.Http2OnlyError):
                    up.exchange(dnsfwd.build_query("a.example", 1), time.monotonic() + 3)

    def test_http11_server_probe_only_until_first_answer(self):
        probes = []
        real = dnsfwd._PinnedHTTPS.__init__

        def spy(conn, *args, probe=0.0, **kw):
            probes.append(probe)
            real(conn, *args, probe=probe, **kw)
        port, _seen = self.serve(self.server_ctx(), _answer_http11)
        up = dnsfwd.DohUpstream(f"https://dns.test:{port}/dns-query", ["127.0.0.1"], self.boot(), self.client_ctx)
        with mock.patch.object(dnsfwd._PinnedHTTPS, "__init__", spy):
            for _ in range(2):
                up.exchange(dnsfwd.build_query("a.example", 1), time.monotonic() + 3)
        self.assertEqual(probes, [dnsfwd.H2_PROBE, 0.0])   # danach kein Warten mehr je Anfrage

    def test_unsolicited_non_http2_data_is_rejected(self):
        def chatty(tls):
            tls.sendall(b"220 hello\r\n")
            time.sleep(0.3)
        port, _seen = self.serve(self.server_ctx(), chatty)
        up = dnsfwd.DohUpstream(f"https://dns.test:{port}/dns-query", ["127.0.0.1"], self.boot(), self.client_ctx)
        with self.assertRaises(dnsfwd.UpstreamError) as ctx:
            up.exchange(dnsfwd.build_query("a.example", 1), time.monotonic() + 3)
        self.assertIn("unaufgefordert", str(ctx.exception))

    def test_closed_connection_text(self):
        self.assertEqual(dnsfwd.describe_error(BrokenPipeError(32, "Broken pipe"), "doh", 443),
                         "Verbindung vom Server geschlossen")
        self.assertEqual(dnsfwd.describe_error(ConnectionAbortedError(), "dot", 853),
                         "Verbindung vom Server geschlossen")

    def test_alpn_rejection_and_preface_detection(self):
        refused = ssl.SSLError(1, "[SSL: TLSV1_ALERT_NO_APPLICATION_PROTOCOL] tlsv1 alert no application protocol")
        refused.reason = "TLSV1_ALERT_NO_APPLICATION_PROTOCOL"
        self.assertEqual(dnsfwd.describe_error(refused, "doh", 443), dnsfwd.HTTP2_ONLY)
        bad = http.client.BadStatusLine(H2_SETTINGS.decode("latin-1"))
        self.assertEqual(dnsfwd.describe_error(bad, "doh", 443), dnsfwd.HTTP2_ONLY)
        self.assertTrue(dnsfwd.looks_like_http2("PRI * HTTP/2.0\r\n"))
        self.assertFalse(dnsfwd.looks_like_http2("HTTP/1.0 200 OK"))


class UpstreamErrorTextTest(unittest.TestCase):
    def test_dot_refused_names_port_and_cause(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()                               # Port frei: Verbindung wird verweigert
        boot = mock.Mock()
        up = dnsfwd.DotUpstream("dns.example.org", "dns.example.org", port, ["127.0.0.1"], boot, None)
        fwd = dnsfwd.Forwarder("dot", [up], use_fallback=False)
        fwd.resolve(dnsfwd.build_query("a.example", 1))
        self.assertIn(f"verweigert die Verbindung auf Port {port}", up.last_error)
        self.assertIn("DNS-over-TLS dort nicht eingeschaltet", up.last_error)
        self.assertGreater(up.down_until, 0)       # verweigert = harter Fehler, nicht erst nach drei Versuchen

    def test_binary_error_text_is_cleaned(self):
        class Broken(dnsfwd.Upstream):
            def exchange(self, query, deadline):
                raise OSError("\x00\x00\x06\x04\x00\x00\x00\x00\x00\x1b[31m" + "x" * 500)
        up = Broken("192.0.2.53")
        fwd = dnsfwd.Forwarder("servers", [up], use_fallback=False)
        fwd.resolve(dnsfwd.build_query("a.example", 1))
        self.assertTrue(up.last_error.isprintable())
        self.assertLessEqual(len(up.last_error), dnsfwd.ERROR_LIMIT)
        self.assertNotIn("\x1b", up.last_error)

    def test_textsafe(self):
        self.assertEqual(textsafe.clean(H2_SETTINGS.decode("latin-1")), textsafe.BINARY_TEXT)
        self.assertEqual(textsafe.clean("a‮b\x07c  d\n e"), "a�b�c d e")
        self.assertEqual(len(textsafe.clean("y" * 50, 10)), 10)
        self.assertEqual(textsafe.clean_tree({"k": ["z\x00", 3]}), {"k": ["z�", 3]})

    def test_events_store_only_printable_text(self):
        row = events._clean("dns", "warn", "Titel\x00\x1b[2J mit Steuerzeichen", {"error": "\x00\x00\x06\x04ab\x07"},
                            "supervisor")
        self.assertTrue(row[3].isprintable())
        self.assertNotIn("\\u0000", row[4])
        self.assertNotIn("\\u001b", row[3] + row[4])

    def test_fallback_hint_names_last_error_per_server(self):
        ups = [{"label": "dns.example.org", "last_error": "verweigert die Verbindung auf Port 853 – DNS-over-TLS "
                                                         "dort nicht eingeschaltet oder Firewall?"},
               {"label": "https://doh.example.org/dns-query", "last_error": dnsfwd.HTTP2_ONLY}]
        out = insights.dns_insights({"mode": "dot", "effective_mode": "dot", "state": "fallback",
                                     "upstreams": ups}, {})
        hint = next(i for i in out if i["key"] == "dns_fallback")
        self.assertIn("dns.example.org: verweigert die Verbindung auf Port 853", hint["text"])
        self.assertIn("spricht nur HTTP/2", hint["text"])
        # Schmutzige Altdaten aus dns.json (älterer Weiterleiter): gesäubert
        ups = [{"label": "192.0.2.53", "last_error": "\x00\x00\x06\x04\x00\x00\x00\x00\x00"}]
        hint = insights.dns_insights({"mode": "servers", "effective_mode": "servers", "state": "fallback",
                                      "upstreams": ups}, {})[0]
        self.assertTrue(hint["text"].isprintable())


# =========================================================================================
# Neustarts: nur chronyd; dnsfwd meldet Bekanntes nicht erneut
# =========================================================================================
@unittest.skipUnless(shutil.which("bash"), "bash fehlt")
class ReloadChronydOnlyTest(unittest.TestCase):
    STUBS = """
set -euo pipefail
log() { :; }
now() { echo 1000; }
write_status() { :; }
declare -A SVC_ENTRY=() SVC_STATE=()
RELOAD_REQUESTED=0; CHRONYD_RELOAD_REQUESTED=0
"""

    def run_bash(self, body, *funcs):
        script = self.STUBS + _entrypoint_functions(*funcs) + "\n" + body
        return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=20,
                              check=True).stdout.split()

    def test_request_file_reloads_only_chronyd(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        out = self.run_bash(f"""
RUN_DIR={tmp}
reload_services() {{ echo VOLL; }}
reload_chronyd() {{ echo "CHRONYD:$1"; }}
touch "$RUN_DIR/reload-chronyd.request"; process_reload_requests
[[ -e "$RUN_DIR/reload-chronyd.request" ]] || echo erledigt
touch "$RUN_DIR/reload-chronyd.request" "$RUN_DIR/reload.request"; process_reload_requests
process_reload_requests; echo leer
""", "process_reload_requests")
        self.assertEqual(out, ["CHRONYD:settings", "erledigt", "VOLL", "leer"])

    def test_settings_reload_keeps_gpsd_and_dnsfwd(self):
        out = self.run_bash("""
service_alive() { kill -0 "${1%%=*}" 2>/dev/null; }
apply_config() { echo apply; }
emit_stub() { echo "EVENT:$1:$2"; }; EMIT_EVENT=emit_stub
start_chronyd() { sleep 60 >/dev/null 2>&1 & SVC_ENTRY[chronyd]="$!=sleep"; }
sleep 60 >/dev/null 2>&1 & old=$!; SVC_ENTRY[chronyd]="$old=sleep"
sleep 60 >/dev/null 2>&1 & gps=$!; SVC_ENTRY[gpsd]="$gps=sleep"
sleep 60 >/dev/null 2>&1 & dns=$!; SVC_ENTRY[dnsfwd]="$dns=sleep"
reload_chronyd settings
kill -0 "$gps" && [[ "${SVC_ENTRY[gpsd]%%=*}" == "$gps" ]] && echo gpsd_gleich
kill -0 "$dns" && [[ "${SVC_ENTRY[dnsfwd]%%=*}" == "$dns" ]] && echo dnsfwd_gleich
[[ "${SVC_ENTRY[chronyd]%%=*}" != "$old" ]] && echo chronyd_neu
kill "$gps" "$dns" "${SVC_ENTRY[chronyd]%%=*}"
""", "reload_chronyd")
        self.assertEqual(out, ["apply", "EVENT:reload:info", "gpsd_gleich", "dnsfwd_gleich", "chronyd_neu"])

    def test_automatics_use_chronyd_reload(self):
        text = (ROOT / "app" / "server.py").read_text(encoding="utf-8")
        self.assertIn("gpsquality.configure(history=HISTORY, trigger_reload=trigger_reload_chronyd", text)
        self.assertIn("autocal.configure(history=HISTORY, trigger_reload=trigger_reload_chronyd)", text)

    def test_trigger_writes_request_and_holdover_sees_it(self):
        import server
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        Path(tmp, "supervisor.pid").write_text("1")
        with mock.patch.object(server, "RUN_DIR", tmp), mock.patch.dict(os.environ, {"NTPGUI_RUN_DIR": tmp}):
            self.assertTrue(server.trigger_reload_chronyd())
            self.assertTrue(Path(tmp, "reload-chronyd.request").exists())
            self.assertFalse(Path(tmp, "reload.request").exists())
            self.assertTrue(holdover.reload_busy())


class DnsEventMemoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.path = os.path.join(self.tmp, dnsfwd.MEMORY_NAME)

    def gate(self, cls, events):
        return cls(lambda level, title, data: events.append((level, title, data)),
                   memory=dnsfwd.EventMemory(self.path))

    def test_known_fallback_not_reported_again_after_restart(self):
        first = []
        self.gate(dnsfwd.EventGate, first)("starting", "fallback", {"errors": ["192.0.2.53: Zeitüberschreitung"]})
        self.assertEqual(len(first), 1)
        again = []   # neuer Prozess (Neustart durch den Supervisor), derselbe Ausfall
        self.gate(dnsfwd.EventGate, again)("starting", "fallback", {"errors": ["192.0.2.53: Zeitüberschreitung"]})
        self.assertEqual(again, [])
        back = []    # nach dem nächsten Neustart antworten die Server wieder: das wird gemeldet
        self.gate(dnsfwd.EventGate, back)("starting", "ok", {"upstream": "192.0.2.53"})
        self.assertEqual([e[0] for e in back], ["info"])
        quiet = []   # und danach ist „starting → ok“ wieder kein Ereignis
        self.gate(dnsfwd.EventGate, quiet)("starting", "ok", {"upstream": "192.0.2.53"})
        self.assertEqual(quiet, [])

    def test_upstream_down_remembered_and_return_reported(self):
        first = []
        gate = self.gate(dnsfwd.UpstreamGate, first)
        gate("192.0.2.53", "down", "Zeitüberschreitung")
        self.assertEqual(len(first), 1)
        again = []
        gate = self.gate(dnsfwd.UpstreamGate, again)
        self.assertEqual(gate.reported_down(), ["192.0.2.53"])
        gate("192.0.2.53", "down", "Zeitüberschreitung")
        self.assertEqual(again, [])
        gate("192.0.2.53", "up", "")
        self.assertEqual([e[0] for e in again], ["info"])

    def test_serve_marks_known_down_upstreams(self):
        """serve() setzt reported_down aus dem Gedächtnis – sonst käme die Rückkehr nie als Ereignis."""
        text = (ROOT / "app" / "dnsfwd.py").read_text(encoding="utf-8")
        self.assertIn("up.reported_down = up.label in known_down", text)


# =========================================================================================
# Hinweise
# =========================================================================================
class NtsNoteTest(unittest.TestCase):
    SOURCES = [{"host": f"nts{i}.example.org", "nts": True} for i in range(1, 6)]

    def test_example_matches_mode_and_list_is_marked_short(self):
        doh = dnsfwd.nts_note({"dns_mode": "doh", "dns_doh": ["https://doh.example.org/dns-query"],
                               "ntp_sources": self.SOURCES}, 1)
        self.assertIn("https://dns.quad9.net/dns-query", doh)
        self.assertIn("(und 1 weitere)", doh)
        self.assertNotIn("nts5.example.org", doh)
        dot = dnsfwd.nts_note({"dns_mode": "dot", "dns_dot": ["dns.example.org"], "ntp_sources": self.SOURCES[:2]}, 1)
        self.assertIn("dns.quad9.net und one.one.one.one", dot)
        self.assertNotIn("weitere", dot)
        plain = dnsfwd.nts_note({"dns_mode": "servers", "dns_servers": ["192.0.2.53"],
                                 "ntp_sources": self.SOURCES[:1]}, 1)
        self.assertIn("9.9.9.9", plain)
        self.assertNotIn("dns.quad9.net", plain)

    def test_example_resolvers_are_not_pseudonymised(self):
        note = dnsfwd.nts_note({"dns_mode": "dot", "dns_dot": ["dns.example.org"], "ntp_sources": self.SOURCES}, 1)
        clean = egress.Sanitizer("diagnostics").text(note)
        self.assertIn("dns.quad9.net und one.one.one.one", clean)
        self.assertEqual(egress.backstop({"h": clean.encode()}), [])
        import webtransport
        self.assertNotIn("172.18.0.2", (ROOT / "app" / "webtransport.py").read_text(encoding="utf-8"))
        self.assertTrue(webtransport)


class GpsCombinedRoleTest(unittest.TestCase):
    CFG = {"gps_enable": True, "gps_pps_device": "", "gps_pps_shm": False, "gps_delay": 0.03,
           "gps_precision": 0.1, "gps_select": "auto", "gps_refid": "GPS", "gps_bound_mode": "measured",
           "ntp_minsources": 1}

    def test_plus_is_not_called_network_worse(self):
        sources = [{"name": "GPS", "mode": "#", "state": "+"}] + [
            {"name": f"192.0.2.{i}", "mode": "^", "state": "*" if i == 1 else "+"} for i in range(1, 6)]
        role = gpsquality.role(self.CFG, sources, {})
        self.assertTrue(role["active"])
        self.assertNotIn("schlechter oder fehlen", role["text"])
        self.assertIn("mit kleinem Gewicht", role["text"])
        best = gpsquality.role(self.CFG, [{"name": "GPS", "mode": "#", "state": "*"}], {})
        self.assertIn("schlechter oder fehlen", best["text"])

    def test_insight_combined_and_weak_reception(self):
        status = {
            "chrony_running": True,
            "tracking": {"synchronised": True, "stratum": 2, "system_time_offset": 1e-6, "ref_name": "192.0.2.1"},
            "sources": [{"mode": "#", "name": "GPS", "state": "+", "select_state": "combined", "offset": 0.0015,
                         "reach": 255},
                        {"mode": "^", "name": "192.0.2.1", "state": "*", "reach": 255}],
            "system": {"clock_control": True}, "gps": {"enabled": True, "running": True, "has_fix": True},
            "ui": {"auth": {"enabled": True}, "storage": {"persistent": True}}, "client_count": 2,
            "gps_summary": {"level": "red"},
        }
        item = next(i for i in insights.build(status, {"gps_refid": "GPS"}) if i["key"] == "gps_used")
        self.assertEqual(item["title"], "GPS wird mitgerechnet")
        self.assertEqual(item["level"], "info")   # schwacher Empfang ist kein „ok“
        status["gps_summary"] = {"level": "green"}
        item = next(i for i in insights.build(status, {"gps_refid": "GPS"}) if i["key"] == "gps_used")
        self.assertEqual(item["level"], "ok")


# =========================================================================================
# Datenschutzfilter
# =========================================================================================
class ChronycCsvColumnsTest(unittest.TestCase):
    ROWS = [("sourcestats", "192.0.2.10,11,7,459,0.367,12.345,-0.001234567,0.000464269"),
            ("sourcestats", "192.0.2.10,11,7,459,0.367,1.2345,-0.000123456,0.0004"),
            ("sourcestats", "192.0.2.33,15,3,1418,-6.635,6.916,-1.637147947,0.042451919"),
            # zwei Offsets ≥ 1 s (beim Start); zusammengesetzt, damit der Wächter keine Koordinate sieht
            ("sources", "^,+,192.0.2.10,1,10,377,178," + ",".join(["-1.234567"] * 2) + ",0.01")]

    def test_columns_and_values_kept(self):
        for command, row in self.ROWS:
            sanitizer = egress.Sanitizer("diagnostics")
            out = sanitizer.chronyc(["-c", command], row)
            self.assertEqual(len(out.split(",")), len(row.split(",")), out)
            self.assertNotIn("<koordinaten>", out)
            for a, b in list(zip(row.split(","), out.split(",")))[3:]:
                self.assertEqual(float(a), float(b), out)
            self.assertNotIn("position", sanitizer.report()["removed"])
            self.assertEqual(egress.check_no_leaks(out), [], out)
            self.assertEqual(egress.backstop({"c": out.encode()}), [], out)

    def test_real_coordinates_still_caught(self):
        sanitizer = egress.Sanitizer("diagnostics")
        self.assertIn("<koordinaten>", sanitizer.text("Standort 48.1371543, 11.5761249"))


class RefclockDelayTest(unittest.TestCase):
    def test_gps_bound_not_rounded_in_json(self):
        sanitizer = egress.Sanitizer("diagnostics")
        sources = sanitizer.obj([{"name": "GPS", "mode": "#", "mode_label": "refclock", "error": 0.0165},
                                 {"name": "198.51.100.7", "mode": "^", "mode_label": "server", "error": 0.0165}])
        self.assertEqual(sources[0]["error"], 0.0165)
        self.assertEqual(sources[1]["error"], 0.02)
        select = sanitizer.obj({"name": "GPS", "select_state": "+", "interval_low": -0.013838812,
                                "interval_high": 0.019216204})
        self.assertEqual(select["interval_high"], 0.019216204)
        role = sanitizer.obj({"gps": {"role": {"delay": 0.027, "bound": 0.0135, "bound_source": "measured"}}})
        self.assertEqual(role["gps"]["role"]["delay"], 0.027)
        event = sanitizer.obj({"kind": "gps", "data": {"old_delay": 0.052, "new_delay": 0.027,
                                                       "measured_delay": 0.0213}})
        self.assertEqual(event["data"], {"old_delay": 0.052, "new_delay": 0.027, "measured_delay": 0.0213})
        self.assertEqual(egress.check_no_leaks([sources, select, role, event]), [])


class SmallFilterFixesTest(unittest.TestCase):
    def test_ptp4l_key_kept(self):
        line = "power_profile.version\t\t\tnone"
        self.assertEqual(egress.Sanitizer("diagnostics").text(line), line)
        self.assertEqual(egress.backstop({"ptp4l.conf": line.encode()}), [])
        # ein echter Name hinter einem Unterstrich bleibt geschützt
        self.assertNotIn("nas.example.de", egress.Sanitizer("diagnostics").text("backup_nas.example.de"))

    def test_event_subject_is_no_certificate(self):
        sanitizer = egress.Sanitizer("diagnostics")
        out = sanitizer.obj([{"kind": "gps", "data": {"subject": "gnss", "stage": "ok"}},
                             {"kind": "gps", "data": {"subject": "gps-sperre"}},
                             {"kind": "clients", "data": {"subject": "192.0.2.20#neu"}}])
        self.assertEqual(out[0]["data"]["subject"], "gnss")
        self.assertEqual(out[1]["data"]["subject"], "gps-sperre")
        self.assertTrue(out[2]["data"]["subject"].endswith("#neu"))
        self.assertNotIn("zertifikat", sanitizer.report()["removed"])
        cert = egress.Sanitizer("diagnostics").obj({"nts_server": {"subject": "ntp.example.de"}})
        self.assertEqual(cert["nts_server"]["subject"], "<zertifikatsname>")

    def test_channel_id_pseudonymised(self):
        sanitizer = egress.Sanitizer("diagnostics")
        out = sanitizer.obj({"title": "Benachrichtigungskanal angelegt: 0a1b2c3d4e",
                             "data": {"channel": "0a1b2c3d4e", "type": "ntfy"}})
        self.assertEqual(out["data"]["channel"], "<kanal-1>")
        self.assertEqual(out["title"], "Benachrichtigungskanal angelegt: <kanal-1>")
        known = egress.Sanitizer("diagnostics", known={"kanal": ["0a1b2c3d4e"]})
        self.assertEqual(known.text("Kanal 0a1b2c3d4e meldet"), "Kanal <kanal-1> meldet")

    def test_uptimes_coarse(self):
        self.assertEqual(egress.coarse_seconds(1234), 1200)
        self.assertEqual(egress.coarse_seconds(5 * H + 1234), 5 * H)
        self.assertEqual(egress.coarse_seconds(3 * 86400 + 7 * H + 5), 3 * 86400)
        meta = diagnostics._collect_meta({}, {"uptime_seconds": 2 * 86400 + 3 * H + 17})
        self.assertEqual(meta["dashboard_uptime_seconds"], 2 * 86400)
        if "host_uptime_seconds" in meta:
            self.assertEqual(meta["host_uptime_seconds"] % 600, 0)
        row = egress.Sanitizer("diagnostics").chronyc(["-c", "authdata"], "192.0.2.1,NTS,1,15,256,123457,0,0,8,64")
        self.assertEqual(row.split(",")[5], "86400")

    def test_directional_dop_dropped(self):
        sanitizer = egress.Sanitizer("diagnostics")
        sky = sanitizer.obj({"class": "SKY", "time": "2026-01-01T00:00:00Z", "xdop": 0.71, "ydop": 0.93,
                             "vdop": 1.21, "tdop": 0.66, "hdop": 0.8333, "pdop": 1.4642, "nSat": 12, "uSat": 8})
        # 2306: auch PDOP (VDOP rückrechenbar) und nSat (Satelliten ohne Signal, folgt der Geometrie).
        self.assertEqual(sky, {"class": "SKY", "time": "2026-01-01T00:00:00Z", "hdop": 0.8, "uSat": 8})
        status = sanitizer.obj({"status": {"xdop": 0.71, "ydop": 0.93, "hdop": 0.8333}})
        self.assertEqual(status, {"status": {"hdop": 0.8}})
        self.assertEqual(sanitizer.report()["removed"].get("dop"), 7)
        self.assertEqual(sanitizer.report()["removed"].get("satellitenliste"), 1)
        self.assertNotIn("position", sanitizer.report()["removed"])

    def test_show_position_switch_kept(self):
        sanitizer = egress.Sanitizer("diagnostics")
        self.assertEqual(sanitizer.obj({"gps_show_position": False, "x": 1}), {"gps_show_position": False, "x": 1})
        self.assertEqual(sanitizer.report()["removed"], {})
        self.assertEqual(egress.check_no_leaks({"gps_show_position": True}), [])
        self.assertEqual(sanitizer.obj({"position": [48.1371543, 11.5761249]}), {})

    def test_dropped_line_names_kind_and_command(self):
        record = json.dumps({"t": 1, "kind": "chronyc", "args": ["-c", "clients"],
                             "out": "Standort 48.1371543, 11.5761249"})
        text = "erste Zeile\n" + record
        out = diagnostics.drop_leaky_lines(text, egress.Sanitizer("diagnostics"))
        self.assertEqual(out.split("\n")[0], "erste Zeile")
        dropped = out.split("\n")[1]
        self.assertTrue(dropped.startswith("[Zeile entfernt – Datenschutz: "), dropped)
        self.assertIn("chronyc -c clients", dropped)
        self.assertNotIn("48.13", dropped)
        self.assertEqual(egress.check_no_leaks(out), [])


# =========================================================================================
# GPS-Fehlerschranke: Einschwingen nach Neustart, Vergrößern nach kurzer Messung
# =========================================================================================
class BoundAfterRestartTest(unittest.TestCase):
    def measured(self, delay, duration):
        return {"status": "measured", "delay": delay, "precision": 0.01, "bound": delay / 2,
                "duration_seconds": duration}

    def test_short_measurement_grows_only_on_clear_increase(self):
        applied = {"delay": 0.04, "precision": 0.01, "t": 1_800_000_000.0}
        now = applied["t"] + 20 * H
        # 1 h nach Neustarts: ± 20 → ± 26 ms (×1,3) – wartet auf mehr Messzeit
        self.assertFalse(gpsquality.decide(self.measured(0.052, 1 * H), applied, now)["apply"])
        # deutlicher Anstieg (×2): sofort
        self.assertTrue(gpsquality.decide(self.measured(0.08, 1 * H), applied, now)["apply"])
        # volles Fenster: wie bisher
        self.assertTrue(gpsquality.decide(self.measured(0.052, 6 * H), applied, now)["apply"])

    def test_tick_skips_settling_after_chronyd_start(self):
        seen = {}

        def fake_measure(samples, name, now=None, hours=gpsquality.BOUND_HOURS, not_before=None):
            seen["not_before"] = not_before
            return {"status": "insufficient"}
        started = 1_800_000_000.0
        cfg = dict(GpsCombinedRoleTest.CFG)
        with mock.patch.object(gpsquality, "measure", fake_measure), \
                mock.patch.object(gpsquality, "load_state", return_value={}), \
                mock.patch.object(gpsquality, "save_state"), \
                mock.patch.object(gpsquality, "note_offset", return_value=None):
            gpsquality.configure(chronyd_started=lambda: started)
            try:
                gpsquality.tick(cfg, started + 2 * H, samples=[])
            finally:
                gpsquality._DEPS["chronyd_started"] = None
        self.assertEqual(seen["not_before"], started + gpsquality.RESTART_SETTLE)

    def test_chronyd_start_from_reload_json(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        with mock.patch.dict(os.environ, {"NTPGUI_RUN_DIR": tmp}):
            self.assertIsNone(gpsquality.chronyd_started())
            Path(tmp, "reload.json").write_text('{"state": "done", "message": "x", "time": 1800000000}')
            self.assertEqual(gpsquality.chronyd_started(), 1_800_000_000)
            Path(tmp, "reload.json").write_text('{"state": "running", "message": "x", "time": 1800000000}')
            self.assertIsNone(gpsquality.chronyd_started())


if __name__ == "__main__":
    unittest.main()
