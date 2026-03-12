"""CSAT 2028 mathematics plugin."""

from __future__ import annotations

from src.config.settings import get_settings
from src.core.schemas import ExamBlueprint, ExamSpec
from src.core.specs import load_exam_spec, resolve_spec_path


class CSATMath2028Plugin:
    """Plugin for the 2028 CSAT mathematics MVP."""

    plugin_id = "csat_math_2028"
    spec_id = "csat_math_2028"

    def load_exam_spec(self) -> ExamSpec:
        """Load the canonical exam spec from the repository."""
        settings = get_settings()
        spec_path = resolve_spec_path(self.spec_id, settings.exam_specs_dir)
        return load_exam_spec(spec_path)

    def build_default_blueprint(self) -> ExamBlueprint:
        """Create the default blueprint directly from the validated exam spec."""
        exam_spec = self.load_exam_spec()
        return ExamBlueprint(
            spec_id=exam_spec.spec_id,
            notes=[
                "Derived from exam_specs/csat_math_2028.yaml",
                "Manual and API modes share PromptPacket/ManualExchangePacket contracts",
            ],
            item_blueprints=[item.model_copy(deep=True) for item in exam_spec.default_item_blueprints],
        )
