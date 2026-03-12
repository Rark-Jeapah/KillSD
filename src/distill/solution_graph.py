"""Solution graph primitives for distilled math items."""

from __future__ import annotations

from enum import Enum
from hashlib import sha1

from pydantic import Field, model_validator

from src.core.schemas import StrictModel
from src.distill.item_card_schema import ManualSourceItem


class SolutionNodeKind(str, Enum):
    """Supported node categories inside a solution graph."""

    GIVEN = "given"
    TRANSFORM = "transform"
    INFERENCE = "inference"
    COMPUTE = "compute"
    CHECK = "check"
    RESULT = "result"


class SolutionNode(StrictModel):
    """Single node in a solution graph."""

    node_id: str
    label: str
    kind: SolutionNodeKind
    content: str
    technique: str
    dependencies: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    difficulty_delta: int = 0


class SolutionEdge(StrictModel):
    """Directed dependency between solution nodes."""

    from_node: str
    to_node: str
    relation: str = "depends_on"


class SolutionGraph(StrictModel):
    """Graph representation of a solved source item."""

    graph_id: str
    source_item_id: str
    nodes: list[SolutionNode]
    edges: list[SolutionEdge]
    final_answer: str
    diagram_tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_graph(self) -> "SolutionGraph":
        """Ensure all edges point to known node ids."""
        node_ids = {node.node_id for node in self.nodes}
        for edge in self.edges:
            if edge.from_node not in node_ids or edge.to_node not in node_ids:
                raise ValueError("All edges must reference known node ids")
        return self


class SolutionGraphError(Exception):
    """Raised when a source item cannot be converted into a graph."""


def build_solution_graph(source_item: ManualSourceItem) -> SolutionGraph:
    """Convert manual solution steps into a dependency graph."""
    nodes: list[SolutionNode] = []
    edges: list[SolutionEdge] = []
    known_kinds = {kind.value for kind in SolutionNodeKind}
    previous_step_id: str | None = None

    for step in source_item.solution_steps:
        if step.kind not in known_kinds:
            raise SolutionGraphError(f"Unsupported solution step kind: {step.kind}")
        nodes.append(
            SolutionNode(
                node_id=step.step_id,
                label=step.label,
                kind=SolutionNodeKind(step.kind),
                content=step.content,
                technique=step.technique,
                dependencies=step.dependencies,
                outputs=step.outputs,
                difficulty_delta=step.difficulty_delta,
            )
        )
        if step.dependencies:
            for dependency in step.dependencies:
                edges.append(SolutionEdge(from_node=dependency, to_node=step.step_id))
        elif previous_step_id is not None:
            edges.append(
                SolutionEdge(
                    from_node=previous_step_id,
                    to_node=step.step_id,
                    relation="sequence",
                )
            )
        previous_step_id = step.step_id

    graph_seed = f"{source_item.source_item_id}:{source_item.answer}:{len(nodes)}"
    graph_id = f"sg-{sha1(graph_seed.encode('utf-8')).hexdigest()[:12]}"
    return SolutionGraph(
        graph_id=graph_id,
        source_item_id=source_item.source_item_id,
        nodes=nodes,
        edges=edges,
        final_answer=source_item.answer,
        diagram_tags=source_item.diagram_tags,
    )
