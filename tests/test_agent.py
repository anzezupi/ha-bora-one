"""Pairing agent tests."""

from __future__ import annotations

from dbus_fast import DBusError
import pytest

from custom_components.bora_one.agent import _agent_class, pairing_agent

ADDRESS = "AA:BB:CC:DD:EE:FF"
COOKTOP = "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"
OTHER = "/org/bluez/hci0/dev_11_22_33_44_55_66"


def test_agent_interface_is_valid() -> None:
    """dbus-fast accepts the Agent1 method signatures."""
    agent = _agent_class()(ADDRESS)
    names = {m.name for m in agent.introspect().methods}
    assert {"RequestConfirmation", "RequestAuthorization", "RequestPasskey", "Cancel"} <= names


def test_agent_accepts_only_the_cooktop() -> None:
    """Requests from any other device are rejected while pairing."""
    agent = _agent_class()(ADDRESS.lower())
    agent._check(COOKTOP)
    with pytest.raises(DBusError):
        agent._check(OTHER)


async def test_agent_is_noop_without_bluez() -> None:
    """Without BlueZ the context manager still lets pairing proceed."""
    entered = False
    async with pairing_agent(ADDRESS):
        entered = True
    assert entered
