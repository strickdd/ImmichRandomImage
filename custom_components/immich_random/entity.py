"""Shared entity naming defaults, independent of registry identity."""
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME


def entity_name(entry: ConfigEntry, suffix: str) -> str:
    """Prefix defaults without changing IDs or overriding registry names."""
    base = entry.data.get(CONF_NAME, "").strip() or "Immich"
    return f"{base} {suffix}"
