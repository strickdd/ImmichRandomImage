"""Hub for the Immich Random Image integration."""
from __future__ import annotations

import logging
import ssl
from urllib.parse import urljoin

import aiohttp
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

_HEADER_API_KEY = "x-api-key"


def _create_ssl_context(verify_ssl: bool) -> ssl.SSLContext | bool:
    """Create an SSL context. If verify_ssl is False, create a context that doesn't verify."""
    if verify_ssl:
        return True  # Use default verification
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


class ImmichRandomHub:
    """Immich API hub for fetching random images."""

    def __init__(
        self,
        host: str,
        api_key: str,
        album_ids: list[str] | None = None,
        verify_ssl: bool = True,
        hass=None,
    ) -> None:
        """Initialize."""
        self.host = host
        self.api_key = api_key
        self.album_ids = album_ids or []
        self.verify_ssl = verify_ssl
        self._hass = hass

    def _get_session(self) -> aiohttp.ClientSession:
        """Get an aiohttp session. Uses HA's managed session when available."""
        if self._hass is not None:
            return async_get_clientsession(self._hass, verify_ssl=self.verify_ssl)
        # Fallback for when hass is not available (e.g. in tests)
        connector = aiohttp.TCPConnector(ssl=_create_ssl_context(self.verify_ssl))
        return aiohttp.ClientSession(connector=connector)

    async def authenticate(self) -> bool:
        """Test if we can authenticate with the host.

        Uses /api/auth/validateToken which requires no special permissions,
        making it compatible with API keys that have limited scopes.
        """
        try:
            session = self._get_session()
            url = urljoin(self.host, "/api/auth/validateToken")
            headers = {"Accept": "application/json", _HEADER_API_KEY: self.api_key}
            async with session.post(url=url, headers=headers) as response:
                if response.status in (401, 403):
                    _LOGGER.error("Auth failed: status=%d", response.status)
                    return False
                if response.status != 200:
                    # A 5xx (e.g. Immich still starting behind a proxy) is not
                    # a credentials problem; let the caller retry.
                    raise CannotConnect(f"Unexpected status {response.status}")
                result = await response.json()
                return result.get("authStatus", False)
        except (aiohttp.ClientError, TimeoutError) as exception:
            _LOGGER.error("Error connecting to the API: %s", exception)
            raise CannotConnect from exception

    async def list_all_albums(self) -> list[dict]:
        """List all albums."""
        try:
            session = self._get_session()
            url = urljoin(self.host, "/api/albums")
            headers = {"Accept": "application/json", _HEADER_API_KEY: self.api_key}
            async with session.get(url=url, headers=headers) as response:
                if response.status != 200:
                    raise ApiError()
                return await response.json()
        except aiohttp.ClientError as exception:
            raise CannotConnect from exception

    async def get_random_image(self) -> dict | None:
        """Get a random image from Immich using the v3 search/random endpoint.

        If album_ids is set, the random image is picked from those albums.
        Otherwise it's a fully random image from the entire library.
        """
        try:
            session = self._get_session()
            url = urljoin(self.host, "/api/search/random")
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                _HEADER_API_KEY: self.api_key,
            }
            payload: dict = {"size": 1, "type": "IMAGE"}
            if self.album_ids:
                payload["albumIds"] = self.album_ids

            async with session.post(
                url=url, headers=headers, json=payload
            ) as response:
                if response.status != 200:
                    _LOGGER.error(
                        "Random search failed: status=%d body=%s",
                        response.status,
                        await response.text(),
                    )
                    return None
                results = await response.json()
                if not results:
                    _LOGGER.warning("No images returned from random search")
                    return None
                return results[0]
        except aiohttp.ClientError as exception:
            _LOGGER.error("Error connecting to the API: %s", exception)
            raise CannotConnect from exception

    async def download_asset(self, asset_id: str) -> bytes | None:
        """Download the original image."""
        try:
            session = self._get_session()
            url = urljoin(self.host, f"/api/assets/{asset_id}/original")
            headers = {_HEADER_API_KEY: self.api_key}
            async with session.get(url=url, headers=headers) as response:
                if response.status != 200:
                    _LOGGER.error(
                        "Download failed: status=%d", response.status
                    )
                    return None
                return await response.read()
        except aiohttp.ClientError as exception:
            _LOGGER.error("Error connecting to the API: %s", exception)
            raise CannotConnect from exception

    async def get_asset_info(self, asset_id: str) -> dict | None:
        """Get asset metadata."""
        try:
            session = self._get_session()
            url = urljoin(self.host, f"/api/assets/{asset_id}")
            headers = {"Accept": "application/json", _HEADER_API_KEY: self.api_key}
            async with session.get(url=url, headers=headers) as response:
                if response.status != 200:
                    return None
                return await response.json()
        except aiohttp.ClientError as exception:
            raise CannotConnect from exception


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class ApiError(HomeAssistantError):
    """Error to indicate that the API returned an error."""
