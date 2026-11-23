"""Container-Härtung (1.9): Dashboard ohne root, Neustarts nur über feste Anforderungen,
Supervisor ohne Hänger bei verweigerten Signalen, schreibgeschütztes Root, Compose-Vorlagen."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
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

import dnsfwd  # noqa: E402
import holdover  # noqa: E402
import providers  # noqa: E402
import ptp  # noqa: E402
import server  # noqa: E402

ENTRYPOINT = ROOT / "docker" / "entrypoint.sh"


def _functions(*names: str) -> str:
    text = ENTRYPOINT.read_text(encoding="utf-8")
    chunks = []
    for name in names:
        match = re.search(rf"^{name}\(\) \{{.*?^\}}$", text, re.S | re.M)
        assert match, name
        chunks.append(match.group(0))
    return "\n".join(chunks)


STUBS = """
set -euo pipefail
log() { printf '[%s] %s\\n' "$1" "${*:2}"; }
now() { echo 1000; }
mono() { echo 1000; }
write_services() { :; }
declare -A SVC_ENTRY=() SVC_STATE=() SVC_RESTARTS=() SVC_EXIT=() SVC_SINCE=() \\
           SVC_NEXT=() SVC_STARTED=() SVC_FAILS=() SVC_NOTE=()
APP_DROP=(); APP_DROP_OFF=""; APP_USER=ntpgui
"""


def run_bash(body: str, *funcs: str, timeout: float = 30) -> list[str]:
    script = STUBS + _functions(*funcs) + "\n" + body
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=timeout,
                          check=True).stdout.splitlines()


@unittest.skipUnless(shutil.which("bash"), "bash fehlt")
class SupervisorWithoutKillTest(unittest.TestCase):
    """Ohne CAP_KILL scheitert das Signal an chronyd (anderer Benutzer). Der Supervisor darf dann nicht
    ewig warten, sondern meldet den Fehler und lässt den alten Dienst laufen."""

    FUNCS = ("wait_exec", "service_alive", "proc_ended", "stop_pid", "reload_chronyd")

    def test_reload_chronyd_returns_when_signal_is_refused(self):
        out = run_bash("""
STOP_GRACE=1
kill() { return 1; }   # wie ohne CAP_KILL: jedes Signal wird verweigert
write_status() { echo "STATUS:$1"; }
apply_config() { echo apply; }
start_chronyd() { echo FALSCH_zweiter_chronyd; }
sleep 60 >/dev/null 2>&1 & old=$!; SVC_ENTRY[chronyd]="$old=sleep"
reload_chronyd settings
[[ "${SVC_ENTRY[chronyd]%%=*}" == "$old" ]] && echo alter_eintrag_bleibt
builtin kill "$old"
""", *self.FUNCS, timeout=20)
        self.assertIn("apply", out)
        self.assertIn("STATUS:error", out)
        self.assertIn("alter_eintrag_bleibt", out)
        self.assertNotIn("FALSCH_zweiter_chronyd", out)
        self.assertTrue(any("CAP_KILL" in line for line in out), out)

    def test_stop_pid_escalates_to_sigkill(self):
        out = run_bash("""
STOP_GRACE=1
bash -c 'trap "" TERM; exec sleep 60' >/dev/null 2>&1 & p=$!
wait_exec "$p" sleep
if stop_pid "$p=sleep" test; then echo beendet; fi
[[ -e /proc/$p ]] && echo FALSCH_lebt || echo weg
""", "wait_exec", "service_alive", "proc_ended", "stop_pid", timeout=20)
        self.assertIn("beendet", out)
        self.assertIn("weg", out)
        self.assertTrue(any("SIGKILL" in line for line in out), out)

    def test_reload_services_does_not_start_twice(self):
        out = run_bash("""
write_status() { echo "STATUS:$1"; }
apply_config() { echo apply; }
stop_services() { return 1; }
start_services() { echo FALSCH_start; }
reload_services
""", "reload_services")
        self.assertEqual(out, ["[main] Einstellungen geändert – Zeitdienste werden neu gestartet …",
                               "STATUS:running", "apply", "STATUS:error"])


@unittest.skipUnless(shutil.which("bash"), "bash fehlt")
class StopServicesWithoutKillTest(unittest.TestCase):
    """Neuladen ohne CAP_KILL: Entweder alle Dienste lassen sich beenden, oder keiner wird angefasst."""

    FUNCS = ("wait_exec", "service_alive", "proc_ended", "stop_services")
    SETUP = """
