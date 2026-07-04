from typing import Optional

from core.adapters.base import PlatformAdapter

_registry: dict[str, PlatformAdapter] = {}


def register_adapter(adapter: PlatformAdapter) -> None:
    _registry[adapter.platform] = adapter


def get_adapter(platform: str) -> Optional[PlatformAdapter]:
    return _registry.get(platform)


def list_adapters() -> list[str]:
    return sorted(_registry.keys())
