"""Sensor platform for the Immich Random Image integration."""
from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ImmichCoordinator
from .entity import entity_name

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Immich Random sensors."""
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    coordinator: ImmichCoordinator = entry_data["coordinator"]

    async_add_entities(
        [
            ImmichLastPulledSensor(coordinator, config_entry),
            ImmichFilenameSensor(coordinator, config_entry),
        ]
    )


class ImmichLastPulledSensor(CoordinatorEntity, SensorEntity):
    """Sensor that reports when the last random image was pulled."""

    _attr_icon = "mdi:clock-outline"

    def __init__(
        self,
        coordinator: ImmichCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._attr_unique_id = f"{config_entry.entry_id}_last_pulled"
        self._attr_name = entity_name(config_entry, "Last Image Pulled")

    @property
    def native_value(self) -> str:
        """Return the last pulled timestamp."""
        data = self._coordinator.data or {}
        return data.get("last_pulled", "unknown")

    @property
    def extra_state_attributes(self) -> dict:
        """Return extra attributes."""
        data = self._coordinator.data or {}
        return {
            "asset_id": data.get("asset_id", ""),
        }


class ImmichFilenameSensor(CoordinatorEntity, SensorEntity):
    """Sensor that exposes the current image filename."""

    _attr_icon = "mdi:file-image"

    def __init__(
        self,
        coordinator: ImmichCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._attr_unique_id = f"{config_entry.entry_id}_filename"
        self._attr_name = entity_name(config_entry, "Image Filename")

    @property
    def native_value(self) -> str:
        """Return the current image filename."""
        data = self._coordinator.data or {}
        return data.get("media_filename", "unknown")

    @property
    def extra_state_attributes(self) -> dict:
        """Return extra attributes."""
        data = self._coordinator.data or {}
        return {
            "media_localdatetime": data.get("media_localdatetime", ""),
            "media_width": data.get("media_width", ""),
            "media_height": data.get("media_height", ""),
        }
