"""Tests for the public plugin registry boundary."""

from __future__ import annotations

import pytest

from src.plugins import get_plugin, list_available_plugins


class _FakeEntryPoint:
    def __init__(self, name: str, loaded: object) -> None:
        self.name = name
        self._loaded = loaded

    def load(self) -> object:
        return self._loaded


def test_builtin_plugin_is_listed_and_loadable() -> None:
    assert "csat_math_2028" in list_available_plugins()

    plugin = get_plugin("csat_math_2028")

    assert plugin.spec_id == "csat_math_2028"
    assert plugin.plugin_id == "csat_math_2028"


def test_external_plugin_can_be_loaded_from_entry_points(monkeypatch: pytest.MonkeyPatch) -> None:
    class PrivateExamPlugin:
        plugin_id = "private_exam_2030"
        spec_id = "private_exam_2030"

        def load_exam_spec(self):  # pragma: no cover - registry test only
            raise NotImplementedError

        def build_default_blueprint(self):  # pragma: no cover - registry test only
            raise NotImplementedError

    monkeypatch.setattr(
        "src.plugins._external_plugin_entry_points",
        lambda: (_FakeEntryPoint("private_exam_2030", PrivateExamPlugin),),
    )

    plugin = get_plugin("private_exam_2030")

    assert plugin.spec_id == "private_exam_2030"
    assert "private_exam_2030" in list_available_plugins()


def test_external_plugin_spec_id_must_match(monkeypatch: pytest.MonkeyPatch) -> None:
    class WrongPlugin:
        plugin_id = "wrong_plugin"
        spec_id = "wrong_spec"

        def load_exam_spec(self):  # pragma: no cover - registry test only
            raise NotImplementedError

        def build_default_blueprint(self):  # pragma: no cover - registry test only
            raise NotImplementedError

    monkeypatch.setattr(
        "src.plugins._external_plugin_entry_points",
        lambda: (_FakeEntryPoint("private_exam_2030", WrongPlugin),),
    )

    with pytest.raises(ValueError, match="mismatched spec_id"):
        get_plugin("private_exam_2030")
