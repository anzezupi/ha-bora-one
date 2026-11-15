"""BORA X BO (oven) support: codecs, discovery and entities against a simulated oven.

Message layouts follow the pbandk descriptors of the BORA One Android app. The
advertisement matches a real X BO (name "BORA X BO", manufacturer data 0x0B56
"XBO" + FD number). Status bodies are built here; no recording exists yet.
"""

from __future__ import annotations

import struct
from types import SimpleNamespace

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.bora_one.ble import oven, wire
from custom_components.bora_one.config_flow import async_pair_and_probe, is_bora, is_oven
from custom_components.bora_one.const import CONF_MODE, DOMAIN, MODE_BLUETOOTH
from custom_components.bora_one.mapper import map_oven
from custom_components.bora_one.models import OvenOperatingState, OvenProgram

from custom_components.bora_one.ble.transport import BOND_UUID

from .bora_peer import FakeBoraPeer
from .conftest import ADDRESS, FakeBluetooth

P = "bora_x_bo"
STATUS = oven.STATUS_SERVICE + "GetDeviceStatus"
FULL = oven.OVEN_STATUS_SERVICE + "GetFullOvenStatus"
IDENTIFY = oven.IDENTIFY_SERVICE + "GetSystemInformation"

ADVERTISEMENT = SimpleNamespace(
    address=ADDRESS,
    name="BORA X BO",
    service_uuids=[],
    manufacturer_data={0x0B56: b"XBO    2501HX00AC"},
)


def _float(number: int, value: float) -> bytes:
    return wire.varint(number << 3 | 5) + struct.pack("<f", value)


def information() -> bytes:
    bs_sys = (
        wire.string(2, "2439H40818")
        + wire.string(3, "2439H40819")
        + wire.string(4, "01.08.009.d63bc51")
        + wire.blob(7, wire.string(2, "de"))
    )
    return (
        wire.string(1, "2501HX00AC")
        + wire.string(2, "E123")
        + wire.blob(3, wire.uint(1, 1))  # bs_product = PRODUCT_XBO
        + wire.blob(4, bs_sys)
    )


def overview(
    *,
    program: int = 0,
    temperature: int = 35,
    target: int = 0,
    humidity: int = 0,
    target_humidity: int = 0,
    step_remaining: int = 0,
    program_remaining: int = 0,
    door_closed: bool = True,
    core: tuple[float, float] | None = None,
) -> bytes:
    xbo = wire.uint(1, 120) + wire.string(5, "Brot" if program else "")
    if core is not None:
        xbo += wire.blob(4, wire.uint(1, 1) + _float(2, core[0]) + _float(3, core[1]))
    body = wire.uint(3, program) + wire.uint(5, target) + wire.uint(6, temperature)
    body += wire.uint(7, target_humidity) + wire.uint(8, humidity)
    body += wire.uint(9, step_remaining) + wire.blob(10, xbo) + wire.uint(12, program_remaining)
    if door_closed:
        body += wire.uint(13, 1)
    return body


def device_status(*, turned_on: bool = True, state: int = 1, **kwargs) -> bytes:
    body = wire.uint(1, int(turned_on)) + wire.uint(2, state)
    body += wire.blob(3, wire.uint(1, 42) + wire.uint(2, 5))
    body += wire.blob(4, wire.blob(1, overview(**kwargs)))
    return body


RUNNING = dict(
    state=2,
    program=1,
    temperature=98,
    target=100,
    humidity=95,
    target_humidity=100,
    step_remaining=600,
    program_remaining=1500,
    core=(65.0, 41.5),
)


def oven_peer(peer: FakeBoraPeer, **kwargs) -> FakeBoraPeer:
    peer.status = {IDENTIFY: information(), STATUS: device_status(**kwargs)}
    peer.zones = {}
    return peer


def test_codecs() -> None:
    """Identity, overview, core temperature and progress decode as expected."""
    info = oven.decode_information(information())
    assert info["product_name"] == "xbo"
    assert info["fd"] == "2501HX00AC"
    assert info["bundle_sw_version"] == "01.08.009.d63bc51"

    status = oven.decode_status(device_status(**RUNNING))
    assert status["turned_on"] is True
    assert status["operating_state"] == "running"
    assert status["operating_hours"] == 42
    view = status["overview"]
    assert view["program"] == "manual_cooking"
    assert view["current_temperature"] == 98
    assert view["door_open"] is False
    assert view["xbo"]["core_temperature"]["current"] == 41.5

    full = oven.decode_full_status(
        wire.uint(1, 7) + wire.uint(4, 30) + wire.blob(7, overview(**{"program": 2}))
    )
    assert full["program_progress"] == 30
    assert full["overview"]["program"] == "automatic_cooking"

    # proto3 drops the default (0 = OPEN): an absent door state is unknown
    assert oven.decode_overview(overview(door_closed=False))["door_open"] is None
    assert oven.decode_overview(overview() + wire.uint(13, 0))["door_open"] is True


