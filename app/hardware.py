"""Hardware-Check: Was kann diese Hardware von dem, was ntp-gui kann? (Platzhalter)"""

from __future__ import annotations

from typing import Any


def report(cfg: dict, refresh: bool = False) -> dict[str, Any]:
    return {"matrix": [], "warnings": []}


def cached_insights(cfg: dict) -> list[dict[str, Any]]:
    return []
