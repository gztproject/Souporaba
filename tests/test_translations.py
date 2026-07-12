"""Tests for translation files and input documentation."""

from __future__ import annotations

import json
from pathlib import Path


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_translation_files_contain_required_keys() -> None:
    base = Path("custom_components/energy_sharing")
    strings = _load_json(base / "strings.json")
    en = _load_json(base / "translations" / "en.json")
    sl = _load_json(base / "translations" / "sl.json")

    required_paths = [
        ("config", "step", "user", "title"),
        ("config", "error", "percentage_or_export_required"),
        ("entity", "sensor", "receiver_import_last_interval", "name"),
        ("entity", "sensor", "processing_status", "name"),
        ("services", "reinitialize_baseline", "name"),
        ("status", "initializing_baseline"),
    ]

    for translation in (strings, en, sl):
        for path in required_paths:
            node = translation
            for key in path:
                assert key in node, f"Missing {'.'.join(path)}"
                node = node[key]


def test_documentation_no_utility_meter_requirement() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    input_doc = Path("docs/INPUT_ENTITIES.md").read_text(encoding="utf-8")
    combined = readme + input_doc

    assert "no longer requires Utility Meter" in combined or (
        "no longer require" in combined and "Utility Meter" in combined
    )
    assert "cumulative" in combined.lower()
    assert "receiver_import_total_source" in combined or (
        "Receiver total grid import" in combined
    )
    assert "Percentage-only" in combined or "percentage-only" in combined.lower()
    assert (
        "Export + percentage" in combined
        or "export plus percentage" in combined.lower()
    )
    assert "must expose `last_period`" not in input_doc
    assert "must expose `last_reset`" not in input_doc

    required_phrases = [
        "shared_energy_total_source",
        "provider_export_total_source",
        "fixed_allocation_percentage",
        "initializing_baseline",
        "counter reset",
    ]
    for phrase in required_phrases:
        assert phrase in combined or phrase.replace("_", " ") in combined
