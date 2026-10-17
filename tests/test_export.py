"""Tests for analysis export helpers and the export service."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.energy_sharing.archive import (
    ArchiveInterval,
    ArchiveLoadSnapshot,
)
from custom_components.energy_sharing.const import (
    PERIOD_CUSTOM,
    PERIOD_LAST_MONTH,
    SERVICE_EXPORT_ANALYSIS_PACK,
)
from custom_components.energy_sharing.export import (
    build_active_load_rows,
    build_energy_rows,
    build_settlement_rows,
    daily_energy_from_intervals,
    merge_archive_and_recorder,
    render_csv,
    resolve_export_period,
    write_export_pack,
)


def _row(
    end: datetime,
    *,
    export: float = 1.0,
    imported: float = 0.2,
    shared: float = 0.1,
    unused: float = 0.0,
    source: str = "settlement",
    loads: list[ArchiveLoadSnapshot] | None = None,
) -> ArchiveInterval:
    start = end - timedelta(minutes=15)
    return ArchiveInterval(
        interval_id=f"{start.isoformat()}|{end.isoformat()}",
        interval_start=start,
        interval_end=end,
        provider_export_kwh=export,
        receiver_import_kwh=imported,
        shared_energy_kwh=shared,
        unused_shared_kwh=unused,
        used_shared_kwh=min(shared, imported),
        fixed_allocation_percentage=7.0,
        active_load_kwh=0.15 if loads else 0.0,
        mopped_wh=150.0 if loads else None,
        loads=loads or [],
        source=source,
    )


def test_resolve_last_month_and_custom() -> None:
    tz = dt_util.get_time_zone("Europe/Ljubljana")
    now = datetime(2026, 10, 10, 9, 0, tzinfo=tz)
    last_month = resolve_export_period(PERIOD_LAST_MONTH, None, None, now)
    assert last_month.start == datetime(2026, 9, 1, 0, 0, tzinfo=tz)
    assert last_month.end == datetime(2026, 10, 1, 0, 0, tzinfo=tz)

    custom = resolve_export_period(
        PERIOD_CUSTOM,
        datetime(2026, 9, 1, 0, 0, tzinfo=tz),
        datetime(2026, 9, 15, 0, 0, tzinfo=tz),
        now,
    )
    assert custom.start.day == 1
    assert custom.end.day == 15

    with pytest.raises(HomeAssistantError):
        resolve_export_period(PERIOD_CUSTOM, None, None, now)


def test_settlement_and_energy_csv_contents() -> None:
    tz = dt_util.get_time_zone("Europe/Ljubljana")
    september = [
        _row(datetime(2026, 9, 1, 12, 15, tzinfo=tz), export=2.0, shared=0.2),
        _row(datetime(2026, 9, 2, 12, 15, tzinfo=tz), export=3.0, shared=0.3),
    ]
    january = [_row(datetime(2026, 1, 15, 12, 15, tzinfo=tz), export=5.0, shared=0.4)]
    settlement = build_settlement_rows(september)
    assert settlement[0]["provider_export_kwh"] == 2.0
    assert settlement[0]["unused_shared_kwh"] == 0.0

    daily = daily_energy_from_intervals(january + september, tz)
    energy = build_energy_rows(
        daily,
        datetime(2026, 9, 1, 0, 0, tzinfo=tz),
        datetime(2026, 10, 1, 0, 0, tzinfo=tz),
    )
    assert [row["date"] for row in energy] == ["2026-09-01", "2026-09-02"]
    assert energy[0]["export_after_sharing_kwh"] == pytest.approx(1.8)
    assert energy[1]["ytd_export_kwh"] == pytest.approx(10.0)
    assert energy[1]["ytd_export_after_sharing_kwh"] == pytest.approx(9.1)

    csv_text = render_csv(
        ("date", "provider_export_kwh"),
        [{"date": "2026-09-01", "provider_export_kwh": 2.0}],
        comments=("not a full reserve",),
    )
    assert csv_text.startswith("# not a full reserve")
    assert "2026-09-01,2.0" in csv_text


def test_active_loads_omitted_when_empty() -> None:
    tz = dt_util.get_time_zone("Europe/Ljubljana")
    empty = [_row(datetime(2026, 9, 1, 12, 15, tzinfo=tz))]
    assert build_active_load_rows(empty) == []
    with_load = [
        _row(
            datetime(2026, 9, 1, 12, 15, tzinfo=tz),
            loads=[
                ArchiveLoadSnapshot(
                    switch_entity_id="switch.boiler",
                    energy_wh=120.0,
                    target_wh=130.0,
                    idle_latched=True,
                )
            ],
        )
    ]
    rows = build_active_load_rows(with_load)
    assert rows[0]["idle_latched"] == "true"
    assert rows[0]["energy_wh"] == 120.0


def test_merge_fills_recorder_gaps() -> None:
    tz = dt_util.get_time_zone("Europe/Ljubljana")
    archive_end = datetime(2026, 9, 1, 12, 15, tzinfo=tz)
    recorder_end = datetime(2026, 9, 1, 12, 30, tzinfo=tz)
    merged = merge_archive_and_recorder(
        [_row(archive_end, export=2.0, source="settlement")],
        [
            _row(archive_end, export=9.0, source="recorder"),
            _row(recorder_end, export=1.5, source="recorder"),
        ],
    )
    assert len(merged) == 2
    by_export = {row.provider_export_kwh: row.source for row in merged}
    assert by_export[2.0] == "settlement"
    assert by_export[1.5] == "recorder"


def test_merge_prefers_archive() -> None:
    tz = dt_util.get_time_zone("Europe/Ljubljana")
    end = datetime(2026, 9, 1, 12, 15, tzinfo=tz)
    archive = [_row(end, export=2.0, source="settlement")]
    recorder = [_row(end, export=9.0, source="recorder")]
    merged = merge_archive_and_recorder(archive, recorder)
    assert len(merged) == 1
    assert merged[0].provider_export_kwh == 2.0
    assert merged[0].source == "settlement"


def test_write_export_pack_creates_zip(tmp_path: Path) -> None:
    folder, zip_path = write_export_pack(
        tmp_path, stamp="20261010T090000", files={"manifest.txt": "ok\n"}
    )
    assert (folder / "manifest.txt").read_text(encoding="utf-8") == "ok\n"
    assert zip_path.is_file()


async def test_export_service_writes_files(
    hass: HomeAssistant,
    setup_export_and_percentage: MockConfigEntry,
    tmp_path: Path,
) -> None:
    manager = setup_export_and_percentage.runtime_data.manager
    tz = dt_util.get_time_zone("Europe/Ljubljana")
    manager.archive.intervals = [
        _row(
            datetime(2026, 9, 2, 12, 15, tzinfo=tz),
            export=2.0,
            imported=0.3,
            shared=0.2,
        )
    ]
    assert hass.services.has_service("energy_sharing", SERVICE_EXPORT_ANALYSIS_PACK)
    with (
        patch(
            "custom_components.energy_sharing.manager.resolve_export_directory",
            return_value=tmp_path,
        ),
        patch(
            "custom_components.energy_sharing.manager.dt_util.now",
            return_value=datetime(2026, 10, 10, 9, 0, tzinfo=tz),
        ),
    ):
        payload = await manager.async_export_analysis_pack(period=PERIOD_LAST_MONTH)
    assert payload["settlement_rows"] == 1
    assert payload["energy_rows"] == 1
    assert payload["active_loads_included"] is False
    assert payload["target_month"] == "2026-11"
    folder = Path(payload["folder"])
    assert (folder / "settlement_intervals.csv").is_file()
    assert (folder / "energy.csv").is_file()
    assert (folder / "next_month_share.csv").is_file()
    assert not (folder / "active_loads.csv").exists()
    energy_text = (folder / "energy.csv").read_text(encoding="utf-8")
    assert "not a full EZ-1" in energy_text