STOP_GRACE=1
dns_restore() { echo DNS_RESTORE; }
start_ptp4l() { echo START_ptp4l; SVC_STATE[ptp4l]=running; }
start_phc2sys() { echo START_phc2sys; SVC_STATE[phc2sys]=running; }
start_chronyd() { echo FALSCH_start_chronyd; }
start_dnsfwd() { echo FALSCH_start_dnsfwd; }
start_gpsd() { echo FALSCH_start_gpsd; }
sleep 60 >/dev/null 2>&1 & ptp=$!; SVC_ENTRY[ptp4l]="$ptp=sleep"; SVC_STATE[ptp4l]=running
sleep 60 >/dev/null 2>&1 & chr=$!; SVC_ENTRY[chronyd]="$chr=sleep"; SVC_STATE[chronyd]=running
sleep 60 >/dev/null 2>&1 & dns=$!; SVC_ENTRY[dnsfwd]="$dns=sleep"; SVC_STATE[dnsfwd]=running
wait_exec "$ptp" sleep; wait_exec "$chr" sleep; wait_exec "$dns" sleep
"""

    def test_refused_signal_leaves_all_services_untouched(self):
        out = run_bash(self.SETUP + """
kill() { if [[ "$1" == -0 && ( "${2:-}" == "$chr" || "${2:-}" == "$dns" ) ]]; then return 1; fi; builtin kill "$@"; }
SECONDS=0
stop_services && echo FALSCH_erfolg || echo verweigert
(( SECONDS < 3 )) && echo ohne_wartezeit
[[ -d /proc/$ptp ]] && echo ptp4l_lebt
echo "ptp4l:${SVC_STATE[ptp4l]}:${SVC_ENTRY[ptp4l]%%=*}" | sed "s/$ptp/PID/"
builtin kill "$ptp" "$chr" "$dns"
""", *self.FUNCS, timeout=20)
        self.assertIn("verweigert", out)
        self.assertIn("ohne_wartezeit", out)
        self.assertIn("ptp4l_lebt", out)
        self.assertIn("ptp4l:running:PID", out)
        self.assertNotIn("DNS_RESTORE", out)
        self.assertTrue(any("chronyd dnsfwd" in line and "CAP_KILL" in line for line in out), out)

    def test_failed_stop_restarts_services_already_stopped(self):
        out = run_bash(self.SETUP + """
stop_pid() {
  if [[ "$2" == chronyd || "$2" == dnsfwd ]]; then return 1; fi
  builtin kill "${1%%=*}" 2>/dev/null; wait "${1%%=*}" 2>/dev/null; return 0
}
kill() { if [[ "$1" != -0 && ( "$1" == "$chr" || "$1" == "$dns" ) ]]; then return 1; fi; builtin kill "$@"; }
stop_services && echo FALSCH_erfolg || echo gescheitert
echo "ptp4l:${SVC_STATE[ptp4l]}"
echo "chronyd:${SVC_STATE[chronyd]}:${SVC_ENTRY[chronyd]:+eintrag}"
builtin kill "$chr" "$dns"
""", *self.FUNCS, timeout=20)
        self.assertIn("gescheitert", out)
        self.assertIn("START_ptp4l", out)
        self.assertIn("ptp4l:running", out)
        self.assertIn("chronyd:running:eintrag", out)
        self.assertNotIn("DNS_RESTORE", out)   # dnsfwd läuft noch: resolv.conf bleibt
        self.assertFalse(any(line.startswith("FALSCH") for line in out), out)

    def test_shutdown_stops_what_it_can(self):
        out = run_bash(self.SETUP + """
