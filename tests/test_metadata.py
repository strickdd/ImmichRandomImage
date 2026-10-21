"""Repository metadata and HACS installation-link checks."""
import json
import re
import tomllib
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]


def test_project_uses_current_repository_name():
    """Package metadata uses the public repository's current name."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert project["name"] == "ImmichRandomImage"


def test_project_version_matches_integration():
    """Release metadata stays aligned with the installable integration."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    manifest = json.loads(
        (ROOT / "custom_components/immich_random/manifest.json").read_text()
    )
    assert project["version"] == manifest["version"]


def test_hacs_badge_targets_current_repository():
    """The install badge opens the actual repository in HACS."""
    urls = re.findall(
        r"https://my\.home-assistant\.io/redirect/hacs_repository/\?[^)\s]+",
        (ROOT / "README.md").read_text(),
    )
    assert urls
    for url in urls:
        query = parse_qs(urlparse(url).query)
        assert query["repository"] == ["ImmichRandomImage"]
        assert query["owner"] == ["strickdd"]
