"""Real-HA coverage for naming and coordinator-owned rotation."""
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
import voluptuous as vol
from homeassistant.const import CONF_API_KEY, CONF_HOST
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from test_integration import (  # noqa: F401
    ASSET,
    HUB,
    _entry,
    _setup,
)

from custom_components.immich_random.const import DOMAIN
from custom_components.immich_random.hub import CannotConnect


@pytest.mark.parametrize("albums", [[{"id": "alb1", "albumName": "A"}], [], None])
@pytest.mark.parametrize("name", [" Living Room ", "", "   "])
async def test_setup_name_survives_all_album_paths(hass, mock_immich, albums, name):
    """Keep optional name through selection, empty albums and request failures."""
    with patch(f"{HUB}.list_all_albums", AsyncMock(return_value=albums or [], side_effect=CannotConnect("down") if albums is None else None)):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        assert "name" in result["data_schema"].schema
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {
            CONF_HOST: "https://immich.test", CONF_API_KEY: "k", "name": name,
        })
        if albums:
            result = await hass.config_entries.flow.async_configure(result["flow_id"], {"album_ids": ["alb1"]})
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == (name.strip() or "Immich @ immich.test")
        assert result["data"].get("name", "") == name.strip()
        await hass.async_block_till_done()


async def test_named_entities_preserve_registry_customizations(hass, mock_immich):
    """All five defaults share a prefix, without changing registry identity."""
    entry = _entry(scan_interval=0)
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, data={**entry.data, "name": "Living Room"})
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, entry.entry_id)
    assert {e.original_name for e in entities} == {
        "Living Room Random Image", "Living Room Refresh Image", "Living Room Album Selection",
        "Living Room Last Image Pulled", "Living Room Image Filename",
    }
    ids = {e.unique_id: e.entity_id for e in entities}
    image_id = ids[f"{entry.entry_id}_image"]
    registry.async_update_entity(image_id, name="My Frame")
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert {e.unique_id: e.entity_id for e in er.async_entries_for_config_entry(registry, entry.entry_id)} == ids
    assert registry.async_get(image_id).name == "My Frame"


@pytest.mark.parametrize("seconds", [0, 1, 300, 86400, -1, 86401])
async def test_interval_options_range(hass, mock_immich, seconds):
    entry = _entry()
    await _setup(hass, entry)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    values = {CONF_HOST: "https://immich.test", "scan_interval": seconds}
    if 0 <= seconds <= 86400:
        assert result["data_schema"](values)["scan_interval"] == seconds
    else:
        with pytest.raises(vol.Invalid):
            result["data_schema"](values)


async def test_zero_interval_has_no_rotation_but_manual_paths_publish(hass, mock_immich, freezer):
    """No timer or cache-read rotation; explicit actions publish all metadata."""
    entry = _entry(scan_interval=0)
    with patch(f"{HUB}.get_random_image", AsyncMock(return_value=ASSET)) as fetch:
        await _setup(hass, entry)
        assert fetch.await_count == 1
        freezer.tick(timedelta(hours=1))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        assert fetch.await_count == 1
        image = hass.data["image"].get_entity("image.immich_random_image")
        await image.async_image()
        assert fetch.await_count == 1
        actions = [("button", "press", {"entity_id": "button.immich_refresh_image"}),
                   (DOMAIN, "refresh", {"entry_id": entry.entry_id}),
                   ("select", "select_option", {"entity_id": "select.immich_album_selection", "option": "alb1"})]
        for index, (domain, service, data) in enumerate(actions):
            freezer.tick(timedelta(seconds=20))
            async_fire_time_changed(hass, dt_util.utcnow())
            await hass.async_block_till_done()
            fetch.return_value = {**ASSET, "originalFileName": f"photo-{index}.jpg"}
            await hass.services.async_call(domain, service, data, blocking=True)
            await hass.async_block_till_done()
            assert hass.states.get("sensor.immich_image_filename").state == f"photo-{index}.jpg"
            assert hass.states.get("image.immich_random_image").attributes["media_filename"] == f"photo-{index}.jpg"