kill() { if [[ "$1" == -0 || "$1" == "$chr" || "$1" == "$dns" || "${2:-}" == "$chr" || "${2:-}" == "$dns" ]]; then return 1; fi; builtin kill "$@"; }
stop_services shutdown && echo FALSCH_erfolg || echo gescheitert
[[ -d /proc/$ptp ]] && echo FALSCH_ptp4l_lebt || echo ptp4l_beendet
builtin kill "$chr" "$dns"
""", *self.FUNCS, "stop_pid", timeout=30)
        self.assertIn("gescheitert", out)
        self.assertIn("ptp4l_beendet", out)
        self.assertNotIn("START_ptp4l", out)


@unittest.skipUnless(shutil.which("bash"), "bash fehlt")
class StartPreparationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_request_dir_keeps_recordings_and_drops_requests(self):
        req = os.path.join(self.tmp, "web")
        os.makedirs(req)
        for name in ("recording-20260101-000000.jsonl", "dns.json", "reload.request",
                     "reload-chronyd.request", "reload.hold", "events.jsonl.tmp"):
            Path(req, name).write_text("1\n", encoding="utf-8")
        run_bash(f"REQUEST_DIR={req}\nprepare_request_dir\n", "prepare_request_dir")
        self.assertEqual(sorted(os.listdir(req)), ["dns.json", "recording-20260101-000000.jsonl"])
        self.assertEqual(stat.S_IMODE(os.stat(req).st_mode), 0o750)

    def test_request_dir_link_is_replaced(self):
        target = os.path.join(self.tmp, "fremd")
        os.makedirs(target)
        Path(target, "reload.hold").write_text("1\n", encoding="utf-8")
        req = os.path.join(self.tmp, "web")
        os.symlink(target, req)
        run_bash(f"REQUEST_DIR={req}\nprepare_request_dir\n", "prepare_request_dir")
        self.assertFalse(os.path.islink(req))
        self.assertTrue(os.path.isdir(req))
        self.assertTrue(os.path.exists(os.path.join(target, "reload.hold")))   # Ziel unberührt

    def test_unreachable_data_dir_names_dac_override(self):
        blocker = os.path.join(self.tmp, "datei")
        Path(blocker).write_text("x", encoding="utf-8")
        script = STUBS + _functions("cap_has", "prepare_request_dir", "prepare_app_user") + f"""
CAP_STATUS_FILE=/dev/null
DATA_DIR={blocker}/ntp-gui; REQUEST_DIR={self.tmp}/web
prepare_app_user
echo FALSCH_weiter
"""
        proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("DAC_OVERRIDE", proc.stdout)
        self.assertNotIn("FALSCH_weiter", proc.stdout)

    def test_password_copy_follows_changes(self):
        src = os.path.join(self.tmp, "web_password.txt")
        Path(src).write_text("alt\n", encoding="utf-8")
        run_dir = os.path.join(self.tmp, "run")
        copy = os.path.join(run_dir, "secrets", "web_password")
        out = run_bash(f"""
