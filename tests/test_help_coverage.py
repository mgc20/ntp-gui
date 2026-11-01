"""Mechanische Prüfung der ⓘ-Erklärungen im Dashboard.

1. Jeder Hilfe-Schlüssel, den eine Seite benutzt (info("…"), help: "…", dritte
   Spalte einer kv-Zeile, Tabellenköpfe mit `help`-Spalte), steht in HELP
   (help.js + help-hardware.js). Ein fehlender Schlüssel fällt im Browser nicht
   auf – info() liefert dann einfach keinen Knopf.
2. Jeder HELP-Schlüssel erscheint auf der Hilfe-Seite (HELP_GROUPS bzw.
   HELP_GROUP_HARDWARE), sonst führt „In der Hilfe ansehen“ ins Leere.
3. Jede kv-Zeile und jede Kachel auf den Seiten hat eine Erklärung.

Kein Node nötig: Der JS-Text wird mit einem kleinen Scanner gelesen, der
Strings, Template-Literale und Kommentare überspringt.
"""

import re
import unittest
from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "app" / "static" / "js"
PAGES = sorted((JS / "pages").glob("*.js"))
HELP_FILES = [JS / "help.js", JS / "help-hardware.js"]

# HELP-Schlüssel, die absichtlich nicht auf der Hilfe-Seite stehen (Schlüssel: Grund).
NOT_IN_GROUPS: dict[str, str] = {}

# kv-Zeilen/Kacheln ohne ⓘ, die so gewollt sind ("datei.js:Beschriftung": Grund).
NO_HELP_OK: dict[str, str] = {
    "sources.js:Zustand": "Der Zustands-Badge im Wert bringt sein eigenes ⓘ für den konkreten Zustand mit.",
}

IDENT = re.compile(r"^[a-z][a-z0-9_]*$")


# --------------------------------------------------------------------------- Scanner
def _skip_string(text: str, i: int) -> int:
    """i zeigt auf ein Anführungszeichen; liefert den Index hinter dem String."""
    quote = text[i]
    i += 1
    while i < len(text):
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if quote == "`" and text.startswith("${", i):
            i = _match(text, i + 1)
            continue
        if c == quote:
            return i + 1
        i += 1
    return i


def _skip_comment(text: str, i: int) -> int:
    if text.startswith("//", i):
        end = text.find("\n", i)
        return len(text) if end < 0 else end
    end = text.find("*/", i + 2)
    return len(text) if end < 0 else end + 2


def _is_comment(text: str, i: int) -> bool:
    return text.startswith("//", i) or text.startswith("/*", i)


def _match(text: str, i: int) -> int:
    """i zeigt auf ( [ oder {; liefert den Index der passenden schließenden Klammer."""
    pairs = {"(": ")", "[": "]", "{": "}"}
    stack = [pairs[text[i]]]
    i += 1
    while i < len(text) and stack:
        c = text[i]
        if c in "\"'`":
            i = _skip_string(text, i)
            continue
        if c == "/" and _is_comment(text, i):
            i = _skip_comment(text, i)
            continue
        if c in pairs:
            stack.append(pairs[c])
        elif stack and c == stack[-1]:
            stack.pop()
            if not stack:
                return i
        i += 1
    return i


def _split_top(text: str) -> list[str]:
    """Teilt den Inhalt einer Klammer an Kommas der obersten Ebene."""
    parts, depth, start, i = [], 0, 0, 0
    while i < len(text):
        c = text[i]
        if c in "\"'`":
            i = _skip_string(text, i)
            continue
        if c == "/" and _is_comment(text, i):
            i = _skip_comment(text, i)
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == "," and depth == 0:
            parts.append(text[start:i])
            start = i + 1
        i += 1
    if text[start:].strip():
        parts.append(text[start:])
    return [p.strip() for p in parts]


def _expression(text: str, i: int) -> str:
    """Ausdruck ab i bis zum nächsten Komma bzw. zur schließenden Klammer der Ebene."""
    start, depth = i, 0
    while i < len(text):
        c = text[i]
        if c in "\"'`":
            i = _skip_string(text, i)
            continue
        if c == "/" and _is_comment(text, i):
            i = _skip_comment(text, i)
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            if depth == 0:
                break
            depth -= 1
        elif c == "," and depth == 0:
            break
        i += 1
    return text[start:i]


