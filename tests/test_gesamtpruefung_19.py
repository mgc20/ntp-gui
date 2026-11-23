"""Release 1.9, Gesamtprüfung: Lesen von settings.json als root, schwache Passwörter mit WEB_REQUIRE_AUTH,
Client-Messung ohne Neustart, Rechte des Containers im Hardware-Check, Vorrang des Passworts aus der
Umgebung, Vorschau mit NTS-Zertifikaten, die nur root lesen kann.

Jeder Test prüft das sichere bzw. richtige Verhalten und schlägt ohne die jeweilige Korrektur fehl."""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: E402,F401 – vor jedem App-Import: Host-Pfade umlenken

import clientmon  # noqa: E402
import confgen  # noqa: E402
import devices  # noqa: E402
import hardware  # noqa: E402
import server  # noqa: E402
import settings  # noqa: E402
from test_anmeldung import _ServerBase, basic  # noqa: E402
from test_container_haertung import run_bash  # noqa: E402
from test_hardware import CAP_TIME_ADMIN, HardwareTestCase, base_cfg  # noqa: E402

ENTRYPOINT = ROOT / "docker" / "entrypoint.sh"


# ---------------------------------------------------------------------------
# 1. settings.json: keine gewöhnliche Datei
# ---------------------------------------------------------------------------