RUN_DIR={run_dir}; WEB_PASSWORD_FILE={src}
chgrp() {{ :; }}
copy_web_password && echo kopiert
refresh_web_password; echo "unverändert:$(cat {copy})"
sleep 1.1; printf 'neu\n' > {src}
refresh_web_password; echo "neu:$(cat {copy})"
rm -f {src}
refresh_web_password; echo "fehlt:[$(cat {copy})]"
""", "file_signature", "copy_web_password", "refresh_web_password")
        self.assertIn("kopiert", out)
        self.assertIn("unverändert:alt", out)
        self.assertIn("neu:neu", out)
        self.assertIn("fehlt:[]", out)   # leer = Dashboard gesperrt, nie offen
        self.assertTrue(any("Passwortdatei geändert" in line for line in out), out)


class RootSafeTest(unittest.TestCase):
    """rootsafe.py: Zugriffe von root in Verzeichnissen, die dem Dashboard gehören."""

    def setUp(self):
        import rootsafe
        self.rootsafe = rootsafe
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_fifo_as_hold_file_does_not_block(self):
        hold = os.path.join(self.tmp, "reload.hold")
        os.mkfifo(hold)
        proc = subprocess.run([sys.executable, str(ROOT / "app" / "rootsafe.py"), "hold", hold],
                              capture_output=True, text=True, timeout=10)
        self.assertEqual((proc.returncode, proc.stdout), (0, ""))

    def test_hold_reads_regular_file_but_not_link(self):
        target = os.path.join(self.tmp, "ziel")
        Path(target).write_text("9999999999\n", encoding="utf-8")
        link = os.path.join(self.tmp, "reload.hold")
        os.symlink(target, link)
        self.assertEqual(self.rootsafe.read_hold(link), "")
        self.assertEqual(self.rootsafe.read_hold(target), "9999999999\n")

    def test_file_with_second_name_keeps_owner(self):
        data = os.path.join(self.tmp, "ntp-gui")
        os.makedirs(os.path.join(data, "sub"))
        outside = os.path.join(self.tmp, "nur-root")
        Path(outside).write_text("x", encoding="utf-8")
        os.link(outside, os.path.join(data, "link.test"))
        Path(data, "settings.json").write_text("{}", encoding="utf-8")
        Path(data, "sub", "a").write_text("1", encoding="utf-8")
        os.symlink(outside, os.path.join(data, "symlink.test"))
        changed = []

        def fake_chown(path, uid, gid):
            changed.append(os.path.realpath(path))
        uid = os.getuid() + 12345
        skipped = self.rootsafe.chown_tree(data, uid, uid, chown=fake_chown)
        self.assertEqual(skipped, [os.path.join(data, "link.test")])
        self.assertNotIn(os.path.realpath(outside), changed)
        for name in ("settings.json", "sub", os.path.join("sub", "a")):
            self.assertIn(os.path.realpath(os.path.join(data, name)), changed)

    def test_data_dir_handover_uses_rootsafe(self):
        body = _functions("data_dir_to_app")
        self.assertIn("rootsafe.py\" chown", body)
        self.assertNotIn("chown -R", body)


@unittest.skipUnless(shutil.which("bash"), "bash fehlt")
class PrivilegeDropTest(unittest.TestCase):
    def _status(self, eff: str, prm: str) -> str:
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        path = os.path.join(tmp, "status")
        Path(path).write_text(f"Name:\tbash\nCapInh:\t0\nCapPrm:\t{prm}\nCapEff:\t{eff}\n", encoding="utf-8")
        return path

    def test_cap_has_reads_bits_without_subprocess(self):
        path = self._status("0000000002000020", "0000000002002020")   # KILL, SYS_TIME; prm + NET_RAW
        out = run_bash(f"""
CAP_STATUS_FILE={path}
for bit in 5 25 13 7; do cap_has $bit && echo "eff:$bit" || true; done
cap_has 13 prm && echo prm:13
""", "cap_has")
        self.assertEqual(out, ["eff:5", "eff:25", "prm:13"])
        self.assertNotIn("$(", _functions("cap_has"))

    def test_app_drop_grants_only_available_caps(self):
        path = self._status("00000000000000c0", "00000000000020c0")   # SETUID/SETGID; NET_RAW erlaubt
        out = run_bash(f"""
CAP_STATUS_FILE={path}
app_drop "net_raw,net_bind_service,sys_time"
printf '%s\\n' "${{APP_DROP[@]}}"
""", "cap_has", "app_drop")
        self.assertEqual(out[:5], ["setpriv", "--reuid=ntpgui", "--regid=ntpgui", "--init-groups",
                                   "--no-new-privs"])
        self.assertIn("--inh-caps=-all,+net_raw", out)
        self.assertIn("--ambient-caps=-all,+net_raw", out)
        self.assertFalse(any("bounding" in item for item in out))   # ohne SETPCAP nicht möglich
        self.assertFalse(any("sys_time" in item or "net_bind" in item for item in out))
        self.assertEqual(out[-1], "--")

    def test_app_drop_empty_when_switch_impossible(self):
        out = run_bash("""
