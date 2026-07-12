"""Tests for translation files."""

from __future__ import annotations

import json
from pathlib import Path


def _load_json(path: Path) -> dict:
    """Load a JSON file."""
    return json.loads(path.read_text(encoding="utf-8"))


def test_translation_files_contain_required_keys() -> None:
    """Test English and Slovenian translation files contain required keys."""
    base = Path("custom_components/energy_sharing")
    strings = _load_json(base / "strings.json")
    en = _load_json(base / "translations" / "en.json")
    sl = _load_json(base / "translations" / "sl.json")

    required_paths = [
        ("config", "step", "user", "title"),
        ("config", "error", "duplicate_entities"),
        ("options", "step", "init", "title"),
        ("entity", "sensor", "imported_last_interval", "name"),
        ("services", "process_now", "name"),
        ("status", "ready"),
    ]

    for translation in (strings, en, sl):
        for path in required_paths:
            node = translation
            for key in path:
                assert key in node, f"Missing {'.'.join(path)} in translation file"
                node = node[key]

    assert en["entity"]["sensor"]["imported_last_interval"]["name"]
    assert sl["entity"]["sensor"]["imported_last_interval"]["name"]
