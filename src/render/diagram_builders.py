"""TikZ diagram builders for exam rendering."""

from __future__ import annotations

from typing import Callable

from src.core.schemas import ValidatedItem


def infer_diagram_tag(item: ValidatedItem) -> str | None:
    """Infer a diagram family from the blueprint/domain metadata."""
    blueprint = item.solved.draft.blueprint
    tags = {tag.lower() for tag in blueprint.skill_tags}
    objective = blueprint.objective.lower()
    if {"graph", "function", "trigonometry", "derivative", "integral"} & tags or "그래프" in objective:
        return "function_graph"
    if {"coordinate", "area", "slope"} & tags:
        return "coordinate_geometry"
    if {"triangle", "circle", "angle"} & tags:
        return "circle_triangle"
    if {"counting", "probability", "conditional_probability", "random_variable"} & tags:
        return "probability_cards"
    if {"distribution", "sampling", "mean", "statistic"} & tags or "표" in objective:
        return "probability_table"
    if {"sequence", "series", "recurrence"} & tags:
        return "sequence_array"
    return None


def build_function_graph() -> str:
    return r"""
\begin{tikzpicture}[scale=0.55]
  \draw[->, thick] (-2.5,0) -- (2.8,0) node[right] {$x$};
  \draw[->, thick] (0,-1.8) -- (0,2.8) node[above] {$y$};
  \draw[smooth, samples=80, domain=-2:2.2, blue!70!black, thick] plot (\x,{0.35*\x*\x - 0.7});
  \draw[dashed, gray] (1.4,0) -- (1.4,1.2);
\end{tikzpicture}
""".strip()


def build_coordinate_geometry() -> str:
    return r"""
\begin{tikzpicture}[scale=0.55]
  \draw[step=1cm, gray!25, very thin] (-0.2,-0.2) grid (4.2,3.2);
  \draw[->, thick] (-0.2,0) -- (4.4,0) node[right] {$x$};
  \draw[->, thick] (0,-0.2) -- (0,3.4) node[above] {$y$};
  \draw[thick, teal!70!black] (0.5,0.7) -- (3.5,2.8) -- (2.7,0.5) -- cycle;
  \filldraw (0.5,0.7) circle (1.6pt) (3.5,2.8) circle (1.6pt) (2.7,0.5) circle (1.6pt);
\end{tikzpicture}
""".strip()


def build_circle_triangle() -> str:
    return r"""
\begin{tikzpicture}[scale=0.65]
  \draw[thick, orange!80!black] (0,0) circle (1.6);
  \draw[thick, orange!80!black] (90:1.6) -- (210:1.6) -- (330:1.6) -- cycle;
  \filldraw (90:1.6) circle (1.4pt) (210:1.6) circle (1.4pt) (330:1.6) circle (1.4pt);
\end{tikzpicture}
""".strip()


def build_probability_cards() -> str:
    return r"""
\begin{tikzpicture}[scale=0.8]
  \draw[rounded corners=2pt, thick] (0,0) rectangle (1,1.4);
  \draw[rounded corners=2pt, thick] (1.3,0) rectangle (2.3,1.4);
  \draw[rounded corners=2pt, thick] (2.6,0) rectangle (3.6,1.4);
  \node at (0.5,0.7) {$A$};
  \node at (1.8,0.7) {$B$};
  \node at (3.1,0.7) {$C$};
  \draw[rounded corners=2pt, thick, fill=gray!10] (4.1,0.15) rectangle (6.4,1.25);
  \node at (5.25,0.7) {$P(A \mid B)$};
\end{tikzpicture}
""".strip()


def build_probability_table() -> str:
    return r"""
\begin{tikzpicture}[scale=0.82]
  \draw[thick] (0,0) rectangle (4.8,2.8);
  \draw[thick] (1.2,0) -- (1.2,2.8);
  \draw[thick] (0,0.9) -- (4.8,0.9);
  \draw[thick] (0,1.8) -- (4.8,1.8);
  \node at (0.6,2.3) {$X$};
  \node at (2.0,2.3) {$0$};
  \node at (3.0,2.3) {$1$};
  \node at (4.0,2.3) {$2$};
  \node at (0.6,1.35) {$P$};
  \node at (2.0,1.35) {$p$};
  \node at (3.0,1.35) {$q$};
  \node at (4.0,1.35) {$1-p-q$};
\end{tikzpicture}
""".strip()


def build_sequence_array() -> str:
    return r"""
\begin{tikzpicture}[scale=0.78]
  \foreach \x/\v in {0/$a_1$,1.3/$a_2$,2.6/$a_3$,3.9/$a_4$} {
    \draw[rounded corners=2pt, thick] (\x,0) rectangle (\x+1,0.8);
    \node at (\x+0.5,0.4) {\v};
  }
  \draw[->, thick] (4.95,0.4) -- (6.0,0.4);
  \node[right] at (6.0,0.4) {$\cdots$};
\end{tikzpicture}
""".strip()


DIAGRAM_BUILDERS: dict[str, Callable[[], str]] = {
    "function_graph": build_function_graph,
    "coordinate_geometry": build_coordinate_geometry,
    "circle_triangle": build_circle_triangle,
    "probability_cards": build_probability_cards,
    "probability_table": build_probability_table,
    "sequence_array": build_sequence_array,
    "area_under_curve": build_function_graph,
    "sign_chart": build_function_graph,
    "number_line": build_sequence_array,
}


def build_diagram_tex(tag: str | None) -> str | None:
    """Build a diagram snippet for a supported diagram tag."""
    if tag is None:
        return None
    builder = DIAGRAM_BUILDERS.get(tag)
    if builder is None:
        return None
    return builder()