APP_DROP_OFF="CAP_SETUID/CAP_SETGID fehlen"
app_drop net_raw
echo "anzahl:${#APP_DROP[@]}"
""", "cap_has", "app_drop")
        self.assertEqual(out, ["anzahl:0"])

    def test_web_and_dnsfwd_start_unprivileged(self):
        text = ENTRYPOINT.read_text(encoding="utf-8")
        self.assertRegex(text, r'spawn_app web "\$WEB_CAPS" python3 "\$\{APP_DIR\}/server.py"')
        self.assertIn('spawn_app dns net_bind_service python3 "${APP_DIR}/dnsfwd.py" serve', text)
        self.assertNotRegex(text, r'\bspawn web\b')
        self.assertNotRegex(text, r'\bspawn dns\b')

    def test_spawned_service_counts_as_alive_after_setpriv(self):
        """Nach „setpriv … -- python3“ heißt das Kind kurz „setpriv“: nicht als Ausfall werten."""
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        os.symlink(shutil.which("bash"), os.path.join(tmp, "setpriv"))   # comm = Name des Links
        out = run_bash(f"""
{tmp}/setpriv -c 'sleep 0.3; exec sleep 60' >/dev/null 2>&1 & p=$!
until [[ "$(cat /proc/$p/comm)" == setpriv ]]; do :; done
service_alive "$p=sleep" && echo lebt || echo tot
kill "$p"
""", "wait_exec", "service_alive")
        self.assertEqual(out, ["lebt"])


@unittest.skipUnless(shutil.which("bash"), "bash fehlt")
class RequestDirTest(unittest.TestCase):
    """Das Dashboard schreibt nur in sein Verzeichnis; der Supervisor liest dort nur die festen Namen."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.run_dir = os.path.join(self.tmp, "run")
        self.req = os.path.join(self.run_dir, "web")
        os.makedirs(self.req)

    def test_supervisor_reads_requests_from_request_dir(self):
        out = run_bash(f"""
RUN_DIR={self.run_dir}; REQUEST_DIR={self.req}
RELOAD_REQUESTED=0; CHRONYD_RELOAD_REQUESTED=0
write_status() {{ :; }}
reload_services() {{ echo VOLL; }}
reload_chronyd() {{ echo "CHRONYD:$1"; }}
touch "$RUN_DIR/reload.request"; process_reload_requests; echo nichts
touch "$REQUEST_DIR/reload-chronyd.request"; process_reload_requests
[[ -e "$REQUEST_DIR/reload-chronyd.request" ]] || echo erledigt
""", "process_reload_requests")
        self.assertEqual(out, ["nichts", "CHRONYD:settings", "erledigt"])

    def test_hold_ignores_fifo_and_link(self):
        hold = os.path.join(self.req, "reload.hold")
        os.mkfifo(hold)
        out = run_bash(f"""
REQUEST_DIR={self.req}; APP_DIR={ROOT / "app"}
hold_active && echo FALSCH || echo fifo_ignoriert
rm -f {hold}; printf '9999999999\\n' > {self.tmp}/ziel; ln -s {self.tmp}/ziel {hold}
hold_active && echo FALSCH || echo link_ignoriert
rm -f {hold}; printf '9999999999\\n' > {hold}
hold_active && echo aktiv
""", "hold_active", timeout=10)
        self.assertEqual(out, ["fifo_ignoriert", "link_ignoriert", "aktiv"])

    def test_noselect_list_read_without_following_links(self):
        """noselect.list gehört dem Dashboard: Link, Pipe oder Verzeichnis an dieser Stelle dürfen den
        Supervisor (set -e) weder beenden noch aufhalten; gelesen werden höchstens die ersten 4 KiB."""
        data = os.path.join(self.tmp, "data")
        os.makedirs(data)
        target = os.path.join(self.tmp, "fremd")
        Path(target).write_text("FREMD\n", encoding="utf-8")
        lst = os.path.join(data, "noselect.list")
        out = run_bash(f"""
NTPGUI_DATA_DIR={data}; APP_DIR={ROOT / "app"}
chronyc() {{ return 0; }}
ln -s {target} {lst}; reapply_noselect; wait; echo link
rm -f {lst}; ln -s {self.tmp}/fehlt {lst}; reapply_noselect; wait; echo kaputt
rm -f {lst}; mkfifo {lst}; reapply_noselect; wait; echo fifo
rm -f {lst}; mkdir {lst}; reapply_noselect; wait; echo verzeichnis
rmdir {lst}; printf 'GPS\nkaputt name\nPPS' > {lst}; reapply_noselect; wait
rm -f {lst}; {{ head -c 5000 /dev/zero | tr '\\0' x; printf '\nSPAET\n'; }} > {lst}; reapply_noselect; wait
echo ende
""", "reapply_noselect", timeout=20)
        self.assertEqual([line.split(" nach dem")[0] for line in out if "WARNUNG" not in line],
                         ["link", "kaputt", "fifo", "verzeichnis", "[chrony] GPS-Sperre: GPS",
                          "[chrony] GPS-Sperre: PPS", "ende"])

    def test_dashboard_writes_requests_into_request_dir(self):
        Path(self.run_dir, "supervisor.pid").write_text("1\n", encoding="utf-8")
        with mock.patch.object(server, "RUN_DIR", self.run_dir), \
                mock.patch.dict(os.environ, {"NTPGUI_REQUEST_DIR": self.req}):
            self.assertTrue(server.trigger_reload())
            self.assertTrue(server.trigger_reload_chronyd())
        self.assertTrue(os.path.exists(os.path.join(self.req, "reload.request")))
        self.assertTrue(os.path.exists(os.path.join(self.req, "reload-chronyd.request")))
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, "reload.request")))

    def test_holdover_uses_request_dir_and_reads_reload_json_from_run_dir(self):
        env = {"NTPGUI_RUN_DIR": self.run_dir, "NTPGUI_REQUEST_DIR": self.req}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(holdover._hold_path(), os.path.join(self.req, "reload.hold"))
            self.assertEqual(holdover.reload_busy(), "")
            Path(self.run_dir, "reload.json").write_text(json.dumps({"state": "running", "time": 1000}),
                                                          encoding="utf-8")
            self.assertTrue(holdover.reload_busy(now=1001))
            Path(self.run_dir, "reload.json").unlink()
            Path(self.req, "reload.request").write_text("1\n", encoding="utf-8")
            self.assertIn("angefordert", holdover.reload_busy())

    def test_request_dir_defaults_to_run_dir(self):
        with mock.patch.dict(os.environ, {"NTPGUI_RUN_DIR": self.run_dir}):
            os.environ.pop("NTPGUI_REQUEST_DIR", None)
            self.assertEqual(providers.request_dir(), self.run_dir)
        with mock.patch.dict(os.environ, {"NTPGUI_RUN_DIR": self.run_dir, "NTPGUI_REQUEST_DIR": self.req}):
            self.assertEqual(providers.request_dir(), self.req)

    def test_recordings_go_to_request_dir(self):
        with mock.patch.dict(os.environ, {"NTPGUI_RUN_DIR": self.run_dir, "NTPGUI_REQUEST_DIR": self.req}):
            providers.start_recording(5)
            try:
                path = providers.status()["path"]
            finally:
                providers.stop()
        self.assertEqual(os.path.dirname(path), self.req)

    def test_dnsfwd_events_rotate(self):
        path = os.path.join(self.req, dnsfwd.EVENTS_NAME)
        Path(path).write_bytes(b"x" * (dnsfwd.EVENTS_MAX + 1))
        dnsfwd.emit_event("info", "Test", run_dir=self.req)
        self.assertTrue(os.path.exists(path + ".1"))
        self.assertLess(os.path.getsize(path), 1000)

    def test_events_ingester_reads_both_files(self):
        seen = []
        stop = mock.Mock()
        stop.wait.return_value = True
        with mock.patch.object(server, "RUN_DIR", self.run_dir), \
                mock.patch.dict(os.environ, {"NTPGUI_REQUEST_DIR": self.req}), \
                mock.patch.object(server.events, "ingest_supervisor", side_effect=seen.append):
            server.events_ingester(stop)
        self.assertEqual(seen, [os.path.join(self.run_dir, "events.jsonl"),
                                os.path.join(self.req, "events.jsonl")])


