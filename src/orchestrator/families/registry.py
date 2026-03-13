"""Auto-discovery for modular deterministic real-item families."""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from types import ModuleType

from src.orchestrator.families.base import RealItemFamily, RealItemFamilyRegistry

_SKIP_MODULES = {"base", "registry"}


def _families_from_module(module: ModuleType) -> tuple[RealItemFamily, ...]:
    if hasattr(module, "FAMILY"):
        return (getattr(module, "FAMILY"),)
    if hasattr(module, "FAMILIES"):
        return tuple(getattr(module, "FAMILIES"))
    raise ValueError(
        f"Family module '{module.__name__}' must define FAMILY or FAMILIES for auto-discovery"
    )


def discover_real_item_families() -> tuple[RealItemFamily, ...]:
    """Import every family module under this package and return discovered families."""

    discovered: list[RealItemFamily] = []
    package_name = __package__
    module_root = [str(Path(__file__).resolve().parent)]
    for module_info in sorted(pkgutil.iter_modules(module_root), key=lambda item: item.name):
        if module_info.name.startswith("_") or module_info.name in _SKIP_MODULES:
            continue
        module = importlib.import_module(f"{package_name}.{module_info.name}")
        discovered.extend(_families_from_module(module))
    return tuple(discovered)


def build_real_item_family_registry() -> RealItemFamilyRegistry:
    """Build the deterministic real-item family registry from discovered modules."""

    return RealItemFamilyRegistry(discover_real_item_families())
