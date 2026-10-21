"""Tests for URL normalization and SSL context — no HA imports needed."""
import ssl
import sys
from unittest.mock import MagicMock, patch

import pytest

# We need to stub out homeassistant before importing our module,
# since HA isn't installed in the test environment.
# We stub only the top-level package; our modules import submodules directly.


def _setup_ha_stubs():
    """Create minimal homeassistant stubs for testing without HA installed."""
    _ha_stubs = [
        "homeassistant",
        "homeassistant.config_entries",
        "homeassistant.const",
        "homeassistant.core",
        "homeassistant.exceptions",
        "homeassistant.helpers",
        "homeassistant.helpers.aiohttp_client",
        "homeassistant.helpers.config_validation",
        "homeassistant.helpers.entity_platform",
        "homeassistant.helpers.selector",
        "homeassistant.helpers.update_coordinator",
        "homeassistant.components",
        "homeassistant.components.image",
        "homeassistant.data_entry_flow",
    ]
    for name in _ha_stubs:
        if name not in sys.modules:
            sys.modules[name] = MagicMock()


_setup_ha_stubs()

from custom_components.immich_random.config_flow import _normalize_host  # noqa: E402
from custom_components.immich_random.hub import (  # noqa: E402
    ImmichRandomHub,
    _create_ssl_context,
)

# ── URL normalization ──────────────────────────────────────────────


def test_normalize_host_adds_https():
    """Bare hostnames get https:// prefix."""
    assert _normalize_host("immich.local") == "https://immich.local"
    assert _normalize_host("localhost:8080") == "https://localhost:8080"
    assert _normalize_host("127.0.0.1:8123") == "https://127.0.0.1:8123"
    assert _normalize_host("172.16.66.5") == "https://172.16.66.5"


def test_normalize_host_keeps_http():
    """http:// URLs are kept as-is (for localhost without TLS)."""
    assert _normalize_host("http://immich.local") == "http://immich.local"
    assert _normalize_host("http://localhost:8080") == "http://localhost:8080"
    assert _normalize_host("http://127.0.0.1:8123") == "http://127.0.0.1:8123"


def test_normalize_host_keeps_https():
    """https:// URLs are kept as-is."""
    assert _normalize_host("https://pics.sasquatch.dev") == "https://pics.sasquatch.dev"
    assert _normalize_host("https://immich.example.com:443") == "https://immich.example.com:443"


def test_normalize_host_strips_trailing_slash():
    """Trailing slashes are stripped."""
    assert _normalize_host("https://immich.local/") == "https://immich.local"
    assert _normalize_host("https://immich.local///") == "https://immich.local"


def test_normalize_host_domain_names():
    """Full domain names work correctly."""
    assert _normalize_host("immich.example.com") == "https://immich.example.com"
    assert _normalize_host("immich.subdomain.example.com") == "https://immich.subdomain.example.com"


def test_normalize_host_private_ip():
    """Private IP addresses work."""
    assert _normalize_host("10.0.0.5") == "https://10.0.0.5"
    assert _normalize_host("192.168.1.100") == "https://192.168.1.100"
    assert _normalize_host("172.16.0.1") == "https://172.16.0.1"


# ── SSL context ───────────────────────────────────────────────────


def test_ssl_context_verify_true():
    """When verify_ssl is True, returns True (default verification)."""
    result = _create_ssl_context(verify_ssl=True)
    assert result is True


def test_ssl_context_verify_false():
    """When verify_ssl is False, returns an SSLContext with verification disabled."""
    result = _create_ssl_context(verify_ssl=False)
    assert isinstance(result, ssl.SSLContext)
    assert result.check_hostname is False
    assert result.verify_mode == ssl.CERT_NONE


def test_ssl_context_verify_false_is_different_from_true():
    """The unverified context is distinct from the default True value."""
    verified = _create_ssl_context(verify_ssl=True)
    unverified = _create_ssl_context(verify_ssl=False)
    assert verified is True
    assert isinstance(unverified, ssl.SSLContext)


# ── Hub initialization ────────────────────────────────────────────


def test_hub_init_defaults():
    """Hub initializes with correct defaults."""
    hub = ImmichRandomHub(host="https://immich.local", api_key="test-key")
    assert hub.host == "https://immich.local"
    assert hub.api_key == "test-key"
    assert hub.album_ids == []
    assert hub.verify_ssl is True


def test_hub_init_with_albums():
    """Hub stores album IDs correctly."""
    hub = ImmichRandomHub(
        host="https://immich.local",
        api_key="test-key",
        album_ids=["album-1", "album-2"],
    )
    assert hub.album_ids == ["album-1", "album-2"]


def test_hub_init_with_ssl_disabled():
    """Hub stores SSL setting correctly."""
    hub = ImmichRandomHub(
        host="https://immich.local",
        api_key="test-key",
        verify_ssl=False,
    )
    assert hub.verify_ssl is False


def test_hub_init_empty_album_ids():
    """Empty album_ids list is treated as no albums (random from all)."""
    hub = ImmichRandomHub(
        host="https://immich.local",
        api_key="test-key",
        album_ids=[],
    )
    assert hub.album_ids == []


@pytest.mark.parametrize("hass", [None, object()])
def test_hub_initialization_does_not_load_certificates(hass):
    """Constructing a hub never reads the CA store, even without HA."""
    with patch(
        "custom_components.immich_random.hub.ssl.create_default_context",
        side_effect=AssertionError("Certificate store read during hub construction"),
    ):
        ImmichRandomHub(
            host="https://immich.local",
            api_key="test-key",
            verify_ssl=False,
            hass=hass,
        )


@pytest.mark.parametrize("verify_ssl", [True, False])
@pytest.mark.asyncio
async def test_fallback_session_creates_ssl_context_only_when_requested(verify_ssl):
    """The no-HA fallback still configures TLS, but only at session creation."""
    with patch(
        "custom_components.immich_random.hub._create_ssl_context",
        wraps=_create_ssl_context,
    ) as create_context:
        hub = ImmichRandomHub(
            host="https://immich.local",
            api_key="test-key",
            verify_ssl=verify_ssl,
        )
        create_context.assert_not_called()
        async with hub._get_session() as session:
            assert not session.closed
            create_context.assert_called_once_with(verify_ssl)
        assert session.closed