class PmcWithoutRootTest(unittest.TestCase):
    def test_pmc_client_socket_in_request_dir_without_root(self):
        with mock.patch.object(ptp.os, "geteuid", return_value=990), \
                mock.patch.dict(os.environ, {"NTPGUI_REQUEST_DIR": "/run/ntp-gui/web"}):
            args = ptp._pmc_base({"ptp_domain": 0})
        self.assertIn("-i", args)
        local = args[args.index("-i") + 1]
        self.assertTrue(local.startswith("/run/ntp-gui/web/pmc-"), local)
        self.assertLess(len(local), 100)   # Grenze für Pfade von Unix-Sockets

    def test_pmc_unchanged_as_root(self):
        with mock.patch.object(ptp.os, "geteuid", return_value=0):
            self.assertNotIn("-i", ptp._pmc_base({"ptp_domain": 0}))


class ConfgenForSupervisorTest(unittest.TestCase):
    def test_apply_reports_clientmon_and_ptp_socket(self):
        import confgen
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        env = dict(os.environ, CHRONY_CONF=os.path.join(tmp, "chrony.conf"),
                   PTP4L_CONF=os.path.join(tmp, "ptp4l.conf"), CLIENTMON="false",
                   PTP_UDS_ADDRESS="/var/run/ptp4l-test")
        with mock.patch.object(confgen, "check_chrony", return_value=None):
            result = confgen.apply(env)
        self.assertEqual(result["NTPGUI_CLIENTMON"], "0")
        self.assertEqual(result["NTPGUI_PTP_UDS"], "/var/run/ptp4l-test")


