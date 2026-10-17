"""Pairing agent tests."""

from __future__ import annotations

from custom_components.bora_one.agent import _agent_class, pairing_agent


def test_agent_interface_is_valid() -> None:
    """dbus-fast accepts the Agent1 method signatures."""
    agent = _agent_class()()
    names = {m.name for m in agent.introspect().methods}
    assert {"RequestConfirmation", "RequestAuthorization", "RequestPasskey", "Cancel"} <= names


async def test_agent_is_noop_without_bluez() -> None:
    """Without BlueZ the context manager still lets pairing proceed."""
    entered = False
    async with pairing_agent():
        entered = True
    assert entered
