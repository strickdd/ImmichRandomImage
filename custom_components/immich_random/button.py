"""Button platform for the Immich Random Image integration."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
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
    """Set up the Immich Random button."""
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    coordinator: ImmichCoordinator = entry_data["coordinator"]

    async_add_entities([ImmichRefreshButton(coordinator, config_entry)])


class ImmichRefreshButton(ButtonEntity):
    """Button entity that triggers a manual image refresh."""

    _attr_icon = "mdi:refresh"

    def __init__(
        self,
        coordinator: ImmichCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the button."""
        self._coordinator = coordinator
        self._attr_unique_id = f"{config_entry.entry_id}_refresh"
        self._attr_name = entity_name(config_entry, "Refresh Image")

    async def async_press(self) -> None:
        """Handle the button press — fetch a new random image."""
        _LOGGER.info("Manual refresh button pressed")
        await self._coordinator.async_request_refresh()
