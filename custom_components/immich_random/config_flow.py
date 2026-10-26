"""Config flow for the Immich Random Image integration."""
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_NAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_ALBUM_IDS,
    CONF_VERIFY_SSL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .hub import CannotConnect, ImmichRandomHub, InvalidAuth

_LOGGER = logging.getLogger(__name__)


def _normalize_host(host: str) -> str:
    """Normalize a host URL.

    Handles:
      - Bare hostnames (e.g. hass.local) -> https://hass.local
      - localhost / 127.0.0.1 / 172.x private IPs
      - Full domain names (e.g. https://pics.sasquatch.dev)
      - Trailing slashes stripped
    """
    if not host.startswith("http://") and not host.startswith("https://"):
        host = "https://" + host
    return host.rstrip("/")


async def validate_input(hass, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input and return normalized data."""
    url = _normalize_host(data[CONF_HOST])
    api_key = data[CONF_API_KEY]
    verify_ssl = data.get(CONF_VERIFY_SSL, True)

    hub = ImmichRandomHub(host=url, api_key=api_key, verify_ssl=verify_ssl, hass=hass)
    if not await hub.authenticate():
        raise InvalidAuth

    hostname = urlparse(url).hostname

    return {
        "title": f"Immich @ {hostname}",
        "data": {
            CONF_HOST: url,
            CONF_API_KEY: api_key,
            CONF_VERIFY_SSL: verify_ssl,
        },
    }


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Immich Random Image."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._credentials: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1: enter host, API key, and SSL toggle."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                result = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                # Store validated credentials for the album step
                self._credentials = result["data"]
                self._credentials[CONF_NAME] = user_input.get(CONF_NAME, "").strip()
                return await self.async_step_album()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_NAME): str,
                    vol.Required(CONF_HOST): str,
                    vol.Required(CONF_API_KEY): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Optional(CONF_VERIFY_SSL, default=True): bool,
                }
            ),
            errors=errors,
        )

    async def async_step_album(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2: select which albums to pull random images from.

        Fetches the album list from Immich using the validated credentials
        from step 1. The user can select zero, one, or multiple albums.
        Leave all unchecked for a fully random image from the entire library.
        """
        if user_input is not None:
            data = dict(self._credentials)
            data[CONF_ALBUM_IDS] = user_input.get(CONF_ALBUM_IDS, [])
            hostname = urlparse(self._credentials[CONF_HOST]).hostname
            return self.async_create_entry(
                title=data.get(CONF_NAME) or f"Immich @ {hostname}", data=data
            )

        # Fetch albums using the validated credentials
        hub = ImmichRandomHub(
            host=self._credentials[CONF_HOST],
            api_key=self._credentials[CONF_API_KEY],
            verify_ssl=self._credentials.get(CONF_VERIFY_SSL, True),
            hass=self.hass,
        )
        try:
            _LOGGER.info("Fetching albums for config flow album selection step")
            albums = await hub.list_all_albums()
            _LOGGER.info("Fetched %d albums from Immich", len(albums))
        except Exception as err:
            _LOGGER.warning("Failed to fetch albums during setup: %s — skipping album step", err)
            # Skip album selection and create the entry directly
            data = dict(self._credentials)
            data[CONF_ALBUM_IDS] = []
            hostname = urlparse(self._credentials[CONF_HOST]).hostname
            return self.async_create_entry(
                title=data.get(CONF_NAME) or f"Immich @ {hostname}", data=data
            )

        album_map = {album["id"]: album["albumName"] for album in albums}

        if not album_map:
            # No albums available — skip this step
            data = dict(self._credentials)
            data[CONF_ALBUM_IDS] = []
            hostname = urlparse(self._credentials[CONF_HOST]).hostname
            return self.async_create_entry(
                title=data.get(CONF_NAME) or f"Immich @ {hostname}", data=data
            )

        return self.async_show_form(
            step_id="album",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_ALBUM_IDS, default=[]): cv.multi_select(
                        album_map
                    ),
                }
            ),
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> FlowResult:
        """Start reauth when Immich rejects the stored API key."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask for a new API key and validate it against the stored host."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()
        if user_input is not None:
            try:
                await validate_input(
                    self.hass,
                    {
                        CONF_HOST: reauth_entry.data[CONF_HOST],
                        CONF_API_KEY: user_input[CONF_API_KEY],
                        CONF_VERIFY_SSL: reauth_entry.data.get(CONF_VERIFY_SSL, True),
                    },
                )
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data_updates={CONF_API_KEY: user_input[CONF_API_KEY]},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
            description_placeholders={"host": reauth_entry.data[CONF_HOST]},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlowHandler:
        """Create the options flow."""
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Options flow for editing connection settings and selecting albums."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options: host, API key, SSL, albums, scan interval.

        The API key field is shown empty for security. If left empty,
        the existing key is kept. If a new key is entered, it's validated
        before saving.
        """
        if user_input is not None:
            return await self._save_options(user_input)

        return await self._show_form()

    async def _save_options(self, user_input: dict[str, Any]) -> FlowResult:
        """Validate and save the options."""
        # Determine which API key to use: new one if provided, else existing
        new_api_key = user_input.get(CONF_API_KEY, "").strip()
        current_api_key = self.config_entry.data.get(CONF_API_KEY, "")
        api_key = new_api_key if new_api_key else current_api_key

        url = _normalize_host(user_input[CONF_HOST])
        verify_ssl = user_input.get(CONF_VERIFY_SSL, True)

        # Validate the connection with these credentials
        try:
            hub = ImmichRandomHub(
                host=url,
                api_key=api_key,
                verify_ssl=verify_ssl,
                hass=self.hass,
            )
            if not await hub.authenticate():
                _LOGGER.warning("Options flow: authentication failed")
                return await self._show_form(
                    errors={"base": "invalid_auth"},
                    submitted_input=user_input,
                )
        except CannotConnect:
            return await self._show_form(
                errors={"base": "cannot_connect"},
                submitted_input=user_input,
            )

        # Check if album selection changed
        old_albums = set(
            self.config_entry.options.get(
                CONF_ALBUM_IDS, self.config_entry.data.get(CONF_ALBUM_IDS, [])
            )
        )
        new_albums = set(user_input.get(CONF_ALBUM_IDS, []))
        albums_changed = old_albums != new_albums

        # Build the new data dict (host, API key, verify_ssl)
        new_data = dict(self.config_entry.data)
        new_data[CONF_HOST] = url
        new_data[CONF_VERIFY_SSL] = verify_ssl
        if new_api_key:
            new_data[CONF_API_KEY] = new_api_key

        # Build options dict
        options = {
            CONF_VERIFY_SSL: verify_ssl,
            "scan_interval": user_input.get("scan_interval", DEFAULT_SCAN_INTERVAL),
            CONF_ALBUM_IDS: user_input.get(CONF_ALBUM_IDS, []),
        }

        _LOGGER.info(
            "Saving options: host=%s, key_changed=%s, albums_changed=%s, "
            "scan_interval=%ss",
            url,
            bool(new_api_key),
            albums_changed,
            options["scan_interval"],
        )

        # Update the config entry with new data and options
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data=new_data,
            options=options,
        )

        # If albums changed, update the hub immediately so the next poll
        # uses the new album set without waiting for a full reload
        if albums_changed:
            _LOGGER.info("Album selection changed, forcing image refresh")
            entry_data = self.hass.data.get(DOMAIN, {}).get(
                self.config_entry.entry_id
            )
            if entry_data and "hub" in entry_data:
                hub_obj = entry_data["hub"]
                hub_obj.album_ids = options[CONF_ALBUM_IDS]
                hub_obj.verify_ssl = verify_ssl

        return self.async_create_entry(title="", data=options)

    async def _show_form(
        self,
        errors: dict[str, str] | None = None,
        submitted_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Show the options form.

        The API key field is always shown empty for security.
        A description tells the user to leave it empty to keep the current key.
        """
        if submitted_input is not None:
            host = submitted_input.get(CONF_HOST, "")
            verify_ssl = submitted_input.get(CONF_VERIFY_SSL, True)
            scan_interval = submitted_input.get(
                "scan_interval", DEFAULT_SCAN_INTERVAL
            )
            current_albums = submitted_input.get(CONF_ALBUM_IDS, [])
        else:
            host = self.config_entry.data.get(CONF_HOST, "")
            verify_ssl = self.config_entry.options.get(
                CONF_VERIFY_SSL,
                self.config_entry.data.get(CONF_VERIFY_SSL, True),
            )
            scan_interval = self.config_entry.options.get(
                "scan_interval", DEFAULT_SCAN_INTERVAL
            )
            current_albums = self.config_entry.options.get(
                CONF_ALBUM_IDS, self.config_entry.data.get(CONF_ALBUM_IDS, [])
            )

        # Fetch albums for the picker using the current stored API key
        current_api_key = self.config_entry.data.get(CONF_API_KEY, "")
        try:
            albums = await self._get_albums(current_api_key, host, verify_ssl)
        except Exception:
            _LOGGER.warning("Failed to fetch albums for options flow")
            albums = []

        album_map = {album["id"]: album["albumName"] for album in albums}
        current_albums = [a for a in current_albums if a in album_map]

        # Build schema — API key is optional and uses password selector
        schema_dict: dict = {
            vol.Required(CONF_HOST, default=host): str,
            vol.Optional(CONF_API_KEY, description="Leave empty to keep current key"): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
            vol.Optional(CONF_VERIFY_SSL, default=verify_ssl): bool,
            vol.Optional(
                "scan_interval",
                default=scan_interval,
            ): vol.All(vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)),
        }

        if album_map:
            schema_dict[
                vol.Optional(CONF_ALBUM_IDS, default=current_albums)
            ] = cv.multi_select(album_map)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema_dict),
            errors=errors or {},
        )

    async def _get_albums(
        self, api_key: str, host: str, verify_ssl: bool
    ) -> list[dict]:
        """Fetch the list of albums from Immich."""
        url = _normalize_host(host)
        hub = ImmichRandomHub(
            host=url, api_key=api_key, verify_ssl=verify_ssl, hass=self.hass
        )
        return await hub.list_all_albums()