async def test_positive_interval_rotates_and_unload_cancels(hass, mock_immich, freezer):
    entry = _entry(scan_interval=60)
    with patch(f"{HUB}.get_random_image", AsyncMock(return_value=ASSET)) as fetch:
        await _setup(hass, entry)
        assert fetch.await_count == 1
        freezer.tick(timedelta(seconds=65))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        assert fetch.await_count == 2
        await hass.config_entries.async_unload(entry.entry_id)
        freezer.tick(timedelta(hours=1))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        assert fetch.await_count == 2


async def test_interval_transitions_and_entries_are_independent(hass, mock_immich, freezer):
    """Reload changes cancel old schedules and leave other entries alone."""
    first, second = _entry(scan_interval=0), _entry(scan_interval=120)
    with patch(f"{HUB}.get_random_image", AsyncMock(return_value=ASSET)) as fetch:
        await _setup(hass, first)
        await _setup(hass, second)
        assert fetch.await_count == 2
        hass.config_entries.async_update_entry(first, options={"scan_interval": 60})
        await hass.async_block_till_done()
        assert fetch.await_count == 3
        freezer.tick(timedelta(seconds=65))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        assert fetch.await_count == 4
        hass.config_entries.async_update_entry(first, options={"scan_interval": 0})
        await hass.async_block_till_done()
        assert fetch.await_count == 5
        freezer.tick(timedelta(seconds=65))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        assert fetch.await_count == 6  # Only the second entry is due.


async def test_failed_download_retains_cached_image_and_metadata(hass, mock_immich, freezer):
    entry = _entry(scan_interval=0)
    await _setup(hass, entry)
    before = hass.states.get("image.immich_random_image")
    freezer.tick(timedelta(seconds=20))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    with patch(f"{HUB}.download_asset", AsyncMock(return_value=None)):
        await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)
    after = hass.states.get("image.immich_random_image")
    assert after.state == before.state
    assert after.attributes["media_filename"] == "x.jpg"
    assert hass.data[DOMAIN][entry.entry_id]["coordinator"].image_bytes == b"img"


async def test_named_entry_collisions_use_unique_registry_ids(hass, mock_immich):
    registry = er.async_get(hass)
    entity_ids = []
    for _ in range(2):
        entry = _entry(scan_interval=0)
        entry.add_to_hass(hass)
        hass.config_entries.async_update_entry(entry, data={**entry.data, "name": "Living Room"})
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        entity_ids.append(registry.async_get_entity_id("image", DOMAIN, f"{entry.entry_id}_image"))
    assert entity_ids == ["image.living_room_random_image", "image.living_room_random_image_2"]


async def test_positive_interval_change_replaces_old_schedule(hass, mock_immich, freezer):
    entry = _entry(scan_interval=60)
    with patch(f"{HUB}.get_random_image", AsyncMock(return_value=ASSET)) as fetch:
        await _setup(hass, entry)
        hass.config_entries.async_update_entry(entry, options={"scan_interval": 180})
        await hass.async_block_till_done()
        assert fetch.await_count == 2
        freezer.tick(timedelta(seconds=65))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        assert fetch.await_count == 2
        freezer.tick(timedelta(seconds=120))
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        assert fetch.await_count == 3


async def test_explicit_update_works_with_ha_polling_disabled(hass, mock_immich):
    assert await async_setup_component(hass, "homeassistant", {})
    entry = _entry(scan_interval=60)
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, pref_disable_polling=True)
    with patch(f"{HUB}.get_random_image", AsyncMock(return_value=ASSET)) as fetch:
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        fetch.return_value = {**ASSET, "originalFileName": "explicit.jpg"}
        await hass.services.async_call("homeassistant", "update_entity", {"entity_id": "image.immich_random_image"}, blocking=True)
        await hass.async_block_till_done()
        assert hass.states.get("sensor.immich_image_filename").state == "explicit.jpg"


async def test_initial_empty_search_recovers_on_image_read(hass, mock_immich):
    entry = _entry(scan_interval=0)
    with patch(f"{HUB}.get_random_image", AsyncMock(return_value=None)) as fetch:
        await _setup(hass, entry)
        image = hass.data["image"].get_entity("image.immich_random_image")
        assert image.image_last_updated is None
        fetch.return_value = ASSET
        assert await image.async_image() == b"img"
        await hass.async_block_till_done()
        assert image.image_last_updated is not None
        assert hass.states.get("sensor.immich_image_filename").state == "x.jpg"
