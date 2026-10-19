"""Data update coordinator for the Immich Random Image integration."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .hub import CannotConnect, ImmichRandomHub

_LOGGER = logging.getLogger(__name__)


class ImmichCoordinator(DataUpdateCoordinator):
    """Coordinator that fetches random images and shares data across entities.

    Exposes:
      - last_updated: when the last image was pulled
      - media_filename: the original filename
      - media_localdatetime: when the photo was taken
      - media_width / media_height: image dimensions
      - image_bytes: the raw image data (for the image entity)
      - album_ids: current album selection (mutable from select entity)
      - albums: the list of available albums (for the select entity options)
    """

    def __init__(
        self,
        hass: HomeAssistant,
        hub: ImmichRandomHub,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        self.hub = hub
        self.config_entry = config_entry
        self.image_bytes: bytes | None = None
        self.albums: list[dict] = []

        scan_interval = config_entry.options.get(
            "scan_interval", DEFAULT_SCAN_INTERVAL
        )

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{config_entry.entry_id[:8]}",
            update_interval=None,  # We poll manually or on scan interval
            update_method=self._async_update_data,
        )
        self._scan_interval_seconds = int(scan_interval)

    @property
    def scan_interval_seconds(self) -> int:
        """Return the configured scan interval in seconds."""
        return self._scan_interval_seconds

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch a new random image from Immich.

        Returns a dict with the latest image metadata.
        The raw image bytes are stored in self.image_bytes.
        """
        _LOGGER.debug("Coordinator fetching new random image from %s", self.hub.host)

        try:
            return await self._async_fetch_random_image()
        except CannotConnect as err:
            raise UpdateFailed(f"Error communicating with Immich: {err}") from err

    async def _async_fetch_random_image(self) -> dict[str, Any]:
        """Fetch and download one random image; keep the old data on a miss."""
        asset = await self.hub.get_random_image()
        if not asset:
            _LOGGER.warning("No random image returned from Immich")
            return self.data or {}

        asset_id = asset.get("id")
        if not asset_id:
            _LOGGER.warning("Random image returned without an asset ID")
            return self.data or {}

        _LOGGER.debug(
            "Got random image: id=%s, file=%s",
            asset_id,
            asset.get("originalFileName", "?"),
        )

        image_bytes = await self.hub.download_asset(asset_id)
        if not image_bytes:
            _LOGGER.warning("Failed to download image %s from Immich", asset_id)
            return self.data or {}

        self.image_bytes = image_bytes

        data: dict[str, Any] = {
            "asset_id": asset_id,
            "media_filename": asset.get("originalFileName", ""),
            "media_localdatetime": asset.get("localDateTime", ""),
            "media_width": asset.get("width", ""),
            "media_height": asset.get("height", ""),
            "last_pulled": datetime.now().isoformat(),
        }

        _LOGGER.info(
            "Updated Immich random image: %s (%sx%s, %s)",
            data["media_filename"],
            data["media_width"],
            data["media_height"],
            data["media_localdatetime"],
        )

        return data

    async def async_refresh_albums(self) -> None:
        """Fetch the list of available albums from Immich."""
        try:
            self.albums = await self.hub.list_all_albums()
            _LOGGER.debug("Fetched %d albums from Immich", len(self.albums))
        except Exception as err:
            _LOGGER.warning("Failed to fetch albums: %s", err)
            self.albums = []

    async def async_set_album_ids(self, album_ids: list[str]) -> None:
        """Update the active album selection (called by the select entity)."""
        self.hub.album_ids = album_ids
        _LOGGER.info("Album selection updated to %d albums, refreshing", len(album_ids))
        await self.async_request_refresh()
