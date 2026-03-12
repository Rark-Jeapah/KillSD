"""Similarity validator for surface, expression, and solution-graph overlap."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from hashlib import blake2b

from src.core.schemas import (
    FailureLevel,
    SolvedItem,
    ValidationFinding,
    ValidationSeverity,
)
from src.distill.fingerprint import ItemFingerprint, normalize_text
from src.distill.item_card_schema import ItemCard
from src.distill.solution_graph import SolutionGraph
from src.validators import reason_codes as rc
from src.validators.report import SimilarityThresholdConfig, ValidatorSectionResult


EXPR_PATTERN = re.compile(r"[A-Za-z0-9_+\-*/^=()]+")


def _sequence_similarity(left: str, right: str) -> float:
    return SequenceMatcher(a=left, b=right).ratio()


def _expression_signature(text: str) -> str:
    expressions = sorted(expr for expr in EXPR_PATTERN.findall(text) if any(ch.isdigit() for ch in expr) or any(ch in "+-*/^=" for ch in expr))
    return " ".join(expressions)


def _solution_graph_signature_from_item(solved_item: SolvedItem) -> set[str]:
    hashes: set[str] = set()
    previous = None
    for step in solved_item.solution_steps:
        token = normalize_text(step)
        node_hash = blake2b(token.encode("utf-8"), digest_size=6).hexdigest()
        hashes.add(node_hash)
        if previous is not None:
            edge_hash = blake2b(f"{previous}>{token}".encode("utf-8"), digest_size=6).hexdigest()
            hashes.add(edge_hash)
        previous = token
    return hashes


def _solution_graph_signature(graph: SolutionGraph) -> set[str]:
    hashes: set[str] = set()
    for node in graph.nodes:
        token = normalize_text(f"{node.label} {node.technique} {node.content}")
        hashes.add(blake2b(token.encode("utf-8"), digest_size=6).hexdigest())
    for edge in graph.edges:
        hashes.add(blake2b(f"{edge.from_node}>{edge.to_node}".encode("utf-8"), digest_size=6).hexdigest())
    return hashes


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _threshold_result(score: float, *, soft: float, hard: float) -> tuple[bool, FailureLevel | None]:
    if score >= hard:
        return False, FailureLevel.HARD
    if score >= soft:
        return False, FailureLevel.SOFT
    return True, None


def validate_similarity(
    *,
    solved_item: SolvedItem,
    existing_item_cards: list[ItemCard],
    existing_fingerprints: list[ItemFingerprint],
    existing_solution_graphs: list[SolutionGraph],
    thresholds: SimilarityThresholdConfig,
) -> ValidatorSectionResult:
    """Check whether the item is too close to existing distilled material."""
    stem_text = normalize_text(solved_item.draft.stem)
    expression_text = _expression_signature(
        " ".join([solved_item.draft.stem, " ".join(solved_item.draft.choices)])
    )
    solution_signature = _solution_graph_signature_from_item(solved_item)

    best_surface = (0.0, None)
    for item_card in existing_item_cards:
        score = _sequence_similarity(stem_text, normalize_text(item_card.stem))
        if score > best_surface[0]:
            best_surface = (score, item_card.source_item_id)

    best_expression = (0.0, None)
    if expression_text:
        for item_card in existing_item_cards:
            source_expression_text = _expression_signature(
                " ".join([item_card.stem, " ".join(item_card.choices)])
            )
            if not source_expression_text:
                continue
            score = _sequence_similarity(expression_text, source_expression_text)
            if score > best_expression[0]:
                best_expression = (score, item_card.source_item_id)

    best_graph = (0.0, None)
    for graph in existing_solution_graphs:
        score = _jaccard(solution_signature, _solution_graph_signature(graph))
        if score > best_graph[0]:
            best_graph = (score, graph.source_item_id)

    surface_pass, surface_level = _threshold_result(
        best_surface[0],
        soft=thresholds.surface_soft_fail,
        hard=thresholds.surface_hard_fail,
    )
    expression_pass, expression_level = _threshold_result(
        best_expression[0],
        soft=thresholds.expression_soft_fail,
        hard=thresholds.expression_hard_fail,
    )
    graph_pass, graph_level = _threshold_result(
        best_graph[0],
        soft=thresholds.solution_graph_soft_fail,
        hard=thresholds.solution_graph_hard_fail,
    )

    findings = [
        ValidationFinding(
            check_name="surface_similarity",
            validator_name="similarity_validator",
            passed=surface_pass,
            severity=ValidationSeverity.ERROR if surface_level == FailureLevel.HARD else ValidationSeverity.WARNING,
            message="surface-level stem similarity stays below the configured threshold",
            reason_code=rc.SIMILARITY_SURFACE_TOO_HIGH.code,
            failure_level=surface_level or FailureLevel.SOFT,
            recommendation="Regenerate the item with a different wording and structure."
            if not surface_pass
            else None,
            context={"score": round(best_surface[0], 4), "matched_source_item_id": best_surface[1]},
        ),
        ValidationFinding(
            check_name="expression_similarity",
            validator_name="similarity_validator",
            passed=expression_pass,
            severity=ValidationSeverity.ERROR if expression_level == FailureLevel.HARD else ValidationSeverity.WARNING,
            message="normalized math-expression similarity stays below the configured threshold",
            reason_code=rc.SIMILARITY_EXPRESSION_TOO_HIGH.code,
            failure_level=expression_level or FailureLevel.SOFT,
            recommendation="Alter the equation structure or numeric parameters to reduce expression overlap."
            if not expression_pass
            else None,
            context={"score": round(best_expression[0], 4), "matched_source_item_id": best_expression[1]},
        ),
        ValidationFinding(
            check_name="solution_graph_similarity",
            validator_name="similarity_validator",
            passed=graph_pass,
            severity=ValidationSeverity.ERROR if graph_level == FailureLevel.HARD else ValidationSeverity.WARNING,
            message="solution-graph fingerprint similarity stays below the configured threshold",
            reason_code=rc.SIMILARITY_SOLUTION_GRAPH_TOO_HIGH.code,
            failure_level=graph_level or FailureLevel.SOFT,
            recommendation="Change the reasoning route or discard the item if it mirrors an existing solution graph."
            if not graph_pass
            else None,
            context={"score": round(best_graph[0], 4), "matched_source_item_id": best_graph[1]},
        ),
    ]

    return ValidatorSectionResult(
        validator_name="similarity_validator",
        findings=findings,
        metrics={
            "surface_similarity": round(best_surface[0], 4),
            "expression_similarity": round(best_expression[0], 4),
            "solution_graph_similarity": round(best_graph[0], 4),
        },
    )
