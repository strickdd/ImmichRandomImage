"""Constants for the Immich Random Image integration."""

DOMAIN = "immich_random"

# Config entry data keys
CONF_ALBUM_IDS = "album_ids"
CONF_VERIFY_SSL = "verify_ssl"

# Options keys
OPT_ALBUM_IDS = "album_ids"
OPT_VERIFY_SSL = "verify_ssl"
OPT_SCAN_INTERVAL = "scan_interval"

# Default scan interval in seconds (5 minutes)
DEFAULT_SCAN_INTERVAL = 300

# Recommended range for scan interval
MIN_SCAN_INTERVAL = 0  # Manual-only rotation
MAX_SCAN_INTERVAL = 86400  # 24 hours
RECOMMENDED_MIN_SCAN_INTERVAL = 60
RECOMMENDED_MAX_SCAN_INTERVAL = 300

# Service: manual refresh
SERVICE_REFRESH = "refresh"
ATTR_ENTRY_ID = "entry_id"
