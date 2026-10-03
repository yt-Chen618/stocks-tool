"""Committed lock for the official open-source LEAN Engine image.

The image is pinned by the platform-specific manifest digest rather than a
mutable tag.  The metadata below was read from Docker Hub's public registry
API on 2026-10-04.  A formal run may use a different digest only when the
operator explicitly provisions it through ``LEAN_IMAGE_DIGEST``; the service
records that value in its run manifest and still rejects tags.
"""

LEAN_ENGINE_IMAGE_REPOSITORY = "quantconnect/lean"
LEAN_ENGINE_IMAGE_TAG = "18100"
LEAN_ENGINE_IMAGE_PLATFORM = "linux/amd64"
LEAN_ENGINE_IMAGE_DIGEST = "sha256:7c3ffad966d62bf636d8b501e06cd94420faa6527229241a724fdd8ce8a6ea43"
LEAN_ENGINE_VERSION = "18100"
LEAN_ENGINE_SOURCE_URL = "https://github.com/QuantConnect/Lean"
LEAN_ENGINE_METADATA_URL = "https://registry.hub.docker.com/v2/repositories/quantconnect/lean/tags/18100"
LEAN_ENGINE_METADATA_OBSERVED = "2026-10-04"


def is_full_digest(value: str | None) -> bool:
    return bool(
        value
        and value.startswith("sha256:")
        and len(value) == 71
        and all(character in "0123456789abcdef" for character in value[7:].lower())
    )