class SettingsFileTypeTest(unittest.TestCase):
    """confgen.py liest settings.json als root aus dem Verzeichnis des Dashboard-Benutzers."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gesamt-settings-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.data = os.path.join(self.tmp, "data")
        os.makedirs(self.data)
        self.file = os.path.join(self.data, "settings.json")

    def run_apply(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("WEB_", "NTP_", "ALLOW_"))}
        env.update(NTPGUI_DATA_DIR=self.data, NTPGUI_RUN_DIR=os.path.join(self.tmp, "run"),
                   CHRONY_CONF=os.path.join(self.tmp, "etc", "chrony.conf"),
                   PTP4L_CONF=os.path.join(self.tmp, "etc", "ptp4l.conf"),
                   NTPGUI_NTS_CERT_DIR=os.path.join(self.tmp, "nts"),
                   NTPGUI_CHRONYD=os.path.join(self.tmp, "kein-chronyd"),
                   CUSTOM_CHRONY_CONF=os.path.join(self.tmp, "keine.conf"),
                   CUSTOM_PTP4L_CONF=os.path.join(self.tmp, "keine-ptp.conf"),
                   GPS_WAIT_SECONDS="0")
        return subprocess.run([sys.executable, str(ROOT / "app" / "confgen.py"), "apply"], env=env,
                              capture_output=True, text=True, timeout=30)

    def test_fifo_as_settings_does_not_block_and_runs_restricted(self):
        os.mkfifo(self.file)
        try:
            result = self.run_apply()
        except subprocess.TimeoutExpired:
            self.fail("confgen.py apply wartet an einer Pipe statt settings.json als nicht lesbar zu werten")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("keine gewöhnliche Datei", result.stderr)
        self.assertIn("Notbetrieb", result.stderr)
        conf = Path(self.tmp, "etc", "chrony.conf").read_text(encoding="utf-8")
        self.assertNotRegex(conf, r"(?m)^allow ")

    def test_link_as_settings_counts_as_unreadable(self):
        target = os.path.join(self.tmp, "fremd.json")
        Path(target).write_text('{"schema": 4, "values": {"allow_networks": ["0.0.0.0/0"]}}', encoding="utf-8")
        os.symlink(target, self.file)
        result = self.run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("symbolischer Link", result.stderr)
        conf = Path(self.tmp, "etc", "chrony.conf").read_text(encoding="utf-8")
        self.assertNotIn("allow 0.0.0.0/0", conf)

    def test_oversized_settings_count_as_unreadable(self):
        with open(self.file, "wb") as handle:
            handle.truncate(settings.SETTINGS_MAX_BYTES + 1)
        with mock.patch.object(settings, "SETTINGS_FILE", self.file), mock.patch("sys.stderr", new=io.StringIO()):
            settings._CACHE.update(mtime=None, data=None, error=None)
            try:
                self.assertIn("größer als", settings.load_error() or "")
            finally:
                settings._CACHE.update(mtime=None, data=None, error=None)

    def test_regular_settings_still_load(self):
        Path(self.file).write_text('{"schema": 4, "values": {"local_stratum": 7}}', encoding="utf-8")
        with mock.patch.object(settings, "SETTINGS_FILE", self.file):
            settings._CACHE.update(mtime=None, data=None, error=None)
            try:
                self.assertIsNone(settings.load_error())
            finally:
                settings._CACHE.update(mtime=None, data=None, error=None)

    @unittest.skipUnless(shutil.which("bash"), "bash fehlt")
    def test_supervisor_keeps_stderr_after_open_pause(self):
        """Meldungen von confgen beim Neuladen (z. B. Schutzmodus) müssen im Container-Log ankommen."""
        from test_container_haertung import STUBS, _functions
        script = STUBS + _functions("open_pause", "pause") + '\nopen_pause\necho "fehlerkanal" >&2\npause 0.1\n'
        result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30, check=True)
        self.assertIn("fehlerkanal", result.stderr)

    def test_entrypoint_bounds_confgen(self):
        text = ENTRYPOINT.read_text(encoding="utf-8")
        self.assertRegex(text, r'out=\$\(timeout -k \d+ "\$CONFGEN_TIMEOUT" python3 "\$\{APP_DIR\}/confgen.py" apply')
        self.assertNotRegex(text, r'out=\$\(python3 "\$\{APP_DIR\}/confgen.py"')


# ---------------------------------------------------------------------------
# 2. WEB_REQUIRE_AUTH: schwaches Passwort aus der Umgebung gilt nicht
# ---------------------------------------------------------------------------

class RequireAuthWeakPasswordTest(_ServerBase):
    ENV = {"WEB_REQUIRE_AUTH": "true", "WEB_PASSWORD": "bitte-aendern"}

    def test_example_password_keeps_dashboard_locked(self):
        status, payload, _ = self.request("GET", "/api/status", headers={
            "Accept": "application/json", "Authorization": basic("admin", "bitte-aendern")})
        self.assertEqual(status, 503)
        self.assertEqual(payload["reason"], "auth_setup_required")
        status, _, _ = self.request("POST", "/api/settings", {"changes": {"ntp_minsources": 2}},
                                    {"Authorization": basic("admin", "bitte-aendern")})
        self.assertEqual(status, 503)
        lines = "\n".join(server.startup_auth_warnings("0.0.0.0"))
        self.assertIn("GESPERRT", lines)
        self.assertIn("zu schwach", lines)

    def test_password_equal_to_user_is_refused(self):
        with mock.patch.dict(os.environ, {"WEB_USER": "zeitmeister", "WEB_PASSWORD": "zeitmeister"}):
            self.assertTrue(server.auth_info()["locked"])

    def test_strong_password_works(self):
        with mock.patch.dict(os.environ, {"WEB_PASSWORD": "ein-langes-eigenes-geheimnis"}):
            auth = {"Authorization": basic("admin", "ein-langes-eigenes-geheimnis")}
            self.assertEqual(self.request("GET", "/api/v1/instance", headers=auth)[0], 200)

    def test_stored_password_still_applies(self):
        settings.set_credentials("admin", "lang-und-eigen-42")
        auth = {"Authorization": basic("admin", "lang-und-eigen-42")}
        self.assertEqual(self.request("GET", "/api/v1/instance", headers=auth)[0], 200)
        self.assertEqual(self.request("GET", "/api/v1/instance",
                                      headers={"Authorization": basic("admin", "bitte-aendern")})[0], 401)


class RequireAuthWithoutPasswordTest(_ServerBase):
    ENV = {"WEB_REQUIRE_AUTH": "true"}

    def test_missing_password_is_not_reported_as_weak(self):
        lines = "\n".join(server.startup_auth_warnings("0.0.0.0"))
        self.assertIn("WEB_REQUIRE_AUTH=true, aber kein Zugang", lines)
        self.assertNotIn("zu schwach", lines)


class WeakPasswordWithoutRequireAuthTest(_ServerBase):
    ENV = {"WEB_PASSWORD": "bitte-aendern"}

    def test_lan_keeps_previous_behaviour(self):
        auth = {"Authorization": basic("admin", "bitte-aendern")}
        self.assertEqual(self.request("GET", "/api/v1/instance", headers=auth)[0], 200)
        self.assertIn("schwach", "\n".join(server.startup_auth_warnings("127.0.0.1")))

    def test_templates_carry_no_example_password(self):
        for path in sorted(ROOT.glob("docker-compose*.yml")):
            with self.subTest(path.name):
                self.assertNotRegex(path.read_text(encoding="utf-8"),
                                    r'WEB_PASSWORD: "(?i:bitte-aendern|changeme|admin|passwort)"')


# ---------------------------------------------------------------------------
# 3. Client-Messung: NET_RAW unabhängig vom Zustand beim Start
# ---------------------------------------------------------------------------

class ClientmonCapabilityTest(unittest.TestCase):
    def test_dashboard_gets_net_raw_regardless_of_saved_switch(self):
        text = ENTRYPOINT.read_text(encoding="utf-8")
        line = next(l for l in text.splitlines() if l.startswith("WEB_CAPS="))
        self.assertIn("net_raw", line)
        self.assertNotRegex(text, r"NTPGUI_CLIENTMON[^\n]*WEB_CAPS")

    def test_field_needs_no_restart_and_reason_matches(self):
        self.assertEqual(settings.FIELDS["clientmon_enable"]["restart"], settings.RESTART_NONE)
        monitor = clientmon.Monitor(123)
        with mock.patch.object(clientmon.socket, "socket", side_effect=PermissionError(1, "verweigert")):
            self.assertFalse(monitor.open())
        self.assertIn("NET_RAW", monitor.reason)
        self.assertNotIn("beim Start", monitor.reason)


# ---------------------------------------------------------------------------
# 5. Hardware-Check: Rechte des Containers statt des Dashboard-Prozesses
# ---------------------------------------------------------------------------

class ContainerCapsTest(HardwareTestCase):
    DASHBOARD_ONLY_NET_RAW = "0000000000002000"

    def setUp(self):
        super().setUp()
        self.run_dir = os.path.join(self.tmp, "run")
        os.makedirs(self.run_dir)
        patch = mock.patch.dict(os.environ, {"NTPGUI_RUN_DIR": self.run_dir})
        patch.start()
        self.addCleanup(patch.stop)

    def write_container(self, cap_prm: str, seccomp: str = "2"):
        Path(self.run_dir, devices.CONTAINER_CAPS_NAME).write_text(
            f"CapPrm:\t{cap_prm}\nCapBnd:\t{cap_prm}\nSeccomp:\t{seccomp}\n", encoding="utf-8")

    def test_sys_time_of_container_counts(self):
        self.host.caps(self.DASHBOARD_ONLY_NET_RAW)
        self.write_container(CAP_TIME_ADMIN)
        rep = self.run_report(base_cfg())
        self.assertTrue(rep["permissions"]["sys_time"])
        self.assertTrue(rep["permissions"]["net_admin"])
        self.assertNotEqual(self.row(rep, "clock_control")["status"], "change")

    def test_privileged_container_detected(self):
        self.host.caps(self.DASHBOARD_ONLY_NET_RAW)
        self.write_container("000001ffffffffff", seccomp="0")
        self.assertTrue(self.run_report(base_cfg())["permissions"]["privileged"])

    def test_without_supervisor_file_own_process_counts(self):
        self.host.caps(CAP_TIME_ADMIN)
        self.assertTrue(self.run_report(base_cfg())["permissions"]["sys_time"])

    def test_ptp_check_uses_container_caps(self):
        self.host.caps(self.DASHBOARD_ONLY_NET_RAW)
        self.write_container(CAP_TIME_ADMIN)
        check = next(c for c in devices.ptp_readiness(base_cfg()) if c["key"] == "capability")
        self.assertTrue(check["ok"])


class DeviceOpenWithoutRootTest(unittest.TestCase):
    def test_eacces_as_unprivileged_user_is_not_unusable(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        dev = os.path.join(tmp, "pps0")
        Path(dev).write_text("", encoding="utf-8")
        refused = PermissionError(13, "Permission denied")
        refused.errno = 13
        with mock.patch.object(hardware.os, "open", side_effect=refused), \
                mock.patch.object(hardware.os, "geteuid", return_value=990):
            usable, code = hardware._try_open(dev)
        self.assertIsNone(usable)
        self.assertIsNone(code)
        self.assertIsNone(hardware._access_problem({"in_container": True, "usable": usable, "_code": code,
                                                    "dev": "/dev/pps0"}))

    def test_eperm_still_reported(self):
        with mock.patch.object(hardware.os, "open", side_effect=PermissionError(1, "Operation not permitted")), \
                mock.patch.object(hardware.os, "geteuid", return_value=990):
            self.assertEqual(hardware._try_open("/dev/pps0"), (False, "EPERM"))


@unittest.skipUnless(shutil.which("bash"), "bash fehlt")
class SupervisorWritesContainerCapsTest(unittest.TestCase):
    def test_container_caps_file(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        status = os.path.join(tmp, "status")
        Path(status).write_text("Name:\tbash\nCapInh:\t0\nCapPrm:\t00000000aa0425fb\nCapEff:\t00000000aa0425fb\n"
                                "CapBnd:\t00000000aa0425fb\nSeccomp:\t2\n", encoding="utf-8")
        run_bash(f"CAP_STATUS_FILE={status}\nRUN_DIR={tmp}\nwrite_container_caps\n", "write_container_caps")
        path = os.path.join(tmp, "container-caps")
        self.assertEqual(Path(path).read_text(encoding="utf-8"),
                         "CapPrm:\t00000000aa0425fb\nCapBnd:\t00000000aa0425fb\nSeccomp:\t2\n")
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o644)
        with mock.patch.dict(os.environ, {"NTPGUI_RUN_DIR": tmp}):
            self.assertTrue(devices.has_cap(25, devices.container_caps()))
        self.assertRegex(ENTRYPOINT.read_text(encoding="utf-8"),
                         r'supervisor\.pid"\nwrite_container_caps\n')


# ---------------------------------------------------------------------------
# 7. Passwort aus der Umgebung übergeht ein gespeichertes Dashboard-Passwort
# ---------------------------------------------------------------------------

class EnvPasswordOverridesStoredTest(_ServerBase):
    def test_startup_warns_when_stored_password_is_overridden(self):
        settings.set_credentials("admin", "geheimes-dashboard-passwort")
        with mock.patch.dict(os.environ, {"WEB_PASSWORD": "ein-langes-env-passwort"}):
            info = server.auth_info()
            self.assertEqual(info["source"], "env")
            self.assertTrue(info["gui_overridden"])
            lines = "\n".join(server.startup_auth_warnings("127.0.0.1"))
        self.assertIn("gilt aber nicht", lines)
        self.assertIn("WEB_PASSWORD", lines)

    def test_no_warning_without_stored_password(self):
        with mock.patch.dict(os.environ, {"WEB_PASSWORD": "ein-langes-env-passwort"}):
            self.assertFalse(server.auth_info()["gui_overridden"])
            self.assertNotIn("gilt aber nicht", "\n".join(server.startup_auth_warnings("127.0.0.1")))

    def test_settings_page_shows_hint(self):
        text = (ROOT / "app" / "static" / "js" / "pages" / "settings.js").read_text(encoding="utf-8")
        self.assertIn("auth.gui_overridden", text)


# ---------------------------------------------------------------------------
# 8. Vorschau: NTS-Originale nur für root lesbar
# ---------------------------------------------------------------------------

class NtsPreviewWithoutRootTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.cert, self.key = os.path.join(self.tmp, "nts.crt"), os.path.join(self.tmp, "nts.key")
        for path in (self.cert, self.key):
            Path(path).write_text("x", encoding="utf-8")
        self.copies = os.path.join(self.tmp, "nts-certs")
        os.makedirs(self.copies)
        self.cfg = {"nts_server_enable": True, "nts_server_cert": self.cert, "nts_server_key": self.key}

    def run_dry(self):
        hidden = {self.cert, self.key}
        notes = []
        real_access = os.access

        def unreadable(path):
            if path in hidden:
                raise PermissionError(13, "Permission denied", path)
            return b""

        with mock.patch.object(confgen.os, "geteuid", return_value=990), \
                mock.patch.object(confgen.os, "access", side_effect=lambda p, m: p not in hidden and real_access(p, m)), \
                mock.patch.object(confgen, "_read_limited", side_effect=unreadable):
            result = confgen.prepare_nts_files(self.cfg, target_dir=self.copies, ids=None, dry_run=True,
                                               warn=lambda _area, msg: notes.append(msg))
        return result, notes

    def test_copies_planned_when_originals_hidden(self):
        for name in ("server.crt", "server.key"):
            Path(self.copies, name).write_text("x", encoding="utf-8")
        result, notes = self.run_dry()
        self.assertEqual(result, (os.path.join(self.copies, "server.crt"), os.path.join(self.copies, "server.key")))
        self.assertFalse([n for n in notes if "bleibt aus" in n])
        self.assertEqual(notes, [])

    def test_without_copies_still_planned_with_hint(self):
        result, notes = self.run_dry()
        self.assertIsNotNone(result)
        self.assertTrue(notes and notes[0].startswith("Hinweis"))
        self.assertFalse([n for n in notes if "bleibt aus" in n])

    def test_missing_original_still_turns_server_off(self):
        os.unlink(self.cert)
        notes = []
        with mock.patch.object(confgen.os, "geteuid", return_value=990):
            result = confgen.prepare_nts_files(self.cfg, target_dir=self.copies, ids=None, dry_run=True,
                                               warn=lambda _area, msg: notes.append(msg))
        self.assertIsNone(result)
        self.assertTrue([n for n in notes if "bleibt aus" in n])


# ---------------------------------------------------------------------------
# Dokumentation
# ---------------------------------------------------------------------------

class DocsTest(unittest.TestCase):
    def test_update_notes_cover_1_9(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        part = text[text.index("## Update-Hinweise"):]
        part = part[:part.index("### Update-Hinweis (opt-in)")]
        self.assertIn("### Von 1.8 auf 1.9", part)
        for needle in ("NTP_RATELIMIT", "CLIENTLOGLIMIT", "OUTBOUND_TARGETS=loopback", "WEB_PASSWORD",
                       "990", "SETUID"):
            self.assertIn(needle, part)
        self.assertNotIn("gelten die Änderungen nur im Speicher", part)

    def test_password_file_must_be_overwritten(self):
        vps = (ROOT / "docs" / "integrationen" / "vps.md").read_text(encoding="utf-8")
        self.assertIn("--force-recreate", vps)
        self.assertIn("überschreiben", vps)

    def test_root_processes_named_correctly(self):
        security = " ".join((ROOT / "SECURITY.md").read_text(encoding="utf-8").split())
        self.assertNotIn("nur der Supervisor als root", security)
        self.assertIn("ptp4l", security)
        for name in ("docker-compose.ptp.yml", "docker-compose.all-in-one.yml"):
            text = (ROOT / name).read_text(encoding="utf-8")
            with self.subTest(name):
                self.assertNotIn("Nur der Supervisor läuft als root", text)
                self.assertIn("ptp4l/phc2sys", text)
        self.assertNotRegex((ROOT / "docker-compose.vps.yml").read_text(encoding="utf-8"), r"„:1\.5")


if __name__ == "__main__":
    unittest.main()
