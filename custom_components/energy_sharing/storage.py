"""Home Assistant storage wrapper for Energy Sharing."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.storage import Store

from .models import migrate_storage


class EnergySharingStore(Store[dict[str, Any]]):
    """Store with migration support for Energy Sharing persistence."""

    async def _async_migrate_func(
        self,
        old_major_version: int,
        old_minor_version: int,
        old_data: dict[str, Any],
    ) -> dict[str, Any]:
        inner_version = old_data.get("version", old_major_version)
        from_version = (
            inner_version if isinstance(inner_version, int) else old_major_version
        )
        return migrate_storage(old_data, from_version)
