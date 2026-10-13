"""Fixtures for BORA JOY tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import patch

import pytest

from custom_components.bora_joy.api import BoraJoyClient, BoraJoyDemoClient
from custom_components.bora_joy.models import Cooktop


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading custom integrations."""


class FakeDemoClient(BoraJoyClient):
    """Demo client whose position in the cycle is set by the test."""

    def __init__(self) -> None:
        self.t = 400

    async def async_login(self) -> None:
        """Nothing to do."""

    async def async_get_cooktops(self) -> dict[str, Cooktop]:
        cooktop = BoraJoyDemoClient.snapshot(self.t)
        return {cooktop.appliance_id: cooktop}


@pytest.fixture
def demo_client() -> Generator[FakeDemoClient]:
    """Patch the demo client with a controllable one."""
    client = FakeDemoClient()
    with patch("custom_components.bora_joy.BoraJoyDemoClient", return_value=client):
        yield client
