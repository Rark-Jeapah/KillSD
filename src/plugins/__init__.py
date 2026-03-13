"""Subject plugin registry and extension boundary."""

from __future__ import annotations

from importlib.metadata import EntryPoint, entry_points
from typing import Protocol

from src.core.schemas import ExamBlueprint, ExamSpec


PLUGIN_ENTRY_POINT_GROUP = "csat_math_mvp.plugins"


class SubjectPlugin(Protocol):
    """Protocol implemented by subject-specific exam plugins."""

    plugin_id: str
    spec_id: str

    def load_exam_spec(self) -> ExamSpec:
        """Load and validate the exam specification."""

    def build_default_blueprint(self) -> ExamBlueprint:
        """Build the default blueprint for the subject/exam."""


def _builtin_plugins() -> dict[str, type[SubjectPlugin]]:
    from src.plugins.csat_math_2028 import CSATMath2028Plugin

    return {"csat_math_2028": CSATMath2028Plugin}


def _external_plugin_entry_points() -> tuple[EntryPoint, ...]:
    discovered = entry_points()
    if hasattr(discovered, "select"):
        return tuple(discovered.select(group=PLUGIN_ENTRY_POINT_GROUP))
    return tuple(discovered.get(PLUGIN_ENTRY_POINT_GROUP, ()))


def list_available_plugins() -> tuple[str, ...]:
    """Return all built-in and externally registered plugin spec ids."""
    names = set(_builtin_plugins())
    names.update(entry_point.name for entry_point in _external_plugin_entry_points())
    return tuple(sorted(names))


def _load_external_plugin(spec_id: str) -> SubjectPlugin | None:
    matches = [entry_point for entry_point in _external_plugin_entry_points() if entry_point.name == spec_id]
    if not matches:
        return None
    if len(matches) > 1:
        raise ValueError(f"Multiple plugins registered for spec_id: {spec_id}")

    loaded = matches[0].load()
    plugin = loaded() if isinstance(loaded, type) else loaded
    if getattr(plugin, "spec_id", None) != spec_id:
        raise ValueError(
            f"Registered plugin for {spec_id} returned mismatched spec_id: {getattr(plugin, 'spec_id', None)}"
        )
    return plugin


def get_plugin(spec_id: str) -> SubjectPlugin:
    """Resolve a plugin by exam specification id.

    Public plugins can live in this repository or in separately installed packages
    registered through the ``csat_math_mvp.plugins`` entry-point group.
    """
    builtin_plugin = _builtin_plugins().get(spec_id)
    if builtin_plugin is not None:
        return builtin_plugin()

    external_plugin = _load_external_plugin(spec_id)
    if external_plugin is not None:
        return external_plugin

    available = ", ".join(list_available_plugins()) or "<none>"
    raise ValueError(f"Unsupported spec_id: {spec_id}. Available plugins: {available}")
