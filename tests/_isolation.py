"""Testsuite vom Host trennen – vor jedem Import aus app/ laden.

Die App liest ihre Pfade beim Import aus der Umgebung (settings.DATA_DIR, server.RUN_DIR,
CHRONY_CONF …) und fällt sonst auf die echten Host-Pfade zurück: /var/lib/chrony/ntp-gui,
/run/ntp-gui, /etc/chrony/chrony.conf. Tests, die diese nicht selbst umlenken, lasen dann
eine settings.json des Hosts (GUI-Werte schlagen Umgebungswerte) oder legten als root eine
echte Datenbank an. Hier zeigen alle diese Pfade in ein eigenes, leeres Temp-Verzeichnis.

Bewusst gesetzt, nicht setdefault: Auch Werte aus der Shell des Entwicklers sollen nicht
mitspielen. Tests, die eigene Pfade brauchen, patchen sie wie bisher selbst.
"""

import atexit
import os
import shutil
import tempfile

ROOT = tempfile.mkdtemp(prefix="ntpgui-tests-")
atexit.register(shutil.rmtree, ROOT, ignore_errors=True)

PATHS = {
    "NTPGUI_DATA_DIR": os.path.join(ROOT, "data"),
    "NTPGUI_RUN_DIR": os.path.join(ROOT, "run"),
    "CHRONY_CONF": os.path.join(ROOT, "etc", "chrony.conf"),       # fehlt absichtlich
    "PTP4L_CONF": os.path.join(ROOT, "etc", "ptp4l.conf"),         # fehlt absichtlich
    "NTPGUI_NTS_CERT_DIR": os.path.join(ROOT, "nts-certs"),
}
os.environ.update(PATHS)