class ImageAndComposeTest(unittest.TestCase):
    """Statische Prüfung der Vorlagen – das Laufzeitverhalten prüft tests/container-test.sh."""

    COMPOSE = sorted(ROOT.glob("docker-compose*.yml"))

    def test_dockerfile_creates_user_and_strips_suid(self):
        text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("useradd --system --uid 990 --gid ntpgui --groups _chrony", text)
        self.assertIn("find / -xdev -type f -perm /6000 -exec chmod a-s {} +", text)

    def test_every_compose_file_is_hardened(self):
        self.assertGreaterEqual(len(self.COMPOSE), 6)
        for path in self.COMPOSE:
            text = path.read_text(encoding="utf-8")
            with self.subTest(path.name):
                self.assertRegex(text, r"\n    security_opt:\n      - no-new-privileges:true\n")
                self.assertRegex(text, r"\n    cap_drop:\n      - ALL\n")
                block = text[text.index("\n    cap_add:\n"):]
                block = block[:re.search(r"\n    [a-z_]+:", block[1:]).start() + 1]
                for cap in ("SYS_TIME", "SETUID", "SETGID", "CHOWN", "FOWNER", "DAC_OVERRIDE", "KILL"):
                    self.assertRegex(block, rf"\n      - {cap}\b")
                self.assertRegex(text, r"\n    pids_limit: \d+\n")
                self.assertRegex(text, r"\n    mem_limit: \d+[mg]\n")
                self.assertRegex(text, r'\n    logging:\n      driver: json-file\n      options:\n'
                                       r'        max-size: "10m"\n        max-file: "3"\n')

    def test_docs_name_chronyd_caps(self):
        for path in (ROOT / "SECURITY.md", ROOT / "README.md", ROOT / "docker-compose.vps.yml", ENTRYPOINT):
            text = " ".join(path.read_text(encoding="utf-8").split()).replace("# ", "")
            with self.subTest(path.name):
                self.assertNotRegex(text, r"(chronyd behält nur|behält nur|_chrony nur mit) `?SYS_TIME`?[.,|)]")
                self.assertRegex(text, r"SYS_TIME`? (\(und|und) `?NET_BIND_SERVICE`? für den NTP-Port")

    def test_ptp_templates_keep_ptp_caps(self):
        text = (ROOT / "docker-compose.ptp.yml").read_text(encoding="utf-8")
        self.assertRegex(text, r"\n      - NET_ADMIN\b")
        self.assertRegex(text, r"\n      - NET_RAW\b")

    def test_vps_template(self):
        text = (ROOT / "docker-compose.vps.yml").read_text(encoding="utf-8")
        for needle in ('WEB_REQUIRE_AUTH: "true"', 'WEB_BIND: "127.0.0.1"', 'NTP_RATELIMIT: "streng"',
                       "read_only: true", "      - /run:", "      - /tmp:", "      - /var/log:",
                       'TRUSTED_PROXIES: "127.0.0.1/32,::1/128"', "docs/integrationen/vps.md"):
            self.assertIn(needle, text)
        self.assertNotRegex(text, r"\n      - NET_RAW\b")
        self.assertTrue((ROOT / "docs" / "integrationen" / "vps.md").is_file())