def _literals(expr: str) -> list[str]:
    """Alle einfachen String-Literale eines Ausdrucks (deckt `a ? "x" : "y"` ab)."""
    return [m.group(2) for m in re.finditer(r"([\"'])([^\"'\\\n]*)\1", expr)]


def _calls(text: str, name: str):
    """Liefert (Zeile, Argumenttext) für jeden Aufruf name(…)."""
    for match in re.finditer(r"(?<![\w.])" + re.escape(name) + r"\(", text):
        start = match.end() - 1
        end = _match(text, start)
        yield text.count("\n", 0, start) + 1, text[start + 1:end]


def _object_entries(body: str) -> dict[str, str]:
    out = {}
    for part in _split_top(body):
        part = re.sub(r"^(?:\s*(?://[^\n]*|/\*.*?\*/))*", "", part, flags=re.S).strip()
        key, sep, value = part.partition(":")
        key = key.strip().strip("\"'")
        if sep and IDENT.match(key):
            out[key] = value.strip()
    return out


def _const(text: str, name: str, opener: str) -> str | None:
    match = re.search(r"\b(?:export\s+)?const\s+" + re.escape(name) + r"\s*=\s*" + re.escape(opener), text)
    if not match:
        return None
    start = match.end() - 1
    return text[start + 1:_match(text, start)]


# --------------------------------------------------------------------------- HELP
def help_keys() -> set[str]:
    keys = set()
    for path in HELP_FILES:
        text = path.read_text(encoding="utf-8")
        for name in ("HELP", "HELP_HARDWARE"):
            body = _const(text, name, "{")
            if body is not None:
                keys.update(_object_entries(body))
    return keys


def group_keys() -> set[str]:
    keys = set()
    for path in HELP_FILES:
        text = path.read_text(encoding="utf-8")
        for name, opener in (("HELP_GROUPS", "["), ("HELP_GROUP_HARDWARE", "{")):
            body = _const(text, name, opener)
            if body is None:
                continue
            for match in re.finditer(r"\bkeys\s*:\s*\[", body):
                start = match.end() - 1
                keys.update(_literals(body[start:_match(body, start)]))
    return keys


def select_state_help_values() -> list[str]:
    body = _const((JS / "help.js").read_text(encoding="utf-8"), "SELECT_STATE_HELP", "{") or ""
    return [v for value in _object_entries(body).values() for v in _literals(value)]


# --------------------------------------------------------------------------- Seiten
def _kv_rows(text: str):
    """(Zeile, Beschriftung, Hilfe-Ausdruck oder None) je kv-Zeile."""
    for line, args in _calls(text, "kv"):
        args = args.strip()
        if not args.startswith("["):
            continue
        for row in _split_top(args[1:_match(args, 0)]):
            if not row.startswith("["):
                continue
            items = _split_top(row[1:_match(row, 0)])
            label = (_literals(items[0]) or [items[0]])[0] if items else "?"
            yield line, label, items[2] if len(items) >= 3 else None


def _tiles(text: str):
    for line, args in _calls(text, "tile"):
        args = args.strip()
        if not args.startswith("{"):
            continue
        entries = _object_entries(args[1:_match(args, 0)])
        label = (_literals(entries.get("label", "")) or ["?"])[0]
        yield line, label, entries.get("help")


def _help_columns(text: str):
    """Tupel-Listen, deren Elemente per `.map(([…, help …]) =>` als ⓘ-Schlüssel dienen."""
    for match in re.finditer(r"\.map\(\(\[([^\]]*)\]\)", text):
        params = [p.strip() for p in match.group(1).split(",")]
        if "help" not in params:
            continue
        index = params.index("help")
        before = text[:match.start()].rstrip()
        body = None
        if before.endswith("]"):
            # Inline-Array: zur passenden öffnenden Klammer zurückgehen.
            depth, i = 0, len(before) - 1
            while i >= 0:
                if before[i] == "]":
                    depth += 1
                elif before[i] == "[":
                    depth -= 1
                    if depth == 0:
                        break
                i -= 1
            body = before[i + 1:-1]
        else:
            ident = re.search(r"(\w+)$", before)
            if ident:
                body = _const(text, ident.group(1), "[")
        if body is None:
            continue
        for row in _split_top(body):
            if row.startswith("["):
                items = _split_top(row[1:_match(row, 0)])
                if len(items) > index:
                    yield text.count("\n", 0, match.start()) + 1, items[index]


