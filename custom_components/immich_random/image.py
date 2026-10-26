"""Image platform for the Immich Random Image integration."""
from __future__ import annotations

import logging
from datetime import datetime

from homeassistant.components.image import ImageEntity
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
    """Set up the Immich Random image platform."""
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    coordinator: ImmichCoordinator = entry_data["coordinator"]

    _LOGGER.info(
        "Setting up Immich Random Image entity (host=%s, albums=%d, verify_ssl=%s)",
        coordinator.hub.host,
        len(coordinator.hub.album_ids),
        coordinator.hub.verify_ssl,
    )

    async_add_entities([ImmichRandomImageEntity(hass, coordinator, config_entry)])


class ImmichRandomImageEntity(CoordinatorEntity, ImageEntity):
    """Image entity that displays a random image from Immich."""


    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: ImmichCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the entity."""
        ImageEntity.__init__(self, hass=hass, verify_ssl=coordinator.hub.verify_ssl)
        CoordinatorEntity.__init__(self, coordinator)
        self._coordinator = coordinator
        self._config_entry = config_entry
        # Stable across album changes and scoped to the entry, so changing
        # albums never orphans the entity and two entries never collide.
        self._attr_unique_id = f"{config_entry.entry_id}_image"
        self._attr_name = entity_name(config_entry, "Random Image")

    async def async_update(self) -> None:
        """Fetch a new random image via the coordinator."""
        await self._coordinator.async_request_refresh()

    async def async_image(self) -> bytes | None:
        """Return the current image bytes."""
        if not self._coordinator.image_bytes:
            await self._coordinator.async_request_refresh()
        return self._coordinator.image_bytes

    @property
    def extra_state_attributes(self) -> dict:
        """Return entity state attributes from coordinator data."""
        data = self._coordinator.data or {}
        return {
            "media_filename": data.get("media_filename", ""),
            "media_localdatetime": data.get("media_localdatetime", ""),
            "media_width": data.get("media_width", ""),
            "media_height": data.get("media_height", ""),
        }

    @property
    def image_last_updated(self) -> datetime | None:
        """Return the last time the image was updated."""
        data = self._coordinator.data or {}
        last_pulled = data.get("last_pulled")
        if last_pulled:
            try:
                return datetime.fromisoformat(last_pulled)
            except (ValueError, TypeError):
                pass
        return None
