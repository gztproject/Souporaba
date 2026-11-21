"""Authorization tests for Energy Sharing service actions.

These tests exercise the HTTP and websocket service APIs. They fail while
process, reset, rebaseline, calibrate, and export run for any signed-in user
and while calibration actuates switches with a blank context.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import voluptuous as vol
from homeassistant.auth.const import GROUP_ID_USER
from homeassistant.const import ATTR_DOMAIN, ATTR_SERVICE, EVENT_CALL_SERVICE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    CLIENT_ID,
    MockConfigEntry,
    MockToggleEntity,
    MockUser,
    async_capture_events,
    setup_test_component_platform,
)

from custom_components.energy_sharing.const import (
    CONF_ACTIVE_LOAD_ENABLED,
    CONF_ACTIVE_LOAD_MIN_OFF_SECONDS,
    CONF_ACTIVE_LOAD_MIN_ON_SECONDS,
    CONF_ACTIVE_LOAD_POWER_SENSOR_ENTITY_ID,
    CONF_ACTIVE_LOAD_PRIORITY,
    CONF_ACTIVE_LOAD_STARTUP_GRACE_SECONDS,
    CONF_ACTIVE_LOAD_SWITCH_ENTITY_ID,
    CONF_ACTIVE_LOADS,
    CONF_EXPORT_PERIOD,
    CONF_FIXED_ALLOCATION_PERCENTAGE,
    CONF_INTERVAL_MINUTES,
    CONF_MAX_WAIT,
    CONF_PROCESSING_DELAY,
    CONF_RETRY_INTERVAL,
    CONF_SOURCE_FRESHNESS_TOLERANCE,
    CONFIG_ENTRY_VERSION,
    DEFAULT_FIXED_ALLOCATION_PERCENTAGE,
    DEFAULT_INTERVAL_MINUTES,
    DEFAULT_MAX_WAIT,
    DEFAULT_PROCESSING_DELAY,
    DEFAULT_RETRY_INTERVAL,
    DEFAULT_SOURCE_FRESHNESS_TOLERANCE,
    DOMAIN,
    PERIOD_LAST_MONTH,
    SERVICE_CALIBRATE_LOADS,
    SERVICE_CONFIRM,
    SERVICE_EXPORT_ANALYSIS_PACK,
    SERVICE_PROCESS_NOW,
    SERVICE_REINITIALIZE_BASELINE,
    SERVICE_RESET_TOTALS,
)
from tests.conftest import set_cumulative_sources

SWITCH_ENTITY = "switch.boiler_contactor"
POWER_ENTITY = "sensor.boiler_power"
RECEIVER_A = "sensor.house_a_import"
SHARED_A = "sensor.house_a_shared"
RECEIVER_B = "sensor.house_b_import"
SHARED_B = "sensor.house_b_shared"


@dataclass(slots=True)
class ServiceAttempt:
    """Result of the same service call over HTTP and the websocket."""

    http_status: int
    ws_success: bool
    http_body: Any
    ws_message: dict[str, Any]


def _options(*, with_loads: bool) -> dict[str, Any]:
    options: dict[str, Any] = {
        CONF_FIXED_ALLOCATION_PERCENTAGE: DEFAULT_FIXED_ALLOCATION_PERCENTAGE,
        CONF_INTERVAL_MINUTES: DEFAULT_INTERVAL_MINUTES,
        CONF_PROCESSING_DELAY: DEFAULT_PROCESSING_DELAY,
        CONF_MAX_WAIT: DEFAULT_MAX_WAIT,
        CONF_RETRY_INTERVAL: DEFAULT_RETRY_INTERVAL,
        CONF_SOURCE_FRESHNESS_TOLERANCE: DEFAULT_SOURCE_FRESHNESS_TOLERANCE,
    }
    if with_loads:
        options[CONF_ACTIVE_LOADS] = [
            {
                CONF_ACTIVE_LOAD_SWITCH_ENTITY_ID: SWITCH_ENTITY,
                CONF_ACTIVE_LOAD_POWER_SENSOR_ENTITY_ID: POWER_ENTITY,
                CONF_ACTIVE_LOAD_PRIORITY: 0,
                CONF_ACTIVE_LOAD_ENABLED: True,
            }
        ]
        options[CONF_ACTIVE_LOAD_STARTUP_GRACE_SECONDS] = 0
        options[CONF_ACTIVE_LOAD_MIN_ON_SECONDS] = 0
        options[CONF_ACTIVE_LOAD_MIN_OFF_SECONDS] = 0
    return options


def _make_entry(
    *,
    title: str,
    receiver: str,
    shared: str,
    with_loads: bool,
) -> MockConfigEntry:
    return MockConfigEntry(
        version=CONFIG_ENTRY_VERSION,
        domain=DOMAIN,
        title=title,
        data={
            "receiver_import_total_source": receiver,
            "shared_energy_total_source": shared,
        },
        options=_options(with_loads=with_loads),
        unique_id=f"{receiver}|{shared}",
    )


async def _setup_api(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, "http", {})
    assert await async_setup_component(hass, "api", {})
    assert await async_setup_component(hass, "websocket_api", {})
    await hass.async_block_till_done()


async def _setup_switch(hass: HomeAssistant) -> MockToggleEntity:
    switch = MockToggleEntity("Boiler contactor", "off")
    switch.entity_id = SWITCH_ENTITY
    setup_test_component_platform(hass, "switch", [switch])
    assert await async_setup_component(hass, "switch", {"switch": {"platform": "test"}})
    await hass.async_block_till_done()
    state = hass.states.get(SWITCH_ENTITY)
    assert state is not None
    assert state.state == "off"
    return switch


async def _setup_entry(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    *,
    receiver: str,
    shared: str,
    receiver_total: float,
    shared_total: float,
) -> MockConfigEntry:
    set_cumulative_sources(
        hass,
        receiver_import_total_entity=receiver,
        shared_energy_total_entity=shared,
        receiver_total=receiver_total,
        shared_total=shared_total,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _device_id(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    assert device is not None
    return device.id


def _export_root(tmp_path: Path) -> Path:
    return tmp_path / "energy_sharing"


async def _token_for_user(hass: HomeAssistant, user: MockUser) -> str:
    refresh = await hass.auth.async_create_refresh_token(user, CLIENT_ID)
    return hass.auth.async_create_access_token(refresh)


async def _attempt(
    hass: HomeAssistant,
    hass_client: Callable[..., Awaitable[Any]],
    hass_ws_client: Callable[..., Awaitable[Any]],
    token: str,
    service: str,
    payload: dict[str, Any] | None,
    *,
    return_response: bool = False,
) -> ServiceAttempt:
    """Call a service the way the REST API and the websocket command do."""
    client = await hass_client(token)
    query = "?return_response" if return_response else ""
    url = f"/api/services/{DOMAIN}/{service}{query}"
    if payload is None:
        response = await client.post(url)
    else:
        response = await client.post(url, json=payload)
    raw = await response.text()
    try:
        http_body: Any = json.loads(raw) if raw else None
    except ValueError:
        http_body = raw

    websocket = await hass_ws_client(hass, token)
    message: dict[str, Any] = {
        "type": "call_service",
        "domain": DOMAIN,
        "service": service,
        "return_response": return_response,
    }
    if payload:
        data = dict(payload)
        device_id = data.pop("device_id", None)
        if data:
            message["service_data"] = data
        if device_id is not None:
            message["target"] = {"device_id": device_id}
    await websocket.send_json_auto_id(message)
    ws_message = await websocket.receive_json()
    return ServiceAttempt(
        http_status=response.status,
        ws_success=bool(ws_message.get("success")),
        http_body=http_body,
        ws_message=ws_message,
    )


def _switch_calls(events: list[Any], service: str) -> list[Any]:
    return [
        event
        for event in events
        if event.data.get(ATTR_DOMAIN) == "switch"
        and event.data.get(ATTR_SERVICE) == service
    ]


async def _prepare_houses(
    hass: HomeAssistant,
    *,
    with_loads: bool = False,
) -> tuple[MockConfigEntry, MockConfigEntry, MockToggleEntity]:
    await _setup_api(hass)
    switch = await _setup_switch(hass)
    hass.states.async_set(
        POWER_ENTITY,
        "1450",
        attributes={"unit_of_measurement": "W", "device_class": "power"},
    )
    house_a = await _setup_entry(
        hass,
        _make_entry(
            title="House A",
            receiver=RECEIVER_A,
            shared=SHARED_A,
            with_loads=with_loads,
        ),
        receiver=RECEIVER_A,
        shared=SHARED_A,
        receiver_total=100.0,
        shared_total=10.0,
    )
    house_b = await _setup_entry(
        hass,
        _make_entry(
            title="House B",
            receiver=RECEIVER_B,
            shared=SHARED_B,
            with_loads=False,
        ),
        receiver=RECEIVER_B,
        shared=SHARED_B,
        receiver_total=80.0,
        shared_total=8.0,
    )
    house_a.runtime_data.manager.data.cumulative_unused = 9.5
    house_a.runtime_data.manager.data.cumulative_shared_energy = 3.25
    house_b.runtime_data.manager.data.cumulative_unused = 4.5
    house_b.runtime_data.manager.data.cumulative_shared_energy = 1.75
    return house_a, house_b, switch


def _payload(
    service: str,
    device_id: str | None,
) -> dict[str, Any] | None:
    if service == SERVICE_CALIBRATE_LOADS and device_id is None:
        return None
    payload: dict[str, Any] = {}
    if service == SERVICE_RESET_TOTALS:
        payload[SERVICE_CONFIRM] = True
    if service == SERVICE_EXPORT_ANALYSIS_PACK:
        payload[CONF_EXPORT_PERIOD] = PERIOD_LAST_MONTH
    if device_id is not None:
        payload["device_id"] = device_id
    return payload


def _unchanged(house_a: MockConfigEntry, house_b: MockConfigEntry) -> bool:
    return (
        house_a.runtime_data.manager.data.cumulative_unused == 9.5
        and house_a.runtime_data.manager.data.cumulative_shared_energy == 3.25
        and house_a.runtime_data.manager.data.baseline_initialization_count == 0
        and house_b.runtime_data.manager.data.cumulative_unused == 4.5
        and house_b.runtime_data.manager.data.cumulative_shared_energy == 1.75
        and house_b.runtime_data.manager.data.baseline_initialization_count == 0
    )


@pytest.fixture(scope="session", autouse=True)
def _pycares_shutdown_thread_started() -> None:
    """Start the c-ares shutdown thread before Home Assistant records threads.

    A denied HTTP call resolves the client address and constructs a resolver.
    That starts a process-lifetime daemon thread which the Home Assistant test
    harness otherwise treats as a leak.
    """
    import pycares

    pycares.Channel()


@pytest.fixture(autouse=True)
def _avoid_reverse_dns_thread() -> Any:
    """Keep the failed-login host lookup on loopback."""
    with patch(
        "homeassistant.components.http.ban.gethostbyaddr",
        return_value=("localhost", [], ["127.0.0.1"]),
    ):
        yield


@pytest.fixture
def fast_calibration() -> Any:
    with patch(
        "custom_components.energy_sharing.active_loads.asyncio.sleep",
        new=AsyncMock(),
    ):
        yield


async def test_read_only_user_cannot_turn_configured_switch_on_directly(
    hass: HomeAssistant,
    hass_client: Callable[..., Awaitable[Any]],
    hass_ws_client: Callable[..., Awaitable[Any]],
    hass_read_only_access_token: str,
) -> None:
    """A read-only token cannot call switch.turn_on itself."""
    await _setup_api(hass)
    switch = await _setup_switch(hass)
    events = async_capture_events(hass, EVENT_CALL_SERVICE)
    client = await hass_client(hass_read_only_access_token)
    response = await client.post(
        "/api/services/switch/turn_on",
        json={"entity_id": SWITCH_ENTITY},
    )
    body = await response.text()
    websocket = await hass_ws_client(hass, hass_read_only_access_token)
    await websocket.send_json_auto_id(
        {
            "type": "call_service",
            "domain": "switch",
            "service": "turn_on",
            "service_data": {"entity_id": SWITCH_ENTITY},
        }
    )
    ws_message = await websocket.receive_json()
    invoked = [
        event
        for event in events
        if event.data.get(ATTR_DOMAIN) == "switch"
        and event.data.get(ATTR_SERVICE) == "turn_on"
    ]
    assert response.status == 401, body
    assert ws_message.get("success") is False, ws_message
    assert invoked, "switch.turn_on was not invoked"
    assert hass.states.get(SWITCH_ENTITY).state == "off"  # type: ignore[union-attr]
    assert not any(call[0] == "turn_on" for call in switch.calls)


PRIVILEGED_SERVICES = (
    SERVICE_PROCESS_NOW,
    SERVICE_RESET_TOTALS,
    SERVICE_REINITIALIZE_BASELINE,
    SERVICE_CALIBRATE_LOADS,
    SERVICE_EXPORT_ANALYSIS_PACK,
)


@pytest.mark.parametrize("service", PRIVILEGED_SERVICES)
@pytest.mark.parametrize("named_device", [False, True])
async def test_read_only_services_do_not_run(
    hass: HomeAssistant,
    hass_client: Callable[..., Awaitable[Any]],
    hass_ws_client: Callable[..., Awaitable[Any]],
    hass_read_only_access_token: str,
    tmp_path: Path,
    fast_calibration: None,
    service: str,
    named_device: bool,
) -> None:
    """Every privileged service rejects a read-only caller before side effects."""
    hass.config.media_dirs = {"local": str(tmp_path)}
    house_a, house_b, switch = await _prepare_houses(hass, with_loads=True)
    device_id = _device_id(hass, house_a) if named_device else None
    events = async_capture_events(hass, EVENT_CALL_SERVICE)
    attempt = await _attempt(
        hass,
        hass_client,
        hass_ws_client,
        hass_read_only_access_token,
        service,
        _payload(service, device_id),
    )
    turn_ons = _switch_calls(events, "turn_on")
    assert attempt.http_status == 401, (
        f"{service} device={device_id} http={attempt.http_status} "
        f"ws_success={attempt.ws_success} turn_on={len(turn_ons)} "
        f"baseline={house_a.runtime_data.manager.data.baseline_initialization_count} "
        f"unused={house_a.runtime_data.manager.data.cumulative_unused} "
        f"export_exists={_export_root(tmp_path).exists()}"
    )
    assert attempt.ws_success is False
    assert _unchanged(house_a, house_b)
    assert turn_ons == []
    assert not any(call[0] == "turn_on" for call in switch.calls)
    assert not _export_root(tmp_path).exists()


async def test_non_admin_user_cannot_reset_totals(
    hass: HomeAssistant,
    hass_client: Callable[..., Awaitable[Any]],
    hass_ws_client: Callable[..., Awaitable[Any]],
    hass_read_only_user: MockUser,
) -> None:
    """A non-admin member of the users group is rejected the same way."""
    del hass_read_only_user
    group = await hass.auth.async_get_group(GROUP_ID_USER)
    assert group is not None
    user = MockUser(name="Household member", groups=[group]).add_to_hass(hass)
    assert user.is_admin is False
    token = await _token_for_user(hass, user)
    house_a, house_b, _switch = await _prepare_houses(hass)
    attempt = await _attempt(
        hass,
        hass_client,
        hass_ws_client,
        token,
        SERVICE_RESET_TOTALS,
        _payload(SERVICE_RESET_TOTALS, _device_id(hass, house_a)),
    )
    assert attempt.http_status == 401, (
        f"http={attempt.http_status} ws_success={attempt.ws_success} "
        f"unused={house_a.runtime_data.manager.data.cumulative_unused}"
    )
    assert attempt.ws_success is False
    assert _unchanged(house_a, house_b)


@pytest.mark.parametrize("service", PRIVILEGED_SERVICES)
async def test_missing_device_does_not_select_the_registering_entry(
    hass: HomeAssistant,
    hass_client: Callable[..., Awaitable[Any]],
    hass_ws_client: Callable[..., Awaitable[Any]],
    hass_access_token: str,
    tmp_path: Path,
    fast_calibration: None,
    service: str,
) -> None:
    """An admin or automation call with no device must not act on the first entry."""
    hass.config.media_dirs = {"local": str(tmp_path)}
    house_a, house_b, switch = await _prepare_houses(hass, with_loads=True)
    events = async_capture_events(hass, EVENT_CALL_SERVICE)
    attempt = await _attempt(
        hass,
        hass_client,
        hass_ws_client,
        hass_access_token,
        service,
        _payload(service, None),
    )
    assert attempt.http_status >= 400, (
        f"admin {service} http={attempt.http_status} "
        f"ws_success={attempt.ws_success} "
        f"baseline={house_a.runtime_data.manager.data.baseline_initialization_count} "
        f"unused={house_a.runtime_data.manager.data.cumulative_unused} "
        f"turn_on={len(_switch_calls(events, 'turn_on'))} "
        f"export_exists={_export_root(tmp_path).exists()}"
    )
    assert attempt.ws_success is False
    assert _unchanged(house_a, house_b)
    assert _switch_calls(events, "turn_on") == []
    assert not any(call[0] == "turn_on" for call in switch.calls)
    assert not _export_root(tmp_path).exists()

    with pytest.raises((HomeAssistantError, vol.Invalid)):
        await hass.services.async_call(
            DOMAIN,
            service,
            _payload(service, None) or {},
            blocking=True,
        )
    assert _unchanged(house_a, house_b)
    assert not _export_root(tmp_path).exists()


async def test_admin_and_automation_act_only_on_the_named_device(
    hass: HomeAssistant,
    hass_client: Callable[..., Awaitable[Any]],
    hass_ws_client: Callable[..., Awaitable[Any]],
    hass_access_token: str,
    tmp_path: Path,
    fast_calibration: None,
) -> None:
    """A device id authorizes that entry only, for an admin and for no user."""
    hass.config.media_dirs = {"local": str(tmp_path)}
    house_a, house_b, _switch = await _prepare_houses(hass, with_loads=True)
    device_b = _device_id(hass, house_b)

    attempt = await _attempt(
        hass,
        hass_client,
        hass_ws_client,
        hass_access_token,
        SERVICE_RESET_TOTALS,
        _payload(SERVICE_RESET_TOTALS, device_b),
    )
    assert attempt.http_status == 200
    assert attempt.ws_success is True
    assert house_b.runtime_data.manager.data.cumulative_unused == 0.0
    assert house_b.runtime_data.manager.data.cumulative_shared_energy == 0.0
    assert house_a.runtime_data.manager.data.cumulative_unused == 9.5
    assert house_a.runtime_data.manager.data.cumulative_shared_energy == 3.25

    house_b.runtime_data.manager.data.cumulative_unused = 4.5
    house_b.runtime_data.manager.data.cumulative_shared_energy = 1.75
    await hass.services.async_call(
        DOMAIN,
        SERVICE_RESET_TOTALS,
        _payload(SERVICE_RESET_TOTALS, device_b),
        blocking=True,
    )
    assert house_b.runtime_data.manager.data.cumulative_unused == 0.0
    assert house_a.runtime_data.manager.data.cumulative_unused == 9.5

    device_a = _device_id(hass, house_a)
    export = await _attempt(
        hass,
        hass_client,
        hass_ws_client,
        hass_access_token,
        SERVICE_EXPORT_ANALYSIS_PACK,
        _payload(SERVICE_EXPORT_ANALYSIS_PACK, device_a),
        return_response=True,
    )
    assert export.http_status == 200
    assert export.ws_success is True
    folder = export.http_body["service_response"]["folder"]
    assert Path(folder).is_dir()
    assert "energy_sharing" in folder
    ws_folder = export.ws_message["result"]["response"]["folder"]
    assert ws_folder == folder

    process = await _attempt(
        hass,
        hass_client,
        hass_ws_client,
        hass_access_token,
        SERVICE_PROCESS_NOW,
        _payload(SERVICE_PROCESS_NOW, device_a),
    )
    assert process.http_status == 200
    assert process.ws_success is True
    # The first call establishes the baseline. The second sees it already set.
    assert house_a.runtime_data.manager.data.baseline_initialization_count == 1
    assert house_b.runtime_data.manager.data.baseline_initialization_count == 0

    rebaseline = await _attempt(
        hass,
        hass_client,
        hass_ws_client,
        hass_access_token,
        SERVICE_REINITIALIZE_BASELINE,
        _payload(SERVICE_REINITIALIZE_BASELINE, device_b),
    )
    assert rebaseline.http_status == 200
    assert rebaseline.ws_success is True
    assert house_b.runtime_data.manager.data.baseline_initialization_count == 2
    assert house_a.runtime_data.manager.data.baseline_initialization_count == 1


async def test_user_calibration_forwards_caller_context_to_switch(
    hass: HomeAssistant,
    hass_client: Callable[..., Awaitable[Any]],
    hass_ws_client: Callable[..., Awaitable[Any]],
    hass_access_token: str,
    hass_admin_user: MockUser,
    fast_calibration: None,
) -> None:
    """Switch turn_on and turn_off keep the caller's context, not a blank one."""
    house_a, _house_b, switch = await _prepare_houses(hass, with_loads=True)
    events = async_capture_events(hass, EVENT_CALL_SERVICE)
    attempt = await _attempt(
        hass,
        hass_client,
        hass_ws_client,
        hass_access_token,
        SERVICE_CALIBRATE_LOADS,
        _payload(SERVICE_CALIBRATE_LOADS, _device_id(hass, house_a)),
    )
    assert attempt.http_status == 200
    assert attempt.ws_success is True
    turn_ons = _switch_calls(events, "turn_on")
    turn_offs = _switch_calls(events, "turn_off")
    assert turn_ons, "calibration did not call switch.turn_on"
    assert turn_offs, "calibration did not call switch.turn_off"
    assert {event.context.user_id for event in turn_ons} == {hass_admin_user.id}
    assert {event.context.user_id for event in turn_offs} == {hass_admin_user.id}
    assert any(call[0] == "turn_on" for call in switch.calls)