def _destructured_tables(text: str):
    """`const [a, b, help] = NAME[…]` → dritte Spalte jedes Eintrags von NAME."""
    for match in re.finditer(r"const\s*\[([^\]]*)\]\s*=\s*(\w+)\[", text):
        params = [p.strip() for p in match.group(1).split(",")]
        if "help" not in params:
            continue
        body = _const(text, match.group(2), "{")
        if body is None:
            continue
        index = params.index("help")
        for value in _object_entries(body).values():
            if value.startswith("["):
                items = _split_top(value[1:_match(value, 0)])
                if len(items) > index:
                    yield text.count("\n", 0, match.start()) + 1, items[index]


def used_keys():
    """(Datei, Zeile, Schlüssel) für jede statisch erkennbare Verwendung."""
    found = []
    for path in PAGES + [JS / "ui.js"]:
        text = path.read_text(encoding="utf-8")
        name = path.name
        for line, args in _calls(text, "info"):
            first = _split_top(args)[0] if args.strip() else ""
            found += [(name, line, key) for key in _literals(first)]
        for match in re.finditer(r"\bhelp\s*:\s*", text):
            line = text.count("\n", 0, match.start()) + 1
            found += [(name, line, key) for key in _literals(_expression(text, match.end()))]
        for line, _label, expr in _kv_rows(text):
            if expr:
                found += [(name, line, key) for key in _literals(expr)]
        for line, expr in list(_help_columns(text)) + list(_destructured_tables(text)):
            found += [(name, line, key) for key in _literals(expr)]
    # FIELD_HELP in settings.js: Feldschlüssel → Hilfe-Schlüssel.
    text = (JS / "pages" / "settings.js").read_text(encoding="utf-8")
    body = _const(text, "FIELD_HELP", "{")
    if body:
        for value in _object_entries(body).values():
            found += [("settings.js", 0, key) for key in _literals(value)]
    return [(f, l, k) for f, l, k in found if IDENT.match(k)]


class HelpCoverageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.help = help_keys()
        cls.groups = group_keys()

    def test_parser_sees_help(self):
        # Schutz gegen einen Scanner, der still nichts findet.
        self.assertGreater(len(self.help), 100)
        for key in ("stratum", "select_reason", "nts_server", "hw_check"):
            self.assertIn(key, self.help)
        uses = {k for _f, _l, k in used_keys()}
        for key in ("system_offset", "rms_offset", "select_reason", "client_address", "last_rx"):
            self.assertIn(key, uses)

    def test_used_keys_exist(self):
        missing = sorted({f"{f}:{l} → {k}" for f, l, k in used_keys() if k not in self.help})
        self.assertEqual(missing, [], "Hilfe-Schlüssel ohne Eintrag in HELP")

    def test_select_state_help_exists(self):
        missing = [k for k in select_state_help_values() if k not in self.help]
        self.assertEqual(missing, [])

    def test_every_help_key_on_help_page(self):
        orphans = sorted(self.help - self.groups - set(NOT_IN_GROUPS))
        self.assertEqual(orphans, [], "HELP-Schlüssel fehlen in HELP_GROUPS")
        unknown = sorted(self.groups - self.help)
        self.assertEqual(unknown, [], "HELP_GROUPS nennt Schlüssel ohne Eintrag")

    def test_every_value_has_help(self):
        bare = []
        for path in PAGES:
            text = path.read_text(encoding="utf-8")
            rows = [(l, lab, e) for l, lab, e in _kv_rows(text)] + list(_tiles(text))
            for line, label, expr in rows:
                if expr is None or expr in {"null", "undefined", '""'}:
                    if f"{path.name}:{label}" not in NO_HELP_OK:
                        bare.append(f"{path.name}:{line} „{label}“")
        self.assertEqual(bare, [], "Werte ohne ⓘ-Erklärung")


if __name__ == "__main__":
    unittest.main()