@unittest.skipUnless(shutil.which("bash"), "bash fehlt")
class ReadOnlyRootTest(unittest.TestCase):
    def test_config_moves_to_run_when_etc_is_read_only(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        ro = os.path.join(tmp, "gibt-es-nicht")   # nicht beschreibbar – auch für root
        out = run_bash(f"""
CHRONY_CONF_GIVEN=""; PTP4L_CONF_GIVEN=1; PTP_LOG_GIVEN=""
CHRONY_CONF={ro}/chrony.conf; PTP4L_CONF={ro}/ptp4l.conf; PTP_LOG_FILE={tmp}/ptp4l.log
mkdir() {{ :; }}; chmod() {{ :; }}
use_run_when_readonly
echo "$CHRONY_CONF|$PTP4L_CONF|$PTP_LOG_FILE"
""", "use_run_when_readonly")
        self.assertEqual(out[-1], f"/run/ntp-gui-conf/chrony.conf|{ro}/ptp4l.conf|{tmp}/ptp4l.log")

    def test_readonly_logic_is_in_entrypoint(self):
        body = _functions("use_run_when_readonly")
        self.assertIn('! -w "${CHRONY_CONF%/*}"', body)
        self.assertIn('[[ -z "$CHRONY_CONF_GIVEN"', body)


class NtsStatusWithoutRootTest(unittest.TestCase):
    """Das Dashboard kann die Originale nicht lesen: Zustand aus den Kopien des Supervisors."""

    def test_uses_supervisor_copies_when_originals_unreadable(self):
        import chrony
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        orig_cert, orig_key = os.path.join(tmp, "orig.crt"), os.path.join(tmp, "orig.key")
        copies = os.path.join(tmp, "nts-certs")
        os.makedirs(copies)
        for path in (orig_cert, orig_key, os.path.join(copies, "server.crt"), os.path.join(copies, "server.key")):
            Path(path).write_text("x", encoding="utf-8")
        cfg = {"nts_server_enable": True, "nts_server_cert": orig_cert, "nts_server_key": orig_key,
               "nts_server_name": "zeit.example.test"}
        readable = {os.path.join(copies, "server.crt")}
        seen = []
        with mock.patch.dict(os.environ, {"NTPGUI_NTS_CERT_DIR": copies}), \
                mock.patch.object(chrony, "_readable", side_effect=lambda p: p in readable), \
                mock.patch.object(chrony, "_cert_info", side_effect=lambda p: seen.append(p) or {}), \
                mock.patch.object(chrony, "serverstats", return_value={}):
            result = chrony.nts_server_status(cfg)
        self.assertTrue(result["cert_readable"])
        self.assertTrue(result["key_readable"])
        self.assertEqual(seen, [os.path.join(copies, "server.crt")])

    def test_hidden_originals_count_when_copies_exist(self):
        import chrony
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        copy = os.path.join(tmp, "server.crt")
        Path(copy).write_text("x", encoding="utf-8")
        real_stat = os.stat

        def fake_stat(path, *a, **k):
            if str(path).startswith("/certs/"):
                raise PermissionError(13, "verweigert")
            return real_stat(path, *a, **k)
        with mock.patch.object(chrony.os, "stat", side_effect=fake_stat):
            self.assertTrue(chrony._file_state("/certs/nts.crt", copy))
            self.assertFalse(chrony._file_state("/certs/nts.crt", os.path.join(tmp, "fehlt")))
        self.assertFalse(chrony._file_state(os.path.join(tmp, "gibt-es-nicht"), copy))


class NtsKeyCopyTest(unittest.TestCase):
    def test_key_copy_owner_only(self):
        import confgen
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        key = os.path.join(tmp, "server.key")
        crt = os.path.join(tmp, "server.crt")
        confgen._install_private(key, b"geheim", None, secret=True)
        confgen._install_private(crt, b"oeffentlich", None)
        self.assertEqual(stat.S_IMODE(os.stat(key).st_mode), 0o400)
        self.assertEqual(stat.S_IMODE(os.stat(crt).st_mode), 0o640)


if __name__ == "__main__":
    unittest.main()