def test_mapping() -> None:
    """The oven model takes temperatures, times and states from the status."""
    state = {"oven": oven.decode_status(device_status(**RUNNING)), "full": {"program_progress": 25}}
    model = map_oven("id", "BORA X BO", oven.decode_information(information()), state)
    assert model.model == "X BO"
    assert model.is_cooking
    assert model.oven.operating_state is OvenOperatingState.RUNNING
    assert model.oven.program is OvenProgram.MANUAL_COOKING
    assert model.oven.target_temperature == 100
    assert model.oven.core_temperature == 41.5
    assert model.oven.target_core_temperature == 65.0
    assert model.oven.program_remaining == 1500
    assert model.oven.program_progress == 25

    idle = map_oven("id", "x", {}, {"oven": oven.decode_status(device_status(turned_on=False))})
    assert not idle.is_cooking
    assert idle.switched_off
    assert idle.oven.target_temperature is None
    assert idle.oven.program_progress is None


def test_discovery() -> None:
    """The X BO advertises no BORA service UUID; name and manufacturer data match."""
    assert is_oven(ADVERTISEMENT)
    assert is_bora(ADVERTISEMENT)
    by_data = SimpleNamespace(name=None, service_uuids=[], manufacturer_data={0x0B56: b"XBO"})
    assert is_oven(by_data) and is_bora(by_data)
    cooktop = SimpleNamespace(name="X PURE", service_uuids=[], manufacturer_data={})
    assert is_bora(cooktop) and not is_oven(cooktop)


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=ADDRESS,
        title="BORA X BO",
        data={
            CONF_MODE: MODE_BLUETOOTH,
            CONF_ADDRESS: ADDRESS,
            "kind": "oven",
            "zones": [],
            "extractor": False,
            "model": "X BO",
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _state(hass: HomeAssistant, entity_id: str) -> str:
    return hass.states.get(entity_id).state


async def test_oven_entities(
    hass: HomeAssistant, bluetooth: FakeBluetooth, peer: FakeBoraPeer
) -> None:
    """A running X BO shows temperatures and programme; only reads are sent."""
    oven_peer(peer, **RUNNING)
    entry = await _setup(hass)
    assert entry.state is ConfigEntryState.LOADED

    assert _state(hass, f"sensor.{P}_status") == "cooking"
    assert _state(hass, f"sensor.{P}_programme") == "manual_cooking"
    assert _state(hass, f"sensor.{P}_cooking_chamber_temperature") == "98"
    assert _state(hass, f"sensor.{P}_target_temperature") == "100"
    assert _state(hass, f"sensor.{P}_cooking_chamber_humidity") == "95"
    assert _state(hass, f"sensor.{P}_core_temperature") == "41.5"
    assert _state(hass, f"sensor.{P}_programme_name") == "Brot"
    assert _state(hass, f"binary_sensor.{P}_door") == "off"
    assert _state(hass, f"binary_sensor.{P}_cooking") == "on"
    assert _state(hass, f"binary_sensor.{P}_bluetooth_connection") == "on"
    assert hass.states.get(f"sensor.{P}_programme_end").state not in ("unknown", "unavailable")

    # No cooktop-only entities on an oven.
    registry = er.async_get(hass)
    ids = {e.entity_id for e in er.async_entries_for_config_entry(registry, entry.entry_id)}
    assert f"sensor.{P}_active_zones" not in ids
    assert f"binary_sensor.{P}_residual_heat" not in ids
    assert not any("extractor" in entity_id for entity_id in ids)

    # Oven paths only; the programme progress read is optional (here: UNIMPLEMENTED).
    assert set(peer.requests) <= {IDENTIFY, STATUS, FULL, oven.STREAM_PATH, oven.EGG_TIMER_STREAM}

    # A status stream update is applied.
    peer.push(oven.STREAM_PATH, device_status(turned_on=True, state=1, door_closed=False))
    await hass.async_block_till_done()
    assert _state(hass, f"sensor.{P}_status") == "standby"
    assert _state(hass, f"binary_sensor.{P}_door") == "unknown"
    assert _state(hass, f"sensor.{P}_target_temperature") == "unknown"


async def test_stop_program_button(
    hass: HomeAssistant, bluetooth: FakeBluetooth, peer: FakeBoraPeer
) -> None:
    """The stop button sends StopCurrentDeviceFunction with an empty request."""
    oven_peer(peer, **RUNNING)
    stop_path = oven.CONTROL_SERVICE + "StopCurrentDeviceFunction"
    peer.status[stop_path] = b""
    await _setup(hass)
    button = f"button.{P}_stop_programme"
    assert _state(hass, button) == "unknown"

    await hass.services.async_call("button", "press", {"entity_id": button}, blocking=True)
    assert stop_path in peer.requests


async def test_egg_timer(
    hass: HomeAssistant, bluetooth: FakeBluetooth, peer: FakeBoraPeer
) -> None:
    """An egg timer set on the oven shows as an end time."""
    oven_peer(peer, **RUNNING)
    peer.extra_streams.add(oven.EGG_TIMER_STREAM)
    await _setup(hass)
    sensor = f"sensor.{P}_egg_timer_end"
    assert _state(hass, sensor) == "unknown"

    peer.push(oven.EGG_TIMER_STREAM, wire.uint(1, 300))
    await hass.async_block_till_done()
    assert _state(hass, sensor) not in ("unknown", "unavailable")

    peer.push(oven.EGG_TIMER_STREAM, b"")
    await hass.async_block_till_done()
    assert _state(hass, sensor) == "unknown"


async def test_oven_switched_off(
    hass: HomeAssistant, bluetooth: FakeBluetooth, peer: FakeBoraPeer
) -> None:
    """A connected but switched-off oven reports Off."""
    oven_peer(peer, turned_on=False)
    await _setup(hass)
    assert _state(hass, f"sensor.{P}_status") == "off"
    assert _state(hass, f"binary_sensor.{P}_cooking") == "off"


async def test_probe_detects_oven(
    hass: HomeAssistant, bluetooth: FakeBluetooth, peer: FakeBoraPeer, monkeypatch
) -> None:
    """Pairing an X BO stores it as an oven without zones or extractor."""
    oven_peer(peer)
    monkeypatch.setattr(
        "homeassistant.components.bluetooth.async_last_service_info",
        lambda hass, address, connectable=True: ADVERTISEMENT,
    )
    details = await async_pair_and_probe(hass, ADDRESS)
    assert details == {"kind": "oven", "zones": [], "extractor": False, "model": "X BO"}
    assert peer.requests == [IDENTIFY]


class ESPHomeClient:
    """Stands in for the ESPHome backend type of a Home Assistant client."""


class StaleCachePeer(FakeBoraPeer):
    """A proxy whose cached GATT table is stale until the cache is cleared."""

    def __init__(self) -> None:
        super().__init__()
        self._backend = ESPHomeClient()
        self.stale = True
        self.cleared = 0

    async def start_notify(self, uuid, callback) -> None:
        if self.stale:
            raise RuntimeError("Bluetooth GATT Error handle=21 error=1 description=Invalid handle")
        await super().start_notify(uuid, callback)

    async def clear_cache(self) -> bool:
        self.cleared += 1
        self.stale = False
        return True


async def test_stale_proxy_gatt_cache_is_cleared() -> None:
    """'Invalid handle' from an ESPHome proxy clears its GATT cache and reconnects."""
    peer = StaleCachePeer()
    oven_peer(peer)
    connection = peer.connection()
    await connection.connect()
    assert peer.cleared >= 1  # once for the stale table, again on every disconnect
    assert connection.connected
    assert oven.decode_information(await connection.rpc(*oven.get_information()))["fd"]
    await connection.disconnect()


class UnencryptedProxyPeer(FakeBoraPeer):
    """An ESPHome proxy link: bonded, but not encrypted until pair() is called."""

    def __init__(self) -> None:
        super().__init__()
        self._backend = ESPHomeClient()
        self.pair_calls = 0

    async def read_gatt_char(self, uuid: str) -> bytearray:
        if uuid == BOND_UUID:
            return bytearray([1])  # the X BO reports the bond before encryption
        return bytearray()

    async def start_notify(self, uuid, callback) -> None:
        encrypted = self.encrypted
        await super().start_notify(uuid, callback)
        self.encrypted = encrypted  # an ESPHome proxy does not encrypt on its own

    async def pair(self) -> None:
        self.pair_calls += 1
        self.encrypted = True

    async def write_gatt_char(self, uuid: str, data: bytes, response: bool) -> None:
        if not self.encrypted:
            raise RuntimeError("Bluetooth GATT Error error=15 description=Insufficient encryption")
        await super().write_gatt_char(uuid, data, response)


async def test_esphome_link_is_encrypted() -> None:
    """Through an ESPHome proxy, a bonded link is encrypted before the first request."""
    peer = UnencryptedProxyPeer()
    oven_peer(peer)
    connection = peer.connection()
    await connection.connect()
    assert peer.pair_calls == 1
    assert oven.decode_information(await connection.rpc(*oven.get_information()))["fd"]
    await connection.disconnect()
