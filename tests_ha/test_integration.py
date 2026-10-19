"""Integration tests that load the integration into a real Home Assistant.

The stub-based suite in tests/ replaces Home Assistant with mocks, so it
cannot catch calls to methods or attributes HA does not have. These tests
set up the real config entry with only the Immich HTTP calls mocked.
"""
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_API_KEY, CONF_HOST
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.immich_random.const import DOMAIN
from custom_components.immich_random.hub import CannotConnect

HUB = "custom_components.immich_random.hub.ImmichRandomHub"
ASSET = {
    "id": "a1",
    "originalFileName": "x.jpg",
    "localDateTime": "2024-01-01T00:00:00",
    "width": 1,
    "height": 1,
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let HA load integrations from custom_components/."""
    yield


@pytest.fixture
def mock_immich():
    """Mock every Immich HTTP call; tests override authenticate as needed."""
    with (
        patch(f"{HUB}.authenticate", AsyncMock(return_value=True)) as auth,
        patch(
            f"{HUB}.list_all_albums",
            AsyncMock(return_value=[{"id": "alb1", "albumName": "A"}]),
        ),
        patch(f"{HUB}.get_random_image", AsyncMock(return_value=ASSET)),
        patch(f"{HUB}.download_asset", AsyncMock(return_value=b"img")),
    ):
        yield auth


def _entry(**options) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "https://immich.test", CONF_API_KEY: "k", "verify_ssl": True},
        options=options,
    )


async def _setup(hass, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_refresh_paths_do_not_raise(hass, mock_immich):
    """Button, album select and the refresh service all refresh cleanly."""
    entry = _entry()
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED

    await hass.services.async_call(
        "button", "press", {"entity_id": "button.immich_refresh_image"}, blocking=True
    )
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.immich_album_selection", "option": "alb1"},
        blocking=True,
    )
    assert hass.states.get("select.immich_album_selection").state == "alb1"
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.immich_album_selection", "option": "all"},
        blocking=True,
    )
    await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)


async def test_image_last_updated_without_data(hass, mock_immich):
    """No pulled image yet means no timestamp, not an AttributeError."""
    entry = _entry()
    await _setup(hass, entry)
    hass.data[DOMAIN][entry.entry_id]["coordinator"].data = None
    entity = hass.data["image"].get_entity("image.immich_random_image")
    assert entity.image_last_updated is None


async def test_image_unique_id_is_stable_and_scoped(hass, mock_immich):
    """Two entries never collide, and changing albums keeps the entity."""
    first, second = _entry(), _entry(album_ids=["alb1"])
    await _setup(hass, first)
    await _setup(hass, second)
    registry = er.async_get(hass)

    image_ids = {e.unique_id for e in registry.entities.values() if e.domain == "image"}
    assert image_ids == {f"{first.entry_id}_image", f"{second.entry_id}_image"}

    entity_id = registry.async_get_entity_id("image", DOMAIN, f"{first.entry_id}_image")
    hass.config_entries.async_update_entry(first, options={"album_ids": ["alb1"]})
    await hass.async_block_till_done()
    assert (
        registry.async_get_entity_id("image", DOMAIN, f"{first.entry_id}_image")
        == entity_id
    )
    assert len([e for e in registry.entities.values() if e.domain == "image"]) == 2


async def test_legacy_image_unique_id_is_migrated(hass, mock_immich):
    """A pre-1.3.0 album-derived unique_id keeps its entity_id."""
    entry = _entry(album_ids=["alb1"])
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "image",
        DOMAIN,
        "immich_random_album_alb1",
        config_entry=entry,
        suggested_object_id="my_frame",
    )

    await _setup(hass, entry)

    assert (
        registry.async_get_entity_id("image", DOMAIN, f"{entry.entry_id}_image")
        == "image.my_frame"
    )
    assert hass.states.get("image.my_frame") is not None


async def test_cannot_connect_at_startup_retries(hass, mock_immich):
    """Immich being down at startup retries instead of failing for good."""
    mock_immich.side_effect = CannotConnect("down")
    entry = _entry()
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_rejected_key_starts_reauth_which_recovers(hass, mock_immich):
    """A rejected key fails auth, and the reauth flow stores a new key."""
    mock_immich.return_value = False
    entry = _entry()
    await _setup(hass, entry)
    assert entry.state is ConfigEntryState.SETUP_ERROR

    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == ["reauth"]
    flow_id = flows[0]["flow_id"]

    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_API_KEY: "still-bad"}
    )
    assert result["errors"] == {"base": "invalid_auth"}

    mock_immich.return_value = True
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_API_KEY: "new"}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_API_KEY] == "new"
    assert entry.state is ConfigEntryState.LOADED
