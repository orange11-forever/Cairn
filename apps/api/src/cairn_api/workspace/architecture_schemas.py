"""The model's bounded architecture graph, validated before it reaches the UI."""

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from cairn_api.knowledge.answer_provider import ProviderAnswer
from cairn_api.workspace.schemas import WorkspaceModel

NodeId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,39}$")]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class ArchitectureNode(WorkspaceModel):
    id: NodeId
    label: Label
    description: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=400)]
    citation_ids: list[str] = Field(min_length=1, max_length=6)


class ArchitectureEdge(WorkspaceModel):
    source: NodeId
    target: NodeId
    label: Label
    basis: Literal["direct", "inferred"]
    citation_ids: list[str] = Field(min_length=1, max_length=6)


class ArchitectureGraph(WorkspaceModel):
    nodes: list[ArchitectureNode] = Field(max_length=12)
    edges: list[ArchitectureEdge] = Field(max_length=20)

    @model_validator(mode="after")
    def valid_graph(self) -> "ArchitectureGraph":
        ids = {node.id for node in self.nodes}
        if len(ids) != len(self.nodes):
            raise ValueError("architecture node ids must be unique")
        pairs: set[tuple[str, str]] = set()
        for edge in self.edges:
            if edge.source not in ids or edge.target not in ids or edge.source == edge.target:
                raise ValueError("architecture edge must connect two distinct known nodes")
            pair = (edge.source, edge.target)
            if pair in pairs:
                raise ValueError("combine relationships for the same directed node pair")
            pairs.add(pair)
        for item in [*self.nodes, *self.edges]:
            if len(item.citation_ids) != len(set(item.citation_ids)):
                raise ValueError("architecture citation ids must be unique")
        return self


class ProviderArchitecture(ProviderAnswer):
    graph: ArchitectureGraph

    @model_validator(mode="after")
    def valid_graph_status(self) -> "ProviderArchitecture":
        if self.status == "answered" and not self.graph.nodes:
            raise ValueError("an architecture answer needs at least one supported node")
        if self.status == "insufficient_evidence" and (self.graph.nodes or self.graph.edges):
            raise ValueError("insufficient evidence cannot include a graph")
        return self

    def check_sources(self, known: set[str]) -> None:
        for item in [*self.paragraphs, *self.graph.nodes, *self.graph.edges]:
            if not set(item.citation_ids) <= known:
                raise ValueError("architecture cites a source outside the supplied snapshot")
