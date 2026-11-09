"""Fremde Texte (Fehlermeldungen aus dem Netz, Antworten von Servern) für Anzeige und Protokoll säubern.

Warum: Ein Server, der etwas anderes spricht als erwartet, liefert statt einer Statuszeile rohe Bytes
(z. B. einen HTTP/2-Rahmen „\\x00\\x00\\x06\\x04…“). str(exc) trägt sie unverändert weiter – in Ereignisse,
Hinweise, Benachrichtigungen und die Oberfläche. Steuerzeichen haben dort nichts verloren (Terminal-Escapes
im Log, unsichtbare Richtungszeichen in der Anzeige), und ein langer Fehlertext sprengt jede Zeile.

clean() macht daraus eine einzeilige, druckbare und begrenzte Zeichenkette. Nur Standardbibliothek, ohne
Seiteneffekte beim Import (dnsfwd nutzt es außerhalb des Webservers).
"""

from __future__ import annotations

from typing import Any

REPLACEMENT = "�"   # „�“ steht für eine Folge nicht druckbarer Zeichen
BINARY_TEXT = "unlesbare Antwort (Binärdaten)"
ELLIPSIS = "…"


def clean(text: Any, limit: int = 300, keep_newlines: bool = False) -> str:
    """Nur druckbare Zeichen, höchstens limit Zeichen (0 = ohne Grenze), einzeilig mit zusammengefasstem
    Leerraum – mit keep_newlines bleiben Zeilenumbrüche, Tabs und Leerzeichen, wie sie sind. Anderer Leerraum
    wird zu einem Leerzeichen, jede Folge sonstiger nicht druckbarer Zeichen (Steuerzeichen, Richtungszeichen,
    Bytes eines Binärprotokolls) zu einem „�“. Besteht ein Text überwiegend aus solchen Zeichen, ist er kein
    Text: dann ein fester Hinweis statt Zeichensalat."""
    raw = "" if text is None else str(text)
    out: list[str] = []
    bad = 0
    for ch in raw:
        if ch == " " or ch.isprintable():
            out.append(ch)
        elif keep_newlines and ch in "\n\t":
            out.append(ch)
        elif ch.isspace():
            out.append(" ")
        else:
            bad += 1
            if not out or out[-1] != REPLACEMENT:
                out.append(REPLACEMENT)
    if bad >= 4 and bad * 4 >= len(raw):
        return BINARY_TEXT
    result = "".join(out)
    if not keep_newlines:
        result = " ".join(result.split())
    if limit and len(result) > limit:
        result = result[:max(1, limit - 1)].rstrip() + ELLIPSIS
    return result


def clean_tree(value: Any, limit: int = 0, depth: int = 0) -> Any:
    """Alle Zeichenketten in einer JSON-artigen Struktur säubern (Zeilenumbrüche bleiben erhalten; limit 0 =
    ohne Kürzung – die Größe begrenzt der Aufrufer);
    Schlüssel werden nur von Steuerzeichen befreit. Andere Werte bleiben, wie sie sind."""
    if isinstance(value, str):
        return clean(value, limit, keep_newlines=True)
    if depth > 20:
        return value
    if isinstance(value, dict):
        return {(clean(k, 200) if isinstance(k, str) else k): clean_tree(v, limit, depth + 1)
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_tree(v, limit, depth + 1) for v in value]
    return value
