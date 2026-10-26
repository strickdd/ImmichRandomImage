"""The Immich Random Image integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, CONF_HOST, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, SERVICE_REFRESH
from .coordinator import ImmichCoordinator
from .hub import CannotConnect, ImmichRandomHub

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.IMAGE,
    Platform.SENSOR,
    Platform.BUTTON,
    Platform.SELECT,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Immich Random Image from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    hub = ImmichRandomHub(
        host=entry.data[CONF_HOST],
        api_key=entry.data[CONF_API_KEY],
        album_ids=entry.options.get("album_ids", entry.data.get("album_ids", [])),
        verify_ssl=entry.options.get(
            "verify_ssl", entry.data.get("verify_ssl", True)
        ),
        hass=hass,
    )

    try:
        authenticated = await hub.authenticate()
    except CannotConnect as err:
        raise ConfigEntryNotReady(f"Cannot connect to Immich: {err}") from err
    if not authenticated:
        raise ConfigEntryAuthFailed("Immich rejected the API key")

    _async_migrate_image_unique_id(hass, entry)

    scan_interval = entry.options.get(
        "scan_interval",
        entry.data.get("scan_interval", DEFAULT_SCAN_INTERVAL),
    )

    coordinator = ImmichCoordinator(hass, hub, entry)
    await coordinator.async_config_entry_first_refresh()

    # Fetch albums for the select entity
    await coordinator.async_refresh_albums()

    hass.data[DOMAIN][entry.entry_id] = {
        "hub": hub,
        "coordinator": coordinator,
        "scan_interval": int(scan_interval),
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register the refresh service
    async def _handle_refresh(call) -> None:
        """Handle the manual refresh service call."""
        target_entry_id = call.data.get("entry_id")
        for eid, entry_data in hass.data.get(DOMAIN, {}).items():
            if target_entry_id and eid != target_entry_id:
                continue
            coord: ImmichCoordinator = entry_data["coordinator"]
            _LOGGER.info("Manual refresh triggered for entry %s", eid)
            await coord.async_request_refresh()

    hass.services.async_register(DOMAIN, SERVICE_REFRESH, _handle_refresh)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


def _async_migrate_image_unique_id(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Move the image entity from its legacy unique_id to the stable one.

    Before 1.3.0 the image unique_id was derived from the album selection
    ("immich_random", "immich_random_album_<id>", "immich_random_albums_..."),
    so it changed whenever albums did. Re-keying the existing registry entry
    keeps the user's entity_id, name, area and history.
    """
    registry = er.async_get(hass)
    new_unique_id = f"{entry.entry_id}_image"
    if registry.async_get_entity_id("image", DOMAIN, new_unique_id):
        return

    for entity_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity_entry.domain == "image" and entity_entry.unique_id.startswith(
            "immich_random"
        ):
            _LOGGER.info(
                "Migrating %s unique_id %s -> %s",
                entity_entry.entity_id,
                entity_entry.unique_id,
                new_unique_id,
            )
            registry.async_update_entity(
                entity_entry.entity_id, new_unique_id=new_unique_id
            )
            # Any further legacy entries were already orphaned by an earlier
            # album change; leave them for the user to remove.
            return


async def _async_update_listener(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Handle options update — reload the entry."""
    await hass.config_entries.async_reload(entry.entry_id)
