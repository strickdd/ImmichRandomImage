"""Select platform for the Immich Random Image integration."""
from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import ImmichCoordinator
from .entity import entity_name

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Immich Random select entity."""
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    coordinator: ImmichCoordinator = entry_data["coordinator"]

    async_add_entities([ImmichAlbumSelect(coordinator, config_entry)])


class ImmichAlbumSelect(SelectEntity):
    """Select entity for choosing which albums to pull random images from.

    This entity allows automations to dynamically change the album selection.
    Each option is an album ID; selecting/deselecting adds/removes it from
    the active set. The special option 'all' clears the selection to pull
    from the entire library.

    Usage in automations:
      # Select a specific album
      action: select.select_option
      target:
        entity_id: select.immich_album_selection
      data:
        option: "<album-id>"

      # Reset to random from all
      action: select.select_option
      target:
        entity_id: select.immich_album_selection
      data:
        option: "all"
    """

    _attr_icon = "mdi:image-multiple"

    def __init__(
        self,
        coordinator: ImmichCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the select entity."""
        self._coordinator = coordinator
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_album_select"
        self._attr_name = entity_name(config_entry, "Album Selection")

    @property
    def options(self) -> list[str]:
        """Return the list of available options (album IDs + 'all')."""
        album_ids = [album["id"] for album in self._coordinator.albums]
        return album_ids + ["all"]

    @property
    def extra_state_attributes(self) -> dict:
        """Return album count as attributes (names excluded for size)."""
        return {
            "album_count": len(self._coordinator.albums),
            "current_selection": self._coordinator.hub.album_ids,
        }

    @property
    def current_option(self) -> str:
        """Return the current selection.

        If albums are selected, returns the first album ID.
        If no albums are selected, returns 'all'.
        """
        album_ids = self._coordinator.hub.album_ids
        if album_ids:
            return album_ids[0]
        return "all"

    async def async_select_option(self, option: str) -> None:
        """Set the album selection."""
        if option == "all":
            _LOGGER.info("Album selection cleared — random from entire library")
            await self._coordinator.async_set_album_ids([])
        else:
            _LOGGER.info("Album selection set to: %s", option)
            await self._coordinator.async_set_album_ids([option])
