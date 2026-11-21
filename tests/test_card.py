"""Tests for serving and registering the dashboard card."""

from __future__ import annotations

from collections.abc import Generator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.brager_one import card
from custom_components.brager_one.card import (
    CARD_PATH,
    CARD_URL,
    async_register_card,
    async_unregister_card,
)

from .conftest import mock_api, setup_integration


class FakeResources:
    """Minimal storage-mode Lovelace resource collection."""

    def __init__(self, items: list[dict[str, Any]] | None = None) -> None:
        self.items = list(items or [])
        self.loaded = False

    async def async_get_info(self) -> dict[str, int]:
        self.loaded = True
        return {"resources": len(self.items)}

    def async_items(self) -> list[dict[str, Any]]:
        return list(self.items)

    async def async_create_item(self, data: dict[str, Any]) -> None:
        self.items.append(
            {
                "id": f"new{len(self.items)}",
                "type": data["res_type"],
                "url": data["url"],
            }
        )

    async def async_update_item(self, item_id: str, data: dict[str, Any]) -> None:
        for item in self.items:
            if item["id"] == item_id:
                item.update(data)

    async def async_delete_item(self, item_id: str) -> None:
        self.items = [item for item in self.items if item["id"] != item_id]


@pytest.fixture
def frontend() -> Generator[MagicMock]:
    """Patch the frontend helpers."""
    with (
        patch.object(card, "add_extra_js_url") as add,
        patch.object(card, "remove_extra_js_url") as remove,
    ):
        add.remove = remove
        yield add


def _setup(hass: HomeAssistant, resources: Any, mode: str = "storage") -> MagicMock:
    hass.data["lovelace"] = SimpleNamespace(resource_mode=mode, resources=resources)
    http = MagicMock()
    http.async_register_static_paths = AsyncMock()
    hass.http = http
    return http


async def _url(hass: HomeAssistant) -> str:
    return await card._async_card_url(hass)


def test_card_file_exists() -> None:
    """The card ships with the integration."""
    assert CARD_PATH.is_file()
    assert 'customElements.define("brager-one-card"' in CARD_PATH.read_text()


async def test_register_creates_resource(
    hass: HomeAssistant, frontend: MagicMock
) -> None:
    """A new install gets the static path, the module and one resource."""
    resources = FakeResources()
    http = _setup(hass, resources)
    await async_register_card(hass)
    await async_register_card(hass)

    http.async_register_static_paths.assert_awaited_once()
    url = await _url(hass)
    assert url.startswith(f"{CARD_URL}?v=")
    frontend.assert_called_with(hass, url)
    assert [item["url"] for item in resources.items] == [url]
    assert resources.items[0]["type"] == "module"


async def test_register_updates_version_and_removes_duplicates(
    hass: HomeAssistant, frontend: MagicMock
) -> None:
    """An upgrade moves the resource to the new version and drops extra copies."""
    resources = FakeResources(
        [
            {"id": "a", "type": "module", "url": f"{CARD_URL}?v=0.1"},
            {"id": "b", "type": "module", "url": f"{CARD_URL}?v=0.2"},
            {"id": "c", "type": "module", "url": "/other/card.js"},
        ]
    )
    _setup(hass, resources)
    await async_register_card(hass)
    url = await _url(hass)
    assert {item["id"]: item["url"] for item in resources.items} == {
        "a": url,
        "c": "/other/card.js",
    }

    # Already current: nothing changes.
    await async_register_card(hass)
    assert len(resources.items) == 2


async def test_register_yaml_mode_leaves_resources(
    hass: HomeAssistant, frontend: MagicMock
) -> None:
    """YAML-mode dashboards are not touched; the module is still added."""
    resources = FakeResources()
    _setup(hass, resources, mode="yaml")
    await async_register_card(hass)
    assert resources.items == []
    frontend.assert_called_once()


async def test_register_never_raises(
    hass: HomeAssistant, frontend: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    """A failure is logged and does not stop setup."""
    http = _setup(hass, FakeResources())
    http.async_register_static_paths.side_effect = RuntimeError("boom")
    await async_register_card(hass)
    assert "Could not register the BragerOne card" in caplog.text


async def test_unregister(hass: HomeAssistant, frontend: MagicMock) -> None:
    """Unregistering removes our resource and the module, nothing else."""
    resources = FakeResources(
        [
            {"id": "a", "type": "module", "url": f"{CARD_URL}?v=1"},
            {"id": "c", "type": "module", "url": "/other/card.js"},
        ]
    )
    _setup(hass, resources)
    await async_unregister_card(hass)
    assert [item["id"] for item in resources.items] == ["c"]
    frontend.remove.assert_called_once()


async def test_unregister_without_lovelace(
    hass: HomeAssistant, frontend: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    """No storage dashboards: only the module is removed; errors are logged."""
    await async_unregister_card(hass)
    frontend.remove.assert_called_once()

    frontend.remove.side_effect = RuntimeError("boom")
    await async_unregister_card(hass)
    assert "Could not remove the BragerOne card resource" in caplog.text


async def test_entry_lifecycle_registers_card(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_entry: MockConfigEntry,
) -> None:
    """Setup registers the card; removing the last entry removes it."""
    with (
        patch("custom_components.brager_one.async_register_card") as register,
        patch("custom_components.brager_one.async_unregister_card") as unregister,
    ):
        mock_api(aioclient_mock)
        other = MockConfigEntry(
            domain="brager_one",
            unique_id="OTHER",
            data={**mock_entry.data, "devid": "OTHER"},
        )
        other.add_to_hass(hass)
        await setup_integration(hass, mock_entry)
        register.assert_awaited()

        await hass.config_entries.async_remove(mock_entry.entry_id)
        await hass.async_block_till_done()
        unregister.assert_not_awaited()

        await hass.config_entries.async_remove(other.entry_id)
        await hass.async_block_till_done()
        unregister.assert_awaited_once()
