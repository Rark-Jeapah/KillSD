"""Manual-mode helpers for prompt export and response import."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from src.core.schemas import ExchangeStatus, ManualExchangePacket, PromptPacket, utc_now

T = TypeVar("T", bound=BaseModel)


class ManualModeError(Exception):
    """Raised when manual-mode exchange files are invalid."""


class ManualModeController:
    """Export prompt packets and import pasted manual responses."""

    def __init__(self, exchange_root: Path) -> None:
        self.exchange_root = exchange_root

    def export_packet(self, packet: PromptPacket) -> Path:
        """Write a prompt packet to a stable manual exchange file."""
        path = self.packet_path_for(packet)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(packet.model_dump_json(indent=2), encoding="utf-8")
        return path

    def packet_path_for(self, packet: PromptPacket) -> Path:
        """Return the canonical packet file path for a prompt packet."""
        item_label = f"item_{packet.item_no}" if packet.item_no is not None else "exam"
        file_name = f"{packet.stage_name}__{item_label}__attempt_{packet.attempt}.packet.json"
        return self.exchange_root / packet.run_id / file_name

    def response_path_for(self, packet: PromptPacket) -> Path:
        """Return the recommended response file path for a prompt packet."""
        return self.packet_path_for(packet).with_suffix("").with_suffix(".response.json")

    def submitted_path_for(self, packet: PromptPacket) -> Path:
        """Return the archival path for an imported manual exchange."""
        return self.packet_path_for(packet).with_suffix("").with_suffix(".submitted.json")

    def import_response(
        self,
        *,
        packet_path: Path,
        response_path: Path,
        model_type: type[T],
    ) -> tuple[PromptPacket, T, ManualExchangePacket]:
        """Validate a pasted manual response against the expected output model."""
        if not packet_path.exists():
            raise ManualModeError(f"Packet file not found: {packet_path}")
        if not response_path.exists():
            raise ManualModeError(f"Response file not found: {response_path}")

        try:
            packet = PromptPacket.model_validate(
                json.loads(packet_path.read_text(encoding="utf-8"))
            )
            response_payload = json.loads(response_path.read_text(encoding="utf-8"))
            validated_output = model_type.model_validate(response_payload)
        except Exception as exc:
            raise ManualModeError("Manual response failed schema validation") from exc

        exchange = ManualExchangePacket(
            prompt_packet=packet,
            submitted_output=validated_output.model_dump(mode="json"),
            status=ExchangeStatus.SUBMITTED,
            responded_at=utc_now(),
        )
        submitted_path = self.submitted_path_for(packet)
        submitted_path.parent.mkdir(parents=True, exist_ok=True)
        submitted_path.write_text(exchange.model_dump_json(indent=2), encoding="utf-8")
        return packet, validated_output, exchange
