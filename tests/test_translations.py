"""Tests for translation files and input documentation."""

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
        ("config", "error", "duplicate_sources"),
        ("options", "step", "init", "title"),
        ("entity", "sensor", "provider_export_last_interval", "name"),
        ("entity", "sensor", "calculated_allocated_last_interval", "name"),
        ("services", "process_now", "name"),
        ("status", "ready"),
        ("status", "reconciliation_mismatch"),
    ]

    for translation in (strings, en, sl):
        for path in required_paths:
            node = translation
            for key in path:
                assert key in node, f"Missing {'.'.join(path)} in translation file"
                node = node[key]


def test_input_documentation_contains_required_source_descriptions() -> None:
    """Test input documentation contains all required source descriptions."""
    readme = Path("README.md").read_text(encoding="utf-8")
    input_doc = Path("docs/INPUT_ENTITIES.md").read_text(encoding="utf-8")
    combined = readme + input_doc

    required_phrases = [
        "Input entities",
        "Provider export interval source",
        "Receiver grid import interval source",
        "Allocation percentage",
        "Optional reported allocated energy",
        "last_period",
        "last_reset",
        "Wh",
        "kWh",
        "7%",
        "15-minute interval",
        "MQTT",
        "sensor.trata_solaredge_oddaja_v_omrezje_15min",
        "sensor.hodnik_elektro_stevec_prevzem_iz_omrezja_15min",
        "input_number.trenutni_odstotek_souporabe",
        "sensor.trata_solaredge_gn_souporaba_15min",
        "Developer Tools",
    ]

    for phrase in required_phrases:
        assert phrase in combined, f"Missing documentation phrase: {phrase}"
